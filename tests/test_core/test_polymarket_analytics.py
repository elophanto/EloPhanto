"""Polymarket analytics tests — failure classification, position
reconstruction, full-report shape, time-windowing.

Builds a synthetic order_history schema in a tempfile DB so we don't
depend on the operator's live data file.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from core.polymarket_analytics import (
    Position,
    analyze_all_windows,
    analyze_performance,
    classify_failure,
)

# ---------------------------------------------------------------------------
# Failure classifier
# ---------------------------------------------------------------------------


class TestClassifyFailure:
    def test_precision_pattern(self) -> None:
        msg = (
            "invalid amounts, the market buy orders maker amount supports a "
            "max accuracy of 2 decimals, taker amount a max of 4 decimals"
        )
        assert classify_failure(msg) == "precision"

    def test_allowance_pattern(self) -> None:
        msg = (
            "not enough balance / allowance: the balance is not enough -> "
            "balance: 0, order amount: 12459400"
        )
        assert classify_failure(msg) == "allowance"

    def test_other_falls_through(self) -> None:
        assert classify_failure("rate limit exceeded") == "other"

    def test_empty_or_none_unknown(self) -> None:
        assert classify_failure(None) == "unknown"
        assert classify_failure("") == "unknown"

    def test_case_insensitive(self) -> None:
        assert classify_failure("INVALID AMOUNTS — MAX ACCURACY OF 2 DECIMALS")
        assert (
            classify_failure("INVALID AMOUNTS — MAX ACCURACY OF 2 DECIMALS")
            == "precision"
        )


# ---------------------------------------------------------------------------
# Synthetic DB fixture
# ---------------------------------------------------------------------------


_SCHEMA = """
CREATE TABLE order_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    order_id TEXT,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    order_type TEXT NOT NULL DEFAULT 'GTC',
    status TEXT NOT NULL DEFAULT 'submitting',
    error_msg TEXT,
    response_json TEXT,
    created_at REAL NOT NULL,
    fee_amount_raw TEXT,
    escrow_order_id TEXT,
    fee_escrow_tx_hash TEXT
)
"""


def _seed(db_path: Path, rows: list[dict]) -> None:
    """Create a polynode-shaped DB and insert ``rows``."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_SCHEMA)
        conn.executemany(
            """INSERT INTO order_history
                 (wallet_address, token_id, side, price, size, status,
                  error_msg, created_at)
               VALUES
                 (:wallet_address, :token_id, :side, :price, :size,
                  :status, :error_msg, :created_at)""",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    db = tmp_path / "polynode-trading.db"
    _seed(db, [])
    return db


@pytest.fixture
def winning_position_db(tmp_path: Path) -> Path:
    """One position: bought 100 @ $0.50 (cost $50), sold 100 @ $0.80
    ($80 proceeds). Realized P&L = +$30."""
    db = tmp_path / "winning.db"
    now = time.time()
    _seed(
        db,
        [
            {
                "wallet_address": "w",
                "token_id": "tok-A",
                "side": "BUY",
                "price": 0.50,
                "size": 100.0,
                "status": "submitted",
                "error_msg": None,
                "created_at": now - 86400,
            },
            {
                "wallet_address": "w",
                "token_id": "tok-A",
                "side": "SELL",
                "price": 0.80,
                "size": 100.0,
                "status": "submitted",
                "error_msg": None,
                "created_at": now - 3600,
            },
        ],
    )
    return db


@pytest.fixture
def losing_open_position_db(tmp_path: Path) -> Path:
    """Bought 100 @ $0.50, never sold. Open position with $50 cost basis,
    zero realized P&L."""
    db = tmp_path / "open.db"
    now = time.time()
    _seed(
        db,
        [
            {
                "wallet_address": "w",
                "token_id": "tok-OPEN",
                "side": "BUY",
                "price": 0.50,
                "size": 100.0,
                "status": "submitted",
                "error_msg": None,
                "created_at": now - 86400,
            },
        ],
    )
    return db


@pytest.fixture
def failure_mix_db(tmp_path: Path) -> Path:
    """Mirrors the live-data shape: 6 precision rejections + 2
    allowance failures, no successful orders."""
    db = tmp_path / "failures.db"
    now = time.time()
    rows: list[dict] = []
    precision_msg = (
        "invalid amounts, the market buy orders maker amount supports a "
        "max accuracy of 2 decimals, taker amount a max of 5 decimals"
    )
    allowance_msg = (
        "not enough balance / allowance: the balance is not enough -> "
        "balance: 0, order amount: 12459400"
    )
    for i in range(6):
        rows.append(
            {
                "wallet_address": "w",
                "token_id": f"tok-FAIL-P-{i}",
                "side": "BUY",
                "price": 0.35,
                "size": 42.85,
                "status": "failed",
                "error_msg": precision_msg,
                "created_at": now - 86400 - i * 1000,
            }
        )
    for i in range(2):
        rows.append(
            {
                "wallet_address": "w",
                "token_id": f"tok-FAIL-A-{i}",
                "side": "BUY",
                "price": 0.82,
                "size": 15.0,
                "status": "failed",
                "error_msg": allowance_msg,
                "created_at": now - 86400 - 6000 - i * 1000,
            }
        )
    _seed(db, rows)
    return db


# ---------------------------------------------------------------------------
# Position reconstruction + report shape
# ---------------------------------------------------------------------------


class TestAnalyzePerformance:
    def test_empty_db_returns_zeroed_report(self, empty_db: Path) -> None:
        r = analyze_performance(empty_db)
        assert r.total_orders == 0
        assert r.total_realized_pnl == 0.0
        assert r.win_count == 0
        assert r.loss_count == 0
        assert r.failures.total_failed == 0
        assert r.positions == []

    def test_missing_db_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            analyze_performance(tmp_path / "does-not-exist.db")

    def test_simple_winning_position(self, winning_position_db: Path) -> None:
        r = analyze_performance(winning_position_db)
        assert r.total_orders == 2
        assert r.submitted_orders == 2
        assert r.failed_orders == 0
        assert r.closed_position_count == 1
        assert r.open_position_count == 0
        assert r.win_count == 1
        assert r.loss_count == 0
        assert r.win_rate == 1.0
        # 100 * 0.80 - 100 * 0.50 = 30
        assert abs(r.total_realized_pnl - 30.0) < 0.01
        assert abs(r.total_buy_notional - 50.0) < 0.01
        assert abs(r.total_sell_proceeds - 80.0) < 0.01

    def test_open_position_not_counted_as_win_or_loss(
        self, losing_open_position_db: Path
    ) -> None:
        """An open position has no realized P&L; it should NOT be
        bucketed as a loss until the agent actually sells (or holds
        to resolution at zero)."""
        r = analyze_performance(losing_open_position_db)
        assert r.open_position_count == 1
        assert r.closed_position_count == 0
        assert r.win_count == 0
        assert r.loss_count == 0
        assert r.total_realized_pnl == 0.0
        # But the open exposure should be visible.
        assert abs(r.total_open_cost_basis - 50.0) < 0.01

    def test_net_pnl_worst_case_treats_open_as_zero(
        self, losing_open_position_db: Path
    ) -> None:
        """The conservative read: realized − open cost basis. With
        $0 realized and $50 of open cost basis on a never-closed
        position, the worst-case net P&L is -$50.

        This is the operator-anchor metric that ships in the CLI's
        leading row. Hides the "realized P&L positive" misdirection
        when the bot is the kind of trader that never sells losers.
        """
        r = analyze_performance(losing_open_position_db)
        assert abs(r.net_pnl_worst_case - (-50.0)) < 0.01

    def test_net_pnl_worst_case_combines_realized_and_open(
        self, tmp_path: Path
    ) -> None:
        """Closed position: +$30 realized. Open position: $50 cost
        basis. Worst-case net = 30 − 50 = -$20."""
        db = tmp_path / "mixed.db"
        now = time.time()
        _seed(
            db,
            [
                # Closed: bought 100 @ $0.50, sold 100 @ $0.80 → +$30.
                {
                    "wallet_address": "w",
                    "token_id": "tok-WIN",
                    "side": "BUY",
                    "price": 0.50,
                    "size": 100.0,
                    "status": "submitted",
                    "error_msg": None,
                    "created_at": now - 7200,
                },
                {
                    "wallet_address": "w",
                    "token_id": "tok-WIN",
                    "side": "SELL",
                    "price": 0.80,
                    "size": 100.0,
                    "status": "submitted",
                    "error_msg": None,
                    "created_at": now - 3600,
                },
                # Open: bought 100 @ $0.50, never sold → $50 cost basis.
                {
                    "wallet_address": "w",
                    "token_id": "tok-OPEN",
                    "side": "BUY",
                    "price": 0.50,
                    "size": 100.0,
                    "status": "submitted",
                    "error_msg": None,
                    "created_at": now - 3600,
                },
            ],
        )
        r = analyze_performance(db)
        assert abs(r.total_realized_pnl - 30.0) < 0.01
        assert abs(r.total_open_cost_basis - 50.0) < 0.01
        assert abs(r.net_pnl_worst_case - (-20.0)) < 0.01

    def test_partial_close_realized_pnl_proportional(self, tmp_path: Path) -> None:
        """Bought 100 @ $0.40 ($40 cost), sold 60 @ $0.60 ($36 proceeds).
        Realized P&L on the closed 60: $36 - 60 * $0.40 = $36 - $24 = $12."""
        db = tmp_path / "partial.db"
        now = time.time()
        _seed(
            db,
            [
                {
                    "wallet_address": "w",
                    "token_id": "tok-PARTIAL",
                    "side": "BUY",
                    "price": 0.40,
                    "size": 100.0,
                    "status": "submitted",
                    "error_msg": None,
                    "created_at": now - 7200,
                },
                {
                    "wallet_address": "w",
                    "token_id": "tok-PARTIAL",
                    "side": "SELL",
                    "price": 0.60,
                    "size": 60.0,
                    "status": "submitted",
                    "error_msg": None,
                    "created_at": now - 3600,
                },
            ],
        )
        r = analyze_performance(db)
        position = r.positions[0]
        assert abs(position.realized_pnl - 12.0) < 0.01
        # Still 40 shares open at $0.40 cost basis = $16 exposure.
        assert abs(position.open_cost_basis - 16.0) < 0.01
        assert position.is_open

    def test_failure_mix_classified_correctly(self, failure_mix_db: Path) -> None:
        """Mirrors the live-data shape (6 precision + 2 allowance =
        8 total failures, no successful orders)."""
        r = analyze_performance(failure_mix_db)
        assert r.failed_orders == 8
        assert r.failures.precision == 6
        assert r.failures.allowance == 2
        assert r.failures.other == 0
        assert abs(r.failures.precision_pct - 0.75) < 0.001
        assert abs(r.failures.allowance_pct - 0.25) < 0.001
        # Sample messages preserved for display.
        assert "precision" in r.failures.sample_messages
        assert "allowance" in r.failures.sample_messages

    def test_failed_orders_dont_create_positions(self, failure_mix_db: Path) -> None:
        """A failed BUY didn't fill, so it must not show up as an
        open position with cost basis."""
        r = analyze_performance(failure_mix_db)
        assert r.positions == []
        assert r.total_open_cost_basis == 0.0

    def test_window_filter_applied(self, tmp_path: Path) -> None:
        """A trade older than the window must NOT contribute to
        a windowed report."""
        db = tmp_path / "windowed.db"
        now = time.time()
        _seed(
            db,
            [
                # 60 days ago — outside last-7d, last-30d.
                {
                    "wallet_address": "w",
                    "token_id": "tok-OLD",
                    "side": "BUY",
                    "price": 0.40,
                    "size": 50.0,
                    "status": "submitted",
                    "error_msg": None,
                    "created_at": now - 60 * 86400,
                },
                {
                    "wallet_address": "w",
                    "token_id": "tok-OLD",
                    "side": "SELL",
                    "price": 0.60,
                    "size": 50.0,
                    "status": "submitted",
                    "error_msg": None,
                    "created_at": now - 60 * 86400 + 3600,
                },
                # Yesterday — inside both windows.
                {
                    "wallet_address": "w",
                    "token_id": "tok-NEW",
                    "side": "BUY",
                    "price": 0.40,
                    "size": 50.0,
                    "status": "submitted",
                    "error_msg": None,
                    "created_at": now - 86400,
                },
                {
                    "wallet_address": "w",
                    "token_id": "tok-NEW",
                    "side": "SELL",
                    "price": 0.50,
                    "size": 50.0,
                    "status": "submitted",
                    "error_msg": None,
                    "created_at": now - 3600,
                },
            ],
        )
        all_time = analyze_performance(db)
        last_7 = analyze_performance(db, window_days=7)
        last_30 = analyze_performance(db, window_days=30)

        # All-time: both positions visible.
        assert all_time.closed_position_count == 2
        # Last 30d: only the recent one.
        assert last_30.closed_position_count == 1
        assert last_7.closed_position_count == 1
        # All-time P&L: 60-50 = 10 + 50*0.5 - 50*0.4 = 5 → +15.
        assert abs(all_time.total_realized_pnl - 15.0) < 0.1
        # 30d P&L: only the +5.
        assert abs(last_30.total_realized_pnl - 5.0) < 0.1

    def test_analyze_all_windows_returns_three_reports(
        self, winning_position_db: Path
    ) -> None:
        reports = analyze_all_windows(winning_position_db)
        assert len(reports) == 3
        labels = [r.window_label for r in reports]
        assert labels == ["all-time", "last 30d", "last 7d"]


# ---------------------------------------------------------------------------
# Mark-to-market — live bid pricing
# ---------------------------------------------------------------------------


class TestMarkToMarket:
    """Pure tests via stub fetcher — no HTTP. The actual fetcher is
    smoke-tested separately (or live)."""

    def _make_open_position(
        self,
        token_id: str,
        cost_basis: float,
        size: float,
    ) -> Position:
        # Construct a position by hand so we don't need a DB.
        # avg_buy_price is computed from the totals on access.
        return Position(
            token_id=token_id,
            buy_count=1,
            sell_count=0,
            buy_size=size,
            sell_size=0.0,
            buy_cost_total=cost_basis,
            sell_proceeds_total=0.0,
            first_trade_at=time.time() - 3600,
            last_trade_at=time.time() - 3600,
        )

    def test_position_with_live_bid_marks_to_market(self) -> None:
        from core.polymarket_analytics import mark_open_positions_to_market

        positions = [
            self._make_open_position("tok-A", cost_basis=100.0, size=200.0),
        ]
        # Stub fetcher: bid at 0.40. Bought 200 @ $0.50 cost basis $100;
        # market value = 200 * 0.40 = $80 → unrealized = -$20.
        summary = mark_open_positions_to_market(
            positions, fetch_bid=lambda token_id: 0.40
        )
        assert len(summary.positions) == 1
        p = summary.positions[0]
        assert p.current_bid == 0.40
        assert abs(p.market_value - 80.0) < 0.01
        assert abs(p.unrealized_pnl - (-20.0)) < 0.01
        assert p.note == "ok"
        assert abs(summary.total_unrealized_pnl - (-20.0)) < 0.01

    def test_no_bids_means_zero_recovery(self) -> None:
        from core.polymarket_analytics import mark_open_positions_to_market

        positions = [
            self._make_open_position("tok-DEAD", cost_basis=50.0, size=100.0),
        ]
        # Stub returns None — no bids.
        summary = mark_open_positions_to_market(
            positions, fetch_bid=lambda token_id: None
        )
        p = summary.positions[0]
        assert p.current_bid is None
        assert p.market_value == 0.0
        assert abs(p.unrealized_pnl - (-50.0)) < 0.01
        assert p.note == "no-bids"
        assert summary.no_bids_count == 1

    def test_zero_bid_treated_as_no_bid(self) -> None:
        """Polymarket sometimes returns 0-priced bids on resolved
        markets. Treat as effectively dead, not as 'recover $0 × size'."""
        from core.polymarket_analytics import mark_open_positions_to_market

        positions = [
            self._make_open_position("tok-ZERO", cost_basis=50.0, size=100.0),
        ]
        summary = mark_open_positions_to_market(
            positions, fetch_bid=lambda token_id: 0.0
        )
        assert summary.positions[0].current_bid is None
        assert summary.positions[0].note == "no-bids"
        assert summary.no_bids_count == 1

    def test_fetch_failure_handled_gracefully(self) -> None:
        """If the fetcher raises, the loop must NOT abort — that
        position lands as fetch-failed, the rest still get marked."""
        from core.polymarket_analytics import mark_open_positions_to_market

        positions = [
            self._make_open_position("tok-OK", cost_basis=100.0, size=200.0),
            self._make_open_position("tok-FAIL", cost_basis=80.0, size=100.0),
            self._make_open_position("tok-OK2", cost_basis=50.0, size=100.0),
        ]

        def buggy_fetcher(token_id: str) -> float | None:
            if token_id == "tok-FAIL":
                raise RuntimeError("CLOB unreachable")
            return 0.30

        summary = mark_open_positions_to_market(positions, fetch_bid=buggy_fetcher)
        assert len(summary.positions) == 3
        notes = {p.token_id: p.note for p in summary.positions}
        assert notes["tok-OK"] == "ok"
        assert notes["tok-OK2"] == "ok"
        assert "fetch-failed" in notes["tok-FAIL"]
        assert summary.fetch_failed_count == 1

    def test_only_open_positions_marked(self) -> None:
        """Closed positions must not appear in mark-to-market output —
        they have no open exposure to price."""
        from core.polymarket_analytics import mark_open_positions_to_market

        # Fully-closed position (buy_size == sell_size).
        closed = Position(
            token_id="tok-CLOSED",
            buy_count=1,
            sell_count=1,
            buy_size=100.0,
            sell_size=100.0,
            buy_cost_total=50.0,
            sell_proceeds_total=80.0,
            first_trade_at=time.time() - 7200,
            last_trade_at=time.time() - 3600,
        )
        # Open position.
        open_pos = self._make_open_position("tok-OPEN", cost_basis=50.0, size=100.0)
        summary = mark_open_positions_to_market(
            [closed, open_pos], fetch_bid=lambda t: 0.40
        )
        assert len(summary.positions) == 1
        assert summary.positions[0].token_id == "tok-OPEN"

    def test_liveness_pct_computed(self) -> None:
        """Liveness = fraction of cost basis that has live bids.
        Two positions, $100 basis each, one with bids one without →
        50% liveness."""
        from core.polymarket_analytics import mark_open_positions_to_market

        positions = [
            self._make_open_position("tok-LIVE", cost_basis=100.0, size=200.0),
            self._make_open_position("tok-DEAD", cost_basis=100.0, size=100.0),
        ]

        def fetcher(token_id: str) -> float | None:
            return 0.40 if token_id == "tok-LIVE" else None

        summary = mark_open_positions_to_market(positions, fetch_bid=fetcher)
        assert abs(summary.liveness_pct - 0.5) < 0.001

    def test_aggregate_unrealized_sums_correctly(self) -> None:
        from core.polymarket_analytics import mark_open_positions_to_market

        positions = [
            self._make_open_position("tok-A", cost_basis=100.0, size=200.0),
            self._make_open_position("tok-B", cost_basis=80.0, size=100.0),
        ]

        def fetcher(token_id: str) -> float | None:
            return {"tok-A": 0.40, "tok-B": 0.10}[token_id]

        summary = mark_open_positions_to_market(positions, fetch_bid=fetcher)
        # tok-A: 200 * 0.40 - 100 = -20
        # tok-B: 100 * 0.10 - 80 = -70
        # total: -90
        assert abs(summary.total_unrealized_pnl - (-90.0)) < 0.01
        assert abs(summary.total_market_value - (80.0 + 10.0)) < 0.01
        assert abs(summary.total_cost_basis - (100.0 + 80.0)) < 0.01
