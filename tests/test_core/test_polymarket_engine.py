"""Polymarket risk-engine tests — edge filter, skip tags, stop-loss,
drawdown circuit breaker, combined pre-trade gate.

The historical bug was "no constraints between LLM confidence and
place_order." Each test pins one of the new gates so we don't drift
back to that behavior.
"""

from __future__ import annotations

import pytest

from core.polymarket_engine import (
    DEFAULT_SKIP_TAG_SLUGS,
    DEFAULT_SKIP_TITLE_PHRASES,
    calculate_stop_loss_levels,
    check_drawdown,
    check_edge,
    confidence_band,
    evaluate_pre_trade,
    should_skip_market,
    threshold_for_band,
)

# ---------------------------------------------------------------------------
# Edge filter
# ---------------------------------------------------------------------------


class TestEdgeFilter:
    def test_blocks_trade_when_edge_below_threshold(self) -> None:
        # LLM thinks 0.55, market at 0.54 → 1% edge, way below 4% floor.
        result = check_edge(llm_prob=0.55, market_price=0.54, confidence=0.7)
        assert result.passes is False
        assert "edge" in result.reason.lower()

    def test_allows_trade_when_edge_above_threshold(self) -> None:
        # 10% edge with high confidence → easily passes.
        result = check_edge(llm_prob=0.65, market_price=0.55, confidence=0.8)
        assert result.passes is True
        assert result.side == "YES"

    def test_picks_no_side_when_market_overprices_yes(self) -> None:
        result = check_edge(llm_prob=0.30, market_price=0.55, confidence=0.7)
        assert result.passes is True
        assert result.side == "NO"
        assert result.edge < 0

    def test_low_confidence_demands_bigger_edge(self) -> None:
        """The same 5% edge that a confident bet would clear should be
        rejected when the LLM is uncertain. Asymmetric thresholds are
        the whole point — uncertain claims are exactly where the
        market is most likely correct."""
        # 5% edge.
        prob, price = 0.55, 0.50
        confident = check_edge(prob, price, confidence=0.85)
        uncertain = check_edge(prob, price, confidence=0.30)
        assert confident.passes is True
        assert uncertain.passes is False
        assert uncertain.threshold_used > confident.threshold_used

    def test_clamps_oob_inputs_instead_of_raising(self) -> None:
        """LLM occasionally returns prob > 1 or < 0. Treat as edge
        case — clamp and let the edge math run, don't blow up the
        whole trading loop on a malformed LLM response."""
        result = check_edge(llm_prob=1.5, market_price=0.5, confidence=0.5)
        # 1.0 - 0.5 = 0.5 edge → way above any threshold.
        assert result.passes is True

    def test_confidence_band_buckets(self) -> None:
        assert confidence_band(0.85) == "high"
        assert confidence_band(0.55) == "medium"
        assert confidence_band(0.20) == "low"

    def test_threshold_per_band(self) -> None:
        """Pin the asymmetric thresholds so a future loosening doesn't
        accidentally invert the relationship."""
        high_t = threshold_for_band("high")
        med_t = threshold_for_band("medium")
        low_t = threshold_for_band("low")
        assert high_t < med_t < low_t


# ---------------------------------------------------------------------------
# Skip-tag filter
# ---------------------------------------------------------------------------


class TestSkipTags:
    def test_blocks_sports_tag(self) -> None:
        result = should_skip_market(["sports", "nfl"], "Will the Cowboys win?")
        assert result.skip is True
        assert "skip-tag matched" in result.reason

    def test_blocks_award_show(self) -> None:
        result = should_skip_market(["awards", "oscars"], "Best picture 2026?")
        assert result.skip is True

    def test_blocks_entertainment_titles_via_phrase(self) -> None:
        # No tags, but title contains skip-phrase.
        result = should_skip_market(None, "Will Taylor Swift mention Donald Trump?")
        assert result.skip is True
        assert "title-phrase" in result.reason

    def test_passes_legitimate_market(self) -> None:
        result = should_skip_market(
            ["politics", "us-elections"],
            "Will the Federal Reserve cut rates by July?",
        )
        assert result.skip is False

    def test_case_insensitive_tag_match(self) -> None:
        result = should_skip_market(["SPORTS", "NFL"], "test")
        assert result.skip is True

    def test_empty_tags_and_title_passes(self) -> None:
        result = should_skip_market(None, "")
        assert result.skip is False

    def test_default_skip_lists_are_non_empty(self) -> None:
        """Sanity check: the default lists ship with content. Otherwise
        the filter is effectively disabled by default."""
        assert len(DEFAULT_SKIP_TAG_SLUGS) > 10
        assert len(DEFAULT_SKIP_TITLE_PHRASES) >= 4
        assert "sports" in DEFAULT_SKIP_TAG_SLUGS
        assert "mention" in DEFAULT_SKIP_TITLE_PHRASES


