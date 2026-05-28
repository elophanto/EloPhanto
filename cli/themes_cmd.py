"""CLI for managing dashboard themes.

  elophanto themes list                 — show all discoverable themes
  elophanto themes show <name>          — print the resolved theme (after extends)
  elophanto themes validate <path>      — validate a file without installing it
  elophanto themes init <name>          — write a starter template to ~/.elophanto/themes/

Themes are YAML files. Search order: project → user → built-in.
See ``docs/79-DASHBOARD-THEMES.md`` for the schema.
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from cli.dashboard.theme import (
    ThemeError,
    list_themes,
    load_theme,
    validate_theme_file,
)

console = Console()


_STARTER_TEMPLATE = """\
# {name} — dashboard theme.
#
# Validate with `elophanto themes validate {path}` before reloading
# the dashboard. Apply with `elophanto chat --theme {name}` or set
# `dashboard.theme: {name}` in config.yaml.

name: {name}
description: "Describe your theme here"
extends: default   # inherit defaults; override only the keys below

colors:
  # Uncomment + override any color from the default. Removing the
  # `extends: default` line above means you must spell out ALL keys.
  # accent: "#7c3aed"
  # background: "#f9f8f4"

layout:
  # Re-order or hide panels. Removing the block inherits the default
  # layout via extends.
  # sidebar: [mascot, agent, mind, goals, companies, swarm,
  #           scheduler, approvals, gateway, footer]
  panels:
    # reasoning:
    #   default_size: small
    # mascot:
    #   hidden: false
"""


@click.group("themes")
def themes_cmd() -> None:
    """Manage dashboard themes (list / show / validate / init)."""


@themes_cmd.command("list")
def list_cmd() -> None:
    """Show all discoverable themes (project > user > built-in)."""
    themes = list_themes(project_root=Path.cwd())
    if not themes:
        console.print("[dim]No themes found.[/dim]")
        return

    table = Table(title="Available dashboard themes", show_header=True)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Description")
    table.add_column("Source", style="dim")

    for name, path in sorted(themes.items()):
        try:
            t = load_theme(name, project_root=Path.cwd())
            desc = t.description or "—"
        except ThemeError as e:
            desc = f"[red](broken: {e})[/red]"
        # Source label — short, points at the right tree
        source_label = _source_label(path)
        table.add_row(name, desc, source_label)

    console.print(table)
    console.print(
        "[dim]Apply with `--theme <name>` or `dashboard.theme: <name>` "
        "in config.yaml.[/dim]"
    )


@themes_cmd.command("show")
@click.argument("name")
def show_cmd(name: str) -> None:
    """Print the loaded theme YAML (with `extends:` chain resolved)."""
    try:
        theme = load_theme(name, project_root=Path.cwd())
    except ThemeError as e:
        console.print(f"[red]Failed to load theme {name!r}:[/red] {e}")
        raise SystemExit(1) from None

    console.print(f"[bold]{theme.name}[/bold]  [dim]({theme.source_path})[/dim]")
    if theme.description:
        console.print(f"[dim]{theme.description}[/dim]")
    if theme.extends:
        console.print(f"[dim]extends: {theme.extends}[/dim]")
    console.print()

    # Colors table
    color_table = Table(title="colors", show_header=False, box=None, padding=(0, 2))
    color_table.add_column(style="cyan")
    color_table.add_column()
    for field in (
        "background",
        "surface",
        "raised",
        "border",
        "foreground",
        "bright",
        "muted",
        "placeholder",
        "accent",
        "accent_alt",
        "success",
        "warning",
        "error",
        "info",
    ):
        value = getattr(theme.colors, field)
        color_table.add_row(field, f"[{value}]{value}[/{value}]")
    console.print(color_table)

    # Layout
    console.print()
    console.print(
        f"[bold]layout[/bold]  [dim](sidebar_width={theme.layout.sidebar_width})[/dim]"
    )
    console.print(f"  [cyan]sidebar:[/cyan]  {list(theme.layout.sidebar)}")
    console.print(f"  [cyan]main:[/cyan]     {list(theme.layout.main)}")
    if theme.layout.panels:
        console.print("  [cyan]panels:[/cyan]")
        for pname, opts in theme.layout.panels.items():
            console.print(
                f"    {pname}: default_size={opts.default_size}, hidden={opts.hidden}"
            )


@themes_cmd.command("validate")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def validate_cmd(path: Path) -> None:
    """Validate a theme YAML file without installing it."""
    try:
        theme = validate_theme_file(path)
    except ThemeError as e:
        console.print(f"[red]Invalid theme:[/red] {e}")
        raise SystemExit(1) from None
    console.print(f"[green]✓ valid[/green]  {theme.name} — {path}")
    if theme.description:
        console.print(f"[dim]{theme.description}[/dim]")


@themes_cmd.command("init")
@click.argument("name")
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite an existing user-themes file by the same name.",
)
def init_cmd(name: str, force: bool) -> None:
    """Write a starter theme template to ~/.elophanto/themes/<name>.yaml.

    The template extends `default`, so it only needs to declare the
    color/layout fields you actually want to change.
    """
    target_dir = Path.home() / ".elophanto" / "themes"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{name}.yaml"
    if target.exists() and not force:
        console.print(
            f"[yellow]{target} already exists.[/yellow] "
            f"Re-run with `--force` to overwrite."
        )
        raise SystemExit(1)
    target.write_text(_STARTER_TEMPLATE.format(name=name, path=str(target)))
    console.print(f"[green]wrote[/green] {target}")
    console.print("[dim]Edit it, then validate with:[/dim]")
    console.print(f"  elophanto themes validate {target}")
    console.print("[dim]Apply with:[/dim]")
    console.print(f"  elophanto chat --theme {name}")


def _source_label(path: Path) -> str:
    """Short label saying where a theme came from."""
    p_str = str(path)
    if "/site-packages/" in p_str or "/cli/dashboard/themes/" in p_str:
        return "built-in"
    if str(Path.home()) in p_str:
        return f"~/{path.relative_to(Path.home())}"
    return p_str


# Also re-export sub-render for show_cmd's "print the YAML literally" path.
def _print_yaml(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    console.print(Syntax(text, "yaml", line_numbers=True))
