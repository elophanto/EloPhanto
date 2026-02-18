"""elophanto telegram — Start the Telegram bot interface."""

from __future__ import annotations

import asyncio
import logging

import click
from rich.console import Console

from core.log_setup import setup_logging

console = Console()
logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(),
    default=None,
    help="Path to config.yaml",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging")
def telegram_cmd(config_path: str | None, debug: bool) -> None:
    """Start the Telegram bot interface."""
    setup_logging(debug=debug)
    asyncio.run(_run_telegram(config_path))


async def _run_telegram(config_path: str | None) -> None:
    """Initialize agent and start Telegram bot."""
    from core.agent import Agent
    from core.config import load_config
    from core.vault import Vault, VaultError

    cfg = load_config(config_path)

    if not cfg.telegram.enabled:
        console.print(
            "[red]Telegram is not enabled in config.yaml.[/red]\n"
            "Set [bold]telegram.enabled: true[/bold] and configure "
            "your bot token in the vault."
        )
        return

    agent = Agent(cfg)

    # Unlock vault to get bot token
    bot_token = None
    if Vault.exists("."):
        from rich.prompt import Prompt

        password = Prompt.ask(
            "[bold]Vault password[/bold] (for bot token)",
            password=True,
            default="",
        )
        if password:
            try:
                vault = Vault.unlock(".", password)
                agent._vault = vault
                bot_token = vault.get(cfg.telegram.bot_token_ref)
            except VaultError as e:
                console.print(f"[yellow]Vault: {e}[/yellow]")

    if not bot_token:
        console.print(
            "[red]No bot token found.[/red]\n"
            f"Store it with: [bold]elophanto vault set "
            f"{cfg.telegram.bot_token_ref} YOUR_TOKEN[/bold]"
        )
        return

    # Initialize agent
    console.print("[dim]Initializing agent...[/dim]")
    try:
        await agent.initialize()
    except Exception as e:
        console.print(f"[red]Initialization failed: {e}[/red]")
        return

    from core.telegram import TelegramAdapter

    adapter = TelegramAdapter(agent, cfg.telegram, bot_token)

    allowed = cfg.telegram.allowed_users
    users_str = ", ".join(str(u) for u in allowed) if allowed else "all (no whitelist)"
    console.print(
        f"[green]Telegram bot starting[/green]\n"
        f"[dim]Mode:[/dim] {cfg.telegram.mode}\n"
        f"[dim]Allowed users:[/dim] {users_str}\n"
        f"[dim]Press Ctrl+C to stop[/dim]"
    )

    try:
        await adapter.start()
    except KeyboardInterrupt:
        pass
    finally:
        await adapter.stop()
        console.print("\n[dim]Telegram bot stopped.[/dim]")
