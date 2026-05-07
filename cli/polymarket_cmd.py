"""``elophanto polymarket performance`` — read trade history, print P&L.

Static report from polynode-trading.db. Same shape as
``elophanto schedule status`` / ``affect status`` — the operator can
run this any time without a daemon, and the output answers
"is the bot losing money less than it used to?"

The exact same numbers are also exposed to the agent via the
``polymarket_performance`` tool so scheduled tasks can reason over
their own track record before deciding what to trade next.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.config import load_config

console = Console()


def _project_root() -> Path:
    """Same convention as cli/affect_cmd.py — find the dir holding
    config.yaml so the operator can run this from any subdir."""
    cwd = Path.cwd()
    for p in [cwd, *cwd.parents]:
        if (p / "config.yaml").exists() or (p / "config.demo.yaml").exists():
            return p
    return cwd


def _resolve_db_path(config: Any) -> Path:
    """Mirror tools/polymarket/performance_tool.py's resolution: explicit
    config path → workspace default."""
    cfg_path = (
        getattr(config.polymarket, "trading_db_path", "")
        if hasattr(config, "polymarket")
        else ""
    )
    if cfg_path:
        return Path(cfg_path).expanduser()
    workspace = Path(getattr(config, "workspace", ".")).expanduser()
    return workspace / "data" / "polymarket" / "polynode-trading.db"


def _pnl_color(pnl: float) -> str:
    if pnl > 0.5:
        return "green"
    if pnl < -0.5:
        return "red"
    return "white"


# ──────────────────────────────────────────────────────────────────
# Subcommands
# ──────────────────────────────────────────────────────────────────


async def _performance_async(
    config_path: str | None,
    window_days: int | None,
    show_positions: bool,
    show_failures_only: bool,
) -> int:
    from core.polymarket_analytics import (
        analyze_all_windows,
        analyze_performance,
    )

    config = load_config(config_path)
    db_path = _resolve_db_path(config)

    if not db_path.exists():
        console.print(f"[red]Trading DB not found at[/red] {db_path}")
        console.print(
            "[dim]Set polymarket.trading_db_path in config.yaml or run a "
            "Polymarket trade first.[/dim]"
        )
        return 1

    if window_days is None:
        # Default: side-by-side all-time / 30d / 7d.
        reports = analyze_all_windows(db_path)
    else:
        reports = [analyze_performance(db_path, window_days=window_days or None)]

    for report in reports:
        if show_failures_only:
            _render_failures(report)
        else:
            _render_summary(report)
            if show_positions:
                _render_positions(report)
            _render_failures(report)
        console.print()

    return 0


def _render_summary(report: Any) -> None:
    """Lead with the conservative net P&L (realized − open cost basis,
    i.e. what the books look like if every open position resolves at
    zero). Then break out realized + unrealized so the operator can
    adjust if any open positions are actually worth something."""
    net_color = _pnl_color(report.net_pnl_worst_case)
    realized_color = _pnl_color(report.total_realized_pnl)
    body = (
        f"[bold {net_color}]net P&L (open=$0)[/bold {net_color}]   "
        f"[{net_color}]${report.net_pnl_worst_case:+.2f}[/{net_color}]"
        "  [dim]worst-case: every open position resolves to zero[/dim]\n"
        f"  realized              "
        f"[{realized_color}]${report.total_realized_pnl:+.2f}[/{realized_color}] "
        f"on {report.closed_position_count} closed (W {report.win_count} / "
        f"L {report.loss_count}, win rate {report.win_rate:.1%})\n"
        f"  unrealized exposure   "
        f"[red]-${report.total_open_cost_basis:.2f}[/red] "
        f"across {report.open_position_count} open "
        f"[dim](mark-to-market for true number)[/dim]\n"
        f"\n"
        f"[bold]orders[/bold]              "
        f"{report.total_orders} (submitted {report.submitted_orders}, "
        f"failed {report.failed_orders})\n"
        f"[bold]submit success[/bold]      "
        f"{report.submit_success_rate:.1%}\n"
        f"[bold]bought[/bold]              "
        f"${report.total_buy_notional:.2f} USDC\n"
        f"[bold]sold[/bold]                "
        f"${report.total_sell_proceeds:.2f} USDC"
    )
    console.print(Panel(body, title=f"Polymarket performance — {report.window_label}"))


def _render_positions(report: Any) -> None:
    closed = [p for p in report.positions if not p.is_open]
    open_pos = [p for p in report.positions if p.is_open]

    if closed:
        winners = sorted(closed, key=lambda p: p.realized_pnl, reverse=True)[:5]
        losers = sorted(closed, key=lambda p: p.realized_pnl)[:5]
        table = Table(
            title=f"Top closed positions ({report.window_label})", show_lines=False
        )
        table.add_column("token_id", style="dim")
        table.add_column("avg buy", justify="right")
        table.add_column("buys", justify="right")
        table.add_column("sells", justify="right")
        table.add_column("realized P&L", justify="right")
        seen: set[str] = set()
        for p in winners + losers:
            if p.token_id in seen:
                continue
            seen.add(p.token_id)
            color = _pnl_color(p.realized_pnl)
            table.add_row(
                (p.token_id[:18] + "…") if len(p.token_id) > 19 else p.token_id,
                f"${p.avg_buy_price:.3f}",
                str(p.buy_count),
                str(p.sell_count),
                f"[{color}]${p.realized_pnl:+.2f}[/{color}]",
            )
        console.print(table)

    if open_pos:
        table = Table(
            title=f"Open positions ({report.window_label}) — held to resolution if not closed",
            show_lines=False,
        )
        table.add_column("token_id", style="dim")
        table.add_column("avg buy", justify="right")
        table.add_column("open size", justify="right")
        table.add_column("cost basis", justify="right")
        for p in sorted(open_pos, key=lambda p: p.open_cost_basis, reverse=True)[:8]:
            table.add_row(
                (p.token_id[:18] + "…") if len(p.token_id) > 19 else p.token_id,
                f"${p.avg_buy_price:.3f}",
                f"{p.open_size:.2f}",
                f"${p.open_cost_basis:.2f}",
            )
        console.print(table)


def _render_failures(report: Any) -> None:
    if report.failures.total_failed == 0:
        return
    table = Table(title=f"Failure modes ({report.window_label})", show_lines=False)
    table.add_column("category", style="cyan")
    table.add_column("count", justify="right")
    table.add_column("share", justify="right")
    table.add_column("sample message", style="dim")
    fb = report.failures
    rows = [
        ("precision", fb.precision, fb.precision_pct),
        ("allowance", fb.allowance, fb.allowance_pct),
        ("other", fb.other, fb.other / fb.total_failed if fb.total_failed else 0),
        (
            "unknown",
            fb.unknown,
            fb.unknown / fb.total_failed if fb.total_failed else 0,
        ),
    ]
    for category, count, pct in rows:
        if count == 0:
            continue
        sample = fb.sample_messages.get(category, "")
        table.add_row(category, str(count), f"{pct:.0%}", sample[:60] if sample else "")
    console.print(table)


# ──────────────────────────────────────────────────────────────────
# Click wiring
# ──────────────────────────────────────────────────────────────────


@click.group(name="polymarket")
def polymarket_cmd() -> None:
    """Polymarket-specific CLI commands.

    See docs/64-POLYMARKET.md for the broader Polymarket integration
    and docs/71-POLYMARKET-RISK.md for the risk-engine + analytics
    architecture.
    """
    pass


@polymarket_cmd.command(name="performance")
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.option(
    "--window",
    "window",
    default=None,
    type=click.Choice(["7d", "30d", "all"]),
    help=(
        "Lookback window. Default shows all three side-by-side "
        "(all-time / 30d / 7d)."
    ),
)
@click.option(
    "--positions/--no-positions",
    default=False,
    help="Include per-position tables (top winners/losers + open).",
)
@click.option(
    "--failures-only",
    is_flag=True,
    default=False,
    help="Only show failure-mode breakdown, skip the P&L summary.",
)
def polymarket_performance(
    config_path: str | None,
    window: str | None,
    positions: bool,
    failures_only: bool,
) -> None:
    """Print Polymarket trading performance — realized P&L, win rate,
    open-position cost basis, and failure-mode breakdown.

    Reads from `polymarket.trading_db_path` if set, otherwise the
    default `<agent.workspace>/data/polymarket/polynode-trading.db`.
    """
    window_days: int | None
    if window is None:
        window_days = None  # signals analyze_all_windows
    elif window == "7d":
        window_days = 7
    elif window == "30d":
        window_days = 30
    else:  # all
        window_days = 0  # 0 means "no window filter"

    rc = asyncio.run(
        _performance_async(
            config_path=config_path,
            window_days=window_days,
            show_positions=positions,
            show_failures_only=failures_only,
        )
    )
    raise SystemExit(rc)


# ──────────────────────────────────────────────────────────────────
# polymarket mark — fetch live bids, compute true unrealized P&L
# ──────────────────────────────────────────────────────────────────


async def _mark_to_market_async(
    config_path: str | None, max_positions: int | None
) -> int:
    from core.polymarket_analytics import (
        analyze_performance,
        fetch_best_bid_via_clob,
        mark_open_positions_to_market,
    )

    config = load_config(config_path)
    db_path = _resolve_db_path(config)
    if not db_path.exists():
        console.print(f"[red]Trading DB not found at[/red] {db_path}")
        return 1

    with console.status("[bold]Reading positions[/bold]…", spinner="dots"):
        report = analyze_performance(db_path, window_days=None)

    open_positions = [p for p in report.positions if p.is_open]
    if not open_positions:
        console.print("[dim]No open positions to mark.[/dim]")
        return 0

    if max_positions:
        open_positions = sorted(
            open_positions, key=lambda p: p.open_cost_basis, reverse=True
        )[:max_positions]

    n = len(open_positions)
    with console.status(
        f"[bold]Fetching live bids for {n} open positions[/bold]…",
        spinner="dots",
    ):
        summary = mark_open_positions_to_market(
            open_positions, fetch_bid=fetch_best_bid_via_clob
        )

    # Headline panel — the real number.
    net_marked = report.total_realized_pnl + summary.total_unrealized_pnl
    realized = report.total_realized_pnl
    net_color = _pnl_color(net_marked)
    realized_color = _pnl_color(realized)
    unrealized_color = _pnl_color(summary.total_unrealized_pnl)
    body = (
        f"[bold {net_color}]net P&L (live bids)[/bold {net_color}]    "
        f"[{net_color}]${net_marked:+.2f}[/{net_color}]\n"
        f"  realized               "
        f"[{realized_color}]${realized:+.2f}[/{realized_color}] "
        f"on {report.closed_position_count} closed\n"
        f"  unrealized (marked)    "
        f"[{unrealized_color}]${summary.total_unrealized_pnl:+.2f}[/{unrealized_color}] "
        f"across {len(summary.positions)} open\n"
        f"\n"
        f"  cost basis             ${summary.total_cost_basis:.2f} USDC\n"
        f"  market value (live)    ${summary.total_market_value:.2f} USDC\n"
        f"  liveness               {summary.liveness_pct:.0%} "
        f"[dim](% of cost basis with live bids)[/dim]\n"
        f"  positions w/ no bids   {summary.no_bids_count} "
        f"[dim](effectively dead — recover $0)[/dim]"
    )
    console.print(Panel(body, title="Mark-to-market — true unrealized P&L"))

    # Per-position table sorted by recovery potential descending.
    table = Table(title="Open positions — marked to current bid")
    table.add_column("token_id", style="dim")
    table.add_column("avg buy", justify="right")
    table.add_column("open size", justify="right")
    table.add_column("cost basis", justify="right")
    table.add_column("current bid", justify="right")
    table.add_column("market value", justify="right")
    table.add_column("unrealized P&L", justify="right")
    table.add_column("note")
    sorted_positions = sorted(
        summary.positions, key=lambda p: p.unrealized_pnl, reverse=True
    )
    for p in sorted_positions:
        bid_str = f"${p.current_bid:.3f}" if p.current_bid else "[red]—[/red]"
        pnl_color = _pnl_color(p.unrealized_pnl)
        note_color = "yellow" if p.note != "ok" else "dim"
        table.add_row(
            (p.token_id[:18] + "…") if len(p.token_id) > 19 else p.token_id,
            f"${p.avg_buy_price:.3f}",
            f"{p.open_size:.2f}",
            f"${p.cost_basis:.2f}",
            bid_str,
            f"${p.market_value:.2f}",
            f"[{pnl_color}]${p.unrealized_pnl:+.2f}[/{pnl_color}]",
            f"[{note_color}]{p.note}[/{note_color}]",
        )
    console.print(table)

    if summary.no_bids_count > 0:
        console.print(
            f"\n[yellow]⚠[/yellow]  {summary.no_bids_count} position(s) have no bids — "
            "those will recover $0 if held. Consider whether the markets have "
            "already resolved against you."
        )

    return 0


@polymarket_cmd.command(name="mark")
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.option(
    "--max",
    "max_positions",
    type=int,
    default=None,
    help="Cap how many open positions to mark (highest cost basis first).",
)
def polymarket_mark(config_path: str | None, max_positions: int | None) -> None:
    """Mark every open Polymarket position to the current best bid.

    Fetches live orderbook data from Polymarket's public CLOB API for
    each open token_id, computes per-position recovery values, and
    rolls up the true unrealized P&L.

    Use this to decide which open positions to cut now (cheap recovery
    today) vs hold to resolution. Read-only HTTP — no orders placed.
    """
    rc = asyncio.run(
        _mark_to_market_async(config_path=config_path, max_positions=max_positions)
    )
    raise SystemExit(rc)
