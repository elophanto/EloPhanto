"""Telegram channel adapter — bridges Telegram Bot API to the gateway.

Replaces the direct-coupled core/telegram.py with a gateway-based
adapter. Messages from Telegram users are forwarded to the gateway,
and responses are sent back as Telegram messages.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command
from aiogram.utils.backoff import BackoffConfig

from channels.base import ChannelAdapter
from core.config import TelegramConfig
from core.protocol import GatewayMessage
from core.telegram_fmt import split_message, to_plain_text, to_telegram_markdown

logger = logging.getLogger(__name__)

# Cap backoff at 60s and limit consecutive failures before pausing longer.
_BACKOFF = BackoffConfig(min_delay=1.0, max_delay=60.0, factor=1.5, jitter=0.1)
_MAX_CONSECUTIVE_ERRORS = 10
_ERROR_PAUSE_SECONDS = 300  # 5-min pause after too many failures


def _escape_md2(text: str) -> str:
    """Light escape for MarkdownV2."""
    safe_markers = {"*", "_", "`", "[", "]", "(", ")"}
    result: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            result.append(ch)
            result.append(text[i + 1])
            i += 2
            continue
        if ch in safe_markers:
            result.append(ch)
        elif ch in ".!->#+=|{}~":
            result.append(f"\\{ch}")
        else:
            result.append(ch)
        i += 1
    return "".join(result)


class TelegramChannelAdapter(ChannelAdapter):
    """Telegram interface as a gateway channel adapter."""

    name = "telegram"

    def __init__(
        self,
        bot_token: str,
        config: TelegramConfig,
        gateway_url: str = "ws://127.0.0.1:18789",
    ) -> None:
        super().__init__(gateway_url)
        self._tg_config = config
        self._bot = Bot(token=bot_token)
        self._dp = Dispatcher()
        self._allowed_users = set(config.allowed_users)

        # Map session_id → telegram chat_id (for sending responses back)
        self._session_chats: dict[str, int] = {}
        # Map session_id → user_id string
        self._session_users: dict[str, str] = {}

        self._register_handlers()

    def _is_authorized(self, user_id: int) -> bool:
        if not self._allowed_users:
            return True
        return user_id in self._allowed_users

    def _register_handlers(self) -> None:
        """Register Telegram message and command handlers."""

        @self._dp.message(Command("start"))
        async def cmd_start(message: types.Message) -> None:
            if not self._is_authorized(message.from_user.id):
                return
            await message.answer(
                _escape_md2("*EloPhanto* is ready.\n\nSend me any task or question."),
                parse_mode=ParseMode.MARKDOWN_V2,
            )

        @self._dp.message(Command("help"))
        async def cmd_help(message: types.Message) -> None:
            if not self._is_authorized(message.from_user.id):
                return
            await message.answer(
                _escape_md2(
                    "*Commands*\n\n"
                    "/status — Agent status\n"
                    "/approve — Approve pending action\n"
                    "/deny — Deny pending action\n"
                    "/help — This message"
                ),
                parse_mode=ParseMode.MARKDOWN_V2,
            )

        @self._dp.message(Command("status"))
        async def cmd_status(message: types.Message) -> None:
            if not self._is_authorized(message.from_user.id):
                return
            user_id = str(message.from_user.id)
            await self.send_command("status", user_id=user_id)

        @self._dp.message(Command("approve"))
        async def cmd_approve(message: types.Message) -> None:
            if not self._is_authorized(message.from_user.id):
                return
            # Find pending approval for this user's session
            str(message.from_user.id)
            for req_id, _future in list(self._pending_approvals.items()):
                await self.send_approval(req_id, True)
                await message.answer("Approved.")
                return
            await message.answer("No pending approvals.")

        @self._dp.message(Command("deny"))
        async def cmd_deny(message: types.Message) -> None:
            if not self._is_authorized(message.from_user.id):
                return
            str(message.from_user.id)
            for req_id, _future in list(self._pending_approvals.items()):
                await self.send_approval(req_id, False)
                await message.answer("Denied.")
                return
            await message.answer("No pending approvals.")

        @self._dp.message()
        async def handle_message(message: types.Message) -> None:
            if not self._is_authorized(message.from_user.id):
                return

            user_id = str(message.from_user.id)
            chat_id = message.chat.id

            # Extract text — prefer .text, fall back to .caption for media
            text = message.text or message.caption or ""

            # Handle file attachments (photos, documents)
            attachments: list[dict[str, Any]] = []
            if message.photo:
                # Telegram sends multiple sizes; take the largest
                photo = message.photo[-1]
                att = await self._download_telegram_file(
                    photo.file_id, f"photo_{photo.file_unique_id}.jpg", user_id,
                )
                if att:
                    attachments.append(att)
            if message.document:
                doc = message.document
                att = await self._download_telegram_file(
                    doc.file_id, doc.file_name or f"file_{doc.file_unique_id}", user_id,
                )
                if att:
                    if doc.mime_type:
                        att["mime_type"] = doc.mime_type
                    if doc.file_size:
                        att["size_bytes"] = doc.file_size
                    attachments.append(att)

            # Nothing to send?
            if not text and not attachments:
                return

            if attachments and not text:
                text = "Analyze this file"

            await self._bot.send_chat_action(chat_id, ChatAction.TYPING)

            try:
                response = await self.send_chat(
                    content=text,
                    user_id=user_id,
                    attachments=attachments or None,
                )

                # Track chat mapping
                if response.session_id:
                    self._session_chats[response.session_id] = chat_id
                    self._session_users[response.session_id] = user_id

                content = response.data.get("content", "No response")
                await self._send_formatted(chat_id, content)

            except TimeoutError:
                await message.answer("Request timed out. Please try again.")
            except Exception as e:
                logger.error("Telegram message handling failed: %s", e)
                await message.answer(f"Error: {e}")

    # Track pending approval request IDs
    _pending_approvals: dict[str, str] = {}

    async def start(self) -> None:
        """Connect to gateway and start Telegram polling."""
        await self.connect_gateway()

        # Start gateway listener and Telegram polling concurrently.
        # Wrap polling in a resilient loop that pauses after repeated failures
        # instead of spamming logs indefinitely.
        await asyncio.gather(
            self.gateway_listener(),
            self._resilient_polling(),
        )

    async def _resilient_polling(self) -> None:
        """Run polling with a circuit-breaker for sustained outages."""
        consecutive_errors = 0
        while self._running:
            try:
                await self._dp.start_polling(
                    self._bot, backoff_config=_BACKOFF,
                )
                break  # clean exit
            except asyncio.CancelledError:
                raise
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                    logger.warning(
                        "Telegram polling failed %d times, pausing %ds: %s",
                        consecutive_errors, _ERROR_PAUSE_SECONDS, e,
                    )
                    await asyncio.sleep(_ERROR_PAUSE_SECONDS)
                    consecutive_errors = 0
                else:
                    logger.debug("Telegram polling error (%d): %s", consecutive_errors, e)
                    await asyncio.sleep(2)

    async def stop(self) -> None:
        """Stop polling and disconnect."""
        self._running = False
        await self._dp.stop_polling()
        await self._bot.session.close()
        await self.disconnect_gateway()

    async def on_response(self, msg: GatewayMessage) -> None:
        """Handle unsolicited responses — send to the right Telegram chat."""
        session_id = msg.session_id
        chat_id = self._session_chats.get(session_id)
        if chat_id:
            content = msg.data.get("content", "")
            if content:
                await self._send_formatted(chat_id, content)

    async def on_approval_request(self, msg: GatewayMessage) -> None:
        """Show approval request as inline keyboard in Telegram."""
        session_id = msg.session_id
        chat_id = self._session_chats.get(session_id)
        if not chat_id:
            # Send to all allowed users
            for uid in self._allowed_users:
                chat_id = uid
                break

        if not chat_id:
            return

        tool_name = msg.data.get("tool_name", "?")
        description = msg.data.get("description", "")

        # Track this approval
        self._pending_approvals[msg.id] = session_id

        text = _escape_md2(
            f"*Approval needed*\n\n"
            f"Tool: `{tool_name}`\n"
            f"Action: {description}\n\n"
            f"/approve — Allow\n"
            f"/deny — Block"
        )
        await self._bot.send_message(
            chat_id, text, parse_mode=ParseMode.MARKDOWN_V2
        )

    async def on_event(self, msg: GatewayMessage) -> None:
        """Forward events as Telegram notifications."""
        event = msg.data.get("event", "")
        session_id = msg.session_id
        chat_id = self._session_chats.get(session_id)

        if not chat_id:
            return

        if event == "task_complete":
            goal = msg.data.get("goal", "")
            await self._bot.send_message(
                chat_id, f"Task complete: {goal[:200]}"
            )
        elif event == "task_error":
            error = msg.data.get("error", "Unknown error")
            await self._bot.send_message(chat_id, f"Error: {error[:300]}")

    async def _download_telegram_file(
        self, file_id: str, filename: str, user_id: str,
    ) -> dict[str, Any] | None:
        """Download a Telegram file to local storage and return attachment dict."""
        try:
            tg_file = await self._bot.get_file(file_id)
            if not tg_file.file_path:
                return None

            # Use StorageManager if available, otherwise fall back to temp dir
            if hasattr(self, "_storage") and self._storage:
                local_path = self._storage.get_upload_path(
                    session_id=f"telegram_{user_id}", filename=filename,
                )
            else:
                import tempfile
                from pathlib import Path

                tmp_dir = Path(tempfile.gettempdir()) / "elophanto" / f"telegram_{user_id}"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                local_path = tmp_dir / filename

            await self._bot.download_file(tg_file.file_path, destination=local_path)
            logger.info("Downloaded Telegram file: %s → %s", filename, local_path)

            return {
                "filename": filename,
                "local_path": str(local_path),
                "mime_type": "application/octet-stream",
                "size_bytes": tg_file.file_size or 0,
            }
        except Exception as e:
            logger.warning("Failed to download Telegram file %s: %s", filename, e)
            return None

    async def _send_formatted(self, chat_id: int, content: str) -> None:
        """Send content as formatted Telegram message(s)."""
        formatted = to_telegram_markdown(content)
        chunks = split_message(formatted, self._tg_config.max_message_length)

        for chunk in chunks:
            try:
                await self._bot.send_message(
                    chat_id, chunk, parse_mode=ParseMode.MARKDOWN_V2
                )
            except Exception:
                plain = to_plain_text(content)
                for pc in split_message(plain, self._tg_config.max_message_length):
                    await self._bot.send_message(chat_id, pc)
                break
