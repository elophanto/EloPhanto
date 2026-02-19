"""elophanto skills — install, list, and manage skills."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from core.skills import SkillManager

console = Console()


def _get_manager() -> SkillManager:
    from core.skills import SkillManager

    skills_dir = Path.cwd() / "skills"
    mgr = SkillManager(skills_dir)
    mgr.discover()
    return mgr


@click.group()
def skills_cmd() -> None:
    """Manage EloPhanto skills."""


@skills_cmd.command("list")
def list_skills() -> None:
    """List all available skills."""
    mgr = _get_manager()
    skills = mgr.list_skills()

    if not skills:
        console.print("[dim]No skills found in skills/ directory.[/dim]")
        return

    table = Table(title=f"Skills ({len(skills)})")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Triggers", style="dim")

    for skill in skills:
        triggers = ", ".join(skill.triggers[:4])
        if len(skill.triggers) > 4:
            triggers += f" (+{len(skill.triggers) - 4})"
        table.add_row(skill.name, skill.description[:60], triggers)

    console.print(table)


@skills_cmd.command("read")
@click.argument("name")
def read_skill(name: str) -> None:
    """Read a skill's SKILL.md content."""
    mgr = _get_manager()
    content = mgr.read_skill(name)

    if content is None:
        console.print(f"[red]Skill '{name}' not found.[/red]")
        available = [s.name for s in mgr.list_skills()]
        if available:
            console.print(f"[dim]Available: {', '.join(available)}[/dim]")
        return

    from rich.markdown import Markdown

    console.print(Markdown(content))


@skills_cmd.command("install")
@click.argument("source")
@click.option("--name", default=None, help="Override the skill name")
def install_skill(source: str, name: str | None) -> None:
    """Install a skill from a local path or git repo URL.

    SOURCE can be:
    - A local directory path containing SKILL.md
    - A git repo URL (https://github.com/user/repo)
    - A git repo with subdirectory (https://github.com/user/repo/tree/main/skills/my-skill)
    """
    mgr = _get_manager()

    source_path = Path(source)
    if source_path.exists() and source_path.is_dir():
        try:
            installed = mgr.install_from_directory(source_path, name)
            console.print(f"[green]Installed skill: {installed}[/green]")
        except Exception as e:
            console.print(f"[red]Failed to install: {e}[/red]")
        return

    if source.startswith("http") and "github.com" in source:
        _install_from_git(mgr, source, name)
        return

    console.print(f"[red]Source not found: {source}[/red]")
    console.print("[dim]Provide a local directory path or a GitHub repo URL.[/dim]")


@skills_cmd.command("remove")
@click.argument("name")
def remove_skill(name: str) -> None:
    """Remove an installed skill."""
    mgr = _get_manager()

    if not mgr.get_skill(name):
        console.print(f"[red]Skill '{name}' not found.[/red]")
        return

    if mgr.remove_skill(name):
        console.print(f"[green]Removed skill: {name}[/green]")
    else:
        console.print(f"[red]Failed to remove skill: {name}[/red]")


# ── Hub subcommands ──────────────────────────────────────────


@skills_cmd.group("hub")
def hub_group() -> None:
    """EloPhantoHub — search and install skills from the registry."""


@hub_group.command("search")
@click.argument("query")
def hub_search(query: str) -> None:
    """Search EloPhantoHub for skills matching a query."""
    import asyncio

    asyncio.run(_hub_search(query))


async def _hub_search(query: str) -> None:
    from core.config import load_config
    from core.hub import HubClient

    cfg = load_config()
    skills_dir = cfg.project_root / "skills"
    hub = HubClient(
        skills_dir=skills_dir,
        index_url=cfg.hub.index_url,
        cache_ttl_hours=cfg.hub.cache_ttl_hours,
    )

    results = await hub.search(query)

    if not results:
        console.print(f"[dim]No skills found for '{query}'.[/dim]")
        return

    table = Table(title=f"EloPhantoHub Results ({len(results)})")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Version", style="dim")
    table.add_column("Tags", style="dim")

    for skill in results:
        tags = ", ".join(skill.tags[:3])
        table.add_row(skill.name, skill.description[:60], skill.version, tags)

    console.print(table)
    console.print("\n[dim]Install with:[/dim] [bold]elophanto skills hub install <name>[/bold]")


@hub_group.command("install")
@click.argument("name")
def hub_install(name: str) -> None:
    """Install a skill from EloPhantoHub."""
    import asyncio

    asyncio.run(_hub_install(name))


