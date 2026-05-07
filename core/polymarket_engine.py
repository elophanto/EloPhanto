"""Polymarket risk-management engine — edge filter + stop-loss + skip tags.

Pure Python module. No I/O, no DB, no LLM calls. Decides things; the
caller (a tool, the skill, future trading code) acts on the decision.

Why this exists:
    Live trade history showed the agent buying mid-probability markets
    (avg BUY price 0.599) and never selling losers (avg SELL price
    0.864 — only winners get sold). Single losing positions held to
    resolution at 0¢ dominate P&L. The architecture had zero
    constraints between LLM "confidence" and the place_order call.

    The fix is structural: every trade goes through three gates before
    it ships. Each gate is a small pure function with a clear contract.

    This module is intentionally not coupled to ``py-clob-client`` —
    the actual order placement still happens via the existing skill /
    shell flow. We only enforce the rules.

Design beats borrowed from zostaff/poly-trading-bot:
  * Edge filter with confidence-asymmetric thresholds (high-confidence
    needs less edge; low-confidence needs more).
  * Skip-tag list for sports / entertainment / awards markets — pure
    noise that LLM "predictions" have no edge against sharps.
  * Per-position stop-loss + take-profit at fixed pcts of entry.
  * Drawdown circuit breaker.

See `docs/64-POLYMARKET.md` (existing) and `tools/polymarket/` for
the tool surface that wraps these decisions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
#
# Defaults mirror zostaff's loosened-2026-03-29 thresholds. These are
# CONSERVATIVE for an agent that previously had no constraints — easier
# to start tight and loosen on measured evidence than the reverse.

# Edge thresholds (decimal — 0.04 = 4%).
_DEFAULT_MIN_EDGE = 0.04
_DEFAULT_HIGH_CONFIDENCE_EDGE = 0.03
_DEFAULT_MEDIUM_CONFIDENCE_EDGE = 0.05
_DEFAULT_LOW_CONFIDENCE_EDGE = 0.08

# Confidence band cutoffs.
_DEFAULT_HIGH_CONFIDENCE = 0.70
_DEFAULT_LOW_CONFIDENCE = 0.40

# Stop-loss / take-profit defaults (pct of entry).
_DEFAULT_STOP_LOSS_PCT = 0.07
_DEFAULT_TAKE_PROFIT_PCT = 0.20

# Skip-tag list — Polymarket parent-event tag slugs that are pure
# noise for LLM-predicted directional trades. Sourced from
# zostaff/poly-trading-bot SKIP_TAG_SLUGS, expanded slightly.
DEFAULT_SKIP_TAG_SLUGS: tuple[str, ...] = (
    # Sports: sharp markets, no LLM edge
    "sports",
    "soccer",
    "basketball",
    "nba",
    "epl",
    "ucl",
    "champions-league",
    "fifa-world-cup",
    "f1",
    "formula1",
    "nfl",
    "mlb",
    "nhl",
    "ufc",
    "pga",
    "tennis",
    "boxing",
    "esports",
    # Entertainment: too narrative-driven, low signal
    "awards",
    "oscars",
    "emmys",
    "grammys",
    "music",
    "pop-culture",
    "entertainment",
    "tv",
    "movies",
    "gaming",
    "games",
    "celebrity",
    "kpop",
)

# Title-phrase blocklist — markets phrased as social-media garbage even
# outside skip tags. Substring match (case-insensitive).
DEFAULT_SKIP_TITLE_PHRASES: tuple[str, ...] = (
    "mention",
    "say in",
    "speech mention",
    "address mention",
    "tweet about",
    "post about",
    "wear",
    "outfit",
)

# Drawdown circuit-breaker default — if portfolio is down this much
# from peak in the lookback window, pause new entries.
_DEFAULT_DRAWDOWN_PAUSE_PCT = 0.20


# ---------------------------------------------------------------------------
# Edge filter
# ---------------------------------------------------------------------------


@dataclass
class EdgeResult:
    """Outcome of an edge check. ``passes`` is the only thing callers
    must inspect; the rest is for telemetry / logging."""

    passes: bool
    edge: float  # llm_prob - market_price (signed)
    edge_abs: float
    threshold_used: float
    band: str  # "high" | "medium" | "low"
    side: str  # "YES" | "NO"
    reason: str


def confidence_band(
    confidence: float,
    *,
    high: float = _DEFAULT_HIGH_CONFIDENCE,
    low: float = _DEFAULT_LOW_CONFIDENCE,
) -> str:
    """Bucket confidence into ``high`` / ``medium`` / ``low``."""
    if confidence >= high:
        return "high"
    if confidence < low:
        return "low"
    return "medium"


def threshold_for_band(
    band: str,
    *,
    high_edge: float = _DEFAULT_HIGH_CONFIDENCE_EDGE,
    medium_edge: float = _DEFAULT_MEDIUM_CONFIDENCE_EDGE,
    low_edge: float = _DEFAULT_LOW_CONFIDENCE_EDGE,
) -> float:
    """Confidence-asymmetric edge thresholds.

    The LLM's confidence is a self-report, not a calibrated probability.
    We trust it less when it claims to be uncertain — those are the
    exact bets where the market is most likely correct and we're most
    likely paying spread + fees for nothing.
    """
    if band == "high":
        return high_edge
    if band == "low":
        return low_edge
    return medium_edge


def check_edge(
    llm_prob: float,
    market_price: float,
    confidence: float,
    *,
    min_edge: float = _DEFAULT_MIN_EDGE,
    high_confidence_edge: float = _DEFAULT_HIGH_CONFIDENCE_EDGE,
    medium_confidence_edge: float = _DEFAULT_MEDIUM_CONFIDENCE_EDGE,
    low_confidence_edge: float = _DEFAULT_LOW_CONFIDENCE_EDGE,
    high_confidence_cutoff: float = _DEFAULT_HIGH_CONFIDENCE,
    low_confidence_cutoff: float = _DEFAULT_LOW_CONFIDENCE,
) -> EdgeResult:
    """The pre-trade gate.

    Args:
        llm_prob: LLM's estimated probability of the YES outcome [0, 1].
        market_price: Current YES price [0, 1].
        confidence: LLM's self-reported confidence [0, 1].

    Returns an EdgeResult. Block the trade if ``passes is False``.

    A trade is allowed only when the absolute edge ``|llm_prob -
    market_price|`` exceeds BOTH the floor (``min_edge``) and the
    confidence-band-specific threshold. Sign of edge picks YES vs NO.
    """
    # Validate inputs — clamp to legal range without raising; bad
    # inputs from the LLM should fail closed (block the trade), not
    # explode the trading loop.
    llm_prob = max(0.0, min(1.0, float(llm_prob)))
    market_price = max(0.0, min(1.0, float(market_price)))
    confidence = max(0.0, min(1.0, float(confidence)))

    edge = llm_prob - market_price
    edge_abs = abs(edge)
    side = "YES" if edge > 0 else "NO"

    band = confidence_band(
        confidence, high=high_confidence_cutoff, low=low_confidence_cutoff
    )
    band_threshold = threshold_for_band(
        band,
        high_edge=high_confidence_edge,
        medium_edge=medium_confidence_edge,
        low_edge=low_confidence_edge,
    )
    threshold = max(min_edge, band_threshold)

    if edge_abs < threshold:
        return EdgeResult(
            passes=False,
            edge=edge,
            edge_abs=edge_abs,
            threshold_used=threshold,
            band=band,
            side=side,
            reason=(
                f"edge {edge_abs:.3f} < threshold {threshold:.3f} "
                f"(confidence band: {band})"
            ),
        )

    return EdgeResult(
        passes=True,
        edge=edge,
        edge_abs=edge_abs,
        threshold_used=threshold,
        band=band,
        side=side,
        reason=(
            f"edge {edge_abs:.3f} >= threshold {threshold:.3f} "
            f"(confidence band: {band}, side: {side})"
        ),
    )


# ---------------------------------------------------------------------------
# Skip-tag filter
# ---------------------------------------------------------------------------


@dataclass
class SkipResult:
    """Outcome of a skip-tag check."""

    skip: bool
    reason: str


def should_skip_market(
    market_tags: list[str] | tuple[str, ...] | None,
    market_title: str = "",
    *,
    skip_tag_slugs: tuple[str, ...] = DEFAULT_SKIP_TAG_SLUGS,
    skip_title_phrases: tuple[str, ...] = DEFAULT_SKIP_TITLE_PHRASES,
) -> SkipResult:
    """Block sports / entertainment / awards markets.

    Args:
        market_tags: Polymarket event tag slugs (e.g. ``["sports",
            "nfl"]``). Case-insensitive match against ``skip_tag_slugs``.
        market_title: Market question text. Substring-matched (case-
            insensitive) against ``skip_title_phrases``.

    Returns a SkipResult. Skip the trade if ``skip is True``.
    """
    skip_tag_set = {t.lower() for t in skip_tag_slugs}
    if market_tags:
        for tag in market_tags:
            if not isinstance(tag, str):
                continue
            if tag.lower().strip() in skip_tag_set:
                return SkipResult(skip=True, reason=f"skip-tag matched: {tag.lower()}")

    if market_title:
        title_lower = market_title.lower()
        for phrase in skip_title_phrases:
            if phrase.lower() in title_lower:
                return SkipResult(
                    skip=True, reason=f"skip-title-phrase matched: {phrase!r}"
                )

    return SkipResult(skip=False, reason="market is in scope")


# ---------------------------------------------------------------------------
# Stop-loss / take-profit calculator
# ---------------------------------------------------------------------------


@dataclass
class StopLossLevels:
    """Companion exit levels for a position. The caller places one
    ``stop_loss_price`` and one ``take_profit_price`` limit order
    against the position immediately on fill."""

    entry_price: float
    side: str  # "BUY" | "SELL"
    stop_loss_price: float
    take_profit_price: float
    stop_loss_pct: float
    take_profit_pct: float
    rationale: str


def calculate_stop_loss_levels(
    entry_price: float,
    side: str = "BUY",
    *,
    stop_loss_pct: float = _DEFAULT_STOP_LOSS_PCT,
    take_profit_pct: float = _DEFAULT_TAKE_PROFIT_PCT,
    confidence: float | None = None,
) -> StopLossLevels:
    """Compute exit levels for a Polymarket position.

    For a BUY at $0.60:
      stop  = 0.60 × (1 - 0.07) = $0.558  (sell if it drops 7%)
      tp    = 0.60 × (1 + 0.20) = $0.720  (sell if it rises 20%)

    For a SELL (short YES, equivalent to long NO):
      stop  = 0.60 × (1 + 0.07) = $0.642
      tp    = 0.60 × (1 - 0.20) = $0.480

    Confidence (optional) tightens the stop on uncertain trades — a
    50/50 bet doesn't deserve a wide stop. High-confidence trades get
    the default; low-confidence trades get half the stop distance.
    """
    if entry_price <= 0 or entry_price >= 1:
        raise ValueError(
            f"entry_price must be in (0, 1) for Polymarket; got {entry_price}"
        )
    side_upper = side.upper()
    if side_upper not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL; got {side!r}")

    # Confidence adjustment: tighter stop for low-confidence bets.
    effective_stop_pct = stop_loss_pct
    rationale_parts = [f"base stop {stop_loss_pct:.1%}"]
    if confidence is not None:
        if confidence < _DEFAULT_LOW_CONFIDENCE:
            effective_stop_pct = stop_loss_pct * 0.5
            rationale_parts.append(
                f"halved to {effective_stop_pct:.1%} "
                f"(low confidence {confidence:.2f})"
            )
        elif confidence >= _DEFAULT_HIGH_CONFIDENCE:
            rationale_parts.append(f"high confidence {confidence:.2f}, no adj")

    if side_upper == "BUY":
        stop = entry_price * (1.0 - effective_stop_pct)
        tp = entry_price * (1.0 + take_profit_pct)
    else:  # SELL — mirror
        stop = entry_price * (1.0 + effective_stop_pct)
        tp = entry_price * (1.0 - take_profit_pct)

    # Clamp to Polymarket's [0.01, 0.99] valid range. Orders at the
    # edge round defensively away from the bound.
    stop = max(0.01, min(0.99, round(stop, 4)))
    tp = max(0.01, min(0.99, round(tp, 4)))

    return StopLossLevels(
        entry_price=entry_price,
        side=side_upper,
        stop_loss_price=stop,
        take_profit_price=tp,
        stop_loss_pct=effective_stop_pct,
        take_profit_pct=take_profit_pct,
        rationale="; ".join(rationale_parts),
    )


# ---------------------------------------------------------------------------
# Drawdown circuit breaker
# ---------------------------------------------------------------------------


@dataclass
class CircuitBreakerResult:
    """Outcome of the drawdown check."""

    paused: bool
    drawdown_pct: float
    threshold_pct: float
    reason: str


def check_drawdown(
    peak_equity: float,
    current_equity: float,
    *,
    pause_pct: float = _DEFAULT_DRAWDOWN_PAUSE_PCT,
) -> CircuitBreakerResult:
    """Pause new entries if portfolio is down ``pause_pct`` from peak.

    The agent can still close positions while paused — only NEW
    positions are blocked. This is the difference between "had a bad
    week" and "blew up the account on tilt."

    Args:
        peak_equity: Highest portfolio value observed in the lookback
            window (operator decides the window — typically 30 days).
        current_equity: Current portfolio value.
    """
    if peak_equity <= 0:
        return CircuitBreakerResult(
            paused=False,
            drawdown_pct=0.0,
            threshold_pct=pause_pct,
            reason="no peak equity yet",
        )
    drawdown = (peak_equity - current_equity) / peak_equity
    drawdown = max(0.0, drawdown)  # clamp — equity above peak is not a drawdown
    if drawdown >= pause_pct:
        return CircuitBreakerResult(
            paused=True,
            drawdown_pct=drawdown,
            threshold_pct=pause_pct,
            reason=(
                f"drawdown {drawdown:.1%} >= threshold {pause_pct:.1%} "
                f"(peak={peak_equity:.2f}, current={current_equity:.2f})"
            ),
        )
    return CircuitBreakerResult(
        paused=False,
        drawdown_pct=drawdown,
        threshold_pct=pause_pct,
        reason=(f"drawdown {drawdown:.1%} below threshold {pause_pct:.1%}"),
    )


# ---------------------------------------------------------------------------
# Combined pre-trade gate
# ---------------------------------------------------------------------------


@dataclass
class PreTradeDecision:
    """Aggregated result of the three pre-trade checks. Use this as
    the single decision point before any place_order call."""

    allow_trade: bool
    edge: EdgeResult
    skip: SkipResult
    stop_loss: StopLossLevels | None
    blockers: list[str] = field(default_factory=list)


def evaluate_pre_trade(
    *,
    llm_prob: float,
    market_price: float,
    confidence: float,
    market_tags: list[str] | tuple[str, ...] | None = None,
    market_title: str = "",
    config: Any = None,
) -> PreTradeDecision:
    """One-shot evaluator. Combines edge + skip-tag + stop-loss into a
    single decision the calling tool / skill can act on.

    ``config`` is an optional ``PolymarketConfig`` (see
    :mod:`core.config`). When omitted, module defaults apply.
    """
    # Pull tunables from config if provided, else fall through to the
    # module-level defaults baked into each check's signature.
    skip_tags = DEFAULT_SKIP_TAG_SLUGS
    skip_phrases = DEFAULT_SKIP_TITLE_PHRASES
    edge_kwargs: dict[str, float] = {}
    sl_kwargs: dict[str, float] = {}
    if config is not None:
        skip_tags = tuple(getattr(config, "skip_tag_slugs", skip_tags))
        skip_phrases = tuple(getattr(config, "skip_title_phrases", skip_phrases))
        for key in (
            "min_edge",
            "high_confidence_edge",
            "medium_confidence_edge",
            "low_confidence_edge",
            "high_confidence_cutoff",
            "low_confidence_cutoff",
        ):
            if hasattr(config, key):
                edge_kwargs[key] = float(getattr(config, key))
        for key in ("stop_loss_pct", "take_profit_pct"):
            if hasattr(config, key):
                sl_kwargs[key] = float(getattr(config, key))

    skip = should_skip_market(
        market_tags,
        market_title,
        skip_tag_slugs=skip_tags,
        skip_title_phrases=skip_phrases,
    )
    edge = check_edge(llm_prob, market_price, confidence, **edge_kwargs)

    blockers: list[str] = []
    if skip.skip:
        blockers.append(f"skip-tag: {skip.reason}")
    if not edge.passes:
        blockers.append(f"edge: {edge.reason}")

    # Stop-loss levels are computed only if the trade is going to ship —
    # caller needs them paired with the entry order. Side derived from
    # edge sign.
    stop_loss: StopLossLevels | None = None
    if not blockers:
        # If the LLM picked YES (edge > 0), entry is at market YES price
        # via BUY. If NO (edge < 0), entry is at (1 - YES) NO price via
        # BUY-NO, equivalent to short YES — we represent this as side
        # SELL on the YES token. The skill chooses the actual order
        # leg; we just provide the levels.
        entry_side = "BUY" if edge.side == "YES" else "SELL"
        try:
            stop_loss = calculate_stop_loss_levels(
                entry_price=market_price,
                side=entry_side,
                confidence=confidence,
                **sl_kwargs,
            )
        except ValueError as e:
            blockers.append(f"stop-loss calc failed: {e}")

    return PreTradeDecision(
        allow_trade=not blockers,
        edge=edge,
        skip=skip,
        stop_loss=stop_loss,
        blockers=blockers,
    )


# ---------------------------------------------------------------------------
# Order amount quantization — fix the 75% precision-error failure mode
# ---------------------------------------------------------------------------
#
# Polymarket rejects orders whose maker amount (price × size in USDC)
# has more than 2 decimals, or whose taker amount has more than 4-5
# decimals. Live trade history showed 6 of 8 failed orders hitting
# this exact precision rule:
#   "invalid amounts, the market buy orders maker amount supports a
#    max accuracy of 2 decimals, taker amount a max of 5 decimals"
#
# Fix: snap size to the nearest value that makes price × size land on
# 2 decimals exactly. Down-rounds (never up) so we never accidentally
# size a position larger than the operator authorized.

# Polymarket precision rules from the rejection messages we logged.
_MAKER_DECIMALS = 2  # USDC notional (price × size for BUY)
_TAKER_DECIMALS_BUY = 5  # share count for BUY market orders
_TAKER_DECIMALS_SELL = 4  # share count for SELL orders


@dataclass
class QuantizedOrder:
    """A size + price pair that satisfies Polymarket's precision rules."""

    price: float
    size: float
    notional_usdc: float  # price × size, exactly 2 decimals
    side: str  # "BUY" | "SELL"
    rationale: str


