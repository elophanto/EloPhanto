"""kid_agent — channel adapter that runs INSIDE a kid container.

Boot path:
    Dockerfile.kid CMD → core.kid_bootstrap.kid_main()
    kid_bootstrap → consume KID_VAULT_JSON → build kid Config → Agent()
                  → KidAgentAdapter(agent=...) → adapter.start()

The adapter's job is the wire-protocol piece: keep a WebSocket open to
the parent's gateway, dispatch CHILD_TASK_ASSIGNED events to the local
agent, and stream responses back as gateway chat messages.

Tasks run sequentially per kid (one container = one agent loop). If the
parent wants concurrency it spawns more kids.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from channels.base import ChannelAdapter
from core.protocol import GatewayMessage, MessageType, chat_message

logger = logging.getLogger(__name__)


class KidAgentAdapter(ChannelAdapter):
    """Adapter run inside a kid container.

    Wraps an `Agent` instance built by `core.kid_bootstrap`. On task
    assignment from the parent, runs `agent.run(task)` and sends the
    result back as a chat message tagged with this kid's id.
    """

    name = "kid-agent"

    def __init__(self, agent: Any | None = None) -> None:
        gateway_url = os.environ.get(
            "ELOPHANTO_PARENT_GATEWAY", "ws://host.docker.internal:18789"
        )
        super().__init__(gateway_url=gateway_url)
        self._kid_id = os.environ.get("ELOPHANTO_KID_ID", "unknown")
        self._kid_name = os.environ.get("ELOPHANTO_KID_NAME", "kid")
        self._purpose = os.environ.get("KID_PURPOSE", "")
        self._agent = agent  # Agent instance from kid_bootstrap; may be None in tests

        # Tasks are queued so a slow task doesn't block the websocket
        # reader. Bounded to prevent runaway parents from queueing
        # infinite work — over the cap, drop new tasks with an explicit
        # rejection chat.
        self._task_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=8)
        self._worker_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Connect to the parent gateway and process tasks until cancelled."""
        logger.info(
            "Kid adapter starting: kid_id=%s name=%s gateway=%s",
            self._kid_id,
            self._kid_name,
            self._gateway_url,
        )
        await self.connect_gateway()
        # Register so the parent gateway sees us under (channel, user_id).
        await self._send_chat(
            f"[kid {self._kid_name} online; purpose: {self._purpose[:200]}]"
        )

        # Worker drains the task queue so message reading is never blocked.
        self._worker_task = asyncio.create_task(
            self._task_worker(), name=f"kid-{self._kid_id}-worker"
        )

        async for raw in self._ws:
            try:
                msg = GatewayMessage.from_json(raw)
            except Exception as e:
                logger.debug("could not parse message: %s", e)
                continue
            if msg.type == MessageType.EVENT:
                await self.on_event(msg)
            elif msg.type == MessageType.RESPONSE:
                await self.on_response(msg)
            elif msg.type == MessageType.APPROVAL_REQUEST:
                await self.on_approval_request(msg)

    async def stop(self) -> None:
        self._running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    # ── Event handlers ─────────────────────────────────────────────

    async def on_response(self, msg: GatewayMessage) -> None:
        logger.debug("kid %s got response: %s", self._kid_id, msg.data)

    async def on_approval_request(self, msg: GatewayMessage) -> None:
        # Kids do NOT auto-approve; escalate to the parent. The parent
        # makes the call; the kid just relays.
        logger.info("kid %s escalating approval to parent: %s", self._kid_id, msg.data)

    async def on_event(self, msg: GatewayMessage) -> None:
        data = msg.data or {}
        if (
            data.get("event_type") == "child_task_assigned"
            and data.get("kid_id") == self._kid_id
        ):
            task = (data.get("task") or "").strip()
            if not task:
                return
            try:
                self._task_queue.put_nowait(task)
            except asyncio.QueueFull:
                # Refuse loudly — parent should see this and back off.
                await self._send_chat(
                    f"[kid {self._kid_name} REFUSED task — queue full ({self._task_queue.qsize()} pending). "
                    "Wait for the current tasks to finish or destroy and respawn me.]"
                )

    # ── Task worker ────────────────────────────────────────────────

    async def _task_worker(self) -> None:
        """Drain the task queue, run each through the local agent."""
        while True:
            try:
                task = await self._task_queue.get()
            except asyncio.CancelledError:
                raise
            try:
                await self._run_task(task)
            except Exception as e:
                logger.exception("kid %s task failed: %s", self._kid_id, e)
                await self._send_chat(
                    f"[kid {self._kid_name} ERROR running task: {type(e).__name__}: {e}]"
                )
            finally:
                self._task_queue.task_done()

    async def _run_task(self, task: str) -> None:
        if self._agent is None:
            await self._send_chat(
                f"[kid {self._kid_name} cannot run task: no agent attached (test mode?)]"
            )
            return
        logger.info("kid %s running task: %s", self._kid_id, task[:200])
        await self._send_chat(f"[kid {self._kid_name} starting: {task[:160]}]")
        result = await self._agent.run(task)
        # Agent.run returns AgentResponse with .content and .steps_taken
        content = getattr(result, "content", str(result))
        steps = getattr(result, "steps_taken", 0)
        # Trim very long results to keep gateway frames sane; parent can
        # call read_kid_file() for full artifact retrieval.
        trimmed = (
            content if len(content) <= 8000 else content[:8000] + "\n\n[...truncated]"
        )
        await self._send_chat(
            f"[kid {self._kid_name} done in {steps} steps]\n\n{trimmed}"
        )

    # ── Helpers ────────────────────────────────────────────────────

    async def _send_chat(self, content: str) -> None:
        if not self._ws:
            return
        try:
            await self._ws.send(
                chat_message(
                    channel=self.name,
                    user_id=self._kid_id,
                    content=content,
                ).to_json()
            )
        except Exception as e:
            logger.debug("send_chat failed: %s", e)


def main() -> None:
    """Standalone entrypoint (used only by tests / manual runs).

    The real production entrypoint is `core.kid_bootstrap.main()` which
    builds the agent first and passes it in. This function is kept so
    `python -m channels.kid_agent_adapter` still does something sensible
    — it boots a no-agent adapter that ack's tasks but can't run them.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    adapter = KidAgentAdapter(agent=None)
    try:
        asyncio.run(adapter.start())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
