"""Parent channel adapter — connects a child agent to its master's gateway.

This adapter runs inside child agent instances. It connects to the master's
gateway WebSocket and handles bidirectional communication:

  Child → Master:
    - Reports (work completed, findings, status updates)
    - Approval requests (child wants master to review output)

  Master → Child:
    - Task assignments (delegated work)
    - Feedback (approvals, rejections, corrections)
    - Teaching (pushed knowledge)

The child appears to the master gateway as channel="child:{child_id}".
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from channels.base import ChannelAdapter
from core.protocol import EventType, GatewayMessage, MessageType

logger = logging.getLogger(__name__)


class ParentChannelAdapter(ChannelAdapter):
    """Connects a child agent to its parent master's gateway.

    This is the child-side counterpart to the organization system.
    The master spawns children and they connect back using this adapter.
    """

    name = "parent"

    def __init__(
        self,
        parent_host: str = "127.0.0.1",
        parent_port: int = 18789,
        child_id: str = "",
        auth_token: str = "",
    ) -> None:
        gateway_url = f"ws://{parent_host}:{parent_port}"
        super().__init__(gateway_url)
        self._child_id = child_id
        self._auth_token = auth_token
        self._parent_host = parent_host
        self._parent_port = parent_port
        self._task_queue: asyncio.Queue[str] = asyncio.Queue()
        self._feedback_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._listener_task: asyncio.Task[None] | None = None

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to master gateway and start listening."""
        try:
            await self.connect_gateway()
            self._listener_task = asyncio.create_task(
                self.gateway_listener(), name=f"parent-listener-{self._child_id}"
            )
            logger.info(
                "Parent adapter connected to master at %s:%d (child=%s)",
                self._parent_host,
                self._parent_port,
                self._child_id,
            )
        except Exception as e:
            logger.error("Failed to connect to master gateway: %s", e)
            raise

    async def stop(self) -> None:
        """Disconnect from master gateway."""
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        self._listener_task = None
        await self.disconnect_gateway()
        logger.info("Parent adapter disconnected (child=%s)", self._child_id)

    # ── Child → Master: Sending ──────────────────────────────────────

    async def send_report(self, content: str, task_ref: str = "") -> None:
        """Send a work report to the master."""
        msg = GatewayMessage(
            type=MessageType.EVENT,
            channel=f"child:{self._child_id}",
            user_id=self._child_id,
            data={
                "event": EventType.CHILD_REPORT,
                "content": content,
                "task_ref": task_ref,
                "child_id": self._child_id,
            },
        )
        await self.send_to_gateway(msg)
        logger.debug("Sent report to master: %s", content[:80])

    async def request_approval(self, task: str, result: str) -> None:
        """Request master approval for completed work."""
        msg = GatewayMessage(
            type=MessageType.EVENT,
            channel=f"child:{self._child_id}",
            user_id=self._child_id,
            data={
                "event": EventType.CHILD_APPROVAL_REQUEST,
                "task": task,
                "result": result,
                "child_id": self._child_id,
            },
        )
        await self.send_to_gateway(msg)
        logger.debug("Requested approval for: %s", task[:80])

    # ── Master → Child: Receiving ────────────────────────────────────

    async def receive_task(self, timeout: float = 0) -> str | None:
        """Wait for a task assignment from master.

        Returns None if timeout expires (0 = non-blocking check).
        """
        try:
            if timeout <= 0:
                return self._task_queue.get_nowait()
            return await asyncio.wait_for(self._task_queue.get(), timeout=timeout)
        except (asyncio.QueueEmpty, TimeoutError):
            return None

    async def receive_feedback(self, timeout: float = 0) -> dict[str, Any] | None:
        """Wait for feedback from master.

        Returns None if timeout expires (0 = non-blocking check).
        """
        try:
            if timeout <= 0:
                return self._feedback_queue.get_nowait()
            return await asyncio.wait_for(self._feedback_queue.get(), timeout=timeout)
        except (asyncio.QueueEmpty, TimeoutError):
            return None

    # ── Gateway Message Handlers ─────────────────────────────────────

    async def on_response(self, msg: GatewayMessage) -> None:
        """Handle a response from master (typically a task result or ack)."""
        content = msg.data.get("content", "")
        if content:
            logger.info("Master response: %s", content[:100])

    async def on_approval_request(self, msg: GatewayMessage) -> None:
        """Handle approval requests from master (auto-approve for children)."""
        # Children auto-approve tool use from master instructions
        await self.send_approval(msg.id, approved=True)

    async def on_event(self, msg: GatewayMessage) -> None:
        """Handle events from master — task assignments and feedback."""
        event = msg.data.get("event", "")

        if event == EventType.CHILD_TASK_ASSIGNED:
            task = msg.data.get("task", "")
            if task:
                await self._task_queue.put(task)
                logger.info("Received task from master: %s", task[:80])

        elif event == EventType.CHILD_FEEDBACK:
            feedback = {
                "approved": msg.data.get("approved", True),
                "task_ref": msg.data.get("task_ref", ""),
                "feedback": msg.data.get("feedback", ""),
            }
            await self._feedback_queue.put(feedback)
            status = "approved" if feedback["approved"] else "rejected"
            logger.info(
                "Received feedback from master: %s — %s",
                status,
                feedback["feedback"][:80] if feedback["feedback"] else "",
            )

        else:
            logger.debug("Unhandled parent event: %s", event)