def quantize_order(
    *,
    price: float,
    desired_size: float,
    side: str = "BUY",
) -> QuantizedOrder:
    """Snap (price, desired_size) onto Polymarket's precision grid so
    the order is accepted instead of rejected.

    The constraint: ``price × size`` (maker amount in USDC) must fit
    in 2 decimals. We hold ``price`` fixed and round ``size`` DOWN to
    the largest value that keeps the product at 2 decimals.

    Concrete example from the live failure logs:
        price = 0.35, desired_size = 42.85 → 0.35 × 42.85 = 14.9975
        → not 2 decimals → REJECTED.
        Snapped: notional = floor(14.9975 × 100) / 100 = 14.99.
                 size = 14.99 / 0.35 = 42.8285714... rounded to 5 dp
                 = 42.82857. Notional now: 0.35 × 42.82857 = 14.9899...
        → loop once more: notional = 14.99 → exact.

    Always rounds DOWN — never sizes a position larger than the caller
    asked for. Returns the snapped size + actual notional that will
    execute.
    """
    side_upper = side.upper()
    if side_upper not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL; got {side!r}")
    if price <= 0 or price >= 1:
        raise ValueError(f"price must be in (0, 1) for Polymarket; got {price}")
    if desired_size <= 0:
        raise ValueError(f"desired_size must be > 0; got {desired_size}")

    taker_decimals = (
        _TAKER_DECIMALS_BUY if side_upper == "BUY" else _TAKER_DECIMALS_SELL
    )

    # Step 1: floor the desired notional to 2 decimals.
    raw_notional = price * desired_size
    quantum = 10**_MAKER_DECIMALS  # 100
    floored_notional = int(raw_notional * quantum) / quantum

    if floored_notional <= 0:
        raise ValueError(
            f"price={price} × desired_size={desired_size} = {raw_notional}, "
            f"which floors to 0 USDC at {_MAKER_DECIMALS}-decimal precision. "
            "Increase desired_size or use a higher-priced market."
        )

    # Step 2: derive size from the snapped notional, rounded to taker-
    # decimals precision.
    snapped_size = round(floored_notional / price, taker_decimals)

    # Step 3: re-floor in case round-to-decimals nudged the product
    # back over the maker quantum (rounding is bidirectional; floor
    # isn't). Take the smaller of (a) the size we computed and (b)
    # the largest size whose product with price stays at 2 decimals.
    final_notional = round(price * snapped_size, _MAKER_DECIMALS)
    if abs(price * snapped_size - final_notional) > 1e-9:
        # The snapped size, when multiplied by price, doesn't land
        # exactly on 2 decimals. Step DOWN by one taker-quantum and
        # re-check.
        taker_quantum = 10 ** (-taker_decimals)
        snapped_size = round(snapped_size - taker_quantum, taker_decimals)
        final_notional = round(price * snapped_size, _MAKER_DECIMALS)

    return QuantizedOrder(
        price=price,
        size=snapped_size,
        notional_usdc=final_notional,
        side=side_upper,
        rationale=(
            f"desired notional {raw_notional:.6f} → snapped {final_notional} "
            f"USDC (size {desired_size} → {snapped_size})"
        ),
    )


