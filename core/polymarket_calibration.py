"""Polymarket calibration audit — pure math.

Two questions every prediction-market bot must be able to answer:

1. **Is the LLM calibrated?** When it says "70% confidence", does the
   resolved win rate actually land near 70%? Bucket by stated
   probability and compare claimed vs realized.

2. **Do we have edge over the market?** When we enter at $0.40, does
   the market actually resolve YES 40% of the time? Bucket by entry
   price and compare market-implied vs realized. (This is the chart
   in the Polymarket Quantitative Trading Framework image.)

Plus Brier score (overall probabilistic accuracy) and maker fill rate
(how often post-only orders we placed actually filled before
resolution).

Pure functions only — no DB I/O, no LLM calls, no network. The
``polymarket_calibration`` tool is the I/O wrapper.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Records (DB row shape, after _outcome_prob() resolves YES vs NO side)
# ---------------------------------------------------------------------------


@dataclass
class ResolvedPrediction:
    """A prediction whose market has resolved.

    ``claimed_prob`` is the bot's probability of *winning the side it
    took*, not the YES probability. So if we bet NO at 0.35 and the LLM
    said 0.30 YES (i.e. 0.70 NO), ``claimed_prob`` is 0.70 and
    ``entry_price_implied`` is 0.65 (the implied market probability of
    NO winning, = 1 - 0.35).

    ``won`` is True iff our side won.
    """

    claimed_prob: float
    entry_price_implied: float
    won: bool
    confidence_band: str = "medium"
    order_type: str = "GTC"
    filled: bool = True
    # 'live' (real position) or 'shadow' (paper bet for calibration).
    # Reports bucket by kind so shadow predictions don't inflate
    # confidence in live-edge claims.
    kind: str = "live"


def to_winner_perspective(
    *,
    side: str,
    entry_price: float,
    llm_prob: float,
    settle_price: float,
) -> tuple[float, float, bool]:
    """Translate a (side, entry_price, llm_prob_yes, settle_price) tuple
    into ``(claimed_prob, entry_price_implied, won)`` framed from the
    side we actually took.

    Polymarket settles to 0.0 or 1.0 (0.5 only on pushes). YES side
    wins iff ``settle_price > 0.5``; NO side wins iff
    ``settle_price < 0.5``.
    """
    side_u = side.upper()
    if side_u == "YES":
        claimed = llm_prob
        implied = entry_price
        won = settle_price > 0.5
    elif side_u == "NO":
        claimed = 1.0 - llm_prob
        implied = 1.0 - entry_price
        won = settle_price < 0.5
    else:
        raise ValueError(f"side must be YES or NO, got {side!r}")
    return claimed, implied, won


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------


@dataclass
class CalibrationBucket:
    """One row in a calibration table — e.g. "predictions claiming
    60–70% won X of N times"."""

    bucket_lower: float
    bucket_upper: float
    n: int = 0
    wins: int = 0
    sum_claimed: float = 0.0  # for averaged claimed prob inside the bucket

    @property
    def realized_win_rate(self) -> float:
        return self.wins / self.n if self.n else 0.0

    @property
    def avg_claimed(self) -> float:
        return self.sum_claimed / self.n if self.n else 0.0

    @property
    def calibration_gap(self) -> float:
        """``realized - claimed`` — positive means the bucket
        outperformed its stated probability; negative means it
        underperformed."""
        return self.realized_win_rate - self.avg_claimed

    def to_dict(self) -> dict:
        return {
            "bucket": f"{int(self.bucket_lower * 100)}-{int(self.bucket_upper * 100)}%",
            "n": self.n,
            "wins": self.wins,
            "realized_win_rate": round(self.realized_win_rate, 4),
            "avg_claimed": round(self.avg_claimed, 4),
            "calibration_gap": round(self.calibration_gap, 4),
        }


def _make_buckets(width: float) -> list[CalibrationBucket]:
    """10% buckets by default: [0.0, 0.1), [0.1, 0.2), ..., [0.9, 1.0]."""
    if not 0 < width <= 1:
        raise ValueError(f"width must be in (0, 1], got {width!r}")
    buckets: list[CalibrationBucket] = []
    edge = 0.0
    while edge < 1.0 - 1e-9:
        upper = min(1.0, edge + width)
        buckets.append(CalibrationBucket(bucket_lower=edge, bucket_upper=upper))
        edge = upper
    return buckets


def _bucket_index(value: float, width: float, n_buckets: int) -> int:
    """Map a probability in [0, 1] to a bucket index."""
    if value <= 0:
        return 0
    if value >= 1:
        return n_buckets - 1
    return min(int(value / width), n_buckets - 1)


# ---------------------------------------------------------------------------
# Brier score
# ---------------------------------------------------------------------------


