"""email_monitor — start/stop/status for background inbox monitoring."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class EmailMonitorTool(BaseTool):
    """Control background email inbox monitoring via conversation."""

    def __init__(self) -> None:
        self._email_monitor: Any = None

    @property
    def name(self) -> str:
        return "email_monitor"

    @property
    def description(self) -> str:
        return (
            "Start, stop, or check status of background monitoring of the agent's "
            "own email inbox. When active, new emails to the agent's address trigger "
            "notifications to all connected channels (CLI, Telegram, Discord, Slack) "
            "without manual checking. This monitors the agent's inbox, not the user's."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "status"],
                    "description": (
                        "start: begin polling for new emails. "
                        "stop: stop the background monitor. "
                        "status: check if monitoring is active."
                    ),
                },
                "poll_interval_minutes": {
                    "type": "integer",
                    "description": (
                        "How often to check for new emails (minutes). "
                        "Default: 5. Only used with action=start."
                    ),
                },
            },
            "required": ["action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._email_monitor:
            return ToolResult(
                success=False,
                error="Email monitor not available — email system may not be configured.",
            )

        action = params["action"]

        if action == "start":
            if self._email_monitor.is_running:
                return ToolResult(
                    success=True,
                    data={
                        "status": "already_running",
                        "message": "Email monitor is already active.",
                    },
                )
            interval = params.get("poll_interval_minutes")
            self._email_monitor.start(poll_interval_minutes=interval)
            return ToolResult(
                success=True,
                data={
                    "status": "started",
                    "poll_interval_minutes": interval
                    or self._email_monitor._poll_interval_minutes,
                    "message": "Email monitor started. You'll be notified of new emails.",
                },
            )

        if action == "stop":
            if not self._email_monitor.is_running:
                return ToolResult(
                    success=True,
                    data={
                        "status": "not_running",
                        "message": "Email monitor is not active.",
                    },
                )
            await self._email_monitor.stop()
            return ToolResult(
                success=True,
                data={"status": "stopped", "message": "Email monitor stopped."},
            )

        if action == "status":
            return ToolResult(
                success=True,
                data={
                    "is_running": self._email_monitor.is_running,
                    "poll_interval_minutes": self._email_monitor._poll_interval_minutes,
                    "seen_count": len(self._email_monitor._seen_ids),
                },
            )

        return ToolResult(success=False, error=f"Unknown action: {action}")
