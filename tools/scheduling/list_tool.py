"""Schedule list tool — list and manage scheduled tasks."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class ScheduleListTool(BaseTool):
    """List and manage scheduled tasks."""

    @property
    def group(self) -> str:
        return "scheduling"

    def __init__(self) -> None:
        self._scheduler: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return "schedule_list"

    @property
    def description(self) -> str:
        return (
            "List all scheduled tasks with their status, next run time, and "
            "last result. Can also enable, disable, delete, update, stop a "
            "running task, stop all running tasks, or view run history. "
            "Use 'update' to amend an existing schedule (cron, task_goal, "
            "name, description, max_retries) without losing the schedule_id "
            "or run history."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list",
                        "enable",
                        "disable",
                        "delete",
                        "update",
                        "history",
                        "stop",
                        "stop_all",
                    ],
                    "description": (
                        "Action to perform (default: list). 'stop' cancels an "
                        "in-flight task without disabling. 'stop_all' cancels "
                        "every running task. 'disable' and 'delete' also "
                        "cancel in-flight execution. 'update' amends fields "
                        "on an existing schedule in place."
                    ),
                },
                "schedule_id": {
                    "type": "string",
                    "description": (
                        "Schedule ID (for enable/disable/delete/update/" "history/stop)"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results for history (default: 10)",
                },
                "name": {
                    "type": "string",
                    "description": "New name (update only)",
                },
                "task_goal": {
                    "type": "string",
                    "description": "New task goal text (update only)",
                },
                "cron": {
                    "type": "string",
                    "description": (
                        "New cron expression, e.g. '0 9 * * *' (update only)"
                    ),
                },
                "description_text": {
                    "type": "string",
                    "description": "New description (update only)",
                },
                "max_retries": {
                    "type": "integer",
                    "description": "New max_retries (update only)",
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

        # Cross-schedule mutation guard: a scheduled task is NEVER allowed
        # to enable / disable / stop / delete another schedule (or itself
        # in a way that breaks the cron). The scheduler queues runs;
        # individual schedules don't get to meddle with each other. This
        # check guards against the 2026-05-15 incident where a Daily
        # Review schedule autonomously disabled three other schedules
        # right after operator policy was updated. Read-only ``list`` and
        # ``history`` stay allowed for legitimate dedupe checks.
        _MUTATING_ACTIONS = {
            "enable",
            "disable",
            "stop",
            "stop_all",
            "delete",
            "update",
        }
        if action in _MUTATING_ACTIONS:
            try:
                from core.agent import is_in_scheduled_task

                if is_in_scheduled_task():
                    return ToolResult(
                        success=False,
                        error=(
                            f"refused: schedule_list action='{action}' is not "
                            "allowed from inside a scheduled task. One schedule "
                            "must not modify another — the scheduler queues "
                            "runs; schedules do not meddle with each other. "
                            "If you believe a schedule should be changed, log "
                            "the recommendation to workspace/ for the operator "
                            "to review and apply manually."
                        ),
                    )
            except ImportError:
                pass

        if action == "stop_all":
            count = await self._scheduler.stop_all_running()
            return ToolResult(
                success=True,
                data={"action": "stop_all", "cancelled": count},
            )

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
        elif action == "stop":
            stopped = await self._scheduler.stop_running(schedule_id)
            return ToolResult(
                success=True,
                data={
                    "action": "stop",
                    "schedule_id": schedule_id,
                    "was_running": stopped,
                },
            )
        elif action == "update":
            try:
                updated = await self._scheduler.update_schedule(
                    schedule_id,
                    name=params.get("name"),
                    task_goal=params.get("task_goal"),
                    cron_expression=params.get("cron"),
                    description=params.get("description_text"),
                    max_retries=params.get("max_retries"),
                )
            except ValueError as e:
                return ToolResult(success=False, error=str(e))
            if not updated:
                return ToolResult(
                    success=False,
                    error=f"Schedule {schedule_id} not found",
                )
            return ToolResult(
                success=True,
                data={
                    "action": "updated",
                    "schedule_id": schedule_id,
                    "name": updated.name,
                    "cron": updated.cron_expression,
                    "task_goal": updated.task_goal,
                    "enabled": updated.enabled,
                },
            )

        return ToolResult(success=False, error=f"Unknown action: {action}")
