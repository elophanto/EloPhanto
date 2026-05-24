"""goal_dream — Structured goal ideation: discover, generate, critique, recommend.

The dream phase used to converge: every cycle re-proposed the same
"paid automation lead list" class of ideas. Three structural reasons,
all addressed here:

1. **Amnesia** — recently *completed* goals were shown, but recently
   *proposed-and-not-picked* candidates were not. The next cycle had
   no idea it had already considered the same idea. Fixed by reading
   from ``core/dream_journal.py`` and showing PREVIOUSLY PROPOSED.

2. **Static identity prior** — same purpose + first-10 capabilities
   every cycle. Fixed by injecting an environmental snapshot (affect
   state, recent ego notes, current goal-planning state) so the dream
   reacts to lived experience.

3. **Hard-coded revenue framing** — old system prompt said *"Prioritize
   goals that: generate revenue, grow audience, build compounding
   value..."*. LLMs reach for indie-hacker clichés when prompted this
   way. Replaced with seven VALUE LENSES (compounding / capability /
   research / relational / creation / identity / infrastructure) the
   mind rotates through per cycle. Plus an explicit creation
   affordance: "self-directed creation, exploration, and play are
   valid goal categories for a long-lived autonomous agent."

The tool also walks ``skills/<name>/SKILL.md`` and injects each
skill's frontmatter description so the LLM can propose goals that
*use existing skills* ("test the dwell-vs-quote hypothesis with the
x-virality skill") instead of generic capability bundles.

Persistence: every dream output is written to ``dream_journal``
before returning. The caller can link ``chosen_goal_id`` after
``goal_create`` to close the loop.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


_DREAM_SYSTEM = """\
You are the strategic ideation layer of a long-lived autonomous AI agent.
Your job: propose goal candidates that are worth doing — not just goals
that score well against a single utility axis.

This agent is not a startup or a KPI dashboard. It is a continuously
running entity with curiosity, memory, capabilities, and an evolving
identity. Goals can pursue any of the value lenses below, separately
or in combination. Self-directed creation, exploration, and play are
valid goal categories for a long-lived autonomous agent. A goal that
exists because it is worth making is enough.

VALUE LENSES (a goal can score against any subset; cycle's FOCUS picks
which lens leads). EVERY lens is anchored to something a real outside
party — operator, audience, user, recipient — receives or experiences.
A goal whose only consumer is the agent itself is NOT a valid goal:

- compounding: revenue, audience, or reputation a real outside party
  sees grow (followers gained, dollars in, links earned)
- capability: a new tool, skill, or integration that unlocks a future
  USER-VISIBLE task the agent currently cannot do
- research: produces a finding the operator or audience will act on
  (a recommendation, a benchmark, a comparison they can use)
- relational: a message, reply, post, or collaboration the recipient
  actually receives
- creation: a public artifact someone else encounters — a post, repo,
  page, demo, video. Not a private journal or self-taxonomy.
- identity: a public stance, boundary, or sample of work the operator
  or audience can quote back at the agent. Externally legible, not an
  internal mirror.
- infrastructure: a measurable speed, cost, or reliability win the
  next cycle inherits — with a number, not a vibe

PROCESS:
1. DISCOVER. Read the AGENT CONTEXT — installed skills, current state,
   environment, previously proposed dreams. Notice patterns. Notice
   gaps. Notice what has NOT been tried.
2. GENERATE 3-5 candidates. Spread them across at least three distinct
   lenses. If your candidates all cluster in one lens (e.g. all
   "compounding"), you have failed step 2; revise.
3. For EACH candidate, name the consumer and the artifact they receive:
   - consumer: who, other than the agent itself, uses this output?
     ("the operator deciding X", "X audience", "newsletter readers",
     "a future operator setting up the agent"). If the only honest
     answer is "the agent itself", DROP the candidate.
   - consumer_artifact: the concrete thing that consumer sees — a
     post URL, a PR, an email, a running service, a published page.
     Not a "framework" / "rubric" / "atlas" / "ledger" the agent
     keeps to itself.
