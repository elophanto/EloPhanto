"""Competitive intelligence — a scored, evidence-backed model of a market.

ABE organ 2 (market model). Where ``prospects`` tracks people to sell to, this
tracks *brands to measure*: what they do, how good it is, on what evidence, and
what changed since last month.

Five tables (see ``core/database.py``): subjects, dimensions, evidence, scores,
snapshots. Two rules are enforced here in code rather than left to a prompt,
because both are load-bearing for the analysis being honest:

1. **A missing datapoint is never a bad score.** ``score`` is nullable. Absence
   surfaces as ``coverage_pct`` beside the score, never as a 1. A brand that is
   simply opaque must not be reported as a weak competitor.
2. **Evidence is append-only.** Re-observation writes a new row and supersedes
   the old one, so a month-over-month diff reflects what actually changed
   instead of what got overwritten.

The scoring math is pure functions (no DB, no I/O) so it can be tested directly
and reused by the scorecard/board-report renderers.

Design: tmp/competitive-intel-organ-spec.md
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.database import Database

logger = logging.getLogger(__name__)


VALID_CONFIDENCE: tuple[str, ...] = ("high", "medium", "low")
VALID_CADENCE: tuple[str, ...] = ("weekly", "monthly", "quarterly")
VALID_COLLECTOR: tuple[str, ...] = ("agent", "human")

# The customer states the SOW tests across. Everything from ``verified`` on
# requires an account and is human-collected by default (operator decision:
# no automated account creation on operators) — see ``AGENT_SAFE_STATES``.
VALID_CUSTOMER_STATES: tuple[str, ...] = (
    "logged_out",
    "registered",
    "verified",
    "purchaser",
    "redeemer",
    "vip",
)
AGENT_SAFE_STATES: frozenset[str] = frozenset({"logged_out"})

VALID_SOURCE_TYPES: tuple[str, ...] = (
    "site",
    "terms",
    "ad_library",
    "trust_site",
    "filing",
    "shop",
    "press",
    "other",
)

_CONFIDENCE_POINTS: dict[str, float] = {"high": 3.0, "medium": 2.0, "low": 1.0}

# ── Voice of customer (second evidence class; docs/87) ─────────────────
# Fixed vocabularies so cycles compare. Opinion, never fact: nothing here
# is read by score_subject / build_scorecard.
VOICE_SOURCES: tuple[str, ...] = (
    "reddit",
    "app_store",
    "google_play",
    "trustpilot",
    "bbb",
    "x",
    "web",
)
VOICE_THEMES: tuple[str, ...] = (
    "redemption_speed",
    "kyc_friction",
    "support",
    "fairness_rtp",
    "promo_value",
    "app_stability",
    "account_bans",
    "vip_treatment",
    "game_selection",
    "payments",
    "other",
)
VOICE_SENTIMENTS: tuple[str, ...] = ("negative", "neutral", "positive")
VOICE_MIN_MENTIONS = 15  # below this a brand is "too few mentions to read"

# Refresh cadence in days — drives the staleness queue (P3) and is reported
# beside every score so a reader can see how old the evidence is.
CADENCE_DAYS: dict[str, int] = {"weekly": 7, "monthly": 30, "quarterly": 91}


# ── Records ─────────────────────────────────────────────────────────────


@dataclass(slots=True)
class WatchSubject:
    subject_id: str
    name: str
    company_id: str = "elophanto-self"
    group_name: str = ""
    url: str = ""
    product_offering: str = ""
    market_share_est: str = ""
    is_self: bool = False
    tags: list[str] = field(default_factory=list)
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class WatchDimension:
    dimension_id: str
    name: str
    company_id: str = "elophanto-self"
    description: str = ""
    weight_pct: float = 0.0
    # [{"name": "Welcome-offer value", "weight_pct": 25}, …]
    subcriteria: list[dict[str, Any]] = field(default_factory=list)
    refresh_cadence: str = "monthly"
    # {"customer_proposition": 12, "transition_priority": 4} — alternative
    # weightings over the SAME scores. Empty falls back to weight_pct.
    view_weights: dict[str, float] = field(default_factory=dict)
    sort_order: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class WatchEvidence:
    evidence_id: str
    subject_id: str
    dimension_id: str
    claim: str
    company_id: str = "elophanto-self"
    subcriterion: str = ""
    value_text: str = ""
    value_num: float | None = None
    source_url: str = ""
    source_type: str = "site"
    geo_state: str = "n/a"
    customer_state: str = "logged_out"
    journey_stage: str = ""
    observed_at: str = ""
    confidence: str = "medium"
    excerpt: str = ""
    screenshot_path: str = ""
    collector: str = "agent"
    # The verified network exit the page was fetched through — the proof
    # behind geo_state. "" means no state was claimed (or a human entered it).
    exit_ip: str = ""
    superseded_by: str | None = None
    created_at: str = ""


@dataclass(slots=True)
class WatchScore:
    score_id: str
    subject_id: str
    dimension_id: str
    company_id: str = "elophanto-self"
    score: float | None = None
    subcriteria_scores: dict[str, float] = field(default_factory=dict)
    rationale: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    coverage_pct: float = 0.0
    confidence: str = "low"
    scored_at: str = ""
    scored_by: str = "agent"


# ── Pure scoring math ───────────────────────────────────────────────────

# Minimum share of total dimension weight a subject must have scored before
# it is allowed to carry a rank. 50% is the point at which "we measured most
# of this brand" becomes defensible in front of a client; below it the
# normalized score is still shown, but as a provisional figure rather than a
# league position. Override per call when a market is deliberately scored on
# a narrow slice.
_RANK_THRESHOLD_PCT = 50.0

# Comparability spread. Even above the rank threshold, a brand measured to
# 27% depth and one measured to 80% are not standing on the same ground;
# ranking them side by side reads as a like-for-like league table when it is
# not. Judged on COVERAGE (how much of each scored dimension's sub-criteria
# the evidence actually covers) — not on the share of model weight that has
# a score. Those differ: a brand can hold a score on 70% of the model while
# its evidence covers 27% of what those dimensions ask (LuckyLand, 2026-08-16,
# ranked #14 in a pack whose own receipt called the ranking non-comparable).
# If coverage across would-be ranked brands spreads wider than this, ranking
# is withheld for the whole field and every row is provisional with the
# reason stated. Scores still show; the pack says "not yet comparable —
# collect X, Y" instead of drawing a table.
_RANK_COMPARABILITY_SPREAD_PCT = 35.0


@dataclass(slots=True)
class WatchVoice:
    """One thing a player said about a brand — opinion with provenance."""

    voice_id: str
    subject_id: str
    source: str
    theme: str
    sentiment: str
    company_id: str = "elophanto-self"
    source_url: str = ""
    posted_at: str = ""
    observed_at: str = ""
    exit_ip: str = ""
    rating: float | None = None
    quote: str = ""
    dimension_id: str = ""
    geo_hint: str = ""
    weight: float = 1.0
    dedupe_key: str = ""
    created_at: str = ""


def voice_dedupe_key(quote: str, source_url: str = "") -> str:
    """Cross-posts and re-scrapes count once: key on the normalised quote
    (or the URL when the quote is empty)."""
    import hashlib

    base = " ".join((quote or "").lower().split())[:200] or (source_url or "").lower()
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]


def _pick_quote(
    rows: list[WatchVoice], sentiment: str, theme: str | None, *, same: bool
) -> dict[str, str] | None:
    """The most credible, most recent quote of that sentiment on (or off) a
    theme — the deck shows three per brand."""
    best = max(
        (
            r
            for r in rows
            if r.quote and r.sentiment == sentiment and ((r.theme == theme) if same else (r.theme != theme))
        ),
        key=lambda r: (r.weight, r.posted_at or r.observed_at),
        default=None,
    )
    if best is None:
        return None
    return {
        "quote": best.quote,
        "source": best.source,
        "url": best.source_url,
        "posted_at": (best.posted_at or best.observed_at)[:10],
        "theme": best.theme,
        "sentiment": best.sentiment,
    }


def summarize_voice(
    rows: list[WatchVoice],
    subjects: list[WatchSubject],
    *,
    window_days: int = 30,
    min_mentions: int = VOICE_MIN_MENTIONS,
    now: str = "",
) -> dict[str, Any]:
    """The reading of what players said, per brand and field-wide.

    Pure computation. Every number is a SHARE with its n — volume differs
    a hundredfold between brands, so absolutes would mislead — and brands
    under ``min_mentions`` are marked ``too_few`` rather than charted.
    Rows are weighted by their credibility ``weight``.
    """
    from datetime import timedelta

    now_dt = datetime.fromisoformat(now) if now else datetime.now(UTC)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=UTC)
    since = (now_dt - timedelta(days=int(window_days))).isoformat()
    name_of = {s.subject_id: s.name for s in subjects}
    is_self = {s.subject_id: bool(s.is_self) for s in subjects}
    in_window = [r for r in rows if (r.posted_at or r.observed_at) >= since]

    def _weighted(rs: list[WatchVoice]) -> float:
        return sum(max(0.0, min(1.0, r.weight)) for r in rs) or 0.0

    per: list[dict[str, Any]] = []
    for subj in subjects:
        rs = [r for r in in_window if r.subject_id == subj.subject_id]
        n = len(rs)
        w = _weighted(rs)
        themes: dict[str, dict[str, Any]] = {}
        for t in VOICE_THEMES:
            trs = [r for r in rs if r.theme == t]
            if not trs:
                continue
            tw = _weighted(trs)
            neg = _weighted([r for r in trs if r.sentiment == "negative"])
            themes[t] = {
                "n": len(trs),
                "share": round(tw / w, 3) if w else 0.0,
                "neg_share": round(neg / tw, 3) if tw else 0.0,
            }
        ratings = [r.rating for r in rs if r.rating is not None]
        neg_w = _weighted([r for r in rs if r.sentiment == "negative"])
        pos_w = _weighted([r for r in rs if r.sentiment == "positive"])
        complaint = max(
            (t for t in themes if t != "other"),
            key=lambda t: themes[t]["share"] * themes[t]["neg_share"],
            default=None,
        )
        praise = max(
            (t for t in themes if t != "other"),
            key=lambda t: themes[t]["share"] * (1.0 - themes[t]["neg_share"]),
            default=None,
        )

        quotes = [
            q
            for q in (
                _pick_quote(rs, "negative", complaint, same=True),
                _pick_quote(rs, "positive", praise, same=True),
                _pick_quote(rs, "negative", complaint, same=False),
            )
            if q
        ]
        per.append(
            {
                "subject_id": subj.subject_id,
                "name": name_of.get(subj.subject_id, subj.subject_id),
                "is_self": is_self.get(subj.subject_id, False),
                "n": n,
                "too_few": n < int(min_mentions),
                "sources": sorted({r.source for r in rs}),
                "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
                "neg_share": round(neg_w / w, 3) if w else 0.0,
                "pos_share": round(pos_w / w, 3) if w else 0.0,
                "themes": themes,
                "top_complaint": complaint,
                "top_praise": praise,
                "quotes": quotes,
                "flags": sorted(
                    {
                        r.dimension_id
                        for r in rs
                        if r.dimension_id and r.sentiment == "negative"
                    }
                ),
            }
        )

    field_w = _weighted(in_window)
    field_themes: dict[str, dict[str, Any]] = {}
    for t in VOICE_THEMES:
        trs = [r for r in in_window if r.theme == t]
        if not trs:
            continue
        tw = _weighted(trs)
        neg = _weighted([r for r in trs if r.sentiment == "negative"])
        field_themes[t] = {
            "n": len(trs),
            "share": round(tw / field_w, 3) if field_w else 0.0,
            "neg_share": round(neg / tw, 3) if tw else 0.0,
        }
    return {
        "window_days": int(window_days),
        "since": since,
        "mentions": len(in_window),
        "min_mentions": int(min_mentions),
        "brands": per,
        "field_themes": field_themes,
        "sources": sorted({r.source for r in in_window}),
        "label": "What players say — sentiment from public posts, not observed product fact.",
    }


def diff_voice(
    old: dict[str, Any] | None,
    new: dict[str, Any],
    *,
    min_share_delta: float = 0.10,
    min_n: int = 5,
) -> dict[str, Any]:
    """Theme deltas between two voice summaries — the monthly 'rising and
    falling'. Reports a brand × theme when its share of that brand's
    mentions moved by ``min_share_delta`` or its negative share did, and
    at least ``min_n`` mentions back the newer number."""
    changes: list[dict[str, Any]] = []
    old_brands = {b["name"]: b for b in (old or {}).get("brands", [])}
    for b in new.get("brands", []):
        ob = old_brands.get(b["name"], {})
        for theme, cur in (b.get("themes") or {}).items():
            if int(cur.get("n", 0)) < min_n:
                continue
            prev = (ob.get("themes") or {}).get(theme, {"share": 0.0, "neg_share": 0.0, "n": 0})
            d_share = float(cur["share"]) - float(prev.get("share", 0.0))
            d_neg = float(cur["neg_share"]) - float(prev.get("neg_share", 0.0))
            if abs(d_share) >= min_share_delta or abs(d_neg) >= min_share_delta:
                changes.append(
                    {
                        "brand": b["name"],
                        "is_self": bool(b.get("is_self")),
                        "theme": theme,
                        "n_from": int(prev.get("n", 0)),
                        "n_to": int(cur["n"]),
                        "share_from": float(prev.get("share", 0.0)),
                        "share_to": float(cur["share"]),
                        "neg_from": float(prev.get("neg_share", 0.0)),
                        "neg_to": float(cur["neg_share"]),
                        "direction": "rising"
                        if (d_neg if abs(d_neg) >= abs(d_share) else d_share) > 0
                        else "falling",
                    }
                )
    changes.sort(
        key=lambda c: -max(abs(c["share_to"] - c["share_from"]), abs(c["neg_to"] - c["neg_from"]))
    )
    return {
        "baseline": old is None,
        "changed": changes,
        "material_count": len(changes),
        "from_mentions": int((old or {}).get("mentions", 0)),
        "to_mentions": int(new.get("mentions", 0)),
    }


def weighted_points(score: float | None, weight_pct: float) -> float:
    """Weighted contribution of one dimension: ``(score / 5) x weight``.

    A 4/5 on a dimension weighted 10% yields 8 points. ``None`` (no evidence)
    contributes nothing — it is *not* treated as zero-out-of-five, which would
    silently punish opacity. Callers must read ``scored_weight_pct`` alongside
    the total to know what the total is out of.
    """
    if score is None:
        return 0.0
    return (float(score) / 5.0) * float(weight_pct)


def coverage_pct(subcriteria: list[dict[str, Any]], covered: set[str]) -> float:
    """Percentage of a dimension's required datapoints that have evidence.

    With no declared subcriteria the dimension is a single datapoint: any
    evidence at all is 100% coverage, none is 0%.
    """
    names = [str(s.get("name", "")).strip() for s in subcriteria if s.get("name")]
    if not names:
        return 100.0 if covered else 0.0
    hit = sum(1 for n in names if n in covered)
    return round(hit / len(names) * 100.0, 1)


def confidence_rollup(confidences: list[str]) -> str:
    """Roll a set of per-evidence confidences into one label.

    Mean of high=3 / medium=2 / low=1, bucketed conservatively: a body of
    evidence only reads 'high' when it is decisively so (>= 2.5).
    """
    vals = [_CONFIDENCE_POINTS[c] for c in confidences if c in _CONFIDENCE_POINTS]
    if not vals:
        return "low"
    avg = sum(vals) / len(vals)
    if avg >= 2.5:
        return "high"
    if avg >= 1.75:
        return "medium"
    return "low"


def _view_weight(dim: WatchDimension, view: str | None) -> float:
    """Weight for a dimension under an alternative view (falls back to base)."""
    if not view:
        return float(dim.weight_pct)
    raw = dim.view_weights.get(view)
    return float(dim.weight_pct) if raw is None else float(raw)


def score_subject(
    dimensions: list[WatchDimension],
    scores: dict[str, WatchScore],
    *,
    view: str | None = None,
) -> dict[str, Any]:
    """Weighted result for one subject across all dimensions.

    Returns ``raw_points`` (out of ``scored_weight_pct``, not out of 100) and
    ``normalized_pct`` — raw rescaled to the weight that was actually scored,
    which is the only figure comparable between brands with different coverage.
    Both are reported so a reader can never mistake thin evidence for strength.
    """
    raw = 0.0
    scored_weight = 0.0
    total_weight = 0.0
    coverages: list[float] = []
    confs: list[str] = []
    unscored: list[str] = []

    for dim in dimensions:
        w = _view_weight(dim, view)
        total_weight += w
        s = scores.get(dim.dimension_id)
        if s is None or s.score is None:
            unscored.append(dim.name)
            coverages.append(s.coverage_pct if s else 0.0)
            continue
        raw += weighted_points(s.score, w)
        scored_weight += w
        coverages.append(s.coverage_pct)
        confs.append(s.confidence)

    normalized = round(raw / scored_weight * 100.0, 2) if scored_weight > 0 else None
    return {
        "raw_points": round(raw, 2),
        "scored_weight_pct": round(scored_weight, 2),
        "total_weight_pct": round(total_weight, 2),
        "normalized_pct": normalized,
        "coverage_pct": round(sum(coverages) / len(coverages), 1) if coverages else 0.0,
        "confidence": confidence_rollup(confs),
        "unscored_dimensions": unscored,
    }


def build_scorecard(
    subjects: list[WatchSubject],
    dimensions: list[WatchDimension],
    scores_by_subject: dict[str, dict[str, WatchScore]],
    *,
    views: tuple[str, ...] = ("customer_proposition", "transition_priority"),
    rank_threshold_pct: float = _RANK_THRESHOLD_PCT,
    comparability_spread_pct: float = _RANK_COMPARABILITY_SPREAD_PCT,
) -> dict[str, Any]:
    """Full scorecard: every subject scored on the base weighting + each view.

    Ranked by ``normalized_pct`` so brands with partial evidence still place
    honestly. Subjects with nothing scored sort last rather than at zero.

    **Thin evidence does not win.** ``normalized_pct`` rescales to the weight
    actually scored, which is the right comparable figure but has a sharp
    edge: a brand with one 4%-weight dimension scored 5/5 normalizes to
    100.0 and would otherwise outrank a brand measured on all twelve. In a
    board pack that reads as "this is the market leader" when the truth is
    "we looked at one thing". So a subject is only *ranked* once its scored
    weight reaches ``rank_threshold_pct`` of the total; below that it is
    marked ``provisional`` and sorted after every ranked brand, carrying
    ``rank: None`` exactly like a subject with no evidence at all.

    The scores themselves are never suppressed — a provisional row still
    shows its normalized figure, coverage, and which dimensions are missing.
    Only the claim to a rank is withheld, because that is the number a
    reader trusts without checking the footnote.
    """
    rows: list[dict[str, Any]] = []
    for subj in subjects:
        s_scores = scores_by_subject.get(subj.subject_id, {})
        row: dict[str, Any] = {
            "subject_id": subj.subject_id,
            "name": subj.name,
            "group": subj.group_name,
            "is_self": subj.is_self,
            "overall": score_subject(dimensions, s_scores),
            "views": {v: score_subject(dimensions, s_scores, view=v) for v in views},
            "dimensions": {
                d.name: {
                    "score": (
                        s_scores[d.dimension_id].score
                        if d.dimension_id in s_scores
                        else None
                    ),
                    "coverage_pct": (
                        s_scores[d.dimension_id].coverage_pct
                        if d.dimension_id in s_scores
                        else 0.0
                    ),
                    "confidence": (
                        s_scores[d.dimension_id].confidence
                        if d.dimension_id in s_scores
                        else "low"
                    ),
                }
                for d in dimensions
            },
        }
        rows.append(row)

    # Evidence sufficiency, computed against the same total the weights sum
    # to, so a part-built dimension set cannot make every brand provisional.
    total_weight = sum(float(d.weight_pct) for d in dimensions)
    for r in rows:
        overall = r["overall"]
        scored_w = float(overall.get("scored_weight_pct") or 0.0)
        share = (scored_w / total_weight * 100.0) if total_weight > 0 else 0.0
        r["evidence_weight_pct"] = round(share, 1)
        r["provisional"] = (
            overall["normalized_pct"] is None or share < rank_threshold_pct
        )
        if r["provisional"] and overall["normalized_pct"] is not None:
            r["provisional_reason"] = (
                f"scored on {share:.0f}% of total dimension weight "
                f"(needs {rank_threshold_pct:.0f}% to rank); "
                f"missing: {', '.join(overall['unscored_dimensions'][:4])}"
                + ("…" if len(overall["unscored_dimensions"]) > 4 else "")
            )

    # Field-level comparability: brands that individually clear the rank
    # threshold still cannot be ranked AGAINST EACH OTHER if their evidence
    # depth is wildly uneven. A first-pass run that measured one brand on
    # 75% and another on 30% is not a league table yet.
    rankable = [r for r in rows if not r["provisional"]]
    comparability_note = ""
    if len(rankable) >= 2:
        depths = [float(r["overall"]["coverage_pct"] or 0.0) for r in rankable]
        spread = max(depths) - min(depths)
        if spread > comparability_spread_pct:
            thin = sorted(
                rankable, key=lambda r: float(r["overall"]["coverage_pct"] or 0.0)
            )
            comparability_note = (
                f"evidence coverage ranges {min(depths):.0f}%–{max(depths):.0f}% "
                f"across ranked brands (spread {spread:.0f} points > "
                f"{comparability_spread_pct:.0f}); ranking withheld until "
                "coverage is comparable — collect: "
                + ", ".join(r["name"] for r in thin[:4])
            )
            for r in rankable:
                r["provisional"] = True
                r["provisional_reason"] = "field not comparable: " + (
                    f"evidence covers {float(r['overall']['coverage_pct'] or 0):.0f}% "
                    "of the scored dimensions"
                )

    rows.sort(
        key=lambda r: (
            r["provisional"],
            r["overall"]["normalized_pct"] is None,
            -(r["overall"]["normalized_pct"] or 0.0),
        )
    )
    rank = 0
    for r in rows:
        if r["provisional"]:
            r["rank"] = None
            continue
        rank += 1
        r["rank"] = rank

    total_w = round(sum(float(d.weight_pct) for d in dimensions), 2)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "comparability_note": comparability_note,
        "dimensions": [
            {"name": d.name, "weight_pct": d.weight_pct, "cadence": d.refresh_cadence}
            for d in dimensions
        ],
        "weight_total_pct": total_w,
        "weights_valid": abs(total_w - 100.0) < 0.01,
        "rows": rows,
    }


def diff_scorecards(
    old: dict[str, Any],
    new: dict[str, Any],
    *,
    min_score_delta: float = 1.0,
    min_coverage_delta: float = 25.0,
) -> dict[str, Any]:
    """Material changes between two scorecards — the spine of a board report.

    "Material" is deliberately conservative: a monthly report that surfaces
    every 0.1 wobble trains its readers to ignore it. A change qualifies when a
    dimension score moves by ``min_score_delta`` (default a full point on the
    1-5 scale), a brand's rank moves, evidence coverage shifts by
    ``min_coverage_delta``, or a brand enters or leaves the analysis.

    A dimension going from unscored to scored (or back) is always material —
    that is new knowledge, not noise.
    """
    old_rows = {r["name"]: r for r in old.get("rows", [])}
    new_rows = {r["name"]: r for r in new.get("rows", [])}

    added = sorted(set(new_rows) - set(old_rows))
    removed = sorted(set(old_rows) - set(new_rows))
    changes: list[dict[str, Any]] = []

    for name in sorted(set(old_rows) & set(new_rows)):
        o, n = old_rows[name], new_rows[name]
        entry: dict[str, Any] = {
            "subject": name,
            "group": n.get("group", ""),
            "items": [],
        }

        o_rank, n_rank = o.get("rank"), n.get("rank")
        if o_rank != n_rank and (o_rank is not None or n_rank is not None):
            entry["items"].append(
                {
                    "kind": "rank",
                    "from": o_rank,
                    "to": n_rank,
                    "detail": f"rank {o_rank or '—'} → {n_rank or '—'}",
                }
            )

        o_dims = o.get("dimensions", {})
        n_dims = n.get("dimensions", {})
        for dim_name, n_d in n_dims.items():
            o_d = o_dims.get(dim_name, {})
            o_score, n_score = o_d.get("score"), n_d.get("score")
            if o_score is None and n_score is not None:
                entry["items"].append(
                    {
                        "kind": "newly_scored",
                        "dimension": dim_name,
                        "from": None,
                        "to": n_score,
                        "detail": f"{dim_name}: now scored {n_score}/5 (was no evidence)",
                    }
                )
            elif o_score is not None and n_score is None:
                entry["items"].append(
                    {
                        "kind": "score_withdrawn",
                        "dimension": dim_name,
                        "from": o_score,
                        "to": None,
                        "detail": f"{dim_name}: score withdrawn (was {o_score}/5)",
                    }
                )
            elif (
                o_score is not None
                and n_score is not None
                and abs(n_score - o_score) >= min_score_delta
            ):
                entry["items"].append(
                    {
                        "kind": "score",
                        "dimension": dim_name,
                        "from": o_score,
                        "to": n_score,
                        "detail": f"{dim_name}: {o_score}/5 → {n_score}/5",
                    }
                )
            o_cov, n_cov = o_d.get("coverage_pct", 0.0), n_d.get("coverage_pct", 0.0)
            if abs(n_cov - o_cov) >= min_coverage_delta:
                entry["items"].append(
                    {
                        "kind": "coverage",
                        "dimension": dim_name,
                        "from": o_cov,
                        "to": n_cov,
                        "detail": f"{dim_name}: evidence coverage {o_cov:.0f}% → {n_cov:.0f}%",
                    }
                )
        if entry["items"]:
            entry["overall_from"] = o.get("overall", {}).get("normalized_pct")
            entry["overall_to"] = n.get("overall", {}).get("normalized_pct")
            changes.append(entry)

    return {
        "from_generated_at": old.get("generated_at"),
        "to_generated_at": new.get("generated_at"),
        "added_subjects": added,
        "removed_subjects": removed,
        "changed": changes,
        "material_count": (
            sum(len(c["items"]) for c in changes) + len(added) + len(removed)
        ),
        "thresholds": {
            "min_score_delta": min_score_delta,
            "min_coverage_delta": min_coverage_delta,
        },
    }


def _row_get(r: Any, key: str, default: Any = None) -> Any:
    """sqlite3.Row has no .get()."""
    try:
        return r[key]
    except (IndexError, KeyError):
        return default


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ── Manager ─────────────────────────────────────────────────────────────


class WatchManager:
    """CRUD + scoring over the competitive-intelligence tables."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Subjects ────────────────────────────────────────────────────

    async def add_subject(
        self,
        *,
        name: str,
        company_id: str,
        group_name: str = "",
        url: str = "",
        product_offering: str = "",
        market_share_est: str = "",
        is_self: bool = False,
        tags: list[str] | None = None,
    ) -> WatchSubject:
        existing = await self.get_subject_by_name(name, company_id)
        if existing:
            return existing
        now = _now()
        sub = WatchSubject(
            subject_id=_sid("subj"),
            name=name,
            company_id=company_id,
            group_name=group_name,
            url=url,
            product_offering=product_offering,
            market_share_est=market_share_est,
            is_self=is_self,
            tags=tags or [],
            created_at=now,
            updated_at=now,
        )
        await self._db.execute_insert(
            "INSERT INTO watch_subjects (subject_id, company_id, name, group_name, "
            "url, product_offering, market_share_est, is_self, tags, status, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sub.subject_id,
                sub.company_id,
                sub.name,
                sub.group_name,
                sub.url,
                sub.product_offering,
                sub.market_share_est,
                1 if is_self else 0,
                json.dumps(sub.tags),
                sub.status,
                now,
                now,
            ),
        )
        return sub

    async def list_subjects(
        self, company_id: str, *, include_archived: bool = False
    ) -> list[WatchSubject]:
        sql = "SELECT * FROM watch_subjects WHERE company_id = ?"
        if not include_archived:
            sql += " AND status = 'active'"
        sql += " ORDER BY is_self DESC, name"
        return [self._to_subject(r) for r in await self._db.execute(sql, (company_id,))]

    async def tag_subject(self, subject_id: str, tag: str) -> None:
        """Append a tag to a subject (idempotent). Used for cached lookups
        such as ``app_store:<id>`` — never for status."""
        rows = await self._db.execute(
            "SELECT tags FROM watch_subjects WHERE subject_id = ?", (subject_id,)
        )
        if not rows:
            return
        tags = json.loads(_row_get(rows[0], "tags", "[]") or "[]")
        if tag in tags:
            return
        tags.append(tag)
        await self._db.execute(
            "UPDATE watch_subjects SET tags = ?, updated_at = ? WHERE subject_id = ?",
            (json.dumps(tags), _now(), subject_id),
        )

    async def archive_subject(self, subject_id: str) -> None:
        """Stop tracking a brand. Evidence and scores are retained so past
        scorecards and diffs stay reproducible."""
        await self._db.execute(
            "UPDATE watch_subjects SET status = 'archived', updated_at = ? "
            "WHERE subject_id = ?",
            (_now(), subject_id),
        )

    async def get_subject_by_name(
        self, name: str, company_id: str
    ) -> WatchSubject | None:
        rows = await self._db.execute(
            "SELECT * FROM watch_subjects WHERE company_id = ? AND name = ?",
            (company_id, name),
        )
        return self._to_subject(rows[0]) if rows else None

    @staticmethod
    def _to_subject(r: Any) -> WatchSubject:
        return WatchSubject(
            subject_id=r["subject_id"],
            name=r["name"],
            company_id=r["company_id"],
            group_name=_row_get(r, "group_name", "") or "",
            url=_row_get(r, "url", "") or "",
            product_offering=_row_get(r, "product_offering", "") or "",
            market_share_est=_row_get(r, "market_share_est", "") or "",
            is_self=bool(_row_get(r, "is_self", 0)),
            tags=json.loads(_row_get(r, "tags", "[]") or "[]"),
            status=_row_get(r, "status", "active") or "active",
            created_at=_row_get(r, "created_at", "") or "",
            updated_at=_row_get(r, "updated_at", "") or "",
        )

    # ── Dimensions ──────────────────────────────────────────────────

    async def upsert_dimension(
        self,
        *,
        name: str,
        company_id: str,
        description: str = "",
        weight_pct: float = 0.0,
        subcriteria: list[dict[str, Any]] | None = None,
        refresh_cadence: str = "monthly",
        view_weights: dict[str, float] | None = None,
        sort_order: int = 0,
    ) -> WatchDimension:
        if refresh_cadence not in VALID_CADENCE:
            raise ValueError(f"invalid cadence: {refresh_cadence!r}")
        now = _now()
        existing = await self.get_dimension_by_name(name, company_id)
        dim_id = existing.dimension_id if existing else _sid("dim")
        created = existing.created_at if existing else now
        await self._db.execute_insert(
            "INSERT OR REPLACE INTO watch_dimensions (dimension_id, company_id, name, "
            "description, weight_pct, subcriteria_json, refresh_cadence, "
            "view_weights_json, sort_order, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                dim_id,
                company_id,
                name,
                description,
                float(weight_pct),
                json.dumps(subcriteria or []),
                refresh_cadence,
                json.dumps(view_weights or {}),
                int(sort_order),
                created,
                now,
            ),
        )
        dim = await self.get_dimension_by_name(name, company_id)
        assert dim is not None
        return dim

    async def list_dimensions(self, company_id: str) -> list[WatchDimension]:
        rows = await self._db.execute(
            "SELECT * FROM watch_dimensions WHERE company_id = ? "
            "ORDER BY sort_order, name",
            (company_id,),
        )
        return [self._to_dimension(r) for r in rows]

    async def get_dimension_by_name(
        self, name: str, company_id: str
    ) -> WatchDimension | None:
        rows = await self._db.execute(
            "SELECT * FROM watch_dimensions WHERE company_id = ? AND name = ?",
            (company_id, name),
        )
        return self._to_dimension(rows[0]) if rows else None

    @staticmethod
    def _to_dimension(r: Any) -> WatchDimension:
        return WatchDimension(
            dimension_id=r["dimension_id"],
            name=r["name"],
            company_id=r["company_id"],
            description=_row_get(r, "description", "") or "",
            weight_pct=float(_row_get(r, "weight_pct", 0) or 0),
            subcriteria=json.loads(_row_get(r, "subcriteria_json", "[]") or "[]"),
            refresh_cadence=_row_get(r, "refresh_cadence", "monthly") or "monthly",
            view_weights=json.loads(_row_get(r, "view_weights_json", "{}") or "{}"),
            sort_order=int(_row_get(r, "sort_order", 0) or 0),
            created_at=_row_get(r, "created_at", "") or "",
            updated_at=_row_get(r, "updated_at", "") or "",
        )

    # ── Evidence (append-only) ──────────────────────────────────────

    async def add_evidence(
        self,
        *,
        company_id: str,
        subject_id: str,
        dimension_id: str,
        claim: str,
        subcriterion: str = "",
        value_text: str = "",
        value_num: float | None = None,
        source_url: str = "",
        source_type: str = "site",
        geo_state: str = "n/a",
        customer_state: str = "logged_out",
        journey_stage: str = "",
        observed_at: str = "",
        confidence: str = "medium",
        excerpt: str = "",
        screenshot_path: str = "",
        collector: str = "agent",
        exit_ip: str = "",
        supersedes: str | None = None,
    ) -> WatchEvidence:
        """Record one observed fact. Never mutates prior evidence.

        ``supersedes`` marks an earlier row as replaced (a correction or a
        re-observation) rather than editing it, preserving the history a
        month-over-month diff depends on.
        """
        if confidence not in VALID_CONFIDENCE:
            raise ValueError(f"invalid confidence: {confidence!r}")
        if customer_state not in VALID_CUSTOMER_STATES:
            raise ValueError(f"invalid customer_state: {customer_state!r}")
        if collector not in VALID_COLLECTOR:
            raise ValueError(f"invalid collector: {collector!r}")
        now = _now()
        ev = WatchEvidence(
            evidence_id=_sid("ev"),
            subject_id=subject_id,
            dimension_id=dimension_id,
            claim=claim,
            company_id=company_id,
            subcriterion=subcriterion,
            value_text=value_text,
            value_num=value_num,
            source_url=source_url,
            source_type=source_type,
            geo_state=geo_state,
            customer_state=customer_state,
            journey_stage=journey_stage,
            observed_at=observed_at or now,
            confidence=confidence,
            excerpt=excerpt,
            screenshot_path=screenshot_path,
            collector=collector,
            exit_ip=exit_ip,
            created_at=now,
        )
        await self._db.execute_insert(
            "INSERT INTO watch_evidence (evidence_id, company_id, subject_id, "
            "dimension_id, subcriterion, claim, value_text, value_num, source_url, "
            "source_type, geo_state, customer_state, journey_stage, observed_at, "
            "confidence, excerpt, screenshot_path, collector, exit_ip, "
            "superseded_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
            (
                ev.evidence_id,
                company_id,
                subject_id,
                dimension_id,
                subcriterion,
                claim,
                value_text,
                value_num,
                source_url,
                source_type,
                geo_state,
                customer_state,
                journey_stage,
                ev.observed_at,
                confidence,
                excerpt,
                screenshot_path,
                collector,
                exit_ip,
                now,
            ),
        )
        if supersedes:
            await self._db.execute(
                "UPDATE watch_evidence SET superseded_by = ? WHERE evidence_id = ?",
                (ev.evidence_id, supersedes),
            )
        return ev

    async def list_evidence(
        self,
        company_id: str,
        *,
        subject_id: str | None = None,
        dimension_id: str | None = None,
        include_superseded: bool = False,
        limit: int = 200,
    ) -> list[WatchEvidence]:
        sql = "SELECT * FROM watch_evidence WHERE company_id = ?"
        args: list[Any] = [company_id]
        if subject_id:
            sql += " AND subject_id = ?"
            args.append(subject_id)
        if dimension_id:
            sql += " AND dimension_id = ?"
            args.append(dimension_id)
        if not include_superseded:
            sql += " AND superseded_by IS NULL"
        sql += " ORDER BY observed_at DESC LIMIT ?"
        args.append(int(limit))
        return [self._to_evidence(r) for r in await self._db.execute(sql, tuple(args))]

    @staticmethod
    def _to_evidence(r: Any) -> WatchEvidence:
        return WatchEvidence(
            evidence_id=r["evidence_id"],
            subject_id=r["subject_id"],
            dimension_id=r["dimension_id"],
            claim=r["claim"],
            company_id=r["company_id"],
            subcriterion=_row_get(r, "subcriterion", "") or "",
            value_text=_row_get(r, "value_text", "") or "",
            value_num=_row_get(r, "value_num"),
            source_url=_row_get(r, "source_url", "") or "",
            source_type=_row_get(r, "source_type", "site") or "site",
            geo_state=_row_get(r, "geo_state", "n/a") or "n/a",
            customer_state=_row_get(r, "customer_state", "logged_out") or "logged_out",
            journey_stage=_row_get(r, "journey_stage", "") or "",
            observed_at=_row_get(r, "observed_at", "") or "",
            confidence=_row_get(r, "confidence", "medium") or "medium",
            excerpt=_row_get(r, "excerpt", "") or "",
            screenshot_path=_row_get(r, "screenshot_path", "") or "",
            collector=_row_get(r, "collector", "agent") or "agent",
            exit_ip=_row_get(r, "exit_ip", "") or "",
            superseded_by=_row_get(r, "superseded_by"),
            created_at=_row_get(r, "created_at", "") or "",
        )

    # ── Scores ──────────────────────────────────────────────────────

    async def set_score(
        self,
        *,
        company_id: str,
        subject_id: str,
        dimension_id: str,
        score: float | None,
        rationale: str = "",
        subcriteria_scores: dict[str, float] | None = None,
        scored_by: str = "agent",
    ) -> WatchScore:
        """Score one subject x dimension **from its evidence**.

        Coverage and confidence are derived from the evidence rows, never
        supplied by the caller — that is what keeps them honest. Scoring with
        zero evidence is refused; the correct representation of "we don't know"
        is a NULL score with its coverage gap, which ``clear_score`` records.
        """
        if score is not None and not (1 <= float(score) <= 5):
            raise ValueError("score must be between 1 and 5, or None")

        evidence = await self.list_evidence(
            company_id, subject_id=subject_id, dimension_id=dimension_id
        )
        if score is not None and not evidence:
            raise ValueError(
                "cannot score a dimension with no evidence — collect evidence "
                "first, or leave the score NULL to record the gap"
            )

        dim_rows = await self._db.execute(
            "SELECT * FROM watch_dimensions WHERE dimension_id = ?", (dimension_id,)
        )
        subcriteria = self._to_dimension(dim_rows[0]).subcriteria if dim_rows else []
        covered = {e.subcriterion for e in evidence if e.subcriterion}
        cov = coverage_pct(subcriteria, covered)
        conf = confidence_rollup([e.confidence for e in evidence])

        now = _now()
        existing = await self._db.execute(
            "SELECT score_id, scored_at FROM watch_scores WHERE company_id = ? "
            "AND subject_id = ? AND dimension_id = ?",
            (company_id, subject_id, dimension_id),
        )
        score_id = existing[0]["score_id"] if existing else _sid("scr")
        await self._db.execute_insert(
            "INSERT OR REPLACE INTO watch_scores (score_id, company_id, subject_id, "
            "dimension_id, score, subcriteria_scores_json, rationale, "
            "evidence_ids_json, coverage_pct, confidence, scored_at, scored_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                score_id,
                company_id,
                subject_id,
                dimension_id,
                None if score is None else float(score),
                json.dumps(subcriteria_scores or {}),
                rationale,
                json.dumps([e.evidence_id for e in evidence]),
                cov,
                conf,
                now,
                scored_by,
            ),
        )
        return WatchScore(
            score_id=score_id,
            subject_id=subject_id,
            dimension_id=dimension_id,
            company_id=company_id,
            score=None if score is None else float(score),
            subcriteria_scores=subcriteria_scores or {},
            rationale=rationale,
            evidence_ids=[e.evidence_id for e in evidence],
            coverage_pct=cov,
            confidence=conf,
            scored_at=now,
            scored_by=scored_by,
        )

    async def list_scores(
        self, company_id: str, *, subject_id: str | None = None
    ) -> list[WatchScore]:
        sql = "SELECT * FROM watch_scores WHERE company_id = ?"
        args: list[Any] = [company_id]
        if subject_id:
            sql += " AND subject_id = ?"
            args.append(subject_id)
        return [self._to_score(r) for r in await self._db.execute(sql, tuple(args))]

    @staticmethod
    def _to_score(r: Any) -> WatchScore:
        raw = _row_get(r, "score")
        return WatchScore(
            score_id=r["score_id"],
            subject_id=r["subject_id"],
            dimension_id=r["dimension_id"],
            company_id=r["company_id"],
            score=None if raw is None else float(raw),
            subcriteria_scores=json.loads(
                _row_get(r, "subcriteria_scores_json", "{}") or "{}"
            ),
            rationale=_row_get(r, "rationale", "") or "",
            evidence_ids=json.loads(_row_get(r, "evidence_ids_json", "[]") or "[]"),
            coverage_pct=float(_row_get(r, "coverage_pct", 0) or 0),
            confidence=_row_get(r, "confidence", "low") or "low",
            scored_at=_row_get(r, "scored_at", "") or "",
            scored_by=_row_get(r, "scored_by", "agent") or "agent",
        )

    # ── Scorecard ───────────────────────────────────────────────────

    async def scorecard(self, company_id: str) -> dict[str, Any]:
        """Assemble the full weighted scorecard for a company's market."""
        subjects = await self.list_subjects(company_id)
        dimensions = await self.list_dimensions(company_id)
        all_scores = await self.list_scores(company_id)
        by_subject: dict[str, dict[str, WatchScore]] = {}
        for s in all_scores:
            by_subject.setdefault(s.subject_id, {})[s.dimension_id] = s
        return build_scorecard(subjects, dimensions, by_subject)

    async def evidence_with_names(
        self,
        company_id: str,
        *,
        limit: int | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        """Live evidence with subject/dimension names resolved — for export.

        Scoped to the ACTIVE register by default: an archived brand's rows
        stay in the store (append-only) but do not ship in a deliverable that
        claims a canonical brand list. Uncapped by default — a silent 2,000-
        row cap once truncated a 1,900+-row run's export by exactly the rows
        that would have shown its completeness. Pass ``limit`` for previews.
        """
        subjects = {
            s.subject_id: s.name
            for s in await self.list_subjects(
                company_id, include_archived=include_archived
            )
        }
        dims = {d.dimension_id: d.name for d in await self.list_dimensions(company_id)}
        rows = await self.list_evidence(
            company_id, limit=limit if limit is not None else 1_000_000
        )
        rows = [e for e in rows if e.subject_id in subjects]
        return [
            {
                "subject": subjects.get(e.subject_id, e.subject_id),
                "dimension": dims.get(e.dimension_id, e.dimension_id),
                "subcriterion": e.subcriterion,
                "claim": e.claim,
                "value_text": e.value_text,
                "source_url": e.source_url,
                "source_type": e.source_type,
                "geo_state": e.geo_state,
                "customer_state": e.customer_state,
                "observed_at": e.observed_at,
                "confidence": e.confidence,
                "collector": e.collector,
                "excerpt": e.excerpt,
                "screenshot_path": e.screenshot_path,
                "exit_ip": e.exit_ip,
            }
            for e in rows
        ]

    # ── Snapshots + change detection ────────────────────────────────

    # ── Voice of customer (docs/87) ──────────────────────────────────

    async def add_voice(
        self,
        *,
        company_id: str,
        subject_id: str,
        source: str,
        theme: str,
        sentiment: str,
        quote: str = "",
        source_url: str = "",
        posted_at: str = "",
        observed_at: str = "",
        exit_ip: str = "",
        rating: float | None = None,
        dimension_id: str = "",
        geo_hint: str = "",
        weight: float = 1.0,
    ) -> WatchVoice | None:
        """Record one thing a player said. Append-only; a duplicate (same
        brand, same normalised quote) is ignored and returns None. Never
        touches watch_evidence or any score."""
        if source not in VOICE_SOURCES:
            raise ValueError(f"invalid voice source: {source!r}")
        if theme not in VOICE_THEMES:
            raise ValueError(f"invalid voice theme: {theme!r}")
        if sentiment not in VOICE_SENTIMENTS:
            raise ValueError(f"invalid voice sentiment: {sentiment!r}")
        quote = " ".join((quote or "").split())[:240]
        now = _now()
        row = WatchVoice(
            voice_id=_sid("vo"),
            subject_id=subject_id,
            source=source,
            theme=theme,
            sentiment=sentiment,
            company_id=company_id,
            source_url=source_url,
            posted_at=posted_at,
            observed_at=observed_at or now,
            exit_ip=exit_ip,
            rating=rating,
            quote=quote,
            dimension_id=dimension_id,
            geo_hint=geo_hint,
            weight=max(0.0, min(1.0, float(weight))),
            dedupe_key=voice_dedupe_key(quote, source_url),
            created_at=now,
        )
        dup = await self._db.execute(
            "SELECT 1 FROM watch_voice WHERE company_id = ? AND subject_id = ? "
            "AND dedupe_key = ?",
            (company_id, subject_id, row.dedupe_key),
        )
        if dup:
            return None
        await self._db.execute_insert(
            "INSERT INTO watch_voice (voice_id, company_id, subject_id, source, "
            "source_url, posted_at, observed_at, exit_ip, rating, theme, sentiment, "
            "quote, dimension_id, geo_hint, weight, dedupe_key, created_at) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row.voice_id,
                company_id,
                subject_id,
                source,
                source_url,
                posted_at,
                row.observed_at,
                exit_ip,
                rating,
                theme,
                sentiment,
                row.quote,
                dimension_id,
                geo_hint,
                row.weight,
                row.dedupe_key,
                now,
            ),
        )
        return row

    async def list_voice(
        self,
        company_id: str,
        *,
        subject_id: str | None = None,
        source: str | None = None,
        theme: str | None = None,
        since: str = "",
        limit: int = 500,
    ) -> list[WatchVoice]:
        sql = "SELECT * FROM watch_voice WHERE company_id = ?"
        args: list[Any] = [company_id]
        if subject_id:
            sql += " AND subject_id = ?"
            args.append(subject_id)
        if source:
            sql += " AND source = ?"
            args.append(source)
        if theme:
            sql += " AND theme = ?"
            args.append(theme)
        if since:
            sql += " AND (CASE WHEN posted_at != '' THEN posted_at ELSE observed_at END) >= ?"
            args.append(since)
        sql += " ORDER BY (CASE WHEN posted_at != '' THEN posted_at ELSE observed_at END) DESC LIMIT ?"
        args.append(int(limit))
        return [self._to_voice(r) for r in await self._db.execute(sql, tuple(args))]

    @staticmethod
    def _to_voice(r: Any) -> WatchVoice:
        return WatchVoice(
            voice_id=r["voice_id"],
            subject_id=r["subject_id"],
            source=r["source"],
            theme=r["theme"],
            sentiment=r["sentiment"],
            company_id=r["company_id"],
            source_url=_row_get(r, "source_url", "") or "",
            posted_at=_row_get(r, "posted_at", "") or "",
            observed_at=_row_get(r, "observed_at", "") or "",
            exit_ip=_row_get(r, "exit_ip", "") or "",
            rating=_row_get(r, "rating"),
            quote=_row_get(r, "quote", "") or "",
            dimension_id=_row_get(r, "dimension_id", "") or "",
            geo_hint=_row_get(r, "geo_hint", "") or "",
            weight=float(_row_get(r, "weight", 1.0) or 0.0),
            dedupe_key=_row_get(r, "dedupe_key", "") or "",
            created_at=_row_get(r, "created_at", "") or "",
        )

    async def voice_summary(
        self,
        company_id: str,
        *,
        window_days: int = 30,
        min_mentions: int = VOICE_MIN_MENTIONS,
    ) -> dict[str, Any]:
        """What players said, per active brand and field-wide, in the window."""
        subjects = await self.list_subjects(company_id)
        rows = await self.list_voice(company_id, limit=20000)
        return summarize_voice(
            rows, subjects, window_days=window_days, min_mentions=min_mentions
        )

    # ── Alerts (docs/88 §B) ──────────────────────────────────────────

    async def record_alerts(
        self, company_id: str, candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Store alert candidates that are new for this company (dedupe key);
        return the ones actually stored, with ids. Resolves subject_id by
        name when the brand is in the register."""
        names = {s.name: s.subject_id for s in await self.list_subjects(company_id)}
        stored: list[dict[str, Any]] = []
        now = _now()
        for c in candidates:
            key = str(c.get("dedupe_key") or "")
            if not key:
                continue
            dup = await self._db.execute(
                "SELECT 1 FROM watch_alerts WHERE company_id = ? AND dedupe_key = ?",
                (company_id, key),
            )
            if dup:
                continue
            aid = _sid("al")
            await self._db.execute_insert(
                "INSERT INTO watch_alerts (alert_id, company_id, kind, subject_id, subject_name, "
                "title, detail, source_url, detected_at, notified_at, dedupe_key) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                (
                    aid,
                    company_id,
                    str(c.get("kind") or "other"),
                    names.get(str(c.get("subject_name") or ""), ""),
                    str(c.get("subject_name") or ""),
                    str(c.get("title") or "")[:200],
                    str(c.get("detail") or "")[:1000],
                    str(c.get("source_url") or ""),
                    now,
                    key,
                ),
            )
            stored.append({**c, "alert_id": aid, "detected_at": now})
        return stored

    async def list_alerts(
        self, company_id: str, *, since: str = "", unnotified_only: bool = False, limit: int = 100
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM watch_alerts WHERE company_id = ?"
        args: list[Any] = [company_id]
        if since:
            sql += " AND detected_at >= ?"
            args.append(since)
        if unnotified_only:
            sql += " AND notified_at IS NULL"
        sql += " ORDER BY detected_at DESC LIMIT ?"
        args.append(int(limit))
        rows = await self._db.execute(sql, tuple(args))
        return [
            {
                "alert_id": r["alert_id"],
                "kind": r["kind"],
                "subject_name": _row_get(r, "subject_name", "") or "",
                "title": r["title"],
                "detail": _row_get(r, "detail", "") or "",
                "source_url": _row_get(r, "source_url", "") or "",
                "detected_at": r["detected_at"],
                "notified_at": _row_get(r, "notified_at"),
            }
            for r in rows
        ]

    async def mark_alerts_notified(self, alert_ids: list[str]) -> None:
        now = _now()
        for aid in alert_ids:
            await self._db.execute(
                "UPDATE watch_alerts SET notified_at = ? WHERE alert_id = ?", (now, aid)
            )

    async def take_snapshot(self, company_id: str, *, label: str = "") -> str:
        """Freeze the current scorecard so future months have something to
        diff against — and the voice summary beside it, so theme deltas
        diff the same way. Returns the snapshot id."""
        card = await self.scorecard(company_id)
        try:
            voice = await self.voice_summary(company_id)
            if voice.get("mentions"):
                card["voice"] = voice
        except Exception:  # voice must never break a scorecard snapshot
            pass
        snap_id = _sid("snap")
        await self._db.execute_insert(
            "INSERT INTO watch_snapshots (snapshot_id, company_id, taken_at, "
            "label, payload_json) VALUES (?, ?, ?, ?, ?)",
            (snap_id, company_id, _now(), label, json.dumps(card)),
        )
        return snap_id

    async def list_snapshots(
        self, company_id: str, *, limit: int = 24
    ) -> list[dict[str, Any]]:
        rows = await self._db.execute(
            "SELECT snapshot_id, taken_at, label FROM watch_snapshots "
            "WHERE company_id = ? ORDER BY taken_at DESC LIMIT ?",
            (company_id, int(limit)),
        )
        return [
            {
                "snapshot_id": r["snapshot_id"],
                "taken_at": r["taken_at"],
                "label": _row_get(r, "label", "") or "",
            }
            for r in rows
        ]

    async def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        rows = await self._db.execute(
            "SELECT payload_json FROM watch_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        if not rows:
            return None
        return json.loads(rows[0]["payload_json"] or "{}")

    async def latest_snapshot(
        self, company_id: str
    ) -> tuple[str, dict[str, Any]] | None:
        rows = await self._db.execute(
            "SELECT snapshot_id, payload_json FROM watch_snapshots "
            "WHERE company_id = ? ORDER BY taken_at DESC LIMIT 1",
            (company_id,),
        )
        if not rows:
            return None
        return rows[0]["snapshot_id"], json.loads(rows[0]["payload_json"] or "{}")

    async def diff_since_snapshot(
        self,
        company_id: str,
        *,
        snapshot_id: str | None = None,
        min_score_delta: float = 1.0,
    ) -> dict[str, Any] | None:
        """Diff the live scorecard against a snapshot (default: the latest)."""
        if snapshot_id:
            old = await self.get_snapshot(snapshot_id)
            sid = snapshot_id
        else:
            latest = await self.latest_snapshot(company_id)
            if latest is None:
                return None
            sid, old = latest
        if old is None:
            return None
        new = await self.scorecard(company_id)
        out = diff_scorecards(old, new, min_score_delta=min_score_delta)
        out["against_snapshot"] = sid
        return out

    async def diff_voice_since_snapshot(
        self, company_id: str, *, snapshot_id: str | None = None
    ) -> dict[str, Any] | None:
        """Theme deltas of the live voice summary against a snapshot's
        ``voice`` section (default: the latest snapshot). None when there is
        no snapshot at all; ``baseline: true`` when the snapshot carried no
        voice — the first cycle."""
        if snapshot_id:
            old = await self.get_snapshot(snapshot_id)
            sid = snapshot_id
        else:
            latest = await self.latest_snapshot(company_id)
            if latest is None:
                return None
            sid, old = latest
        if old is None:
            return None
        new = await self.voice_summary(company_id)
        out = diff_voice(old.get("voice") if isinstance(old, dict) else None, new)
        out["against_snapshot"] = sid
        return out

    async def evidence_since(
        self, company_id: str, since_iso: str, *, limit: int = 500
    ) -> list[WatchEvidence]:
        """Evidence observed since a timestamp — what actually drove the change."""
        rows = await self._db.execute(
            "SELECT * FROM watch_evidence WHERE company_id = ? AND observed_at > ? "
            "ORDER BY observed_at DESC LIMIT ?",
            (company_id, since_iso, int(limit)),
        )
        return [self._to_evidence(r) for r in rows]

    async def staleness(self, company_id: str) -> list[dict[str, Any]]:
        """Which subject x dimension pairs are overdue for a refresh.

        Each dimension declares a cadence (weekly / monthly / quarterly); a pair
        is stale when its newest live evidence is older than that, and 'never
        observed' when there is none. This is what stops a scorecard quietly
        ageing into fiction.
        """
        subjects = await self.list_subjects(company_id)
        dimensions = await self.list_dimensions(company_id)
        rows = await self._db.execute(
            "SELECT subject_id, dimension_id, MAX(observed_at) AS last_seen "
            "FROM watch_evidence WHERE company_id = ? AND superseded_by IS NULL "
            "GROUP BY subject_id, dimension_id",
            (company_id,),
        )
        last: dict[tuple[str, str], str] = {
            (r["subject_id"], r["dimension_id"]): r["last_seen"] for r in rows
        }
        now = datetime.now(UTC)
        out: list[dict[str, Any]] = []
        for subj in subjects:
            for dim in dimensions:
                seen = last.get((subj.subject_id, dim.dimension_id))
                max_age = CADENCE_DAYS.get(dim.refresh_cadence, 30)
                if not seen:
                    out.append(
                        {
                            "subject": subj.name,
                            "dimension": dim.name,
                            "cadence": dim.refresh_cadence,
                            "last_observed": None,
                            "age_days": None,
                            "status": "never_observed",
                        }
                    )
                    continue
                try:
                    age = (now - datetime.fromisoformat(seen)).days
                except ValueError:
                    continue
                if age > max_age:
                    out.append(
                        {
                            "subject": subj.name,
                            "dimension": dim.name,
                            "cadence": dim.refresh_cadence,
                            "last_observed": seen,
                            "age_days": age,
                            "status": "stale",
                        }
                    )
        return out
