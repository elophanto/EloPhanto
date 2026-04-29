"""Pump.fun livestream chat client (Socket.IO) — internal helper.

Pump.fun's live chat panel runs on ``wss://livechat.pump.fun`` over
Socket.IO v4. Auth uses the same JWT cookie issued by
``frontend-api-v3.pump.fun/auth/login``; the cookie is also passed
explicitly in the Socket.IO ``auth`` payload as ``token`` because
the server reads either source.

This module wraps a one-shot send + history fetch so callers don't
need to manage the connection lifecycle. For sustained read streams
(reactions, viewer presence) build a longer-lived client on top of
``LivechatClient`` directly.

Events used (verified by reverse-engineering pump.fun's frontend JS,
see ``useLivechatSocketEmitters`` in the bundle):

    joinRoom         emit {roomId, username}        ack {authenticated, userAddress, isCreator, isRoomModerator, roomConfig}
    leaveRoom        emit {roomId, username}        no ack
    sendMessage      emit {roomId, message, username, replyToId, replyPreview}
                                                    ack {id, roomId, message, username, userAddress, profile_image, ...}
    getMessageHistory emit {roomId, ...}            ack {messages: [...]}
    pinMessage / unpinMessage / addReaction / removeReaction / viewerHeartbeat — supported but not exposed here.

Server broadcasts ``newMessage`` to all subscribers when any message
posts (including your own).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

LIVECHAT_URL = "wss://livechat.pump.fun"
LIVECHAT_PATH = "/socket.io/"
PUMP_ORIGIN = "https://pump.fun"


class PumpChatError(RuntimeError):
    """Raised on any pump.fun chat client failure surfaced to caller."""


class LivechatClient:
    """One-shot Socket.IO client for pump.fun's live chat.

    Connects, joins a room, executes a small sequence of emits,
    disconnects. ``async with`` semantics so the socket always closes
    on exit (no leaked file descriptors when the agent exits mid-call).
    """

    def __init__(self, jwt: str, *, connect_timeout: float = 15.0) -> None:
        if not jwt:
            raise PumpChatError("LivechatClient needs a non-empty pump.fun JWT.")
        self._jwt = jwt
        self._connect_timeout = connect_timeout
        self._sio: Any = None
        self._joined: set[str] = set()

    async def __aenter__(self) -> LivechatClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        # Lazy import — socketio is a heavyweight dep, not needed unless
        # someone actually opens chat. Importing inside keeps tool registry
        # startup cheap.
        try:
            import socketio
        except ImportError as e:
            raise PumpChatError(
                "python-socketio not installed. Run "
                "`uv add 'python-socketio[asyncio_client]>=5.11'`."
            ) from e

        sio = socketio.AsyncClient(logger=False, engineio_logger=False)
        self._sio = sio

        try:
            await asyncio.wait_for(
                sio.connect(
                    LIVECHAT_URL,
                    headers={
                        "Cookie": f"auth_token={self._jwt}",
                        "Origin": PUMP_ORIGIN,
                        "User-Agent": "Mozilla/5.0 (compatible; EloPhanto-livestream)",
                    },
                    socketio_path=LIVECHAT_PATH,
                    transports=["websocket"],
                    auth={
                        "origin": PUMP_ORIGIN,
                        "timestamp": int(time.time() * 1000),
                        "token": self._jwt,
                    },
                ),
                timeout=self._connect_timeout,
            )
        except Exception as e:
            raise PumpChatError(f"Could not connect to {LIVECHAT_URL}: {e}") from e
        logger.debug("[livechat] connected sid=%s", sio.sid)

    async def disconnect(self) -> None:
        sio = self._sio
        if sio is None:
            return
        try:
            await sio.disconnect()
        except Exception:
            pass
        self._sio = None
        self._joined.clear()

    async def join_room(self, room_id: str, username: str) -> dict[str, Any]:
        """Idempotent — silently no-ops on subsequent calls for the same room."""
        if room_id in self._joined:
            return {"authenticated": True, "cached": True}
        if self._sio is None:
            raise PumpChatError("Not connected. Call connect() first.")
        ack = await self._sio.call(
            "joinRoom", {"roomId": room_id, "username": username}, timeout=10
        )
        if isinstance(ack, dict) and ack.get("error"):
            raise PumpChatError(f"joinRoom failed: {ack['error']}")
        self._joined.add(room_id)
        return ack if isinstance(ack, dict) else {"raw": ack}

    async def send_message(
        self,
        room_id: str,
        username: str,
        text: str,
        *,
        reply_to_id: str | None = None,
        reply_preview: str | None = None,
    ) -> dict[str, Any]:
        if not text or not text.strip():
            raise PumpChatError("Cannot send an empty message.")
        if self._sio is None:
            raise PumpChatError("Not connected. Call connect() first.")
        await self.join_room(room_id, username)
        ack = await self._sio.call(
            "sendMessage",
            {
                "roomId": room_id,
                "message": text,
                "username": username,
                "replyToId": reply_to_id,
                "replyPreview": reply_preview,
            },
            timeout=10,
        )
        if isinstance(ack, dict) and ack.get("error"):
            raise PumpChatError(f"sendMessage rejected: {ack['error']}")
        return ack if isinstance(ack, dict) else {"raw": ack}

    async def get_message_history(
        self, room_id: str, username: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        if self._sio is None:
            raise PumpChatError("Not connected. Call connect() first.")
        await self.join_room(room_id, username)
        ack = await self._sio.call(
            "getMessageHistory",
            {"roomId": room_id, "limit": int(limit)},
            timeout=10,
        )
        if isinstance(ack, dict):
            if ack.get("error"):
                raise PumpChatError(f"getMessageHistory failed: {ack['error']}")
            messages = ack.get("messages") or ack.get("data") or []
            if isinstance(messages, list):
                return messages
        if isinstance(ack, list):
            return ack
        return []
