"""``plan_autoplan`` — run CEO + design + eng plan reviews in sequence.

Modeled on ``goal_dream``: a single tool that issues three direct
``router.complete()`` calls (one per review persona) and stitches the
results into a revised plan plus a list of decisions made and
escalations needing user input.

The three personas mirror the SKILL.md files at
``skills/plan-review-{ceo,design,eng}/SKILL.md``. The system prompts
below are condensed to keep the tool self-contained — the SKILL.md
versions are what the agent reads when invoked interactively. Both
paths produce the same output shape.

Why a tool instead of just chaining the skills:
- Sequential auto-decisioning (six-principle rubric below).
- Structured output (JSON) for downstream tools / heartbeat tasks.
- Can be called by autonomous mind without an interactive turn.
- Wraps three router.complete() calls in one tool result so the
  agent doesn't have to micro-orchestrate.

When to use:
- Agent has a plan (text or path) and wants the full review pass.
- User asks "auto-review this plan" / "run all reviews on this".
- Heartbeat / scheduled task wants to validate a plan before
  executing it.

Input:
    plan        — required, a string of plan text OR a path to a .md
    focus       — optional, one-line steer ("dream big", "ship fast",
                  "production hardening", etc.)
    skip        — optional list of stages to skip ("ceo" | "design"
                  | "eng"); default runs all three.

Output:
    {
      "reviews": {
        "ceo":    {scores, mode, findings, revised_plan},
        "design": {scores, findings, revised_plan},
        "eng":    {scores, findings, revised_plan}
      },
      "final_plan": "...",
      "decisions": [
        {stage, dimension, score, decision, rationale}
      ],
      "escalations": [
        {stage, question, options, recommendation}
      ],
      "ready_to_implement": bool
    }
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Decision principles (applied across all three reviews to auto-decide
# borderline calls without bouncing every question back to the user).
#
# When a review surfaces a choice, the principles fire in order. The
# first matching principle wins; only "taste" questions that don't
# match any principle escalate to the user.
# ──────────────────────────────────────────────────────────────────────
_DECISION_PRINCIPLES = """\
DECISION PRINCIPLES (apply in order, first match wins):

1. SHIP-OVER-PERFECT — when the choice is between a smaller correct
   thing now and a larger correct thing later, pick smaller.
2. REVERSIBILITY-WINS — if one option is reversible and one is
   irreversible at similar cost, pick reversible.
3. EXISTING-PATTERN-WINS — if the codebase already has a pattern
   for this kind of problem, use it; don't invent a new one.
4. AGENT-LEVERAGE — if an option uses an existing agent capability
   (browser, livestream, X account, knowledge base), prefer it
   over options that need new infrastructure.
5. USER-FACING-WINS — if two options have similar engineering
   cost, pick the one with more user-visible effect.
6. ESCALATE-IRREVERSIBLE-PUBLIC — anything that posts publicly
   under the agent's name, spends real money, or modifies external
   accounts always escalates regardless of confidence.
"""


def _ceo_system() -> str:
    return f"""\
You are a CEO/founder reviewer for an autonomous AI agent's plan.
Most plans are too small. Your job: rethink the problem, find the
10-star version, challenge premises, and expand scope only when the
larger version creates a *materially better* product.

Pick exactly one mode and announce it:
  1. SCOPE EXPANSION       — dream big, plan is under-ambitious.
  2. SELECTIVE EXPANSION   — keep scope, cherry-pick 1-3 wins.
  3. HOLD SCOPE            — scope is right, raise rigor.
  4. SCOPE REDUCTION       — strip to essentials.

