"""organization_status — List specialist child agents and performance."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class OrganizationStatusTool(BaseTool):
    """View the status of specialist child agents."""

    def __init__(self) -> None:
        self._organization_manager: Any = None

    @property
    def name(self) -> str:
        return "organization_status"

    @property
    def description(self) -> str:
        return (
            "List all specialist child agents with their status, trust score, "
            "and performance metrics. Optionally filter by child_id for details."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "child_id": {
                    "type": "string",
                    "description": "Optional: filter to a specific specialist.",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._organization_manager:
            return ToolResult(error="Organization system is not enabled.")

        children = self._organization_manager.list_children()
        child_id = kwargs.get("child_id", "")

        if child_id:
            children = [c for c in children if c["child_id"] == child_id]
            if not children:
                return ToolResult(error=f"No specialist found with id '{child_id}'.")

        return ToolResult(
            data={
                "specialists": children,
                "total": len(children),
                "running": sum(1 for c in children if c["status"] == "running"),
            }
        )
