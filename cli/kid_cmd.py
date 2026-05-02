"""elophanto kid — kid-agent admin commands (build, list, destroy).

The runtime spawn/exec live as agent tools (`kid_spawn`, `kid_exec`...)
because they're invoked through conversation. This CLI is the
human-facing admin surface — building the kid image, listing kids
across processes, force-destroying.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group(invoke_without_command=False)
def kid_cmd() -> None:
    """Kid-agent administration."""


@kid_cmd.command("build")
@click.option(
    "--tag",
    default="elophanto-kid:latest",
    show_default=True,
    help="Image tag to build.",
)
@click.option(
    "--no-cache",
    is_flag=True,
    help="Pass --no-cache to docker build.",
)
def build_cmd(tag: str, no_cache: bool) -> None:
    """Build the kid container image from Dockerfile.kid."""
    project_root = Path(__file__).parent.parent
    dockerfile = project_root / "Dockerfile.kid"
    if not dockerfile.exists():
        console.print(f"[red]Dockerfile.kid not found at {dockerfile}[/red]")
        raise SystemExit(1)

    docker_bin = shutil.which("docker") or shutil.which("podman")
    if not docker_bin:
        console.print(
            "[red]Neither docker nor podman is installed.[/red]\n"
            "On macOS:  brew install colima docker && colima start\n"
            "On Linux:  curl -fsSL https://get.docker.com | sh"
        )
        raise SystemExit(1)

    cmd = [docker_bin, "build", "-f", str(dockerfile), "-t", tag]
    if no_cache:
        cmd.append("--no-cache")
    cmd.append(str(project_root))

    console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
    rc = subprocess.call(cmd)
    if rc != 0:
        console.print(f"[red]Build failed (exit {rc}).[/red]")
        raise SystemExit(rc)
    console.print(f"[green]Built {tag} successfully.[/green]")


@kid_cmd.command("list")
def list_cmd() -> None:
    """List kids known to the local EloPhanto database."""
    from core.config import load_config
    from core.database import Database

    async def _run() -> None:
        cfg = load_config("config.yaml")
        db = Database(cfg.project_root / "data" / "elophanto.db")
        await db.initialize()
        try:
            rows = await db.execute(
                "SELECT kid_id, name, runtime, image, status, "
                "spawned_at, completed_at FROM kid_agents "
                "ORDER BY spawned_at DESC LIMIT 50"
            )
        finally:
            await db.close()

        if not rows:
            console.print("[dim]No kids found.[/dim]")
            return

        table = Table(title="Kid agents", show_lines=False)
        table.add_column("kid_id", style="cyan")
        table.add_column("name")
        table.add_column("runtime")
        table.add_column("status")
        table.add_column("spawned")
        for r in rows:
            table.add_row(
                r["kid_id"],
                r["name"] or "",
                r["runtime"] or "",
                r["status"] or "",
                (r["spawned_at"] or "")[:19],
            )
        console.print(table)

    asyncio.run(_run())


@kid_cmd.command("destroy")
@click.argument("kid_id_or_name")
@click.option("--reason", default="cli", help="Reason recorded in metadata.")
def destroy_cmd(kid_id_or_name: str, reason: str) -> None:
    """Force-destroy a kid by id or name (CLI escape hatch)."""
    from core.config import load_config
    from core.database import Database
    from core.kid_manager import KidManager

    async def _run() -> None:
        cfg = load_config("config.yaml")
        db = Database(cfg.project_root / "data" / "elophanto.db")
        await db.initialize()
        try:
            mgr = KidManager(db=db, config=cfg.kids)
            await mgr.start()
            try:
                ok = await mgr.destroy(kid_id_or_name, reason=reason)
                if ok:
                    console.print(f"[green]Destroyed {kid_id_or_name}.[/green]")
                else:
                    console.print(f"[yellow]No kid named {kid_id_or_name!r}.[/yellow]")
            finally:
                await mgr.stop()
        finally:
            await db.close()

    asyncio.run(_run())
