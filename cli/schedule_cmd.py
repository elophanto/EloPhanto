"""CLI command for managing scheduled tasks."""

from __future__ import annotations

import asyncio
from typing import Any

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

    Actions: list, status, enable <id>, disable <id>, delete <id>, history <id>

    `status` prints the resource-typed concurrency config and groups
    enabled schedules by inferred resource set, so you can see when
    too many schedules will contend for the same resource (e.g.
    "5 schedules need browser → they'll serialize").
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

    if action == "status":
        await _status_report(db, config)
        return

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
            "[red]Usage: elophanto schedule [list|status|enable|disable|delete|history] [id][/red]"
        )

    await db.close()


async def _status_report(db: Database, config: Any) -> None:
    """Print resource-typed concurrency config + per-resource schedule
    grouping. Live queue depth requires a running daemon and lives in
    the dashboard / log stream — this is the static report."""
    from rich.panel import Panel

    from core.task_resources import infer_resources

    sched = config.scheduler
    cap_panel = (
        f"[bold]max_concurrent_tasks[/bold]   {sched.max_concurrent_tasks}\n"
        f"[bold]llm_burst_capacity[/bold]    {sched.llm_burst_capacity}\n"
        f"[bold]queue_depth_cap[/bold]        {sched.queue_depth_cap}\n"
        f"[bold]task_timeout_seconds[/bold]   {sched.task_timeout_seconds}\n"
        f"[bold]default_max_retries[/bold]    {sched.default_max_retries}"
    )
    console.print(Panel(cap_panel, title="Scheduler concurrency config"))

    rows = await db.execute(
        "SELECT id, name, cron_expression, task_goal, enabled "
        "FROM scheduled_tasks ORDER BY created_at"
    )
    enabled_rows = [r for r in rows if r["enabled"]]
    if not enabled_rows:
        console.print("[dim]No enabled schedules.[/dim]")
        return

    # Group by inferred-resource fingerprint (sorted tuple of resource
    # values), so the operator sees at a glance which schedules will
    # contend for the same locks.
    by_resource: dict[tuple[str, ...], list[Any]] = {}
    for row in enabled_rows:
        resources = infer_resources(row["task_goal"] or "")
        key = tuple(sorted(r.value for r in resources))
        by_resource.setdefault(key, []).append(row)

    table = Table(title="Enabled schedules grouped by inferred resources")
    table.add_column("Resources", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("Schedules", style="dim")
    for resources_key, group in sorted(by_resource.items(), key=lambda kv: -len(kv[1])):
        names = ", ".join(r["name"] for r in group)
        table.add_row(", ".join(resources_key), str(len(group)), names)
    console.print(table)

    # Surface oversubscription warnings — multiple schedules contending
    # for a hard-1-capacity resource will serialize through the queue.
    warnings: list[str] = []
    browser_count = sum(
        1 for k, group in by_resource.items() if "browser" in k for _ in group
    )
    desktop_count = sum(
        1 for k, group in by_resource.items() if "desktop" in k for _ in group
    )
    if browser_count > 1:
        warnings.append(
            f"[yellow]⚠[/yellow]  {browser_count} schedules need the browser "
            f"(capacity 1). They will serialize."
        )
    if desktop_count > 1:
        warnings.append(
            f"[yellow]⚠[/yellow]  {desktop_count} schedules need the desktop "
            f"(capacity 1). They will serialize."
        )
    llm_count = len(enabled_rows)
    if llm_count > sched.llm_burst_capacity:
        warnings.append(
            f"[yellow]⚠[/yellow]  {llm_count} enabled schedules vs "
            f"llm_burst_capacity={sched.llm_burst_capacity}. Some LLM "
            f"work will queue."
        )
    if warnings:
        console.print()
        for w in warnings:
            console.print(w)
