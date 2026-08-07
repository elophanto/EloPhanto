"""personality_rule_propose — propose a measurable stance rule."""

from __future__ import annotations

from typing import Any

from core.personality import MeasurableObservable, default_observable_for_kind
from tools.base import BaseTool, PermissionLevel, ToolResult


class PersonalityRuleProposeTool(BaseTool):
    def __init__(self) -> None:
        self._personality_manager: Any = None

    @property
    def group(self) -> str:
        return "identity"

    @property
    def name(self) -> str:
        return "personality_rule_propose"

    @property
    def description(self) -> str:
        return (
            "Propose a durable personality stance rule with a measurable "
            "observable (brevity / anti_hype / deference / custom). "
            "Does not activate until personality_rule_confirm."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "rule": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": ["brevity", "anti_hype", "deference", "custom"],
                },
                "evidence_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "measurable": {
                    "type": "object",
                    "description": "Optional override of measurable_observable",
                },
            },
            "required": ["rule", "kind"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._personality_manager:
            return ToolResult(success=False, error="Personality system not initialized")
        kind = str(params.get("kind") or "custom")
        measurable_raw = params.get("measurable")
        if isinstance(measurable_raw, dict) and measurable_raw:
            measurable = MeasurableObservable.from_dict(measurable_raw)
        else:
            measurable = default_observable_for_kind(kind)
        try:
            rule = await self._personality_manager.propose_rule(
                rule=str(params.get("rule") or ""),
                kind=kind,
                measurable=measurable,
                evidence_ids=list(params.get("evidence_ids") or []),
            )
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        return ToolResult(
            success=True,
            data={
                "id": rule.id,
                "status": rule.status,
                "kind": rule.kind,
                "rule": rule.rule,
                "cite": rule.cite_token(),
                "note": "proposed — operator must confirm to activate",
            },
        )
