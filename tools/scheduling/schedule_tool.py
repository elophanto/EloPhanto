"""Schedule task tool — create recurring or one-time scheduled tasks."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class ScheduleTaskTool(BaseTool):
    """Create a new scheduled task (recurring or one-time)."""

    def __init__(self) -> None:
        self._scheduler: Any = None

    @property
    def name(self) -> str:
        return "schedule_task"

    @property
    def description(self) -> str:
        return (
            "Schedule a task to run automatically. Supports both recurring schedules "
            "(cron or natural language like 'every morning at 9am', 'every hour') "
            "and one-time delayed tasks ('in 5 minutes', 'in 1 hour', 'at 3pm'). "
            "The task goal is executed through the full agent loop when triggered."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Human-readable name for the task",
                },
                "task_goal": {
                    "type": "string",
                    "description": "The goal/task to execute when triggered",
                },
                "schedule": {
                    "type": "string",
                    "description": (
                        "When to run. Recurring: cron expression or natural language "
                        "('every hour', 'every monday at 2pm'). One-time: 'in 5 minutes', "
                        "'in 1 hour', 'at 3pm'."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "Optional description",
                },
                "max_retries": {
                    "type": "integer",
                    "description": "Max retries on failure (default: 3 for recurring, 1 for one-time)",
                },
            },
            "required": ["name", "task_goal", "schedule"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._scheduler:
            return ToolResult(success=False, error="Scheduler not available")

        from core.scheduler import parse_delay, parse_natural_language_schedule

        schedule_text = params["schedule"]

        # Try one-time schedule first
        run_at = parse_delay(schedule_text)
        if run_at is not None:
            try:
                entry = await self._scheduler.schedule_once(
                    name=params["name"],
                    task_goal=params["task_goal"],
                    run_at=run_at,
                    description=params.get("description", ""),
                )
                return ToolResult(
                    success=True,
                    data={
                        "schedule_id": entry.id,
                        "name": entry.name,
                        "type": "one_time",
                        "run_at": run_at.isoformat(),
                        "task_goal": entry.task_goal,
                    },
                )
            except Exception as e:
                return ToolResult(success=False, error=f"Failed to schedule: {e}")

        # Fall back to recurring schedule
        try:
            cron = parse_natural_language_schedule(schedule_text)
        except ValueError as e:
            return ToolResult(success=False, error=str(e))

        try:
            entry = await self._scheduler.create_schedule(
                name=params["name"],
                task_goal=params["task_goal"],
                cron_expression=cron,
                description=params.get("description", ""),
                max_retries=params.get("max_retries", 3),
            )
            return ToolResult(
                success=True,
                data={
                    "schedule_id": entry.id,
                    "name": entry.name,
                    "type": "recurring",
                    "cron_expression": cron,
                    "original_schedule": schedule_text,
                    "task_goal": entry.task_goal,
                    "enabled": entry.enabled,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to create schedule: {e}")
