"""``panel_review`` and ``panel_refine`` — the quality-gated spawn tier.

The other spawn tiers dispatch and aggregate. These two converge: work is
judged by independent subagents wearing distinct lenses, and revised against
their specific objections until it clears a bar or the budget runs out.

Judges run with a read-only view of the registry. A reviewer that can edit
the thing it is reviewing is not a reviewer, and one that can spawn more
reviewers is a fork bomb with opinions.
"""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

# Judges read and reason; they never act. Anything that mutates state, spends,
# or spawns is hidden from them — a review that edits its subject is worthless,
# and recursive panels multiply cost without adding independence.
_JUDGE_EXCLUDED_PREFIXES: tuple[str, ...] = (
    "panel_",
    "delegate",
    "swarm_",
    "kid_",
    "org_",
    "payment_",
    "wallet_",
    "crypto_",
    "fiat_",
    "agent_connect",
    "agent_message",
    "agent_disconnect",
    "schedule_task",
    "file_write",
    "file_patch",
    "file_delete",
    "file_move",
    "shell_execute",
    "http_request",
    "email_send",
    "gmail",
    "self_modify_source",
    "self_create_plugin",
    "browser_",
    "desktop_",
)

# The producer may act, but must not recurse into more panels or open the
# blast-radius tools that the parent turn already gates.
_PRODUCER_EXCLUDED_PREFIXES: tuple[str, ...] = (
    "panel_",
    "delegate",
    "swarm_",
    "kid_",
    "org_",
    "payment_",
    "wallet_",
    "agent_connect",
    "agent_message",
    "agent_disconnect",
    "schedule_task",
)

_DEFAULT_JUDGE_STEPS = 8
_DEFAULT_PRODUCER_STEPS = 25
_MAX_ARTIFACT_CHARS = 60_000


def _excluded(all_names: list[str], prefixes: tuple[str, ...]) -> set[str]:
    out: set[str] = set()
    for name in all_names:
        for prefix in prefixes:
            if name == prefix or name.startswith(prefix):
                out.add(name)
                break
    return out


class _PanelBase(BaseTool):
    """Shared wiring: both tools drive subagents through ``run_isolated``."""

    def __init__(self) -> None:
        self._agent: Any = None  # injected by Agent at startup
        self._registry: Any = None  # injected by Agent at startup
        # The previous round's output, so a revision can be handed its own
        # prior attempt alongside the objections raised against it.
        self._last_artifact: str = ""

    @property
    def group(self) -> str:
        return "panel"

    def _tool_names(self) -> list[str]:
        if self._registry is None:
            return []
        return [t.name for t in self._registry.all_tools()]

    def _make_judge(self, steps: int):
        excluded = _excluded(self._tool_names(), _JUDGE_EXCLUDED_PREFIXES)

        async def judge(prompt: str, lens: Any) -> str:
            response = await self._agent.run_isolated(
                prompt,
                excluded_tool_names=excluded,
                max_steps_override=steps,
            )
            return getattr(response, "content", "") or ""

        return judge

    @staticmethod
    def _lens_payload(verdicts: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "lens": v.lens,
                "score": v.score,
                "passed": v.passed,
                "blocking": v.blocking,
                "findings": v.actionable_findings,
                **({"error": v.error} if v.error else {}),
            }
            for v in verdicts
        ]