# ---------------------------------------------------------------------------
# Safe-compounder strategy — NO-side, high-certainty, edge-gated
# ---------------------------------------------------------------------------
#
# Ported from zostaff/poly-trading-bot's safe_compounder.py. The
# structural insight: directional LLM bets on mid-probability markets
# bleed P&L because the agent doesn't have edge against sharps. NO-
# side bets on near-certain outcomes (lowest_no_ask > $0.80) at the
# top of the book, with a measurable edge over the live ask, are
# structurally favored on Polymarket given the fee structure.
#
# This is not a magic profit machine. It's a baseline strategy with
# lower variance than directional betting. Use as a sister to the
# LLM directional bot — different risk profile, different cadence,
# both running in parallel via the resource-typed scheduler.

# Strategy thresholds — match zostaff's defaults.
_SAFE_COMPOUNDER_MIN_NO_ASK = 0.80  # only trade when NO ≥ this (high prob NO wins)
_SAFE_COMPOUNDER_MIN_EDGE = 0.03  # 3% edge over current ask
_SAFE_COMPOUNDER_MIN_VOLUME = 10  # USDC; below this, orderbook is meaningless
_SAFE_COMPOUNDER_MAX_POSITION_PCT = 0.10  # 10% of portfolio per position
_SAFE_COMPOUNDER_MIN_DAYS_TO_EXPIRY = 0.5  # avoid sub-half-day uncertainty
_SAFE_COMPOUNDER_MAX_DAYS_TO_EXPIRY = 60.0  # too far out → too much can change
# Maker offset — place limit at (lowest_no_ask - this) so we sit on the
# book and earn maker rebates instead of paying taker fees.
_SAFE_COMPOUNDER_MAKER_OFFSET = 0.01


