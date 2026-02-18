"""CLI command for managing scheduled tasks."""

from __future__ import annotations

import asyncio

import click
from rich.console import Console
from rich.table import Table

from core.config import load_config
from core.database import Database

console = Console()


@click.command("schedule")
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.argument("action", default="list")
@click.argument("schedule_id", required=False)
def schedule_cmd(config_path: str | None, action: str, schedule_id: str | None) -> None:
    """Manage scheduled tasks.

    Actions: list, enable <id>, disable <id>, delete <id>, history <id>
    """
    asyncio.run(_schedule_action(config_path, action, schedule_id))


async def _schedule_action(
    config_path: str | None, action: str, schedule_id: str | None
) -> None:
    config = load_config(config_path)
    from pathlib import Path

    db_path = Path(config.database.db_path)
    if not db_path.is_absolute():
        db_path = config.project_root / db_path

    db = Database(db_path)
    await db.initialize()

    if action == "list":
        rows = await db.execute("SELECT * FROM scheduled_tasks ORDER BY created_at")
        if not rows:
            console.print("[dim]No scheduled tasks.[/dim]")
            return

        table = Table(title="Scheduled Tasks")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Schedule", style="yellow")
        table.add_column("Enabled", style="bold")
        table.add_column("Last Status")
        table.add_column("Last Run")

        for row in rows:
            enabled = "Yes" if row["enabled"] else "No"
            table.add_row(
                row["id"],
                row["name"],
                row["cron_expression"],
                enabled,
                row["last_status"] or "never",
                row["last_run_at"] or "never",
            )

        console.print(table)

    elif action == "history" and schedule_id:
        rows = await db.execute(
            """SELECT * FROM schedule_runs
               WHERE schedule_id = ?
               ORDER BY started_at DESC LIMIT 10""",
            (schedule_id,),
        )
        if not rows:
            console.print("[dim]No run history.[/dim]")
            return

        table = Table(title=f"Run History — {schedule_id}")
        table.add_column("Started", style="cyan")
        table.add_column("Status", style="bold")
        table.add_column("Steps")
        table.add_column("Result")

        for row in rows:
            result = (row["result"] or "")[:60]
            table.add_row(
                row["started_at"],
                row["status"],
                str(row["steps_taken"]),
                result,
            )

        console.print(table)

    elif action in ("enable", "disable", "delete") and schedule_id:
        if action == "enable":
            await db.execute_insert(
                "UPDATE scheduled_tasks SET enabled = 1 WHERE id = ?",
                (schedule_id,),
            )
            console.print(f"[green]Schedule {schedule_id} enabled.[/green]")
        elif action == "disable":
            await db.execute_insert(
                "UPDATE scheduled_tasks SET enabled = 0 WHERE id = ?",
                (schedule_id,),
            )
            console.print(f"[yellow]Schedule {schedule_id} disabled.[/yellow]")
        elif action == "delete":
            await db.execute_insert(
                "DELETE FROM schedule_runs WHERE schedule_id = ?",
                (schedule_id,),
            )
            await db.execute_insert(
                "DELETE FROM scheduled_tasks WHERE id = ?",
                (schedule_id,),
            )
            console.print(f"[red]Schedule {schedule_id} deleted.[/red]")
    else:
        console.print(
            "[red]Usage: elophanto schedule [list|enable|disable|delete|history] [id][/red]"
        )

    await db.close()
