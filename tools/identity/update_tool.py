"""identity_update — update a specific identity field."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class IdentityUpdateTool(BaseTool):
    """Update a specific field of the agent's identity."""

    def __init__(self) -> None:
        self._identity_manager: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return "identity_update"

    @property
    def description(self) -> str:
        return (
            "Update a specific identity field (e.g. add a capability, "
            "change communication style, update beliefs with account info). "
            "Requires a reason for the change."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "description": (
                        "Field to update: display_name, purpose, values, beliefs, "
                        "curiosities, boundaries, capabilities, personality, communication_style"
                    ),
                },
                "value": {
                    "description": "New value. For list fields, a string to add. For others, the replacement value.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this update is being made.",
                },
            },
            "required": ["field", "value", "reason"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._identity_manager:
            return ToolResult(success=False, error="Identity system not initialized")

        field = params.get("field", "").strip()
        value = params.get("value")
        reason = params.get("reason", "").strip()

        if not field:
            return ToolResult(success=False, error="Field is required")
        if not value:
            return ToolResult(success=False, error="Value is required")
        if not reason:
            return ToolResult(success=False, error="Reason is required")

        ok = await self._identity_manager.update_field(field, value, reason, trigger="explicit")
        if not ok:
            return ToolResult(
                success=False,
                error=f"Failed to update '{field}'. It may be immutable or unknown.",
            )

        identity = await self._identity_manager.get_identity()
        return ToolResult(
            success=True,
            data={
                "field": field,
                "new_value": getattr(identity, field, value),
                "version": identity.version,
                "reason": reason,
            },
        )