# ---------------------------------------------------------------------------
# Stop-loss / take-profit
# ---------------------------------------------------------------------------


class TestStopLossLevels:
    def test_buy_levels_are_below_entry_for_stop_above_for_tp(self) -> None:
        levels = calculate_stop_loss_levels(entry_price=0.60, side="BUY")
        assert levels.stop_loss_price < 0.60
        assert levels.take_profit_price > 0.60
        # Defaults: 7% stop, 20% TP.
        assert abs(levels.stop_loss_price - 0.558) < 0.001
        assert abs(levels.take_profit_price - 0.72) < 0.001

    def test_sell_levels_are_mirrored(self) -> None:
        """Selling YES at 0.60 = long NO at 0.40. Stop fires when YES
        rises (short loses); TP fires when YES falls."""
        levels = calculate_stop_loss_levels(entry_price=0.60, side="SELL")
        assert levels.stop_loss_price > 0.60
        assert levels.take_profit_price < 0.60

    def test_low_confidence_halves_the_stop(self) -> None:
        """Uncertain trades get a tighter stop — they don't deserve
        the full 7% of breathing room."""
        confident = calculate_stop_loss_levels(
            entry_price=0.60, side="BUY", confidence=0.85
        )
        uncertain = calculate_stop_loss_levels(
            entry_price=0.60, side="BUY", confidence=0.30
        )
        assert uncertain.stop_loss_pct < confident.stop_loss_pct
        # Stop sits closer to entry on uncertain.
        assert uncertain.stop_loss_price > confident.stop_loss_price

    def test_levels_clamped_to_polymarket_range(self) -> None:
        """Polymarket prices are [0.01, 0.99]. Don't ship a stop at
        zero or above one."""
        # Very high entry — TP at 0.99 × 1.20 = 1.188 → clamp to 0.99.
        levels = calculate_stop_loss_levels(entry_price=0.99, side="BUY")
        assert levels.take_profit_price <= 0.99
        # Very low entry — stop at 0.02 × 0.93 = 0.0186 → clamp to 0.01.
        levels = calculate_stop_loss_levels(entry_price=0.02, side="BUY")
        assert levels.stop_loss_price >= 0.01

    def test_invalid_entry_raises(self) -> None:
        with pytest.raises(ValueError):
            calculate_stop_loss_levels(entry_price=0.0, side="BUY")
        with pytest.raises(ValueError):
            calculate_stop_loss_levels(entry_price=1.0, side="BUY")

    def test_invalid_side_raises(self) -> None:
        with pytest.raises(ValueError):
            calculate_stop_loss_levels(entry_price=0.5, side="HOLD")


# ---------------------------------------------------------------------------
# Drawdown circuit breaker
# ---------------------------------------------------------------------------


class TestDrawdownBreaker:
    def test_pauses_on_threshold_breach(self) -> None:
        result = check_drawdown(peak_equity=1000.0, current_equity=750.0)
        assert result.paused is True  # 25% drawdown >= 20% threshold
        assert result.drawdown_pct > 0.24

    def test_within_threshold_does_not_pause(self) -> None:
        result = check_drawdown(peak_equity=1000.0, current_equity=900.0)
        assert result.paused is False

    def test_equity_above_peak_treated_as_zero_drawdown(self) -> None:
        """If current > peak (e.g. caller passed stale peak), treat as
        no drawdown — don't pause on a math edge case."""
        result = check_drawdown(peak_equity=1000.0, current_equity=1100.0)
        assert result.paused is False
        assert result.drawdown_pct == 0.0

    def test_zero_peak_returns_safe_default(self) -> None:
        """Fresh portfolio with no peak yet — don't pause, don't
        divide by zero."""
        result = check_drawdown(peak_equity=0.0, current_equity=0.0)
        assert result.paused is False

    def test_threshold_configurable(self) -> None:
        # Tight 5% threshold trips on the same equity that 20% wouldn't.
        loose = check_drawdown(1000.0, 950.0, pause_pct=0.20)
        tight = check_drawdown(1000.0, 950.0, pause_pct=0.05)
        assert loose.paused is False
        assert tight.paused is True


