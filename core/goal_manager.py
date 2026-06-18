"""Autonomous goal loop — decomposition, checkpoints, context management.

Decomposes complex goals into ordered checkpoints, persists progress
across sessions, summarizes context to avoid token overflow, and
self-evaluates to revise plans when needed.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.company import ALL_COMPANIES, current_company_id
from core.config import GoalsConfig
from core.database import Database

logger = logging.getLogger(__name__)

# The founder loop (tmp/founder-vs-elophanto-audit-2026-06-18.md Phase 1).
# Every goal + checkpoint is tagged with where in this loop it sits so the
# decompose prompt can enforce validate-before-build and the mind/weekly
# review can reason about stage. 'unknown' is the pre-Stage-0 default.
GOAL_STAGES: tuple[str, ...] = (
    "scan",
    "validate",
    "build",
    "launch",
    "acquire",
    "operate",
    "scale",
)

# Stages that must NOT run before validation has succeeded. `operate`
# (support/billing/books) is intentionally excluded — it can legitimately
# precede a paying-party signal (e.g. setting up the inbox). The hard gate
# (GoalManager.validate_gate_reason + goal_runner) blocks these when the goal
# still has an unfinished `validate` checkpoint.
POST_VALIDATION_STAGES: frozenset[str] = frozenset(
    {"build", "launch", "acquire", "scale"}
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Checkpoint:
    """A single checkpoint within a goal's plan."""

    goal_id: str
    order: int
    title: str
    description: str
    success_criteria: str = ""
    status: str = "pending"  # pending | active | completed | failed | skipped
    result_summary: str | None = None
    attempts: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    # Founder-loop stage (Stage 0, 2026-06-18). One of GOAL_STAGES, or
    # 'unknown' for pre-migration / legacy checkpoints. Lets the decompose
    # prompt mark which checkpoint is the validate gate.
    stage: str = "unknown"


@dataclass
class Goal:
    """A persistent, multi-checkpoint goal."""

    goal_id: str
    session_id: str | None
    goal: str
    status: str = "planning"  # planning|active|paused|completed|failed|cancelled
    plan: list[dict[str, Any]] = field(default_factory=list)
    context_summary: str = ""
    current_checkpoint: int = 0
    total_checkpoints: int = 0
    attempts: int = 0
    max_attempts: int = 3
    llm_calls_used: int = 0
    cost_usd: float = 0.0
    created_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None
    # Optional FK to ``missions.mission_id``. None for unparented
    # goals (legacy + one-off operator requests). When set, the
    # goal-completion hook bumps the mission's momentum. See
    # docs/75-AUTONOMOUS-MIND-V2.md §Phase 2.
    mission_id: str | None = None
    # Optional role assignment (ABE Phase 2, docs/76-ABE-FRAMEWORK.md).
    # When set, the autonomous mind biases candidate selection so this
    # goal is preferred during cycles where the active role matches.
    # None = goal works for any role (the CEO default).
    assigned_to_role: str | None = None
    # Strategy-tactic metadata (ABE Phase 11). When this goal was created
    # from a strategy tactic by `company_plan_apply`, this dict carries
    # the tactic's per-row fields: strategy_id, tactic_id, priority,
    # channel, budget, expectedImpact, riskLevel, dependencies,
    # successMetrics, inspiredBy. Empty dict for non-strategy goals.
    tactic_metadata: dict[str, Any] = field(default_factory=dict)
    # ABE Phase 12 (Tier 1 #1, 2026-06-18). Company this goal
    # belongs to. Stamped from the contextvar at INSERT time; pre-
    # migration rows default to 'elophanto-self' via the schema.
    company_id: str = "elophanto-self"
    # Founder-doctrine Stage 0 (2026-06-18). Position in the founder loop
    # (one of GOAL_STAGES) and the measurable abandon-threshold written
    # before work starts. Unlike most fields these are set by the decompose
    # prompt (or the caller of create_goal) rather than inferred at runtime.
    # 'unknown'/None for pre-Stage-0 goals.
    stage: str = "unknown"
    kill_criterion: str | None = None


@dataclass
class EvaluationResult:
    """Result of a self-evaluation check."""

    on_track: bool
    revision_needed: bool
    reason: str
    suggested_changes: str | None = None


# ---------------------------------------------------------------------------
# LLM prompt templates
# ---------------------------------------------------------------------------

