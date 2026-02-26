"""elophanto gateway — Start the gateway with agent and channel adapters.

This is the primary entry point for multi-channel mode. It:
1. Initializes the agent (tools, browser, vault, etc.)
2. Starts the WebSocket gateway
3. Launches enabled channel adapters (Telegram, Discord, Slack)
4. Optionally also runs the CLI adapter inline
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from rich.table import Table

from cli.chat_cmd import _build_banner
from core.agent import Agent
from core.config import load_config
from core.log_setup import setup_logging
from core.vault import Vault, VaultError

console = Console()
logger = logging.getLogger(__name__)

_C_PRIMARY = "bright_white"
_C_ACCENT = "grey74"
_C_SUCCESS = "bright_green"
_C_WARN = "bright_yellow"
_C_DIM = "dim"
_C_BORDER = "grey50"


@click.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(),
    default=None,
    help="Path to config.yaml",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging")
@click.option("--no-cli", is_flag=True, default=False, help="Don't start CLI adapter")
def gateway_cmd(config_path: str | None, debug: bool, no_cli: bool) -> None:
    """Start the gateway with agent and all enabled channel adapters."""
    import signal
    import time as _time

    setup_logging(debug=debug)

    _last_interrupt = 0.0

    def _force_exit(sig: int, frame: Any) -> None:
        nonlocal _last_interrupt
        now = _time.monotonic()
        if now - _last_interrupt < 1.0:
            # Double Ctrl+C within 1 second — force exit
            import os

            os._exit(1)
        _last_interrupt = now
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _force_exit)
    asyncio.run(_run_gateway(config_path, no_cli=no_cli))


async def _run_gateway(config_path: str | None, no_cli: bool = False) -> None:
    """Initialize agent, start gateway, launch adapters."""
    cfg = load_config(config_path)

    if not cfg.gateway.enabled:
        console.print(
            f"  [{_C_WARN}]Gateway disabled in config. Set gateway.enabled: true[/]"
        )
        return

    console.print(_build_banner())

    # Initialize agent
    agent = Agent(cfg)

    # Unlock vault
    from rich.prompt import Prompt

    if Vault.exists("."):
        password = Prompt.ask(
            f"  [{_C_DIM}]Vault password (Enter to skip)[/]", password=True, default=""
        )
        if password:
            try:
                agent._vault = Vault.unlock(".", password)
                console.print(f"  [{_C_SUCCESS}]Vault unlocked.[/]")
            except VaultError as e:
                console.print(f"  [{_C_WARN}]Vault: {e}[/]")

    spinner = Status("", console=console, spinner="dots")
    spinner.start()

    def _on_status(msg: str) -> None:
        spinner.update(f"  [{_C_DIM}]{msg}...[/]")

    try:
        await agent.initialize(on_status=_on_status)  # type: ignore[arg-type]
    except Exception as e:
        spinner.stop()
        console.print(f"  [bold red]Initialization failed:[/] {e}")
        return
    finally:
        spinner.stop()

    # Start gateway
    from core.gateway import Gateway
    from core.session import SessionManager

    session_mgr = SessionManager(agent._db)
    # Resolve auth token from vault if configured
    auth_token: str | None = None
    if cfg.gateway.auth_token_ref and agent._vault:
        auth_token = agent._vault.get(cfg.gateway.auth_token_ref)

    gateway = Gateway(
        agent=agent,
        session_manager=session_mgr,
        host=cfg.gateway.host,
        port=cfg.gateway.port,
        auth_token=auth_token,
        max_sessions=cfg.gateway.max_sessions,
        session_timeout_hours=cfg.gateway.session_timeout_hours,
        unified_sessions=cfg.gateway.unified_sessions,
        authority_config=cfg.authority,
    )

    await gateway.start()
    agent._gateway = gateway  # Enable scheduled task notifications

    # Update GoalRunner with gateway reference + resume active goals
    if agent._goal_runner:
        agent._goal_runner._gateway = gateway
        asyncio.create_task(agent._goal_runner.resume_on_startup())

    # Update AutonomousMind with gateway reference + start
    if agent._autonomous_mind:
        agent._autonomous_mind._gateway = gateway
        mind_task = asyncio.create_task(agent._autonomous_mind.resume_on_startup())
        mind_task.add_done_callback(
            lambda t: (
                logger.error("Mind startup failed: %s", t.exception())
                if not t.cancelled() and t.exception()
                else None
            )
        )

    # Update EmailMonitor with gateway reference (user starts via tool)
    if agent._email_monitor:
        agent._email_monitor._gateway = gateway

    # Track adapter tasks and instances for clean shutdown
    adapter_tasks: list[asyncio.Task] = []
    adapter_instances: list = []
    adapters_started: list[str] = []

    gw_url = gateway.url

    # Start Telegram adapter if enabled
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

    # Start Discord adapter if enabled
    if cfg.discord.enabled and agent._vault:
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

    # Start Slack adapter if enabled
    if cfg.slack.enabled and agent._vault:
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
    tool_count = len(agent._registry.list_tools())
    skill_count = len(agent._skill_manager.list_skills())
    health = getattr(agent, "_provider_health", {})
    providers = [k for k, v in health.items() if v]

    info = Table.grid(padding=(0, 2))
    info.add_column(style=_C_DIM, justify="right", min_width=14)
    info.add_column()
    info.add_row("Gateway", f"[{_C_SUCCESS}]{gw_url}[/]")

    prov_parts = [f"[{_C_SUCCESS}]●[/] {p}" for p in providers] or ["[red]● none[/]"]
    info.add_row("Providers", "  ".join(prov_parts))
    info.add_row("Tools", f"[bold]{tool_count}[/] registered")
    info.add_row("Skills", f"[bold]{skill_count}[/] loaded")

    # Channel badges
    channel_badges = []
    for a in adapters_started:
        channel_badges.append(f"[black on {_C_SUCCESS}] {a} [/]")
    info.add_row(
        "Channels",
        "  ".join(channel_badges) if channel_badges else f"[{_C_DIM}]none[/]",
    )
    info.add_row("Mode", f"[{_C_ACCENT}]{cfg.permission_mode}[/]")

    console.print(
        Panel(
            info,
            title=f"[bold {_C_PRIMARY}]Gateway Running[/]",
            subtitle=f"[{_C_DIM}]{gw_url}[/]",
            border_style=_C_BORDER,
            padding=(1, 2),
        )
    )

    # Start CLI adapter inline (or just wait)
    if not no_cli:
        from channels.cli_adapter import CLIAdapter

        cli = CLIAdapter(gateway_url=gw_url)
        try:
            await cli.start()
        except (KeyboardInterrupt, EOFError):
            pass
    else:
        console.print(f"\n  [{_C_DIM}]Gateway running. Press Ctrl+C to stop.[/]\n")
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
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

    # Shut down agent (MCP connections, browser, scheduler, DB)
    try:
        await agent.shutdown()
    except Exception:
        pass

    console.print(f"  [{_C_DIM}]Goodbye.[/]")
