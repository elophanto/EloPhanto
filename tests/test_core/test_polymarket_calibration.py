"""Polymarket calibration audit tests.

Pin the math + tool contracts:
- to_winner_perspective re-frames YES/NO correctly so the calibration
  table is always "side I took" not "YES side".
- Bucketing correctly maps probabilities to 10% bins, including edges.
- Brier score: 0 perfect, 0.25 always-50, 1 always-wrong.
- Outcome classification: WIN/LOSS/PUSH thresholds.
- Tools: log requires bounded inputs, resolve hits Gamma once per
  unique slug, calibration buckets resolved-only and reports maker
  fill rate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from core.database import Database
from core.polymarket_calibration import (
    CalibrationBucket,
    ResolvedPrediction,
    _bucket_index,
    _make_buckets,
    brier_score,
    build_report,
    to_winner_perspective,
)
from tools.polymarket.calibration_tool import PolymarketCalibrationTool
from tools.polymarket.log_prediction_tool import PolymarketLogPredictionTool
from tools.polymarket.resolve_pending_tool import (
    PolymarketResolvePendingTool,
    _classify_outcome,
    _compute_realized_pnl,
)
from tools.polymarket.shadow_candidates_tool import (
    PolymarketShadowCandidatesTool,
)

# ---------------------------------------------------------------------------
# to_winner_perspective
# ---------------------------------------------------------------------------


class TestWinnerPerspective:
    def test_yes_side_wins(self) -> None:
        c, i, won = to_winner_perspective(
            side="YES", entry_price=0.4, llm_prob=0.7, settle_price=1.0
        )
        assert c == 0.7
        assert i == 0.4
        assert won is True

    def test_yes_side_loses(self) -> None:
        c, i, won = to_winner_perspective(
            side="YES", entry_price=0.4, llm_prob=0.7, settle_price=0.0
        )
        assert won is False

    def test_no_side_reframes(self) -> None:
        # Bot bet NO at 0.35 with LLM at 0.30 (YES) — frame to NO side.
        c, i, won = to_winner_perspective(
            side="NO", entry_price=0.35, llm_prob=0.30, settle_price=0.0
        )
        assert c == pytest.approx(0.70)  # 1 - 0.30
        assert i == pytest.approx(0.65)  # 1 - 0.35
        assert won is True

    def test_no_side_loses_when_yes_wins(self) -> None:
        c, i, won = to_winner_perspective(
            side="NO", entry_price=0.35, llm_prob=0.30, settle_price=1.0
        )
        assert won is False

    def test_invalid_side_raises(self) -> None:
        with pytest.raises(ValueError):
            to_winner_perspective(
                side="MAYBE", entry_price=0.5, llm_prob=0.5, settle_price=1.0
            )


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------


class TestBucketing:
    def test_make_buckets_default_width(self) -> None:
        buckets = _make_buckets(0.10)
        assert len(buckets) == 10
        assert buckets[0].bucket_lower == 0.0
        assert buckets[0].bucket_upper == pytest.approx(0.10)
        assert buckets[-1].bucket_upper == pytest.approx(1.00)

    def test_make_buckets_5pct(self) -> None:
        assert len(_make_buckets(0.05)) == 20

    def test_make_buckets_invalid(self) -> None:
        with pytest.raises(ValueError):
            _make_buckets(0.0)
        with pytest.raises(ValueError):
            _make_buckets(1.5)

    def test_bucket_index_clamps(self) -> None:
        assert _bucket_index(-0.5, 0.10, 10) == 0
        assert _bucket_index(0.0, 0.10, 10) == 0
        assert _bucket_index(0.55, 0.10, 10) == 5
        assert _bucket_index(0.95, 0.10, 10) == 9
        assert _bucket_index(1.5, 0.10, 10) == 9

    def test_bucket_realized_win_rate(self) -> None:
        b = CalibrationBucket(0.6, 0.7, n=10, wins=7, sum_claimed=6.5)
        assert b.realized_win_rate == 0.7
        assert b.avg_claimed == 0.65
        assert b.calibration_gap == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Brier score
# ---------------------------------------------------------------------------


class TestBrier:
    def test_perfect_predictor(self) -> None:
        # Always claims 1.0 when wins, 0.0 when loses → Brier 0.
        ps = [
            ResolvedPrediction(claimed_prob=1.0, entry_price_implied=0.5, won=True),
            ResolvedPrediction(claimed_prob=0.0, entry_price_implied=0.5, won=False),
        ]
        score, n = brier_score(ps)
        assert score == 0.0
        assert n == 2

    def test_always_50pct(self) -> None:
        ps = [
            ResolvedPrediction(claimed_prob=0.5, entry_price_implied=0.5, won=True)
            for _ in range(10)
        ]
        score, _ = brier_score(ps)
        assert score == pytest.approx(0.25)

    def test_always_wrong(self) -> None:
        ps = [
            ResolvedPrediction(claimed_prob=1.0, entry_price_implied=0.5, won=False),
            ResolvedPrediction(claimed_prob=0.0, entry_price_implied=0.5, won=True),
        ]
        score, _ = brier_score(ps)
        assert score == 1.0

    def test_empty(self) -> None:
        assert brier_score([]) == (0.0, 0)


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------


class TestBuildReport:
    def test_empty_input(self) -> None:
        r = build_report([])
        assert r.n_resolved == 0
        assert r.brier == 0.0
        assert r.overall_win_rate == 0.0

    def test_simple_calibration(self) -> None:
        # 4 predictions all in the 60-70% claimed bucket. 3 won.
        # → bucket should report claimed avg 0.65, realized 0.75.
        ps = [
            ResolvedPrediction(claimed_prob=0.65, entry_price_implied=0.5, won=True),
            ResolvedPrediction(claimed_prob=0.65, entry_price_implied=0.5, won=True),
            ResolvedPrediction(claimed_prob=0.65, entry_price_implied=0.5, won=True),
            ResolvedPrediction(claimed_prob=0.65, entry_price_implied=0.5, won=False),
        ]
        r = build_report(ps)
        assert r.n_resolved == 4
        assert r.overall_win_rate == 0.75
        non_empty = [b for b in r.by_claimed_prob if b.n > 0]
        assert len(non_empty) == 1
        assert non_empty[0].avg_claimed == pytest.approx(0.65)
        assert non_empty[0].realized_win_rate == 0.75

    def test_confidence_band_breakdown(self) -> None:
        ps = [
            ResolvedPrediction(
                claimed_prob=0.8,
                entry_price_implied=0.6,
                won=True,
                confidence_band="high",
            ),
            ResolvedPrediction(
                claimed_prob=0.55,
                entry_price_implied=0.5,
                won=False,
                confidence_band="low",
            ),
        ]
        r = build_report(ps)
        assert r.by_confidence_band["high"].n == 1
        assert r.by_confidence_band["high"].wins == 1
        assert r.by_confidence_band["low"].n == 1
        assert r.by_confidence_band["low"].wins == 0

    def test_maker_fill_rate(self) -> None:
        r = build_report([], placed_post_only=10, filled_post_only=7)
        assert r.maker_fill_rate == 0.7
        assert r.n_maker_orders == 10

    def test_maker_fill_rate_zero_placed(self) -> None:
        r = build_report([], placed_post_only=0, filled_post_only=0)
        assert r.maker_fill_rate == 0.0


# ---------------------------------------------------------------------------
# Resolve helpers
# ---------------------------------------------------------------------------


class TestResolveHelpers:
    def test_classify_yes_win(self) -> None:
        assert _classify_outcome("YES", 1.0) == "WIN"
        assert _classify_outcome("YES", 0.0) == "LOSS"
        assert _classify_outcome("YES", 0.5) == "PUSH"

    def test_classify_no_win(self) -> None:
        assert _classify_outcome("NO", 0.0) == "WIN"
        assert _classify_outcome("NO", 1.0) == "LOSS"
        assert _classify_outcome("NO", 0.5) == "PUSH"

    def test_pnl_yes_win(self) -> None:
        # Bought YES at 0.40, settled to 1.0, 100 shares. Profit per
        # share = 1.0 - 0.40 = 0.60 → $60.
        assert _compute_realized_pnl("YES", 0.40, 100, 1.0) == pytest.approx(60.0)

    def test_pnl_yes_loss(self) -> None:
        # Bought YES at 0.40, settled to 0. → -0.40 * 100 = -40.
        assert _compute_realized_pnl("YES", 0.40, 100, 0.0) == pytest.approx(-40.0)

    def test_pnl_no_win(self) -> None:
        # Bought NO at 0.40 (i.e. paid $0.60 per NO share since
        # YES side trades at 0.40 → NO at 0.60). Settled to 0 (NO
        # wins). Per share: (1 - 0) - (1 - 0.40) = 1 - 0.60 = 0.40.
        assert _compute_realized_pnl("NO", 0.40, 100, 0.0) == pytest.approx(40.0)

    def test_pnl_no_loss(self) -> None:
        # Bought NO at 0.40, YES wins. Per share: (1-1) - (1-0.40)
        # = -0.60. → -60 for 100 shares.
        assert _compute_realized_pnl("NO", 0.40, 100, 1.0) == pytest.approx(-60.0)


# ---------------------------------------------------------------------------
# Tool: log_prediction
# ---------------------------------------------------------------------------


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


class TestLogPredictionTool:
    @pytest.mark.asyncio
    async def test_logs_a_prediction(self, db: Database) -> None:
        tool = PolymarketLogPredictionTool()
        tool._db = db
        result = await tool.execute(
            {
                "token_id": "0xabc",
                "side": "YES",
                "entry_price": 0.40,
                "size": 100,
                "llm_prob": 0.55,
                "confidence_band": "high",
                "kelly_fraction": 0.05,
                "order_type": "post-only",
                "market_slug": "btc-up-down-1h",
                "rationale": "BTC is up 2% in the last 30m",
            }
        )
        assert result.success
        assert result.data["prediction_id"] > 0
        rows = await db.execute(
            "SELECT side, entry_price, llm_prob, confidence_band, "
            "order_type, rationale FROM polymarket_predictions"
        )
        assert len(rows) == 1
        assert rows[0]["side"] == "YES"
        assert rows[0]["entry_price"] == 0.40
        assert rows[0]["llm_prob"] == 0.55
        assert rows[0]["order_type"] == "post-only"

    @pytest.mark.asyncio
    async def test_rejects_invalid_side(self, db: Database) -> None:
        tool = PolymarketLogPredictionTool()
        tool._db = db
        result = await tool.execute(
            {
                "token_id": "0xabc",
                "side": "MAYBE",
                "entry_price": 0.5,
                "size": 1,
                "llm_prob": 0.5,
            }
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_rejects_out_of_range_probs(self, db: Database) -> None:
        tool = PolymarketLogPredictionTool()
        tool._db = db
        result = await tool.execute(
            {
                "token_id": "0xabc",
                "side": "YES",
                "entry_price": 1.5,
                "size": 1,
                "llm_prob": 0.5,
            }
        )
        assert not result.success
        result = await tool.execute(
            {
                "token_id": "0xabc",
                "side": "YES",
                "entry_price": 0.5,
                "size": 1,
                "llm_prob": -0.1,
            }
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_normalizes_unknown_band_to_medium(self, db: Database) -> None:
        tool = PolymarketLogPredictionTool()
        tool._db = db
        result = await tool.execute(
            {
                "token_id": "0xabc",
                "side": "YES",
                "entry_price": 0.5,
                "size": 1,
                "llm_prob": 0.5,
                "confidence_band": "unicorn",
            }
        )
        assert result.success
        rows = await db.execute("SELECT confidence_band FROM polymarket_predictions")
        assert rows[0]["confidence_band"] == "medium"


# ---------------------------------------------------------------------------
# Tool: resolve_pending
# ---------------------------------------------------------------------------


class TestResolvePendingTool:
    @pytest.mark.asyncio
    async def test_caches_per_slug(self, db: Database) -> None:
        # Two predictions on the same slug — Gamma must only be hit once.
        await db.execute_insert(
            """INSERT INTO polymarket_predictions
               (market_slug, token_id, side, entry_price, size, llm_prob,
                confidence_band, order_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "btc-test",
                "0xa",
                "YES",
                0.40,
                100,
                0.55,
                "high",
                "GTC",
                "2026-05-10T00:00:00Z",
            ),
        )
        await db.execute_insert(
            """INSERT INTO polymarket_predictions
               (market_slug, token_id, side, entry_price, size, llm_prob,
                confidence_band, order_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "btc-test",  # same slug
                "0xb",
                "NO",
                0.55,
                50,
                0.45,
                "medium",
                "GTC",
                "2026-05-10T00:00:00Z",
            ),
        )

        tool = PolymarketResolvePendingTool()
        tool._db = db

        with patch(
            "tools.polymarket.resolve_pending_tool._fetch_resolution_for_slug",
            new=AsyncMock(return_value={"resolved": True, "settle_price_yes": 1.0}),
        ) as mock_fetch:
            result = await tool.execute({})

        assert result.success
        assert result.data["unique_markets_queried"] == 1
        assert mock_fetch.call_count == 1
        assert result.data["resolved"] == 2

    @pytest.mark.asyncio
    async def test_skips_predictions_without_slug(self, db: Database) -> None:
        await db.execute_insert(
            """INSERT INTO polymarket_predictions
               (market_slug, token_id, side, entry_price, size, llm_prob,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("", "0xa", "YES", 0.40, 100, 0.55, "2026-05-10T00:00:00Z"),
        )
        tool = PolymarketResolvePendingTool()
        tool._db = db
        result = await tool.execute({})
        assert result.success
        assert result.data["skipped_no_slug"] == 1
        assert result.data["resolved"] == 0

    @pytest.mark.asyncio
    async def test_unresolved_market_stays_pending(self, db: Database) -> None:
        await db.execute_insert(
            """INSERT INTO polymarket_predictions
               (market_slug, token_id, side, entry_price, size, llm_prob,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("future", "0xa", "YES", 0.40, 100, 0.55, "2026-05-10T00:00:00Z"),
        )
        tool = PolymarketResolvePendingTool()
        tool._db = db
        with patch(
            "tools.polymarket.resolve_pending_tool._fetch_resolution_for_slug",
            new=AsyncMock(return_value={"resolved": False, "settle_price_yes": None}),
        ):
            result = await tool.execute({})
        assert result.data["still_pending"] == 1
        assert result.data["resolved"] == 0

    @pytest.mark.asyncio
    async def test_writes_pnl_correctly(self, db: Database) -> None:
        await db.execute_insert(
            """INSERT INTO polymarket_predictions
               (market_slug, token_id, side, entry_price, size, llm_prob,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("yes-wins", "0xa", "YES", 0.40, 100, 0.55, "2026-05-10T00:00:00Z"),
        )
        tool = PolymarketResolvePendingTool()
        tool._db = db
        with patch(
            "tools.polymarket.resolve_pending_tool._fetch_resolution_for_slug",
            new=AsyncMock(return_value={"resolved": True, "settle_price_yes": 1.0}),
        ):
            await tool.execute({})
        rows = await db.execute(
            "SELECT outcome, settle_price, realized_pnl FROM polymarket_predictions"
        )
        assert rows[0]["outcome"] == "WIN"
        assert rows[0]["settle_price"] == 1.0
        assert rows[0]["realized_pnl"] == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# Tool: calibration
# ---------------------------------------------------------------------------


class TestCalibrationTool:
    @pytest.mark.asyncio
    async def test_empty_db_returns_zero_n(self, db: Database) -> None:
        tool = PolymarketCalibrationTool()
        tool._db = db
        result = await tool.execute({})
        assert result.success
        assert result.data["n_resolved"] == 0
        assert result.data["overall_win_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_buckets_only_resolved(self, db: Database) -> None:
        # One resolved (won), one still pending — only the resolved
        # one should appear in the report.
        await db.execute_insert(
            """INSERT INTO polymarket_predictions
               (market_slug, token_id, side, entry_price, size, llm_prob,
                confidence_band, order_type, created_at, resolved_at,
                settle_price, outcome, realized_pnl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "won",
                "0xa",
                "YES",
                0.40,
                100,
                0.55,
                "high",
                "post-only",
                "2026-05-10T00:00:00Z",
                "2026-05-10T12:00:00Z",
                1.0,
                "WIN",
                60.0,
            ),
        )
        await db.execute_insert(
            """INSERT INTO polymarket_predictions
               (market_slug, token_id, side, entry_price, size, llm_prob,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "pending",
                "0xb",
                "YES",
                0.40,
                100,
                0.55,
                "2026-05-10T00:00:00Z",
            ),
        )
        tool = PolymarketCalibrationTool()
        tool._db = db
        result = await tool.execute({})
        assert result.success
        assert result.data["n_resolved"] == 1
        assert result.data["overall_win_rate"] == 1.0
        # post-only fill rate: 1 resolved / 1 placed = 1.0
        assert result.data["maker_fill_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_maker_fill_rate_partial(self, db: Database) -> None:
        await db.execute_insert(
            """INSERT INTO polymarket_predictions
               (market_slug, token_id, side, entry_price, size, llm_prob,
                order_type, created_at, resolved_at, settle_price, outcome)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "x",
                "0xa",
                "YES",
                0.4,
                10,
                0.55,
                "post-only",
                "2026-05-10T00:00:00Z",
                "2026-05-10T12:00:00Z",
                1.0,
                "WIN",
            ),
        )
        await db.execute_insert(
            """INSERT INTO polymarket_predictions
               (market_slug, token_id, side, entry_price, size, llm_prob,
                order_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("y", "0xb", "YES", 0.4, 10, 0.55, "post-only", "2026-05-10T00:00:00Z"),
        )
        tool = PolymarketCalibrationTool()
        tool._db = db
        result = await tool.execute({})
        assert result.data["maker_fill_rate"] == 0.5
        assert result.data["n_maker_orders"] == 2

    @pytest.mark.asyncio
    async def test_rejects_bad_bucket_width(self, db: Database) -> None:
        tool = PolymarketCalibrationTool()
        tool._db = db
        result = await tool.execute({"bucket_width": 1.5})
        assert not result.success

    @pytest.mark.asyncio
    async def test_kind_persisted_and_defaults_live(self, db: Database) -> None:
        # Live default: omitted live flag → kind='live'.
        tool = PolymarketLogPredictionTool()
        tool._db = db
        r = await tool.execute(
            {
                "token_id": "0xa",
                "side": "YES",
                "entry_price": 0.5,
                "size": 10,
                "llm_prob": 0.6,
                "kelly_fraction": 0.05,
            }
        )
        assert r.success
        assert r.data["kind"] == "live"
        # Shadow: live=False → kind='shadow', size optional.
        r2 = await tool.execute(
            {
                "token_id": "0xb",
                "side": "NO",
                "entry_price": 0.5,
                "llm_prob": 0.4,
                "live": False,
            }
        )
        assert r2.success
        assert r2.data["kind"] == "shadow"
        rows = await db.execute(
            "SELECT token_id, kind FROM polymarket_predictions ORDER BY id"
        )
        assert rows[0]["kind"] == "live"
        assert rows[1]["kind"] == "shadow"

    @pytest.mark.asyncio
    async def test_calibration_buckets_by_kind(self, db: Database) -> None:
        # One live win, one shadow loss → by_kind splits them.
        await db.execute_insert(
            """INSERT INTO polymarket_predictions
               (market_slug, token_id, side, entry_price, size, llm_prob,
                order_type, created_at, resolved_at, settle_price, outcome,
                kind)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "live-m",
                "0xa",
                "YES",
                0.4,
                10,
                0.6,
                "GTC",
                "2026-05-01T00:00:00Z",
                "2026-05-02T00:00:00Z",
                1.0,
                "WIN",
                "live",
            ),
        )
        await db.execute_insert(
            """INSERT INTO polymarket_predictions
               (market_slug, token_id, side, entry_price, size, llm_prob,
                order_type, created_at, resolved_at, settle_price, outcome,
                kind)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "shadow-m",
                "0xb",
                "YES",
                0.4,
                0,
                0.6,
                "GTC",
                "2026-05-01T00:00:00Z",
                "2026-05-02T00:00:00Z",
                0.0,
                "LOSS",
                "shadow",
            ),
        )
        tool = PolymarketCalibrationTool()
        tool._db = db
        all_r = await tool.execute({})
        assert all_r.data["n_resolved"] == 2
        assert all_r.data["by_kind"]["live"]["n_resolved"] == 1
        assert all_r.data["by_kind"]["live"]["overall_win_rate"] == 1.0
        assert all_r.data["by_kind"]["shadow"]["n_resolved"] == 1
        assert all_r.data["by_kind"]["shadow"]["overall_win_rate"] == 0.0
        # kind filter narrows the main body.
        only_live = await tool.execute({"kind": "live"})
        assert only_live.data["n_resolved"] == 1
        assert only_live.data["overall_win_rate"] == 1.0
        only_shadow = await tool.execute({"kind": "shadow"})
        assert only_shadow.data["n_resolved"] == 1
        assert only_shadow.data["overall_win_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_since_filter(self, db: Database) -> None:
        await db.execute_insert(
            """INSERT INTO polymarket_predictions
               (market_slug, token_id, side, entry_price, size, llm_prob,
                order_type, created_at, resolved_at, settle_price, outcome)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "old",
                "0xa",
                "YES",
                0.4,
                10,
                0.55,
                "GTC",
                "2026-04-01T00:00:00Z",
                "2026-04-15T00:00:00Z",
                1.0,
                "WIN",
            ),
        )
        await db.execute_insert(
            """INSERT INTO polymarket_predictions
               (market_slug, token_id, side, entry_price, size, llm_prob,
                order_type, created_at, resolved_at, settle_price, outcome)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "new",
                "0xb",
                "YES",
                0.4,
                10,
                0.55,
                "GTC",
                "2026-05-09T00:00:00Z",
                "2026-05-10T00:00:00Z",
                0.0,
                "LOSS",
            ),
        )
        tool = PolymarketCalibrationTool()
        tool._db = db
        result = await tool.execute({"since": "2026-05-01T00:00:00Z"})
        assert result.success
        assert result.data["n_resolved"] == 1
        assert result.data["overall_win_rate"] == 0.0


# ---------------------------------------------------------------------------
# Tool: shadow_candidates
# ---------------------------------------------------------------------------


class TestShadowCandidatesTool:
    @pytest.mark.asyncio
    async def test_excludes_already_shadowed(self, db: Database) -> None:
        from datetime import UTC, datetime, timedelta

        # Pre-shadow the "already" market so it should be filtered out.
        await db.execute_insert(
            """INSERT INTO polymarket_predictions
               (market_slug, token_id, side, entry_price, size, llm_prob,
                created_at, kind)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "already",
                "0xa",
                "YES",
                0.5,
                0,
                0.5,
                "2026-05-01T00:00:00Z",
                "shadow",
            ),
        )

        end = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        gamma_resp = [
            {
                "slug": "already",
                "question": "skip me",
                "endDate": end,
                "volume24hr": 5000,
                "outcomePrices": '["0.5", "0.5"]',
            },
            {
                "slug": "fresh-one",
                "question": "pick me",
                "endDate": end,
                "volume24hr": 5000,
                "outcomePrices": '["0.3", "0.7"]',
            },
        ]

        class _R:
            status_code = 200

            def json(self) -> Any:
                return gamma_resp

        class _Client:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

            async def __aenter__(self) -> _Client:
                return self

            async def __aexit__(self, *a: Any) -> None:
                pass

            async def get(self, *a: Any, **k: Any) -> _R:
                return _R()

        tool = PolymarketShadowCandidatesTool()
        tool._db = db
        with patch(
            "tools.polymarket.shadow_candidates_tool.httpx.AsyncClient", _Client
        ):
            result = await tool.execute({"limit": 10, "min_volume": 0})

        assert result.success
        slugs = [c["slug"] for c in result.data["candidates"]]
        assert "already" not in slugs
        assert "fresh-one" in slugs
        assert result.data["already_shadowed_count"] == 1
