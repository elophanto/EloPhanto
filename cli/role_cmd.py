"""CLI for managing role personas (ABE Phase 2).

See ``docs/76-ABE-FRAMEWORK.md``. A role is a system-prompt overlay
plus a tool allowlist. EloPhanto stays one evolving identity; roles
are masks it wears per cycle. The CLI lets the operator inspect what
roles exist, sync changes from ``roles/<name>.yaml`` files, and scope
a session to a specific role.

Actions:
- ``list``                  — show all roles + active marker + last_active_at
- ``show <name>``           — print one role's full overlay + allowlist + KPI
- ``sync``                  — re-read roles/*.yaml into the DB (idempotent)
- ``use <name>``            — set this role as the active one for future CLI
                              invocations (persisted to
                              ``~/.elophanto/current_role``); empty/clear unsets
- ``clear``                 — same as ``use`` with no name; removes the sidecar
- ``current``               — print the active role name (or "(none)")
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from core.config import load_config
from core.database import Database
from core.role import RoleManager
from core.role_context import (
    read_persisted_current_role,
    write_persisted_current_role,
)

console = Console()


@click.command("role")
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.argument("action", default="list")
@click.argument("name", required=False)
def role_cmd(
    config_path: str | None,
    action: str,
    name: str | None,
) -> None:
    """Manage role personas (ABE framework). Default action: list."""
    cfg_path = Path(config_path) if config_path else None
    config = load_config(cfg_path)
    asyncio.run(_dispatch(config, action, name))


async def _dispatch(config, action: str, name: str | None) -> None:
    db_path = Path(config.database.db_path)
    if not db_path.is_absolute():
        db_path = config.project_root / db_path
    db = Database(db_path)
    await db.initialize()
    roles_dir = config.project_root / "roles"
    mgr = RoleManager(db=db, roles_dir=roles_dir)

    if action == "list":
        await _list(mgr)
    elif action == "show":
        if not name:
            console.print("[red]Usage:[/red] elophanto role show <name>")
            return
        await _show(mgr, name)
    elif action == "sync":
        count = await mgr.sync_from_disk()
        console.print(
            f"[green]Synced[/green] {count} role(s) from " f"[dim]{roles_dir}[/dim]"
        )
    elif action == "use":
        if not name:
            # Treat bare `use` as clear, matching the docstring.
            write_persisted_current_role(None)
            console.print("[green]Active role cleared[/green] — defaulting to CEO")
            return
        await _use(mgr, name)
    elif action == "clear":
        write_persisted_current_role(None)
        console.print("[green]Active role cleared[/green] — defaulting to CEO")
    elif action == "current":
        active = read_persisted_current_role()
        console.print(active or "(none — playing CEO)")
    else:
        console.print(f"[red]Unknown action:[/red] {action}")
        console.print("Use: list | show | sync | use | clear | current")


async def _list(mgr: RoleManager) -> None:
    roles = await mgr.list_roles()
    if not roles:
        console.print(
            "[dim]No roles. Add YAML files under[/dim] roles/ "
            "[dim]then run:[/dim] elophanto role sync"
        )
        return

    active = read_persisted_current_role()
    table = Table(title="Roles")
    table.add_column("", style="green")
    table.add_column("Name", style="cyan")
    table.add_column("Allowed tools", justify="right")
    table.add_column("Allowed groups", justify="right")
    table.add_column("Last active")
    for r in roles:
        marker = "●" if r.name == active else ""
        tool_count = (
            "[dim](no constraint)[/dim]"
            if not r.allowed_tools and not r.allowed_tool_groups
            else str(len(r.allowed_tools))
        )
        group_count = str(len(r.allowed_tool_groups)) if r.allowed_tool_groups else "—"
        last = (
            r.last_active_at.split("T")[0] if r.last_active_at else "[dim]never[/dim]"
        )
        table.add_row(marker, r.name, tool_count, group_count, last)
    console.print(table)
    console.print(f"[dim]Active:[/dim] {active or '(none — playing CEO)'}")


async def _show(mgr: RoleManager, name: str) -> None:
    role = await mgr.get(name)
    if role is None:
        console.print(f"[red]No such role:[/red] {name}")
        return
    console.print()
    console.print(f"[bold cyan]{role.name}[/bold cyan] — {role.description.strip()}")
    if role.prompt_overlay:
        console.print()
        console.print("[bold]Prompt overlay:[/bold]")
        console.print(role.prompt_overlay.strip())
    if role.allowed_tools:
        console.print()
        console.print(
            f"[bold]Allowed tools[/bold] ({len(role.allowed_tools)}): "
            f"{', '.join(role.allowed_tools)}"
        )
    if role.allowed_tool_groups:
        console.print(
            f"[bold]Allowed tool groups:[/bold] {', '.join(role.allowed_tool_groups)}"
        )
    if not role.allowed_tools and not role.allowed_tool_groups:
        console.print("[dim]No tool constraint — full registry.[/dim]")
    if role.kpi:
        console.print()
        console.print("[bold]KPI:[/bold]")
        for k, v in role.kpi.items():
            console.print(f"  {k}: {v}")
    console.print()
    last = role.last_active_at or "[dim]never[/dim]"
    console.print(f"[dim]Scope:[/dim] {role.scope}   [dim]Last active:[/dim] {last}")


async def _use(mgr: RoleManager, name: str) -> None:
    role = await mgr.get(name)
    if role is None:
        console.print(f"[red]No such role:[/red] {name}")
        console.print("[dim]Run:[/dim] elophanto role sync [dim]to import YAMLs[/dim]")
        return
    write_persisted_current_role(name)
    console.print(f"[green]Active role:[/green] [cyan]{name}[/cyan]")
