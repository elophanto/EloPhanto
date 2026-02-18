"""Schedule list tool — list and manage scheduled tasks."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class ScheduleListTool(BaseTool):
    """List and manage scheduled tasks."""

    def __init__(self) -> None:
        self._scheduler: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return "schedule_list"

    @property
    def description(self) -> str:
        return (
            "List all scheduled tasks with their status, next run time, and "
            "last result. Can also enable, disable, or delete schedules."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "enable", "disable", "delete", "history"],
                    "description": "Action to perform (default: list)",
                },
                "schedule_id": {
                    "type": "string",
                    "description": "Schedule ID (for enable/disable/delete/history)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results for history (default: 10)",
                },
            },
            "required": [],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._scheduler:
            return ToolResult(success=False, error="Scheduler not available")

        action = params.get("action", "list")
        schedule_id = params.get("schedule_id", "")

        if action == "list":
            schedules = await self._scheduler.list_schedules()
            return ToolResult(
                success=True,
                data={
                    "schedules": [
                        {
                            "id": s.id,
                            "name": s.name,
                            "cron": s.cron_expression,
                            "task_goal": s.task_goal,
                            "enabled": s.enabled,
                            "last_status": s.last_status,
                            "last_run_at": s.last_run_at,
                        }
                        for s in schedules
                    ],
                    "total": len(schedules),
                },
            )

        if not schedule_id:
            return ToolResult(
                success=False,
                error=f"schedule_id required for action '{action}'",
            )

        if action == "enable":
            await self._scheduler.enable_schedule(schedule_id)
            return ToolResult(
                success=True, data={"action": "enabled", "schedule_id": schedule_id}
            )
        elif action == "disable":
            await self._scheduler.disable_schedule(schedule_id)
            return ToolResult(
                success=True, data={"action": "disabled", "schedule_id": schedule_id}
            )
        elif action == "delete":
            await self._scheduler.delete_schedule(schedule_id)
            return ToolResult(
                success=True, data={"action": "deleted", "schedule_id": schedule_id}
            )
        elif action == "history":
            limit = params.get("limit", 10)
            history = await self._scheduler.get_run_history(schedule_id, limit)
            return ToolResult(success=True, data={"history": history})

        return ToolResult(success=False, error=f"Unknown action: {action}")
