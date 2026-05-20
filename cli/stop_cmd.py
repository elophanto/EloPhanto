"""``elophanto stop`` + ``elophanto resume`` — operator kill switch.

When a runaway agent.run() / mind cycle / scheduled task can't be
interrupted from inside the agent process, the operator needs a
brake pedal that works from any terminal. This module provides it
via a sentinel file at ``<data_dir>/STOP``.

While the sentinel exists:

  - ``Agent._run_with_history`` checks it between rounds and breaks
    out at the next safe checkpoint (no mid-tool-call interruption).
  - ``AutonomousMind._run_loop`` skips each wakeup without thinking
    or burning LLM budget.
  - ``TaskScheduler._run_one`` skips dispatch.

``elophanto resume`` removes the file; the next mind wakeup and
scheduler tick pick up where they were.

Optional flags:

  - ``--cancel-goals`` — also flip every ``active`` / ``planning``
    goal in the DB to ``cancelled`` so the GoalRunner doesn't pick
    them back up on resume.
  - ``--cancel-schedules`` — disable every cron schedule. Operator
    re-enables manually via ``elophanto schedule enable <id>``.
  - ``--hard`` — both of the above.

This is intentionally simple. No gateway round-trip, no in-process
signal. A file the agent polls is the most reliable kill switch
because it survives across restarts, doesn't require the gateway
to be healthy, and is trivially recoverable (``rm data/STOP``).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console

from core.config import load_config
from core.database import Database

console = Console()


def _stop_file_path(config_path: str | None) -> Path:
    cfg = load_config(config_path)
    data_dir = Path(cfg.database.db_path).parent
    if not data_dir.is_absolute():
        data_dir = cfg.project_root / data_dir
    # Tolerate legacy configs where db_path is just "data/elophanto.db".
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "STOP"


@click.command("stop")
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.option(
    "--cancel-goals",
    is_flag=True,
    help="Also cancel every active/planning goal in the DB.",
)
@click.option(
    "--cancel-schedules",
    is_flag=True,
    help="Also disable every enabled cron schedule.",
)
@click.option(
    "--hard",
    is_flag=True,
    help="Shortcut for --cancel-goals --cancel-schedules.",
)
def stop_cmd(
    config_path: str | None,
    cancel_goals: bool,
    cancel_schedules: bool,
    hard: bool,
) -> None:
    """Halt the autonomous mind, scheduler, and current agent.run loops.

    Writes a sentinel file the agent's in-process loops poll. They
    halt at their next safe checkpoint (between rounds, between
    wakeups, before scheduler dispatch).

    Use --hard when you suspect the goal queue or cron schedules are
    the root cause of a runaway state — it disables both so they
    don't come back when you resume.
    """
    if hard:
        cancel_goals = True
        cancel_schedules = True

    stop_path = _stop_file_path(config_path)
    if stop_path.exists():
        console.print(f"[yellow]Already stopped (sentinel at {stop_path})[/yellow]")
    else:
        stop_path.write_text(
            "Created by `elophanto stop`. Remove with `elophanto resume`.\n"
        )
        console.print(f"[green]✓[/green] STOP sentinel written: {stop_path}")
        console.print(
            "  Mind, scheduler, and agent.run loops will halt at their "
            "next safe checkpoint."
        )

    if cancel_goals or cancel_schedules:
        asyncio.run(_do_db_cancels(config_path, cancel_goals, cancel_schedules))

    console.print(
        "\n[dim]Run [bold]elophanto resume[/bold] to clear the sentinel.[/dim]"
    )


@click.command("resume")
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
def resume_cmd(config_path: str | None) -> None:
    """Clear the STOP sentinel — mind and scheduler tick again on their
    next cycle. Does NOT auto-resume cancelled goals or re-enable
    disabled schedules (those require explicit operator action so a
    careless resume doesn't restart the same runaway state)."""
    stop_path = _stop_file_path(config_path)
    if not stop_path.exists():
        console.print("[dim]No STOP sentinel — nothing to clear.[/dim]")
        return
    stop_path.unlink()
    console.print(f"[green]✓[/green] STOP sentinel removed: {stop_path}")
    console.print(
        "  Mind will think on its next wakeup; scheduler will dispatch "
        "queued / cron-fired tasks."
    )


async def _do_db_cancels(
    config_path: str | None, cancel_goals: bool, cancel_schedules: bool
) -> None:
    cfg = load_config(config_path)
    db_path = Path(cfg.database.db_path)
    if not db_path.is_absolute():
        db_path = cfg.project_root / db_path
    db = Database(db_path)
    await db.initialize()

    if cancel_goals:
        # active + planning are the running-or-runnable states.
        # paused/cancelled/completed/failed are already terminal.
        rows = await db.execute(
            "SELECT goal_id FROM goals WHERE status IN ('active', 'planning')"
        )
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        for r in rows:
            await db.execute_insert(
                "UPDATE goals SET status='cancelled', updated_at=? " "WHERE goal_id=?",
                (now, r["goal_id"]),
            )
        console.print(f"[green]✓[/green] cancelled {len(rows)} active/planning goal(s)")

    if cancel_schedules:
        rows = await db.execute("SELECT id FROM scheduled_tasks WHERE enabled=1")
        for r in rows:
            await db.execute_insert(
                "UPDATE scheduled_tasks SET enabled=0 WHERE id=?",
                (r["id"],),
            )
        console.print(f"[green]✓[/green] disabled {len(rows)} enabled schedule(s)")
