"""identity_status — view current agent identity."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class IdentityStatusTool(BaseTool):
    """View the agent's current identity profile."""

    def __init__(self) -> None:
        self._identity_manager: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return "identity_status"

    @property
    def description(self) -> str:
        return (
            "View the agent's current identity: name, purpose, values, "
            "capabilities, personality, version, and evolution history."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "description": "Specific field to show (e.g. 'capabilities', 'values'). Omit for full identity.",
                },
                "include_history": {
                    "type": "boolean",
                    "description": "Include recent evolution history. Default false.",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._identity_manager:
            return ToolResult(success=False, error="Identity system not initialized")

        identity = await self._identity_manager.get_identity()
        field = params.get("field")
        include_history = params.get("include_history", False)

        if field:
            value = getattr(identity, field, None)
            if value is None:
                return ToolResult(success=False, error=f"Unknown field: {field}")
            return ToolResult(success=True, data={"field": field, "value": value})

        data: dict[str, Any] = {
            "creator": identity.creator,
            "display_name": identity.display_name,
            "purpose": identity.purpose,
            "values": identity.values,
            "capabilities": identity.capabilities,
            "personality": identity.personality,
            "communication_style": identity.communication_style,
            "curiosities": identity.curiosities,
            "boundaries": identity.boundaries,
            "beliefs": identity.beliefs,
            "version": identity.version,
            "created_at": identity.created_at,
            "updated_at": identity.updated_at,
        }

        if include_history:
            data["evolution_history"] = await self._identity_manager.get_evolution_history(limit=10)

        return ToolResult(success=True, data=data)
