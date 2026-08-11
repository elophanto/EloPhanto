"""set_next_wakeup — let the mind control its own sleep interval.

Scheduling the next cycle and *starting* the loop are two different acts, and
conflating them let the agent switch itself on.

This tool used to call ``mind.start()`` whenever the loop was not running,
unconditionally. That was added for a real case — the operator says "turn on
autonomous mode" in chat and expects it to work without editing config — but
the tool cannot tell who is asking. In practice the agent called it mid-goal
with ``reason="Continue the active private writing-learning goal"`` and
started its own background loop while ``autonomous_mind.enabled`` was
``false``:

    11:09:57  Executing tool 'set_next_wakeup' {'seconds': 300, ...}
    11:09:57  Autonomous mind started (first wakeup in 240s)

``autonomous_mind.enabled`` sits in ``PROTECTED_CONFIG_KEYS`` precisely so the
agent cannot turn autonomy *off*. The protection was one-directional: nothing
stopped it turning autonomy *on*, which is the direction that costs money and
runs unattended.

So starting is now explicit and separately gated:

* Loop already running — set the interval. SAFE, unchanged.
* Loop stopped, ``enabled: true`` — start it. That is the configured
  behaviour; the operator already opted in.
* Loop stopped, ``enabled: false``, ``start_if_stopped`` omitted — schedule
  nothing and say so. The agent cannot self-start by default.
* Loop stopped, ``enabled: false``, ``start_if_stopped: true`` — CRITICAL.
  The operator sees exactly what is about to happen and approves it, which is
  what makes "turn on autonomous mode" from chat still work.
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
        "Set how many seconds until your next autonomous thinking cycle. "
        "If the autonomous mind is already running this just adjusts the "
        "interval. It does NOT start the mind on its own — when the operator "
        "has autonomous_mind.enabled set to false, that is a deliberate "
        "choice and continuing your own work is not a reason to override it. "
        "Pass start_if_stopped=true ONLY when the operator has asked you to "
        "turn autonomous mode on in this conversation; it requires their "
        "approval. Clamped to min_wakeup_seconds..max_wakeup_seconds."
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
            "start_if_stopped": {
                "type": "boolean",
                "description": (
                    "Start the autonomous mind if it is not running. Only set "
                    "this when the OPERATOR asked for autonomous mode — never "
                    "to keep your own current task going."
                ),
            },
        },
        "required": ["seconds"],
    }
    permission_level = PermissionLevel.SAFE

    # Set by AutonomousMind before use
    _mind: Any = None

    def dynamic_permission_level(
        self, params: dict[str, Any]
    ) -> PermissionLevel | None:
        """Starting an unattended loop the operator disabled always asks.

        Adjusting the interval of an already-running mind stays SAFE — that
        is housekeeping. Booting the loop against the configured setting is a
        different act and the operator decides it.
        """
        if not params.get("start_if_stopped"):
            return PermissionLevel.SAFE
        mind = self._mind
        if mind is None:
            return PermissionLevel.SAFE
        try:
            if mind.is_running:
                return PermissionLevel.SAFE
            if bool(getattr(mind._config, "enabled", False)):
                # Operator already opted in via config; starting is expected.
                return PermissionLevel.MODERATE
        except Exception:  # pragma: no cover — never block on classification
            return PermissionLevel.CRITICAL
        return PermissionLevel.CRITICAL

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        seconds = params.get("seconds", 300)
        if self._mind is None:
            return ToolResult(success=False, error="Mind not available")

        clamped = max(
            self._mind._config.min_wakeup_seconds,
            min(self._mind._config.max_wakeup_seconds, int(seconds)),
        )
        reason = params.get("reason", "")
        running = bool(self._mind.is_running)
        enabled = bool(getattr(self._mind._config, "enabled", False))
        requested_start = bool(params.get("start_if_stopped"))

        if running:
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

        # Not running. Starting is now a decision, not a side effect.
        if not (enabled or requested_start):
            return ToolResult(
                success=True,
                data={
                    "next_wakeup_seconds": clamped,
                    "reason": reason,
                    "mind_started": False,
                    "running": False,
                    "note": (
                        "The autonomous mind is not running and "
                        "autonomous_mind.enabled is false, so no wakeup was "
                        "scheduled. That setting is the operator's choice — "
                        "wanting to continue your own work does not override "
                        "it. If the OPERATOR asked for autonomous mode, call "
                        "this again with start_if_stopped=true (they will be "
                        "asked to approve). Otherwise finish in this turn and "
                        "tell them what remains."
                    ),
                },
            )

        # Either configured on, or the operator approved the start.
        await self._mind.start()
        self._mind._next_wakeup_sec = float(clamped)
        return ToolResult(
            success=True,
            data={
                "next_wakeup_seconds": clamped,
                "reason": reason,
                "mind_started": True,
                "running": bool(self._mind.is_running),
                "note": (
                    "Autonomous mind started. Tell the operator it is now "
                    "running and that `stop --hard` halts it."
                    if not enabled
                    else None
                ),
            },
        )
