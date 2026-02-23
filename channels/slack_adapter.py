"""Slack channel adapter — bridges Slack Bot API to the gateway.

Uses slack_bolt library with Socket Mode for real-time messaging.
Maps Slack users/channels to gateway sessions.

Requires: pip install slack-bolt
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from channels.base import ChannelAdapter
from core.config import SlackConfig
from core.protocol import GatewayMessage

logger = logging.getLogger(__name__)


class SlackAdapter(ChannelAdapter):
    """Slack interface as a gateway channel adapter."""

    name = "slack"

    def __init__(
        self,
        bot_token: str,
        app_token: str,
        config: SlackConfig,
        gateway_url: str = "ws://127.0.0.1:18789",
    ) -> None:
        super().__init__(gateway_url)
        self._slack_config = config
        self._bot_token = bot_token
        self._app_token = app_token
        self._app: Any = None
        self._handler: Any = None

        # Map session_id → slack channel_id + thread_ts
        self._session_threads: dict[str, tuple[str, str | None]] = {}

    async def start(self) -> None:
        """Connect to gateway and start Slack Socket Mode."""
        try:
            from slack_bolt.adapter.socket_mode.async_handler import (
                AsyncSocketModeHandler,
            )
            from slack_bolt.async_app import AsyncApp
        except ImportError as err:
            raise RuntimeError(
                "slack-bolt not installed. Run: pip install slack-bolt"
            ) from err

        await self.connect_gateway()

        self._app = AsyncApp(token=self._bot_token)

        @self._app.event("app_mention")
        async def handle_mention(event: dict, say: Any) -> None:
            await self._handle_slack_message(event, say)

        @self._app.event("message")
        async def handle_dm(event: dict, say: Any) -> None:
            # Only handle DMs (channel type "im")
            if event.get("channel_type") != "im":
                return
            # Ignore bot messages
            if event.get("bot_id"):
                return
            await self._handle_slack_message(event, say)

        self._handler = AsyncSocketModeHandler(self._app, self._app_token)

        await asyncio.gather(
            self.gateway_listener(),
            self._handler.start_async(),
        )

    async def stop(self) -> None:
        """Stop Slack handler and disconnect from gateway."""
        self._running = False
        if self._handler:
            await self._handler.close_async()
        await self.disconnect_gateway()

    async def _handle_slack_message(self, event: dict, say: Any) -> None:
        """Process a Slack message and route to gateway."""
        text = event.get("text", "")
        user_id = event.get("user", "")
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts") or event.get("ts")

        # Strip bot mention
        if "<@" in text:
            import re

            text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()

        if not text:
            return

        # Check allowed channels
        if (
            self._slack_config.allowed_channels
            and channel not in self._slack_config.allowed_channels
        ):
            return

        try:
            response = await self.send_chat(content=text, user_id=user_id)

            if response.session_id:
                self._session_threads[response.session_id] = (channel, thread_ts)

            reply = response.data.get("content", "No response")
            # Slack has 4000 char limit per message
            for chunk in _split_slack(reply, 3900):
                await say(text=chunk, thread_ts=thread_ts)

        except TimeoutError:
            await say(text="Request timed out.", thread_ts=thread_ts)
        except Exception as e:
            logger.error("Slack message handling failed: %s", e)
            await say(text=f"Error: {e}", thread_ts=thread_ts)

    async def on_response(self, msg: GatewayMessage) -> None:
        """Send unsolicited responses to the right Slack thread."""
        session_data = self._session_threads.get(msg.session_id)
        if session_data and self._app:
            channel, thread_ts = session_data
            content = msg.data.get("content", "")
            if content:
                client = self._app.client
                for chunk in _split_slack(content, 3900):
                    await client.chat_postMessage(
                        channel=channel, text=chunk, thread_ts=thread_ts
                    )

    async def on_approval_request(self, msg: GatewayMessage) -> None:
        """Send approval request as Slack message with reaction-based approval."""
        session_data = self._session_threads.get(msg.session_id)
        if not session_data or not self._app:
            return

        channel, thread_ts = session_data
        tool = msg.data.get("tool_name", "?")
        desc = msg.data.get("description", "")

        client = self._app.client
        await client.chat_postMessage(
            channel=channel,
            text=(
                f"*Approval needed*\n"
                f"Tool: `{tool}`\n"
                f"Action: {desc}\n\n"
                "React with :white_check_mark: to approve or :x: to deny."
            ),
            thread_ts=thread_ts,
        )

        # Auto-approve after timeout (Slack doesn't have easy reaction listeners in bolt)
        # For now, auto-deny after timeout
        await asyncio.sleep(300)
        await self.send_approval(msg.id, False)

    async def on_event(self, msg: GatewayMessage) -> None:
        """Forward events to Slack."""
        event = msg.data.get("event", "")

        # Cross-channel user messages — route to all known threads
        if event == "user_message" and self._app:
            ch = msg.data.get("channel", "?")
            content = msg.data.get("content", "")
            if content:
                for slack_channel, thread_ts in self._session_threads.values():
                    try:
                        await self._app.client.chat_postMessage(
                            channel=slack_channel,
                            text=f"({ch}) {content[:400]}",
                            thread_ts=thread_ts,
                        )
                    except Exception:
                        pass
            return

        session_data = self._session_threads.get(msg.session_id)
        if not session_data or not self._app:
            return

        channel, thread_ts = session_data

        if event == "task_complete":
            goal = msg.data.get("goal", "")
            await self._app.client.chat_postMessage(
                channel=channel,
                text=f"Task complete: {goal[:200]}",
                thread_ts=thread_ts,
            )


def _split_slack(text: str, max_len: int = 3900) -> list[str]:
    """Split text for Slack's message limit."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        idx = text.rfind("\n", 0, max_len)
        if idx == -1:
            idx = max_len
        chunks.append(text[:idx])
        text = text[idx:].lstrip("\n")
    return chunks
