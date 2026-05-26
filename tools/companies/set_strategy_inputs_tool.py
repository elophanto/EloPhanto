"""company_set_strategy_inputs — capture business context for the
strategy generator (Phase 11).

Writes/updates the ``strategy_inputs:`` section of
``companies/<slug>/company.yaml``. Separate from ``company_onboard``
(which captures the product) and from ``company_set_product`` (which
revises the product) — strategy inputs are stable per-company facts
the planner needs: target audience, competitors, budget, risk
tolerance, channels, goals.

MODERATE permission so the operator sees + approves the inputs
before they shape the strategy. The agent typically calls this
after asking the operator a brief intake questionnaire.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


_VALID_BUDGET_TYPES: tuple[str, ...] = ("organic", "mixed", "paid")
_VALID_MODES: tuple[str, ...] = (
    "standard",
    "unconventional",
    "guerrilla",
    "brand-awareness",
    "controversial",
)
_VALID_FOCUS: tuple[str, ...] = (
    "full",
    "geo",
    "seo",
    "content",
    "paid",
    "social",
    "email",
    "brand",
)


class CompanySetStrategyInputsTool(BaseTool):
    def __init__(self) -> None:
        self._project_root: Path | None = None

    @property
    def name(self) -> str:
        return "company_set_strategy_inputs"

    @property
    def group(self) -> str:
        return "companies"

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    @property
    def description(self) -> str:
        return (
            "Capture the business context the strategy generator "
            "needs: target_audience, competitors, current_challenges, "
            "unique_selling_points, budget {type, amount, period}, "
            "risk_tolerance (0-100), primary_goals, strategy_mode, "
            "focus, timeline_hint. Updates the `strategy_inputs:` "
            "section of companies/<slug>/company.yaml. Call this "
            "after company_onboard and before company_plan — the "
            "plan tool reads these inputs to build the LLM brief."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "target_audience": {"type": "string"},
                "industry": {"type": "string"},
                "competitors": {"type": "string"},
                "current_challenges": {"type": "string"},
                "unique_selling_points": {"type": "string"},
                "budget_type": {
                    "type": "string",
                    "enum": list(_VALID_BUDGET_TYPES),
                },
                "budget_amount": {"type": "number"},
                "budget_period": {"type": "string"},
                "risk_tolerance": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                },
                "primary_goals": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "strategy_mode": {
                    "type": "string",
                    "enum": list(_VALID_MODES),
                },
                "focus": {"type": "string", "enum": list(_VALID_FOCUS)},
                "timeline_hint": {"type": "string"},
                "context": {
                    "type": "string",
                    "description": "Optional prior research summary.",
                },
            },
            "required": ["slug"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._project_root is None:
            return ToolResult(
                success=False,
                error="company_set_strategy_inputs not initialized (project_root)",
            )

        slug = str(params["slug"]).strip()
        if not slug:
            return ToolResult(success=False, error="slug must be non-empty")
        path = self._project_root / "companies" / slug / "company.yaml"
        if not path.is_file():
            return ToolResult(
                success=False,
                error=(
                    f"companies/{slug}/company.yaml does not exist — "
                    "run company_onboard first."
                ),
            )

        import yaml

        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            return ToolResult(success=False, error=f"company.yaml parse failed: {e}")
        if not isinstance(doc, dict):
            return ToolResult(
                success=False, error="company.yaml top-level must be a mapping"
            )

        existing = doc.get("strategy_inputs") or {}
        if not isinstance(existing, dict):
            existing = {}

        # Merge new fields over existing — explicit None / "" skipped so
        # partial updates don't clobber prior values.
        updated = dict(existing)
        budget = dict(existing.get("budget") or {})

        for field in (
            "target_audience",
            "industry",
            "competitors",
            "current_challenges",
            "unique_selling_points",
            "strategy_mode",
            "focus",
            "timeline_hint",
            "context",
        ):
            v = params.get(field)
            if v is not None and str(v).strip() != "":
                updated[field] = str(v)

        if "risk_tolerance" in params and params["risk_tolerance"] is not None:
            rt = int(params["risk_tolerance"])
            if 0 <= rt <= 100:
                updated["risk_tolerance"] = rt

        if isinstance(params.get("primary_goals"), list):
            updated["primary_goals"] = [str(g) for g in params["primary_goals"]]

        for bkey, source in (
            ("type", "budget_type"),
            ("amount", "budget_amount"),
            ("period", "budget_period"),
        ):
            if source in params and params[source] is not None:
                budget[bkey] = params[source]
        if budget:
            updated["budget"] = budget

        # Validate enums (lenient — log but accept; the generator
        # falls back to defaults for unknown modes/focus).
        if (
            updated.get("strategy_mode")
            and updated["strategy_mode"] not in _VALID_MODES
        ):
            logger.warning(
                "unknown strategy_mode %r; valid: %s",
                updated["strategy_mode"],
                _VALID_MODES,
            )
        if updated.get("focus") and updated["focus"] not in _VALID_FOCUS:
            logger.warning(
                "unknown focus %r; valid: %s", updated["focus"], _VALID_FOCUS
            )

        doc["strategy_inputs"] = updated
        try:
            path.write_text(
                yaml.safe_dump(doc, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
        except Exception as e:
            return ToolResult(success=False, error=f"company.yaml write failed: {e}")

        return ToolResult(
            success=True,
            data={
                "slug": slug,
                "path": str(path),
                "strategy_inputs": updated,
                "next": (
                    "Strategy inputs captured. Run `company_capabilities` "
                    "to audit what's available, then `company_plan` to "
                    "produce a proposed strategy."
                ),
            },
        )
