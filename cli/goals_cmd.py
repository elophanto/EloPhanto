"""CLI for inspecting and managing goals.

Goals are normally created by the agent (via the ``goal_create`` LLM
tool) — there is no ``elophanto goals create`` because writing a
useful goal requires the model's planning context. But operators
DO need to inspect and prune the goal queue:

  elophanto goals list                  — recent goals (default: 20)
  elophanto goals list --status active  — filter by status
  elophanto goals show <id>             — detail incl. checkpoints
  elophanto goals cancel <id>           — mark cancelled (runner skips it)
  elophanto goals pause/resume <id>     — toggle active ↔ paused
  elophanto goals delete <id>           — hard-delete (destructive)
  elophanto goals delete-all            — wipe every goal (asks confirm)

Statuses: planning | active | paused | completed | failed | cancelled.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from core.config import load_config
from core.database import Database
from core.goal_manager import GoalManager

console = Console()


_VALID_STATUSES = {
    "planning",
    "active",
    "paused",
    "completed",
    "failed",
    "cancelled",
}


def _new_manager(db: Database, cfg) -> GoalManager:
    # Read-only ops (list / show / cancel / delete / pause / resume)
    # never call the LLM, so a None router is fine. Avoid spinning up
    # the full router stack just for a CLI listing.
    return GoalManager(db, router=None, config=cfg.goals)


@click.command("goals")
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.option(
    "--status",
    "status_filter",
    default=None,
    help="Filter list by status (planning|active|paused|completed|failed|cancelled)",
)
@click.option("--limit", default=20, show_default=True, help="Rows in list view")
@click.argument("action", default="list")
@click.argument("goal_id", required=False)
def goals_cmd(
    config_path: str | None,
    status_filter: str | None,
    limit: int,
    action: str,
    goal_id: str | None,
) -> None:
    """Inspect and manage goals (the agent creates them via goal_create)."""
    asyncio.run(_run(config_path, status_filter, limit, action, goal_id))


async def _run(
    config_path: str | None,
    status_filter: str | None,
    limit: int,
    action: str,
    goal_id: str | None,
) -> None:
    config = load_config(config_path)
    db_path = Path(config.database.db_path)
    if not db_path.is_absolute():
        db_path = config.project_root / db_path
    db = Database(db_path)
    await db.initialize()
    mgr = _new_manager(db, config)

    if action == "list":
        if status_filter and status_filter not in _VALID_STATUSES:
            console.print(
                f"[red]invalid status:[/red] {status_filter}\n"
                f"valid: {', '.join(sorted(_VALID_STATUSES))}"
            )
            raise SystemExit(1)
        await _list(mgr, status=status_filter, limit=limit)
        return

    if action == "show" and goal_id:
        await _show(mgr, goal_id)
        return

    if action == "cancel" and goal_id:
        ok = await mgr.cancel_goal(goal_id)
        _report(ok, "cancelled", goal_id)
        return

    if action == "pause" and goal_id:
        ok = await mgr.pause_goal(goal_id)
        _report(ok, "paused", goal_id)
        return

    if action == "resume" and goal_id:
        ok = await mgr.resume_goal(goal_id)
        _report(ok, "resumed", goal_id)
        return

    if action == "delete" and goal_id:
        if not Confirm.ask(
            f"Delete goal {goal_id!r} and its checkpoints?", default=False
        ):
            console.print("[dim]aborted[/dim]")
            return
        ok = await mgr.delete_goal(goal_id)
        _report(ok, "deleted", goal_id)
        return

    if action == "delete-all":
        if not Confirm.ask(
            "[red]DELETE ALL GOALS[/red] (and all checkpoints)?", default=False
        ):
            console.print("[dim]aborted[/dim]")
            return
        n = await mgr.delete_all_goals()
        console.print(f"[green]deleted {n} goal(s)[/green]")
        return

    console.print(
        "[yellow]Usage:[/yellow] elophanto goals "
        "<list|show <id>|cancel <id>|pause <id>|resume <id>|delete <id>|delete-all>\n"
        "[dim]list flags:[/dim] --status <name> --limit <n>"
    )


async def _list(mgr: GoalManager, *, status: str | None, limit: int) -> None:
    goals = await mgr.list_goals(status=status, limit=limit)
    if not goals:
        console.print(
            "[dim]No goals." + (f" (status={status})" if status else "") + "[/dim]"
        )
        return

    title = "Goals" + (f" — status={status}" if status else f" — recent {limit}")
    table = Table(title=title)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Goal", style="green")
    table.add_column("Status")
    table.add_column("Progress", justify="right")
    table.add_column("LLM calls", justify="right")
    table.add_column("Cost $", justify="right")
    table.add_column("Updated", no_wrap=True)

    status_color = {
        "planning": "yellow",
        "active": "green",
        "paused": "yellow",
        "completed": "blue",
        "failed": "red",
        "cancelled": "dim",
    }
    for g in goals:
        progress = (
            f"{g.current_checkpoint}/{g.total_checkpoints}"
            if g.total_checkpoints
            else "—"
        )
        goal_text = g.goal if len(g.goal) <= 60 else g.goal[:57] + "…"
        color = status_color.get(g.status, "white")
        table.add_row(
            g.goal_id,
            goal_text,
            f"[{color}]{g.status}[/{color}]",
            progress,
            str(g.llm_calls_used),
            f"{g.cost_usd:.4f}",
            g.updated_at[:19] if g.updated_at else "—",
        )
    console.print(table)


async def _show(mgr: GoalManager, goal_id: str) -> None:
    g = await mgr.get_goal(goal_id)
    if not g:
        console.print(f"[red]goal {goal_id!r} not found[/red]")
        return
    console.print(f"[bold]{g.goal}[/bold]  [dim]({g.goal_id})[/dim]")
    console.print(f"Status:           {g.status}")
    console.print(f"Session:          {g.session_id or '—'}")
    console.print(f"Mission:          {g.mission_id or '—'}")
    console.print(f"Role:             {g.assigned_to_role or '—'}")
    console.print(
        f"Progress:         {g.current_checkpoint}/{g.total_checkpoints} checkpoints"
    )
    console.print(f"Attempts:         {g.attempts}/{g.max_attempts}")
    console.print(f"LLM calls:        {g.llm_calls_used}")
    console.print(f"Cost:             ${g.cost_usd:.4f}")
    console.print(f"Created:          {g.created_at}")
    console.print(f"Updated:          {g.updated_at}")
    if g.completed_at:
        console.print(f"Completed:        {g.completed_at}")

    checkpoints = await mgr.get_checkpoints(goal_id)
    if checkpoints:
        console.print()
        cp_table = Table(title="Checkpoints", show_header=True)
        cp_table.add_column("#", justify="right", style="cyan")
        cp_table.add_column("Title", style="green")
        cp_table.add_column("Status")
        for cp in checkpoints:
            color = {
                "pending": "yellow",
                "active": "cyan",
                "completed": "green",
                "failed": "red",
            }.get(cp.status, "white")
            cp_table.add_row(str(cp.order), cp.title, f"[{color}]{cp.status}[/{color}]")
        console.print(cp_table)

    if g.context_summary:
        console.print()
        console.print("[dim]Context summary:[/dim]")
        console.print(g.context_summary)


def _report(ok: bool, verb: str, goal_id: str) -> None:
    if ok:
        console.print(f"[green]{verb}[/green] {goal_id}")
    else:
        console.print(f"[red]goal {goal_id!r} not found or not in a valid state[/red]")
