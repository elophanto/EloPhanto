"""company_set_posture — maturity × objective for an ABE company.

MODERATE. Writes ``posture:`` on ``companies/<slug>/company.yaml`` and
mirrors maturity into ``strategy_inputs`` so ``company_plan`` picks it up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class CompanySetPostureTool(BaseTool):
    def __init__(self) -> None:
        self._project_root: Path | None = None

    @property
    def name(self) -> str:
        return "company_set_posture"

    @property
    def group(self) -> str:
        return "companies"

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    @property
    def description(self) -> str:
        return (
            "Set company operating posture: maturity "
            "(pre_revenue|early|scaling|established) × objective "
            "(validate|growth|profit|balance). Reshapes arbiter "
            "attention, role rotation, strategy breadth, and spend "
            "envelopes. Optional intent preset: startup_founder, "
            "established, profitability, growth. MODERATE."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        from core.posture import (
            INTENT_PRESETS,
            VALID_MATURITY,
            VALID_OBJECTIVE,
        )

        return {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "Company slug (must have company.yaml).",
                },
                "maturity": {
                    "type": "string",
                    "enum": list(VALID_MATURITY),
                    "description": (
                        "Channel/ops breadth. pre_revenue=one channel; "
                        "early=primary+capped experiment; scaling=multi-surface; "
                        "established=multi-surface + retention/ops weight."
                    ),
                },
                "objective": {
                    "type": "string",
                    "enum": list(VALID_OBJECTIVE),
                    "description": (
                        "Attention mandate. validate=paying signal first; "
                        "growth=pipeline velocity; profit=net/runway; "
                        "balance=steady ops."
                    ),
                },
                "intent": {
                    "type": "string",
                    "enum": list(INTENT_PRESETS.keys()),
                    "description": (
                        "Optional preset that fills maturity+objective: "
                        "startup_founder, established, profitability, growth. "
                        "Explicit maturity/objective override the preset."
                    ),
                },
            },
            "required": ["slug"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._project_root is None:
            return ToolResult(
                success=False,
                error="company_set_posture not initialized (project_root)",
            )

        from core.posture import (
            INTENT_PRESETS,
            VALID_MATURITY,
            VALID_OBJECTIVE,
            Posture,
            load_posture,
            normalize_maturity,
            normalize_objective,
            save_posture,
        )

        slug = str(params.get("slug") or "").strip()
        if not slug:
            return ToolResult(success=False, error="slug must be non-empty")

        current = load_posture(self._project_root, slug)
        maturity = current.maturity
        objective = current.objective

        intent = str(params.get("intent") or "").strip().lower()
        if intent:
            if intent not in INTENT_PRESETS:
                return ToolResult(
                    success=False,
                    error=(
                        f"unknown intent {intent!r}; valid: "
                        f"{', '.join(INTENT_PRESETS)}"
                    ),
                )
            maturity, objective = INTENT_PRESETS[intent]

        if params.get("maturity") is not None and str(params["maturity"]).strip():
            raw_m = str(params["maturity"]).strip().lower()
            if raw_m not in VALID_MATURITY:
                return ToolResult(
                    success=False,
                    error=f"invalid maturity {raw_m!r}; valid: {VALID_MATURITY}",
                )
            maturity = normalize_maturity(raw_m)

        if params.get("objective") is not None and str(params["objective"]).strip():
            raw_o = str(params["objective"]).strip().lower()
            if raw_o not in VALID_OBJECTIVE:
                return ToolResult(
                    success=False,
                    error=f"invalid objective {raw_o!r}; valid: {VALID_OBJECTIVE}",
                )
            objective = normalize_objective(raw_o)

        if (
            params.get("maturity") is None
            and params.get("objective") is None
            and not intent
        ):
            return ToolResult(
                success=False,
                error=(
                    "Provide intent=… and/or maturity=… and/or objective=…. "
                    f"Current posture: {current.label()}"
                ),
            )

        posture = Posture(maturity=maturity, objective=objective)
        try:
            path = save_posture(self._project_root, slug, posture)
        except FileNotFoundError as e:
            return ToolResult(success=False, error=str(e))
        except ValueError as e:
            return ToolResult(success=False, error=str(e))

        return ToolResult(
            success=True,
            data={
                "slug": slug,
                "posture": posture.as_dict(),
                "label": posture.label(),
                "path": str(path),
                "previous": current.as_dict(),
                "note": (
                    "Maturity mirrored to strategy_inputs.maturity for "
                    "company_plan. Arbiter/role/spend pick this up next cycle."
                ),
            },
        )
