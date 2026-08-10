"""elophanto oauth — Connect user accounts (Gmail, Calendar, …).

Commands:
    login   — Run the browser consent flow and store the tokens
    list    — Show connected accounts (never the tokens themselves)
    logout  — Forget a provider's tokens
    scope   — Manage the self-owned-scope declaration
"""

from __future__ import annotations

import asyncio

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.config import load_config

console = Console()


def _store(config, vault=None):
    from core.oauth import store_from_config

    return store_from_config(config, vault=vault)


def _unlock_vault_if_present(config):
    """Offer to unlock the vault so tokens are stored encrypted."""
    from rich.prompt import Confirm, Prompt

    from core.vault import Vault, VaultError

    if not Vault.exists(config.project_root):
        console.print(
            "[yellow]No vault found — tokens will be stored in a 0600 file.[/yellow]\n"
            "Run [bold]elophanto vault init[/bold] first to encrypt them at rest."
        )
        return None
    if not Confirm.ask("Unlock the vault to store tokens encrypted?", default=True):
        return None
    password = Prompt.ask("[bold]Master password[/bold]", password=True)
    try:
        return Vault.unlock(config.project_root, password)
    except VaultError as exc:
        console.print(f"[red]{exc}[/red]")
        return None


@click.group()
def oauth_cmd() -> None:
    """Connect the agent to your accounts (Gmail, Calendar, …)."""


@oauth_cmd.command("login")
@click.argument("provider")
@click.option("--timeout", default=300.0, help="Seconds to wait for consent.")
def login(provider: str, timeout: float) -> None:
    """Run the OAuth consent flow for PROVIDER (e.g. google)."""
    from core.oauth import WELL_KNOWN, OAuthError, OAuthFlow

    config = load_config()
    provider_cfg = config.oauth.providers.get(provider)
    if provider_cfg is None:
        known = ", ".join(sorted(WELL_KNOWN))
        console.print(
            Panel(
                f"No config for provider [bold]{provider}[/bold].\n\n"
                "Add this to config.yaml:\n\n"
                f"[dim]oauth:\n"
                f"  enabled: true\n"
                f"  providers:\n"
                f"    {provider}:\n"
                f'      client_id: "..."\n'
                f'      client_secret: "..."   # omit for PKCE-only clients[/dim]\n\n'
                f"Endpoints are built in for: {known}",
                title="Provider not configured",
                border_style="yellow",
            )
        )
        raise SystemExit(1)

    vault = _unlock_vault_if_present(config)
    store = _store(config, vault)

    try:
        flow = OAuthFlow(provider, provider_cfg)
        tokens = asyncio.run(flow.run_local_flow(timeout=timeout))
    except OAuthError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    # Resolve the account label so `list` shows something human.
    if provider == "google":
        tokens.account = _google_account(tokens.access_token) or ""

    store.save(provider, tokens)
    console.print(
        Panel(
            f"Connected [bold green]{provider}[/bold green]"
            + (f" as [bold]{tokens.account}[/bold]" if tokens.account else "")
            + f"\nScopes: {', '.join(tokens.scopes) or '(as configured)'}",
            title="Authorized",
            border_style="green",
        )
    )


def _google_account(access_token: str) -> str:
    try:
        import httpx

        response = httpx.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15.0,
        )
        if response.status_code < 400:
            return str(response.json().get("email", ""))
    except Exception:
        pass
    return ""


@oauth_cmd.command("list")
def list_providers() -> None:
    """Show connected accounts."""
    config = load_config()
    store = _store(config)
    providers = store.list_providers()
    if not providers:
        console.print(
            "[dim]No accounts connected. Run "
            "[bold]elophanto oauth login google[/bold].[/dim]"
        )
        return
    table = Table(title="Connected accounts")
    table.add_column("Provider", style="cyan")
    table.add_column("Account")
    table.add_column("Expires in")
    table.add_column("Refreshable")
    for name, info in providers.items():
        expires = info.get("expires_in")
        table.add_row(
            name,
            info.get("account") or "[dim]unknown[/dim]",
            f"{expires}s" if expires is not None else "[dim]n/a[/dim]",
            "yes" if info.get("has_refresh_token") else "[yellow]no[/yellow]",
        )
    console.print(table)


@oauth_cmd.command("logout")
@click.argument("provider")
def logout(provider: str) -> None:
    """Forget PROVIDER's stored tokens."""
    config = load_config()
    vault = _unlock_vault_if_present(config)
    store = _store(config, vault)
    if store.forget(provider):
        console.print(f"[green]Disconnected {provider}.[/green]")
        console.print(
            "[dim]The grant may still exist at the provider — revoke it there "
            "too if you want it gone entirely.[/dim]"
        )
    else:
        console.print(f"[yellow]{provider} was not connected.[/yellow]")


@oauth_cmd.command("scope")
@click.option("--add-owned", help="Declare a host as yours (e.g. api.mygym.com).")
@click.option("--remove-owned", help="Undeclare a host.")
def scope(add_owned: str, remove_owned: str) -> None:
    """Show or edit which systems you have declared as your own.

    The scope guard refuses destructive actions against anything not
    declared here, so this list is what separates "cancel my booking"
    from "delete someone else's".
    """
    from core.scope_guard import ScopeGuard, policy_from_config

    config = load_config()
    data_dir = config.project_root / "data"
    view = policy_from_config(config)
    guard = ScopeGuard.load(data_dir, policy=view.policy)

    changed = False
    if add_owned:
        guard.declare_owned(add_owned)
        changed = True
    if remove_owned:
        target = remove_owned.lower().lstrip(".")
        if target in guard.owned:
            guard._owned.remove(target)
            changed = True
        else:
            console.print(f"[yellow]{remove_owned} was not in the owned list.[/yellow]")
    if changed:
        path = guard.save(data_dir)
        console.print(f"[green]Updated {path}[/green]")

    table = Table(title="Declared scope")
    table.add_column("Class", style="cyan")
    table.add_column("Targets")
    table.add_row("owned", "\n".join(guard.owned) or "[dim]none[/dim]")
    table.add_row("third_party", "\n".join(guard.third_party) or "[dim]none[/dim]")
    table.add_row(
        "authorizations",
        "\n".join(
            f"{a.target} — {a.scope} (by {a.authorized_by or '?'}"
            + (f", expires {a.expires}" if a.expires else "")
            + ")"
            for a in guard.authorizations
        )
        or "[dim]none[/dim]",
    )
    console.print(table)
    console.print(
        f"[dim]Policy: foreign writes → {view.policy.foreign_write}, "
        f"foreign destructive → {view.policy.foreign_destructive}, "
        f"own destructive → {view.policy.owned_destructive}[/dim]"
    )
