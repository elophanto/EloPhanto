"""autonomy_health — what unattended work did, and where it is stuck."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class AutonomyHealthTool(BaseTool):
    """Report on autonomous work: failures, interruptions, stalls, spend."""

    def __init__(self) -> None:
        self._db: Any = None
        self._goal_runner: Any = None

    @property
    def group(self) -> str:
        return "goals"

    @property
    def name(self) -> str:
        return "autonomy_health"

    @property
    def description(self) -> str:
        return (
            "Health of autonomous work over the last N hours: goals by status, "
            "goals active with nothing to run, checkpoints failing repeatedly, "
            "failed attempts by cause, interrupted runs, automatic recoveries, "
            "goals verified complete, and today's goal spend. Use it to answer "
            "'how is the autonomous work going?' from records, not memory."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "hours": {"type": "number", "description": "Window in hours (default 24)."}
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._db is None:
            return ToolResult(success=False, error="Database not initialized")
        from core.autonomy_health import alerts, collect, render

        hours = float(params.get("hours") or 24.0)
        report = await collect(self._db, hours=hours, runner=self._goal_runner)
        return ToolResult(
            success=True,
            data={"report": render(report), "alerts": alerts(report), "numbers": report},
        )
