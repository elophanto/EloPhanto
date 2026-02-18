"""Discord channel adapter — bridges Discord Bot API to the gateway.

Uses discord.py library. Maps Discord users/channels to gateway sessions.
Supports slash commands, DM conversations, and thread-per-task.

Requires: pip install discord.py
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from channels.base import ChannelAdapter
from core.config import DiscordConfig
from core.protocol import GatewayMessage

logger = logging.getLogger(__name__)


class DiscordAdapter(ChannelAdapter):
    """Discord interface as a gateway channel adapter."""

    name = "discord"

    def __init__(
        self,
        bot_token: str,
        config: DiscordConfig,
        gateway_url: str = "ws://127.0.0.1:18789",
    ) -> None:
        super().__init__(gateway_url)
        self._discord_config = config
        self._bot_token = bot_token
        self._client: Any = None

        # Map session_id → discord channel_id for responses
        self._session_channels: dict[str, int] = {}

    async def start(self) -> None:
        """Connect to gateway and start Discord bot."""
        try:
            import discord
            from discord import app_commands
        except ImportError:
            raise RuntimeError(
                "discord.py not installed. Run: pip install discord.py"
            )

        await self.connect_gateway()

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        tree = app_commands.CommandTree(self._client)

        @self._client.event
        async def on_ready() -> None:
            logger.info("Discord bot ready as %s", self._client.user)
            await tree.sync()

        @self._client.event
        async def on_message(message: discord.Message) -> None:
            if message.author == self._client.user:
                return

            # Only respond to DMs or mentions
            is_dm = isinstance(message.channel, discord.DMChannel)
            is_mentioned = self._client.user in message.mentions if not is_dm else False

            if not is_dm and not is_mentioned:
                return

            # Check guild allowlist
            if (
                not is_dm
                and self._discord_config.allowed_guilds
                and str(message.guild.id) not in self._discord_config.allowed_guilds
            ):
                return

            content = message.content
            if is_mentioned:
                # Strip the mention prefix
                content = content.replace(f"<@{self._client.user.id}>", "").strip()

            if not content:
                return

            user_id = str(message.author.id)
            channel_id = message.channel.id

            async with message.channel.typing():
                try:
                    response = await self.send_chat(
                        content=content, user_id=user_id
                    )

                    if response.session_id:
                        self._session_channels[response.session_id] = channel_id

                    reply = response.data.get("content", "No response")
                    # Discord has 2000 char limit
                    for chunk in _split_discord(reply, 1900):
                        await message.channel.send(chunk)

                except asyncio.TimeoutError:
                    await message.channel.send("Request timed out.")
                except Exception as e:
                    logger.error("Discord message handling failed: %s", e)
                    await message.channel.send(f"Error: {e}")

        @tree.command(name="ask", description="Ask EloPhanto a question")
        async def slash_ask(
            interaction: discord.Interaction, question: str
        ) -> None:
            await interaction.response.defer(thinking=True)
            user_id = str(interaction.user.id)

            try:
                response = await self.send_chat(content=question, user_id=user_id)
                reply = response.data.get("content", "No response")
                for chunk in _split_discord(reply, 1900):
                    await interaction.followup.send(chunk)
            except Exception as e:
                await interaction.followup.send(f"Error: {e}")

        @tree.command(name="status", description="EloPhanto status")
        async def slash_status(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            await self.send_command("status", user_id=str(interaction.user.id))
            await interaction.followup.send("Status requested.")

        # Run both gateway listener and Discord client
        await asyncio.gather(
            self.gateway_listener(),
            self._client.start(self._bot_token),
        )

    async def stop(self) -> None:
        """Stop Discord bot and disconnect from gateway."""
        self._running = False
        if self._client:
            await self._client.close()
        await self.disconnect_gateway()

    async def on_response(self, msg: GatewayMessage) -> None:
        """Send unsolicited responses to the right Discord channel."""
        channel_id = self._session_channels.get(msg.session_id)
        if channel_id and self._client:
            channel = self._client.get_channel(channel_id)
            if channel:
                content = msg.data.get("content", "")
                for chunk in _split_discord(content, 1900):
                    await channel.send(chunk)

    async def on_approval_request(self, msg: GatewayMessage) -> None:
        """Send approval request to Discord channel."""
        channel_id = self._session_channels.get(msg.session_id)
        if channel_id and self._client:
            channel = self._client.get_channel(channel_id)
            if channel:
                tool = msg.data.get("tool_name", "?")
                desc = msg.data.get("description", "")
                text = (
                    f"**Approval needed**\n"
                    f"Tool: `{tool}`\n"
                    f"Action: {desc}\n\n"
                    f"React with \u2705 to approve or \u274c to deny."
                )
                sent = await channel.send(text)
                await sent.add_reaction("\u2705")
                await sent.add_reaction("\u274c")

                # Wait for reaction
                def check(reaction, user):
                    return (
                        user != self._client.user
                        and str(reaction.emoji) in ("\u2705", "\u274c")
                        and reaction.message.id == sent.id
                    )

                try:
                    reaction, user = await self._client.wait_for(
                        "reaction_add", timeout=300, check=check
                    )
                    approved = str(reaction.emoji) == "\u2705"
                    await self.send_approval(msg.id, approved)
                    status = "Approved" if approved else "Denied"
                    await channel.send(f"{status} by {user.display_name}.")
                except asyncio.TimeoutError:
                    await self.send_approval(msg.id, False)
                    await channel.send("Approval timed out (denied).")

    async def on_event(self, msg: GatewayMessage) -> None:
        """Forward events to Discord."""
        channel_id = self._session_channels.get(msg.session_id)
        if channel_id and self._client:
            channel = self._client.get_channel(channel_id)
            if channel:
                event = msg.data.get("event", "")
                if event == "task_complete":
                    goal = msg.data.get("goal", "")
                    await channel.send(f"Task complete: {goal[:200]}")


def _split_discord(text: str, max_len: int = 1900) -> list[str]:
    """Split text for Discord's 2000 char limit."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Find last newline within limit
        idx = text.rfind("\n", 0, max_len)
        if idx == -1:
            idx = max_len
        chunks.append(text[:idx])
        text = text[idx:].lstrip("\n")
    return chunks
