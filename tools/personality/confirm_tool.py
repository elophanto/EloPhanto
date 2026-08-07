"""personality_rule_confirm — activate or reject a proposed rule."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class PersonalityRuleConfirmTool(BaseTool):
    def __init__(self) -> None:
        self._personality_manager: Any = None

    @property
    def group(self) -> str:
        return "identity"

    @property
    def name(self) -> str:
        return "personality_rule_confirm"

    @property
    def description(self) -> str:
        return (
            "Confirm (activate) or reject (retire) a proposed personality_rule. "
            "Operator trust-ladder step — same spirit as voice approve."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "rule_id": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["confirm", "reject"],
                },
            },
            "required": ["rule_id", "action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.CRITICAL

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._personality_manager:
            return ToolResult(success=False, error="Personality system not initialized")
        rid = str(params.get("rule_id") or "").strip()
        action = str(params.get("action") or "").strip()
        if not rid:
            return ToolResult(success=False, error="rule_id required")
        if action == "confirm":
            ok = await self._personality_manager.confirm_rule(rid)
        elif action == "reject":
            ok = await self._personality_manager.reject_rule(rid)
        else:
            return ToolResult(success=False, error="action must be confirm|reject")
        if not ok:
            return ToolResult(success=False, error=f"rule {rid!r} not found")
        return ToolResult(success=True, data={"rule_id": rid, "action": action})
