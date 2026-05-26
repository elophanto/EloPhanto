"""CLI for ABE Phase 11 strategy artifacts.

See ``docs/76-ABE-FRAMEWORK.md`` §Phase 11.

Actions:
- ``list``                          — strategy + blocker status per company
- ``show <slug>``                   — print the active strategy.yaml
- ``proposed <slug>``               — list proposed/<timestamp>.yaml files
- ``archive <slug>``                — list archive/<timestamp>.yaml files
- ``capabilities <slug>``           — print capabilities.md
- ``blockers``                      — list across companies
- ``blockers <slug>``               — this company only
- ``blockers resolve <slug> <id> <method>`` — mark a blocker resolved
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from core.config import load_config
from core.strategy import (
    active_path,
    archive_dir,
    load_blockers,
    load_strategy,
    proposed_dir,
    save_blockers,
)

console = Console()


def _company_slugs(project_root: Path) -> list[str]:
    root = project_root / "data" / "companies"
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir())


@click.command("strategy")
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.argument("action", default="list")
@click.argument("arg1", required=False)
@click.argument("arg2", required=False)
@click.argument("arg3", required=False)
@click.argument("arg4", required=False)
def strategy_cmd(
    config_path: str | None,
    action: str,
    arg1: str | None,
    arg2: str | None,
    arg3: str | None,
    arg4: str | None,
) -> None:
    """Manage per-company strategy artifacts (ABE Phase 11)."""
    cfg_path = Path(config_path) if config_path else None
    config = load_config(cfg_path)
    project_root = config.project_root

    if action == "list":
        _list_strategies(project_root, slug_filter=arg1)
    elif action == "show":
        if not arg1:
            console.print("[red]Usage:[/red] elophanto strategy show <slug>")
            return
        _show_strategy(project_root, arg1)
    elif action == "proposed":
        if not arg1:
            console.print("[red]Usage:[/red] elophanto strategy proposed <slug>")
            return
        _list_versions(project_root, arg1, "proposed")
    elif action == "archive":
        if not arg1:
            console.print("[red]Usage:[/red] elophanto strategy archive <slug>")
            return
        _list_versions(project_root, arg1, "archive")
    elif action == "capabilities":
        if not arg1:
            console.print("[red]Usage:[/red] elophanto strategy capabilities <slug>")
            return
        _show_capabilities(project_root, arg1)
    elif action == "blockers":
        if arg1 == "resolve":
            if not arg2 or not arg3:
                console.print(
                    "[red]Usage:[/red] elophanto strategy blockers resolve "
                    "<slug> <id> [method]"
                )
                return
            _resolve_blocker(project_root, arg2, arg3, arg4 or "manual")
        else:
            _list_blockers(project_root, slug_filter=arg1)
    else:
        console.print(f"[red]Unknown action:[/red] {action}")
        console.print("Use: list | show | proposed | archive | capabilities | blockers")


def _list_strategies(project_root: Path, slug_filter: str | None) -> None:
    slugs = _company_slugs(project_root)
    if slug_filter:
        slugs = [s for s in slugs if s == slug_filter]
    if not slugs:
        console.print(
            "[dim]No companies with data dirs yet. Run "
            "`elophanto company onboard ...` first.[/dim]"
        )
        return
    table = Table(title="Strategy status")
    table.add_column("Company", style="cyan")
    table.add_column("Active")
    table.add_column("Proposals")
    table.add_column("Archive")
    table.add_column("Blockers")
    for slug in slugs:
        active = active_path(project_root, slug)
        has_active = active.is_file()
        proposed_count = (
            len(list(proposed_dir(project_root, slug).glob("*.yaml")))
            if proposed_dir(project_root, slug).is_dir()
            else 0
        )
        archive_count = (
            len(list(archive_dir(project_root, slug).glob("*.yaml")))
            if archive_dir(project_root, slug).is_dir()
            else 0
        )
        blockers = load_blockers(project_root, slug)
        unresolved = sum(1 for b in blockers if not b.is_resolved())
        if has_active:
            strat = load_strategy(project_root, slug)
            active_label = (
                f"[green]{strat.strategy_name or 'unnamed'}[/green]"
                if strat
                else "[green]yes[/green]"
            )
        else:
            active_label = "[yellow]none[/yellow]"
        block_label = (
            f"[red]{unresolved}[/red]"
            if unresolved
            else f"[dim]{len(blockers)} (all resolved)[/dim]"
        )
        table.add_row(
            slug,
            active_label,
            str(proposed_count),
            str(archive_count),
            block_label,
        )
    console.print(table)


def _show_strategy(project_root: Path, slug: str) -> None:
    path = active_path(project_root, slug)
    if not path.is_file():
        console.print(
            f"[yellow]No active strategy for {slug}[/yellow] [dim](would live at "
            f"{path})[/dim]"
        )
        prop_dir = proposed_dir(project_root, slug)
        if prop_dir.is_dir() and any(prop_dir.glob("*.yaml")):
            console.print(
                f"[dim]Proposals exist — list with `elophanto strategy "
                f"proposed {slug}`. Activate via `company_plan_apply` "
                f"(MODERATE permission).[/dim]"
            )
        return
    console.print(f"[cyan]{slug}[/cyan] strategy.yaml ({path})")
    console.print(path.read_text(encoding="utf-8"))


def _list_versions(project_root: Path, slug: str, kind: str) -> None:
    target_dir = (
        proposed_dir(project_root, slug)
        if kind == "proposed"
        else archive_dir(project_root, slug)
    )
    if not target_dir.is_dir():
        console.print(f"[dim]No {kind}/ directory yet for {slug}.[/dim]")
        return
    files = sorted(target_dir.glob("*.yaml"))
    if not files:
        console.print(f"[dim]No {kind} strategy versions for {slug}.[/dim]")
        return
    table = Table(title=f"{slug} — {kind} strategy versions")
    table.add_column("Timestamp", style="cyan")
    table.add_column("Path", style="dim")
    for path in files:
        table.add_row(path.stem, str(path))
    console.print(table)


def _show_capabilities(project_root: Path, slug: str) -> None:
    path = project_root / "data" / "companies" / slug / "capabilities.md"
    if not path.is_file():
        console.print(
            f"[yellow]No capabilities.md for {slug}[/yellow] [dim](run "
            f"`company_capabilities` via the agent to generate one)[/dim]"
        )
        return
    console.print(path.read_text(encoding="utf-8"))


def _list_blockers(project_root: Path, slug_filter: str | None) -> None:
    slugs = _company_slugs(project_root)
    if slug_filter:
        slugs = [s for s in slugs if s == slug_filter]
    rows: list[tuple[str, str, str, str, str, str]] = []
    for slug in slugs:
        for b in load_blockers(project_root, slug):
            if b.is_resolved():
                continue
            rows.append(
                (
                    slug,
                    b.id,
                    b.type,
                    b.resolution_proposal,
                    ", ".join(b.affected_tactics) or "—",
                    b.description[:80],
                )
            )
    if not rows:
        if slug_filter:
            console.print(f"[dim]No unresolved blockers for {slug_filter}.[/dim]")
        else:
            console.print("[dim]No unresolved blockers across any company.[/dim]")
        return
    table = Table(title="Unresolved blockers")
    table.add_column("Company", style="cyan")
    table.add_column("ID", style="dim")
    table.add_column("Type")
    table.add_column("Resolution")
    table.add_column("Tactics")
    table.add_column("Description")
    for r in rows:
        table.add_row(*[str(v) for v in r])
    console.print(table)
    console.print(
        "[dim]Resolve with `elophanto strategy blockers resolve "
        "<slug> <id> <method>` once unblocked.[/dim]"
    )


def _resolve_blocker(
    project_root: Path, slug: str, blocker_id: str, method: str
) -> None:
    blockers = load_blockers(project_root, slug)
    matched = next((b for b in blockers if b.id == blocker_id), None)
    if matched is None:
        console.print(f"[red]No such blocker:[/red] {blocker_id} (company {slug})")
        return
    matched.resolved_at = datetime.now(UTC).isoformat()
    matched.resolved_by = "operator"
    matched.resolved_method = method
    save_blockers(project_root, slug, blockers)
    console.print(
        f"[green]Resolved[/green] blocker [dim]{blocker_id}[/dim] for "
        f"[cyan]{slug}[/cyan] (method: {method})"
    )
