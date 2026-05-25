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

from core.config import GoalsConfig
from core.database import Database

logger = logging.getLogger(__name__)

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
3-15 ordered checkpoints. Each checkpoint should be:
- Concrete and actionable (produces a tangible result)
- Independently verifiable (clear success criteria)
- Sequenced logically (dependencies flow left-to-right)

Return ONLY a JSON array. No markdown, no explanation. Each element:
{
  "order": <int starting at 1>,
  "title": "<short title, max 60 chars>",
  "description": "<what to do, 1-3 sentences>",
  "success_criteria": "<how to verify completion, objective and measurable>"
}

Guidelines:
- First checkpoint should always be research/information gathering
- Front-load risky or uncertain steps
- Keep each checkpoint achievable in 5-30 tool calls
- Avoid subjective criteria ("good quality") — use measurable ones ("3+ items found")
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

Return ONLY a JSON array of new checkpoints (same format as decomposition).
Start ordering from the next checkpoint number after the last completed one.
</goal_revision>"""


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
    ) -> Goal:
        """Create a new goal and persist it.

        ``mission_id`` optionally parents the goal under a mission
        (Phase 2). Unparented goals (mission_id=None) are still
        first-class — the missions tier is opt-in.

        ``assigned_to_role`` (ABE Phase 2) optionally scopes the goal
        to a role persona — e.g. ``assigned_to_role='sales'``. The
        autonomous mind biases candidate selection accordingly. Null
        means the goal works for any role (CEO default).
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
        )
        await self._persist_goal(g)
        return g

    async def get_goal(self, goal_id: str) -> Goal | None:
        """Fetch a goal by ID."""
        rows = await self._db.execute(
            "SELECT * FROM goals WHERE goal_id = ?", (goal_id,)
        )
        if not rows:
            return None
        return self._row_to_goal(rows[0])

    async def get_active_goal(self, session_id: str) -> Goal | None:
        """Get the active goal for a session (if any)."""
        rows = await self._db.execute(
            "SELECT * FROM goals WHERE session_id = ? AND status IN ('planning', 'active') "
            "ORDER BY updated_at DESC LIMIT 1",
            (session_id,),
        )
        if not rows:
            return None
        return self._row_to_goal(rows[0])

    async def list_goals(
        self, status: str | None = None, limit: int = 20
    ) -> list[Goal]:
        """List goals, optionally filtered by status."""
        if status:
            rows = await self._db.execute(
                "SELECT * FROM goals WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            rows = await self._db.execute(
                "SELECT * FROM goals ORDER BY updated_at DESC LIMIT ?",
                (limit,),
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

        checkpoints = self._parse_checkpoint_json(
            response.content or "[]", goal.goal_id
        )
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
                "(goal_id, checkpoint_order, title, description, success_criteria) "
                "VALUES (?, ?, ?, ?, ?)",
                (cp.goal_id, cp.order, cp.title, cp.description, cp.success_criteria),
            )

        # Update goal
        goal.status = "active"
        goal.total_checkpoints = len(checkpoints)
        goal.current_checkpoint = 1
        goal.plan = [
            {
                "order": c.order,
                "title": c.title,
                "description": c.description,
                "success_criteria": c.success_criteria,
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
        # crash/recovery. Querying max(order) where status='completed' is
        # the only source of truth that can't collide with UNIQUE.
        rows = await self._db.execute(
            "SELECT MAX(checkpoint_order) AS max_ord FROM goal_checkpoints "
            "WHERE goal_id = ? AND status = 'completed'",
            (goal.goal_id,),
        )
        max_completed = 0
        if rows:
            max_ord = rows[0]["max_ord"]
            max_completed = int(max_ord) if max_ord is not None else 0

        new_checkpoints = self._parse_checkpoint_json(
            response.content or "[]", goal.goal_id, start_order=max_completed + 1
        )
        if not new_checkpoints:
            return []

        # Delete old pending/failed checkpoints
        await self._db.execute(
            "DELETE FROM goal_checkpoints WHERE goal_id = ? AND status IN ('pending', 'failed')",
            (goal.goal_id,),
        )

        # Insert new ones
        for cp in new_checkpoints:
            await self._db.execute_insert(
                "INSERT INTO goal_checkpoints "
                "(goal_id, checkpoint_order, title, description, success_criteria) "
                "VALUES (?, ?, ?, ?, ?)",
                (cp.goal_id, cp.order, cp.title, cp.description, cp.success_criteria),
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
        """Mark a checkpoint as completed and advance the goal."""
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE goal_checkpoints SET status = 'completed', result_summary = ?, "
            "completed_at = ? WHERE goal_id = ? AND checkpoint_order = ?",
            (summary, now, goal_id, order),
        )

        goal = await self.get_goal(goal_id)
        if not goal:
            return

        next_cp = await self.get_next_checkpoint(goal_id)
        just_completed = False
        if next_cp:
            goal.current_checkpoint = next_cp.order
        else:
            # All checkpoints done
            goal.status = "completed"
            goal.completed_at = now
            just_completed = True

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
            goal = await self.get_goal(goal_id)
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
        """Upsert a goal to the database."""
        await self._db.execute_insert(
            """
            INSERT INTO goals (goal_id, session_id, goal, status, plan_json,
                context_summary, current_checkpoint, total_checkpoints,
                attempts, max_attempts, llm_calls_used, cost_usd,
                created_at, updated_at, completed_at, mission_id,
                assigned_to_role)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                assigned_to_role = excluded.assigned_to_role
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
        # Try to extract JSON array from response
        text = raw.strip()
        # Handle markdown code blocks
        if "```" in text:
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1:
                text = text[start : end + 1]

        try:
            items = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse checkpoint JSON: %s", text[:200])
            return []

        if not isinstance(items, list):
            return []

        checkpoints: list[Checkpoint] = []
        next_order = start_order
        for item in items:
            if not isinstance(item, dict):
                continue
            checkpoints.append(
                Checkpoint(
                    goal_id=goal_id,
                    order=next_order,
                    title=str(item.get("title", "Untitled"))[:60],
                    description=str(item.get("description", "")),
                    success_criteria=str(item.get("success_criteria", "")),
                )
            )
            next_order += 1
        return checkpoints

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
        )
