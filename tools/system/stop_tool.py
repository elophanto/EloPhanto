"""``agent_stop`` — cancel the CURRENT chat action only.

The deterministic ``stop`` / ``/stop`` / ``halt`` / ``kill`` / ``pause``
slash-command intercept in the gateway catches the operator's exact
stop tokens BEFORE the LLM sees them and cancels the in-flight
session task directly. This tool covers the natural-language path —
when the operator says "hold on stop that" or "there is a running
goal, can you stop it?", the LLM recognizes the intent and calls
this tool.

**Scope: current chat action only.** Cancels the in-flight
``run_session`` task for THIS session. The autonomous mind keeps
running, the scheduler keeps firing, other channels' sessions
keep going. There is NO sentinel write, NO goal cancellation,
NO schedule disabling. Operators who genuinely want to halt
everything use ``stop --hard`` in chat (gateway intercept handles
it) or ``elophanto stop`` from the terminal.

Permission tier MODERATE — operator approves explicitly so the LLM
can't accidentally cancel itself during normal planning.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class AgentStopTool(BaseTool):
    """Cancel the current session's in-flight agent.run."""

    def __init__(self) -> None:
        self._gateway: Any = None

    @property
    def name(self) -> str:
        return "agent_stop"

    @property
    def group(self) -> str:
        return "system"

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    @property
    def description(self) -> str:
        return (
            "Cancel the current chat action only (this session). Mind, "
            "scheduler, other sessions unaffected. For full system "
            "halt the operator types `stop --hard` in chat."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        # Locate the current in-flight task — it's the asyncio task
        # the LLM is currently running inside. Match against the
        # gateway's tracked dict to ensure we only cancel a tracked
        # session task, not the autonomous mind or a scheduled job.
        current = asyncio.current_task()
        if current is None:
            return ToolResult(
                success=False,
                error=(
                    "agent_stop: no current asyncio task — not running "
                    "inside a chat session."
                ),
            )

        if self._gateway is None:
            return ToolResult(
                success=False,
                error=(
                    "agent_stop: gateway reference missing — direct-mode "
                    "agents should use Ctrl+C to cancel. This tool is "
                    "only available in gateway-backed chat (the canonical "
                    "operator path)."
                ),
            )

        tracked = getattr(self._gateway, "_inflight_run_tasks", {}) or {}
        target_session_id: str | None = None
        for sid, task in tracked.items():
            if task is current or current in _ancestors(current, task):
                target_session_id = sid
                break

        if target_session_id is None:
            # Not in a tracked run_session task. Could be a scheduled
            # task, autonomous mind, or other context. Refuse — we
            # don't want to accidentally cancel the wrong loop.
            return ToolResult(
                success=False,
                error=(
                    "agent_stop: current task is not a chat session "
                    "run. To cancel an autonomous-mind goal, use "
                    "the goal management tools. To halt everything, "
                    "tell the operator to use `stop --hard` or "
                    "`elophanto stop`."
                ),
            )

        target_task = tracked[target_session_id]
        if target_task.done():
            return ToolResult(
                success=True,
                data={
                    "session_id": target_session_id,
                    "cancelled": False,
                    "note": "Task already done — nothing to cancel.",
                },
            )

        # Schedule cancellation. The next await in this task will
        # raise asyncio.CancelledError; the gateway's wrapper catches
        # it and sends a "Cancelling current action" response.
        target_task.cancel()
        logger.info(
            "agent_stop: cancelled session %s in-flight run via LLM tool",
            target_session_id[:8],
        )
        return ToolResult(
            success=True,
            data={
                "session_id": target_session_id,
                "cancelled": True,
                "next": (
                    "Your task is being cancelled. The operator will "
                    "see a 'Cancelling current action' confirmation. "
                    "Autonomous mind + scheduler keep running."
                ),
            },
        )


def _ancestors(current: Any, target: Any) -> list[Any]:
    """Walk the asyncio task chain — currently a no-op placeholder.

    asyncio doesn't expose a clean way to walk a task's parent chain
    in user code; tasks scheduled inside the current task aren't
    parent/child related the way OS processes are. Match by identity
    only for now. If a tool spawns a sub-task and runs the LLM inside,
    the LLM tool wouldn't be able to identify its outer session — we
    can extend this with a contextvar later if that case matters.
    """
    return []