def estimate_true_prob_no(yes_last_price: float, days_to_expiry: float) -> float:
    """Rough estimate of NO's true probability from YES last price +
    time-to-expiry. Lower YES price = higher NO probability; less time
    until resolution = stronger conviction (less time for the YES
    outcome to materialize).

    Default behavior:
        estimated_no_prob = 1 - yes_last_price

    Time adjustments:
      * Near expiry (< 3 days): small certainty *bump* — if YES is at
        3¢ with a day left, the NO outcome is approaching certainty.
      * Far from expiry (> 30 days): small certainty *discount* — more
        time means more can change. The discount is gentle (a few %)
        so we don't kill obviously favorable bets that just happen to
        be a couple weeks out.

    This is heuristic, not Bayesian. The real edge check is against
    the LIVE NO ask price, not this estimate.

    The previous version pulled toward 0.5 at distance, which was
    too aggressive — qualifying markets fell just below the 3% edge
    floor when they shouldn't have. Tightened 2026-05-07.
    """
    if not 0 <= yes_last_price <= 1:
        raise ValueError(f"yes_last_price out of [0,1]: {yes_last_price}")
    base_no_prob = 1.0 - yes_last_price

    if days_to_expiry < 3.0:
        # Last-3-days bump: nudge toward whichever side is dominant.
        # Half-cent boost per remaining day of certainty.
        bump = 0.01 * (3.0 - max(0.0, days_to_expiry))
        if base_no_prob >= 0.5:
            adjusted = base_no_prob + bump
        else:
            adjusted = base_no_prob - bump
    elif days_to_expiry > 30.0:
        # Far-from-expiry discount: pull a small fraction toward 0.5.
        # At 60 days, discount the certainty by ~3% (0.96 → 0.93).
        excess = min(60.0, days_to_expiry) - 30.0  # 0..30
        discount = excess / 30.0 * 0.05  # 0..0.05
        adjusted = base_no_prob * (1.0 - discount) + 0.5 * discount
    else:
        adjusted = base_no_prob

    return max(0.0, min(1.0, adjusted))


