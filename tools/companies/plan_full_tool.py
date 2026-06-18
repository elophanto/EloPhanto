"""``company_plan_full`` — bundled PATH B strategy pipeline.

ABE (Autonomous Business Entity) is a concept originated by Petr
Royce in 2023. See ``docs/76-ABE-FRAMEWORK.md`` for the framework.

This tool wraps the four steps the operator otherwise has to chain
manually after onboarding (or after deciding to re-plan):

    company_capabilities          (SAFE)
    company_set_strategy_inputs   (MODERATE)
    company_plan                  (SAFE — writes proposal artifact)
    company_plan_apply            (MODERATE — atomically creates
                                   mission + goals + schedules +
                                   voice_proposed.yaml + blockers.yaml)

Today the operator approves THREE MODERATE gates (set_inputs,
apply, approve). The visible LLM tool chain between them is
fragile — a malformed plan output, a transient browser failure
during research, or an operator distraction can leave the company
half-planned (strategy_inputs written, no proposal generated).

``company_plan_full`` collapses the first two MODERATE gates into
one. The operator supplies the strategy_inputs as call arguments
(same shape as ``company_set_strategy_inputs``), approves once,
and the tool runs the four steps in sequence. The final operator
gate — ``company_plan_approve`` — stays separate by design: it
is the trust act that promotes ``voice_proposed.yaml`` → active,
and the operator must see the voice draft before promoting it.

Approval count: 3 MODERATE → 2 (this tool + ``company_plan_approve``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


_STRATEGY_INPUT_PASSTHROUGH: tuple[str, ...] = (
    "target_audience",
    "industry",
    "competitors",
    "current_challenges",
    "unique_selling_points",
    "budget_type",
    "budget_amount",
    "budget_period",
    "risk_tolerance",
    "primary_goals",
    "strategy_mode",
    "focus",
    "timeline_hint",
    "context",
)


class CompanyPlanFullTool(BaseTool):
    """One-shot Phase 11 strategy pipeline up to (but not including) approve."""

    def __init__(self) -> None:
        self._project_root: Path | None = None
        # The wrapper looks up its sub-tools from the registry rather
        # than duplicating their dependency injection. Each sub-tool
        # is already fully wired by Agent._inject_company_deps when
        # the wrapper is registered alongside them.
        self._registry: Any = None

    @property
    def name(self) -> str:
        return "company_plan_full"

    @property
    def group(self) -> str:
        return "companies"

    @property
    def permission_level(self) -> PermissionLevel:
        # One approval covers the bundled write side effects:
        # set_strategy_inputs (writes company.yaml) + plan_apply
        # (atomically creates mission + goals + schedules + voice
        # proposal + blockers). capabilities is SAFE; plan writes a
        # proposal artifact but doesn't mutate live state.
        return PermissionLevel.MODERATE

    @property
    def description(self) -> str:
        return (
            "Bundle PATH B of the drive-business skill: capabilities "
            "audit + set_strategy_inputs + plan + apply, all under one "
            "MODERATE approval. Operator runs company_plan_approve "
            "separately afterward (the voice/trust gate stays explicit). "
            "Use when onboarding flow needs a strategy or when re-planning."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        # Inputs are the union of (a) the strategy_inputs fields
        # ``company_set_strategy_inputs`` accepts and (b) the optional
        # plan overrides ``company_plan`` accepts. Slug is the only
        # required field — strategy_inputs may already exist on
        # company.yaml from a prior set_strategy_inputs call.
        return {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": (
                        "Company slug. Required — the wrapper does not "
                        "default to the active company because re-planning "
                        "the wrong company is the kind of operator mistake "
                        "we want to make impossible."
                    ),
                },
                "target_audience": {"type": "string"},
                "industry": {"type": "string"},
                "competitors": {"type": "string"},
                "current_challenges": {"type": "string"},
                "unique_selling_points": {"type": "string"},
                "budget_type": {"type": "string"},
                "budget_amount": {"type": "number"},
                "budget_period": {"type": "string"},
                "risk_tolerance": {"type": "integer", "minimum": 0, "maximum": 100},
                "primary_goals": {"type": "array", "items": {"type": "string"}},
                "strategy_mode": {"type": "string"},
                "focus": {"type": "string"},
                "timeline_hint": {"type": "string"},
                "context": {
                    "type": "string",
                    "description": (
                        "Optional prior research summary passed through "
                        "to both set_strategy_inputs and company_plan. "
                        "The capabilities audit is always appended."
                    ),
                },
                "override_strategy_mode": {"type": "string"},
                "override_focus": {"type": "string"},
            },
            "required": ["slug"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._project_root is None or self._registry is None:
            return ToolResult(
                success=False,
                error=(
                    "company_plan_full not initialized "
                    "(missing project_root or registry)"
                ),
            )

        slug = str(params.get("slug", "")).strip()
        if not slug:
            return ToolResult(success=False, error="slug is required")

        company_yaml = self._project_root / "companies" / slug / "company.yaml"
        if not company_yaml.is_file():
            return ToolResult(
                success=False,
                error=(
                    f"companies/{slug}/company.yaml does not exist — "
                    "run company_onboard first."
                ),
            )

        capabilities_tool = self._registry.get("company_capabilities")
        set_inputs_tool = self._registry.get("company_set_strategy_inputs")
        plan_tool = self._registry.get("company_plan")
        apply_tool = self._registry.get("company_plan_apply")

        missing = [
            name
            for name, tool in (
                ("company_capabilities", capabilities_tool),
                ("company_set_strategy_inputs", set_inputs_tool),
                ("company_plan", plan_tool),
                ("company_plan_apply", apply_tool),
            )
            if tool is None
        ]
        if missing:
            return ToolResult(
                success=False,
                error=(
                    "company_plan_full requires these tools to be "
                    f"registered: {missing}. Either run a normal Phase 11 "
                    "chain manually or fix the registry."
                ),
            )

        # ------------------------------------------------------------------
        # Step 1: capabilities audit (SAFE — no approval needed)
        # ------------------------------------------------------------------
        cap_result = await capabilities_tool.execute(
            {"company_id": slug, "write_markdown": True}
        )
        if not cap_result.success:
            return ToolResult(
                success=False,
                error=f"company_capabilities failed: {cap_result.error}",
            )
        cap_preview = (cap_result.data or {}).get("preview", "")

        # ------------------------------------------------------------------
        # Step 2: write strategy_inputs to company.yaml. Only pass through
        # the fields the operator actually supplied — set_strategy_inputs
        # merges over existing values, and we don't want None/missing to
        # clobber prior calls.
        # ------------------------------------------------------------------
        set_inputs_params: dict[str, Any] = {"slug": slug}
        for field in _STRATEGY_INPUT_PASSTHROUGH:
            if field in params and params[field] is not None:
                set_inputs_params[field] = params[field]

        set_inputs_result = await set_inputs_tool.execute(set_inputs_params)
        if not set_inputs_result.success:
            return ToolResult(
                success=False,
                error=f"company_set_strategy_inputs failed: {set_inputs_result.error}",
            )

        # ------------------------------------------------------------------
        # Step 3: generate strategy proposal artifact. Pass the
        # capabilities preview as agent context so the LLM grounds in
        # what's actually available (vault keys, registered tools by
        # group, installed skills) — same wiring the docs/76-ABE-
        # FRAMEWORK.md Phase 11 recipe recommends, just done in one
        # tool call instead of leaving it to the LLM to remember.
        # ------------------------------------------------------------------
        plan_context_parts: list[str] = []
        operator_context = params.get("context")
        if operator_context:
            plan_context_parts.append(str(operator_context))
        if cap_preview:
            plan_context_parts.append(
                "CAPABILITY AUDIT (from company_capabilities):\n" + cap_preview
            )
        plan_params: dict[str, Any] = {"company_id": slug}
        if plan_context_parts:
            plan_params["context"] = "\n\n".join(plan_context_parts)
        for override_field in ("override_strategy_mode", "override_focus"):
            if params.get(override_field):
                plan_params[override_field] = params[override_field]

        plan_result = await plan_tool.execute(plan_params)
        if not plan_result.success:
            return ToolResult(
                success=False,
                error=f"company_plan failed: {plan_result.error}",
            )
        proposal_path = (plan_result.data or {}).get("proposal_path")

        # ------------------------------------------------------------------
        # Step 4: apply the proposal. Pass the exact proposal_path we
        # just wrote so a concurrent operator-triggered plan call can't
        # race us into applying the wrong artifact.
        # ------------------------------------------------------------------
        apply_params: dict[str, Any] = {"company_id": slug}
        if proposal_path:
            apply_params["proposal_path"] = proposal_path

        apply_result = await apply_tool.execute(apply_params)
        if not apply_result.success:
            return ToolResult(
                success=False,
                error=f"company_plan_apply failed: {apply_result.error}",
            )

        # Aggregate everything operator-visible into one summary so
        # the response is one paragraph instead of four nested ones.
        apply_data = apply_result.data or {}
        return ToolResult(
            success=True,
            data={
                "slug": slug,
                "strategy_name": (plan_result.data or {}).get("strategy_name"),
                "proposal_path": proposal_path,
                "capabilities_md": (cap_result.data or {}).get("capabilities_md"),
                "strategy_inputs_path": (set_inputs_result.data or {}).get("path"),
                "tactic_count": (plan_result.data or {}).get("tactic_count"),
                "mission_id": apply_data.get("mission_id"),
                "goal_count": apply_data.get("goal_count"),
                "schedule_count": apply_data.get("schedule_count"),
                "voice_proposed_path": apply_data.get("voice_proposed_path"),
                "blockers_count": apply_data.get("blockers_count"),
                "blockers_md": apply_data.get("blockers_md"),
                "next": (
                    "Strategy applied. Review the voice proposal at "
                    f"data/companies/{slug}/voice_proposed.yaml and the "
                    f"blockers at data/companies/{slug}/blockers.md. "
                    "Run `company_plan_approve` to promote voice and "
                    "finalize the strategy."
                ),
            },
        )