# ---------------------------------------------------------------------------
# Combined pre-trade decision
# ---------------------------------------------------------------------------


class TestPreTradeDecision:
    def test_allow_when_all_gates_pass(self) -> None:
        decision = evaluate_pre_trade(
            llm_prob=0.70,
            market_price=0.55,
            confidence=0.80,
            market_tags=["politics"],
            market_title="Will the Fed cut in July?",
        )
        assert decision.allow_trade is True
        assert decision.blockers == []
        assert decision.stop_loss is not None
        # Side derived from edge sign (LLM > market → YES).
        assert decision.stop_loss.side == "BUY"
        assert decision.stop_loss.stop_loss_price < 0.55

    def test_block_on_skip_tag(self) -> None:
        decision = evaluate_pre_trade(
            llm_prob=0.70,
            market_price=0.55,
            confidence=0.80,
            market_tags=["sports", "nfl"],
            market_title="Will the Cowboys cover?",
        )
        assert decision.allow_trade is False
        assert any("skip-tag" in b for b in decision.blockers)
        # No stop-loss when the trade isn't shipping.
        assert decision.stop_loss is None

    def test_block_on_no_edge(self) -> None:
        decision = evaluate_pre_trade(
            llm_prob=0.55,
            market_price=0.54,
            confidence=0.80,
            market_tags=["politics"],
            market_title="legit market",
        )
        assert decision.allow_trade is False
        assert any("edge" in b for b in decision.blockers)

    def test_no_side_decision_picks_sell_entry(self) -> None:
        """When the LLM thinks YES is overpriced, the entry is a SELL
        on the YES token (≡ BUY on the NO token). Stop levels mirror."""
        decision = evaluate_pre_trade(
            llm_prob=0.30,
            market_price=0.55,
            confidence=0.80,
            market_tags=["politics"],
            market_title="legit market",
        )
        assert decision.allow_trade is True
        assert decision.edge.side == "NO"
        assert decision.stop_loss is not None
        assert decision.stop_loss.side == "SELL"

    def test_config_override_loosens_thresholds(self) -> None:
        """A custom config with looser thresholds should let trades
        through that the defaults block."""
        from core.config import PolymarketConfig

        # 1.5% edge — would be blocked by the 4% default floor.
        cfg = PolymarketConfig(
            min_edge=0.01,
            high_confidence_edge=0.01,
            medium_confidence_edge=0.01,
            low_confidence_edge=0.02,
        )
        decision = evaluate_pre_trade(
            llm_prob=0.515,
            market_price=0.50,
            confidence=0.80,
            market_tags=["politics"],
            market_title="legit",
            config=cfg,
        )
        assert decision.allow_trade is True

    def test_config_override_can_clear_skip_tags(self) -> None:
        """Operator who wants to trade sports markets can override the
        skip list."""
        from core.config import PolymarketConfig

        cfg = PolymarketConfig(skip_tag_slugs=[], skip_title_phrases=[])
        decision = evaluate_pre_trade(
            llm_prob=0.70,
            market_price=0.55,
            confidence=0.80,
            market_tags=["sports", "nfl"],
            market_title="Will the Cowboys cover?",
            config=cfg,
        )
        assert decision.allow_trade is True


# ---------------------------------------------------------------------------
# Order-amount quantization — fixes the precision-rejection failure mode
# ---------------------------------------------------------------------------