_DECOMPOSE_SYSTEM = """\
<goal_decomposition>
You are the goal planning subsystem. Given a user's goal, decompose it into
3-15 ordered checkpoints AND state the single condition that should make the
agent abandon the goal.

Each checkpoint must be:
- Concrete and actionable (produces a tangible result)
- Independently verifiable (clear, measurable success criteria)
- Sequenced logically (dependencies flow left-to-right)
- Tagged with the founder-loop STAGE it belongs to (see below)

FOUNDER-LOOP STAGES — tag every checkpoint with exactly one:
- scan      : choosing what to do; comparing options; research that picks a direction
- validate  : getting evidence a real outside party will PAY — a paid pre-order,
              signed LOI, paid pilot, or advertiser/sponsor/affiliate commitment
- build     : making the smallest thing that delivers the validated promise
- launch    : putting it in front of the first customers with tracked attribution
- acquire   : repeatable customer acquisition on ONE proven channel
- operate   : support, fulfilment, billing, books
- scale     : removing the next constraint once 1-6 are healthy

VALIDATE-FIRST GATE (the most important rule):
If the goal involves building, selling, launching, or growing anything, and
there is NO evidence yet that a paying party wants it, the FIRST checkpoint
MUST be a `validate` checkpoint whose success criteria is a signal of revenue
intent from a real outside party (e.g. ">=3 paid pre-orders at $X" or "2 signed
LOIs"). Do NOT make the first checkpoint generic research, and do NOT place any
`build` checkpoint before a `validate` checkpoint has produced that signal.
Research that does not end in a paying-party signal is procrastination.
(Pure-research, learning, or internal-tooling goals that have no customer may
legitimately have no validate stage — use `scan`/`build` and that is fine.)

KILL CRITERION:
State one measurable abandon-threshold, decided before work starts, with a
NUMBER and a DATE or VOLUME. Good: "If after 50 outreach messages over 14 days
fewer than 5 reply with buying intent, abandon." Bad: "If it doesn't work out."

Return ONLY a JSON object. No markdown, no explanation:
{
  "kill_criterion": "<measurable abandon-threshold with a number + date or volume>",
  "checkpoints": [
    {
      "order": <int starting at 1>,
      "title": "<short title, max 60 chars>",
      "description": "<what to do, 1-3 sentences>",
      "success_criteria": "<how to verify completion, objective and measurable>",
      "stage": "<one of: scan|validate|build|launch|acquire|operate|scale>"
    }
  ]
}

Guidelines:
- Front-load risky or uncertain steps; the validate gate above overrides the
  old "research first" habit.
- Keep each checkpoint achievable in 5-30 tool calls.
- Avoid subjective criteria ("good quality") — use measurable ones ("3+ items found").
</goal_decomposition>"""

_SUMMARIZE_SYSTEM = """\
Summarize what was accomplished in this checkpoint execution. Be factual,
concise, and preserve key data points (names, URLs, numbers, decisions made).
Maximum 200 words. Write as numbered points matching checkpoint order."""

_EVALUATE_SYSTEM = """\
<goal_evaluation>
You are evaluating progress on a long-running goal. Given the goal, plan,
completed checkpoints, and context summary, determine:
1. Is the goal still on track?
2. Does the remaining plan need revision based on what was learned?

Return ONLY a JSON object:
{
  "on_track": true/false,
  "revision_needed": true/false,
  "reason": "<brief explanation>",
  "suggested_changes": "<what to change, or null>"
}
</goal_evaluation>"""

