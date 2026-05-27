"""CLI for managing companies (ABE framework Phase 1).

See ``docs/76-ABE-FRAMEWORK.md``. A company is the isolation key
threaded as ``company_id`` through every multi-tenant table. The
default seed ``elophanto-self`` owns all pre-existing rows; new
companies are created with this command and selected with ``use``.

Actions:
- ``list``                 — show all companies + status
- ``create <slug> [name]`` — create a new company (slug + display name)
- ``use <slug>``           — set this company as the active one for
                             future CLI invocations (persisted to
                             ``~/.elophanto/current_company``)
- ``current``              — print the active company slug
- ``pause <slug>``         — mark company as paused
- ``resume <slug>``        — flip a paused company back to active
- ``backfill``             — one-shot import of historical llm_usage /
                             payment_audit / email_log rows into
                             resource_ledger (idempotent)
- ``report [<slug>]``      — show revenue / spend / touches /
                             last events for the active or named company
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from core.company import (
    CompanyManager,
    read_persisted_current_company,
    write_persisted_current_company,
)
from core.config import load_config
from core.database import Database

console = Console()


@click.command("company")
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.argument("action", default="list")
@click.argument("slug", required=False)
@click.argument("name", required=False)
def company_cmd(
    config_path: str | None,
    action: str,
    slug: str | None,
    name: str | None,
) -> None:
    """Manage companies (ABE framework). Default action: list."""
    cfg_path = Path(config_path) if config_path else None
    config = load_config(cfg_path)
    asyncio.run(_dispatch(config, action, slug, name))


async def _dispatch(config, action: str, slug: str | None, name: str | None) -> None:
    db_path = Path(config.database.db_path)
    if not db_path.is_absolute():
        db_path = config.project_root / db_path
    db = Database(db_path)
    await db.initialize()
    mgr = CompanyManager(db, project_root=config.project_root)
    # ABE Phase 6: ensure the default company's data dir exists. The
    # seed company predates the per-company-dir feature; one-shot
    # idempotent backfill so existing installs get the directory the
    # first time they run any `elophanto company` subcommand.
    mgr.ensure_data_dir("elophanto-self")

    if action == "list":
        await _list(mgr)
    elif action == "create":
        if not slug:
            console.print("[red]Usage:[/red] elophanto company create <slug> [name]")
            return
        await _create(mgr, slug, name or slug)
    elif action == "use":
        if not slug:
            console.print("[red]Usage:[/red] elophanto company use <slug>")
            return
        await _use(mgr, slug)
    elif action == "current":
        _current()
    elif action == "pause":
        if not slug:
            console.print("[red]Usage:[/red] elophanto company pause <slug>")
            return
        await _set_status(mgr, slug, "paused")
    elif action == "resume":
        if not slug:
            console.print("[red]Usage:[/red] elophanto company resume <slug>")
            return
        await _set_status(mgr, slug, "active")
    elif action == "archive":
        if not slug:
            console.print("[red]Usage:[/red] elophanto company archive <slug>")
            return
        if slug == "elophanto-self":
            console.print(
                "[red]Refusing to archive 'elophanto-self'[/red] — that's "
                "the agent's own ABE. Pause if you really mean to."
            )
            return
        await _set_status(mgr, slug, "archived")
    elif action == "purge":
        if not slug:
            console.print("[red]Usage:[/red] elophanto company purge <slug> --confirm")
            return
        confirm = (name or "").lower() in ("--confirm", "confirm", "yes")
        await _purge(db, mgr, slug, project_root=config.project_root, confirmed=confirm)
    elif action == "backfill":
        await _backfill(db)
    elif action == "report":
        await _report(db, mgr, slug, project_root=config.project_root)
    elif action == "trust":
        # `trust <slug> [state]` — show current trust_state if no
        # state given, or promote/demote if state given. Phase 9.
        # Operator forms:
        #   elophanto company trust acme-inc         → show
        #   elophanto company trust acme-inc trial   → set to trial
        if slug is None:
            console.print("[red]Usage:[/red] elophanto company trust <slug> [state]")
            return
        if name is None:
            await _trust_show(mgr, slug)
        else:
            await _trust_set(mgr, slug, name)
    else:
        console.print(f"[red]Unknown action:[/red] {action}")
        console.print(
            "Use: list | create | use | current | pause | resume | "
            "backfill | report | trust"
        )


async def _list(mgr: CompanyManager) -> None:
    companies = await mgr.list()
    if not companies:
        console.print("[dim]No companies. Use:[/dim] elophanto company create <slug>")
        return

    active = read_persisted_current_company() or "elophanto-self"
    table = Table(title="Companies")
    table.add_column("", style="green")  # active marker
    table.add_column("Slug", style="cyan")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Created")
    for c in companies:
        marker = "●" if c.id == active else ""
        status_style = "green" if c.status == "active" else "yellow"
        table.add_row(
            marker,
            c.id,
            c.name,
            f"[{status_style}]{c.status}[/{status_style}]",
            c.created_at.split("T")[0],
        )
    console.print(table)
    console.print(f"[dim]Active:[/dim] {active}")


async def _create(mgr: CompanyManager, slug: str, name: str) -> None:
    try:
        company = await mgr.create(slug, name)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        return
    console.print(
        f"[green]Created[/green] company [cyan]{company.id}[/cyan] ({company.name})"
    )
    console.print(
        f"[dim]Run[/dim] elophanto company use {company.id} [dim]to activate it.[/dim]"
    )


async def _use(mgr: CompanyManager, slug: str) -> None:
    company = await mgr.get(slug)
    if company is None:
        console.print(f"[red]No such company:[/red] {slug}")
        return
    write_persisted_current_company(slug)
    console.print(f"[green]Active company:[/green] [cyan]{slug}[/cyan]")


def _current() -> None:
    active = read_persisted_current_company() or "elophanto-self"
    console.print(active)


async def _set_status(mgr: CompanyManager, slug: str, status: str) -> None:
    company = await mgr.get(slug)
    if company is None:
        console.print(f"[red]No such company:[/red] {slug}")
        return
    await mgr.set_status(slug, status)
    console.print(f"[green]Set[/green] {slug} → {status}")


async def _purge(
    db: Database,
    mgr: CompanyManager,
    slug: str,
    *,
    project_root: Any,
    confirmed: bool,
) -> None:
    """Hard delete a company + cascade through every dependent table
    + remove on-disk artifacts. Mirrors `CompanyPurgeTool` for the
    chat-side path. Requires explicit `--confirm` flag (CLI) or
    `confirm: true` (tool) to acknowledge irreversibility."""
    if slug == "elophanto-self":
        console.print(
            "[red]Refusing to purge 'elophanto-self'[/red] — that's the "
            "agent's own ABE; purging would orphan production state."
        )
        return
    if not confirmed:
        console.print(
            f"[yellow]Purge is irreversible.[/yellow] To proceed: "
            f"[bold]elophanto company purge {slug} --confirm[/bold]"
        )
        return
    company = await mgr.get(slug)
    if company is None:
        console.print(f"[red]No such company:[/red] {slug}")
        return

    cascade_tables = (
        "resource_ledger",
        "goals",
        "missions",
        "scheduled_tasks",
        "prospects",
        "outreach_log",
        "email_log",
        "payment_audit",
        "payment_requests",
        "sessions",
        "llm_usage",
    )
    totals: dict[str, int] = {}
    for table in cascade_tables:
        try:
            rows = await db.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE company_id = ?",
                (slug,),
            )
            n = int(rows[0]["n"]) if rows else 0
            if n > 0:
                await db.execute_insert(
                    f"DELETE FROM {table} WHERE company_id = ?", (slug,)
                )
            totals[table] = n
        except Exception:
            totals[table] = -1  # schema mismatch — skip but report

    await db.execute_insert("DELETE FROM companies WHERE id = ?", (slug,))

    import shutil

    fs_removed: list[str] = []
    for sub in ("companies", "data/companies"):
        target = project_root / sub / slug
        if target.is_dir():
            try:
                shutil.rmtree(target)
                fs_removed.append(str(target))
            except Exception:
                pass

    console.print(f"[green]Purged[/green] {slug}")
    console.print(f"[dim]rows: {totals}[/]")
    if fs_removed:
        console.print(f"[dim]filesystem: removed {len(fs_removed)} path(s)[/]")


async def _trust_show(mgr: CompanyManager, slug: str) -> None:
    """Show the current trust state of a company (Phase 9)."""
    company = await mgr.get(slug)
    if company is None:
        console.print(f"[red]No such company:[/red] {slug}")
        return
    style = {
        "learning": "yellow",
        "trial": "cyan",
        "operating": "green",
    }.get(company.trust_state, "white")
    console.print(
        f"[cyan]{slug}[/cyan] trust: [{style}]{company.trust_state}[/{style}]"
    )
    if company.trust_state == "learning":
        console.print(
            "[dim]Live outreach (email_send / email_reply / "
            "prospect_outreach / twitter_post) is REFUSED. Agent "
            "must draft instead. Promote with:[/dim] "
            f"elophanto company trust {slug} trial"
        )


async def _trust_set(mgr: CompanyManager, slug: str, state: str) -> None:
    """Operator promotes / demotes a company's trust state (Phase 9)."""
    try:
        ok = await mgr.set_trust_state(slug, state)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        return
    if not ok:
        console.print(f"[red]No such company:[/red] {slug}")
        return
    style = {
        "learning": "yellow",
        "trial": "cyan",
        "operating": "green",
    }.get(state, "white")
    console.print(f"[green]Set[/green] {slug} trust → [{style}]{state}[/{style}]")