def brier_score(predictions: Iterable[ResolvedPrediction]) -> tuple[float, int]:
    """Mean squared error of stated probability vs realized 0/1 outcome.

    Lower is better. 0.25 is what you get from always claiming 50%
    (random / no edge). A calibrated bot with real edge runs 0.18–0.22
    on Polymarket-shape markets. Above 0.25 is worse than always
    claiming 50% and means the bot is *anti-correlated* with reality —
    flip its predictions and it would do better.

    Returns ``(score, n)``. ``n`` is the count of resolved predictions
    contributing to the score (so the report can warn when the sample
    is too small to be meaningful).
    """
    total = 0.0
    n = 0
    for p in predictions:
        outcome_int = 1.0 if p.won else 0.0
        total += (p.claimed_prob - outcome_int) ** 2
        n += 1
    if n == 0:
        return 0.0, 0
    return total / n, n


# ---------------------------------------------------------------------------
# Top-level report builder
# ---------------------------------------------------------------------------


@dataclass
class CalibrationReport:
    n_resolved: int
    overall_win_rate: float
    brier: float
    by_claimed_prob: list[CalibrationBucket]
    by_entry_price: list[CalibrationBucket]
    by_confidence_band: dict[str, CalibrationBucket] = field(default_factory=dict)
    maker_fill_rate: float = 0.0  # filled / placed (post-only orders)
    n_maker_orders: int = 0
    # Breakdown by prediction kind: 'live' (real money), 'shadow' (paper).
    # Each value is the same shape as the top-level fields above so
    # callers can read e.g. report.by_kind["shadow"]["brier_score"].
    by_kind: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "n_resolved": self.n_resolved,
            "overall_win_rate": round(self.overall_win_rate, 4),
            "brier_score": round(self.brier, 4),
            "by_claimed_prob": [b.to_dict() for b in self.by_claimed_prob if b.n > 0],
            "by_entry_price": [b.to_dict() for b in self.by_entry_price if b.n > 0],
            "by_confidence_band": {
                band: bucket.to_dict()
                for band, bucket in self.by_confidence_band.items()
                if bucket.n > 0
            },
            "maker_fill_rate": round(self.maker_fill_rate, 4),
            "n_maker_orders": self.n_maker_orders,
            "by_kind": self.by_kind,
        }


def build_report(
    resolved: list[ResolvedPrediction],
    *,
    bucket_width: float = 0.10,
    placed_post_only: int | None = None,
    filled_post_only: int | None = None,
) -> CalibrationReport:
    """Roll a list of resolved predictions into a full report.

    ``placed_post_only`` / ``filled_post_only`` are passed in by the
    caller because counting "placed" requires reading rows that may
    have never resolved (timed-out, cancelled). Pure function stays
    pure: caller handles the I/O.
    """
    fill_rate = 0.0
    if placed_post_only is not None and placed_post_only > 0:
        fill_rate = (filled_post_only or 0) / placed_post_only

    n = len(resolved)
    if n == 0:
        return CalibrationReport(
            n_resolved=0,
            overall_win_rate=0.0,
            brier=0.0,
            by_claimed_prob=_make_buckets(bucket_width),
            by_entry_price=_make_buckets(bucket_width),
            maker_fill_rate=fill_rate,
            n_maker_orders=placed_post_only or 0,
        )

    by_claim = _make_buckets(bucket_width)
    by_price = _make_buckets(bucket_width)
    by_band: dict[str, CalibrationBucket] = {
        "high": CalibrationBucket(0.0, 1.0),
        "medium": CalibrationBucket(0.0, 1.0),
        "low": CalibrationBucket(0.0, 1.0),
    }
    n_buckets = len(by_claim)
    wins = 0
    for p in resolved:
        idx_claim = _bucket_index(p.claimed_prob, bucket_width, n_buckets)
        idx_price = _bucket_index(p.entry_price_implied, bucket_width, n_buckets)
        b1 = by_claim[idx_claim]
        b1.n += 1
        b1.sum_claimed += p.claimed_prob
        if p.won:
            b1.wins += 1
            wins += 1
        b2 = by_price[idx_price]
        b2.n += 1
        b2.sum_claimed += p.entry_price_implied
        if p.won:
            b2.wins += 1
        if p.confidence_band in by_band:
            band_bucket = by_band[p.confidence_band]
            band_bucket.n += 1
            band_bucket.sum_claimed += p.claimed_prob
            if p.won:
                band_bucket.wins += 1

    brier, _ = brier_score(resolved)

    # Per-kind breakdown: bucket separately so shadow predictions
    # don't inflate confidence in live-edge claims. Each kind gets
    # its own n, win rate, Brier — no shared bucketing across kinds.
    by_kind: dict[str, dict] = {}
    kinds_present = {p.kind for p in resolved}
    for kind in sorted(kinds_present):
        subset = [p for p in resolved if p.kind == kind]
        if not subset:
            continue
        k_wins = sum(1 for p in subset if p.won)
        k_brier, _ = brier_score(subset)
        by_kind[kind] = {
            "n_resolved": len(subset),
            "overall_win_rate": round(k_wins / len(subset), 4),
            "brier_score": round(k_brier, 4),
        }

    return CalibrationReport(
        n_resolved=n,
        overall_win_rate=wins / n if n else 0.0,
        brier=brier,
        by_claimed_prob=by_claim,
        by_entry_price=by_price,
        by_confidence_band=by_band,
        maker_fill_rate=fill_rate,
        n_maker_orders=placed_post_only or 0,
        by_kind=by_kind,
    )
