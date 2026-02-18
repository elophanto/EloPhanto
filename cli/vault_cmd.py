"""elophanto vault — Manage the encrypted credential vault.

Commands:
    init   — Create a new vault (sets master password)
    set    — Store a credential (domain + email + password)
    get    — Retrieve a credential
    list   — List stored credential keys
    delete — Remove a credential
"""

from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from core.vault import Vault, VaultError

console = Console()


def _vault_dir() -> str:
    """Return the directory where vault files live (project root)."""
    return "."


def _ask_master_password(*, confirm: bool = False) -> str:
    """Prompt for the vault master password."""
    password = Prompt.ask("[bold]Master password[/bold]", password=True)
    if not password:
        raise click.Abort()
    if confirm:
        password2 = Prompt.ask("[bold]Confirm password[/bold]", password=True)
        if password != password2:
            console.print("[red]Passwords do not match.[/red]")
            raise click.Abort()
    return password


@click.group()
def vault_cmd() -> None:
    """Manage the encrypted credential vault."""


@vault_cmd.command("init")
def vault_init() -> None:
    """Create a new encrypted vault."""
    vdir = _vault_dir()

    if Vault.exists(vdir):
        if not click.confirm(
            "A vault already exists. This will overwrite it. Continue?"
        ):
            return

    console.print(
        Panel(
            "Create a master password for your credential vault.\n"
            "This password encrypts all stored credentials using AES-256.\n"
            "[dim]The vault files (vault.enc, vault.salt) are in .gitignore.[/dim]",
            title="[bold]Vault Setup[/bold]",
            border_style="blue",
        )
    )

    password = _ask_master_password(confirm=True)
    Vault.create(vdir, password)
    console.print("[green]Vault created.[/green]")


@vault_cmd.command("set")
@click.argument("domain")
def vault_set(domain: str) -> None:
    """Store credentials for DOMAIN (e.g. google.com, github.com)."""
    vdir = _vault_dir()
    password = _ask_master_password()

    try:
        vault = Vault.unlock(vdir, password)
    except VaultError as e:
        console.print(f"[red]{e}[/red]")
        return

    # Get existing values as defaults
    existing = vault.get(domain) or {}
    default_email = existing.get("email", "")
    default_username = existing.get("username", "")

    console.print(f"\n[bold]Credentials for[/bold] [blue]{domain}[/blue]")

    email = Prompt.ask(
        "  Email",
        default=default_email or None,
        show_default=bool(default_email),
    )
    username = Prompt.ask(
        "  Username (if different from email, press Enter to skip)",
        default=default_username or "",
        show_default=bool(default_username),
    )
    cred_password = Prompt.ask("  Password", password=True)

    if not cred_password:
        console.print("[yellow]No password provided — skipped.[/yellow]")
        return

    entry: dict[str, str] = {"password": cred_password}
    if email:
        entry["email"] = email
    if username:
        entry["username"] = username

    vault.set(domain, entry)
    console.print(f"[green]Credentials for {domain} saved.[/green]")


@vault_cmd.command("get")
@click.argument("domain")
def vault_get(domain: str) -> None:
    """Retrieve credentials for DOMAIN."""
    vdir = _vault_dir()
    password = _ask_master_password()

    try:
        vault = Vault.unlock(vdir, password)
    except VaultError as e:
        console.print(f"[red]{e}[/red]")
        return

    creds = vault.get(domain)
    if not creds:
        console.print(f"[yellow]No credentials found for {domain}[/yellow]")
        return

    console.print(f"\n[bold]Credentials for[/bold] [blue]{domain}[/blue]")
    if isinstance(creds, dict):
        for k, v in creds.items():
            if k == "password":
                console.print(f"  {k}: [dim]{'*' * len(v)}[/dim]")
            else:
                console.print(f"  {k}: {v}")
    else:
        console.print(f"  {creds}")


@vault_cmd.command("list")
def vault_list() -> None:
    """List all stored credential keys."""
    vdir = _vault_dir()
    password = _ask_master_password()

    try:
        vault = Vault.unlock(vdir, password)
    except VaultError as e:
        console.print(f"[red]{e}[/red]")
        return

    keys = vault.list_keys()
    if not keys:
        console.print("[dim]Vault is empty.[/dim]")
        return

    table = Table(title="Stored Credentials")
    table.add_column("Domain", style="blue")
    table.add_column("Email / Username", style="dim")

    for key in sorted(keys):
        entry = vault.get(key)
        identity = ""
        if isinstance(entry, dict):
            identity = entry.get("email", "") or entry.get("username", "")
        table.add_row(key, identity)

    console.print(table)


@vault_cmd.command("delete")
@click.argument("domain")
def vault_delete(domain: str) -> None:
    """Delete credentials for DOMAIN."""
    vdir = _vault_dir()
    password = _ask_master_password()

    try:
        vault = Vault.unlock(vdir, password)
    except VaultError as e:
        console.print(f"[red]{e}[/red]")
        return

    if vault.delete(domain):
        console.print(f"[green]Credentials for {domain} deleted.[/green]")
    else:
        console.print(f"[yellow]No credentials found for {domain}[/yellow]")
