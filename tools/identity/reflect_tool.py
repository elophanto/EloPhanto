"""identity_reflect — trigger self-reflection on recent experience."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class IdentityReflectTool(BaseTool):
    """Trigger self-reflection to evolve identity based on recent experience."""

    def __init__(self) -> None:
        self._identity_manager: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return "identity_reflect"

    @property
    def description(self) -> str:
        return (
            "Trigger self-reflection on recent tasks to evolve identity. "
            "Light reflection reviews the last task; deep reflection analyzes "
            "recent patterns and updates the nature document."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "depth": {
                    "type": "string",
                    "enum": ["light", "deep"],
                    "description": "Reflection depth. 'light' checks last task, 'deep' reviews recent history.",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._identity_manager:
            return ToolResult(success=False, error="Identity system not initialized")

        depth = params.get("depth", "light")

        if depth == "deep":
            updates = await self._identity_manager.deep_reflect()
        else:
            updates = await self._identity_manager.reflect_on_task(
                goal="(manual reflection trigger)",
                outcome="completed",
                tools_used=[],
            )

        identity = await self._identity_manager.get_identity()
        return ToolResult(
            success=True,
            data={
                "depth": depth,
                "updates_applied": len(updates),
                "updates": updates[:5],
                "current_version": identity.version,
            },
        )
