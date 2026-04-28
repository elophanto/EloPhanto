"""Heartbeat engine — periodic file-based standing orders.

Reads HEARTBEAT.md from the project root at a configurable interval.
If the file contains actionable content, the agent executes it as a task.
If the file is empty or missing, the cycle is skipped (no LLM call).

This provides a simple, non-LLM way for the user (or external automation)
to queue work: just write instructions into HEARTBEAT.md and the agent
picks them up on the next heartbeat cycle.

See docs/46-PROACTIVE-ENGINE.md for full design.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.config import HeartbeatConfig
from core.protocol import EventType, event_message

if TYPE_CHECKING:
    from core.gateway import Gateway

logger = logging.getLogger(__name__)


class HeartbeatEngine:
    """Periodic HEARTBEAT.md reader and task dispatcher."""

    def __init__(
        self,
        agent: Any,
        gateway: Gateway | None,
        config: HeartbeatConfig,
        project_root: Path,
    ) -> None:
        self._agent = agent
        self._gateway = gateway
        self._config = config
        self._project_root = project_root
        self._file_path = project_root / config.file_path

        # Lifecycle
        self._task: asyncio.Task[None] | None = None
        self._stop_requested: bool = False
        self._paused: bool = False

        # Stats
        self._cycle_count: int = 0
        self._last_check_time: str = "never"
        self._last_action: str = "(not started)"
        self._tasks_executed: int = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> bool:
        """Launch the heartbeat background task."""
        if self.is_running:
            logger.warning("Heartbeat engine already running")
            return False

        self._stop_requested = False
        self._paused = False
        self._task = asyncio.create_task(self._run_loop(), name="heartbeat-engine")
        self._task.add_done_callback(self._on_task_done)
        logger.info(
            "Heartbeat engine started (checking %s every %ds)",
            self._config.file_path,
            self._config.check_interval_seconds,
        )
        return True

    @staticmethod
    def _on_task_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Heartbeat engine crashed: %s", exc, exc_info=exc)

    async def cancel(self) -> None:
        """Stop the heartbeat engine."""
        self._stop_requested = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None

    def notify_user_interaction(self) -> None:
        """Pause heartbeat when user sends a message."""
        if self.is_running and not self._paused:
            self._paused = True

    def notify_task_complete(self) -> None:
        """Resume heartbeat after user task completes."""
        if self.is_running and self._paused:
            self._paused = False

    def get_status(self) -> dict[str, Any]:
        """Return current heartbeat state."""
        return {
            "running": self.is_running,
            "paused": self._paused,
            "cycle_count": self._cycle_count,
            "last_check": self._last_check_time,
            "last_action": self._last_action,
            "tasks_executed": self._tasks_executed,
            "file_path": str(self._file_path),
            "file_exists": self._file_path.exists(),
            "interval_seconds": self._config.check_interval_seconds,
        }

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Background loop: sleep → check file → execute if needed → sleep."""
        try:
            while not self._stop_requested:
                await asyncio.sleep(self._config.check_interval_seconds)

                if self._stop_requested:
                    break

                if self._paused:
                    continue

                try:
                    await self._check_and_execute()
                    self._cycle_count += 1
                except Exception as e:
                    logger.error("Heartbeat cycle error: %s", e, exc_info=True)

        except asyncio.CancelledError:
            logger.info("Heartbeat engine cancelled")
            raise
        finally:
            self._task = None

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    async def _check_and_execute(self) -> None:
        """Read HEARTBEAT.md and execute if it has content."""
        from datetime import UTC, datetime

        self._last_check_time = datetime.now(UTC).strftime("%H:%M UTC")

        # Read the file
        content = self._read_heartbeat_file()

        if not content:
            # Nothing to do — skip LLM call entirely
            if not self._config.suppress_idle:
                await self._broadcast_event(
                    EventType.HEARTBEAT_IDLE,
                    {"file": self._config.file_path, "reason": "empty_or_missing"},
                )
            return

        await self._broadcast_event(
            EventType.HEARTBEAT_CHECK,
            {
                "file": self._config.file_path,
                "content_length": len(content),
                "preview": content[:200].strip(),
            },
        )

        # Execute the heartbeat content as an agent task
        cycle_start = time.monotonic()

        # Isolate conversation history (same pattern as AutonomousMind)
        saved_history = list(self._agent._conversation_history)
        self._agent._conversation_history.clear()

        # Auto-approve tools during heartbeat execution
        prev_approval = self._agent._executor._approval_callback

        async def _auto_approve(
            tool_name: str, description: str, params: dict[str, Any]
        ) -> bool:
            if self._gateway:
                from core.protocol import approval_request_message

                msg = approval_request_message(
                    session_id="",
                    tool_name=tool_name,
                    description=f"[Heartbeat] {description}",
                    params=params,
                )
                future: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
                self._gateway._pending_approvals[msg.id] = future
                await self._gateway.broadcast(msg, session_id=None)
                try:
                    return await asyncio.wait_for(future, timeout=120)
                except TimeoutError:
                    return False
                finally:
                    self._gateway._pending_approvals.pop(msg.id, None)
            return True

        self._agent._executor.set_approval_callback(_auto_approve)

        try:
            prompt = (
                "You are executing a heartbeat task. "
                "The following instructions were found in HEARTBEAT.md. "
                "Follow them strictly. Do not infer or repeat old tasks from prior chats. "
                "If all instructions are already completed, reply HEARTBEAT_OK.\n\n"
                f"---\n{content}\n---"
            )

            # Acquire the action queue so heartbeat doesn't race with
            # scheduled / mind / user tasks for the browser. Skip this
            # cycle if another task is holding it for >10 min.
            from core.action_queue import TaskPriority

            try:
                async with self._agent._action_queue.acquire(
                    TaskPriority.HEARTBEAT, timeout=600.0
                ):
                    response = await self._agent.run(
                        prompt,
                        max_steps_override=self._config.max_rounds,
                    )
            except TimeoutError:
                logger.warning(
                    "Heartbeat skipped — action queue held >10 min by "
                    "another task. Will retry next cycle."
                )
                return

            elapsed = time.monotonic() - cycle_start
            response_text = (response.content or "")[:500]

            # Check if agent indicated nothing to do
            is_idle = "HEARTBEAT_OK" in (response_text or "").upper()

            if is_idle:
                self._last_action = "HEARTBEAT_OK (all tasks complete)"
                if not self._config.suppress_idle:
                    await self._broadcast_event(
                        EventType.HEARTBEAT_IDLE,
                        {"reason": "all_complete", "elapsed": f"{elapsed:.1f}s"},
                    )
            else:
                action_summary = (
                    response_text.split("\n")[0][:120]
                    if response_text
                    else "(no output)"
                )
                self._last_action = action_summary
                self._tasks_executed += 1

                await self._broadcast_event(
                    EventType.HEARTBEAT_ACTION,
                    {
                        "summary": action_summary,
                        "elapsed": f"{elapsed:.1f}s",
                        "cycle": self._cycle_count + 1,
                    },
                )
        finally:
            self._agent._conversation_history = saved_history
            self._agent._executor._approval_callback = prev_approval

    def _read_heartbeat_file(self) -> str:
        """Read HEARTBEAT.md and return its content, or empty string."""
        if not self._file_path.exists():
            return ""
        try:
            content = self._file_path.read_text(encoding="utf-8").strip()
            return content
        except OSError as e:
            logger.warning("Failed to read %s: %s", self._file_path, e)
            return ""

    # ------------------------------------------------------------------
    # Event broadcasting
    # ------------------------------------------------------------------

    async def _broadcast_event(
        self, event_type: EventType, data: dict[str, Any]
    ) -> None:
        if self._gateway:
            await self._gateway.broadcast(
                event_message("", event_type, data), session_id=None
            )
        else:
            logger.info("Heartbeat event [%s]: %s", event_type, data)