_REVISE_SYSTEM = """\
<goal_revision>
You are revising the remaining checkpoints for a goal. The completed
checkpoints are fixed — only generate replacement checkpoints for the
remaining (uncompleted) portion of the plan.

Return ONLY a JSON array of new checkpoint objects, each with:
{"order": <int>, "title": "...", "description": "...",
 "success_criteria": "...", "stage": "scan|validate|build|launch|acquire|operate|scale"}
Start ordering from the next checkpoint number after the last completed one.
Honor the validate-first rule: do not introduce a `build` checkpoint if no
`validate` checkpoint has yet produced a paying-party signal.
</goal_revision>"""


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def _loads_json_lenient(raw: str) -> Any:
    """Best-effort JSON parse tolerant of markdown fences + surrounding prose.

    Returns the parsed value (object or array), or None if nothing
    parseable is found. The decompose prompt emits an object; the
    revise prompt (and pre-Stage-0 decompose) emit a bare array — both
    must round-trip. Tries a clean parse first, then falls back to the
    widest ``{...}`` and then ``[...]`` substring so a trailing comma
    or stray prose line doesn't discard the whole plan.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text[3:]
        if text[:4].lower() == "json":
            text = text[4:]
        if text.rstrip().endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Object first (Stage-0 decompose shape), then array (revise shape).
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


# ---------------------------------------------------------------------------
# GoalManager
# ---------------------------------------------------------------------------


class GoalManager:
    """Orchestrates goal decomposition, checkpoint tracking, and context management."""

    def __init__(self, db: Database, router: Any, config: GoalsConfig) -> None:
        self._db = db
        self._router = router
        self._config = config
        # Optional callback fired when a goal flips to "completed". The
        # autonomous mind registers a hook so finishing a goal kicks the
        # next dream cycle immediately instead of waiting up to several
        # hours for the next scheduled wakeup. Kept as a list to support
        # multiple subscribers (e.g. analytics + mind).
        # Signature: async def hook(goal_id: str) -> None
        self._on_goal_completed: list[Any] = []

    def add_completion_hook(self, hook: Any) -> None:
        """Register an async callback fired after a goal flips to
        'completed'. Hooks must be ``async def hook(goal_id: str)`` and
        must not raise — failures are logged and swallowed so one bad
        subscriber cannot break the goal lifecycle.
        """
        self._on_goal_completed.append(hook)

    async def _fire_completion_hooks(self, goal_id: str) -> None:
        """Best-effort fan-out. Hook exceptions are logged and dropped
        so a downstream consumer cannot affect goal persistence."""
        for hook in self._on_goal_completed:
            try:
                await hook(goal_id)
            except Exception as e:
                logger.warning("Goal completion hook failed: %s", e)

    # --- Goal lifecycle ---

    async def create_goal(
        self,
        goal: str,
        session_id: str | None = None,
        *,
        mission_id: str | None = None,
        assigned_to_role: str | None = None,
        tactic_metadata: dict[str, Any] | None = None,
        stage: str = "unknown",
        kill_criterion: str | None = None,
    ) -> Goal:
        """Create a new goal and persist it.

        ``mission_id`` optionally parents the goal under a mission
        (Phase 2). Unparented goals (mission_id=None) are still
        first-class — the missions tier is opt-in.

        ``assigned_to_role`` (ABE Phase 2) optionally scopes the goal
        to a role persona — e.g. ``assigned_to_role='sales'``. The
        autonomous mind biases candidate selection accordingly. Null
        means the goal works for any role (CEO default).

        ``stage`` + ``kill_criterion`` (founder-doctrine Stage 0,
        2026-06-18) let a caller stamp the founder-loop stage and the
        abandon-threshold up front. Both are usually left at the
        defaults here and filled in by ``decompose`` from the LLM
        plan; an operator/mind that already knows them can pass them
        in and ``decompose`` will not overwrite a caller-set
        kill_criterion.

        Company is captured from the contextvar at create time and
        stored on the Goal object so subsequent ``_persist_goal`` calls
        (from checkpoint advances etc.) preserve it even if the
        contextvar later flips. Before Tier 1 #1 (2026-06-18) this
        relied on the schema DEFAULT, which silently routed every
        create into 'elophanto-self' regardless of the operator's
        active company.
        """
        now = datetime.now(UTC).isoformat()
        g = Goal(
            goal_id=str(uuid.uuid4())[:12],
            session_id=session_id,
            goal=goal,
            status="planning",
            max_attempts=self._config.max_goal_attempts,
            created_at=now,
            updated_at=now,
            mission_id=mission_id,
            assigned_to_role=assigned_to_role,
            tactic_metadata=dict(tactic_metadata or {}),
            company_id=current_company_id(),
            stage=stage or "unknown",
            kill_criterion=(kill_criterion or None),
        )
        await self._persist_goal(g)
        return g

    async def get_goal(
        self, goal_id: str, *, company_id: str | None = None
    ) -> Goal | None:
        """Fetch a goal by ID.

        Defaults to the contextvar company — passing a known
        goal_id from another tenant returns None instead of leaking
        the row. Pass ``company_id=ALL_COMPANIES`` to bypass the
        filter (admin / diagnostics only).
        """
        scope = current_company_id() if company_id is None else company_id
        if scope == ALL_COMPANIES:
            rows = await self._db.execute(
                "SELECT * FROM goals WHERE goal_id = ?", (goal_id,)
            )
        else:
            rows = await self._db.execute(
                "SELECT * FROM goals WHERE goal_id = ? AND company_id = ?",
                (goal_id, scope),
            )
        if not rows:
            return None
        return self._row_to_goal(rows[0])

    async def get_active_goal(
        self, session_id: str, *, company_id: str | None = None
    ) -> Goal | None:
        """Get the active goal for a session (if any).

        Filters by the contextvar company so a stale session shared
        across companies (Tier 2 #4 — sessions UNIQUE doesn't include
        company_id yet) doesn't return another company's active goal.
        """
        scope = current_company_id() if company_id is None else company_id
        if scope == ALL_COMPANIES:
            rows = await self._db.execute(
                "SELECT * FROM goals WHERE session_id = ? "
                "AND status IN ('planning', 'active') "
                "ORDER BY updated_at DESC LIMIT 1",
                (session_id,),
            )
        else:
            rows = await self._db.execute(
                "SELECT * FROM goals WHERE session_id = ? AND company_id = ? "
                "AND status IN ('planning', 'active') "
                "ORDER BY updated_at DESC LIMIT 1",
                (session_id, scope),
            )
        if not rows:
            return None
        return self._row_to_goal(rows[0])

    async def list_goals(
        self,
        status: str | None = None,
        limit: int = 20,
        *,
        company_id: str | None = None,
    ) -> list[Goal]:
        """List goals, optionally filtered by status.

        Defaults to the contextvar company. Pass ``company_id=
        ALL_COMPANIES`` to list across every tenant (admin only).
        """
        scope = current_company_id() if company_id is None else company_id
        clauses: list[str] = []
        params: list[Any] = []
        if scope != ALL_COMPANIES:
            clauses.append("company_id = ?")
            params.append(scope)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where_sql = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        params.append(limit)
        rows = await self._db.execute(
            f"SELECT * FROM goals {where_sql}" "ORDER BY updated_at DESC LIMIT ?",
            tuple(params),
        )
        return [self._row_to_goal(r) for r in rows]

    async def cancel_goal(self, goal_id: str) -> bool:
        """Cancel a goal."""
        return await self._update_status(goal_id, "cancelled")

    async def delete_goal(self, goal_id: str) -> bool:
        """Permanently delete a goal and its checkpoints."""
        try:
            await self._db.execute_insert(
                "DELETE FROM goal_checkpoints WHERE goal_id = ?", (goal_id,)
            )
            await self._db.execute_insert(
                "DELETE FROM goals WHERE goal_id = ?", (goal_id,)
            )
            return True
        except Exception:
            return False

    async def delete_all_goals(self) -> int:
        """Permanently delete ALL goals and checkpoints. Returns count deleted."""
        try:
            rows = await self._db.execute("SELECT goal_id FROM goals")
            count = len(rows)
            await self._db.execute_insert("DELETE FROM goal_checkpoints")
            await self._db.execute_insert("DELETE FROM goals")
            return count
        except Exception:
            return 0

    async def pause_goal(self, goal_id: str) -> bool:
        """Pause an active goal."""
        return await self._update_status(goal_id, "paused", from_statuses=("active",))

    async def resume_goal(self, goal_id: str) -> bool:
        """Resume a paused goal."""
        return await self._update_status(goal_id, "active", from_statuses=("paused",))

    # --- Decomposition ---

    async def decompose(self, goal: Goal) -> list[Checkpoint]:
        """Use LLM to decompose a goal into ordered checkpoints."""
        response = await self._router.complete(
            messages=[
                {"role": "system", "content": _DECOMPOSE_SYSTEM},
                {
                    "role": "user",
                    "content": f"Decompose this goal into checkpoints: {goal.goal}",
                },
            ],
            task_type="simple",
            temperature=0.3,
        )
        goal.llm_calls_used += 1

        raw = response.content or "[]"
        checkpoints = self._parse_checkpoint_json(raw, goal.goal_id)
        if not checkpoints:
            logger.warning(
                "Decomposition returned no checkpoints for goal %s", goal.goal_id
            )
            return []

        # Cap at max
        checkpoints = checkpoints[: self._config.max_checkpoints]

        # Persist checkpoints
        for cp in checkpoints:
            await self._db.execute_insert(
                "INSERT INTO goal_checkpoints "
                "(goal_id, checkpoint_order, title, description, success_criteria, "
                "stage) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    cp.goal_id,
                    cp.order,
                    cp.title,
                    cp.description,
                    cp.success_criteria,
                    cp.stage,
                ),
            )

        # Update goal. Founder-doctrine Stage 0: the goal's stage tracks the
        # first checkpoint (where the goal currently sits in the loop), and
        # the kill_criterion comes from the decompose plan unless the caller
        # already set one (operator/mind providing it up front wins).
        goal.status = "active"
        goal.total_checkpoints = len(checkpoints)
        goal.current_checkpoint = 1
        goal.stage = checkpoints[0].stage if checkpoints else (goal.stage or "unknown")
        if not goal.kill_criterion:
            goal.kill_criterion = self._extract_kill_criterion(raw)
        goal.plan = [
            {
                "order": c.order,
                "title": c.title,
                "description": c.description,
                "success_criteria": c.success_criteria,
                "stage": c.stage,
            }
            for c in checkpoints
        ]
        goal.updated_at = datetime.now(UTC).isoformat()
        await self._persist_goal(goal)

        return checkpoints

    async def revise_plan(self, goal: Goal, reason: str) -> list[Checkpoint]:
        """Revise remaining checkpoints based on new information."""
        completed = await self.get_checkpoints(goal.goal_id, status="completed")
        completed_summary = "\n".join(
            f"[{c.order}] {c.title} — {c.result_summary or 'done'}" for c in completed
        )

        prompt = (
            f"Goal: {goal.goal}\n"
            f"Completed checkpoints:\n{completed_summary}\n"
            f"Context: {goal.context_summary}\n"
            f"Reason for revision: {reason}\n\n"
            f"Generate revised remaining checkpoints starting from order {goal.current_checkpoint}."
        )

        response = await self._router.complete(
            messages=[
                {"role": "system", "content": _REVISE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            task_type="simple",
            temperature=0.3,
        )
        goal.llm_calls_used += 1

        # Pick start_order from the LIVE DB state, not goal.current_checkpoint —
        # the goal's in-memory counter can lag behind completed rows after
        # crash/recovery. The previous version used MAX(order) WHERE
        # status='completed', but that ignored ``active`` rows (the
        # checkpoint the agent is currently working on), causing
        # UNIQUE(goal_id, checkpoint_order) collisions during revise.
        # Production 2026-06-01: 6 active + 20 pending + 35 completed
        # → revise crashed because the LLM proposed a new checkpoint
        # at order N while an active row already held that slot.
        #
        # The query must match the rows that will SURVIVE the DELETE
        # below — anything we're about to drop shouldn't constrain
        # the new start_order. Surviving = completed + active.
        # Gaps in the order sequence are fine — readers sort by
        # ``checkpoint_order`` and don't assume contiguity.
        rows = await self._db.execute(
            "SELECT MAX(checkpoint_order) AS max_ord FROM goal_checkpoints "
            "WHERE goal_id = ? AND status IN ('completed', 'active')",
            (goal.goal_id,),
        )
        max_surviving = 0
        if rows:
            max_ord = rows[0]["max_ord"]
            max_surviving = int(max_ord) if max_ord is not None else 0

        new_checkpoints = self._parse_checkpoint_json(
            response.content or "[]", goal.goal_id, start_order=max_surviving + 1
        )
        if not new_checkpoints:
            return []

        # Delete revisable checkpoints — anything the operator/agent
        # would expect a revision to replace. ``active`` is preserved
        # because the agent may be mid-cycle on it; yanking the row
        # from under itself causes the executing turn to lose its
        # bookkeeping. ``completed`` is preserved because those are
        # facts on the ground, not plans. Everything else (pending,
        # failed, skipped) is replanned work.
        await self._db.execute(
            "DELETE FROM goal_checkpoints WHERE goal_id = ? "
            "AND status IN ('pending', 'failed', 'skipped')",
            (goal.goal_id,),
        )

        # Insert new ones
        for cp in new_checkpoints:
            await self._db.execute_insert(
                "INSERT INTO goal_checkpoints "
                "(goal_id, checkpoint_order, title, description, success_criteria, "
                "stage) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    cp.goal_id,
                    cp.order,
                    cp.title,
                    cp.description,
                    cp.success_criteria,
                    cp.stage,
                ),
            )

        # Update goal
        all_cps = await self.get_checkpoints(goal.goal_id)
        goal.total_checkpoints = len(all_cps)
        goal.plan = [
            {
                "order": c.order,
                "title": c.title,
                "description": c.description,
                "success_criteria": c.success_criteria,
                "stage": c.stage,
            }
            for c in all_cps
        ]
        goal.updated_at = datetime.now(UTC).isoformat()
        await self._persist_goal(goal)

        return new_checkpoints

    # --- Checkpoint tracking ---

    async def get_checkpoints(
        self, goal_id: str, status: str | None = None
    ) -> list[Checkpoint]:
        """Get all checkpoints for a goal, optionally filtered by status."""
        if status:
            rows = await self._db.execute(
                "SELECT * FROM goal_checkpoints WHERE goal_id = ? AND status = ? "
                "ORDER BY checkpoint_order",
                (goal_id, status),
            )
        else:
            rows = await self._db.execute(
                "SELECT * FROM goal_checkpoints WHERE goal_id = ? ORDER BY checkpoint_order",
                (goal_id,),
            )
        return [self._row_to_checkpoint(r) for r in rows]

    async def get_next_checkpoint(self, goal_id: str) -> Checkpoint | None:
        """Get the next pending checkpoint."""
        rows = await self._db.execute(
            "SELECT * FROM goal_checkpoints WHERE goal_id = ? AND status = 'pending' "
            "ORDER BY checkpoint_order LIMIT 1",
            (goal_id,),
        )
        if not rows:
            return None
        return self._row_to_checkpoint(rows[0])

    async def validate_gate_reason(
        self, goal_id: str, checkpoint: Checkpoint
    ) -> str | None:
        """Hard validate-first gate (founder-doctrine Stage 0, #2 hardening).

        Returns a human-readable reason if executing ``checkpoint`` would
        violate validate-before-build, else None. The gate fires when a
        post-validation checkpoint (build / launch / acquire / scale) is about
        to run while the goal still has a ``validate`` checkpoint that has NOT
        completed — i.e. pending, active, failed, or skipped. A failed or
        skipped validate means no paying-party signal was obtained, and
        building on that is the exact silent-failure mode the founder audit
        flagged (tmp/founder-vs-elophanto-audit-2026-06-18.md §1.2.4).

        Goals with no ``validate`` checkpoint at all (pure research, learning,
        internal tooling) never trip the gate — the decompose prompt is
        allowed to omit a validate stage for those, so absence is not a
        violation. This is the code-level backstop for when the LLM ignores
        the decompose prompt's validate-first instruction, or a ``revise``
        re-introduces a build step after validation failed.
        """
        if (checkpoint.stage or "unknown") not in POST_VALIDATION_STAGES:
            return None
        rows = await self._db.execute(
            "SELECT COUNT(*) AS c FROM goal_checkpoints "
            "WHERE goal_id = ? AND stage = 'validate' AND status != 'completed'",
            (goal_id,),
        )
        incomplete = int(rows[0]["c"]) if rows else 0
        if incomplete <= 0:
            return None
        return (
            f"validate-first gate: checkpoint #{checkpoint.order} "
            f"('{checkpoint.title}', stage={checkpoint.stage}) cannot run while "
            f"{incomplete} validate checkpoint(s) are unfinished — no paying-party "
            f"signal yet. Validate before build; pivot or kill if validation failed."
        )

    async def mark_checkpoint_active(self, goal_id: str, order: int) -> None:
        """Mark a checkpoint as actively being worked on."""
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE goal_checkpoints SET status = 'active', started_at = ?, "
            "attempts = attempts + 1 WHERE goal_id = ? AND checkpoint_order = ?",
            (now, goal_id, order),
        )

    async def mark_checkpoint_complete(
        self, goal_id: str, order: int, summary: str
    ) -> None:
        """Mark a checkpoint as completed and advance the goal.

        Uses ALL_COMPANIES on the internal goal fetch so a context
        flip during a long-running goal cannot leave the DB in a
        half-updated state (checkpoint marked complete but goal not
        advanced). The goal runner already vouches for the goal_id —
        soft-guard scoping belongs on the operator-facing surface.
        """
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE goal_checkpoints SET status = 'completed', result_summary = ?, "
            "completed_at = ? WHERE goal_id = ? AND checkpoint_order = ?",
            (summary, now, goal_id, order),
        )

        goal = await self.get_goal(goal_id, company_id=ALL_COMPANIES)
        if not goal:
            return

        next_cp = await self.get_next_checkpoint(goal_id)
        just_completed = False
        if next_cp:
            goal.current_checkpoint = next_cp.order
        else:
            # No pending checkpoint — but that doesn't necessarily mean
            # the goal is done. It can also mean an earlier revise_plan
            # crashed after deleting pending rows but before inserting
            # the replacements (observed 2026-06-01: legal-pdf goal had
            # 5 of 15 checkpoints completed, 0 pending, and got auto-
            # flipped to status='completed' purely because no pending
            # row remained). Source-of-truth check: count completed
            # rows vs the goal's declared total. If the count falls
            # short, the goal is STALLED — there's planning work
            # missing, not work finished.
            completed_count_rows = await self._db.execute(
                "SELECT COUNT(*) AS c FROM goal_checkpoints "
                "WHERE goal_id = ? AND status = 'completed'",
                (goal_id,),
            )
            completed_count = (
                int(completed_count_rows[0]["c"]) if completed_count_rows else 0
            )
            if completed_count >= goal.total_checkpoints:
                goal.status = "completed"
                goal.completed_at = now
                just_completed = True
            else:
                # Stalled: planning was lost / interrupted. Leave status
                # 'active' (or whatever it was) so the goal stays visible
                # in the sidebar — completed gets filtered out. Log the
                # diagnostic so operators reading the log see WHY the
                # goal isn't progressing; the next arbiter cycle's
                # candidate generators can pick this up and propose a
                # revise via the "stuck planning" detector.
                logger.warning(
                    "goal %s: no pending checkpoints but %d/%d completed "
                    "— NOT marking completed (likely revise_plan crash, "
                    "see core/goal_manager.py:revise_plan). Goal will "
                    "stay active until revised.",
                    goal_id[:8],
                    completed_count,
                    goal.total_checkpoints,
                )

        goal.updated_at = now
        await self._persist_goal(goal)

        # Fire completion hooks AFTER persistence — subscribers can
        # safely re-query DB state. The autonomous mind uses this to
        # interrupt its sleep and start dreaming the next goal
        # immediately, closing the multi-hour latency window between
        # "goal finished" and "next dream cycle wakes up".
        if just_completed:
            await self._fire_completion_hooks(goal_id)

    async def mark_checkpoint_failed(
        self, goal_id: str, order: int, error: str
    ) -> None:
        """Mark a checkpoint as failed."""
        now = datetime.now(UTC).isoformat()

        # Check attempts
        rows = await self._db.execute(
            "SELECT attempts FROM goal_checkpoints WHERE goal_id = ? AND checkpoint_order = ?",
            (goal_id, order),
        )
        attempts = rows[0]["attempts"] if rows else 0

        if attempts >= self._config.max_checkpoint_attempts:
            # Too many failures — pause the goal
            await self._db.execute(
                "UPDATE goal_checkpoints SET status = 'failed', result_summary = ? "
                "WHERE goal_id = ? AND checkpoint_order = ?",
                (f"Failed after {attempts} attempts: {error}", goal_id, order),
            )
            # ALL_COMPANIES on internal fetch — see mark_checkpoint_complete
            # for rationale (avoid half-updated state on context flip).
            goal = await self.get_goal(goal_id, company_id=ALL_COMPANIES)
            if goal:
                goal.status = "paused"
                goal.updated_at = now
                await self._persist_goal(goal)
        else:
            # Reset to pending for retry
            await self._db.execute(
                "UPDATE goal_checkpoints SET status = 'pending' "
                "WHERE goal_id = ? AND checkpoint_order = ?",
                (goal_id, order),
            )

    # --- Context management ---

    async def summarize_context(
        self, goal: Goal, recent_messages: list[dict[str, Any]]
    ) -> str:
        """Compress recent conversation into a rolling context summary."""
        # Extract text content from messages
        text_parts: list[str] = []
        for msg in recent_messages[-20:]:  # Last 20 messages max
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                text_parts.append(f"{role}: {content[:500]}")

        if not text_parts:
            return goal.context_summary

        conversation_text = "\n".join(text_parts)
        prompt = (
            f"Goal: {goal.goal}\n"
            f"Previous context:\n{goal.context_summary}\n\n"
            f"New checkpoint conversation:\n{conversation_text}\n\n"
            f"Summarize the full progress so far."
        )

        response = await self._router.complete(
            messages=[
                {"role": "system", "content": _SUMMARIZE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            task_type="simple",
            temperature=0.2,
        )
        goal.llm_calls_used += 1

        summary = response.content or goal.context_summary
        # Truncate if too long
        max_chars = self._config.context_summary_max_tokens * 4  # rough char estimate
        if len(summary) > max_chars:
            summary = summary[:max_chars]

        goal.context_summary = summary
        goal.updated_at = datetime.now(UTC).isoformat()
        await self._persist_goal(goal)

        return summary

    async def build_goal_context(self, goal_id: str) -> str:
        """Build XML context block for injection into the system prompt."""
        goal = await self.get_goal(goal_id)
        if not goal:
            return ""

        checkpoints = await self.get_checkpoints(goal_id)
        completed = [c for c in checkpoints if c.status == "completed"]
        remaining = [c for c in checkpoints if c.status in ("pending", "active")]
        current = next(
            (c for c in checkpoints if c.status in ("active", "pending")), None
        )

        parts: list[str] = [
            "<active_goal>",
            f"  <goal_id>{goal.goal_id}</goal_id>",
            f"  <goal>{goal.goal}</goal>",
            f"  <progress>{len(completed)} of {goal.total_checkpoints} checkpoints completed</progress>",
        ]

        if current:
            parts.append(
                f'  <current_checkpoint order="{current.order}" title="{current.title}">'
            )
            parts.append(f"    <description>{current.description}</description>")
            parts.append(
                f"    <success_criteria>{current.success_criteria}</success_criteria>"
            )
            parts.append("  </current_checkpoint>")

        if goal.context_summary:
            parts.append(
                f"  <context_summary>\n{goal.context_summary}\n  </context_summary>"
            )

        if completed:
            parts.append("  <completed_checkpoints>")
            for c in completed:
                parts.append(
                    f'    <checkpoint order="{c.order}" title="{c.title}" status="completed"/>'
                )
            parts.append("  </completed_checkpoints>")

        if remaining:
            parts.append("  <remaining_checkpoints>")
            for c in remaining:
                parts.append(f'    <checkpoint order="{c.order}" title="{c.title}"/>')
            parts.append("  </remaining_checkpoints>")

        parts.append("</active_goal>")
        return "\n".join(parts)

    # --- Self-evaluation ---

    async def evaluate_progress(self, goal: Goal) -> EvaluationResult:
        """Evaluate whether the goal is on track and if the plan needs revision."""
        checkpoints = await self.get_checkpoints(goal.goal_id)
        completed = [c for c in checkpoints if c.status == "completed"]
        remaining = [c for c in checkpoints if c.status in ("pending", "active")]

        completed_text = "\n".join(
            f"[{c.order}] {c.title} — {c.result_summary or 'done'}" for c in completed
        )
        remaining_text = "\n".join(f"[{c.order}] {c.title}" for c in remaining)

        prompt = (
            f"Goal: {goal.goal}\n\n"
            f"Completed checkpoints:\n{completed_text}\n\n"
            f"Remaining checkpoints:\n{remaining_text}\n\n"
            f"Context summary:\n{goal.context_summary}\n\n"
            f"Evaluate: is this goal on track? Should the remaining plan be revised?"
        )

        response = await self._router.complete(
            messages=[
                {"role": "system", "content": _EVALUATE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            task_type="simple",
            temperature=0.2,
        )
        goal.llm_calls_used += 1

        try:
            data = json.loads(response.content or "{}")
            return EvaluationResult(
                on_track=data.get("on_track", True),
                revision_needed=data.get("revision_needed", False),
                reason=data.get("reason", ""),
                suggested_changes=data.get("suggested_changes"),
            )
        except (json.JSONDecodeError, AttributeError):
            return EvaluationResult(
                on_track=True,
                revision_needed=False,
                reason="Could not parse evaluation",
            )

    def check_budget(self, goal: Goal) -> tuple[bool, str]:
        """Check if the goal is within its LLM call budget."""
        if goal.llm_calls_used >= self._config.max_llm_calls_per_goal:
            return (
                False,
                f"LLM call limit reached ({self._config.max_llm_calls_per_goal})",
            )
        return True, ""

    # --- Persistence helpers ---

    async def _persist_goal(self, goal: Goal) -> None:
        """Upsert a goal to the database.

        ``company_id`` is written only on INSERT (it stays out of the
        ON CONFLICT update set), so subsequent persist calls from
        checkpoint advances or status flips cannot move a goal
        between companies even if the contextvar has flipped in the
        meantime.
        """
        await self._db.execute_insert(
            """
            INSERT INTO goals (goal_id, session_id, goal, status, plan_json,
                context_summary, current_checkpoint, total_checkpoints,
                attempts, max_attempts, llm_calls_used, cost_usd,
                created_at, updated_at, completed_at, mission_id,
                assigned_to_role, tactic_metadata, company_id,
                stage, kill_criterion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(goal_id) DO UPDATE SET
                status = excluded.status,
                plan_json = excluded.plan_json,
                context_summary = excluded.context_summary,
                current_checkpoint = excluded.current_checkpoint,
                total_checkpoints = excluded.total_checkpoints,
                attempts = excluded.attempts,
                llm_calls_used = excluded.llm_calls_used,
                cost_usd = excluded.cost_usd,
                updated_at = excluded.updated_at,
                completed_at = excluded.completed_at,
                mission_id = excluded.mission_id,
                assigned_to_role = excluded.assigned_to_role,
                tactic_metadata = excluded.tactic_metadata,
                stage = excluded.stage,
                kill_criterion = excluded.kill_criterion
            """,
            (
                goal.goal_id,
                goal.session_id,
                goal.goal,
                goal.status,
                json.dumps(goal.plan),
                goal.context_summary,
                goal.current_checkpoint,
                goal.total_checkpoints,
                goal.attempts,
                goal.max_attempts,
                goal.llm_calls_used,
                goal.cost_usd,
                goal.created_at,
                goal.updated_at,
                goal.completed_at,
                goal.mission_id,
                goal.assigned_to_role,
                json.dumps(goal.tactic_metadata or {}),
                goal.company_id,
                goal.stage or "unknown",
                goal.kill_criterion,
            ),
        )

    async def _update_status(
        self,
        goal_id: str,
        new_status: str,
        from_statuses: tuple[str, ...] | None = None,
    ) -> bool:
        """Update a goal's status, optionally requiring a specific current status."""
        goal = await self.get_goal(goal_id)
        if not goal:
            return False
        if from_statuses and goal.status not in from_statuses:
            return False
        goal.status = new_status
        goal.updated_at = datetime.now(UTC).isoformat()
        await self._persist_goal(goal)
        return True

    def _parse_checkpoint_json(
        self, raw: str, goal_id: str, start_order: int = 1
    ) -> list[Checkpoint]:
        """Parse LLM JSON output into Checkpoint objects.

        Accepts EITHER a bare JSON array (the ``revise`` path, and
        pre-Stage-0 decompose output) OR an object of the shape
        ``{"kill_criterion": ..., "checkpoints": [...]}`` (the
        Stage-0 decompose output). The kill_criterion is ignored here
        — ``_extract_kill_criterion`` pulls it; this method only
        returns the checkpoint list.

        The ``order`` field emitted by the LLM is **ignored** — we
        renumber sequentially from ``start_order`` so the resulting
        list is guaranteed to be collision-free against the UNIQUE
        (goal_id, checkpoint_order) constraint. Trusting LLM-emitted
        order numbers was the source of repeated UNIQUE violations:
        the model would emit duplicates within one decompose, or
        numbers that overlapped already-completed checkpoints on
        revise. The DB constraint is the truth; this parser conforms
        to it instead of fighting it.
        """
        data = _loads_json_lenient(raw)
        if data is None:
            logger.warning("Failed to parse checkpoint JSON: %s", (raw or "")[:200])
            return []

        if isinstance(data, dict):
            items = data.get("checkpoints", [])
        else:
            items = data
        if not isinstance(items, list):
            return []

        checkpoints: list[Checkpoint] = []
        next_order = start_order
        for item in items:
            if not isinstance(item, dict):
                continue
            stage = str(item.get("stage", "unknown")).strip().lower() or "unknown"
            if stage not in GOAL_STAGES:
                stage = "unknown"
            checkpoints.append(
                Checkpoint(
                    goal_id=goal_id,
                    order=next_order,
                    title=str(item.get("title", "Untitled"))[:60],
                    description=str(item.get("description", "")),
                    success_criteria=str(item.get("success_criteria", "")),
                    stage=stage,
                )
            )
            next_order += 1
        return checkpoints

    @staticmethod
    def _extract_kill_criterion(raw: str) -> str | None:
        """Pull the goal-level kill_criterion from a decompose response.

        Returns the trimmed string, or None if the response is a bare
        array (revise path) / has no kill_criterion field."""
        data = _loads_json_lenient(raw)
        if isinstance(data, dict):
            kc = data.get("kill_criterion")
            if isinstance(kc, str) and kc.strip():
                return kc.strip()
        return None

    @staticmethod
    def _row_to_goal(row: Any) -> Goal:
        """Convert a database row to a Goal object."""
        return Goal(
            goal_id=row["goal_id"],
            session_id=row["session_id"],
            goal=row["goal"],
            status=row["status"],
            plan=json.loads(row["plan_json"] or "[]"),
            context_summary=row["context_summary"] or "",
            current_checkpoint=row["current_checkpoint"],
            total_checkpoints=row["total_checkpoints"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            llm_calls_used=row["llm_calls_used"],
            cost_usd=row["cost_usd"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            mission_id=row["mission_id"] if "mission_id" in row.keys() else None,
            assigned_to_role=(
                row["assigned_to_role"] if "assigned_to_role" in row.keys() else None
            ),
            tactic_metadata=(
                json.loads(row["tactic_metadata"] or "{}")
                if "tactic_metadata" in row.keys()
                else {}
            ),
            company_id=(
                row["company_id"] if "company_id" in row.keys() else "elophanto-self"
            ),
            stage=(row["stage"] if "stage" in row.keys() else "unknown") or "unknown",
            kill_criterion=(
                row["kill_criterion"] if "kill_criterion" in row.keys() else None
            ),
        )

    @staticmethod
    def _row_to_checkpoint(row: Any) -> Checkpoint:
        """Convert a database row to a Checkpoint object."""
        return Checkpoint(
            goal_id=row["goal_id"],
            order=row["checkpoint_order"],
            title=row["title"],
            description=row["description"],
            success_criteria=row["success_criteria"] or "",
            status=row["status"],
            result_summary=row["result_summary"],
            attempts=row["attempts"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            stage=(row["stage"] if "stage" in row.keys() else "unknown") or "unknown",
        )
