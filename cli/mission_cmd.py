"""CLI for managing missions (durable drives).

See ``docs/75-AUTONOMOUS-MIND-V2.md`` §Phase 2 for the design. The
mission tier sits above goals: missions are NEVER auto-completed,
only paused or retired. Goals roll under missions via
``goals.mission_id``; finishing a goal bumps the parent mission's
momentum.

Actions:
- ``list``                 — show active missions ranked by neglect
- ``list --all``           — include paused / retired
- ``show <id>``            — print one mission with momentum + staleness
- ``touch <id> [bump]``    — manually log progress on a mission
- ``pause <id>``           — pause a mission (still seeded, not picked)
- ``resume <id>``          — flip a paused mission back to active
- ``retire <id>``          — soft-delete (rows kept for goal history)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from core.config import load_config
from core.database import Database
from core.mission_manager import (
    STATUS_ACTIVE,
    STATUS_PAUSED,
    STATUS_RETIRED,
    MissionManager,
)

console = Console()


@click.command("mission")
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.option("--all", "show_all", is_flag=True, help="Include paused/retired in list")
@click.argument("action", default="list")
@click.argument("mission_id", required=False)
@click.argument("extra", required=False)
def mission_cmd(
    config_path: str | None,
    show_all: bool,
    action: str,
    mission_id: str | None,
    extra: str | None,
) -> None:
    """Manage missions (durable drives the agent works toward)."""
    asyncio.run(_run(config_path, show_all, action, mission_id, extra))


async def _run(
    config_path: str | None,
    show_all: bool,
    action: str,
    mission_id: str | None,
    extra: str | None,
) -> None:
    config = load_config(config_path)
    db_path = Path(config.database.db_path)
    if not db_path.is_absolute():
        db_path = config.project_root / db_path

    db = Database(db_path)
    await db.initialize()
    mgr = MissionManager(db)

    if action == "list":
        await _list(mgr, show_all=show_all)
        return
    if action == "show" and mission_id:
        await _show(mgr, mission_id)
        return
    if action == "touch" and mission_id:
        bump = float(extra) if extra else 1.0
        await _touch(mgr, mission_id, bump)
        return
    if action in {"pause", "resume", "retire"} and mission_id:
        target = {
            "pause": STATUS_PAUSED,
            "resume": STATUS_ACTIVE,
            "retire": STATUS_RETIRED,
        }[action]
        ok = await mgr.set_status(mission_id, target)
        if ok:
            console.print(f"[green]{action}d[/green] {mission_id}")
        else:
            console.print(f"[red]mission {mission_id!r} not found[/red]")
        return

    console.print(
        "[yellow]Usage:[/yellow] elophanto mission "
        "<list|show <id>|touch <id> [bump]|pause <id>|resume <id>|retire <id>>"
    )


async def _list(mgr: MissionManager, *, show_all: bool) -> None:
    if show_all:
        missions = await mgr.list_missions(status=None)
        ranked = sorted(
            missions,
            key=lambda m: (m.status != STATUS_ACTIVE, -m.priority_weight),
        )
        title = "Missions (all)"
    else:
        ranked = await mgr.list_by_neglect(limit=50)
        title = "Missions — active, ranked by neglect"

    if not ranked:
        console.print("[dim]No missions.[/dim]")
        return

    table = Table(title=title)
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Status")
    table.add_column("Weight", justify="right")
    table.add_column("Momentum", justify="right")
    table.add_column("Stale (h)", justify="right")
    table.add_column("Last touched")

    for m in ranked:
        stale = m.staleness_hours()
        stale_label = "—" if stale == float("inf") else f"{stale:.1f}"
        momentum = m.decayed_momentum()
        status_color = {
            STATUS_ACTIVE: "green",
            STATUS_PAUSED: "yellow",
            STATUS_RETIRED: "dim",
        }.get(m.status, "white")
        table.add_row(
            m.mission_id,
            m.title,
            f"[{status_color}]{m.status}[/{status_color}]",
            f"{m.priority_weight:.1f}",
            f"{momentum:.2f}",
            stale_label,
            m.last_touched_at or "—",
        )

    console.print(table)


async def _show(mgr: MissionManager, mission_id: str) -> None:
    m = await mgr.get(mission_id)
    if not m:
        console.print(f"[red]mission {mission_id!r} not found[/red]")
        return
    console.print(f"[bold]{m.title}[/bold]  [dim]({m.mission_id})[/dim]")
    console.print(f"Status:           {m.status}")
    console.print(f"Priority weight:  {m.priority_weight}")
    console.print(f"Momentum (raw):   {m.momentum_score:.3f}")
    console.print(f"Momentum (decay): {m.decayed_momentum():.3f}")
    stale = m.staleness_hours()
    console.print(
        "Staleness (h):    "
        + ("never touched" if stale == float("inf") else f"{stale:.1f}")
    )
    console.print(f"Last touched:     {m.last_touched_at or '—'}")
    console.print(f"Created:          {m.created_at}")
    console.print()
    console.print("[dim]Description:[/dim]")
    console.print(m.description or "[dim](none)[/dim]")


async def _touch(mgr: MissionManager, mission_id: str, bump: float) -> None:
    m = await mgr.touch(mission_id, bump=bump)
    if not m:
        console.print(f"[red]mission {mission_id!r} not found[/red]")
        return
    console.print(
        f"[green]touched[/green] {m.mission_id} "
        f"momentum={m.momentum_score:.3f} at={m.last_touched_at}"
    )
