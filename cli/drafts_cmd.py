"""CLI for managing outreach drafts (ABE Phase 9).

See ``docs/76-ABE-FRAMEWORK.md`` §Phase 9. Drafts live under
``companies/<slug>/drafts/<kind>/{pending,approved,rejected}/``
as Markdown the operator can read in any tool.

Actions:
- ``list [slug]``            — show pending drafts for one or all companies
- ``show <draft_id>``        — print one draft's contents
- ``approve <draft_id> [note]``  — move pending → approved
- ``reject <draft_id> <reason>`` — move pending → rejected
- ``trust set <slug> <state>``   — promote/demote company trust state
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from core.config import load_config

console = Console()


def _drafts_root(project_root: Path) -> Path:
    return project_root / "companies"


def _iter_pending(project_root: Path, slug_filter: str | None = None):
    """Yield (company_slug, kind, draft_path) for every pending draft."""
    root = _drafts_root(project_root)
    if not root.is_dir():
        return
    for company_dir in sorted(root.iterdir()):
        if not company_dir.is_dir():
            continue
        if slug_filter and company_dir.name != slug_filter:
            continue
        drafts_dir = company_dir / "drafts"
        if not drafts_dir.is_dir():
            continue
        for kind_dir in sorted(drafts_dir.iterdir()):
            pending = kind_dir / "pending"
            if not pending.is_dir():
                continue
            for path in sorted(pending.glob("*.md")):
                yield company_dir.name, kind_dir.name, path


def _find_draft(project_root: Path, draft_id: str) -> tuple[Path, str, str] | None:
    """Locate a draft by id across all companies + kinds. Returns
    (path, company, kind) or None. Mirrors the helper in
    tools/drafts/draft_tools.py — kept in sync by hand for now."""
    for company, kind, path in _iter_pending(project_root):
        if path.stem == draft_id:
            return path, company, kind
    return None


@click.command("drafts")
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.argument("action", default="list")
@click.argument("arg1", required=False)
@click.argument("arg2", required=False)
def drafts_cmd(
    config_path: str | None,
    action: str,
    arg1: str | None,
    arg2: str | None,
) -> None:
    """Manage outreach drafts (ABE Phase 9). Default action: list."""
    cfg_path = Path(config_path) if config_path else None
    config = load_config(cfg_path)
    project_root = config.project_root

    if action == "list":
        _list_drafts(project_root, slug_filter=arg1)
    elif action == "show":
        if not arg1:
            console.print("[red]Usage:[/red] elophanto drafts show <draft_id>")
            return
        _show_draft(project_root, arg1)
    elif action == "approve":
        if not arg1:
            console.print(
                "[red]Usage:[/red] elophanto drafts approve <draft_id> [note]"
            )
            return
        _resolve_draft(project_root, arg1, "approved", arg2)
    elif action == "reject":
        if not arg1 or not arg2:
            console.print(
                "[red]Usage:[/red] elophanto drafts reject <draft_id> <reason>"
            )
            return
        _resolve_draft(project_root, arg1, "rejected", arg2)
    else:
        console.print(f"[red]Unknown action:[/red] {action}")
        console.print("Use: list | show | approve | reject")


def _list_drafts(project_root: Path, slug_filter: str | None) -> None:
    rows = list(_iter_pending(project_root, slug_filter))
    if not rows:
        if slug_filter:
            console.print(f"[dim]No pending drafts for {slug_filter}.[/dim]")
        else:
            console.print("[dim]No pending drafts across any company.[/dim]")
        return

    table = Table(title="Pending drafts")
    table.add_column("Company", style="cyan")
    table.add_column("Kind")
    table.add_column("Draft ID", style="dim")
    table.add_column("Title")
    table.add_column("Age")
    now = datetime.now(UTC)
    for company, kind, path in rows:
        title = _read_title(path)
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            age_h = (now - mtime).total_seconds() / 3600.0
            age = f"{age_h:.1f}h"
        except OSError:
            age = "?"
        table.add_row(company, kind, path.stem, title, age)
    console.print(table)
    console.print(
        f"[dim]{len(rows)} pending. Run "
        f"`elophanto drafts approve <draft_id>` to approve.[/dim]"
    )


def _read_title(path: Path) -> str:
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        # Strip leading `# Foo draft — `
        return first_line.replace("# ", "")[:60]
    except OSError:
        return "(unreadable)"


def _show_draft(project_root: Path, draft_id: str) -> None:
    # Check pending + resolved
    found = _find_draft(project_root, draft_id)
    if found is None:
        # Look in approved/rejected
        for company_dir in _drafts_root(project_root).iterdir():
            if not company_dir.is_dir():
                continue
            for status in ("approved", "rejected"):
                for path in company_dir.glob(f"drafts/*/{status}/{draft_id}.md"):
                    console.print(
                        f"[yellow]Draft {draft_id} is {status}[/yellow] " f"({path})"
                    )
                    console.print(path.read_text(encoding="utf-8"))
                    return
        console.print(f"[red]No such draft:[/red] {draft_id}")
        return
    path, company, kind = found
    console.print(f"[dim]{company} / {kind} / pending[/dim]")
    console.print(path.read_text(encoding="utf-8"))


def _resolve_draft(
    project_root: Path, draft_id: str, status: str, note: str | None
) -> None:
    found = _find_draft(project_root, draft_id)
    if found is None:
        console.print(f"[red]No such pending draft:[/red] {draft_id}")
        return
    src, company, kind = found
    dest_dir = project_root / "companies" / company / "drafts" / kind / status
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name

    body = src.read_text(encoding="utf-8")
    body += (
        f"\n\n---\n## Resolution ({status})\n\n"
        f"**at**: {datetime.now(UTC).isoformat()}  \n"
        f"**note**: {note or '(no note)'}\n"
    )
    dest.write_text(body, encoding="utf-8")
    src.unlink()
    color = "green" if status == "approved" else "yellow"
    console.print(
        f"[{color}]{status.title()}[/{color}] draft "
        f"[dim]{draft_id}[/dim] for [cyan]{company}[/cyan] / {kind}"
    )
    console.print(f"[dim]Moved to:[/dim] {dest}")


def _trust_set(_project_root: Path, _slug: str, _state: str) -> None:
    """Placeholder — operator should use:
       elophanto company trust set <slug> <state>
    which is handled in cli/company_cmd.py. Kept in module for
    discoverability; not wired."""
    raise NotImplementedError