def kelly_position_size(
    *,
    estimated_win_prob: float,
    price: float,
    portfolio_value: float,
    cap_pct: float = _SAFE_COMPOUNDER_MAX_POSITION_PCT,
) -> float:
    """Kelly fractional sizing for a binary bet, capped at ``cap_pct``
    of portfolio. Returns USDC notional to deploy.

    For a NO bet at ``price`` (you stake ``price`` to win 1):
        b = (1 - price) / price       # net odds
        f* = (p*b - q) / b            # Kelly fraction of bankroll

    Where p = estimated_win_prob (NO probability) and q = 1 - p.
    Negative or tiny f* → zero size (don't trade).
    """
    if portfolio_value <= 0:
        return 0.0
    if not 0 < price < 1:
        return 0.0
    if not 0 <= estimated_win_prob <= 1:
        return 0.0
    p = estimated_win_prob
    q = 1.0 - p
    b = (1.0 - price) / price
    if b <= 0:
        return 0.0
    f_star = (p * b - q) / b
    if f_star <= 0:
        return 0.0
    # Cap fraction; Kelly is theoretically right but operationally
    # ruthless — half-Kelly or capped is what you actually want.
    f_capped = min(f_star * 0.5, cap_pct)  # half-Kelly + hard cap
    return round(portfolio_value * f_capped, 2)


