"""Base channel adapter — abstract interface for all gateway clients.

Every channel (CLI, Telegram, Discord, Slack, etc.) implements this
interface to connect to the gateway WebSocket and translate between
platform-specific messages and the gateway protocol.
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from core.protocol import (
    GatewayMessage,
    MessageType,
    approval_response_message,
    chat_message,
    command_message,
    status_message,
)

logger = logging.getLogger(__name__)


class ChannelAdapter(ABC):
    """Base class for all channel adapters.

    Subclasses implement platform-specific message handling while
    this base class manages the WebSocket connection to the gateway.
    """

    name: str = "base"

    def __init__(self, gateway_url: str = "ws://127.0.0.1:18789") -> None:
        self._gateway_url = gateway_url
        self._ws: Any = None
        self._running = False
        self._client_id: str = ""

        # Pending response futures: msg_id → Future[GatewayMessage]
        self._pending_responses: dict[str, asyncio.Future[GatewayMessage]] = {}

    @abstractmethod
    async def start(self) -> None:
        """Start the adapter (connect to gateway + start listening)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully disconnect."""
        ...

    @abstractmethod
    async def on_response(self, msg: GatewayMessage) -> None:
        """Handle a response message from the gateway."""
        ...

    @abstractmethod
    async def on_approval_request(self, msg: GatewayMessage) -> None:
        """Handle an approval request from the gateway."""
        ...

    @abstractmethod
    async def on_event(self, msg: GatewayMessage) -> None:
        """Handle an event broadcast from the gateway."""
        ...

    async def on_error(self, msg: GatewayMessage) -> None:
        """Handle an error message. Override for custom behavior."""
        logger.error(
            "Gateway error: %s", msg.data.get("detail", "unknown")
        )

    # ── Gateway connection ──────────────────────────────────────

    async def connect_gateway(self) -> None:
        """Connect to the gateway WebSocket."""
        try:
            import websockets
        except ImportError:
            raise RuntimeError("websockets package required: pip install websockets")

        self._ws = await websockets.connect(self._gateway_url)
        self._running = True

        # Wait for initial connected status
        raw = await self._ws.recv()
        msg = GatewayMessage.from_json(raw)
        if msg.type == MessageType.STATUS:
            self._client_id = msg.data.get("client_id", "")
            logger.info(
                "%s adapter connected to gateway (client=%s)",
                self.name,
                self._client_id[:8],
            )

    async def disconnect_gateway(self) -> None:
        """Disconnect from the gateway."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send_to_gateway(self, msg: GatewayMessage) -> None:
        """Send a message to the gateway."""
        if self._ws:
            await self._ws.send(msg.to_json())

    async def send_chat(
        self, content: str, user_id: str, session_id: str = "",
        attachments: list[dict] | None = None,
    ) -> GatewayMessage:
        """Send a chat message and wait for the response."""
        msg = chat_message(
            content=content,
            channel=self.name,
            user_id=user_id,
            session_id=session_id,
            attachments=attachments,
        )

        # Create future for response
        future: asyncio.Future[GatewayMessage] = asyncio.get_event_loop().create_future()
        self._pending_responses[msg.id] = future

        await self.send_to_gateway(msg)

        try:
            return await asyncio.wait_for(future, timeout=600)
        except asyncio.TimeoutError:
            logger.warning("Chat response timed out for message %s", msg.id[:8])
            raise
        finally:
            self._pending_responses.pop(msg.id, None)

    async def send_approval(self, request_id: str, approved: bool) -> None:
        """Send an approval response to the gateway."""
        msg = approval_response_message(request_id, approved)
        await self.send_to_gateway(msg)

    async def send_command(
        self, command: str, args: dict | None = None, user_id: str = "",
        session_id: str = "",
    ) -> None:
        """Send a slash command to the gateway."""
        msg = command_message(
            command=command,
            args=args,
            channel=self.name,
            user_id=user_id,
            session_id=session_id,
        )
        await self.send_to_gateway(msg)

    async def gateway_listener(self) -> None:
        """Listen for messages from the gateway and dispatch to handlers."""
        if not self._ws:
            return

        try:
            async for raw in self._ws:
                try:
                    msg = GatewayMessage.from_json(raw)
                    await self._dispatch(msg)
                except Exception as e:
                    logger.error("Error processing gateway message: %s", e)
        except Exception as e:
            if self._running:
                logger.error("Gateway connection lost: %s", e)
            self._running = False

    async def _dispatch(self, msg: GatewayMessage) -> None:
        """Route incoming gateway messages to the appropriate handler."""
        if msg.type == MessageType.RESPONSE:
            # Check if this is a reply to a pending request
            reply_to = msg.data.get("reply_to", "")
            future = self._pending_responses.get(reply_to)
            if future and not future.done():
                future.set_result(msg)
            else:
                await self.on_response(msg)

        elif msg.type == MessageType.APPROVAL_REQUEST:
            await self.on_approval_request(msg)

        elif msg.type == MessageType.EVENT:
            await self.on_event(msg)

        elif msg.type == MessageType.ERROR:
            # Check if this is a reply to a pending request
            reply_to = msg.data.get("reply_to", "")
            future = self._pending_responses.get(reply_to)
            if future and not future.done():
                future.set_exception(
                    RuntimeError(msg.data.get("detail", "Gateway error"))
                )
            else:
                await self.on_error(msg)

        elif msg.type == MessageType.STATUS:
            pass  # Heartbeat, ignore