async def _hub_install(name: str) -> None:
    from core.config import load_config
    from core.hub import HubClient

    cfg = load_config()
    skills_dir = cfg.project_root / "skills"
    hub = HubClient(
        skills_dir=skills_dir,
        index_url=cfg.hub.index_url,
        cache_ttl_hours=cfg.hub.cache_ttl_hours,
    )

    try:
        installed = await hub.install(name)
        console.print(f"[green]Installed skill: {installed}[/green]")
    except FileExistsError:
        console.print(f"[yellow]Skill '{name}' is already installed.[/yellow]")
    except Exception as e:
        console.print(f"[red]Failed to install: {e}[/red]")


@hub_group.command("update")
@click.argument("name", required=False, default=None)
def hub_update(name: str | None) -> None:
    """Update hub-installed skills. Omit name to update all."""
    import asyncio

    asyncio.run(_hub_update(name))


async def _hub_update(name: str | None) -> None:
    from core.config import load_config
    from core.hub import HubClient

    cfg = load_config()
    skills_dir = cfg.project_root / "skills"
    hub = HubClient(
        skills_dir=skills_dir,
        index_url=cfg.hub.index_url,
        cache_ttl_hours=cfg.hub.cache_ttl_hours,
    )

    updated = await hub.update(name)
    if updated:
        for n in updated:
            console.print(f"  [green]Updated: {n}[/green]")
        console.print(f"[green]Updated {len(updated)} skill(s).[/green]")
    else:
        console.print("[dim]All skills are up to date.[/dim]")


@hub_group.command("list")
def hub_list() -> None:
    """List skills installed from EloPhantoHub."""
    from core.config import load_config
    from core.hub import HubClient

    cfg = load_config()
    skills_dir = cfg.project_root / "skills"
    hub = HubClient(
        skills_dir=skills_dir,
        index_url=cfg.hub.index_url,
        cache_ttl_hours=cfg.hub.cache_ttl_hours,
    )

    installed = hub.list_installed()
    if not installed:
        console.print("[dim]No skills installed from EloPhantoHub.[/dim]")
        return

    table = Table(title="Hub-Installed Skills")
    table.add_column("Name", style="cyan")
    table.add_column("Version", style="dim")

    for s in installed:
        table.add_row(s["name"], s["version"])

    console.print(table)


# ── Git install helper ──────────────────────────────────────


def _install_from_git(mgr: SkillManager, url: str, name: str | None) -> None:
    """Clone a git repo and install the skill from it."""
    # Handle GitHub URLs with /tree/main/skills/name paths
    parts = url.split("/tree/")
    repo_url = parts[0]
    subdir = parts[1].split("/", 1)[1] if len(parts) > 1 and "/" in parts[1] else None

    if not repo_url.endswith(".git"):
        repo_url += ".git"

    with tempfile.TemporaryDirectory() as tmpdir:
        console.print(f"[dim]Cloning {repo_url}...[/dim]")
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, tmpdir],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                console.print(f"[red]Git clone failed: {result.stderr}[/red]")
                return
        except Exception as e:
            console.print(f"[red]Git clone failed: {e}[/red]")
            return

        source_dir = Path(tmpdir)
        if subdir:
            source_dir = source_dir / subdir

        # Check if it's a single skill (has SKILL.md) or a collection
        if (source_dir / "SKILL.md").exists():
            try:
                skill_name = name or source_dir.name
                installed = mgr.install_from_directory(source_dir, skill_name)
                console.print(f"[green]Installed skill: {installed}[/green]")
            except Exception as e:
                console.print(f"[red]Failed to install: {e}[/red]")
        else:
            # Look for subdirectories with SKILL.md (skill collection)
            count = 0
            for entry in sorted(source_dir.iterdir()):
                if entry.is_dir() and (entry / "SKILL.md").exists():
                    try:
                        installed = mgr.install_from_directory(entry)
                        console.print(f"  [green]Installed: {installed}[/green]")
                        count += 1
                    except FileExistsError:
                        console.print(f"  [yellow]Skipped (exists): {entry.name}[/yellow]")
                    except Exception as e:
                        console.print(f"  [red]Failed {entry.name}: {e}[/red]")

            if count == 0:
                console.print("[red]No skills found in the repository.[/red]")
            else:
                console.print(f"[green]Installed {count} skill(s).[/green]")
