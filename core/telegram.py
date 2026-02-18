"""Telegram bot adapter — bridges Telegram messages to the agent core.

Runs as an async task alongside the agent process. Handles user
authentication, command routing, message formatting, and notifications.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, Dispatcher, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command

from core.agent import Agent, AgentResponse
from core.config import TelegramConfig
from core.telegram_fmt import split_message, to_plain_text, to_telegram_markdown

logger = logging.getLogger(__name__)

router = Router()


class TelegramAdapter:
    """Bridges Telegram Bot API to the EloPhanto agent."""

    def __init__(
        self,
        agent: Agent,
        config: TelegramConfig,
        bot_token: str,
    ) -> None:
        self._agent = agent
        self._config = config
        self._bot = Bot(token=bot_token)
        self._dp = Dispatcher()
        self._dp.include_router(router)
        self._allowed_users = set(config.allowed_users)
        self._running = False

        self._register_handlers()

    @property
    def bot(self) -> Bot:
        return self._bot

    def _is_authorized(self, user_id: int) -> bool:
        if not self._allowed_users:
            return True
        return user_id in self._allowed_users

    def _register_handlers(self) -> None:
        """Register all message and command handlers."""

        @self._dp.message(Command("start"))
        async def cmd_start(message: types.Message) -> None:
            if not self._is_authorized(message.from_user.id):
                return
            await message.answer(
                f"*{self._agent._config.agent_name}* is ready\\.\n\n"
                "Send me any task or question\\. "
                "Type /help for available commands\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )

        @self._dp.message(Command("help"))
        async def cmd_help(message: types.Message) -> None:
            if not self._is_authorized(message.from_user.id):
                return
            help_text = (
                "*Available Commands*\n\n"
                "/status — Current agent status\n"
                "/tasks — Recent and scheduled tasks\n"
                "/approve — Approve pending action\n"
                "/deny — Deny pending action\n"
                "/plugins — List capabilities\n"
                "/mode — Show/change permission mode\n"
                "/budget — Today's LLM spending\n"
                "/help — This message"
            )
            await message.answer(
                escape_for_md2(help_text),
                parse_mode=ParseMode.MARKDOWN_V2,
            )

        @self._dp.message(Command("status"))
        async def cmd_status(message: types.Message) -> None:
            if not self._is_authorized(message.from_user.id):
                return
            tool_count = len(self._agent._registry.list_tools())
            health = getattr(self._agent, "_provider_health", {})
            providers = [k for k, v in health.items() if v]
            mode = self._agent._config.permission_mode

            features: list[str] = []
            if self._agent._browser_manager:
                features.append("browser")
            if self._agent._scheduler:
                features.append("scheduler")
            features.append("telegram")

            text = (
                f"📊 *{self._agent._config.agent_name} Status*\n\n"
                f"Providers: {', '.join(providers) or 'none'}\n"
                f"Tools: {tool_count}\n"
                f"Features: {', '.join(features)}\n"
                f"Permission mode: {mode}"
            )
            await message.answer(
                escape_for_md2(text),
                parse_mode=ParseMode.MARKDOWN_V2,
            )

        @self._dp.message(Command("tasks"))
        async def cmd_tasks(message: types.Message) -> None:
            if not self._is_authorized(message.from_user.id):
                return
            try:
                from core.memory import MemoryManager

                mm = MemoryManager(self._agent._db)
                recent = await mm.get_recent_tasks(limit=5)
                if not recent:
                    await message.answer("No recent tasks.")
                    return
                lines = ["📋 *Recent Tasks*\n"]
                for task in recent:
                    status = "✅" if task["outcome"] == "completed" else "⚠️"
                    lines.append(f"{status} {task['goal'][:60]}")
                await message.answer(
                    escape_for_md2("\n".join(lines)),
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            except Exception as e:
                await message.answer(f"Failed to fetch tasks: {e}")

        @self._dp.message(Command("approve"))
        async def cmd_approve(message: types.Message) -> None:
            if not self._is_authorized(message.from_user.id):
                return
            await self._handle_approval(message, approved=True)

        @self._dp.message(Command("deny"))
        async def cmd_deny(message: types.Message) -> None:
            if not self._is_authorized(message.from_user.id):
                return
            await self._handle_approval(message, approved=False)

        @self._dp.message(Command("plugins"))
        async def cmd_plugins(message: types.Message) -> None:
            if not self._is_authorized(message.from_user.id):
                return
            summaries = self._agent._registry.list_tool_summaries()
            lines = [f"🔧 *Tools ({len(summaries)})*\n"]
            for s in summaries[:30]:
                lines.append(f"• `{s['name']}` — {s['description'][:50]}")
            if len(summaries) > 30:
                lines.append(f"\n...and {len(summaries) - 30} more")
            await message.answer(
                escape_for_md2("\n".join(lines)),
                parse_mode=ParseMode.MARKDOWN_V2,
            )

        @self._dp.message(Command("mode"))
        async def cmd_mode(message: types.Message) -> None:
            if not self._is_authorized(message.from_user.id):
                return
            args = message.text.split(maxsplit=1)
            if len(args) > 1 and args[1] in ("ask_always", "smart_auto", "full_auto"):
                self._agent._config.permission_mode = args[1]
                await message.answer(f"Permission mode changed to: {args[1]}")
            else:
                mode = self._agent._config.permission_mode
                await message.answer(
                    f"Current mode: {mode}\n"
                    "Change with: /mode ask_always|smart_auto|full_auto"
                )

        @self._dp.message(Command("budget"))
        async def cmd_budget(message: types.Message) -> None:
            if not self._is_authorized(message.from_user.id):
                return
            tracker = self._agent._router.cost_tracker
            daily = tracker.daily_total
            task = tracker.task_total
            limit = self._agent._config.llm.budget.daily_limit_usd
            await message.answer(
                f"💰 Today's spending: ${daily:.4f} / ${limit:.2f} limit\n"
                f"Current task: ${task:.4f}"
            )

        @self._dp.message()
        async def handle_message(message: types.Message) -> None:
            if not self._is_authorized(message.from_user.id):
                return
            if not message.text:
                return

            from aiogram.enums import ChatAction

            await self._bot.send_chat_action(message.chat.id, ChatAction.TYPING)

            try:
                response: AgentResponse = await self._agent.run(message.text)
                formatted = to_telegram_markdown(response.content)
                chunks = split_message(formatted, self._config.max_message_length)

                for chunk in chunks:
                    try:
                        await message.answer(chunk, parse_mode=ParseMode.MARKDOWN_V2)
                    except Exception:
                        # MarkdownV2 failed — send as plain text
                        plain = to_plain_text(response.content)
                        for plain_chunk in split_message(
                            plain, self._config.max_message_length
                        ):
                            await message.answer(plain_chunk)
                        break

            except Exception as e:
                logger.error(f"Telegram message handling failed: {e}")
                await message.answer(f"Error: {e}")

    async def _handle_approval(self, message: types.Message, approved: bool) -> None:
        """Resolve the most recent pending approval."""
        try:
            queue = getattr(self._agent, "_approval_queue", None)
            if queue is None:
                await message.answer("No approval queue available.")
                return

            pending = await queue.pending(limit=1)
            if not pending:
                await message.answer("No pending approvals.")
                return

            item = pending[0]
            await queue.resolve(item["id"], approved)
            status = "✅ Approved" if approved else "❌ Denied"
            await message.answer(f"{status}: {item['description']}")
        except Exception as e:
            await message.answer(f"Failed to process approval: {e}")

    # --- Notification methods (called from agent hooks) ---

    async def notify_task_complete(
        self, goal: str, summary: str, steps: int, cost: float
    ) -> None:
        """Send task completion notification to all allowed users."""
        if not self._config.notifications.task_complete:
            return
        text = (
            f"✅ *Task complete*\n\n"
            f"{goal[:200]}\n\n"
            f"{summary[:500]}\n\n"
            f"Steps: {steps} | Cost: ${cost:.4f}"
        )
        await self._broadcast(escape_for_md2(text))

    async def notify_approval_needed(self, tool_name: str, description: str) -> None:
        """Send approval request notification."""
        if not self._config.notifications.approval_needed:
            return
        text = (
            f"🔔 *Approval needed*\n\n"
            f"Tool: `{tool_name}`\n"
            f"Action: {description}\n\n"
            f"/approve — Allow\n"
            f"/deny — Block"
        )
        await self._broadcast(escape_for_md2(text))

    async def notify_error(self, task: str, error: str) -> None:
        """Send error notification."""
        if not self._config.notifications.errors:
            return
        text = f"⚠️ *Error*\n\n{task[:100]}\n\n{error[:300]}"
        await self._broadcast(escape_for_md2(text))

    async def notify_scheduled_result(self, task_name: str, result: str) -> None:
        """Send scheduled task result."""
        if not self._config.notifications.scheduled_results:
            return
        text = f"📬 *Scheduled: {task_name}*\n\n{result[:500]}"
        await self._broadcast(escape_for_md2(text))

    async def _broadcast(self, text: str) -> None:
        """Send a message to all allowed users."""
        for user_id in self._allowed_users:
            try:
                await self._bot.send_message(
                    user_id, text, parse_mode=ParseMode.MARKDOWN_V2
                )
            except Exception as e:
                logger.warning(f"Failed to notify user {user_id}: {e}")

    async def start(self) -> None:
        """Start the Telegram polling loop."""
        self._running = True
        logger.info("Telegram bot starting (polling mode)")
        try:
            await self._dp.start_polling(self._bot)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

    async def stop(self) -> None:
        """Gracefully stop the bot."""
        self._running = False
        await self._dp.stop_polling()
        await self._bot.session.close()


def escape_for_md2(text: str) -> str:
    """Light escape for pre-formatted text that already has markdown markers."""
    import re

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
