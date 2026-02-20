"""elophanto chat — Interactive conversation with the agent.

REPL loop with a visually rich terminal UI: ASCII art banner,
live stats bar (tokens, context, cost), styled panels, and
color-coded output.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import click
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.status import Status
from rich.table import Table
from rich.text import Text

from core.agent import Agent
from core.config import load_config
from core.log_setup import setup_logging
from core.vault import Vault, VaultError

console = Console()
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# Palette
# ──────────────────────────────────────────────────────────────────
_C_PRIMARY = "bright_cyan"
_C_ACCENT = "bright_magenta"
_C_SUCCESS = "bright_green"
_C_WARN = "bright_yellow"
_C_DIM = "dim"
_C_USER = "bold bright_blue"
_C_AGENT = "bold bright_green"
_C_BORDER = "bright_cyan"

# ──────────────────────────────────────────────────────────────────
# ASCII Art
# ──────────────────────────────────────────────────────────────────
_BANNER = f"""\
[{_C_PRIMARY}]
  ███████╗██╗      ██████╗ ██████╗ ██╗  ██╗ █████╗ ███╗   ██╗████████╗ ██████╗
  ██╔════╝██║     ██╔═══██╗██╔══██╗██║  ██║██╔══██╗████╗  ██║╚══██╔══╝██╔═══██╗
  █████╗  ██║     ██║   ██║██████╔╝███████║███████║██╔██╗ ██║   ██║   ██║   ██║
  ██╔══╝  ██║     ██║   ██║██╔═══╝ ██╔══██║██╔══██║██║╚██╗██║   ██║   ██║   ██║
  ███████╗███████╗╚██████╔╝██║     ██║  ██║██║  ██║██║ ╚████║   ██║   ╚██████╔╝
  ╚══════╝╚══════╝ ╚═════╝ ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝[/]
"""

_LOGO_SMALL = f"[{_C_PRIMARY}]◆[/] [{_C_ACCENT}]EloPhanto[/]"


# ──────────────────────────────────────────────────────────────────
# Session stats tracker
# ──────────────────────────────────────────────────────────────────
class SessionStats:
    """Track token usage and context across the session."""

    def __init__(self) -> None:
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.task_input_tokens = 0
        self.task_output_tokens = 0
        self.task_count = 0
        self.session_cost = 0.0
        self.context_messages = 0
        self.last_model = ""
        self.last_provider = ""
        self.start_time = time.time()

    def update_from_tracker(self, cost_tracker: Any) -> None:
        """Pull latest numbers from the router's cost tracker."""
        total_in = 0
        total_out = 0
        for call in cost_tracker.calls:
            total_in += call.get("input_tokens", 0)
            total_out += call.get("output_tokens", 0)
        self.total_input_tokens = total_in
        self.total_output_tokens = total_out
        self.session_cost = cost_tracker.daily_total
        if cost_tracker.calls:
            last = cost_tracker.calls[-1]
            self.last_model = last.get("model", "")
            self.last_provider = last.get("provider", "")

    def update_task_tokens(self, cost_tracker: Any) -> None:
        """Capture task-specific token counts."""
        task_in = 0
        task_out = 0
        for call in cost_tracker.calls:
            if call.get("timestamp", 0) >= self.start_time:
                task_in += call.get("input_tokens", 0)
                task_out += call.get("output_tokens", 0)
        self.task_input_tokens = task_in
        self.task_output_tokens = task_out

    @property
    def uptime(self) -> str:
        elapsed = int(time.time() - self.start_time)
        if elapsed < 60:
            return f"{elapsed}s"
        if elapsed < 3600:
            return f"{elapsed // 60}m {elapsed % 60}s"
        return f"{elapsed // 3600}h {(elapsed % 3600) // 60}m"

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens


def _format_tokens(n: int) -> str:
    """Format token count with K/M suffix."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


# ──────────────────────────────────────────────────────────────────
# UI builders
# ──────────────────────────────────────────────────────────────────


def _build_welcome_panel(
    cfg: Any, agent: Agent, skill_count: int, telegram_running: bool = False
) -> Panel:
    """Build the system info panel shown at startup."""
    health = getattr(agent, "_provider_health", {})
    providers = [k for k, v in health.items() if v]
    tool_count = len(agent._registry.list_tools())

    features: list[str] = []
    if agent._browser_manager:
        features.append(f"[{_C_SUCCESS}]browser[/]")
    if agent._scheduler:
        features.append(f"[{_C_SUCCESS}]scheduler[/]")
    if telegram_running:
        features.append(f"[{_C_SUCCESS}]telegram[/]")
    elif cfg.telegram.enabled:
        features.append(f"[{_C_WARN}]telegram (no token)[/]")
    features.append(f"[{_C_SUCCESS}]vault[/]")

    # Build info table
    info = Table.grid(padding=(0, 2))
    info.add_column(style=_C_DIM, justify="right", min_width=14)
    info.add_column()

    prov_parts = []
    for p in providers:
        prov_parts.append(f"[{_C_SUCCESS}]●[/] {p}")
    if not prov_parts:
        prov_parts = ["[red]● none[/]"]

    info.add_row("Providers", "  ".join(prov_parts))
    info.add_row("Tools", f"[bold]{tool_count}[/] registered")
    info.add_row("Skills", f"[bold]{skill_count}[/] loaded")
    info.add_row("Features", "  ".join(features))
    info.add_row("Mode", f"[{_C_ACCENT}]{cfg.permission_mode}[/]")

    commands = Text()
    commands.append("\n")
    commands.append("  /clear", style="bold")
    commands.append(" reset context  ", style=_C_DIM)
    commands.append("  /stats", style="bold")
    commands.append(" session info  ", style=_C_DIM)
    commands.append("  exit", style="bold")
    commands.append(" quit", style=_C_DIM)

    content = Group(info, commands)
    return Panel(
        content,
        title=f"[bold {_C_PRIMARY}]System[/]",
        subtitle=f"[{_C_DIM}]v0.1.0[/]",
        border_style=_C_BORDER,
        padding=(1, 2),
    )


def _build_stats_bar(stats: SessionStats, cfg: Any) -> Text:
    """Build the compact stats bar shown after each response."""
    bar = Text()
    bar.append("  ╰─ ", style=_C_DIM)

    # Tokens
    bar.append("tokens ", style=_C_DIM)
    bar.append(f"↑{_format_tokens(stats.task_input_tokens)}", style=_C_PRIMARY)
    bar.append(" ", style=_C_DIM)
    bar.append(f"↓{_format_tokens(stats.task_output_tokens)}", style=_C_ACCENT)

    bar.append("  │  ", style=_C_DIM)

    # Context
    ctx_msgs = stats.context_messages
    max_ctx = 20  # _MAX_CONVERSATION_HISTORY from agent.py
    ctx_pct = min(100, int((ctx_msgs / max_ctx) * 100)) if max_ctx > 0 else 0
    ctx_color = _C_SUCCESS if ctx_pct < 60 else (_C_WARN if ctx_pct < 85 else "red")
    bar.append("ctx ", style=_C_DIM)
    bar.append(f"{ctx_msgs}/{max_ctx}", style=ctx_color)
    bar.append(f" ({ctx_pct}%)", style=_C_DIM)

    bar.append("  │  ", style=_C_DIM)

    # Cost
    bar.append("cost ", style=_C_DIM)
    bar.append(f"${stats.session_cost:.4f}", style=_C_WARN)

    bar.append("  │  ", style=_C_DIM)

    # Model
    if stats.last_model:
        model_short = stats.last_model.split("/")[-1][:20]
        bar.append(f"{model_short}", style=_C_DIM)

    return bar


def _build_session_stats_panel(stats: SessionStats, cfg: Any) -> Panel:
    """Build the detailed stats panel for /stats command."""
    info = Table.grid(padding=(0, 3))
    info.add_column(style=_C_DIM, justify="right", min_width=16)
    info.add_column()

    info.add_row("Session uptime", f"[bold]{stats.uptime}[/]")
    info.add_row("Tasks completed", f"[bold]{stats.task_count}[/]")
    info.add_row("", "")
    info.add_row(
        "Total tokens in",
        f"[{_C_PRIMARY}]{_format_tokens(stats.total_input_tokens)}[/]",
    )
    info.add_row(
        "Total tokens out",
        f"[{_C_ACCENT}]{_format_tokens(stats.total_output_tokens)}[/]",
    )
    info.add_row("Total tokens", f"[bold]{_format_tokens(stats.total_tokens)}[/]")
    info.add_row("", "")
    info.add_row("Context messages", f"{stats.context_messages} / 20")
    info.add_row("Session cost", f"[{_C_WARN}]${stats.session_cost:.4f}[/]")
    info.add_row(
        "Budget remaining",
        f"[{_C_SUCCESS}]${max(0, cfg.llm.budget.daily_limit_usd - stats.session_cost):.2f}[/]",
    )
    info.add_row("", "")
    info.add_row("Last model", f"{stats.last_model or 'n/a'}")
    info.add_row("Last provider", f"{stats.last_provider or 'n/a'}")

    return Panel(
        info,
        title=f"[bold {_C_ACCENT}]Session Stats[/]",
        border_style=_C_ACCENT,
        padding=(1, 2),
    )


# ──────────────────────────────────────────────────────────────────
# Live progress display
# ──────────────────────────────────────────────────────────────────


class _LiveProgress:
    """Shows real-time step-by-step progress during agent execution."""

    def __init__(self, con: Console) -> None:
        self._console = con
        self._status = Status(
            f"  [{_C_DIM}]Planning...[/]",
            console=con,
            spinner="dots",
        )
        self._current_step = 0
        self._steps_log: list[str] = []

    def start(self) -> None:
        self._status.start()

    def stop(self) -> None:
        self._status.stop()
        if self._steps_log:
            for line in self._steps_log:
                self._console.print(line)

    def update(self, step: int, tool: str, detail: str) -> None:
        self._current_step = step
        detail_str = f" [{_C_DIM}]{detail}[/]" if detail else ""

        self._status.update(
            f"  [{_C_PRIMARY}]Step {step}[/] [{_C_DIM}]│[/] [bold]{tool}[/]{detail_str}"
        )

        log_line = (
            f"  [{_C_DIM}]  step {step}[/] [{_C_PRIMARY}]{tool}[/]"
            f"{f' [{_C_DIM}]{detail}[/]' if detail else ''}"
        )
        self._steps_log.append(log_line)


def _summarize_params(tool: str, params: dict[str, Any]) -> str:
    """Extract a short human-readable summary from tool params."""
    if tool == "shell_execute":
        cmd = params.get("command", "")
        return cmd[:60] + ("..." if len(cmd) > 60 else "")
    if tool in ("file_read", "file_write", "file_list", "file_delete"):
        return params.get("path", "")
    if tool == "file_move":
        return f"{params.get('source', '')} → {params.get('destination', '')}"
    if tool == "browser_navigate":
        return params.get("url", "")[:60]
    if tool in ("browser_click_text",):
        return f'"{params.get("text", "")}"'
    if tool == "browser_type":
        text = params.get("text", "")
        return f'"{text[:30]}..."' if len(text) > 30 else f'"{text}"'
    if tool == "skill_read":
        return params.get("skill_name", "")
    if tool == "knowledge_search":
        return params.get("query", "")[:40]
    if tool == "knowledge_write":
        return params.get("path", "")
    if tool == "self_create_plugin":
        return params.get("goal", "")[:40]
    if tool == "browser_extract":
        return "extracting page content"
    if tool == "browser_get_elements":
        return "listing elements"
    if tool == "browser_screenshot":
        return "capturing screenshot"
    if tool == "browser_wait_for_selector":
        return params.get("selector", "")
    return ""


# ──────────────────────────────────────────────────────────────────
# Approval UI
# ──────────────────────────────────────────────────────────────────


def approval_callback(tool_name: str, description: str, params: dict[str, Any]) -> bool:
    """Ask the user to approve a tool execution."""
    console.print()

    param_display = ""
    if tool_name == "shell_execute":
        param_display = f"  [bold]{params.get('command', '?')}[/bold]"
    elif tool_name in ("file_write", "file_read", "file_list", "file_delete"):
        param_display = f"  [bold]{params.get('path', '?')}[/bold]"
    elif tool_name == "file_move":
        param_display = f"  [bold]{params.get('source', '?')}[/bold] → [bold]{params.get('destination', '?')}[/bold]"
    else:
        param_display = f"  {json.dumps(params, indent=2)}"

    console.print(
        Panel(
            f"[{_C_WARN}]Tool:[/] [bold]{tool_name}[/]\n"
            f"[{_C_WARN}]Action:[/] {description}\n"
            f"{param_display}",
            title="[bold red]⚠ Approval Required[/]",
            border_style="red",
            padding=(0, 2),
        )
    )
    return Confirm.ask(f"  [{_C_SUCCESS}]Approve?[/]", default=True)


# ──────────────────────────────────────────────────────────────────
# Vault unlock
# ──────────────────────────────────────────────────────────────────


def _try_unlock_vault(agent: Any) -> None:
    """Unlock or create the credential vault."""
    if Vault.exists("."):
        console.print(f"  [{_C_DIM}]Credential vault found.[/]")
        password = Prompt.ask(
            f"  [{_C_DIM}]Vault password (Enter to skip)[/]", password=True, default=""
        )
        if not password:
            console.print(f"  [{_C_DIM}]Vault skipped.[/]")
            return
        try:
            agent._vault = Vault.unlock(".", password)
            console.print(f"  [{_C_SUCCESS}]Vault unlocked.[/]")
        except VaultError as e:
            console.print(f"  [{_C_WARN}]Vault: {e}[/]")
    else:
        console.print(f"  [{_C_DIM}]No vault found. Create one to store credentials securely.[/]")
        password = Prompt.ask(
            f"  [{_C_DIM}]Set vault password (Enter to skip)[/]",
            password=True,
            default="",
        )
        if not password:
            console.print(f"  [{_C_DIM}]Vault skipped.[/]")
            return
        try:
            agent._vault = Vault.create(".", password)
            console.print(f"  [{_C_SUCCESS}]Vault created and unlocked.[/]")
        except VaultError as e:
            console.print(f"  [{_C_WARN}]Vault creation failed: {e}[/]")


# ──────────────────────────────────────────────────────────────────
# Main entry
# ──────────────────────────────────────────────────────────────────


@click.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(),
    default=None,
    help="Path to config.yaml",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging")
@click.option(
    "--direct", is_flag=True, default=False, help="Skip gateway, connect directly to agent"
)
def chat_cmd(config_path: str | None, debug: bool, direct: bool) -> None:
    """Start an interactive chat session with EloPhanto."""
    import signal

    setup_logging(debug=debug)
    cfg = load_config(config_path)

    # Force-kill on second Ctrl+C (handles cases where aiogram swallows the first one)
    _interrupted_once = False

    def _force_exit(sig: int, frame: Any) -> None:
        nonlocal _interrupted_once
        if _interrupted_once:
            import os

            os._exit(1)
        _interrupted_once = True
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _force_exit)

    # Use gateway mode if enabled and not overridden
    if cfg.gateway.enabled and not direct:
        asyncio.run(_chat_gateway(cfg))
    else:
        asyncio.run(_chat_loop(config_path))


async def _chat_gateway(cfg: Any) -> None:
    """Gateway-mode chat: start gateway + agent inline, run CLI adapter."""
    from channels.cli_adapter import CLIAdapter
    from core.gateway import Gateway
    from core.session import SessionManager

    console.print(_BANNER)

    # Initialize agent (same as direct mode)
    agent = Agent(cfg)
    _try_unlock_vault(agent)

    console.print()
    spinner = Status("", console=console, spinner="dots")
    spinner.start()

    def _on_status(msg: str) -> None:
        spinner.update(f"  [{_C_DIM}]{msg}...[/]")

    try:
        _on_status("Loading tools")
        await agent.initialize(on_status=_on_status)  # type: ignore[arg-type]
    except Exception as e:
        spinner.stop()
        console.print(f"  [bold red]Initialization failed:[/bold red] {e}")
        console.print("  Run [bold]elophanto init[/bold] to configure providers.")
        return
    finally:
        spinner.stop()

    # Start gateway server
    session_mgr = SessionManager(agent._db)
    gateway = Gateway(
        agent=agent,
        session_manager=session_mgr,
        host=cfg.gateway.host,
        port=cfg.gateway.port,
        max_sessions=cfg.gateway.max_sessions,
    )
    await gateway.start()
    agent._gateway = gateway  # Enable scheduled task notifications
    gw_url = gateway.url

    # Start background channel adapters (Telegram, Discord, Slack)
    adapter_tasks: list[asyncio.Task] = []
    adapter_instances: list[Any] = []
    adapters_started: list[str] = []

    if cfg.telegram.enabled and agent._vault:
        try:
            bot_token = agent._vault.get(cfg.telegram.bot_token_ref)
            if bot_token:
                from channels.telegram_adapter import TelegramChannelAdapter

                tg = TelegramChannelAdapter(
                    bot_token=bot_token,
                    config=cfg.telegram,
                    gateway_url=gw_url,
                )
                adapter_instances.append(tg)
                adapter_tasks.append(asyncio.create_task(tg.start()))
                adapters_started.append("telegram")
        except Exception as e:
            console.print(f"  [{_C_WARN}]Telegram: {e}[/]")

    if getattr(cfg, "discord", None) and cfg.discord.enabled and agent._vault:
        try:
            bot_token = agent._vault.get(cfg.discord.bot_token_ref)
            if bot_token:
                from channels.discord_adapter import DiscordAdapter

                dc = DiscordAdapter(
                    bot_token=bot_token,
                    config=cfg.discord,
                    gateway_url=gw_url,
                )
                adapter_instances.append(dc)
                adapter_tasks.append(asyncio.create_task(dc.start()))
                adapters_started.append("discord")
        except Exception as e:
            console.print(f"  [{_C_WARN}]Discord: {e}[/]")

    if getattr(cfg, "slack", None) and cfg.slack.enabled and agent._vault:
        try:
            bot_token = agent._vault.get(cfg.slack.bot_token_ref)
            app_token = agent._vault.get(cfg.slack.app_token_ref)
            if bot_token and app_token:
                from channels.slack_adapter import SlackAdapter

                sl = SlackAdapter(
                    bot_token=bot_token,
                    app_token=app_token,
                    config=cfg.slack,
                    gateway_url=gw_url,
                )
                adapter_instances.append(sl)
                adapter_tasks.append(asyncio.create_task(sl.start()))
                adapters_started.append("slack")
        except Exception as e:
            console.print(f"  [{_C_WARN}]Slack: {e}[/]")

    # Show status panel
    skill_count = len(agent._skill_manager.list_skills())
    health = getattr(agent, "_provider_health", {})
    providers = [k for k, v in health.items() if v]
    tool_count = len(agent._registry.list_tools())

    features: list[str] = [f"[{_C_SUCCESS}]gateway[/]"]
    for a in adapters_started:
        features.append(f"[{_C_SUCCESS}]{a}[/]")
    if agent._browser_manager:
        features.append(f"[{_C_SUCCESS}]browser[/]")
    if agent._scheduler:
        features.append(f"[{_C_SUCCESS}]scheduler[/]")
    features.append(f"[{_C_SUCCESS}]vault[/]")

    info = Table.grid(padding=(0, 2))
    info.add_column(style=_C_DIM, justify="right", min_width=14)
    info.add_column()

    prov_parts = [f"[{_C_SUCCESS}]●[/] {p}" for p in providers] or ["[red]● none[/]"]
    info.add_row("Providers", "  ".join(prov_parts))
    info.add_row("Tools", f"[bold]{tool_count}[/] registered")
    info.add_row("Skills", f"[bold]{skill_count}[/] loaded")
    info.add_row("Features", "  ".join(features))
    info.add_row("Mode", f"[{_C_ACCENT}]{cfg.permission_mode}[/]")

    commands = Text()
    commands.append("\n")
    commands.append("  /clear", style="bold")
    commands.append(" reset context  ", style=_C_DIM)
    commands.append("  /stats", style="bold")
    commands.append(" session info  ", style=_C_DIM)
    commands.append("  exit", style="bold")
    commands.append(" quit", style=_C_DIM)

    content = Group(info, commands)
    welcome = Panel(
        content,
        title=f"[bold {_C_PRIMARY}]System[/]",
        subtitle=f"[{_C_DIM}]v0.1.0 · gateway {gw_url}[/]",
        border_style=_C_BORDER,
        padding=(1, 2),
    )
    console.print(welcome)
    console.print()

    # Run CLI adapter connected to local gateway
    cli = CLIAdapter(gateway_url=gw_url)
    try:
        await cli.start()
    except (KeyboardInterrupt, EOFError):
        pass

    # Shutdown — stop adapters gracefully, then cancel tasks
    console.print(f"\n  [{_C_DIM}]Shutting down...[/]")
    for adapter in adapter_instances:
        try:
            await adapter.stop()
        except Exception:
            pass
    for task in adapter_tasks:
        task.cancel()
    for task in adapter_tasks:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    await gateway.stop()
    console.print(f"  [{_C_DIM}]Goodbye.[/]")


async def _chat_loop(config_path: str | None) -> None:
    """Main chat REPL."""
    cfg = load_config(config_path)
    agent = Agent(cfg)
    stats = SessionStats()

    # Banner
    console.print(_BANNER)

    _try_unlock_vault(agent)

    console.print()
    spinner = Status("", console=console, spinner="dots")
    spinner.start()

    def _on_status(msg: str) -> None:
        spinner.update(f"  [{_C_DIM}]{msg}...[/]")

    try:
        _on_status("Loading tools")
        await agent.initialize(on_status=_on_status)  # type: ignore[arg-type]
    except Exception as e:
        spinner.stop()
        console.print(f"  [bold red]Initialization failed:[/bold red] {e}")
        console.print("  Run [bold]elophanto init[/bold] to configure providers.")
        return
    finally:
        spinner.stop()

    agent.set_approval_callback(approval_callback)

    # Start Telegram bot in background if enabled and vault has the token
    telegram_adapter = None
    if cfg.telegram.enabled and agent._vault:
        try:
            bot_token = agent._vault.get(cfg.telegram.bot_token_ref)
            if bot_token:
                from core.telegram import TelegramAdapter

                telegram_adapter = TelegramAdapter(agent, cfg.telegram, bot_token)
                asyncio.create_task(telegram_adapter.start())
                console.print(f"  [{_C_SUCCESS}]Telegram bot started.[/]")
            else:
                console.print(f"  [{_C_WARN}]Telegram enabled but no bot token in vault.[/]")
        except Exception as e:
            console.print(f"  [{_C_WARN}]Telegram failed: {e}[/]")
            telegram_adapter = None

    skill_count = len(agent._skill_manager.list_skills())
    welcome = _build_welcome_panel(
        cfg, agent, skill_count, telegram_running=telegram_adapter is not None
    )
    console.print(welcome)
    console.print()

    loop = asyncio.get_event_loop()

    while True:
        try:
            user_input = await loop.run_in_executor(None, lambda: Prompt.ask(f"  [{_C_USER}]❯[/]"))
        except (EOFError, KeyboardInterrupt):
            break

        stripped = user_input.strip().lower()

        if stripped in ("exit", "quit", "q"):
            break

        if not user_input.strip():
            continue

        if stripped == "/clear":
            agent.clear_conversation()
            console.print(f"  [{_C_DIM}]Context cleared.[/]")
            stats.context_messages = 0
            continue

        if stripped == "/stats":
            stats.update_from_tracker(agent._router.cost_tracker)
            stats.context_messages = len(agent._conversation_history)
            console.print(_build_session_stats_panel(stats, cfg))
            continue

        # Execute task (cancellable with Ctrl+C)
        try:
            console.print()
            progress = _LiveProgress(console)
            progress.start()

            def _on_step(
                step: int, tool: str, thought: str, params: dict, _p: Any = progress
            ) -> None:
                detail = _summarize_params(tool, params)
                _p.update(step, tool, detail)

            agent._on_step = _on_step
            task_start = time.time()

            # Run as cancellable task so Ctrl+C can interrupt it
            agent_task = asyncio.create_task(agent.run(user_input))
            try:
                response = await asyncio.shield(agent_task)
            except asyncio.CancelledError:
                progress.stop()
                agent._on_step = None
                console.print(f"\n  [{_C_WARN}]Task interrupted.[/]")
                continue

            task_elapsed = time.time() - task_start
            agent._on_step = None

            progress.stop()

            stats.task_count += 1
            stats.update_from_tracker(agent._router.cost_tracker)
            stats.update_task_tokens(agent._router.cost_tracker)
            stats.context_messages = len(agent._conversation_history)

            # Response panel
            console.print()
            console.print(
                Panel(
                    Markdown(response.content),
                    title=_LOGO_SMALL,
                    border_style=_C_BORDER,
                    padding=(1, 2),
                )
            )

            # Stats bar
            stats_bar = _build_stats_bar(stats, cfg)
            console.print(stats_bar)

            # Step summary
            if response.tool_calls_made:
                unique_tools = list(dict.fromkeys(response.tool_calls_made))
                tools_text = Text()
                tools_text.append("  ╰─ ", style=_C_DIM)
                tools_text.append(f"{response.steps_taken} step(s)", style=_C_DIM)
                tools_text.append("  ", style=_C_DIM)
                for i, t in enumerate(unique_tools[:6]):
                    if i > 0:
                        tools_text.append(" → ", style=_C_DIM)
                    tools_text.append(t, style=_C_PRIMARY)
                if len(unique_tools) > 6:
                    tools_text.append(f" +{len(unique_tools) - 6}", style=_C_DIM)
                tools_text.append(f"  {task_elapsed:.1f}s", style=_C_DIM)
                console.print(tools_text)

            console.print()

        except KeyboardInterrupt:
            try:
                agent_task.cancel()
            except Exception:
                pass
            try:
                progress.stop()
            except Exception:
                pass
            agent._on_step = None
            console.print(f"\n  [{_C_WARN}]Task interrupted. Ready for next command.[/]")
        except Exception as e:
            try:
                progress.stop()
            except Exception:
                pass
            agent._on_step = None
            console.print(f"\n  [bold red]Error:[/bold red] {e}")
            logger.exception("Agent run failed")

    # Shutdown
    if telegram_adapter:
        try:
            await telegram_adapter.stop()
        except Exception:
            pass

    console.print()
    stats.update_from_tracker(agent._router.cost_tracker)
    console.print(
        Panel(
            f"[{_C_DIM}]Session: {stats.uptime} │ "
            f"Tasks: {stats.task_count} │ "
            f"Tokens: {_format_tokens(stats.total_tokens)} │ "
            f"Cost: ${stats.session_cost:.4f}[/]",
            title=f"[{_C_DIM}]Goodbye[/]",
            border_style=_C_DIM,
            padding=(0, 2),
        )
    )
