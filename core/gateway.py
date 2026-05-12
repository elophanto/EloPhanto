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
import json
import logging
from dataclasses import dataclass
from typing import Any

from core.protocol import (
    EventType,
    GatewayMessage,
    MessageType,
    approval_request_message,
    capability_response_message,
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

    # Agent-to-agent identity (filled in by IDENTIFY handshake, optional).
    # peer_verified=True ⇔ the peer signed our challenge with the private
    # key matching the public_key recorded for `peer_agent_id` in the
    # trust ledger, AND that ledger entry is not blocked.
    # Legacy clients (no IDENTIFY) leave these empty / False — tools that
    # need verified peers must check `peer_verified`.
    peer_agent_id: str = ""
    peer_public_key: str = ""
    peer_trust_level: str = ""
    peer_verified: bool = False
    # Server-side challenge bytes (base64) we issued — peer must sign
    # exactly these to prove key ownership. Rotated after a successful
    # IDENTIFY so each handshake uses a fresh nonce.
    pending_challenge: str = ""

    # Connect-time anchors used to enforce verified-peers mode: we
    # remember when the client connected (so the grace window can be
    # measured) and whether it came in over loopback (loopback is
    # always exempt from peer verification — it's the user's own
    # CLI/Web/VSCode adapter on the same machine).
    connected_at_monotonic: float = 0.0
    is_loopback: bool = False


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
        tls_cert: str = "",
        tls_key: str = "",
        require_verified_peers: bool = False,
        verify_grace_seconds: int = 15,
    ) -> None:
        self._agent = agent
        self._sessions = session_manager
        self._host = host
        self._port = port
        self._auth_token = auth_token
        self._max_sessions = max_sessions
        self._session_timeout_hours = session_timeout_hours
        self._unified_sessions = unified_sessions
        self._tls_cert = tls_cert
        self._tls_key = tls_key
        self._require_verified_peers = require_verified_peers
        self._verify_grace_seconds = verify_grace_seconds
        self._authority_config = authority_config  # AuthorityConfig | None

        self._clients: dict[str, ClientConnection] = {}
        self._server: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._serve_task: asyncio.Task[None] | None = None

        # Pending approval futures: approval_msg_id → asyncio.Future[bool]
        self._pending_approvals: dict[str, asyncio.Future[bool]] = {}

        # Active chat tasks: client_id → asyncio.Task (for cancellation)
        self._active_chat_tasks: dict[str, asyncio.Task[None]] = {}

        self._session_cleanup_task: asyncio.Task[None] | None = None

        # Map session_id → set of client_ids subscribed to that session
        self._session_clients: dict[str, set[str]] = {}

        # Session IDs whose run_session() is currently in flight. Second
        # chat messages arriving for an in-flight session are routed to
        # ``session.add_pending_message()`` instead of starting a second
        # concurrent run — the running loop picks them up at the next
        # plan boundary (Phase C of docs/74-CONCURRENCY-MIGRATION.md).
        self._inflight_sessions: set[str] = set()

        # Optional kid manager hook — set externally by Agent.initialize()
        # when kids are enabled. Intercepts inbound chat from
        # channel="kid-agent" so kid responses don't pollute the parent's
        # main conversation; instead they go to a per-kid queue that
        # KidManager.exec() awaits.
        self._kid_manager: Any = None

        # Optional agent-identity hooks — set externally by
        # Agent.initialize() once the keypair is loaded and the trust
        # ledger is wired up. When both are present, IDENTIFY messages
        # are processed end-to-end. When absent (e.g. cloud mode without
        # local key), peers can still connect under the legacy
        # auth-token path and end up as session.peer_verified=False.
        self._agent_identity: Any = None  # core.agent_identity.AgentIdentityKey
        self._trust_ledger: Any = None  # core.trust_ledger.TrustLedger

        # Recovery handler — pure Python, no LLM
        router = getattr(agent, "_router", None)
        config = getattr(agent, "_config", None)
        self._recovery = (
            RecoveryHandler(config, router, agent) if config and router else None
        )
        self._health_monitor_task: asyncio.Task[None] | None = None

        # Remote shutdown signal (set by exit/shutdown commands from any channel)
        self._shutdown_event: asyncio.Event = asyncio.Event()

        # Webhook config
        self._webhook_config = getattr(config, "webhooks", None)
        self._webhook_auth_token: str | None = None  # resolved during start
        self._heartbeat_engine: Any = None  # set by agent initialization

    @property
    def url(self) -> str:
        scheme = "wss" if self._tls_enabled() else "ws"
        return f"{scheme}://{self._host}:{self._port}"

    def _tls_enabled(self) -> bool:
        return bool(self._tls_cert and self._tls_key)

    def _build_ssl_context(self) -> Any:
        """Construct an SSLContext from configured cert/key paths.

        Returns None if TLS is not configured. Raised exceptions
        propagate so the gateway fails loudly on bad cert paths
        rather than silently falling back to plaintext."""
        if not self._tls_enabled():
            return None
        import ssl

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=self._tls_cert, keyfile=self._tls_key)
        return ctx

    @property
    def is_running(self) -> bool:
        return self._server is not None

    def _process_http_request(self, connection: Any, request: Any) -> Any:
        """Handle plain HTTP requests (health, webhooks, web UI) before WebSocket upgrade."""
        import mimetypes
        from pathlib import Path

        from websockets.datastructures import Headers
        from websockets.http11 import Response

        if request.path == "/health":
            body = json.dumps(
                {
                    "status": "ok",
                    "sessions": len(self._clients),
                }
            ).encode()
            return Response(
                200,
                "OK",
                Headers({"Content-Type": "application/json"}),
                body,
            )

        # --- Capability discovery ---
        if request.path == "/capabilities":
            body = json.dumps(self._build_capabilities_payload()).encode()
            return Response(
                200,
                "OK",
                Headers({"Content-Type": "application/json"}),
                body,
            )

        # --- Webhook endpoints ---
        if request.path.startswith("/hooks/"):
            return self._handle_webhook(request)

        # --- Static web UI (React SPA) ---
        # Only serve if the web/dist directory exists (cloud/packaged deployments).
        # WebSocket upgrade requests carry an "Upgrade" header — let those through.
        if request.headers.get("Upgrade", "").lower() != "websocket":
            web_dist = Path(__file__).parent.parent / "web" / "dist"
            if web_dist.exists():
                req_path = request.path.split("?")[0].lstrip("/")
                file_path = web_dist / req_path if req_path else web_dist / "index.html"
                # Unknown paths → index.html (SPA client-side routing)
                if not file_path.is_file():
                    file_path = web_dist / "index.html"
                content_type = (
                    mimetypes.guess_type(str(file_path))[0]
                    or "application/octet-stream"
                )
                cache = (
                    "public, max-age=31536000, immutable"
                    if "/assets/" in request.path
                    else "no-cache"
                )
                return Response(
                    200,
                    "OK",
                    Headers({"Content-Type": content_type, "Cache-Control": cache}),
                    file_path.read_bytes(),
                )

        return None  # Continue with WebSocket upgrade

    def _build_capabilities_payload(self) -> dict[str, Any]:
        """Build the capabilities payload used by both HTTP and WebSocket responses."""
        import hashlib

        # Tools
        tools_data: list[dict[str, str]] = []
        registry = getattr(self._agent, "_registry", None)
        if registry:
            for t in registry.all_tools():
                tools_data.append(
                    {
                        "name": t.name,
                        "description": t.description,
                        "group": t.group,
                    }
                )

        # Skills
        skills_data: list[str] = []
        skill_mgr = getattr(self._agent, "_skill_manager", None)
        if skill_mgr:
            skills_data = [s.name for s in skill_mgr.list_skills()]

        # Providers
        providers_data: list[str] = []
        router = getattr(self._agent, "_router", None)
        if router:
            router_cfg = getattr(router, "_config", None)
            if router_cfg and hasattr(router_cfg, "llm"):
                providers_data = list(router_cfg.llm.provider_priority)

        # Channels — derive from connected clients + config
        channels: list[str] = sorted(
            {c.channel for c in self._clients.values() if c.channel}
        )
        if not channels:
            channels = ["cli"]

        # Features — detect from registered tool groups
        tool_groups = {t.get("group", "") for t in tools_data}
        feature_map = {
            "browser": "browser",
            "payment": "payments",
            "email": "email",
            "deployment": "deployment",
            "desktop": "desktop",
            "commune": "commune",
        }
        features = [
            feat for group_key, feat in feature_map.items() if group_key in tool_groups
        ]

        # Agent ID — stable fingerprint from identity or config
        identity_mgr = getattr(self._agent, "_identity_manager", None)
        agent_id = ""
        if identity_mgr:
            ident = getattr(identity_mgr, "_identity", None)
            if ident and hasattr(ident, "name"):
                agent_id = hashlib.sha256(ident.name.encode()).hexdigest()[:16]
        if not agent_id:
            agent_id = hashlib.sha256(
                f"{self._host}:{self._port}".encode()
            ).hexdigest()[:16]

        # Version
        version = getattr(self._agent, "VERSION", "0.0.0")

        return {
            "protocol_version": "1.0",
            "agent_id": agent_id,
            "tools": tools_data,
            "skills": skills_data,
            "providers": providers_data,
            "channels": channels,
            "features": features,
            "version": version,
        }

    def _schedule_async(self, coro: Any) -> None:
        """Schedule a coroutine onto the gateway's running loop.

        Used by synchronous webhook handlers that need to fire a
        background task. Prefers the loop captured at start(); falls
        back to ``get_running_loop()`` (works when called from inside
        the loop's thread); silently drops the coroutine if no loop is
        available (unit tests calling handlers in isolation).

        Replaces ``asyncio.get_event_loop().create_task(...)`` which
        raised RuntimeError under Python 3.13+ when no loop existed in
        the current thread.
        """
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No loop and no captured reference. Close the coroutine
                # so it doesn't emit a "never awaited" warning, then bail.
                coro.close()
                return
        if loop.is_running():
            try:
                # Thread-safe scheduling — works whether we're on the loop
                # thread or another thread (websockets dispatches handlers
                # on the loop thread, but be defensive).
                asyncio.run_coroutine_threadsafe(coro, loop)
                return
            except RuntimeError:
                pass
        # Fall back: create_task within the same thread.
        try:
            loop.create_task(coro)
        except Exception:
            coro.close()

    def _handle_webhook(self, request: Any) -> Any:
        """Route webhook HTTP requests."""
        from websockets.datastructures import Headers
        from websockets.http11 import Response

        # Check if webhooks are enabled
        if not self._webhook_config or not self._webhook_config.enabled:
            body = json.dumps({"error": "webhooks disabled"}).encode()
            return Response(
                404, "Not Found", Headers({"Content-Type": "application/json"}), body
            )

        # Auth check
        if self._webhook_auth_token:
            auth_header = request.headers.get("Authorization", "")
            expected = f"Bearer {self._webhook_auth_token}"
            if auth_header != expected:
                body = json.dumps({"error": "unauthorized"}).encode()
                return Response(
                    401,
                    "Unauthorized",
                    Headers({"Content-Type": "application/json"}),
                    body,
                )

        # Parse body (websockets provides body as bytes on the request)
        raw_body = getattr(request, "body", b"") or b""
        max_bytes = self._webhook_config.max_payload_bytes
        if len(raw_body) > max_bytes:
            body = json.dumps(
                {"error": f"payload too large (max {max_bytes} bytes)"}
            ).encode()
            return Response(
                413,
                "Payload Too Large",
                Headers({"Content-Type": "application/json"}),
                body,
            )

        payload: dict[str, Any] = {}
        if raw_body:
            try:
                payload = json.loads(raw_body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = json.dumps({"error": "invalid JSON"}).encode()
                return Response(
                    400,
                    "Bad Request",
                    Headers({"Content-Type": "application/json"}),
                    body,
                )

        path = request.path

        if path == "/hooks/wake":
            return self._webhook_wake(payload)
        elif path == "/hooks/task":
            return self._webhook_task(payload)
        else:
            body = json.dumps(
                {"error": "unknown hook", "available": ["/hooks/wake", "/hooks/task"]}
            ).encode()
            return Response(
                404, "Not Found", Headers({"Content-Type": "application/json"}), body
            )

    def _webhook_wake(self, payload: dict[str, Any]) -> Any:
        """POST /hooks/wake — trigger an immediate heartbeat check."""
        from websockets.datastructures import Headers
        from websockets.http11 import Response

        heartbeat = self._heartbeat_engine
        if not heartbeat or not heartbeat.is_running:
            body = json.dumps({"error": "heartbeat engine not running"}).encode()
            return Response(
                503,
                "Service Unavailable",
                Headers({"Content-Type": "application/json"}),
                body,
            )

        # Inject event into autonomous mind if available
        event_text = payload.get("event", "External wake trigger received")
        mind = getattr(self._agent, "_autonomous_mind", None)
        if mind:
            mind.inject_event(f"[WEBHOOK] {event_text}")

        # Schedule heartbeat check on next event loop iteration
        self._schedule_async(heartbeat._check_and_execute())

        # Broadcast webhook received event
        self._schedule_async(
            self.broadcast(
                event_message(
                    "",
                    EventType.WEBHOOK_RECEIVED,
                    {"hook": "wake", "event": event_text[:200]},
                ),
                session_id=None,
            )
        )

        body = json.dumps({"status": "ok", "action": "heartbeat_triggered"}).encode()
        return Response(200, "OK", Headers({"Content-Type": "application/json"}), body)

    def _webhook_task(self, payload: dict[str, Any]) -> Any:
        """POST /hooks/task — inject an ad-hoc task for the agent to execute."""
        from websockets.datastructures import Headers
        from websockets.http11 import Response

        task_goal = payload.get("goal", "")
        if not task_goal:
            body = json.dumps({"error": "missing 'goal' in payload"}).encode()
            return Response(
                400,
                "Bad Request",
                Headers({"Content-Type": "application/json"}),
                body,
            )

        # Cap goal length
        task_goal = task_goal[:2000]

        # Schedule the task asynchronously
        self._schedule_async(self._execute_webhook_task(task_goal, payload))

        body = json.dumps({"status": "accepted", "goal": task_goal[:200]}).encode()
        return Response(
            202, "Accepted", Headers({"Content-Type": "application/json"}), body
        )

    async def _execute_webhook_task(self, goal: str, payload: dict[str, Any]) -> None:
        """Execute a webhook-injected task through the agent."""
        await self.broadcast(
            event_message(
                "",
                EventType.WEBHOOK_TASK_STARTED,
                {"goal": goal[:200], "source": payload.get("source", "webhook")},
            ),
            session_id=None,
        )

        # Isolate conversation history
        saved_history = list(self._agent._conversation_history)
        self._agent._conversation_history.clear()

        try:
            max_rounds = 8
            if hasattr(self._agent, "_config") and hasattr(
                self._agent._config, "heartbeat"
            ):
                max_rounds = self._agent._config.heartbeat.max_rounds

            await self._agent.run(goal, max_steps_override=max_rounds)
        except Exception as e:
            logger.error("Webhook task failed: %s", e, exc_info=True)
        finally:
            self._agent._conversation_history = saved_history

    async def start(self) -> None:
        """Start the WebSocket server (non-blocking)."""
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not installed. Run: uv add websockets")
            raise

        # Capture the running loop so synchronous webhook handlers
        # (called from the websockets process_request hook) can schedule
        # background tasks without relying on the deprecated
        # asyncio.get_event_loop() lookup that raises in Python 3.13+.
        self._loop = asyncio.get_running_loop()

        ssl_ctx = self._build_ssl_context()
        self._server = await websockets.serve(
            self._handle_connection,
            self._host,
            self._port,
            process_request=self._process_http_request,
            # Increase keepalive tolerance — long-running tasks (heartbeat,
            # scheduled, browser automation) can starve the event loop for
            # extended periods, causing default 20s pings to time out.
            ping_interval=60,
            ping_timeout=120,
            ssl=ssl_ctx,
        )
        logger.info(
            "Gateway started on %s (tls=%s, require_verified_peers=%s)",
            self.url,
            "on" if ssl_ctx else "off",
            self._require_verified_peers,
        )

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

        # Mark connect time + loopback status. Loopback connections are
        # always exempt from verified-peers enforcement — they're the
        # user's own CLI/Web/VSCode adapters running on the same machine,
        # and asking them to speak IDENTIFY would gain nothing.
        import time as _time

        client.connected_at_monotonic = _time.monotonic()
        try:
            remote = websocket.remote_address
            host = remote[0] if remote else ""
            client.is_loopback = host in ("127.0.0.1", "::1", "localhost")
        except Exception:
            client.is_loopback = False

        # Issue an IDENTIFY challenge if agent identity is wired. Peers
        # speaking the protocol will sign exactly this nonce and send it
        # back in their first IDENTIFY message; legacy peers ignore the
        # field and fall through to auth-token-only with peer_verified=False.
        challenge_b64 = ""
        if self._agent_identity is not None:
            import base64

            from core.agent_identity import make_nonce

            challenge_b64 = base64.b64encode(make_nonce()).decode("ascii")
            client.pending_challenge = challenge_b64

        self._clients[client_id] = client
        logger.info(
            "Client connected: %s (loopback=%s)",
            client_id[:8],
            client.is_loopback,
        )

        try:
            # Send ready status. The optional `identify_challenge` lets
            # IDENTIFY-aware peers sign + reply without an extra round-trip.
            status_payload: dict[str, Any] = {"client_id": client_id}
            if challenge_b64:
                status_payload["identify_challenge"] = challenge_b64
                status_payload["our_agent_id"] = self._agent_identity.agent_id
                status_payload["our_public_key"] = self._agent_identity.public_key_b64()
            await websocket.send(status_message("connected", status_payload).to_json())

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
            MessageType.CAPABILITY_REQUEST: self._handle_capability_request,
            MessageType.IDENTIFY: self._handle_identify,
        }

        handler = handlers.get(msg.type)  # type: ignore[call-overload]
        if handler:
            await handler(client, msg)
        else:
            await client.websocket.send(
                error_message(f"Unknown message type: {msg.type}").to_json()
            )

    def _peer_verification_check(self, client: ClientConnection) -> tuple[bool, str]:
        """Decide whether a client may send sensitive messages (CHAT,
        COMMAND, etc.) given the current verified-peers policy.

        Returns ``(allowed, reason)``. The order matters:
            1. Policy off → always allow.
            2. Loopback → always allow (local UI bypass).
            3. peer_verified → allow.
            4. Inside grace window → allow (let the IDENTIFY round-trip
               complete; otherwise legitimate peers race the handshake).
            5. Otherwise → deny, with a clear reason.
        """
        if not self._require_verified_peers:
            return True, ""
        if client.is_loopback:
            return True, ""
        if client.peer_verified:
            return True, ""
        import time as _time

        elapsed = _time.monotonic() - (client.connected_at_monotonic or 0.0)
        if elapsed < self._verify_grace_seconds:
            return True, ""
        return False, (
            "verified-peers mode is enabled and this client has not "
            "completed the IDENTIFY handshake within "
            f"{self._verify_grace_seconds}s of connecting"
        )

    async def _handle_chat(self, client: ClientConnection, msg: GatewayMessage) -> None:
        """Handle a chat message — route to agent with session isolation."""
        # Verified-peers gate. Loopback clients (local CLI/Web/VSCode)
        # are always exempt. Non-loopback unverified peers are refused
        # if the gateway is configured for require_verified_peers.
        allowed, reason = self._peer_verification_check(client)
        if not allowed:
            await client.websocket.send(
                error_message(f"chat refused: {reason}", client.session_id).to_json()
            )
            return

        # Kid agents: inbound chat from a kid container goes to the kid
        # manager's per-kid queue, NOT to the parent's agent loop. This
        # keeps kid responses out of the parent's conversation history;
        # KidManager.exec() awaits the queue and returns the kid's output
        # to whatever called it (the kid_exec tool).
        kid_channel = (msg.channel or client.channel or "") == "kid-agent"
        if kid_channel and self._kid_manager is not None:
            try:
                await self._kid_manager.handle_kid_message(msg)
            except Exception as e:
                logger.debug("kid_manager.handle_kid_message failed: %s", e)
            return

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

        # Phase C interrupt routing: if a turn is already running for
        # this session, fold the new message into it instead of starting
        # a second concurrent run (which would corrupt conversation
        # history). The running plan loop drains pending messages at the
        # next plan boundary and folds them in as
        # "[user added mid-turn: ...]" turns. See
        # docs/74-CONCURRENCY-MIGRATION.md Phase C.
        if session.session_id in self._inflight_sessions:
            session.add_pending_message(content)
            await self.broadcast(
                event_message(
                    session.session_id,
                    EventType.STEP_PROGRESS,
                    {
                        "step": -1,
                        "tool_name": "(mid-turn)",
                        "thought": (
                            "Added your message to the running turn. The "
                            "agent will pick it up at the next plan step."
                        ),
                    },
                ),
                session_id=session.session_id,
            )
            logger.info(
                "Phase C: routed mid-turn message into session %s "
                "(turn already in flight)",
                session.session_id[:8],
            )
            return

        # Run agent with session isolation
        self._inflight_sessions.add(session.session_id)
        try:
            agent_response = await self._agent.run_session(
                goal=content,
                session=session,
                approval_callback=session_approval_callback,
                on_step=on_step,
                authority=authority,
            )

            # ── Send response FIRST before any DB work ───────────────────────
            # DB inserts after agent completion can block if a background task
            # (lesson extraction, directive detection, etc.) holds a write lock.
            # The user must never wait for housekeeping.
            # Get last provider/model from cost tracker
            _last_provider = ""
            _last_model = ""
            if self._agent._router.cost_tracker.calls:
                _last_call = self._agent._router.cost_tracker.calls[-1]
                _last_provider = _last_call.get("provider", "")
                _last_model = _last_call.get("model", "")

            resp = response_message(
                session.session_id,
                agent_response.content,
                done=True,
                reply_to=msg.id,
                provider=_last_provider,
                model=_last_model,
            )
            if self._unified_sessions:
                await self.broadcast(resp, session_id=session.session_id)
            else:
                await client.websocket.send(resp.to_json())

            # ── Persist session + chat messages (background, non-blocking) ───
            async def _persist() -> None:
                import uuid as _uuid
                from datetime import UTC
                from datetime import datetime as _dt

                try:
                    await self._sessions.save(session)
                except Exception:
                    pass

                try:
                    _now = _dt.now(UTC).isoformat()
                    _conv_id = client.conversation_id

                    if not _conv_id:
                        _conv_id = str(_uuid.uuid4())
                        client.conversation_id = _conv_id
                        _title = (
                            content[:50].replace("\n", " ").strip()
                            or "New conversation"
                        )
                        await self._agent._db.execute_insert(
                            "INSERT INTO conversations"
                            " (conversation_id, title, created_at, updated_at)"
                            " VALUES (?, ?, ?, ?)",
                            (_conv_id, _title, _now, _now),
                        )
                    else:
                        await self._agent._db.execute_insert(
                            "UPDATE conversations SET updated_at = ?"
                            " WHERE conversation_id = ?",
                            (_now, _conv_id),
                        )

                    await self._agent._db.execute_insert(
                        "INSERT INTO chat_messages"
                        " (session_id, msg_id, role, content, created_at, conversation_id)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (session.session_id, msg.id, "user", content, _now, _conv_id),
                    )
                    await self._agent._db.execute_insert(
                        "INSERT INTO chat_messages"
                        " (session_id, msg_id, role, content, created_at, conversation_id)"
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
                except Exception:
                    pass

            asyncio.create_task(_persist())

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
        finally:
            # Phase C: release the in-flight marker so the next message
            # for this session starts a fresh turn (or, if more pending
            # messages are sitting in the buffer, the next run_session
            # call drains them on its first iteration).
            self._inflight_sessions.discard(session.session_id)

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
        self._pending_approvals[req.id] = asyncio.get_running_loop().create_future()

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

    # Commands that modify secrets or agent config — require OWNER authority.
    _OWNER_ONLY_COMMANDS: frozenset[str] = frozenset({"vault_set", "config_update"})

    async def _handle_command(
        self, client: ClientConnection, msg: GatewayMessage
    ) -> None:
        """Handle slash commands — including recovery commands (no LLM)."""
        # Verified-peers gate. Same policy as _handle_chat: loopback
        # exempt, peer_verified or grace-window required for non-loopback.
        allowed, reason = self._peer_verification_check(client)
        if not allowed:
            await client.websocket.send(
                error_message(f"command refused: {reason}", client.session_id).to_json()
            )
            return

        command = msg.data.get("command", "")
        session_id = msg.session_id or client.session_id
        user_id = msg.user_id or client.user_id

        # --- RBAC: block sensitive commands for non-owner users ---
        if command in self._OWNER_ONLY_COMMANDS:
            from core.authority import AuthorityLevel, resolve_authority

            channel = msg.channel or client.channel or "unknown"
            authority = resolve_authority(
                channel, user_id or "", self._authority_config
            )
            if authority != AuthorityLevel.OWNER:
                logger.warning(
                    "RBAC denied %s for %s:%s (authority=%s)",
                    command,
                    channel,
                    (user_id or "")[:8],
                    authority.value,
                )
                await client.websocket.send(
                    error_message(
                        f"Permission denied: '{command}' requires owner authority",
                        session_id,
                    ).to_json()
                )
                return

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

            # Ego — structured fields (NOT prose). The dashboard's
            # footer is one line; cramming `last_self_critique` or
            # `self_image` into it produces truncated garble. Send the
            # *evaluative* numbers and let the dashboard derive a
            # one-word qualifier client-side.
            #
            # Why not send mood prose at all:
            #   - last_self_critique is "the single sharpest thing I'd
            #     say about myself if I were being unsparing" — not a
            #     mood, an unsparing critique. Wrong tone for a footer.
            #   - self_image is 3-5 sentences. Won't fit.
            #   - proud_of / embarrassed_by / aspiration are
            #     concept-per-field, not single-line summaries.
            #
            # The numeric coherence + capability confidence give the
            # dashboard everything it needs to render an honest
            # one-word qualifier ("settled" / "steady" / "questioning"
            # / "shaken" / "humbled" / "stale").
            ego_mgr = getattr(self._agent, "_ego_manager", None)
            if ego_mgr:
                try:
                    ego = await ego_mgr.get_ego()
                    # Confidence stats — used to detect "broadly
                    # uncertain" (low mean) vs "lopsided" (high range)
                    # ego states the coherence score alone misses.
                    # Field name is `confidence` (dict on the dataclass)
                    # — `confidence_json` is the SQL column name only.
                    # Got this wrong on first pass; the AttributeError
                    # was being swallowed by the broad except below
                    # which sent ego=None and rendered footer 'ego –'.
                    confidence_dict = getattr(ego, "confidence", None) or {}
                    confidences: list[float] = [
                        float(v)
                        for v in confidence_dict.values()
                        if isinstance(v, int | float)
                    ]
                    confidence_avg = (
                        sum(confidences) / len(confidences) if confidences else 0.0
                    )
                    confidence_min = min(confidences) if confidences else 0.0
                    confidence_max = max(confidences) if confidences else 0.0
                    humbling_count = (
                        len(ego.humbling_events)
                        if hasattr(ego, "humbling_events")
                        else 0
                    )
                    dashboard["ego"] = {
                        "coherence": float(ego.coherence_score),
                        "confidence_avg": float(confidence_avg),
                        "confidence_min": float(confidence_min),
                        "confidence_max": float(confidence_max),
                        "humbling_count": int(humbling_count),
                        "tasks_since_recompute": int(
                            getattr(ego, "tasks_since_recompute", 0)
                        ),
                    }
                except Exception:
                    dashboard["ego"] = None
            else:
                dashboard["ego"] = None

            # Mind
            mind = getattr(self._agent, "_autonomous_mind", None)
            if mind:
                try:
                    dashboard["mind"] = mind.get_status()
                except Exception:
                    dashboard["mind"] = None
            else:
                dashboard["mind"] = None

            # Goals — emit BOTH the legacy detailed shape (web
            # dashboard, /goal_status tool, etc.) AND the compact
            # shape the new sidebar/digest consumes. Web dashboard
            # already reads the legacy keys; sidebar reads only the
            # compact shape. Both layers are stable contracts now.
            goal_mgr = getattr(self._agent, "_goal_manager", None)
            if goal_mgr:
                try:
                    goals = await goal_mgr.list_goals(limit=10)
                    dashboard["goals"] = [
                        {
                            # Legacy keys — kept for downstream
                            # consumers that already read these.
                            "goal_id": g.goal_id,
                            "goal": g.goal[:120],
                            "status": g.status,
                            "current_checkpoint": g.current_checkpoint,
                            "total_checkpoints": g.total_checkpoints,
                            "cost_usd": g.cost_usd,
                            "created_at": g.created_at,
                            # Compact keys — consumed by sidebar
                            # GoalsPanel + digest auto-derivation.
                            # Title is the goal text capped to 60
                            # chars (sidebar truncates further to 8).
                            # pct = current/total * 100; rounded to int.
                            "title": g.goal[:60],
                            "pct": (
                                int(g.current_checkpoint / g.total_checkpoints * 100)
                                if g.total_checkpoints > 0
                                else 0
                            ),
                            "checkpoint": (
                                f"{g.current_checkpoint}/{g.total_checkpoints}"
                                if g.total_checkpoints > 0
                                else ""
                            ),
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

            # Provider health — use router._provider_health + config priority
            router = getattr(self._agent, "_router", None)
            providers_health: dict[str, Any] = {}
            if router:
                try:
                    router_cfg = getattr(router, "_config", None)
                    priority: list[str] = (
                        router_cfg.llm.provider_priority if router_cfg else []
                    )
                    health_map: dict[str, bool] = getattr(
                        router, "_provider_health", {}
                    )
                    llm_cfg = router_cfg.llm if router_cfg else None
                    for pname in priority:
                        # providers is a dict, not attributes
                        prov_cfg = llm_cfg.providers.get(pname) if llm_cfg else None
                        enabled = (
                            getattr(prov_cfg, "enabled", True) if prov_cfg else True
                        )
                        if not enabled:
                            # Disabled providers always show as off — skip health check
                            providers_health[pname] = {
                                "healthy": False,
                                "enabled": False,
                                "latency_ms": 0,
                            }
                            continue
                        # Enabled but not yet in health map → assume ok
                        healthy = health_map.get(pname, True)
                        providers_health[pname] = {
                            "healthy": healthy,
                            "enabled": True,
                            "latency_ms": 0,
                        }
                except Exception:
                    pass
            dashboard["providers"] = providers_health

            # Full scheduled tasks list (for sidebar)
            if scheduler:
                try:
                    sched_entries = await scheduler.list_schedules()
                    dashboard["scheduled_tasks"] = [
                        {
                            "name": s.name,
                            "enabled": s.enabled,
                            "next_run_at": s.next_run_at,
                            "last_run_at": s.last_run_at,
                            "last_status": s.last_status,
                        }
                        for s in sched_entries
                        if s.enabled
                    ]
                except Exception:
                    dashboard["scheduled_tasks"] = []
            else:
                dashboard["scheduled_tasks"] = []

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

        elif command == "settings_get":
            # Return current settings state for the Settings UI
            import json as _json

            config = getattr(self._agent, "_config", None)
            vault = getattr(self._agent, "_vault", None)
            vault_keys: list[str] = vault.list_keys() if vault else []

            providers_info: list[dict[str, Any]] = []
            _PROVIDER_VAULT_MAP = {
                "openrouter": "openrouter_api_key",
                "openai": "openai_api_key",
                "zai": "zai_api_key",
                "kimi": "kimi_api_key",
            }
            _KNOWN_PROVIDERS = ["openrouter", "openai", "zai", "kimi", "ollama"]

            # Collect models per provider from routing config
            provider_models: dict[str, list[str]] = {}
            if config:
                for task_cfg in config.llm.routing.values():
                    for prov, model in (task_cfg.models or {}).items():
                        if model and model not in provider_models.get(prov, []):
                            provider_models.setdefault(prov, []).append(model)
                # Include default_model at the front of each provider's list
                for pname, pcfg in config.llm.providers.items():
                    if pcfg.default_model:
                        lst = provider_models.setdefault(pname, [])
                        if pcfg.default_model not in lst:
                            lst.insert(0, pcfg.default_model)

            seen: set[str] = set()
            if config:
                for name, pcfg in config.llm.providers.items():
                    seen.add(name)
                    vault_key = _PROVIDER_VAULT_MAP.get(name, f"{name}_api_key")
                    providers_info.append(
                        {
                            "name": name,
                            "enabled": pcfg.enabled,
                            "base_url": pcfg.base_url,
                            "has_key": bool(pcfg.api_key) or vault_key in vault_keys,
                            "default_model": pcfg.default_model,
                            "available_models": provider_models.get(name, []),
                        }
                    )
            for name in _KNOWN_PROVIDERS:
                if name not in seen:
                    vault_key = _PROVIDER_VAULT_MAP.get(name, f"{name}_api_key")
                    providers_info.append(
                        {
                            "name": name,
                            "enabled": False,
                            "base_url": "",
                            "has_key": vault_key in vault_keys,
                            "default_model": "",
                            "available_models": provider_models.get(name, []),
                        }
                    )

            payload = _json.dumps(
                {
                    "settings": {
                        "agent_name": config.agent_name if config else "EloPhanto",
                        "permission_mode": (
                            config.permission_mode if config else "ask_always"
                        ),
                        "providers": providers_info,
                        "vault_unlocked": vault is not None,
                        "vault_keys": vault_keys,
                        "config_path": str(getattr(config, "config_path", "") or ""),
                    }
                }
            )
            await client.websocket.send(
                response_message(session_id, payload, done=True).to_json()
            )

        elif command == "vault_set":
            # Store a secret in the vault (creates vault in cloud mode if needed)
            import json as _json
            import os as _os

            args = msg.data.get("args") or {}
            key = str(args.get("key", "")).strip()
            value = str(args.get("value", "")).strip()
            if not key:
                await client.websocket.send(
                    error_message("vault_set: key is required", session_id).to_json()
                )
                return

            vault = getattr(self._agent, "_vault", None)
            if vault is None:
                # In cloud mode, auto-create vault with the env password
                cloud_mode = _os.environ.get("ELOPHANTO_CLOUD") == "1"
                vault_password = _os.environ.get("ELOPHANTO_VAULT_PASSWORD", "")
                config = getattr(self._agent, "_config", None)
                base_dir = str(config.project_root) if config else "."
                if cloud_mode and vault_password:
                    from core.vault import Vault as _Vault

                    try:
                        if _Vault.exists(base_dir):
                            vault = _Vault.unlock(base_dir, vault_password)
                        else:
                            vault = _Vault.create(base_dir, vault_password)
                        self._agent._vault = vault
                    except Exception as ve:
                        await client.websocket.send(
                            error_message(f"Vault error: {ve}", session_id).to_json()
                        )
                        return
                else:
                    await client.websocket.send(
                        error_message(
                            "Vault is not unlocked. Set ELOPHANTO_VAULT_PASSWORD secret.",
                            session_id,
                        ).to_json()
                    )
                    return

            vault.set(key, value)
            # Also inject into live config if it's an API key
            _VAULT_TO_PROVIDER = {
                "openrouter_api_key": "openrouter",
                "openai_api_key": "openai",
                "zai_api_key": "zai",
                "kimi_api_key": "kimi",
            }
            config = getattr(self._agent, "_config", None)
            if config and key in _VAULT_TO_PROVIDER:
                provider_name = _VAULT_TO_PROVIDER[key]
                from core.config import ProviderConfig as _ProviderConfig

                if provider_name not in config.llm.providers:
                    config.llm.providers[provider_name] = _ProviderConfig(
                        api_key=value, enabled=True
                    )
                    if provider_name not in config.llm.provider_priority:
                        config.llm.provider_priority.insert(0, provider_name)
                else:
                    config.llm.providers[provider_name].api_key = value
                    config.llm.providers[provider_name].enabled = True
                # Auto-set default_model if not already set
                _PROVIDER_DEFAULT_MODELS = {
                    "openrouter": "openrouter/hunter-alpha",
                    "openai": "gpt-5.5",
                    "zai": "glm-4.7",
                    "kimi": "kimi-k2.5",
                }
                pcfg = config.llm.providers[provider_name]
                if not pcfg.default_model and provider_name in _PROVIDER_DEFAULT_MODELS:
                    pcfg.default_model = _PROVIDER_DEFAULT_MODELS[provider_name]
                # Re-inject into router
                router = getattr(self._agent, "_router", None)
                if router and hasattr(router, "_config"):
                    router._config = config
                # Re-create embedder so knowledge search uses the new key immediately
                try:
                    from core.embeddings import create_embedder as _create_embedder

                    registry = getattr(self._agent, "_registry", None)
                    if registry:
                        ks = registry.get("knowledge_search")
                        if ks and hasattr(ks, "_embedder"):
                            ks._embedder = _create_embedder(config)
                except Exception:
                    pass

            await client.websocket.send(
                response_message(
                    session_id,
                    _json.dumps({"vault_set": {"ok": True, "key": key}}),
                    done=True,
                ).to_json()
            )

        elif command == "config_update":
            # Update config fields (agent name, permission mode, provider toggles)
            # and persist to config.yaml
            import json as _json
            import os as _os

            args = msg.data.get("args") or {}
            config = getattr(self._agent, "_config", None)
            if not config:
                await client.websocket.send(
                    error_message("No config loaded", session_id).to_json()
                )
                return

            changed: list[str] = []

            if "agent_name" in args:
                config.agent_name = str(args["agent_name"])
                changed.append("agent_name")

            if "permission_mode" in args:
                mode = str(args["permission_mode"])
                if mode in ("ask_always", "smart_auto", "full_auto"):
                    config.permission_mode = mode
                    changed.append("permission_mode")

            from core.config import ProviderConfig as _ProviderConfig2

            _PROVIDER_BASE_URLS = {
                "openrouter": "https://openrouter.ai/api/v1",
                "zai": "https://api.z.ai/api/paas/v4",
                "kimi": "https://api.kilo.ai/api/gateway",
            }

            def _ensure_provider(pname: str) -> None:
                if pname not in config.llm.providers:
                    config.llm.providers[pname] = _ProviderConfig2(
                        base_url=_PROVIDER_BASE_URLS.get(pname, ""),
                    )
                    if pname not in config.llm.provider_priority:
                        config.llm.provider_priority.append(pname)

            _AUTO_DEFAULT_MODELS = {
                "openrouter": "openrouter/hunter-alpha",
                "openai": "gpt-5.5",
                "zai": "glm-4.7",
                "kimi": "kimi-k2.5",
            }

            if "provider_enabled" in args:
                for provider_name, enabled in args["provider_enabled"].items():
                    _ensure_provider(provider_name)
                    config.llm.providers[provider_name].enabled = bool(enabled)
                    # Auto-set default_model if enabling and none is set
                    if (
                        bool(enabled)
                        and not config.llm.providers[provider_name].default_model
                    ):
                        if provider_name in _AUTO_DEFAULT_MODELS:
                            config.llm.providers[provider_name].default_model = (
                                _AUTO_DEFAULT_MODELS[provider_name]
                            )
                    changed.append(f"provider_{provider_name}_enabled")

            if "provider_model" in args:
                for provider_name, model in args["provider_model"].items():
                    _ensure_provider(provider_name)
                    config.llm.providers[provider_name].default_model = str(model)
                    changed.append(f"provider_{provider_name}_model")

            # Persist to config.yaml
            import yaml as _yaml  # type: ignore[import]

            config_path = _os.environ.get("ELOPHANTO_CONFIG") or "config.yaml"
            try:
                try:
                    with open(config_path) as _f:
                        existing = _yaml.safe_load(_f) or {}
                except FileNotFoundError:
                    existing = {}

                # Patch only the changed fields
                if "agent_name" in changed:
                    existing.setdefault("agent", {})["name"] = config.agent_name
                if "permission_mode" in changed:
                    existing.setdefault("agent", {})[
                        "permission_mode"
                    ] = config.permission_mode
                if any("provider_" in c for c in changed):
                    llm = existing.setdefault("llm", {})
                    providers = llm.setdefault("providers", {})
                    for pname, pcfg in config.llm.providers.items():
                        providers.setdefault(pname, {})["enabled"] = pcfg.enabled
                        if pcfg.default_model:
                            providers[pname]["default_model"] = pcfg.default_model

                _os.makedirs(
                    _os.path.dirname(_os.path.abspath(config_path)), exist_ok=True
                )
                with open(config_path, "w") as _f:
                    _f.write(_yaml.dump(existing, allow_unicode=True))
            except Exception as e:
                logger.warning("config_update: failed to persist: %s", e)

            status_key = args.get("_status_key", "config")
            await client.websocket.send(
                response_message(
                    session_id,
                    _json.dumps(
                        {
                            "config_update": {
                                "ok": True,
                                "changed": changed,
                                "status_key": status_key,
                            }
                        }
                    ),
                    done=True,
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

    async def _handle_capability_request(
        self, client: ClientConnection, msg: GatewayMessage
    ) -> None:
        """Handle capability discovery request — return what this agent can do."""
        payload = self._build_capabilities_payload()
        resp = capability_response_message(
            tools=payload["tools"],
            skills=payload["skills"],
            providers=payload["providers"],
            version=payload.get("version", "0.0.0"),
        )
        await client.websocket.send(resp.to_json())

    async def _handle_identify(
        self, client: ClientConnection, msg: GatewayMessage
    ) -> None:
        """Process an IDENTIFY claim from a peer.

        Steps:

        1. Decode ``agent_id``, ``public_key``, ``challenge``,
           ``signature`` from msg.data.
        2. Verify the signature against ``challenge`` using
           ``public_key``. If it doesn't validate → refuse.
        3. Confirm ``agent_id`` matches the public_key (we derive it
           deterministically — peers can't lie about their id).
        4. Confirm the signed challenge matches the one WE issued for
           this client (anti-replay).
        5. Hand the (agent_id, public_key) pair to the trust ledger.
           If it raises ``TrustConflict`` → refuse with reason
           ``public_key_conflict``. If the resulting entry is blocked
           → refuse with reason ``blocked``. Otherwise mark
           ``peer_verified=True`` on the connection.
        6. Mint a fresh challenge and include it in the response so the
           peer can sign it back for mutual auth in a follow-up
           IDENTIFY.

        If the gateway has no agent_identity / trust_ledger wired (cloud
        mode without local key) we send back ``accepted=False`` with
        reason ``protocol_unavailable`` so peers know not to bother.
        """
        from core.agent_identity import (
            TRUST_BLOCKED,
            derive_agent_id_from_public_key,
            make_nonce,
            verify_signature,
        )
        from core.protocol import identify_response_message

        if self._trust_ledger is None or self._agent_identity is None:
            await client.websocket.send(
                identify_response_message(
                    accepted=False,
                    reason="protocol_unavailable",
                ).to_json()
            )
            return

        data = msg.data or {}
        agent_id = str(data.get("agent_id", "")).strip()
        public_key = str(data.get("public_key", "")).strip()
        challenge_b64 = str(data.get("challenge", "")).strip()
        signature_b64 = str(data.get("signature", "")).strip()

        if not (agent_id and public_key and challenge_b64 and signature_b64):
            await client.websocket.send(
                identify_response_message(
                    accepted=False, reason="missing_fields"
                ).to_json()
            )
            return

        # 1. agent_id must derive from claimed public_key. This stops a
        # peer from pretending to be a different elo-* than its key
        # implies.
        if derive_agent_id_from_public_key(public_key) != agent_id:
            await client.websocket.send(
                identify_response_message(
                    accepted=False, reason="agent_id_mismatch"
                ).to_json()
            )
            return

        # 2. The challenge MUST be the one we issued for this client —
        # otherwise a peer could replay a signature it intercepted on
        # another connection. (If pending_challenge is empty the gateway
        # never set one; treat as misuse.)
        if not client.pending_challenge:
            await client.websocket.send(
                identify_response_message(
                    accepted=False, reason="no_challenge_issued"
                ).to_json()
            )
            return
        if challenge_b64 != client.pending_challenge:
            await client.websocket.send(
                identify_response_message(
                    accepted=False, reason="challenge_mismatch"
                ).to_json()
            )
            return

        # 3. Signature must validate against the raw challenge bytes.
        import base64

        try:
            challenge_raw = base64.b64decode(challenge_b64)
            signature_raw = base64.b64decode(signature_b64)
        except Exception:
            await client.websocket.send(
                identify_response_message(
                    accepted=False, reason="bad_encoding"
                ).to_json()
            )
            return

        if not verify_signature(public_key, signature_raw, challenge_raw):
            await client.websocket.send(
                identify_response_message(
                    accepted=False, reason="signature_invalid"
                ).to_json()
            )
            return

        # 4. Hand to the trust ledger. TrustConflict → key rotation
        # detected; refuse and let the owner intervene with
        # agent_trust_set.
        from core.trust_ledger import TrustConflict

        try:
            entry = await self._trust_ledger.record_handshake(
                agent_id=agent_id, public_key=public_key
            )
        except TrustConflict:
            await client.websocket.send(
                identify_response_message(
                    accepted=False, reason="public_key_conflict"
                ).to_json()
            )
            return

        if entry.trust_level == TRUST_BLOCKED:
            await client.websocket.send(
                identify_response_message(accepted=False, reason="blocked").to_json()
            )
            return

        # 5. Accepted — record peer identity on the connection.
        client.peer_agent_id = agent_id
        client.peer_public_key = public_key
        client.peer_trust_level = entry.trust_level
        client.peer_verified = True

        # 6. Issue a fresh challenge so the peer can mutually verify us
        # in a return IDENTIFY (signed by our own private key).
        new_challenge = base64.b64encode(make_nonce()).decode("ascii")
        client.pending_challenge = new_challenge

        await client.websocket.send(
            identify_response_message(
                accepted=True,
                trust_level=entry.trust_level,
                challenge_b64=new_challenge,
            ).to_json()
        )
        logger.info(
            "Gateway: IDENTIFY accepted from %s (trust=%s, conn_count=%d)",
            agent_id,
            entry.trust_level,
            entry.connection_count,
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
