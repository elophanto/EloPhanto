"""Proactive communication tool — lets the agent surface insights without being asked."""

from __future__ import annotations

import logging
import time
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_MAX_BRIEFS_PER_HOUR = 3
_brief_timestamps: list[float] = []


class AgentBriefTool(BaseTool):
    """Surface insights, alerts, or status updates proactively."""

    @property
    def name(self) -> str:
        return "agent_brief"

    @property
    def description(self) -> str:
        return (
            "Proactively communicate an insight, alert, or status update to the user. "
            "Use when you discover something worth reporting — goal completion, pattern "
            "detected, security event, cost anomaly, or knowledge contradiction. "
            "Priority 'actionable' bypasses rate limits."
        )

    @property
    def group(self) -> str:
        return "communication"

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "1-2 sentence insight or alert",
                },
                "details": {
                    "type": "string",
                    "description": "Optional expanded context",
                },
                "priority": {
                    "type": "string",
                    "enum": ["info", "warning", "actionable"],
                    "description": "Brief priority level",
                },
            },
            "required": ["summary", "priority"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        summary = params["summary"]
        details = params.get("details", "")
        priority = params.get("priority", "info")

        # Rate limiting (actionable bypasses)
        now = time.time()
        if priority != "actionable":
            # Clean old timestamps
            _brief_timestamps[:] = [t for t in _brief_timestamps if now - t < 3600]
            if len(_brief_timestamps) >= _MAX_BRIEFS_PER_HOUR:
                return ToolResult(
                    success=False,
                    error=f"Rate limited: max {_MAX_BRIEFS_PER_HOUR} briefs per hour. Use priority 'actionable' to bypass.",
                )

        _brief_timestamps.append(now)

        # Broadcast via gateway if available
        if hasattr(self, "_gateway") and self._gateway:
            from core.protocol import EventType, event_message

            msg = event_message(
                "",
                EventType.NOTIFICATION,
                {
                    "type": "brief",
                    "priority": priority,
                    "summary": summary,
                    "details": details,
                },
            )
            await self._gateway.broadcast(msg)

        prefix = {
            "info": "\u2139\ufe0f",
            "warning": "\u26a0\ufe0f",
            "actionable": "\U0001f514",
        }.get(priority, "\u2139\ufe0f")

        logger.info("[BRIEF/%s] %s", priority.upper(), summary)

        result_text = f"{prefix} {summary}"
        if details:
            result_text += f"\n{details}"

        return ToolResult(
            success=True, data={"brief": result_text, "priority": priority}
        )
