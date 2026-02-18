"""elophanto rollback — list and revert self-modification commits."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import click
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

console = Console()

_ALLOWED_PREFIXES = ("[self-modify]", "[self-create-plugin]")


@click.command()
@click.option("--list", "list_only", is_flag=True, help="List revertible commits")
@click.option(
    "--commit", "commit_hash", type=str, default=None, help="Commit hash to revert"
)
def rollback_cmd(list_only: bool, commit_hash: str | None) -> None:
    """List or revert self-modification commits."""
    project_root = Path.cwd()

    # Get revertible commits
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-50"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines = result.stdout.strip().splitlines()
    except Exception as e:
        console.print(f"[red]Failed to read git log: {e}[/red]")
        return

    revertible: list[tuple[str, str]] = []
    for line in lines:
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        h, msg = parts
        if any(msg.startswith(p) for p in _ALLOWED_PREFIXES):
            revertible.append((h, msg))

    if not revertible:
        console.print("[dim]No self-modification commits found.[/dim]")
        return

    if list_only or commit_hash is None:
        table = Table(title="Revertible Self-Modification Commits")
        table.add_column("#", style="dim")
        table.add_column("Hash", style="cyan")
        table.add_column("Message")
        for i, (h, msg) in enumerate(revertible, 1):
            table.add_row(str(i), h, msg)
        console.print(table)

        if commit_hash is None and not list_only:
            choice = Prompt.ask(
                "Enter commit # to revert (or 'q' to cancel)",
                default="q",
            )
            if choice.lower() == "q":
                return
            try:
                idx = int(choice) - 1
                commit_hash = revertible[idx][0]
            except (ValueError, IndexError):
                console.print("[red]Invalid selection.[/red]")
                return

    if commit_hash is None:
        return

    if not Confirm.ask(f"Revert commit [cyan]{commit_hash}[/cyan]?", default=False):
        console.print("[dim]Cancelled.[/dim]")
        return

    try:
        result = subprocess.run(
            ["git", "revert", "--no-edit", commit_hash],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            console.print(f"[red]Revert failed: {result.stderr}[/red]")
            return
        console.print(f"[green]Reverted commit {commit_hash}.[/green]")
    except Exception as e:
        console.print(f"[red]Revert failed: {e}[/red]")
        return

    # Run tests
    console.print("[dim]Running tests...[/dim]")
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/", "-v", "--tb=short"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            console.print("[green]All tests passed after rollback.[/green]")
        else:
            console.print("[yellow]Some tests failed after rollback:[/yellow]")
            console.print(result.stdout[-500:])
    except Exception as e:
        console.print(f"[yellow]Could not run tests: {e}[/yellow]")