class TestQuantizeOrder:
    def test_replicates_the_real_failure_case(self) -> None:
        """The exact (price, size) that Polymarket rejected in live
        history must now produce a valid (2-decimal-notional) order."""
        from core.polymarket_engine import quantize_order

        result = quantize_order(price=0.35, desired_size=42.85, side="BUY")
        # Notional MUST be exactly 2 decimals.
        assert (
            abs(result.notional_usdc * 100 - round(result.notional_usdc * 100)) < 1e-6
        )
        # Notional must NEVER exceed the desired (always rounds down).
        assert result.notional_usdc <= 0.35 * 42.85
        # Size must be smaller-or-equal to desired (defensive sizing).
        assert result.size <= 42.85

    def test_already_clean_amounts_pass_through_unchanged(self) -> None:
        """If the caller supplied (price, size) that already lands on
        2-decimal notional, don't shrink it unnecessarily."""
        from core.polymarket_engine import quantize_order

        # 0.50 × 20.00 = 10.00 USDC — already exact.
        result = quantize_order(price=0.50, desired_size=20.00, side="BUY")
        assert abs(result.notional_usdc - 10.00) < 1e-6
        assert abs(result.size - 20.00) < 1e-4

    def test_taker_decimals_differ_for_buy_vs_sell(self) -> None:
        """BUY uses 5-decimal taker; SELL uses 4-decimal. The size
        snap should respect the side's grid."""
        from core.polymarket_engine import quantize_order

        # Pick a price/size combo that lands cleanly in 5dp but might
        # need extra rounding in 4dp.
        buy = quantize_order(price=0.35, desired_size=42.85, side="BUY")
        sell = quantize_order(price=0.35, desired_size=42.85, side="SELL")
        # Both should have valid 2-decimal notionals.
        assert abs(buy.notional_usdc * 100 - round(buy.notional_usdc * 100)) < 1e-6
        assert abs(sell.notional_usdc * 100 - round(sell.notional_usdc * 100)) < 1e-6

    def test_dust_amounts_raise_loud(self) -> None:
        """If the desired notional floors to 0 USDC, raise — better
        than silently sending a 0-share order."""
        from core.polymarket_engine import quantize_order

        with pytest.raises(ValueError, match="floors to 0"):
            quantize_order(price=0.35, desired_size=0.01, side="BUY")

    def test_invalid_inputs_raise(self) -> None:
        from core.polymarket_engine import quantize_order

        with pytest.raises(ValueError):
            quantize_order(price=0.0, desired_size=10.0, side="BUY")
        with pytest.raises(ValueError):
            quantize_order(price=0.5, desired_size=-5.0, side="BUY")
        with pytest.raises(ValueError):
            quantize_order(price=0.5, desired_size=10.0, side="HOLD")


# ---------------------------------------------------------------------------
# Safe-compounder strategy
# ---------------------------------------------------------------------------


class TestEstimateTrueProbNo:
    def test_low_yes_high_no(self) -> None:
        from core.polymarket_engine import estimate_true_prob_no

        # YES at 5¢ → NO probability should be high.
        prob = estimate_true_prob_no(yes_last_price=0.05, days_to_expiry=10.0)
        assert prob > 0.85

    def test_high_yes_low_no(self) -> None:
        from core.polymarket_engine import estimate_true_prob_no

        # YES at 90¢ → NO probability should be low.
        prob = estimate_true_prob_no(yes_last_price=0.90, days_to_expiry=10.0)
        assert prob < 0.30

    def test_far_expiry_pulls_toward_uncertainty(self) -> None:
        """A bet 60+ days out should be less confident than the same
        bet 1 day out — more time = more can change."""
        from core.polymarket_engine import estimate_true_prob_no

        near = estimate_true_prob_no(0.05, days_to_expiry=1.0)
        far = estimate_true_prob_no(0.05, days_to_expiry=60.0)
        assert near > far
        # And the long-dated version should be pulled toward 0.5.
        assert abs(far - 0.5) < abs(near - 0.5)


class TestKellyPositionSize:
    def test_positive_edge_returns_positive_size(self) -> None:
        from core.polymarket_engine import kelly_position_size

        # NO @ 0.85, true prob = 0.95 → strong edge.
        size = kelly_position_size(
            estimated_win_prob=0.95, price=0.85, portfolio_value=1000.0
        )
        assert size > 0
        # Capped at 10% of portfolio.
        assert size <= 100.0

    def test_no_edge_returns_zero(self) -> None:
        from core.polymarket_engine import kelly_position_size

        # NO @ 0.95, true prob = 0.85 → negative edge.
        size = kelly_position_size(
            estimated_win_prob=0.85, price=0.95, portfolio_value=1000.0
        )
        assert size == 0.0

    def test_zero_portfolio_returns_zero(self) -> None:
        from core.polymarket_engine import kelly_position_size

        size = kelly_position_size(
            estimated_win_prob=0.95, price=0.85, portfolio_value=0.0
        )
        assert size == 0.0

    def test_cap_pct_respected(self) -> None:
        """Even a wildly favorable Kelly fraction must cap at the
        operator-set ceiling."""
        from core.polymarket_engine import kelly_position_size

        size = kelly_position_size(
            estimated_win_prob=0.99,
            price=0.50,
            portfolio_value=1000.0,
            cap_pct=0.05,  # 5% cap
        )
        assert size <= 50.0


