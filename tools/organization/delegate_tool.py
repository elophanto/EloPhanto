"""organization_delegate — Send a task to a specialist child agent."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class OrganizationDelegateTool(BaseTool):
    """Delegate a task to a running specialist agent."""

    def __init__(self) -> None:
        self._organization_manager: Any = None

    @property
    def name(self) -> str:
        return "organization_delegate"

    @property
    def description(self) -> str:
        return (
            "Send a task to a specialist child agent. You can specify either "
            "a child_id or a role (which will auto-resolve to the specialist "
            "for that role). The specialist must be running."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task to delegate to the specialist.",
                },
                "child_id": {
                    "type": "string",
                    "description": "ID of the specialist (use organization_status to find IDs).",
                },
                "role": {
                    "type": "string",
                    "description": (
                        "Role of the specialist (e.g. 'marketing'). "
                        "Alternative to child_id — auto-resolves to the specialist for this role."
                    ),
                },
            },
            "required": ["task"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._organization_manager:
            return ToolResult(error="Organization system is not enabled.")

        task = kwargs.get("task", "")
        if not task:
            return ToolResult(error="'task' is required.")

        child_id = kwargs.get("child_id", "")
        role = kwargs.get("role", "")

        if not child_id and not role:
            return ToolResult(error="Either 'child_id' or 'role' must be provided.")

        # Resolve child_id from role
        if not child_id and role:
            child = self._organization_manager._find_by_role(role)
            if not child:
                return ToolResult(
                    error=f"No specialist found for role '{role}'. "
                    "Use organization_spawn to create one."
                )
            child_id = child.child_id

        try:
            result = await self._organization_manager.send_task(child_id, task)
            return ToolResult(data=result)
        except Exception as e:
            return ToolResult(error=str(e))
