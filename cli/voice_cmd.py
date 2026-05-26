"""CLI for managing per-company voice contracts (ABE Phase 10).

See ``docs/76-ABE-FRAMEWORK.md`` §Phase 10. Voice contracts live at
``data/companies/<slug>/voice.yaml``; proposals from voice_extract
land at ``voice_proposed.yaml`` until the operator approves them.

Actions:
- ``list``                       — show voice status for every company
- ``show <slug>``                — print the active voice.yaml
- ``proposed <slug>``            — print voice_proposed.yaml (if any)
- ``approve <slug>``             — promote voice_proposed.yaml → voice.yaml
- ``reject <slug> <reason>``     — discard voice_proposed.yaml with reason
- ``extract <slug> [channel]``   — invoke voice_extract via the agent path
- ``exemplars <slug>``           — show exemplar counts per channel
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from core.config import load_config
from core.voice import load_voice

console = Console()


def _voice_path(project_root: Path, slug: str) -> Path:
    return project_root / "data" / "companies" / slug / "voice.yaml"


def _proposed_path(project_root: Path, slug: str) -> Path:
    return project_root / "data" / "companies" / slug / "voice_proposed.yaml"


def _exemplars_root(project_root: Path, slug: str) -> Path:
    return project_root / "data" / "companies" / slug / "exemplars"


def _exemplar_count(project_root: Path, slug: str) -> dict[str, int]:
    """Return {channel: count} for exemplar files."""
    out: dict[str, int] = {}
    root = _exemplars_root(project_root, slug)
    if not root.is_dir():
        return out
    for ch_dir in sorted(root.iterdir()):
        if not ch_dir.is_dir():
            continue
        out[ch_dir.name] = sum(1 for _ in ch_dir.glob("*.md"))
    return out


def _list_companies(project_root: Path) -> list[str]:
    """List company slugs that have a data/ dir (Phase 6 convention)."""
    root = project_root / "data" / "companies"
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir())


@click.command("voice")
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.argument("action", default="list")
@click.argument("arg1", required=False)
@click.argument("arg2", required=False)
def voice_cmd(
    config_path: str | None,
    action: str,
    arg1: str | None,
    arg2: str | None,
) -> None:
    """Manage per-company voice contracts (ABE Phase 10).

    Default action: list. Voice contracts gate every draft tool —
    a body that violates the contract is refused before persisting,
    so the operator's approved voice is the anti-AI-slop guarantee.
    """
    cfg_path = Path(config_path) if config_path else None
    config = load_config(cfg_path)
    project_root = config.project_root

    if action == "list":
        _list_voices(project_root)
    elif action == "show":
        if not arg1:
            console.print("[red]Usage:[/red] elophanto voice show <slug>")
            return
        _show_voice(project_root, arg1)
    elif action == "proposed":
        if not arg1:
            console.print("[red]Usage:[/red] elophanto voice proposed <slug>")
            return
        _show_proposed(project_root, arg1)
    elif action == "approve":
        if not arg1:
            console.print("[red]Usage:[/red] elophanto voice approve <slug>")
            return
        _approve_proposed(project_root, arg1)
    elif action == "reject":
        if not arg1 or not arg2:
            console.print("[red]Usage:[/red] elophanto voice reject <slug> <reason>")
            return
        _reject_proposed(project_root, arg1, arg2)
    elif action == "exemplars":
        if not arg1:
            console.print("[red]Usage:[/red] elophanto voice exemplars <slug>")
            return
        _show_exemplars(project_root, arg1)
    elif action == "extract":
        if not arg1:
            console.print("[red]Usage:[/red] elophanto voice extract <slug> [channel]")
            return
        _hint_extract(arg1, arg2)
    else:
        console.print(f"[red]Unknown action:[/red] {action}")
        console.print(
            "Use: list | show | proposed | approve | reject | " "exemplars | extract"
        )


def _list_voices(project_root: Path) -> None:
    slugs = _list_companies(project_root)
    if not slugs:
        console.print(
            "[dim]No companies with data dirs yet. Run "
            "`elophanto company onboard ...` first.[/dim]"
        )
        return
    table = Table(title="Voice contracts")
    table.add_column("Company", style="cyan")
    table.add_column("Status")
    table.add_column("Exemplars")
    table.add_column("Proposed?")
    for slug in slugs:
        voice = load_voice(project_root, slug)
        if voice is not None:
            status = "[green]configured[/green]"
        else:
            status = "[yellow]not configured[/yellow]"
        counts = _exemplar_count(project_root, slug)
        ex_summary = (
            ", ".join(f"{ch}={n}" for ch, n in counts.items()) or "[dim]—[/dim]"
        )
        proposed = (
            "[yellow]yes[/yellow]"
            if _proposed_path(project_root, slug).is_file()
            else "[dim]no[/dim]"
        )
        table.add_row(slug, status, ex_summary, proposed)
    console.print(table)


def _show_voice(project_root: Path, slug: str) -> None:
    path = _voice_path(project_root, slug)
    if not path.is_file():
        console.print(
            f"[yellow]No voice.yaml for {slug}[/yellow] [dim](would live at "
            f"{path})[/dim]"
        )
        proposed = _proposed_path(project_root, slug)
        if proposed.is_file():
            console.print(
                f"[dim]A proposal exists at {proposed}. Review it with "
                f"`elophanto voice proposed {slug}` and promote with "
                f"`elophanto voice approve {slug}`.[/dim]"
            )
        return
    console.print(f"[cyan]{slug}[/cyan] voice.yaml ({path})")
    console.print(path.read_text(encoding="utf-8"))


def _show_proposed(project_root: Path, slug: str) -> None:
    path = _proposed_path(project_root, slug)
    if not path.is_file():
        console.print(
            f"[dim]No proposal at {path}. Run `elophanto voice extract "
            f"{slug}` (via the agent) to produce one.[/dim]"
        )
        return
    console.print(f"[cyan]{slug}[/cyan] voice_proposed.yaml ({path})")
    console.print(path.read_text(encoding="utf-8"))


def _approve_proposed(project_root: Path, slug: str) -> None:
    proposed = _proposed_path(project_root, slug)
    if not proposed.is_file():
        console.print(f"[red]No proposal for {slug}[/red] at {proposed}")
        return
    target = _voice_path(project_root, slug)
    if target.is_file():
        # Back up the existing contract so an accidental approve is
        # reversible.
        backup = target.with_suffix(
            f".yaml.bak.{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}"
        )
        shutil.copy2(target, backup)
        console.print(f"[dim]Backed up existing voice.yaml → {backup}[/dim]")
    shutil.move(str(proposed), str(target))
    console.print(
        f"[green]Approved[/green] voice for [cyan]{slug}[/cyan]. "
        f"Active contract: {target}"
    )
    console.print(
        "[dim]Drafts for this company are now lint-gated. Operator-"
        "approved voice is the anti-slop guarantee.[/dim]"
    )


def _reject_proposed(project_root: Path, slug: str, reason: str) -> None:
    proposed = _proposed_path(project_root, slug)
    if not proposed.is_file():
        console.print(f"[red]No proposal for {slug}[/red] at {proposed}")
        return
    rejected_dir = project_root / "data" / "companies" / slug / "voice_rejected"
    rejected_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    dest = rejected_dir / f"voice_proposed.{stamp}.yaml"
    body = proposed.read_text(encoding="utf-8")
    body += (
        f"\n# ---\n# Rejected at: {datetime.now(UTC).isoformat()}\n"
        f"# Reason: {reason}\n"
    )
    dest.write_text(body, encoding="utf-8")
    proposed.unlink()
    console.print(
        f"[yellow]Rejected[/yellow] voice proposal for [cyan]{slug}[/cyan]. "
        f"Archived at {dest}."
    )
    console.print(
        "[dim]Agent will see the reason in the next voice_extract context "
        "and revise.[/dim]"
    )


def _show_exemplars(project_root: Path, slug: str) -> None:
    counts = _exemplar_count(project_root, slug)
    root = _exemplars_root(project_root, slug)
    if not counts:
        console.print(
            f"[yellow]No exemplars for {slug}[/yellow] [dim](drop reference "
            f"posts/emails at {root}/<channel>/*.md — see the README "
            f"there)[/dim]"
        )
        return
    table = Table(title=f"Exemplars for {slug}")
    table.add_column("Channel", style="cyan")
    table.add_column("Files", justify="right")
    for channel, n in counts.items():
        marker = "" if n >= 2 else " [yellow](need ≥2)[/yellow]"
        table.add_row(channel, f"{n}{marker}")
    console.print(table)
    console.print(f"[dim]Path: {root}/[/dim]")


def _hint_extract(slug: str, channel: str | None) -> None:
    """voice_extract is an agent-side LLM tool. The CLI doesn't run
    the LLM directly — it tells the operator how to invoke it via
    chat or `elophanto chat`."""
    ch_arg = f", channel='{channel}'" if channel else ""
    console.print(
        f"[dim]voice_extract is an LLM tool — invoke it through the "
        f"agent:[/dim]\n"
        f"  [bold]elophanto chat[/bold] then ask: "
        f'"run voice_extract for {slug}{ch_arg}"\n'
        f"[dim]The agent reads exemplars from data/companies/{slug}"
        f"/exemplars/, calls the LLM, and writes "
        f"voice_proposed.yaml. Approve with `elophanto voice approve "
        f"{slug}`.[/dim]"
    )
