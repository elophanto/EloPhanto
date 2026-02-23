"""WebSocket gateway — the control plane for all channel adapters.

All interfaces (CLI, Telegram, Discord, Slack, etc.) connect here
as thin WebSocket clients. The gateway manages sessions, routes
messages to the agent, and broadcasts events back to the right channel.

Architecture:
    Channel Adapter ←ws→ Gateway ←direct→ Agent
                                  ←direct→ SessionManager

Usage:
    gateway = Gateway(agent, config)
    await gateway.start()   # Non-blocking, runs in background
    ...
    await gateway.stop()
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from core.protocol import (
    EventType,
    GatewayMessage,
    MessageType,
    approval_request_message,
    error_message,
    event_message,
    response_message,
    status_message,
)
from core.recovery import RecoveryHandler
from core.session import Session, SessionManager

logger = logging.getLogger(__name__)


@dataclass
class ClientConnection:
    """A connected channel adapter."""

    client_id: str
    websocket: Any  # websockets.WebSocketServerProtocol
    channel: str = ""
    user_id: str = ""
    session_id: str = ""


class Gateway:
    """WebSocket control plane for EloPhanto."""

    def __init__(
        self,
        agent: Any,  # core.agent.Agent — avoid circular import
        session_manager: SessionManager,
        host: str = "127.0.0.1",
        port: int = 18789,
        auth_token: str | None = None,
        max_sessions: int = 50,
        unified_sessions: bool = True,
    ) -> None:
        self._agent = agent
        self._sessions = session_manager
        self._host = host
        self._port = port
        self._auth_token = auth_token
        self._max_sessions = max_sessions
        self._unified_sessions = unified_sessions

        self._clients: dict[str, ClientConnection] = {}
        self._server: Any = None
        self._serve_task: asyncio.Task[None] | None = None

        # Pending approval futures: approval_msg_id → asyncio.Future[bool]
        self._pending_approvals: dict[str, asyncio.Future[bool]] = {}

        # Active chat tasks: client_id → asyncio.Task (for cancellation)
        self._active_chat_tasks: dict[str, asyncio.Task[None]] = {}

        # Map session_id → set of client_ids subscribed to that session
        self._session_clients: dict[str, set[str]] = {}

        # Recovery handler — pure Python, no LLM
        router = getattr(agent, "_router", None)
        config = getattr(agent, "_config", None)
        self._recovery = (
            RecoveryHandler(config, router, agent) if config and router else None
        )
        self._health_monitor_task: asyncio.Task[None] | None = None

    @property
    def url(self) -> str:
        return f"ws://{self._host}:{self._port}"

    @property
    def is_running(self) -> bool:
        return self._server is not None

    async def start(self) -> None:
        """Start the WebSocket server (non-blocking)."""
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not installed. Run: uv add websockets")
            raise

        self._server = await websockets.serve(
            self._handle_connection,
            self._host,
            self._port,
        )
        logger.info("Gateway started on %s", self.url)

        # Start periodic health monitoring for auto-recovery
        if self._recovery:
            self._health_monitor_task = asyncio.create_task(self._health_monitor_loop())

    async def stop(self) -> None:
        """Gracefully shut down the gateway."""
        if self._health_monitor_task:
            self._health_monitor_task.cancel()
            self._health_monitor_task = None
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("Gateway stopped")

        # Cancel any pending approvals
        for future in self._pending_approvals.values():
            if not future.done():
                future.set_result(False)
        self._pending_approvals.clear()

    async def broadcast(
        self,
        msg: GatewayMessage,
        session_id: str | None = None,
        exclude_client: str | None = None,
    ) -> None:
        """Send a message to all clients, or only those subscribed to a session."""
        targets = (
            self._session_clients.get(session_id, set())
            if session_id
            else set(self._clients.keys())
        )

        payload = msg.to_json()
        for cid in targets:
            if cid == exclude_client:
                continue
            client = self._clients.get(cid)
            if client and client.websocket:
                try:
                    await client.websocket.send(payload)
                except Exception:
                    logger.debug("Failed to send to client %s", cid[:8])

    async def _handle_connection(self, websocket: Any) -> None:
        """Handle a single WebSocket client connection lifecycle."""
        import uuid

        client_id = str(uuid.uuid4())
        client = ClientConnection(client_id=client_id, websocket=websocket)
        self._clients[client_id] = client
        logger.info("Client connected: %s", client_id[:8])

        try:
            # Send ready status
            await websocket.send(
                status_message("connected", {"client_id": client_id}).to_json()
            )

            async for raw in websocket:
                try:
                    msg = GatewayMessage.from_json(raw)
                    await self._route_message(client, msg)
                except Exception as e:
                    logger.error("Error handling message: %s", e)
                    await websocket.send(error_message(str(e)).to_json())
        except Exception as e:
            logger.debug("Client %s disconnected: %s", client_id[:8], e)
        finally:
            # Cleanup
            self._clients.pop(client_id, None)
            for subs in self._session_clients.values():
                subs.discard(client_id)
            logger.info("Client disconnected: %s", client_id[:8])

    async def _route_message(
        self, client: ClientConnection, msg: GatewayMessage
    ) -> None:
        """Route an incoming message to the appropriate handler."""
        if msg.type == MessageType.CHAT:
            # Spawn as task so the websocket loop stays responsive for
            # approvals, commands (cancel), and other messages during processing.
            task = asyncio.create_task(self._handle_chat(client, msg))
            self._active_chat_tasks[client.client_id] = task
            task.add_done_callback(
                lambda _t: self._active_chat_tasks.pop(client.client_id, None)
            )
            return

        # Everything else is handled inline (fast operations)
        handlers = {
            MessageType.APPROVAL_RESPONSE: self._handle_approval_response,
            MessageType.COMMAND: self._handle_command,
            MessageType.STATUS: self._handle_status,
        }

        handler = handlers.get(msg.type)  # type: ignore[call-overload]
        if handler:
            await handler(client, msg)
        else:
            await client.websocket.send(
                error_message(f"Unknown message type: {msg.type}").to_json()
            )

    async def _handle_chat(self, client: ClientConnection, msg: GatewayMessage) -> None:
        """Handle a chat message — route to agent with session isolation."""
        # In recovery mode, block chat (LLM is unavailable) and show help
        if self._recovery and self._recovery.recovery_mode:
            session_id = msg.session_id or client.session_id or ""
            await client.websocket.send(
                response_message(
                    session_id,
                    "Agent is in recovery mode (LLM unavailable).\n"
                    "Use /health for diagnostics or /recovery off to exit.",
                    done=True,
                ).to_json()
            )
            return

        channel = msg.channel or client.channel or "unknown"
        user_id = msg.user_id or client.user_id or client.client_id

        # Update client info
        client.channel = channel
        client.user_id = user_id

        # Get or create session — unified mode shares one session across channels
        if self._unified_sessions:
            session = await self._sessions.get_or_create("unified", "owner")
        elif msg.session_id:
            existing = await self._sessions.get(msg.session_id)
            session = existing or await self._sessions.get_or_create(channel, user_id)
        else:
            session = await self._sessions.get_or_create(channel, user_id)

        client.session_id = session.session_id

        # Subscribe client to session events
        if session.session_id not in self._session_clients:
            self._session_clients[session.session_id] = set()
        self._session_clients[session.session_id].add(client.client_id)

        content = msg.data.get("content", "")
        attachments = msg.data.get("attachments")

        # Augment content with file references so the LLM sees them
        if attachments:
            file_lines = []
            for att in attachments:
                fname = att.get("filename", "unknown")
                mime = att.get("mime_type", "")
                path = att.get("local_path", "")
                size = att.get("size_bytes", 0)
                file_lines.append(
                    f"[Attached file: {fname} ({mime}, {size} bytes) at {path}]"
                )
            content = (
                content + "\n\n" + "\n".join(file_lines)
                if content
                else "\n".join(file_lines)
            )

        if not content:
            await client.websocket.send(
                error_message("Empty message", session.session_id).to_json()
            )
            return

        # Notify: step progress
        async def on_step(
            step: int, tool_name: str, thought: str, params: dict
        ) -> None:
            await self.broadcast(
                event_message(
                    session.session_id,
                    EventType.STEP_PROGRESS,
                    {
                        "step": step,
                        "tool_name": tool_name,
                        "thought": thought[:200],
                    },
                ),
                session_id=session.session_id,
            )

        # Create approval callback for this session
        async def session_approval_callback(
            tool_name: str, description: str, params: dict
        ) -> bool:
            return await self._request_approval(
                session, client, tool_name, description, params
            )

        # Broadcast user message to other channels (unified mode)
        if self._unified_sessions:
            await self.broadcast(
                event_message(
                    session.session_id,
                    EventType.USER_MESSAGE,
                    {
                        "channel": channel,
                        "user_id": user_id,
                        "content": content[:500],
                    },
                ),
                session_id=session.session_id,
                exclude_client=client.client_id,
            )

        # Run agent with session isolation
        try:
            agent_response = await self._agent.run_session(
                goal=content,
                session=session,
                approval_callback=session_approval_callback,
                on_step=on_step,
            )

            # Persist session
            await self._sessions.save(session)

            # Send response — broadcast to all session subscribers in unified
            # mode so other channels see the answer. The requesting client
            # resolves via reply_to match; others call on_response().
            resp = response_message(
                session.session_id,
                agent_response.content,
                done=True,
                reply_to=msg.id,
            )
            if self._unified_sessions:
                await self.broadcast(resp, session_id=session.session_id)
            else:
                await client.websocket.send(resp.to_json())

            # Broadcast task complete event
            await self.broadcast(
                event_message(
                    session.session_id,
                    EventType.TASK_COMPLETE,
                    {
                        "goal": content[:100],
                        "steps": agent_response.steps_taken,
                        "tools": agent_response.tool_calls_made,
                    },
                ),
                session_id=session.session_id,
                exclude_client=client.client_id,
            )

        except asyncio.CancelledError:
            logger.info("Chat cancelled for session %s", session.session_id[:8])
            try:
                await client.websocket.send(
                    response_message(
                        session.session_id,
                        "Request cancelled.",
                        done=True,
                        reply_to=msg.id,
                    ).to_json()
                )
            except Exception:
                pass

        except Exception as e:
            logger.error("Agent error for session %s: %s", session.session_id[:8], e)
            await client.websocket.send(
                error_message(str(e), session.session_id, msg.id).to_json()
            )
            await self.broadcast(
                event_message(
                    session.session_id,
                    EventType.TASK_ERROR,
                    {"error": str(e)},
                ),
                session_id=session.session_id,
                exclude_client=client.client_id,
            )

    async def _request_approval(
        self,
        session: Session,
        client: ClientConnection,
        tool_name: str,
        description: str,
        params: dict[str, Any],
    ) -> bool:
        """Send approval request to channel and wait for response."""
        req = approval_request_message(
            session.session_id, tool_name, description, params
        )
        self._pending_approvals[req.id] = asyncio.get_event_loop().create_future()

        # Send to the requesting client and any other clients on this session
        await self.broadcast(req, session_id=session.session_id)

        try:
            approved = await asyncio.wait_for(
                self._pending_approvals[req.id], timeout=300
            )
            return approved
        except TimeoutError:
            logger.warning("Approval timed out for %s", tool_name)
            return False
        finally:
            self._pending_approvals.pop(req.id, None)

    async def _handle_approval_response(
        self, client: ClientConnection, msg: GatewayMessage
    ) -> None:
        """Handle an approval response from a channel adapter."""
        request_id = msg.id
        approved = msg.data.get("approved", False)

        future = self._pending_approvals.get(request_id)
        if future and not future.done():
            future.set_result(approved)
            logger.info(
                "Approval %s: %s",
                "granted" if approved else "denied",
                request_id[:8],
            )
        else:
            logger.warning("No pending approval for id %s", request_id[:8])

    async def _handle_command(
        self, client: ClientConnection, msg: GatewayMessage
    ) -> None:
        """Handle slash commands — including recovery commands (no LLM)."""
        command = msg.data.get("command", "")
        session_id = msg.session_id or client.session_id
        user_id = msg.user_id or client.user_id

        if command == "status":
            active = await self._sessions.list_active(limit=5)
            data = {
                "sessions": len(active),
                "clients": len(self._clients),
                "pending_approvals": len(self._pending_approvals),
            }
            await client.websocket.send(
                response_message(session_id, f"Status: {data}", done=True).to_json()
            )

        elif command == "sessions":
            active = await self._sessions.list_active(limit=10)
            lines = [
                f"- {s.channel}/{s.user_id} ({s.session_id[:8]}) "
                f"last active: {s.last_active.isoformat()}"
                for s in active
            ]
            await client.websocket.send(
                response_message(
                    session_id,
                    (
                        "Active sessions:\n" + "\n".join(lines)
                        if lines
                        else "No active sessions"
                    ),
                    done=True,
                ).to_json()
            )

        elif command == "cancel":
            task = self._active_chat_tasks.get(client.client_id)
            if task and not task.done():
                task.cancel()
                logger.info("Cancelled active task for client %s", client.client_id[:8])
            else:
                await client.websocket.send(
                    response_message(
                        session_id, "Nothing to cancel.", done=True
                    ).to_json()
                )

        else:
            # Try recovery handler — pure Python, no LLM
            if self._recovery:
                result = await self._recovery.handle(command, user_id=user_id)
                if result is not None:
                    await client.websocket.send(
                        response_message(session_id, result, done=True).to_json()
                    )
                    return

            await client.websocket.send(
                error_message(f"Unknown command: {command}", session_id).to_json()
            )

    async def _handle_status(
        self, client: ClientConnection, msg: GatewayMessage
    ) -> None:
        """Handle status/heartbeat messages."""
        await client.websocket.send(
            status_message("ok", {"client_id": client.client_id}).to_json()
        )

    async def _health_monitor_loop(self) -> None:
        """Periodically check provider health; auto-enter recovery if all down."""
        config = getattr(self._agent, "_config", None)
        interval = 60
        if config and hasattr(config, "recovery"):
            interval = config.recovery.health_check_interval_seconds

        while True:
            try:
                await asyncio.sleep(interval)
                if self._recovery:
                    notification = self._recovery.check_auto_recovery()
                    if notification:
                        # Broadcast to all connected clients
                        await self.broadcast(
                            event_message(
                                "",
                                EventType.NOTIFICATION,
                                {"content": notification},
                            )
                        )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("Health monitor tick error", exc_info=True)
