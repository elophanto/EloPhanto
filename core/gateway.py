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
    conversation_id: str = ""


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
        session_timeout_hours: int = 24,
        unified_sessions: bool = True,
        authority_config: Any | None = None,
    ) -> None:
        self._agent = agent
        self._sessions = session_manager
        self._host = host
        self._port = port
        self._auth_token = auth_token
        self._max_sessions = max_sessions
        self._session_timeout_hours = session_timeout_hours
        self._unified_sessions = unified_sessions
        self._authority_config = authority_config  # AuthorityConfig | None

        self._clients: dict[str, ClientConnection] = {}
        self._server: Any = None
        self._serve_task: asyncio.Task[None] | None = None

        # Pending approval futures: approval_msg_id → asyncio.Future[bool]
        self._pending_approvals: dict[str, asyncio.Future[bool]] = {}

        # Active chat tasks: client_id → asyncio.Task (for cancellation)
        self._active_chat_tasks: dict[str, asyncio.Task[None]] = {}

        self._session_cleanup_task: asyncio.Task[None] | None = None

        # Map session_id → set of client_ids subscribed to that session
        self._session_clients: dict[str, set[str]] = {}

        # Recovery handler — pure Python, no LLM
        router = getattr(agent, "_router", None)
        config = getattr(agent, "_config", None)
        self._recovery = (
            RecoveryHandler(config, router, agent) if config and router else None
        )
        self._health_monitor_task: asyncio.Task[None] | None = None

        # Remote shutdown signal (set by exit/shutdown commands from any channel)
        self._shutdown_event: asyncio.Event = asyncio.Event()

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

        # Start session cleanup loop
        self._session_cleanup_task = asyncio.create_task(self._session_cleanup_loop())

    async def request_shutdown(self, reason: str = "Remote shutdown requested") -> None:
        """Signal graceful shutdown from any channel."""
        logger.info("Shutdown requested: %s", reason)
        await self.broadcast(
            event_message("", EventType.SHUTDOWN, {"reason": reason}),
            session_id=None,
        )
        self._shutdown_event.set()

    async def wait_for_shutdown(self) -> None:
        """Block until shutdown is requested. Used by entry points."""
        await self._shutdown_event.wait()

    async def stop(self) -> None:
        """Gracefully shut down the gateway."""
        if self._session_cleanup_task:
            self._session_cleanup_task.cancel()
            self._session_cleanup_task = None
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

    async def _subscribe_to_unified(self, client: ClientConnection) -> None:
        """Subscribe a client to the unified session (creates it if needed)."""
        session = await self._sessions.get_or_create("unified", "owner")
        client.session_id = session.session_id
        if session.session_id not in self._session_clients:
            self._session_clients[session.session_id] = set()
        self._session_clients[session.session_id].add(client.client_id)

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

        # --- Auth check ---
        if self._auth_token:
            # Expect token in first message, Sec-WebSocket-Protocol header,
            # or query string (?token=...).
            token_ok = False
            # Check query string (ws://host:port/?token=xxx)
            req = getattr(websocket, "request", None)
            if req:
                path = getattr(req, "path", "") or ""
                if f"token={self._auth_token}" in path:
                    token_ok = True
                # Check Authorization header
                headers = getattr(req, "headers", {})
                auth_header = (
                    headers.get("Authorization", "") if hasattr(headers, "get") else ""
                )
                if auth_header == f"Bearer {self._auth_token}":
                    token_ok = True

            if not token_ok:
                logger.warning("Rejected unauthenticated connection")
                await websocket.close(4401, "Authentication required")
                return

        # --- Max clients check ---
        if len(self._clients) >= self._max_sessions:
            logger.warning(
                "Rejected connection: max sessions reached (%d)", self._max_sessions
            )
            await websocket.close(4429, "Too many connections")
            return

        client_id = str(uuid.uuid4())
        client = ClientConnection(client_id=client_id, websocket=websocket)
        self._clients[client_id] = client
        logger.info("Client connected: %s", client_id[:8])

        try:
            # Send ready status
            await websocket.send(
                status_message("connected", {"client_id": client_id}).to_json()
            )

            # Auto-subscribe to unified session so cross-channel forwarding
            # works immediately (without requiring the client to chat first).
            if self._unified_sessions:
                await self._subscribe_to_unified(client)

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

        # Resolve authority tier for this user
        from core.authority import resolve_authority

        authority = resolve_authority(channel, user_id, self._authority_config)
        logger.info("Authority: %s for %s:%s", authority.value, channel, user_id[:8])

        # Get or create session — unified mode shares one session across channels
        if self._unified_sessions:
            session = await self._sessions.get_or_create("unified", "owner")
        elif msg.session_id:
            existing = await self._sessions.get(msg.session_id)
            session = existing or await self._sessions.get_or_create(channel, user_id)
        else:
            session = await self._sessions.get_or_create(channel, user_id)

        client.session_id = session.session_id

        # Store authority for observability
        session.metadata["authority_level"] = authority.value

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
                # Sanitize filenames to prevent injection via bracket interpolation
                fname = (
                    fname.replace("[", "(")
                    .replace("]", ")")
                    .replace("<", "(")
                    .replace(">", ")")
                )
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
                authority=authority,
            )

            # Persist session
            await self._sessions.save(session)

            # Persist chat messages + conversation tracking
            import uuid as _uuid
            from datetime import UTC
            from datetime import datetime as _dt

            _now = _dt.now(UTC).isoformat()
            _conv_id = client.conversation_id

            # Create conversation on first message if none active
            if not _conv_id:
                _conv_id = str(_uuid.uuid4())
                client.conversation_id = _conv_id
                _title = content[:50].replace("\n", " ").strip() or "New conversation"
                await self._agent._db.execute_insert(
                    "INSERT INTO conversations (conversation_id, title, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?)",
                    (_conv_id, _title, _now, _now),
                )
            else:
                # Update conversation timestamp
                await self._agent._db.execute_insert(
                    "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                    (_now, _conv_id),
                )

            await self._agent._db.execute_insert(
                "INSERT INTO chat_messages (session_id, msg_id, role, content, created_at, conversation_id)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (session.session_id, msg.id, "user", content, _now, _conv_id),
            )
            await self._agent._db.execute_insert(
                "INSERT INTO chat_messages (session_id, msg_id, role, content, created_at, conversation_id)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    session.session_id,
                    str(_uuid.uuid4()),
                    "assistant",
                    agent_response.content,
                    _now,
                    _conv_id,
                ),
            )

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

        elif command == "clear":
            # Clear LLM context but preserve chat history for sidebar
            old_session_id = client.session_id
            if old_session_id:
                await self._sessions.delete(old_session_id)
                # Remove stale subscription set for the deleted session
                self._session_clients.pop(old_session_id, None)
            client.session_id = ""
            client.conversation_id = ""  # Next message starts new conversation
            # Clear task memory so the agent doesn't recall old tasks
            import json as _json

            mem_mgr = getattr(self._agent, "_memory_manager", None)
            memories_cleared = 0
            if mem_mgr:
                memories_cleared = await mem_mgr.clear_all()
            # Re-subscribe all connected clients to the new unified session
            if self._unified_sessions:
                for _cid, c in self._clients.items():
                    await self._subscribe_to_unified(c)
            payload = _json.dumps(
                {"cleared": {"ok": True, "memories": memories_cleared}}
            )
            await client.websocket.send(
                response_message("", payload, done=True).to_json()
            )

        elif command == "mind":
            mind = getattr(self._agent, "_autonomous_mind", None)
            sub = (msg.data.get("args") or {}).get("subcommand", "").strip()
            if not mind:
                text = "Autonomous mind is not enabled. Set `autonomous_mind.enabled: true` in config.yaml."
            elif sub == "stop":
                await mind.cancel()
                text = "Autonomous mind stopped."
            elif sub == "start":
                if mind.is_running:
                    text = "Autonomous mind is already running."
                else:
                    mind.start()
                    text = "Autonomous mind started."
            else:
                status = mind.get_status()
                state = (
                    "paused"
                    if status["paused"]
                    else ("active" if status["running"] else "stopped")
                )
                budget_pct = (
                    int(status["budget_spent"] / status["budget_total"] * 100)
                    if status["budget_total"] > 0
                    else 0
                )
                lines = [
                    f"**Autonomous Mind** — {state}",
                    f"- Budget: ${status['budget_spent']:.4f} / "
                    f"${status['budget_total']:.2f} ({budget_pct}% used)",
                    f"- Cycles: {status['cycle_count']}",
                    f"- Last wakeup: {status['last_wakeup']}",
                    f"- Last action: {status['last_action'][:100]}",
                    f"- Next wakeup: {int(status['next_wakeup_sec'])}s",
                    f"- Pending events: {status['pending_events']}",
                ]
                actions = status.get("recent_actions", [])
                if actions:
                    lines.append("\n**Recent Actions:**")
                    for a in actions[-8:]:
                        lines.append(f"  {a['ts']}  {a['summary'][:100]}")
                sp = status.get("scratchpad", "")
                if sp:
                    lines.append(f"\n**Scratchpad:**\n{sp[:1000]}")
                text = "\n".join(lines)
            await client.websocket.send(
                response_message(session_id, text, done=True).to_json()
            )

        elif command == "mind_status":
            # Return structured JSON of autonomous mind state
            import json as _json

            mind = getattr(self._agent, "_autonomous_mind", None)
            if mind:
                try:
                    status = mind.get_status()
                    # Add config info
                    cfg = getattr(self._agent, "_config", None)
                    mind_cfg = getattr(cfg, "autonomous_mind", None) if cfg else None
                    config_data: dict[str, Any] = {}
                    if mind_cfg:
                        config_data = {
                            "wakeup_seconds": mind_cfg.wakeup_seconds,
                            "min_wakeup_seconds": mind_cfg.min_wakeup_seconds,
                            "max_wakeup_seconds": mind_cfg.max_wakeup_seconds,
                            "budget_pct": mind_cfg.budget_pct,
                            "max_rounds_per_wakeup": mind_cfg.max_rounds_per_wakeup,
                            "verbosity": mind_cfg.verbosity,
                        }
                    payload = _json.dumps(
                        {
                            "mind_status": {
                                **status,
                                "config": config_data,
                            }
                        }
                    )
                except Exception:
                    logger.debug("Mind status error", exc_info=True)
                    payload = _json.dumps(
                        {
                            "mind_status": {
                                "enabled": False,
                                "error": "Failed to get status",
                            }
                        }
                    )
            else:
                payload = _json.dumps({"mind_status": {"enabled": False}})
            await client.websocket.send(
                response_message(session_id, payload, done=True).to_json()
            )

        elif command == "mind_control":
            # Start/stop/inject event into the autonomous mind
            import json as _json

            mind = getattr(self._agent, "_autonomous_mind", None)
            args = msg.data.get("args") or {}
            action = args.get("action", "")
            result: dict[str, Any] = {"ok": False}

            if not mind:
                result["error"] = "Autonomous mind is not enabled"
            elif action == "start":
                if mind.is_running:
                    result = {"ok": True, "message": "Already running"}
                else:
                    mind.start()
                    result = {"ok": True, "message": "Mind started"}
            elif action == "stop":
                await mind.cancel()
                result = {"ok": True, "message": "Mind stopped"}
            else:
                result["error"] = f"Unknown action: {action}"

            payload = _json.dumps({"mind_control": result})
            await client.websocket.send(
                response_message(session_id, payload, done=True).to_json()
            )

        elif command == "tools":
            # Return structured JSON of all registered tools
            import json as _json

            tools_data = []
            for t in self._agent._registry.all_tools():
                tools_data.append(
                    {
                        "name": t.name,
                        "description": t.description,
                        "permission": t.permission_level.value,
                        "parameters": t.input_schema.get("properties", {}),
                        "required": t.input_schema.get("required", []),
                    }
                )
            payload = _json.dumps({"tools": tools_data})
            await client.websocket.send(
                response_message(session_id, payload, done=True).to_json()
            )

        elif command == "skills":
            # Return structured JSON of all discovered skills
            import json as _json

            skills_data = []
            for s in self._agent._skill_manager.list_skills():
                skills_data.append(
                    {
                        "name": s.name,
                        "description": s.description,
                        "triggers": s.triggers,
                        "source": s.source,
                    }
                )
            payload = _json.dumps({"skills": skills_data})
            await client.websocket.send(
                response_message(session_id, payload, done=True).to_json()
            )

        elif command == "dashboard":
            # Return aggregated dashboard overview data
            import json as _json

            dashboard: dict[str, Any] = {}

            # Identity
            identity_mgr = getattr(self._agent, "_identity_manager", None)
            if identity_mgr:
                try:
                    ident = await identity_mgr.get_identity()
                    dashboard["identity"] = {
                        "display_name": ident.display_name,
                        "purpose": ident.purpose or "",
                        "capabilities": ident.capabilities[:10],
                    }
                except Exception:
                    dashboard["identity"] = None
            else:
                dashboard["identity"] = None

            # Mind
            mind = getattr(self._agent, "_autonomous_mind", None)
            if mind:
                try:
                    dashboard["mind"] = mind.get_status()
                except Exception:
                    dashboard["mind"] = None
            else:
                dashboard["mind"] = None

            # Goals
            goal_mgr = getattr(self._agent, "_goal_manager", None)
            if goal_mgr:
                try:
                    goals = await goal_mgr.list_goals(limit=10)
                    dashboard["goals"] = [
                        {
                            "goal_id": g.goal_id,
                            "goal": g.goal[:120],
                            "status": g.status,
                            "current_checkpoint": g.current_checkpoint,
                            "total_checkpoints": g.total_checkpoints,
                            "cost_usd": g.cost_usd,
                            "created_at": g.created_at,
                        }
                        for g in goals
                    ]
                except Exception:
                    dashboard["goals"] = []
            else:
                dashboard["goals"] = []

            # Schedules summary
            scheduler = getattr(self._agent, "_scheduler", None)
            if scheduler:
                try:
                    schedules = await scheduler.list_schedules()
                    enabled_count = sum(1 for s in schedules if s.enabled)
                    next_runs = [
                        s.next_run_at for s in schedules if s.enabled and s.next_run_at
                    ]
                    dashboard["schedules"] = {
                        "total": len(schedules),
                        "enabled": enabled_count,
                        "next_run": min(next_runs) if next_runs else None,
                    }
                except Exception:
                    dashboard["schedules"] = {
                        "total": 0,
                        "enabled": 0,
                        "next_run": None,
                    }
            else:
                dashboard["schedules"] = {"total": 0, "enabled": 0, "next_run": None}

            # Swarm
            swarm_mgr = getattr(self._agent, "_swarm_manager", None)
            if swarm_mgr:
                try:
                    agents = await swarm_mgr.get_status()
                    dashboard["swarm"] = agents
                except Exception:
                    dashboard["swarm"] = []
            else:
                dashboard["swarm"] = []

            # Connected channels
            dashboard["channels"] = [
                {
                    "client_id": c.client_id[:8],
                    "channel": c.channel or "web",
                    "user_id": c.user_id or "owner",
                }
                for c in self._clients.values()
            ]

            # Stats
            tools_count = len(self._agent._registry.all_tools())
            skills_count = len(self._agent._skill_manager.list_skills())
            knowledge_chunks = 0
            try:
                db = getattr(self._agent, "_db", None)
                if db:
                    rows = await db.execute(
                        "SELECT COUNT(*) as cnt FROM knowledge_chunks"
                    )
                    knowledge_chunks = rows[0]["cnt"] if rows else 0
            except Exception:
                pass
            dashboard["stats"] = {
                "tools_count": tools_count,
                "skills_count": skills_count,
                "knowledge_chunks": knowledge_chunks,
            }

            payload = _json.dumps({"dashboard": dashboard})
            await client.websocket.send(
                response_message(session_id, payload, done=True).to_json()
            )

        elif command == "knowledge":
            # Return knowledge base stats and file listing
            import json as _json

            knowledge: dict[str, Any] = {"stats": {}, "files": []}
            try:
                db = getattr(self._agent, "_db", None)
                if db:
                    # Stats
                    chunk_rows = await db.execute(
                        "SELECT COUNT(*) as cnt FROM knowledge_chunks"
                    )
                    chunks = chunk_rows[0]["cnt"] if chunk_rows else 0

                    embed_count = 0
                    try:
                        vec_rows = await db.execute(
                            "SELECT COUNT(*) as cnt FROM vec_chunks"
                        )
                        embed_count = vec_rows[0]["cnt"] if vec_rows else 0
                    except Exception:
                        pass

                    # Files grouped
                    file_rows = await db.execute(
                        "SELECT file_path, scope, COUNT(*) as chunks, "
                        "GROUP_CONCAT(DISTINCT tags) as all_tags, "
                        "MAX(indexed_at) as updated_at "
                        "FROM knowledge_chunks GROUP BY file_path "
                        "ORDER BY updated_at DESC"
                    )

                    scopes: dict[str, int] = {}
                    files = []
                    for row in file_rows:
                        scope = row["scope"] or "unknown"
                        scopes[scope] = scopes.get(scope, 0) + 1
                        # Parse tags from concatenated JSON arrays
                        raw_tags = row["all_tags"] or ""
                        tags: list[str] = []
                        for part in raw_tags.split(","):
                            part = part.strip().strip('"[]')
                            if part and part not in tags:
                                tags.append(part)
                        files.append(
                            {
                                "path": row["file_path"],
                                "scope": scope,
                                "chunks": row["chunks"],
                                "tags": tags[:10],
                                "updated_at": row["updated_at"] or "",
                            }
                        )

                    knowledge["stats"] = {
                        "chunks": chunks,
                        "embeddings": embed_count,
                        "files": len(files),
                        "scopes": scopes,
                    }
                    knowledge["files"] = files
            except Exception:
                logger.debug("Knowledge command error", exc_info=True)

            payload = _json.dumps({"knowledge": knowledge})
            await client.websocket.send(
                response_message(session_id, payload, done=True).to_json()
            )

        elif command == "knowledge_detail":
            # Return chunks for a specific knowledge file
            import json as _json

            file_path = (msg.data.get("args") or {}).get("file_path", "")
            chunks_data: list[dict[str, Any]] = []
            if file_path:
                try:
                    db = getattr(self._agent, "_db", None)
                    if db:
                        rows = await db.execute(
                            "SELECT heading_path, content, scope, tags, "
                            "token_count, indexed_at "
                            "FROM knowledge_chunks WHERE file_path = ? "
                            "ORDER BY id ASC",
                            (file_path,),
                        )
                        for row in rows:
                            chunks_data.append(
                                {
                                    "heading": row["heading_path"] or "",
                                    "content": row["content"],
                                    "scope": row["scope"],
                                    "tags": row["tags"],
                                    "tokens": row["token_count"],
                                }
                            )
                except Exception:
                    logger.debug("Knowledge detail error", exc_info=True)

            payload = _json.dumps(
                {"knowledge_detail": {"file_path": file_path, "chunks": chunks_data}}
            )
            await client.websocket.send(
                response_message(session_id, payload, done=True).to_json()
            )

        elif command == "schedules":
            # Return all scheduled tasks
            import json as _json

            scheduler = getattr(self._agent, "_scheduler", None)
            schedules_data: list[dict[str, Any]] = []
            if scheduler:
                try:
                    entries = await scheduler.list_schedules()
                    for s in entries:
                        schedules_data.append(
                            {
                                "id": s.id,
                                "name": s.name,
                                "description": s.description,
                                "cron_expression": s.cron_expression,
                                "task_goal": s.task_goal,
                                "enabled": s.enabled,
                                "last_run_at": s.last_run_at,
                                "next_run_at": s.next_run_at,
                                "last_status": s.last_status,
                                "created_at": s.created_at,
                            }
                        )
                except Exception:
                    logger.debug("Schedules command error", exc_info=True)

            payload = _json.dumps({"schedules": schedules_data})
            await client.websocket.send(
                response_message(session_id, payload, done=True).to_json()
            )

        elif command == "channels":
            # Return connected clients and gateway info
            import json as _json

            clients_data = [
                {
                    "client_id": c.client_id[:8],
                    "channel": c.channel or "web",
                    "user_id": c.user_id or "owner",
                    "session_id": (c.session_id or "")[:8],
                }
                for c in self._clients.values()
            ]

            active_sessions = await self._sessions.list_active(limit=50)

            channels_data: dict[str, Any] = {
                "clients": clients_data,
                "sessions": {
                    "active": len(active_sessions),
                    "unified_mode": self._unified_sessions,
                },
                "gateway": {
                    "host": self._host,
                    "port": self._port,
                },
            }

            payload = _json.dumps({"channels": channels_data})
            await client.websocket.send(
                response_message(session_id, payload, done=True).to_json()
            )

        elif command == "config":
            # Return sanitized read-only configuration
            import json as _json
            from dataclasses import asdict

            config = getattr(self._agent, "_config", None)
            if config:
                # Serialize config, redacting secrets
                raw = asdict(config)

                # Remove sensitive fields and internal paths
                def _redact(d: dict[str, Any]) -> dict[str, Any]:
                    redacted: dict[str, Any] = {}
                    for k, v in d.items():
                        if any(
                            s in k.lower()
                            for s in (
                                "api_key",
                                "token",
                                "password",
                                "secret",
                                "_ref",
                                "private",
                            )
                        ):
                            continue
                        if k == "project_root":
                            continue
                        if isinstance(v, dict):
                            redacted[k] = _redact(v)
                        else:
                            redacted[k] = v
                    return redacted

                sanitized = _redact(raw)
                payload = _json.dumps({"config": sanitized})
            else:
                payload = _json.dumps({"config": {}})
            await client.websocket.send(
                response_message(session_id, payload, done=True).to_json()
            )

        elif command == "history":
            # Return task memories and identity evolution
            import json as _json

            history: dict[str, Any] = {"tasks": [], "evolution": []}

            # Task memories
            mem_mgr = getattr(self._agent, "_memory_manager", None)
            if mem_mgr:
                try:
                    tasks = await mem_mgr.get_recent_tasks(limit=50)
                    history["tasks"] = [
                        {
                            "goal": t.get("goal", ""),
                            "summary": t.get("summary", ""),
                            "outcome": t.get("outcome", ""),
                            "tools_used": t.get("tools_used", []),
                            "created_at": t.get("created_at", ""),
                        }
                        for t in tasks
                    ]
                except Exception:
                    logger.debug("History tasks error", exc_info=True)

            # Identity evolution
            identity_mgr = getattr(self._agent, "_identity_manager", None)
            if identity_mgr:
                try:
                    evolution = await identity_mgr.get_evolution_history(limit=50)
                    history["evolution"] = [
                        {
                            "trigger": e.get("trigger", ""),
                            "field": e.get("field", ""),
                            "old_value": str(e.get("old_value", ""))[:200],
                            "new_value": str(e.get("new_value", ""))[:200],
                            "reason": e.get("reason", ""),
                            "created_at": e.get("created_at", ""),
                        }
                        for e in evolution
                    ]
                except Exception:
                    logger.debug("History evolution error", exc_info=True)

            payload = _json.dumps({"history": history})
            await client.websocket.send(
                response_message(session_id, payload, done=True).to_json()
            )

        elif command == "chat_history":
            # Return chat messages for a specific conversation (or current)
            import json as _json

            args = msg.data.get("args") or {}
            conv_id = args.get("conversation_id", "") or client.conversation_id

            if conv_id:
                rows = await self._agent._db.execute(
                    "SELECT msg_id, role, content, created_at FROM chat_messages "
                    "WHERE conversation_id = ? ORDER BY id ASC LIMIT 500",
                    (conv_id,),
                )
            else:
                # No conversation yet — load latest conversation's messages
                latest = await self._agent._db.execute(
                    "SELECT conversation_id FROM conversations "
                    "ORDER BY updated_at DESC LIMIT 1",
                )
                if latest:
                    conv_id = latest[0]["conversation_id"]
                    client.conversation_id = conv_id
                    rows = await self._agent._db.execute(
                        "SELECT msg_id, role, content, created_at FROM chat_messages "
                        "WHERE conversation_id = ? ORDER BY id ASC LIMIT 500",
                        (conv_id,),
                    )
                else:
                    rows = []

            messages = [
                {
                    "id": r["msg_id"],
                    "role": r["role"],
                    "content": r["content"],
                    "timestamp": r["created_at"],
                }
                for r in rows
            ]
            payload = _json.dumps(
                {
                    "chat_history": {
                        "messages": messages,
                        "conversation_id": conv_id,
                    }
                }
            )
            await client.websocket.send(
                response_message(session_id, payload, done=True).to_json()
            )

        elif command == "conversations":
            # List all conversations for sidebar
            import json as _json

            rows = await self._agent._db.execute(
                "SELECT c.conversation_id, c.title, c.created_at, c.updated_at, "
                "(SELECT COUNT(*) FROM chat_messages m "
                " WHERE m.conversation_id = c.conversation_id) as msg_count "
                "FROM conversations c ORDER BY c.updated_at DESC LIMIT 50",
            )
            convs = [
                {
                    "id": r["conversation_id"],
                    "title": r["title"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "msg_count": r["msg_count"],
                }
                for r in rows
            ]
            payload = _json.dumps(
                {
                    "conversations": convs,
                    "current_id": client.conversation_id,
                }
            )
            await client.websocket.send(
                response_message(session_id, payload, done=True).to_json()
            )

        elif command == "delete_conversation":
            # Delete a specific conversation and its messages
            import json as _json

            args = msg.data.get("args") or {}
            del_id = args.get("conversation_id", "")
            if del_id:
                await self._agent._db.execute_insert(
                    "DELETE FROM chat_messages WHERE conversation_id = ?",
                    (del_id,),
                )
                await self._agent._db.execute_insert(
                    "DELETE FROM conversations WHERE conversation_id = ?",
                    (del_id,),
                )
                # Reset current if deleted
                if client.conversation_id == del_id:
                    client.conversation_id = ""
            payload = _json.dumps({"deleted_conversation": {"ok": True, "id": del_id}})
            await client.websocket.send(
                response_message(session_id, payload, done=True).to_json()
            )

        elif command in ("exit", "quit", "shutdown"):
            # Hard stop — shut down the entire agent from any channel
            await client.websocket.send(
                response_message(session_id, "Shutting down...", done=True).to_json()
            )
            await self.request_shutdown(f"{command} from {client.channel}:{user_id}")

        elif command == "stop":
            # Cancel the current task for this client
            task = self._active_chat_tasks.get(client.client_id)
            if task and not task.done():
                task.cancel()
                await client.websocket.send(
                    response_message(session_id, "Task stopped.", done=True).to_json()
                )
            else:
                await client.websocket.send(
                    response_message(session_id, "No active task.", done=True).to_json()
                )

        elif command == "pause":
            # Pause the autonomous mind
            mind = getattr(self._agent, "_autonomous_mind", None)
            if mind and mind.is_running:
                mind.notify_user_interaction()
                await client.websocket.send(
                    response_message(session_id, "Mind paused.", done=True).to_json()
                )
            else:
                await client.websocket.send(
                    response_message(
                        session_id, "Mind not running.", done=True
                    ).to_json()
                )

        else:
            # Try recovery handler — pure Python, no LLM
            if self._recovery:
                recovery_result = await self._recovery.handle(command, user_id=user_id)
                if recovery_result is not None:
                    await client.websocket.send(
                        response_message(
                            session_id, recovery_result, done=True
                        ).to_json()
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

    async def _session_cleanup_loop(self) -> None:
        """Periodically evict sessions that exceed session_timeout_hours."""
        from datetime import UTC, datetime, timedelta

        timeout = timedelta(hours=self._session_timeout_hours)

        while True:
            try:
                await asyncio.sleep(600)  # check every 10 minutes
                now = datetime.now(UTC)
                stale: list[str] = []
                for sid, _clients in self._session_clients.items():
                    session = await self._sessions.get(sid)
                    if session and (now - session.last_active) > timeout:
                        stale.append(sid)

                for sid in stale:
                    # Remove session subscription and evict from cache
                    client_ids = self._session_clients.pop(sid, set())
                    self._sessions._cache.pop(sid, None)
                    logger.info(
                        "Evicted stale session %s (%d clients)",
                        sid[:8],
                        len(client_ids),
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("Session cleanup tick error", exc_info=True)

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
