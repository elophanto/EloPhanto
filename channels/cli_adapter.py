"""CLI channel adapter — Rich terminal UI over the gateway.

Connects to the gateway as a WebSocket client. All the existing
Rich UI (banner, panels, stats bar, progress) is preserved — the
only change is that messages go through the gateway instead of
calling agent.run() directly.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time as _time

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.status import Status

from channels.base import ChannelAdapter
from core.protocol import GatewayMessage

logger = logging.getLogger(__name__)
console = Console()

# Palette (matches chat_cmd.py)
_C_PRIMARY = "bright_cyan"
_C_ACCENT = "bright_magenta"
_C_SUCCESS = "bright_green"
_C_WARN = "bright_yellow"
_C_DIM = "dim"
_C_USER = "bold bright_blue"
_C_BORDER = "bright_cyan"

_LOGO_SMALL = f"[{_C_PRIMARY}]◆[/] [{_C_ACCENT}]EloPhanto[/]"


class CLIAdapter(ChannelAdapter):
    """CLI interface as a gateway channel adapter."""

    name = "cli"

    def __init__(self, gateway_url: str = "ws://127.0.0.1:18789") -> None:
        super().__init__(gateway_url)
        self._session_id = ""
        self._user_id = "cli-user"
        self._listener_task: asyncio.Task | None = None
        self._status: Status | None = None
        self._chat_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Connect to gateway and enter REPL loop."""
        await self.connect_gateway()
        self._listener_task = asyncio.create_task(self.gateway_listener())

        try:
            await self._repl_loop()
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Disconnect from gateway."""
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        await self.disconnect_gateway()

    async def on_response(self, msg: GatewayMessage) -> None:
        """Handle unsolicited responses (shouldn't happen in normal flow)."""
        content = msg.data.get("content", "")
        if content:
            console.print(
                Panel(
                    Markdown(content),
                    title=_LOGO_SMALL,
                    border_style=_C_BORDER,
                    padding=(1, 2),
                )
            )

    async def on_approval_request(self, msg: GatewayMessage) -> None:
        """Show approval prompt in terminal."""
        tool_name = msg.data.get("tool_name", "?")
        description = msg.data.get("description", "")
        msg.data.get("params", {})

        console.print()
        console.print(
            Panel(
                f"[{_C_WARN}]Tool:[/] [bold]{tool_name}[/]\n[{_C_WARN}]Action:[/] {description}",
                title="[bold red]Approval Required[/]",
                border_style="red",
                padding=(0, 2),
            )
        )

        loop = asyncio.get_event_loop()
        approved = await loop.run_in_executor(
            None, lambda: Confirm.ask(f"  [{_C_SUCCESS}]Approve?[/]", default=True)
        )
        await self.send_approval(msg.id, approved)

    async def on_event(self, msg: GatewayMessage) -> None:
        """Show events as dim notifications."""
        event = msg.data.get("event", "")
        if event == "notification":
            ntype = msg.data.get("notification_type", "")
            if ntype == "scheduled_result":
                task_name = msg.data.get("task_name", "")
                status = msg.data.get("status", "")
                result = msg.data.get("result", "")
                icon = "\u2705" if status == "completed" else "\u26a0\ufe0f"
                console.print(f"\n  [{_C_DIM}]{icon} Scheduled: {task_name}[/]")
                if result:
                    console.print(f"  [{_C_DIM}]{result[:300]}[/]\n")
            elif ntype == "new_email":
                sender = msg.data.get("from", "unknown")
                subject = msg.data.get("subject", "(no subject)")
                snippet = msg.data.get("snippet", "")
                console.print(f"\n  \U0001f4e7 New email from {sender}")
                console.print(f"  [{_C_DIM}]{subject}[/]")
                if snippet:
                    console.print(f"  [{_C_DIM}]{snippet[:200]}[/]\n")
        elif event == "step_progress":
            tool_name = msg.data.get("tool_name", "")
            step = msg.data.get("step", "")
            if self._status and tool_name:
                label = tool_name.replace("_", " ").title()
                self._status.update(f"  [{_C_DIM}]Step {step} · {label}...[/]")
        elif event == "task_complete":
            goal = msg.data.get("goal", "")
            console.print(f"  [{_C_DIM}]Task completed: {goal[:60]}[/]")
        elif event == "user_message":
            ch = msg.data.get("channel", "?")
            content = msg.data.get("content", "")
            if content:
                console.print(
                    f"\n  [{_C_DIM}]({ch})[/] [{_C_USER}]{content[:300]}[/]\n"
                )
        elif event in (
            "goal_started",
            "goal_checkpoint_complete",
            "goal_completed",
            "goal_failed",
            "goal_paused",
            "goal_resumed",
        ):
            self._display_goal_event(event, msg.data)

    async def _repl_loop(self) -> None:
        """Main REPL — read input, send to gateway, display response."""
        loop = asyncio.get_event_loop()

        console.print(f"\n  [{_C_DIM}]Connected to gateway at {self._gateway_url}[/]")
        console.print(
            f"  [{_C_DIM}]Type a message, /clear to reset, Ctrl+C to cancel, or exit to quit.[/]\n"
        )

        while self._running:
            try:
                user_input = await loop.run_in_executor(
                    None, lambda: Prompt.ask(f"  [{_C_USER}]❯[/]")
                )
            except (EOFError, KeyboardInterrupt):
                break

            stripped = user_input.strip().lower()
            if stripped in ("exit", "quit", "q"):
                break
            if not user_input.strip():
                continue

            # Slash commands: /clear, /status, etc.
            # Skip paths like /Users/... or /tmp/... (contain "/" after first char)
            if (
                stripped.startswith("/")
                and "/" not in stripped[1:]
                and " " not in stripped
            ):
                cmd = stripped[1:]

                # Handle local-only commands
                if cmd == "clear":
                    await self.send_command(
                        "clear",
                        user_id=self._user_id,
                        session_id=self._session_id,
                    )
                    self._session_id = ""
                    console.print(f"  [{_C_SUCCESS}]Session and memory cleared.[/]\n")
                    continue

                if cmd == "stats":
                    cmd = "status"  # alias to gateway's status command

                if cmd == "stop":
                    await self.send_command(
                        "cancel", user_id=self._user_id, session_id=self._session_id
                    )
                    console.print(f"  [{_C_WARN}]Cancel requested.[/]\n")
                    continue

                if cmd == "help":
                    console.print(
                        f"\n  [{_C_ACCENT}]Commands[/]\n"
                        f"  /clear      — Reset session and wipe task memory\n"
                        f"  /stop       — Cancel running request (or Ctrl+C)\n"
                        f"  /status     — Show gateway status\n"
                        f"  /health     — Provider health report\n"
                        f"  /config     — Read/update config\n"
                        f"  /provider   — Enable/disable providers\n"
                        f"  /restart    — Re-initialize agent\n"
                        f"  /recovery   — Enter/exit recovery mode\n"
                        f"  /help       — This message\n"
                        f"  exit        — Quit\n"
                    )
                    continue

                await self.send_command(
                    cmd, user_id=self._user_id, session_id=self._session_id
                )
                continue

            # Send chat message and wait for response
            console.print()
            self._status = Status(
                f"  [{_C_DIM}]Thinking...[/]", console=console, spinner="dots"
            )
            self._status.start()

            # Wrap in asyncio.Task so SIGINT can cancel it properly.
            # KeyboardInterrupt does NOT propagate through asyncio awaits,
            # so we use loop.add_signal_handler to cancel the task instead.
            self._chat_task = asyncio.create_task(
                self.send_chat(
                    content=user_input,
                    user_id=self._user_id,
                    session_id=self._session_id,
                )
            )

            _sigint_fired = False
            _last_sigint = 0.0

            def _on_sigint() -> None:
                nonlocal _sigint_fired, _last_sigint
                now = _time.monotonic()
                if now - _last_sigint < 1.0:
                    # Double Ctrl+C within 1 second — force exit
                    import os

                    os._exit(1)
                _last_sigint = now
                _sigint_fired = True
                task = self._chat_task
                if task and not task.done():
                    task.cancel()

            loop.add_signal_handler(signal.SIGINT, _on_sigint)

            try:
                response = await self._chat_task

                if self._status:
                    self._status.stop()
                    self._status = None

                # Track session for future messages
                if response.session_id:
                    self._session_id = response.session_id

                content = response.data.get("content", "No response")
                console.print(
                    Panel(
                        Markdown(content),
                        title=_LOGO_SMALL,
                        border_style=_C_BORDER,
                        padding=(1, 2),
                    )
                )
                console.print()

            except asyncio.CancelledError:
                if self._status:
                    self._status.stop()
                    self._status = None
                if _sigint_fired:
                    # User pressed Ctrl+C — cancel request and continue REPL
                    console.print(f"\n  [{_C_WARN}]Cancelling...[/]")
                    try:
                        await self.send_command(
                            "cancel",
                            user_id=self._user_id,
                            session_id=self._session_id,
                        )
                    except Exception:
                        pass
                    console.print()
                    continue
                else:
                    # Outer task cancelled (app shutdown) — propagate
                    raise

            except TimeoutError:
                if self._status:
                    self._status.stop()
                    self._status = None
                console.print(f"\n  [{_C_WARN}]Request timed out.[/]")
            except Exception as e:
                if self._status:
                    self._status.stop()
                    self._status = None
                console.print(f"\n  [bold red]Error:[/] {e}")
            finally:
                try:
                    loop.remove_signal_handler(signal.SIGINT)
                except Exception:
                    pass

    def _display_goal_event(self, event: str, data: dict) -> None:
        """Display a goal lifecycle event in the terminal."""
        goal_text = data.get("goal", "")
        goal_id = data.get("goal_id", "")[:8]

        if event == "goal_started":
            console.print(
                f"\n  [{_C_ACCENT}]\u25b6 Goal started[/] [{_C_DIM}]({goal_id})[/]"
                f"  {goal_text[:80]}"
            )
        elif event == "goal_checkpoint_complete":
            title = data.get("checkpoint_title", "")
            order = data.get("checkpoint_order", "")
            console.print(f"  [{_C_SUCCESS}]\u2713 Checkpoint {order}[/] {title}")
        elif event == "goal_completed":
            console.print(
                f"\n  [{_C_SUCCESS}]\u2714 Goal completed[/] [{_C_DIM}]({goal_id})[/]"
                f"  {goal_text[:80]}\n"
            )
        elif event == "goal_failed":
            error = data.get("error", "")
            console.print(
                f"\n  [bold red]\u2716 Goal failed[/] [{_C_DIM}]({goal_id})[/]"
                f"  {error[:100]}\n"
            )
        elif event == "goal_paused":
            reason = data.get("reason", "")
            console.print(
                f"\n  [{_C_WARN}]\u23f8 Goal paused[/] [{_C_DIM}]({goal_id})[/]"
                f"  {reason[:100]}\n"
            )
        elif event == "goal_resumed":
            console.print(
                f"\n  [{_C_ACCENT}]\u25b6 Goal resumed[/] [{_C_DIM}]({goal_id})[/]\n"
            )
