"""Polymarket trade-history analyzer — what's actually winning, what's losing,
which orders fail and why.

Reads the polynode-trading.db `order_history` table and produces a
:class:`PerformanceReport` the operator + agent can act on. Designed
to answer the questions Tier 1+2 left unanswered:

  * Did the new risk gates change the win rate?
  * How many orders are still hitting the precision-rejection or
    allowance failure modes?
  * Which markets are bleeding (held to resolution at zero) vs.
    actually closing for a profit?
  * Per-window comparison — last 7d vs. last 30d vs. all-time —
    so you can see whether things are improving.

Pure analysis: takes a path to a SQLite file, returns dataclasses.
No I/O outside the read; no LLM calls. Wraps cleanly under a tool
(``polymarket_performance``) and a CLI command
(``elophanto polymarket performance``).

Honest design notes:
  - We can't compute *unrealized* P&L without live YES prices on
    open positions. Open positions are reported with ``open_size``
    and ``cost_basis`` so the caller can fetch live prices and mark
    them to market — analytics layer doesn't do that.
  - Position reconstruction is by ``token_id``. Same market, same
    side. Doesn't currently model NO-side exits as buying-back-YES;
    operator workflow puts each leg on its own token_id, which the
    grouping naturally handles.
  - Failure-mode classification is regex-based against
    ``error_msg``. Two patterns cover ~100% of historical failures
    (precision + allowance); anything else lands in ``other``.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Failure-mode classification — regex against error_msg
# ---------------------------------------------------------------------------
#
# Patterns derived from live failure log analysis (2026-05-07). 6 of 8
# failures were precision errors; 2 of 8 were allowance/balance. Anything
# else is bucketed as "other" so the operator can investigate.

_PRECISION_RE = re.compile(
    r"invalid amounts.*max accuracy of \d+ decimals", re.IGNORECASE
)
_ALLOWANCE_RE = re.compile(r"(?:not enough balance|allowance)", re.IGNORECASE)


def classify_failure(error_msg: str | None) -> str:
    """Bucket a Polymarket error message into a known failure mode.

    Returns one of: ``"precision"``, ``"allowance"``, ``"other"``,
    or ``"unknown"`` (for empty/None).
    """
    if not error_msg:
        return "unknown"
    if _PRECISION_RE.search(error_msg):
        return "precision"
    if _ALLOWANCE_RE.search(error_msg):
        return "allowance"
    return "other"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Position:
    """Reconstructed position for one ``token_id``.

    Long-only model: aggregate BUY size + cost, aggregate SELL size +
    proceeds, the open part is whatever didn't get sold yet.

    realized_pnl is computed proportionally — if you bought 100 shares
    at avg $0.50 ($50 cost basis) and sold 60 at $0.80 ($48 proceeds),
    the realized P&L is $48 - (60/100)*$50 = $48 - $30 = $18, on the
    closed 60. The remaining 40 shares are open with $20 cost basis.
    """

    token_id: str
    buy_count: int = 0
    sell_count: int = 0
    buy_size: float = 0.0  # total shares bought (cumulative)
    sell_size: float = 0.0  # total shares sold (cumulative)
    buy_cost_total: float = 0.0  # USDC paid for BUYs
    sell_proceeds_total: float = 0.0  # USDC received from SELLs
    first_trade_at: float = 0.0  # unix ts
    last_trade_at: float = 0.0  # unix ts

    @property
    def open_size(self) -> float:
        """Shares still held (BUY minus SELL). Negative means oversold —
        treat as fully closed and ignore the dust."""
        return max(0.0, self.buy_size - self.sell_size)

    @property
    def is_open(self) -> bool:
        return self.open_size > 0.0001  # share-precision threshold

    @property
    def avg_buy_price(self) -> float:
        if self.buy_size <= 0:
            return 0.0
        return self.buy_cost_total / self.buy_size

    @property
    def closed_share_count(self) -> float:
        return min(self.buy_size, self.sell_size)

    @property
    def realized_pnl(self) -> float:
        """P&L on the closed portion only. Open shares aren't priced
        here — caller marks them to market separately if needed."""
        if self.closed_share_count <= 0:
            return 0.0
        # Proportional cost basis for the closed portion.
        closed_cost = self.avg_buy_price * self.closed_share_count
        return self.sell_proceeds_total - closed_cost

    @property
    def open_cost_basis(self) -> float:
        """USDC at risk on the open portion (your unrealized exposure)."""
        return self.avg_buy_price * self.open_size


@dataclass
class FailureBreakdown:
    """Failure-mode counts + the worst offender for each."""

    total_failed: int = 0
    precision: int = 0
    allowance: int = 0
    other: int = 0
    unknown: int = 0
    sample_messages: dict[str, str] = field(default_factory=dict)

    @property
    def precision_pct(self) -> float:
        return self.precision / self.total_failed if self.total_failed else 0.0

    @property
    def allowance_pct(self) -> float:
        return self.allowance / self.total_failed if self.total_failed else 0.0


@dataclass
class PerformanceReport:
    """Single-window performance snapshot."""

    window_label: str  # e.g. "all-time" / "last 7d" / "last 30d"
    window_start_unix: float | None  # None for all-time
    window_end_unix: float

    total_orders: int = 0
    submitted_orders: int = 0
    failed_orders: int = 0
    submit_success_rate: float = 0.0  # submitted / total

    positions: list[Position] = field(default_factory=list)
    failures: FailureBreakdown = field(default_factory=FailureBreakdown)

    total_buy_notional: float = 0.0  # USDC put in
    total_sell_proceeds: float = 0.0  # USDC out
    total_realized_pnl: float = 0.0  # sum across positions
    total_open_cost_basis: float = 0.0  # USDC at risk in open positions

    closed_position_count: int = 0
    open_position_count: int = 0
    win_count: int = 0  # closed positions with realized_pnl > 0
    loss_count: int = 0  # closed positions with realized_pnl <= 0

    @property
    def win_rate(self) -> float:
        denom = self.win_count + self.loss_count
        return self.win_count / denom if denom else 0.0

    @property
    def net_pnl_worst_case(self) -> float:
        """Realized P&L minus the cost basis of every open position —
        i.e. the net P&L if every open position resolves at zero. This
        is the conservative read the operator should anchor on; reality
        is between this and ``total_realized_pnl``.

        Why this is the headline number:
            "Realized P&L positive" misleads when the agent is the kind
            of trader who never sells losers. Open positions held to
            resolution dominate P&L; reporting only realized hides the
            damage. The honest baseline is "what would the books look
            like if every still-open bet went to zero?" — then the
            operator marks specific positions to market if they think
            any are worth something.
        """
        return self.total_realized_pnl - self.total_open_cost_basis


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _aggregate_orders(rows: Iterable[dict]) -> dict[str, Position]:
    """Group order_history rows by token_id and reconstruct positions.

    Only ``status == 'submitted'`` rows count toward fills — failed
    orders affected nothing.
    """
    positions: dict[str, Position] = {}
    for row in rows:
        if row["status"] != "submitted":
            continue
        token_id = row["token_id"]
        if not token_id:
            continue
        pos = positions.setdefault(token_id, Position(token_id=token_id))
        side = (row["side"] or "").upper()
        size = float(row["size"] or 0.0)
        price = float(row["price"] or 0.0)
        notional = size * price
        ts = float(row["created_at"] or 0.0)
        if pos.first_trade_at == 0.0 or ts < pos.first_trade_at:
            pos.first_trade_at = ts
        if ts > pos.last_trade_at:
            pos.last_trade_at = ts
        if side == "BUY":
            pos.buy_count += 1
            pos.buy_size += size
            pos.buy_cost_total += notional
        elif side == "SELL":
            pos.sell_count += 1
            pos.sell_size += size
            pos.sell_proceeds_total += notional
    return positions


def _aggregate_failures(rows: Iterable[dict]) -> FailureBreakdown:
    """Classify failed orders by error category."""
    fb = FailureBreakdown()
    for row in rows:
        if row["status"] != "failed":
            continue
        fb.total_failed += 1
        category = classify_failure(row.get("error_msg"))
        if category == "precision":
            fb.precision += 1
        elif category == "allowance":
            fb.allowance += 1
        elif category == "unknown":
            fb.unknown += 1
        else:
            fb.other += 1
        # Keep a sample message per category for display.
        if category not in fb.sample_messages and row.get("error_msg"):
            fb.sample_messages[category] = (row["error_msg"] or "")[:200]
    return fb


def _build_report(
    rows: list[dict],
    *,
    window_label: str,
    window_start_unix: float | None,
    window_end_unix: float,
) -> PerformanceReport:
    """Roll up a row set into a PerformanceReport."""
    positions_dict = _aggregate_orders(rows)
    positions = sorted(
        positions_dict.values(), key=lambda p: p.last_trade_at, reverse=True
    )
    failures = _aggregate_failures(rows)

    submitted = sum(1 for r in rows if r["status"] == "submitted")
    failed = failures.total_failed
    total = len(rows)

    closed_count = sum(1 for p in positions if not p.is_open)
    open_count = len(positions) - closed_count
    win_count = sum(1 for p in positions if not p.is_open and p.realized_pnl > 0)
    loss_count = sum(1 for p in positions if not p.is_open and p.realized_pnl <= 0)

    return PerformanceReport(
        window_label=window_label,
        window_start_unix=window_start_unix,
        window_end_unix=window_end_unix,
        total_orders=total,
        submitted_orders=submitted,
        failed_orders=failed,
        submit_success_rate=submitted / total if total else 0.0,
        positions=positions,
        failures=failures,
        total_buy_notional=sum(p.buy_cost_total for p in positions),
        total_sell_proceeds=sum(p.sell_proceeds_total for p in positions),
        total_realized_pnl=sum(p.realized_pnl for p in positions),
        total_open_cost_basis=sum(p.open_cost_basis for p in positions),
        closed_position_count=closed_count,
        open_position_count=open_count,
        win_count=win_count,
        loss_count=loss_count,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def analyze_performance(
    db_path: str | Path,
    *,
    window_days: int | None = None,
) -> PerformanceReport:
    """Read order_history from ``db_path`` and produce a performance
    report. ``window_days=None`` = all-time; otherwise restrict to the
    last N days from now.

    Raises FileNotFoundError if the DB doesn't exist. Returns an empty
    report (zero counts) on an empty DB — no exception, just zeroed
    snapshot.
    """
    path = Path(db_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(
            f"polymarket trading DB not found at {path}. "
            "If you've never used the polynode tool, this is expected. "
            "Set polymarket.trading_db_path in config.yaml or run a "
            "trade first."
        )

    now_dt = datetime.now(UTC)
    end_unix = now_dt.timestamp()
    if window_days is None:
        start_unix: float | None = None
        window_label = "all-time"
        where = ""
        params: tuple = ()
    else:
        start_unix = (now_dt - timedelta(days=window_days)).timestamp()
        window_label = f"last {window_days}d"
        where = "WHERE created_at >= ?"
        params = (start_unix,)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            f"""SELECT token_id, side, price, size, status, error_msg,
                       created_at
                  FROM order_history
                  {where}
                  ORDER BY created_at""",
            params,
        )
        rows = [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()

    return _build_report(
        rows,
        window_label=window_label,
        window_start_unix=start_unix,
        window_end_unix=end_unix,
    )


# ---------------------------------------------------------------------------
# Multi-window summary — one report per common window
# ---------------------------------------------------------------------------


def analyze_all_windows(db_path: str | Path) -> list[PerformanceReport]:
    """Convenience: build all-time + last-30d + last-7d reports in one
    pass for side-by-side comparison."""
    return [
        analyze_performance(db_path, window_days=None),
        analyze_performance(db_path, window_days=30),
        analyze_performance(db_path, window_days=7),
    ]


# ---------------------------------------------------------------------------
# Mark-to-market — what would each open position recover if sold now?
# ---------------------------------------------------------------------------
#
# The conservative ``net_pnl_worst_case`` treats every open position as
# worth $0. That's the "books look like this if everything goes against
# us" number — useful as an anchor, but pessimistic. Reality lives
# between worst-case and cost basis: each open token has a current best
# bid on the book, and that's what you'd actually receive on a market
# sell.
#
# This module exposes the math; the live bid lookup is injected as a
# callable so the engine layer stays testable without HTTP.

from collections.abc import Callable


@dataclass
class MarkToMarketPosition:
    """One open position priced against current orderbook."""

    token_id: str
    open_size: float
    cost_basis: float
    avg_buy_price: float
    current_bid: float | None  # None = no bids on the book
    market_value: float  # open_size * current_bid (0 if no bids)
    unrealized_pnl: float  # market_value - cost_basis
    note: str  # "ok" | "no-bids" | "fetch-failed: <reason>"


@dataclass
class MarkToMarketSummary:
    """Roll-up across all open positions in a report."""

    positions: list[MarkToMarketPosition]
    total_cost_basis: float
    total_market_value: float
    total_unrealized_pnl: float
    no_bids_count: int  # markets with no bids — effectively dead
    fetch_failed_count: int  # how many bid fetches errored

    @property
    def liveness_pct(self) -> float:
        """How much of the cost basis still has bids on the book.
        100% → all positions are sellable now; 0% → everything is
        either resolved or has no buy interest. Mid-range is normal."""
        if self.total_cost_basis <= 0:
            return 0.0
        live_basis = sum(
            p.cost_basis
            for p in self.positions
            if p.current_bid is not None and p.current_bid > 0
        )
        return live_basis / self.total_cost_basis


def mark_open_positions_to_market(
    positions: list[Position],
    fetch_bid: Callable[[str], float | None],
) -> MarkToMarketSummary:
    """Price every OPEN position against the current best bid.

    ``fetch_bid(token_id)`` returns the highest current bid on the
    orderbook (in USDC, [0, 1] price scale), or ``None`` if there
    are no bids OR the fetch fails. The caller is responsible for
    error handling inside fetch_bid — None covers both cases so the
    summary stays uniform.

    Pure function: no HTTP, no DB. The CLI / tool wires a real HTTP
    fetcher; tests inject a stub.
    """
    out: list[MarkToMarketPosition] = []
    no_bids = 0
    fetch_failed = 0  # caller signals via the note suffix on returned None;
    # keep the field on the summary for future telemetry. For now we can't
    # distinguish "no bids" from "HTTP failed" without instrumentation
    # inside the fetcher itself — the caller can decide which it cares about.

    for pos in positions:
        if not pos.is_open:
            continue
        try:
            bid = fetch_bid(pos.token_id)
        except Exception as e:
            bid = None
            note = f"fetch-failed: {e!r}"[:120]
            fetch_failed += 1
        else:
            if bid is None or bid <= 0:
                note = "no-bids"
                no_bids += 1
            else:
                note = "ok"

        market_value = pos.open_size * bid if bid is not None and bid > 0 else 0.0
        out.append(
            MarkToMarketPosition(
                token_id=pos.token_id,
                open_size=pos.open_size,
                cost_basis=pos.open_cost_basis,
                avg_buy_price=pos.avg_buy_price,
                current_bid=bid if bid and bid > 0 else None,
                market_value=round(market_value, 2),
                unrealized_pnl=round(market_value - pos.open_cost_basis, 2),
                note=note,
            )
        )

    return MarkToMarketSummary(
        positions=out,
        total_cost_basis=round(sum(p.cost_basis for p in out), 2),
        total_market_value=round(sum(p.market_value for p in out), 2),
        total_unrealized_pnl=round(sum(p.unrealized_pnl for p in out), 2),
        no_bids_count=no_bids,
        fetch_failed_count=fetch_failed,
    )


# ---------------------------------------------------------------------------
# Live bid fetcher — Polymarket public CLOB API
# ---------------------------------------------------------------------------
#
# Polymarket's CLOB exposes orderbooks at:
#   GET https://clob.polymarket.com/book?token_id=<id>
# Returns JSON of shape:
#   {"market": ..., "asset_id": ..., "bids": [{"price": "0.42", "size": "100"}, ...], "asks": [...]}
# bids are returned ascending by price; we take the max.
#
# Public endpoint, no auth needed. Best bid is what a market-sell would
# fill at. Empty bids list → no buy interest → effectively unsellable
# (fetcher returns None).


def fetch_best_bid_via_clob(
    token_id: str,
    *,
    base_url: str = "https://clob.polymarket.com",
    timeout: float = 5.0,
) -> float | None:
    """Live HTTP fetcher. Returns best bid (highest price on the book)
    or None if no bids / HTTP error / parse failure. Defensive against
    every failure mode — never raises, so the mark-to-market loop
    can't be derailed by a single bad market."""
    import httpx

    try:
        resp = httpx.get(
            f"{base_url}/book", params={"token_id": token_id}, timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.debug("CLOB book fetch failed for %s: %s", token_id, e)
        return None

    bids = data.get("bids") if isinstance(data, dict) else None
    if not bids:
        return None
    try:
        prices = [float(b["price"]) for b in bids if "price" in b]
        if not prices:
            return None
        return max(prices)
    except (KeyError, TypeError, ValueError) as e:
        logger.debug("CLOB book parse failed for %s: %s", token_id, e)
        return None