async def _backfill(db: Database) -> None:
    from core.ledger_backfill import backfill_ledger

    console.print("[dim]Backfilling resource_ledger from historical rows…[/dim]")
    report = await backfill_ledger(db)
    table = Table(title="Backfill summary")
    table.add_column("Source")
    table.add_column("Rows added", justify="right")
    table.add_row("llm_usage (tokens)", str(report.llm_tokens_added))
    table.add_row("llm_usage (usd)", str(report.llm_usd_added))
    table.add_row("payment_audit", str(report.payment_added))
    table.add_row("email_log (outbound)", str(report.email_added))
    table.add_row("[bold]Total[/bold]", f"[bold]{report.total}[/bold]")
    console.print(table)
    if report.total == 0:
        console.print(
            "[dim]Nothing to backfill — ledger already has all source rows.[/dim]"
        )


async def _report(
    db: Database,
    mgr: CompanyManager,
    slug: str | None,
    *,
    project_root: Path,
) -> None:
    from core.ledger import ResourceLedger

    target = slug or (read_persisted_current_company() or "elophanto-self")
    company = await mgr.get(target)
    if company is None:
        console.print(f"[red]No such company:[/red] {target}")
        return

    ledger = ResourceLedger(db)
    usd_in = await ledger.sum(target, type="usd", direction="in")
    usd_out = await ledger.sum(target, type="usd", direction="out")
    tokens_out = await ledger.sum(target, type="tokens", direction="out")
    emails_out = await ledger.sum(target, type="email_sent", direction="out")
    pipeline_advances = await ledger.sum(
        target, type="pipeline_advance", direction="in"
    )

    # Headline block
    console.print()
    trust_style = {
        "learning": "yellow",
        "trial": "cyan",
        "operating": "green",
    }.get(company.trust_state, "white")
    console.print(
        f"[bold cyan]{company.id}[/bold cyan] — {company.name} "
        f"([{('green' if company.status == 'active' else 'yellow')}]"
        f"{company.status}[/]) "
        f"trust=[{trust_style}]{company.trust_state}[/{trust_style}]"
    )

    # ABE Phase 4: PRODUCT line. Surfaces the company's declared
    # product (`what_we_sell`, capped) so the operator can see at a
    # glance whether this company is actually productized. Missing
    # product = explicit warning so the gap is hard to miss — an
    # un-productized company will produce drift goals in dream phase.
    try:
        from core.product import load_product

        product = load_product(project_root, company.id)
    except Exception:
        product = None
    if product is not None:
        sell = product.what_we_sell.strip().replace("\n", " ")
        if len(sell) > 200:
            sell = sell[:200] + "…"
        console.print(f"[dim]Product:[/dim] {sell}")
    else:
        console.print(
            "[yellow]Product:[/yellow] "
            f"[dim](not defined — write[/dim] companies/{company.id}/company.yaml"
            "[dim] to anchor the dream phase)[/dim]"
        )

    # ABE Phase 10: VOICE line. Surfaces whether the company has an
    # operator-approved voice contract gating its drafts. Without
    # voice.yaml the draft tools are fail-soft (any body lands as a
    # draft) — the operator should know.
    try:
        from core.voice import load_voice

        voice = load_voice(project_root, company.id)
    except Exception:
        voice = None
    if voice is not None:
        rule_count = (
            len(voice.banned_phrases)
            + len(voice.banned_patterns)
            + (1 if voice.length_target.max_chars else 0)
            + (1 if voice.length_target.min_chars else 0)
            + (1 if voice.allowed_hooks else 0)
        )
        console.print(
            f"[dim]Voice:[/dim] [green]configured[/green] "
            f"([dim]{rule_count} rule(s); persona={voice.persona or '—'!r}[/dim])"
        )
    else:
        exemplars_dir = project_root / "data" / "companies" / company.id / "exemplars"
        ex_count = 0
        if exemplars_dir.is_dir():
            ex_count = sum(
                1
                for ch in exemplars_dir.iterdir()
                if ch.is_dir()
                for _ in ch.glob("*.md")
            )
        if ex_count >= 2:
            console.print(
                f"[yellow]Voice:[/yellow] [dim]not configured "
                f"({ex_count} exemplar(s) ready — run[/dim] "
                f"`elophanto voice extract {company.id}` [dim]to propose "
                f"voice.yaml)[/dim]"
            )
        else:
            console.print(
                f"[yellow]Voice:[/yellow] [dim](not configured — drop "
                f"exemplar posts/emails at[/dim] {exemplars_dir}/"
                "<channel>/[dim] then run[/dim] "
                f"`elophanto voice extract {company.id}`[dim])[/dim]"
            )

    # ABE Phase 6: per-company data directory. Materialized on company
    # create (and for the default seed via the one-shot in _dispatch).
    # The line surfaces the location so the operator + tools opting
    # into per-company file state know where to look.
    data_dir = mgr.data_dir(company.id)
    if data_dir is not None:
        marker = "" if data_dir.is_dir() else " [yellow](not yet created)[/yellow]"
        console.print(f"[dim]Data dir:[/dim] {data_dir}{marker}")
    console.print()

    headline = Table(show_header=False, box=None, padding=(0, 2))
    headline.add_column(style="dim")
    headline.add_column(justify="right")
    headline.add_row("Revenue (in)", f"[green]${usd_in:,.2f}[/green]")
    headline.add_row("Spend (out)", f"[red]${usd_out:,.2f}[/red]")
    net = usd_in - usd_out
    net_style = "green" if net >= 0 else "red"
    headline.add_row("Net", f"[{net_style}]${net:+,.2f}[/{net_style}]")
    headline.add_row("LLM tokens (out)", f"{int(tokens_out):,}")
    headline.add_row("Email touches (out)", f"{int(emails_out):,}")
    headline.add_row("Pipeline advances (in)", f"{int(pipeline_advances):,}")
    console.print(headline)
    console.print()

    # ABE Phase 3 — Pipeline by stage. Counts prospects grouped by
    # the existing status enum (new | evaluated | outreach_sent |
    # replied | converted | rejected | expired). Empty for companies
    # with no prospects yet — the section renders blank rather than
    # hiding, so the operator can see that the funnel is wired up.
    pipeline_rows = await db.execute(
        "SELECT status, COUNT(*) AS n FROM prospects "
        "WHERE company_id = ? GROUP BY status",
        (target,),
    )
    if pipeline_rows:
        # Order stages by typical funnel progression so the table
        # reads top-down. Statuses not in this list (legacy values)
        # land at the bottom alphabetically.
        stage_order = [
            "new",
            "evaluated",
            "outreach_sent",
            "replied",
            "converted",
            "rejected",
            "expired",
        ]
        by_status = {r["status"]: r["n"] for r in pipeline_rows}
        ordered = [(s, by_status[s]) for s in stage_order if s in by_status]
        leftovers = sorted((s, by_status[s]) for s in by_status if s not in stage_order)
        ordered.extend(leftovers)

        pipeline_table = Table(title="Pipeline by stage", show_lines=False)
        pipeline_table.add_column("Stage", style="cyan")
        pipeline_table.add_column("Count", justify="right")
        for stage, n in ordered:
            pipeline_table.add_row(stage, str(n))
        console.print(pipeline_table)
        console.print()

    # Recent ledger events
    recent = await ledger.recent(target, limit=10)
    if not recent:
        console.print("[dim]No ledger events yet.[/dim]")
        return

    events = Table(title=f"Last {len(recent)} ledger events", show_lines=False)
    events.add_column("ts", style="dim", no_wrap=True)
    events.add_column("dir", justify="center")
    events.add_column("type")
    events.add_column("amount", justify="right")
    events.add_column("unit", style="dim")
    events.add_column("note", overflow="fold")
    for row in recent:
        dir_style = "green" if row["direction"] == "in" else "red"
        events.add_row(
            row["ts"][:19],  # YYYY-MM-DDTHH:MM:SS
            f"[{dir_style}]{row['direction']}[/{dir_style}]",
            row["type"],
            f"{row['amount']:,.4f}".rstrip("0").rstrip("."),
            row["unit"],
            (row["note"] or "")[:80],
        )
    console.print(events)
