"""set_next_wakeup — let the mind control its own sleep interval."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class SetNextWakeupTool(BaseTool):
    """Control how many seconds until the next autonomous think cycle."""

    name = "set_next_wakeup"
    description = (
        "Set how many seconds until your next autonomous thinking cycle. "
        "Use shorter intervals (60-120s) when actively monitoring something, "
        "longer intervals (600-1800s) when nothing is happening. Range: 60-3600."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "seconds": {
                "type": "integer",
                "description": "Seconds until next wakeup (60-3600)",
            },
            "reason": {
                "type": "string",
                "description": "Brief reason for this interval",
            },
        },
        "required": ["seconds"],
    }
    permission_level = PermissionLevel.SAFE

    # Set by AutonomousMind before use
    _mind: Any = None

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        seconds = params.get("seconds", 300)
        if self._mind is None:
            return ToolResult(success=False, error="Mind not available")

        clamped = max(
            self._mind._config.min_wakeup_seconds,
            min(self._mind._config.max_wakeup_seconds, int(seconds)),
        )
        self._mind._next_wakeup_sec = float(clamped)
        reason = params.get("reason", "")
        return ToolResult(
            success=True,
            data={"next_wakeup_seconds": clamped, "reason": reason},
        )