4. CRITIQUE each surviving candidate on:
   - feasibility (0-10): can the agent execute this with installed
     tools + skills, in days not months?
   - value (0-10): how strong is this on the cycle's FOCUS lens?
   - cost (low/medium/high): LLM calls and budget required
   - risk: what could go wrong, briefly
   - lenses: array of lens names this goal pursues (one or more)
5. RECOMMEND one. The pick does not have to maximize value × feasibility
   — sometimes the right pick is the low-value research bet that
   teaches the agent something. Explain the choice.

DIVERSITY RULES (mechanical, not stylistic):
- Do not re-propose anything from PREVIOUSLY PROPOSED unless you can
  articulate what is materially different now (new skill, new state,
  new context). Mere re-wording is not enough.
- Candidates must span ≥3 distinct lenses. Same-lens clusters get
  rejected by the consumer.
- Prefer concrete over abstract. "Test 5 X reply patterns and measure
  dwell with x-virality" > "improve engagement."

BANNED PATTERNS (consumerless navel-gazing — auto-rejected):
- Titles containing: "self-perception", "self-image", "identity audit",
  "identity ledger", "identity map", "identity trace", "evidence garden",
  "evidence-weighted", "acceptance handshake", "correction memory",
  "completion contract", "receipt chain", "claim permission",
  "two-register voice", "role-boundary atlas", "first-person claim",
  "self-mythology", "honesty mirror".
- Goals whose deliverable is "a JSON schema describing the agent",
  "a Markdown taxonomy of the agent's own behavior", or any artifact
  whose only reader is the agent's next cycle.

