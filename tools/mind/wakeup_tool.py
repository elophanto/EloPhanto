"""set_next_wakeup — let the mind control its own sleep interval."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class SetNextWakeupTool(BaseTool):
    """Control how many seconds until the next autonomous think cycle."""

    @property
    def group(self) -> str:
        return "mind"

    name = "set_next_wakeup"
    description = (
        "Set how many seconds until your next autonomous thinking cycle. "
        "Starts the autonomous mind if it is not already running "
        "(needed when autonomous_mind.enabled is false at boot). "
        "Use shorter intervals when actively monitoring something, "
        "longer intervals when nothing is happening. "
        "Clamped to min_wakeup_seconds..max_wakeup_seconds from config."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "seconds": {
                "type": "integer",
                "description": "Seconds until next wakeup (clamped to config min/max)",
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
        reason = params.get("reason", "")

        # Chat "turn on autonomous mode" used to call this tool alone.
        # set_next_wakeup only wrote _next_wakeup_sec — it never started
        # the background loop — so nothing woke up when enabled=false at
        # boot. Start first; start() resets the interval to config, so
        # apply the requested clamp afterward.
        started = False
        if not self._mind.is_running:
            await self._mind.start()
            started = True

        self._mind._next_wakeup_sec = float(clamped)
        return ToolResult(
            success=True,
            data={
                "next_wakeup_seconds": clamped,
                "reason": reason,
                "mind_started": started,
                "running": bool(self._mind.is_running),
            },
        )
