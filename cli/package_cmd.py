"""elophanto package — export and import whole agent configurations.

Commands:
    export  — Bundle skills, plugins, persona, and schedules into a directory
    inspect — Show what a package contains and what it would install
    install — Install a package after showing the plan
    list    — Show installed packages
"""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from core.config import load_config
from core.package import (
    PackageError,
    check_requirements,
    export_package,
    install_package,
    parse_manifest,
)

console = Console()


@click.group()
def package_cmd() -> None:
    """Export and import complete agent configurations."""


@package_cmd.command("export")
@click.argument("name")
@click.option("--to", "destination", default="", help="Output directory.")
@click.option("--version", default="0.1.0", help="Semver version.")
@click.option("--author", default="", help="Package author.")
@click.option("--description", default="", help="One-line description.")
@click.option("--skill", "skills", multiple=True, help="Skill to bundle (repeatable).")
@click.option(
    "--plugin", "plugins", multiple=True, help="Plugin to bundle (repeatable)."
)
@click.option("--persona-file", default="", help="File whose text becomes the persona.")
def export(
    name: str,
    destination: str,
    version: str,
    author: str,
    description: str,
    skills: tuple[str, ...],
    plugins: tuple[str, ...],
    persona_file: str,
) -> None:
    """Bundle an agent configuration into a shareable package."""
    config = load_config()
    out = Path(destination or f"./{name}-package")

    persona = ""
    if persona_file:
        path = Path(persona_file)
        if not path.exists():
            console.print(f"[red]Persona file not found: {path}[/red]")
            raise SystemExit(1)
        persona = path.read_text(encoding="utf-8")

    manifest = export_package(
        out,
        name=name,
        version=version,
        author=author,
        description=description,
        persona=persona,
        skills=list(skills),
        plugins=list(plugins),
        project_root=config.project_root,
    )
    console.print(
        Panel(
            f"Wrote [bold]{manifest}[/bold]\n\n"
            f"Bundled {len(skills)} skill(s) and {len(plugins)} plugin(s).\n"
            "[dim]No credentials were copied — the manifest records which "
            "credential slugs are needed, never their values.[/dim]",
            title="Package exported",
            border_style="green",
        )
    )


@package_cmd.command("inspect")
@click.argument("path")
def inspect(path: str) -> None:
    """Show what a package contains without installing anything."""
    try:
        pkg = parse_manifest(path)
    except PackageError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    missing = _missing_for(pkg)
    console.print(Panel(pkg.render_plan(missing), title="Package", border_style="cyan"))


@package_cmd.command("install")
@click.argument("path")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--dry-run", is_flag=True, help="Show what would happen, change nothing.")
def install(path: str, yes: bool, dry_run: bool) -> None:
    """Install a package after showing exactly what it will do."""
    config = load_config()
    try:
        pkg = parse_manifest(path)
    except PackageError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    missing = _missing_for(pkg)
    console.print(
        Panel(pkg.render_plan(missing), title="Install plan", border_style="cyan")
    )

    if any(missing.values()):
        console.print(
            "[yellow]Some requirements are unmet. The package will install, "
            "but parts of it will not work until you resolve them.[/yellow]"
        )

    if pkg.mcp_servers or pkg.schedules:
        console.print(
            "\n[dim]MCP servers and schedules are listed but NOT applied — both "
            "run code on your machine, so add them yourself with "
            "`elophanto mcp add` and `elophanto schedule` once you have read "
            "what they do.[/dim]"
        )

    if not dry_run and not yes:
        if not Confirm.ask("\nInstall this package?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            return

    report = install_package(pkg, project_root=config.project_root, dry_run=dry_run)
    verb = "Would install" if dry_run else "Installed"
    console.print(
        Panel(
            f"{verb} {len(report['skills_installed'])} skill(s), "
            f"{len(report['plugins_installed'])} plugin(s).",
            title=pkg.name,
            border_style="green",
        )
    )


@package_cmd.command("list")
def list_installed() -> None:
    """Show packages installed into this project."""
    config = load_config()
    record = config.project_root / "data" / "installed_packages.json"
    if not record.exists():
        console.print("[dim]No packages installed.[/dim]")
        return
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
    except Exception as exc:
        console.print(f"[red]Could not read {record}: {exc}[/red]")
        raise SystemExit(1) from exc

    table = Table(title="Installed packages")
    table.add_column("Name", style="cyan")
    table.add_column("Version")
    table.add_column("Author")
    table.add_column("Skills")
    table.add_column("Installed")
    for name, info in data.items():
        table.add_row(
            name,
            info.get("version", "?"),
            info.get("author", "") or "[dim]—[/dim]",
            str(len(info.get("skills", []))),
            (info.get("installed_at", "") or "")[:10],
        )
    console.print(table)


def _missing_for(pkg) -> dict[str, list[str]]:
    """Resolve the live tool and credential sets, then check requirements."""
    config = load_config()
    try:
        from core.registry import ToolRegistry

        registry = ToolRegistry(config.project_root)
        registry.load_builtin_tools(config)
        tools = {t.name for t in registry.all_tools()}
    except Exception:
        tools = None  # type: ignore[assignment]

    credentials = set(getattr(config.credentials, "bindings", {}) or {})
    return check_requirements(
        pkg, available_tools=tools, available_credentials=credentials
    )
