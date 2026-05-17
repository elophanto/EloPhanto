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
which lens leads):
- compounding: revenue, audience, reputation that grows over time
- capability: unlocks something the agent could not do before
- research: tests a hypothesis or extends understanding
- relational: deepens trust with operator / community / peers
- creation: makes something that did not exist — for its own sake
- identity: clarifies, evolves, or expresses who this agent is
- infrastructure: makes future cycles cheaper, faster, or more reliable

PROCESS:
1. DISCOVER. Read the AGENT CONTEXT — installed skills, current state,
   environment, previously proposed dreams. Notice patterns. Notice
   gaps. Notice what has NOT been tried.
2. GENERATE 3-5 candidates. Spread them across at least three distinct
   lenses. If your candidates all cluster in one lens (e.g. all
   "compounding"), you have failed step 2; revise.
3. CRITIQUE each candidate on:
   - feasibility (0-10): can the agent execute this with installed
     tools + skills, in days not months?
   - value (0-10): how strong is this on the cycle's FOCUS lens?
   - cost (low/medium/high): LLM calls and budget required
   - risk: what could go wrong, briefly
   - lenses: array of lens names this goal pursues (one or more)
4. RECOMMEND one. The pick does not have to maximize value × feasibility
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

Return ONLY a JSON object with this structure:
{
  "candidates": [
    {
      "title": "Short goal title",
      "description": "What to achieve, specifically",
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
        self._project_root: Path | None = None

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