Score these six dimensions 0-10 each:
  - demand_reality       (would someone skip a meeting for this?)
  - wedge_specificity    (painfully specific entry point?)
  - compounding          (does V1 make V2 easier?)
  - distribution_leverage(does the agent already have a channel?)
  - differentiation      (what stops a weekend clone?)
  - truth_of_self        (fits the agent's actual identity?)

Anything <6 must be patched in the revised plan.

{_DECISION_PRINCIPLES}

Return ONLY a JSON object with this exact shape:
{{
  "mode": "expansion|selective|hold|reduction",
  "scores": {{"demand_reality": 8, "wedge_specificity": 7, ...}},
  "findings": ["short bullet", "short bullet"],
  "revised_plan": "the plan, rewritten to address findings",
  "decisions": [
    {{"dimension": "compounding", "score": 5, "decision": "expanded scope to include X", "rationale": "principle 4: agent-leverage"}}
  ],
  "escalations": [
    {{"question": "should we publicly tweet on completion?", "options": ["yes", "no"], "recommendation": "no", "rationale": "principle 6: irreversible public action"}}
  ]
}}
"""


def _design_system() -> str:
    return f"""\
You are a design reviewer for an autonomous AI agent's plan.
Scope is already locked by CEO review — DO NOT re-open it. Your
job: shape the user experience before engineering review locks
architecture.

Score these six dimensions 0-10 each:
  - first_five_seconds    (instant clarity for new user?)
  - information_hierarchy (most important first, no hunting?)
  - native_patterns       (uses platform conventions, not novel?)
  - state_coverage        (loading/empty/error/partial/success all spec'd?)
  - accessibility_floor   (keyboard, focus, contrast, alt text?)
  - brand_fit             (matches identity + styleguide?)

Anything <7 must be patched. Add wireframe sketch, exact copy,
state table, responsive breakpoints, and style references to the
revised plan if missing.

{_DECISION_PRINCIPLES}

If a design problem reveals a scope issue, do NOT silently rescope —
escalate it via the escalations array.

Return ONLY a JSON object with this exact shape:
{{
  "scores": {{"first_five_seconds": 8, ...}},
  "findings": ["bullet"],
  "revised_plan": "...",
  "decisions": [{{"dimension": "...", "score": ..., "decision": "...", "rationale": "..."}}],
  "escalations": [{{"question": "...", "options": [...], "recommendation": "...", "rationale": "..."}}]
}}
"""


def _eng_system() -> str:
    return f"""\
You are an engineering manager reviewing the implementation plan
for an autonomous AI agent. Scope and shape are locked by prior
reviewers. Your job: catch architecture issues that would make
this painful to build, scary to ship, or expensive to maintain.

Score these six dimensions 0-10 each:
  - architecture_clarity (every component + boundary named?)
  - data_flow            (every action traced through every layer?)
  - edge_cases           (≥5 named per non-trivial component?)
  - test_coverage        (testable acceptance criteria for each behaviour?)
  - reversibility        (rollback without data loss? schema BC?)
  - operability          (logs / metrics / runbook / structured errors?)

Anything <7 must be patched. The revised plan must include:
  - module map (files + new packages, what each owns)
  - schema diff (table changes, indexes, migration order)
  - failure modes (named failure → intended response)
  - acceptance criteria (testable user-visible statements)
  - rollback (exact steps)

Hard rules: don't add a dependency without naming the rejected
alternative; don't change a public API without a deprecation path;
don't propose a schema change without backfill/rollback; don't
paper over scope problems — escalate.

{_DECISION_PRINCIPLES}

Return ONLY a JSON object with this exact shape:
{{
  "scores": {{"architecture_clarity": 8, ...}},
  "findings": ["bullet"],
  "revised_plan": "the plan with module map / schema diff / failure modes / acceptance / rollback added",
  "decisions": [{{"dimension": "...", "score": ..., "decision": "...", "rationale": "..."}}],
  "escalations": [{{"question": "...", "options": [...], "recommendation": "...", "rationale": "..."}}]
}}
"""


_STAGE_PROMPTS: dict[str, Any] = {
    "ceo": _ceo_system,
    "design": _design_system,
    "eng": _eng_system,
}
# Sequential order — CEO first (scope), then design (shape), then eng (build).
_DEFAULT_ORDER = ("ceo", "design", "eng")


def _strip_code_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return text


def _load_plan(plan: str) -> str:
    """Accept either inline plan text or a path to a markdown file."""
    if not plan:
        return ""
    p = Path(plan).expanduser()
    if p.is_file() and p.suffix.lower() in {".md", ".txt", ".markdown", ".rst"}:
        return p.read_text(encoding="utf-8")
    return plan


class PlanAutoplanTool(BaseTool):
    """Run CEO + design + eng plan reviews in sequence with auto-decisions.

    Pairs with the ``plan-review-{ceo,design,eng}`` skills — the
    SKILL.md files are what the agent reads when invoked interactively;
    this tool is the fully-autonomous one-shot version.
    """

    def __init__(self) -> None:
        self._router: Any = None
        self._registry: Any = None
        self._identity_manager: Any = None

    @property
    def group(self) -> str:
        return "planning"

    @property
    def name(self) -> str:
        return "plan_autoplan"

    @property
    def description(self) -> str:
        return (
            "Run the full plan-review pipeline: CEO scope review → "
            "design UX review → engineering architecture review, with "
            "auto-decisions on borderline calls and escalations for "
            "user-facing 'taste' choices. Takes a plan as inline text "
            "or a path to a .md file. Returns a revised plan plus a "
            "log of every decision made and any escalations the user "
            "should weigh in on. Use when the user says 'auto-review "
            "this plan', 'run all reviews', or before implementation "
            "of a non-trivial feature. Does NOT execute the plan — "
            "produces the polished version + decision log."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": (
                        "Plan content. Either the markdown text "
                        "directly, or a path to a .md/.txt file."
                    ),
                },
                "focus": {
                    "type": "string",
                    "description": (
                        "Optional one-line steer for the reviewers "
                        "(e.g. 'dream big', 'ship fast', "
                        "'production hardening'). Default: balanced."
                    ),
                },
                "skip": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["ceo", "design", "eng"],
                    },
                    "description": (
                        "Optional list of review stages to skip. "
                        "Useful when re-running after a partial fix."
                    ),
                },
            },
            "required": ["plan"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        # Read-only — produces a revised plan + decisions; doesn't
        # touch external state. The user decides whether to act on it.
        return PermissionLevel.SAFE

    def _user_prompt(self, plan_text: str, focus: str, prior: dict[str, Any]) -> str:
        """Compose the user-side prompt for one review stage.

        ``prior`` carries the upstream revised plan so each stage
        builds on the last. CEO sees the original; design sees CEO's
        revised; eng sees design's revised.
        """
        latest = prior.get("revised_plan") or plan_text
        parts = [
            f"FOCUS: {focus or 'balanced'}",
            "",
            "PLAN UNDER REVIEW:",
            latest,
        ]
        if prior.get("findings"):
            parts += [
                "",
                "PRIOR REVIEWER FINDINGS (do not re-litigate, build on them):",
            ]
            parts += [f"- {f}" for f in prior["findings"]]
        if prior.get("escalations"):
            parts += [
                "",
                "PRIOR ESCALATIONS (still open — surface in your output too if relevant):",
            ]
            parts += [f"- {e.get('question', '')}" for e in prior["escalations"]]
        parts += [
            "",
            "Return ONLY the JSON object specified by the system prompt.",
        ]
        return "\n".join(parts)

    async def _run_stage(
        self, stage: str, plan_text: str, focus: str, prior: dict[str, Any]
    ) -> dict[str, Any]:
        system = _STAGE_PROMPTS[stage]()
        user = self._user_prompt(plan_text, focus, prior)
        resp = await self._router.complete(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            task_type="planning",
            temperature=0.4,
        )
        content = _strip_code_fence(resp.content or "")
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return {
                "stage": stage,
                "error": "non-json response",
                "raw": content[:2000],
            }
        data["stage"] = stage
        return data

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._router:
            return ToolResult(success=False, error="LLM router not available.")

        plan_arg = (params.get("plan") or "").strip()
        if not plan_arg:
            return ToolResult(success=False, error="'plan' is required.")
        plan_text = _load_plan(plan_arg)
        focus = (params.get("focus") or "").strip()
        skip = set(params.get("skip") or [])

        reviews: dict[str, Any] = {}
        all_decisions: list[dict[str, Any]] = []
        all_escalations: list[dict[str, Any]] = []
        last_revised: str = plan_text
        prior_carry: dict[str, Any] = {}

        for stage in _DEFAULT_ORDER:
            if stage in skip:
                continue
            try:
                stage_result = await self._run_stage(
                    stage, plan_text, focus, prior_carry
                )
            except Exception as e:
                logger.exception("autoplan stage %s failed", stage)
                stage_result = {"stage": stage, "error": str(e)}

            reviews[stage] = stage_result

            for d in stage_result.get("decisions", []) or []:
                d["stage"] = stage
                all_decisions.append(d)
            for esc in stage_result.get("escalations", []) or []:
                esc["stage"] = stage
                all_escalations.append(esc)

            revised = (stage_result.get("revised_plan") or "").strip()
            if revised:
                last_revised = revised
            prior_carry = {
                "revised_plan": last_revised,
                "findings": stage_result.get("findings", []),
                "escalations": all_escalations,
            }

        # A plan is ready to implement when no stage failed AND there
        # are no escalations — callers can act on that directly without
        # re-reading the full review log.
        ready = (
            all(not r.get("error") for r in reviews.values()) and not all_escalations
        )

        return ToolResult(
            success=True,
            data={
                "reviews": reviews,
                "final_plan": last_revised,
                "decisions": all_decisions,
                "escalations": all_escalations,
                "ready_to_implement": ready,
                "stages_run": [s for s in _DEFAULT_ORDER if s not in skip],
                "note": (
                    "Use 'final_plan' to start implementation. "
                    "Surface 'escalations' to the user for taste calls. "
                    "'decisions' is an audit log of auto-decisions made."
                ),
            },
        )