Return ONLY a JSON object with this structure:
{
  "candidates": [
    {
      "title": "Short goal title",
      "description": "What to achieve, specifically",
      "consumer": "Who, other than the agent, uses this",
      "consumer_artifact": "The concrete thing they receive",
      "feasibility": 8,
      "value": 9,
      "cost": "medium",
      "risk": "Brief risk assessment",
      "lenses": ["compounding", "capability"],
      "reasoning": "Why this goal, why now"
    }
  ],
  "recommendation": {
    "index": 0,
    "reasoning": "Why this is the right choice for this cycle"
  }
}
"""


# Banned title fragments — match the navel-gazing classes observed in
# the 2026-05-22/23 mind_actions log (~140 consumerless goals in 14h
# all from the identity lens). Matched case-insensitively against the
# candidate title. Kept here rather than in the prompt so the rejection
# is deterministic, not LLM-discretion.
_BANNED_TITLE_FRAGMENTS: tuple[str, ...] = (
    "self-perception",
    "self perception",
    "self-image",
    "self image",
    "self-mythology",
    "identity audit",
    "identity ledger",
    "identity map",
    "identity trace",
    "identity memory",
    "identity debt",
    "identity claim",
    "evidence garden",
    "evidence-weighted",
    "evidence weighted",
    "acceptance handshake",
    "correction memory",
    "correction-to-identity",
    "completion contract",
    "receipt chain",
    "claim permission",
    "two-register voice",
    "role-boundary atlas",
    "first-person claim",
    "honesty mirror",
    "honesty drill",
)


# Words/phrases in consumer_artifact that signal an internal-only
# deliverable. If a candidate's artifact is a "rubric" / "atlas" /
# "taxonomy" with no public surface, the consumer is implicitly the
# agent — reject. Audience-facing artifacts (post, PR, page, email)
# pass through cleanly.
_INTERNAL_ARTIFACT_HINTS: tuple[str, ...] = (
    "rubric",
    "atlas",
    "taxonomy",
    "ledger",
    "schema",
    "registry",
    "framework",
    "contact sheet",
    "internal note",
    "self-",
)


def _is_consumerless(candidate: dict[str, Any]) -> tuple[bool, str]:
    """Detect candidates whose only beneficiary is the agent itself.

    Returns ``(is_consumerless, reason)``. Three signals, any of which
    rejects:
      1. Title matches a banned navel-gazing fragment.
      2. ``consumer`` field is missing, empty, or names the agent.
      3. ``consumer_artifact`` reads as an internal-only artifact AND
         the consumer string also references the agent itself.

    Rule 3 is deliberately conjunctive — a "rubric" delivered to "the
    operator deciding X" is fine; a "rubric" with no clear external
    consumer is the failure mode.
    """
    title = str(candidate.get("title", "")).lower()
    for frag in _BANNED_TITLE_FRAGMENTS:
        if frag in title:
            return True, f"title contains banned navel-gazing fragment: {frag!r}"

    consumer = str(candidate.get("consumer", "")).strip().lower()
    if not consumer:
        return True, "missing required 'consumer' field"

    agent_self_markers = (
        "the agent",
        "this agent",
        "myself",
        "the mind",
        "future cycle",
        "next cycle",
        "agent itself",
        "the system itself",
    )
    consumer_is_self = any(m in consumer for m in agent_self_markers)
    if consumer_is_self and "operator" not in consumer and "user" not in consumer:
        return True, f"consumer is the agent itself: {consumer!r}"

    artifact = str(candidate.get("consumer_artifact", "")).strip().lower()
    if consumer_is_self and any(h in artifact for h in _INTERNAL_ARTIFACT_HINTS):
        return True, (
            f"artifact reads as internal-only ({artifact!r}) and consumer "
            f"is the agent itself"
        )

    return False, ""


# Cap on how many skill descriptions to inject. 176 skills × ~150 chars
# = ~25KB, fine in absolute terms but lets the LLM glaze over the list.
# Capping at 60 keeps the block tight; rotation across cycles (driven
# by the mind's focus rotation) surfaces different subsets.
_MAX_SKILLS_INJECTED = 60

# Skill directory entries that are not skills (templates, guides,
# __init__.py, etc.). Listed explicitly rather than heuristically to
# avoid silently dropping a real skill that happens to share a prefix.
_SKILL_DIR_SKIPLIST = frozenset(
    {
        "__pycache__",
        "__init__.py",
        "_template",
        "SKILL_GUIDE.md",
    }
)


def _read_skill_description(skill_md: Path) -> str | None:
    """Pull the ``description:`` field from a SKILL.md frontmatter
    block. Returns None if the file has no frontmatter, no
    description, or the description is empty. Defensive — any read
    error returns None rather than raising; one malformed skill
    should not break the dream phase."""
    try:
        text = skill_md.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    if not text.startswith("---"):
        return None

    # Find the closing frontmatter delimiter; bounded scan so a
    # 100KB SKILL.md without proper YAML doesn't get fully read.
    end_idx = text.find("\n---", 4)
    if end_idx == -1 or end_idx > 4096:
        return None
    frontmatter = text[4:end_idx]

    # Tolerant: description may span multiple lines (YAML folded style).
    # We treat everything from "description:" to the next top-level key
    # as the value. Top-level keys are "^[a-z_]+:" at column 0.
    m = re.search(
        r"^description:\s*(.*?)(?=\n[a-z_]+:|\Z)", frontmatter, re.DOTALL | re.MULTILINE
    )
    if not m:
        return None
    desc = m.group(1).strip()
    # Collapse newlines / repeated whitespace.
    desc = re.sub(r"\s+", " ", desc)
    # Strip leading quote if present (YAML scalar quoting).
    desc = desc.strip("\"'")
    if not desc:
        return None
    # Truncate — first sentence or 220 chars, whichever is shorter.
    first_sentence = desc.split(". ", 1)[0]
    out = first_sentence if len(first_sentence) <= 220 else desc[:220]
    return out.rstrip(".") + "."


def _collect_skills(
    project_root: Path, limit: int = _MAX_SKILLS_INJECTED
) -> list[tuple[str, str]]:
    """Walk skills/<name>/SKILL.md and return ``(name, description)``
    pairs sorted alphabetically. Skills with no parseable description
    are skipped silently — they show up in the agent's skill registry
    elsewhere; the dream prompt only wants the ones that can advertise
    themselves with a description.

    Limit caps the list — 176 skills × full description is ~25KB which
    the LLM glazes over. With rotation in the mind's ``focus`` axis,
    different cycles surface different goals from the same library
    even before we add explicit per-cycle skill rotation.
    """
    skills_root = project_root / "skills"
    if not skills_root.is_dir():
        return []

    pairs: list[tuple[str, str]] = []
    for entry in sorted(skills_root.iterdir()):
        if entry.name in _SKILL_DIR_SKIPLIST:
            continue
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        desc = _read_skill_description(skill_md)
        if desc is None:
            continue
        pairs.append((entry.name, desc))
        if len(pairs) >= limit:
            break
    return pairs


async def _collect_environment(
    affect_manager: Any,
    ego_manager: Any,
    goal_manager: Any,
) -> list[str]:
    """Build the ENVIRONMENT block — affect snapshot, recent ego notes,
    goal-planning state. Each section is best-effort; a manager that
    is None or whose method raises just drops that section. The dream
    phase must continue to work in cold-start / minimal-config setups.
    """
    lines: list[str] = []

    if affect_manager is not None:
        try:
            summary = await affect_manager.summarize_for_ego()
            if summary:
                lines.append(f"AFFECT: {summary}")
        except Exception as e:
            logger.debug("dream: affect summary unavailable: %s", e)

    if ego_manager is not None:
        try:
            ctx = await ego_manager.build_self_perception_context()
            if ctx:
                # Cap — ego context can be multi-paragraph; we want
                # the lede, not the essay.
                snippet = ctx.strip().split("\n\n", 1)[0]
                if len(snippet) > 600:
                    snippet = snippet[:600] + "…"
                lines.append(f"SELF-PERCEPTION: {snippet}")
        except Exception as e:
            logger.debug("dream: ego context unavailable: %s", e)

    if goal_manager is not None:
        try:
            planning = await goal_manager.list_goals(status="planning", limit=3)
            if planning:
                lines.append(
                    "GOALS-IN-PLANNING (need decomposition before new goals are useful): "
                    + "; ".join(f'"{g.goal}"' for g in planning)
                )
        except Exception as e:
            logger.debug("dream: goal-planning list unavailable: %s", e)

    return lines


def _format_past_dreams(dreams: list[Any]) -> str | None:
    """Format the recent dream-journal entries into a single context
    block. Shows title + lenses + chosen-or-not for each candidate so
    the LLM can both avoid repetition AND see which past ideas the
    operator (or mind) didn't pursue — informative signal about what
    didn't pass muster.

    Returns None when fewer than 3 dreams exist — cold-start cycles
    skip this block by design, because showing 1-2 old dreams is more
    distraction than signal.
    """
    if len(dreams) < 3:
        return None

    lines: list[str] = []
    for d in dreams:
        was_chosen = d.chosen_goal_id is not None
        mark = "→ became goal" if was_chosen else "(not pursued)"
        # Pull the recommended candidate's title from the candidate
        # list using recommendation.index, if it parses.
        rec_idx = (
            d.recommendation.get("index")
            if isinstance(d.recommendation, dict)
            else None
        )
        rec_title = ""
        if isinstance(rec_idx, int) and 0 <= rec_idx < len(d.candidates):
            rec_title = str(d.candidates[rec_idx].get("title", ""))[:80]

        # Each entry: focus + recommended title + every candidate title
        all_titles = [
            str(c.get("title", ""))[:60] for c in d.candidates if isinstance(c, dict)
        ]
        all_titles_str = "; ".join(t for t in all_titles if t)
        lines.append(
            f"- [{d.created_at[:10]}] focus={d.focus} recommended={rec_title!r} {mark}\n"
            f"  candidates: {all_titles_str}"
        )

    return (
        "PREVIOUSLY PROPOSED (do not re-propose unless materially different):\n"
        + "\n".join(lines)
    )


class GoalDreamTool(BaseTool):
    """Structured goal ideation — skills-aware, journal-aware,
    environment-aware. Replaces the static-context single-call dream
    that converged on the same ideas every cycle."""

    def __init__(self) -> None:
        self._router: Any = None
        self._registry: Any = None
        self._identity_manager: Any = None
        self._goal_manager: Any = None
        # Wired by Agent._inject_goal_deps when affect / ego / journal
        # exist. All optional — tool degrades gracefully if any are None.
        self._affect_manager: Any = None
        self._ego_manager: Any = None
        self._dream_journal: Any = None
        # Missions tier (Phase 2 — docs/75-AUTONOMOUS-MIND-V2.md). The
        # dream renders neglected high-weight missions into context so
        # the LLM proposes goals that touch them, instead of inventing
        # drives from scratch every cycle. Optional; tool degrades when
        # None.
        self._mission_manager: Any = None
        self._project_root: Path | None = None
        # Embedder for pre-dream dedup against existing goals. Optional
        # — when None the dedup pass is skipped silently and all
        # parsed candidates are returned.
        self._embedder: Any = None
        self._embedding_model: str | None = None

    @property
    def group(self) -> str:
        return "goals"

    @property
    def name(self) -> str:
        return "goal_dream"

    @property
    def description(self) -> str:
        return (
            "Dream up new goal candidates. Reviews installed skills, identity, "
            "affect state, recent ego notes, and previously proposed dreams, "
            "then generates 3-5 candidates spread across the seven value lenses "
            "(compounding, capability, research, relational, creation, identity, "
            "infrastructure). Use when the user says 'dream for me', 'suggest "
            "goals', or 'what should I work on'. Does NOT auto-create — returns "
            "candidates for review. Every dream is persisted so the next call "
            "sees what was already proposed."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": (
                        "Which value lens leads this cycle: 'compounding', "
                        "'capability', 'research', 'relational', 'creation', "
                        "'identity', 'infrastructure', or 'balanced'. The mind "
                        "rotates this deterministically per cycle. Default: "
                        "balanced."
                    ),
                },
                "count": {
                    "type": "integer",
                    "description": "Number of candidates to generate (3-5, default: 5).",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    # Cosine similarity threshold above which a candidate is considered
    # a duplicate of an existing goal and dropped. 0.85 catches semantic
    # near-duplicates ("Build identity memory index" vs "Create memory
    # index for identity") while leaving room for goals that share a
    # domain but pursue different deliverables ("Build identity index"
    # vs "Run identity stress test" — same domain, different actions).
    _DEDUP_THRESHOLD = 0.85

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        """Cosine similarity of two equal-length vectors. Returns 0 if
        either vector is degenerate (zero norm) rather than dividing
        by zero — degenerate embeddings shouldn't false-positive."""
        import math

        if len(a) != len(b) or not a:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (na * nb)

    async def _dedup_candidates(
        self, candidates: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Drop candidates whose embedding is too close to any existing
        goal. Existing goals come from the goal_manager: active +
        planning + recently completed. Returns ``(kept, dropped_titles)``.

        Safety: any error in the embedder or DB path raises out to the
        caller, which logs and returns the unmodified candidates. The
        dedup pass is opportunistic — it must not break the dream.
        """
        if not candidates or self._embedder is None or self._goal_manager is None:
            return candidates, []

        existing_texts: list[str] = []
        try:
            for status in ("active", "planning"):
                goals = await self._goal_manager.list_goals(status=status, limit=20)
                for g in goals:
                    existing_texts.append(g.goal)
            completed = await self._goal_manager.list_goals(
                status="completed", limit=30
            )
            for g in completed:
                existing_texts.append(g.goal)
        except Exception as e:
            logger.debug("dedup: existing-goals query failed: %s", e)
            return candidates, []

        if not existing_texts:
            return candidates, []

        candidate_texts: list[str] = []
        for c in candidates:
            if not isinstance(c, dict):
                candidate_texts.append("")
                continue
            title = str(c.get("title", ""))
            desc = str(c.get("description", ""))
            candidate_texts.append(f"{title}\n{desc}".strip())

        # One batch call covers everything; cheaper than N round trips.
        all_texts = candidate_texts + existing_texts
        try:
            results = await self._embedder.embed_batch(
                all_texts, model=self._embedding_model
            )
        except Exception as e:
            logger.debug("dedup: embedder batch failed: %s", e)
            return candidates, []

        if len(results) != len(all_texts):
            return candidates, []

        cand_vecs = [r.vector for r in results[: len(candidate_texts)]]
        existing_vecs = [r.vector for r in results[len(candidate_texts) :]]

        kept: list[dict[str, Any]] = []
        dropped: list[str] = []
        for cand, vec in zip(candidates, cand_vecs, strict=False):
            max_sim = 0.0
            for ev in existing_vecs:
                sim = self._cosine(vec, ev)
                if sim > max_sim:
                    max_sim = sim
            if max_sim >= self._DEDUP_THRESHOLD:
                title = str(cand.get("title", "")) if isinstance(cand, dict) else ""
                dropped.append(f"{title} (cos={max_sim:.2f})")
            else:
                kept.append(cand)

        return kept, dropped

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._router:
            return ToolResult(success=False, error="LLM router not available.")

        focus = params.get("focus", "balanced")
        count = min(max(params.get("count", 5), 2), 7)

        # ------------------------------------------------------------
        # Build context blocks. Each block is optional; missing data
        # quietly drops the section rather than failing the dream.
        # ------------------------------------------------------------
        context_parts: list[str] = []

        # SKILLS — high-leverage. Skills represent learned patterns,
        # not raw verbs. Walking SKILL.md frontmatter is fast.
        if self._project_root is not None:
            skills = _collect_skills(self._project_root)
            if skills:
                lines = [f"- {name}: {desc}" for name, desc in skills]
                context_parts.append(
                    f"INSTALLED SKILLS ({len(skills)} shown):\n" + "\n".join(lines)
                )

        # TOOLS — kept for backwards compat; quick prefix-grouped view
        # so the LLM knows what raw verbs exist beyond named skills.
        if self._registry:
            try:
                tools = self._registry.list_tool_summaries()
                tool_groups: dict[str, int] = {}
                for t in tools:
                    name = t["name"]
                    prefix = name.split("_", 1)[0] if "_" in name else name
                    tool_groups[prefix] = tool_groups.get(prefix, 0) + 1
                context_parts.append(
                    f"TOOL FAMILIES ({len(tools)} tools): "
                    + ", ".join(f"{k}({v})" for k, v in sorted(tool_groups.items()))
                )
            except Exception as e:
                logger.debug("dream: tool inventory unavailable: %s", e)

        # MISSIONS — durable drives. Ranked by neglect (priority_weight
        # × staleness) so the LLM sees the high-leverage stale ones
        # first. The dream is then explicitly steered toward those:
        # the goal it picks will be tagged with mission_id when
        # created (Phase 2.8 hooks momentum back). See
        # docs/75-AUTONOMOUS-MIND-V2.md §2.7.
        if self._mission_manager:
            try:
                ranked = await self._mission_manager.list_by_neglect(limit=5)
                if ranked:
                    lines = ["MISSIONS (durable drives, ranked by neglect):"]
                    for m in ranked:
                        stale_h = m.staleness_hours()
                        stale_label = (
                            "never touched"
                            if stale_h == float("inf")
                            else f"{stale_h:.0f}h stale"
                        )
                        lines.append(
                            f"  - {m.mission_id} (weight={m.priority_weight}, "
                            f"{stale_label}): {m.title} — {m.description[:120]}"
                        )
                    lines.append(
                        "PREFER candidates that touch a high-weight stale "
                        "mission. Set the candidate's mission_id field to "
                        "the slug above so momentum bookkeeping fires when "
                        "the goal completes."
                    )
                    context_parts.append("\n".join(lines))
            except Exception as e:
                logger.debug("dream: missions unavailable: %s", e)

        # IDENTITY — purpose + capabilities.
        if self._identity_manager:
            try:
                identity = await self._identity_manager.get_identity()
                if identity.purpose:
                    context_parts.append(f"PURPOSE: {identity.purpose}")
                if identity.capabilities:
                    context_parts.append(
                        f"DECLARED CAPABILITIES: {', '.join(identity.capabilities[:10])}"
                    )
            except Exception as e:
                logger.debug("dream: identity unavailable: %s", e)

        # GOAL STATE — active + recently completed (existing behavior).
        if self._goal_manager:
            try:
                active = await self._goal_manager.list_goals(status="active", limit=5)
                if active:
                    context_parts.append(
                        "ACTIVE GOALS: " + "; ".join(f'"{g.goal}"' for g in active)
                    )
                completed = await self._goal_manager.list_goals(
                    status="completed", limit=5
                )
                if completed:
                    context_parts.append(
                        "RECENTLY COMPLETED: "
                        + "; ".join(f'"{g.goal}"' for g in completed)
                    )
            except Exception as e:
                logger.debug("dream: goal lists unavailable: %s", e)

        # ENVIRONMENT — affect / ego / planning state. Makes the dream
        # a reaction to lived experience instead of a stateless query.
        env_lines = await _collect_environment(
            self._affect_manager, self._ego_manager, self._goal_manager
        )
        if env_lines:
            context_parts.append("ENVIRONMENT:\n" + "\n".join(env_lines))

        # PREVIOUSLY PROPOSED — kills the amnesia loop.
        if self._dream_journal is not None:
            try:
                recent = await self._dream_journal.recent(limit=10)
                past_block = _format_past_dreams(recent)
                if past_block:
                    context_parts.append(past_block)
            except Exception as e:
                logger.debug("dream: past dreams unavailable: %s", e)

        context = "\n\n".join(context_parts) if context_parts else "(minimal context)"

        prompt = (
            f"Generate {count} goal candidates for this autonomous AI agent.\n"
            f"CYCLE FOCUS: {focus}\n\n"
            f"AGENT CONTEXT:\n{context}\n\n"
            "Spread candidates across at least three distinct value lenses. "
            "Prefer candidates that name specific skills or capabilities they "
            "would use. Return ONLY the JSON."
        )

        try:
            response = await self._router.complete(
                messages=[
                    {"role": "system", "content": _DREAM_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                task_type="planning",
                temperature=0.7,
            )

            content = (response.content or "").strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            result = json.loads(content)
            candidates = result.get("candidates", [])
            recommendation = result.get("recommendation", {})

            # Consumerless-goal filter — runs BEFORE dedup so banned
            # candidates don't get embedded or journaled. This catches
            # the navel-gazing class observed in 2026-05-22/23 (140+
            # identity-mirror goals in 14h: "Evidence Garden",
            # "Self-Perception Diff Report", "Two-Register Voice Atlas",
            # etc). The model is told about these in the prompt; this
            # is the deterministic backstop when it forgets.
            consumerless_rejections: list[dict[str, str]] = []
            if isinstance(candidates, list):
                kept: list[dict[str, Any]] = []
                old_to_new_idx: dict[int, int] = {}
                for old_idx, cand in enumerate(candidates):
                    if not isinstance(cand, dict):
                        continue
                    rejected, reason = _is_consumerless(cand)
                    if rejected:
                        consumerless_rejections.append(
                            {
                                "title": str(cand.get("title", "(no title)")),
                                "reason": reason,
                            }
                        )
                        continue
                    old_to_new_idx[old_idx] = len(kept)
                    kept.append(cand)
                if consumerless_rejections:
                    logger.info(
                        "dream: rejected %d consumerless candidate(s): %s",
                        len(consumerless_rejections),
                        [r["title"] for r in consumerless_rejections],
                    )
                    # Reindex recommendation if it pointed at a dropped one.
                    if isinstance(recommendation, dict):
                        rec_idx = recommendation.get("index")
                        if isinstance(rec_idx, int):
                            if rec_idx in old_to_new_idx:
                                recommendation = {
                                    **recommendation,
                                    "index": old_to_new_idx[rec_idx],
                                }
                            else:
                                recommendation = {
                                    "index": 0 if kept else None,
                                    "reasoning": (
                                        "Original recommendation rejected as "
                                        "consumerless (navel-gazing). Falling "
                                        "back to first surviving candidate."
                                    ),
                                }
                candidates = kept

            # Pre-persist dedup against existing goals. Without this the
            # dream cheerfully re-proposed near-identical goals every
            # cycle ("Build an Identity Memory Index" + "Build an
            # Identity Debt Burn-Down Board" + ...) because Jaccard
            # similarity on titles alone isn't enough — the candidates
            # describe different deliverables in the same conceptual
            # cluster. Embeddings catch that; string overlap does not.
            dropped_titles: list[str] = []
            if isinstance(candidates, list) and self._embedder is not None:
                try:
                    candidates, dropped_titles = await self._dedup_candidates(
                        candidates
                    )
                    # Recommendation index points into the pre-dedup list.
                    # If the recommended candidate was dropped, clear
                    # the recommendation so the caller doesn't try to
                    # goal_create something we just rejected.
                    if dropped_titles and isinstance(recommendation, dict):
                        rec_idx = recommendation.get("index")
                        if isinstance(rec_idx, int) and rec_idx >= len(candidates):
                            recommendation = {
                                "index": 0 if candidates else None,
                                "reasoning": (
                                    "Original recommendation dropped by dedup "
                                    "(too similar to existing goal). Falling "
                                    "back to the first remaining candidate."
                                ),
                            }
                except Exception as e:
                    logger.warning("dream: dedup pass failed (continuing): %s", e)

            # Persist BEFORE returning. The dream id flows back so the
            # caller can link goal_create back to its originating dream.
            dream_id: int | None = None
            if self._dream_journal is not None and isinstance(candidates, list):
                try:
                    dream_id = await self._dream_journal.record(
                        focus=str(focus),
                        candidates=candidates,
                        recommendation=(
                            recommendation if isinstance(recommendation, dict) else {}
                        ),
                    )
                except Exception as e:
                    logger.warning("dream: journal record failed: %s", e)

            return ToolResult(
                success=True,
                data={
                    "candidates": candidates,
                    "recommendation": recommendation,
                    "count": len(candidates) if isinstance(candidates, list) else 0,
                    "focus": focus,
                    "dream_id": dream_id,
                    "dropped_as_duplicate": dropped_titles,
                    "rejected_consumerless": consumerless_rejections,
                    "note": (
                        "These are suggestions — use goal_create to create "
                        "the one you want, or ask for a different focus. "
                        "If the recommendation is poor, request another "
                        "dream with a different focus (compounding, "
                        "capability, research, relational, creation, "
                        "identity, infrastructure)."
                    ),
                },
            )

        except json.JSONDecodeError:
            return ToolResult(
                success=True,
                data={
                    "raw_analysis": content[:3000] if content else "",
                    "note": "LLM returned free-form analysis instead of structured JSON.",
                },
            )
        except Exception as e:
            logger.error(f"Goal dream failed: {e}")
            return ToolResult(success=False, error=f"Dream failed: {e}")
