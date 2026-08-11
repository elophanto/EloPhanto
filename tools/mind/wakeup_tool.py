"""set_next_wakeup — pace the mind's own sleep interval. Nothing more.

This tool used to call ``mind.start()`` whenever the loop was not running.
The agent used that to switch itself on mid-goal, with
``reason="Continue the active private writing-learning goal"``, while the
operator had ``autonomous_mind.enabled: false``:

    11:09:57  Executing tool 'set_next_wakeup' {'seconds': 300, ...}
    11:09:57  Autonomous mind started (first wakeup in 240s)

``autonomous_mind.enabled`` is the switch, and it is the operator's. Off means
off — not "off unless the agent asks nicely", and not "off unless someone
approves a prompt". A setting that any sufficiently motivated caller can talk
its way past is not a setting.

So this tool only ever adjusts *timing*, and only while the mind is already
running. When the mind is stopped it schedules nothing and says why. Turning
autonomy on is a config change the operator makes deliberately —
``autonomous_mind.enabled: true`` — and there is no in-band path to it.
"""

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
        "Adjust how many seconds until your next autonomous thinking cycle. "
        "This ONLY works while the autonomous mind is already running — it "
        "cannot start it. If autonomous mode is off, it is off: that is the "
        "operator's setting, and needing more time to finish your own work is "
        "not a reason to reach for it. When the mind is stopped, finish in "
        "this turn and tell the operator what remains. "
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
    # Pacing a loop that is already running is housekeeping. There is no
    # path here that starts anything, so there is nothing to escalate.
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

        if not self._mind.is_running:
            return ToolResult(
                success=True,
                data={
                    "next_wakeup_seconds": None,
                    "reason": reason,
                    "mind_started": False,
                    "running": False,
                    "note": (
                        "The autonomous mind is not running, so no wakeup was "
                        "scheduled and none will happen. Only the operator can "
                        "turn autonomous mode on, by setting "
                        "`autonomous_mind.enabled: true` in config.yaml. "
                        "Finish what you can in this turn and tell them what "
                        "is left."
                    ),
                },
            )

        self._mind._next_wakeup_sec = float(clamped)
        return ToolResult(
            success=True,
            data={
                "next_wakeup_seconds": clamped,
                "reason": reason,
                "mind_started": False,
                "running": True,
            },
        )