class TestSafeCompounder:
    def test_qualifying_market_returns_full_candidate(self) -> None:
        from core.polymarket_engine import score_safe_compounder

        candidate = score_safe_compounder(
            yes_last_price=0.04,
            lowest_no_ask=0.92,
            volume=350.0,
            days_to_expiry=12.0,
            portfolio_value=500.0,
        )
        assert candidate.qualifies is True
        # Suggested limit sits 1¢ inside the lowest NO ask.
        assert abs(candidate.suggested_limit_price - 0.91) < 0.001
        # Size is positive USDC.
        assert candidate.suggested_size_usdc > 0
        assert "edge" in candidate.rationale or "NO" in candidate.rationale

    def test_low_no_ask_disqualifies(self) -> None:
        from core.polymarket_engine import score_safe_compounder

        # Lowest NO ask at 70¢ — below the 80¢ floor.
        candidate = score_safe_compounder(
            yes_last_price=0.30,
            lowest_no_ask=0.70,
            volume=350.0,
            days_to_expiry=12.0,
            portfolio_value=500.0,
        )
        assert candidate.qualifies is False
        assert "lowest_no_ask" in candidate.rationale

    def test_low_volume_disqualifies(self) -> None:
        from core.polymarket_engine import score_safe_compounder

        candidate = score_safe_compounder(
            yes_last_price=0.04,
            lowest_no_ask=0.92,
            volume=2.0,  # below $10 floor
            days_to_expiry=12.0,
            portfolio_value=500.0,
        )
        assert candidate.qualifies is False
        assert "volume" in candidate.rationale

    def test_no_edge_disqualifies(self) -> None:
        """If the live ask already prices in the high probability,
        there's no edge to capture."""
        from core.polymarket_engine import score_safe_compounder

        # YES at 5¢ → est NO ≈ 0.95. NO ask at 0.94 → only 1% edge.
        candidate = score_safe_compounder(
            yes_last_price=0.05,
            lowest_no_ask=0.94,
            volume=350.0,
            days_to_expiry=12.0,
            portfolio_value=500.0,
        )
        assert candidate.qualifies is False
        assert "edge" in candidate.rationale

    def test_too_far_out_disqualifies(self) -> None:
        from core.polymarket_engine import score_safe_compounder

        candidate = score_safe_compounder(
            yes_last_price=0.04,
            lowest_no_ask=0.92,
            volume=350.0,
            days_to_expiry=120.0,  # > 60 day max
            portfolio_value=500.0,
        )
        assert candidate.qualifies is False
        assert "max_days" in candidate.rationale

    def test_too_close_to_expiry_disqualifies(self) -> None:
        from core.polymarket_engine import score_safe_compounder

        candidate = score_safe_compounder(
            yes_last_price=0.04,
            lowest_no_ask=0.92,
            volume=350.0,
            days_to_expiry=0.1,  # below 0.5 day floor
            portfolio_value=500.0,
        )
        assert candidate.qualifies is False
        assert "min_days" in candidate.rationale

    def test_position_size_caps_at_10pct(self) -> None:
        from core.polymarket_engine import score_safe_compounder

        candidate = score_safe_compounder(
            yes_last_price=0.04,
            lowest_no_ask=0.92,
            volume=350.0,
            days_to_expiry=12.0,
            portfolio_value=10000.0,
        )
        assert candidate.qualifies is True
        # 10% of $10000 = $1000 cap.
        assert candidate.suggested_size_usdc <= 1000.0

    def test_zero_portfolio_disqualifies_via_kelly(self) -> None:
        from core.polymarket_engine import score_safe_compounder

        candidate = score_safe_compounder(
            yes_last_price=0.04,
            lowest_no_ask=0.92,
            volume=350.0,
            days_to_expiry=12.0,
            portfolio_value=0.0,
        )
        assert candidate.qualifies is False
        assert "Kelly" in candidate.rationale