@dataclass
class SafeCompounderCandidate:
    """Output of safe-compounder evaluation for one market."""

    qualifies: bool
    estimated_no_prob: float
    edge: float
    suggested_limit_price: float
    suggested_size_usdc: float
    rationale: str


def score_safe_compounder(
    *,
    yes_last_price: float,
    lowest_no_ask: float,
    volume: float,
    days_to_expiry: float,
    portfolio_value: float,
    min_no_ask: float = _SAFE_COMPOUNDER_MIN_NO_ASK,
    min_edge: float = _SAFE_COMPOUNDER_MIN_EDGE,
    min_volume: float = _SAFE_COMPOUNDER_MIN_VOLUME,
    min_days: float = _SAFE_COMPOUNDER_MIN_DAYS_TO_EXPIRY,
    max_days: float = _SAFE_COMPOUNDER_MAX_DAYS_TO_EXPIRY,
    maker_offset: float = _SAFE_COMPOUNDER_MAKER_OFFSET,
    max_position_pct: float = _SAFE_COMPOUNDER_MAX_POSITION_PCT,
) -> SafeCompounderCandidate:
    """Score a single Polymarket market for the safe-compounder
    strategy. Returns ``qualifies=False`` with a reason whenever any
    constraint is violated; ``qualifies=True`` plus suggested limit
    price + Kelly-capped size when the market clears every bar.

    Use as a single market evaluator. The agent loops candidate
    markets through this; for each ``qualifies=True`` it then runs
    ``polymarket_pre_trade`` for the standard edge/skip/stop-loss
    pass and places the order.
    """
    reasons: list[str] = []

    if lowest_no_ask < min_no_ask:
        reasons.append(
            f"lowest_no_ask {lowest_no_ask:.3f} < min_no_ask {min_no_ask:.2f}"
        )
    if volume < min_volume:
        reasons.append(f"volume {volume:.2f} < min_volume {min_volume:.2f}")
    if days_to_expiry < min_days:
        reasons.append(f"days_to_expiry {days_to_expiry:.2f} < min_days {min_days:.2f}")
    if days_to_expiry > max_days:
        reasons.append(f"days_to_expiry {days_to_expiry:.2f} > max_days {max_days:.2f}")

    estimated_no_prob = estimate_true_prob_no(yes_last_price, days_to_expiry)
    edge = estimated_no_prob - lowest_no_ask
    if edge < min_edge:
        reasons.append(
            f"edge {edge:.3f} < min_edge {min_edge:.2f} "
            f"(est_no_prob {estimated_no_prob:.3f}, "
            f"lowest_no_ask {lowest_no_ask:.3f})"
        )

    if reasons:
        return SafeCompounderCandidate(
            qualifies=False,
            estimated_no_prob=estimated_no_prob,
            edge=edge,
            suggested_limit_price=0.0,
            suggested_size_usdc=0.0,
            rationale="; ".join(reasons),
        )

    # Maker order at lowest_no_ask - 1¢ — sits on the book, earns rebates
    # instead of paying taker fees. Clamp away from edges.
    suggested_price = max(0.01, min(0.99, round(lowest_no_ask - maker_offset, 4)))
    suggested_size_usdc = kelly_position_size(
        estimated_win_prob=estimated_no_prob,
        price=suggested_price,
        portfolio_value=portfolio_value,
        cap_pct=max_position_pct,
    )

    if suggested_size_usdc <= 0:
        return SafeCompounderCandidate(
            qualifies=False,
            estimated_no_prob=estimated_no_prob,
            edge=edge,
            suggested_limit_price=suggested_price,
            suggested_size_usdc=0.0,
            rationale=(
                f"Kelly returned non-positive size at price "
                f"{suggested_price:.3f} with est_no_prob "
                f"{estimated_no_prob:.3f}"
            ),
        )

    return SafeCompounderCandidate(
        qualifies=True,
        estimated_no_prob=estimated_no_prob,
        edge=edge,
        suggested_limit_price=suggested_price,
        suggested_size_usdc=suggested_size_usdc,
        rationale=(
            f"NO @ {suggested_price:.3f} (1¢ inside lowest_no_ask "
            f"{lowest_no_ask:.3f}); est NO prob {estimated_no_prob:.3f}; "
            f"edge {edge:.3f}; size ${suggested_size_usdc:.2f} "
            f"(half-Kelly capped at {max_position_pct:.0%})"
        ),
    )