class PanelReviewTool(_PanelBase):
    """Review an artifact through several independent lenses."""

    @property
    def name(self) -> str:
        return "panel_review"

    @property
    def description(self) -> str:
        return (
            "Review work through several INDEPENDENT judges, each with a "
            "different lens (correctness, failure modes, fidelity to a "
            "reference, completeness). Each judge sees only its own lens and "
            "never another's verdict, so you get distinct objections instead "
            "of one opinion repeated. Use it before claiming something is "
            "done — especially when comparing against a reference you are "
            "meant to match or beat. Returns per-lens scores and specific "
            "defects. It does not revise; use panel_refine for that."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "artifact": {
                    "type": "string",
                    "description": "The work to review (text, code, or a report).",
                },
                "goal": {
                    "type": "string",
                    "description": "What the work was supposed to achieve.",
                },
                "reference": {
                    "type": "string",
                    "description": (
                        "The standard to match or beat — a competitor's output, "
                        "a spec, an existing implementation. Judges compare "
                        "against it directly."
                    ),
                },
                "lens_pack": {
                    "type": "string",
                    "description": "Built-in pack: 'code', 'writing', or 'analysis'.",
                },
                "lenses": {
                    "type": "array",
                    "description": (
                        "Custom lenses: [{name, brief, blocking}]. Combined with "
                        "lens_pack when both are given."
                    ),
                    "items": {"type": "object"},
                },
            },
            "required": ["artifact"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._agent is None:
            return ToolResult(
                success=False, error="Panel review needs an agent context."
            )
        from core.panel import QualityBar, assess, resolve_lenses, run_panel

        artifact = str(params.get("artifact", "") or "").strip()
        if not artifact:
            return ToolResult(success=False, error="`artifact` is required.")
        artifact = artifact[:_MAX_ARTIFACT_CHARS]

        lenses = resolve_lenses(
            pack=str(params.get("lens_pack", "") or ""),
            custom=params.get("lenses") or [],
        )
        if not lenses:
            lenses = resolve_lenses(pack="analysis")

        verdicts = await run_panel(
            artifact,
            lenses,
            self._make_judge(_DEFAULT_JUDGE_STEPS),
            reference=str(params.get("reference", "") or ""),
            goal=str(params.get("goal", "") or ""),
        )
        accepted, reason, mean = assess(verdicts, QualityBar())

        return ToolResult(
            success=True,
            data={
                "accepted": accepted,
                "reason": reason,
                "mean_score": round(mean, 2),
                "verdicts": self._lens_payload(verdicts),
                "outstanding": [
                    f"[{v.lens}] {f}" for v in verdicts for f in v.actionable_findings
                ],
            },
        )


class PanelRefineTool(_PanelBase):
    """Produce and revise until an independent panel accepts the work."""

    @property
    def name(self) -> str:
        return "panel_refine"

    @property
    def description(self) -> str:
        return (
            "Do a task, have independent judges review it, revise against "
            "their specific objections, and repeat until it clears the "
            "quality bar or the round budget runs out. This is the "
            "'don't stop until it's genuinely good' tool — use it for work "
            "that must stand comparison with a reference, not for quick "
            "answers. Each round costs a full agent run per judge plus one "
            "for the revision, so keep max_rounds small. It reports honestly "
            "when it fails to converge rather than claiming success."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "What to produce, in full detail.",
                },
                "reference": {
                    "type": "string",
                    "description": (
                        "The standard to match or beat. Judges compare the work "
                        "against this directly — supply it whenever one exists."
                    ),
                },
                "lens_pack": {
                    "type": "string",
                    "description": "Built-in pack: 'code', 'writing', or 'analysis'.",
                },
                "lenses": {
                    "type": "array",
                    "description": "Custom lenses: [{name, brief, blocking}].",
                    "items": {"type": "object"},
                },
                "min_score": {
                    "type": "number",
                    "description": "Mean score required to accept, 1-5. Default 4.0.",
                },
                "max_rounds": {
                    "type": "integer",
                    "description": "Produce/judge cycles before giving up. Default 3.",
                },
            },
            "required": ["goal"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        # Several full agent runs per call — real spend, so it confirms.
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._agent is None:
            return ToolResult(
                success=False, error="Panel refine needs an agent context."
            )
        from core.panel import QualityBar, converge, resolve_lenses

        goal = str(params.get("goal", "") or "").strip()
        if not goal:
            return ToolResult(success=False, error="`goal` is required.")

        reference = str(params.get("reference", "") or "")
        lenses = resolve_lenses(
            pack=str(params.get("lens_pack", "") or ""),
            custom=params.get("lenses") or [],
        )
        if not lenses:
            lenses = resolve_lenses(pack="analysis")

        bar = QualityBar(
            min_score=float(params.get("min_score") or 4.0),
            max_rounds=int(params.get("max_rounds") or 3),
        )

        producer_excluded = _excluded(self._tool_names(), _PRODUCER_EXCLUDED_PREFIXES)

        async def produce(round_num: int, findings: list[str]) -> str:
            if round_num == 1:
                prompt = goal
                if reference:
                    prompt = (
                        f"{goal}\n\nIt must stand comparison with this "
                        f"reference:\n{reference}"
                    )
            else:
                # Revision is answering named objections, not "try harder".
                numbered = "\n".join(f"{i}. {f}" for i, f in enumerate(findings, 1))
                prompt = (
                    f"Revise your previous work on this task.\n\nTask:\n{goal}\n\n"
                    f"Your previous attempt:\n{self._last_artifact}\n\n"
                    f"Independent reviewers raised these specific defects — "
                    f"address every one, and do not regress what already "
                    f"worked:\n{numbered}\n\n"
                    "Return the complete revised work, not a diff or a summary "
                    "of changes."
                )
                if reference:
                    prompt += f"\n\nThe reference to match or beat:\n{reference}"

            response = await self._agent.run_isolated(
                prompt,
                excluded_tool_names=producer_excluded,
                max_steps_override=_DEFAULT_PRODUCER_STEPS,
            )
            content = getattr(response, "content", "") or ""
            self._last_artifact = content[:_MAX_ARTIFACT_CHARS]
            return self._last_artifact

        self._last_artifact = ""
        result = await converge(
            produce=produce,
            judge=self._make_judge(_DEFAULT_JUDGE_STEPS),
            lenses=lenses,
            bar=bar,
            reference=reference,
            goal=goal,
        )

        data: dict[str, Any] = {
            **result.summary(),
            "artifact": result.artifact,
            "rounds": [
                {
                    "round": r.round_num,
                    "accepted": r.accepted,
                    "mean_score": r.mean_score,
                    "reason": r.reason,
                    "verdicts": self._lens_payload(r.verdicts),
                }
                for r in result.rounds
            ],
        }
        if not result.converged:
            data["warning"] = (
                "Did NOT reach the quality bar. The artifact is the best "
                "attempt, not an accepted result — report the outstanding "
                "findings rather than presenting this as finished."
            )
        return ToolResult(success=True, data=data)
