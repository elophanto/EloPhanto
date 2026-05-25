"""Scored candidate arbitration for the autonomous mind.

The legacy mind picks an action via a free-form LLM prompt over the
entire state snapshot. That worked for "what should I do when I have
nothing to do" (dream phase) but collapsed under partial state — one
stuck active goal sucked all attention before the dream could fire,
even when affect / ego / identity / missions all pointed elsewhere
(see ``docs/75-AUTONOMOUS-MIND-V2.md`` for the 36h reconciliation
loop that triggered this redesign).

The arbiter inverts the responsibility:

  - **candidate generators** (one per source) produce typed
    ``Candidate`` objects from real state — workable checkpoints,
    neglected missions, dream proposals, due reflexes, external
    signals.
  - **the arbiter** scores them with explicit weights, dedups by
    ``dedup_key``, sorts, returns the top-K.
  - **the mind's LLM** sees a short ranked menu plus the reasoning
    behind each score, and picks one. The LLM still has agency, but
    over a *menu generated from real state* rather than a wall of
    context.

This is the same shape as Voyager's curriculum, Generative Agents'
reflection loop, and motivated-RL choice arbitration: many drives,
one executive, transparent scoring.

See ``docs/75-AUTONOMOUS-MIND-V2.md`` §Phase 3.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """One scoreable action proposal.

    Frozen so the arbiter can put candidates in sets / dicts keyed by
    ``dedup_key``. All numeric fields are on intuitive scales chosen
    so the default weights in ``ArbiterWeights`` land near-equal
    contributions for a "typical" candidate:

      - ``expected_value``: 0–10. How much value finishing this would
        produce. A small post is ~2; a mission-moving artifact is ~6;
        a major launch step is ~9.
      - ``feasibility``: 0–1. Probability the agent can actually
        finish this in one wakeup. Single-tool actions ~0.9; multi-
        step browser flows ~0.5; experimental research ~0.3.
      - ``lens_match``: 0–1. How well this candidate matches today's
        dream-focus value lens. Set by the generator that knows the
        lens; sources that don't care just pass 0.5.
      - ``cost``: 0–10. Estimated LLM cost + opportunity cost in
        "units". Higher = worse. Cheap mind-only actions ~1; full
        browser flows ~5; long research ~7.
      - ``staleness_bonus``: 0–10. Time-since-last-touch encoded as a
        positive contribution. The neglect-aware sources (mission
        momentum, capability reflex) set this; sources without a
        "since when" concept pass 0.
      - ``affect_bias``: -2 to +2. Felt-state nudge from the affect
        manager. Frustration with a stuck domain → negative bias on
        more of the same; pride after a posting win → positive bias
        on continuing.

    ``mission_id`` is the parent mission slug when applicable — the
    arbiter applies a multiplier from ``ArbiterWeights.mission_weight``
    so high-weight missions win ties.

    ``dedup_key`` is a generator-supplied stable identifier ("same
    underlying action, even if proposed twice this wakeup"). Common
    pattern: ``f"goal:{goal_id}:ckpt:{order}"`` for a checkpoint, or
    ``f"mission_post:{mission_id}"`` for a mission-driven post.
    Default: the SHA1 of ``source + action_spec`` so duplicates from
    the same generator with the same prose collapse automatically.
    """

    source: str
    action_spec: str
    expected_value: float = 5.0
    feasibility: float = 0.7
    lens_match: float = 0.5
    cost: float = 2.0
    staleness_bonus: float = 0.0
    affect_bias: float = 0.0
    mission_id: str | None = None
    dedup_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # ABE Phase 4 (docs/76-ABE-FRAMEWORK.md). How far this candidate's
    # role is from its declared KPI target, normalized to 0–1.
    # 0.0 = role is meeting or exceeding all KPIs (no extra pull).
    # 1.0 = role has zero progress against its targets (max pull).
    # Computed by ``from_role_neglect`` from the role's ``kpi`` map +
    # the ledger sums over the past 7 days. Default 0.0 so non-role
    # candidates and legacy constructors are unaffected.
    kpi_gap: float = 0.0

    def stable_dedup_key(self) -> str:
        """Return ``dedup_key`` if set, else a stable hash of
        ``source + action_spec``. Used by the arbiter to keep the
        highest-scoring duplicate when multiple generators propose
        the same action."""
        if self.dedup_key:
            return self.dedup_key
        payload = f"{self.source}|{self.action_spec}".encode()
        return hashlib.sha1(payload).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArbiterWeights:
    """Knobs for the score combiner.

    Defaults chosen so the most common candidate (a moderate-value
    moderate-feasibility checkpoint) scores around 4–5 and rare
    high-leverage candidates (a neglected high-weight mission move)
    score around 7–9. The actual numbers don't matter — only the
    ordering does. Tune the weights to shift *which kinds of work*
    rise to the top, not the absolute scores.

    Live config maps to this dataclass via
    ``ArbiterWeights.from_config_dict``.
    """

    value: float = 1.0
    """Multiplier on ``expected_value * feasibility``. The core
    quality-vs-confidence term."""

    lens_bonus: float = 0.6
    """How much today's value-lens match boosts a candidate.
    ``score += lens_bonus * lens_match * (value * feasibility)``.
    A perfect lens match (1.0) gives a ~60% boost by default."""

    staleness_bonus: float = 0.4
    """Multiplier on each candidate's staleness_bonus. Lets neglected
    missions and overdue reflexes catch up to flashy new dreams."""

    affect_bias: float = 1.0
    """Multiplier on affect_bias. Frustration / pride directly add or
    subtract from the score. ±2 affect → ±2 raw score points."""

    cost: float = 0.3
    """Penalty per cost unit. Default 0.3 means a max-cost candidate
    (cost=10) loses 3 points, which a strong expected_value+feasibility
    can easily overcome."""

    mission_weight: float = 0.5
    """Per-priority-weight bonus for mission-parented candidates.
    A mission with priority_weight=2.5 gets +1.25 raw points by
    default — enough to break ties but not enough to overwhelm a
    genuinely better non-mission candidate."""

    kpi_gap_weight: float = 0.4
    """ABE Phase 4: per-unit-gap multiplier on a role candidate's
    ``kpi_gap``. The score line is
    ``score += kpi_gap_weight * kpi_gap * 10`` so a max-gap role
    (1.0) earns +4 by default — comparable to a stale mission move
    and enough to nudge the arbiter toward the role whose ledger
    sums lag furthest behind its target. Set to 0 to disable
    KPI-gap biasing without removing role candidates from the menu."""

    @classmethod
    def from_config_dict(cls, d: dict[str, Any] | None) -> ArbiterWeights:
        """Build weights from a config dict, falling back to defaults
        for any missing keys. Unknown keys are ignored so a config
        ahead of this code doesn't crash."""
        if not d:
            return cls()
        defaults = cls()
        return cls(
            value=float(d.get("value", defaults.value)),
            lens_bonus=float(d.get("lens_bonus", defaults.lens_bonus)),
            staleness_bonus=float(d.get("staleness_bonus", defaults.staleness_bonus)),
            affect_bias=float(d.get("affect_bias", defaults.affect_bias)),
            cost=float(d.get("cost", defaults.cost)),
            mission_weight=float(d.get("mission_weight", defaults.mission_weight)),
            kpi_gap_weight=float(d.get("kpi_gap_weight", defaults.kpi_gap_weight)),
        )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_candidate(
    c: Candidate,
    weights: ArbiterWeights,
    mission_weights: dict[str, float] | None = None,
) -> float:
    """Combine candidate signals into a single comparable score.

    The formula is intentionally linear and inspectable: every term
    on its own line, no hidden squashing. Operators tuning a system
    on this kind of arbiter want to read the score and immediately
    see *which input boosted it*. A more clever combiner (logistic,
    learned, MoE) is a future replacement; the contract here is just
    "higher = better".

    ``mission_weights`` is the live ``mission_id → priority_weight``
    map. Candidates with no parent mission get 0 from this term —
    they're not penalized, they just don't get the bonus.
    """
    quality = c.expected_value * c.feasibility
    score = weights.value * quality
    score += weights.lens_bonus * c.lens_match * quality
    score += weights.staleness_bonus * c.staleness_bonus
    score += weights.affect_bias * c.affect_bias
    score -= weights.cost * c.cost
    if c.mission_id and mission_weights:
        score += weights.mission_weight * mission_weights.get(c.mission_id, 0.0)
    # ABE Phase 4: KPI-gap term. Multiplier of 10 scales a 0–1 gap
    # into 0–10 raw points before the weight multiplier — so default
    # weights put a max-gap role at +4, on par with a stale mission.
    score += weights.kpi_gap_weight * c.kpi_gap * 10
    return score


# ---------------------------------------------------------------------------
# Arbiter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoredCandidate:
    """A candidate plus its computed score. Returned by the arbiter
    so the LLM-facing renderer can show both the proposal and the
    reasoning behind its rank."""

    candidate: Candidate
    score: float


def arbitrate(
    candidates: list[Candidate],
    weights: ArbiterWeights,
    *,
    mission_weights: dict[str, float] | None = None,
    top_k: int = 5,
) -> list[ScoredCandidate]:
    """Score, dedup, sort, truncate.

    Dedup keeps the *highest-scoring* candidate per ``dedup_key`` —
    two generators proposing the same action don't double-count, and
    if one of them scored it higher (better expected_value, better
    feasibility), that's the version the LLM sees. Ties broken by
    insertion order so the result is deterministic for a fixed input
    list.

    Returns a list of ``ScoredCandidate`` of length ≤ ``top_k``. Empty
    input → empty output; the caller decides what to do with that
    (typically: force dream phase, the same way the legacy mind did).
    """
    if not candidates:
        return []

    scored: list[ScoredCandidate] = [
        ScoredCandidate(candidate=c, score=score_candidate(c, weights, mission_weights))
        for c in candidates
    ]

    # Dedup by stable key, keep highest-scoring per key. We iterate in
    # original order; when a duplicate key shows up with a higher
    # score, replace. Python dicts preserve insertion order, so the
    # final sort is the only place ordering is reshuffled.
    best_by_key: dict[str, ScoredCandidate] = {}
    for sc in scored:
        key = sc.candidate.stable_dedup_key()
        existing = best_by_key.get(key)
        if existing is None or sc.score > existing.score:
            best_by_key[key] = sc

    final = list(best_by_key.values())
    final.sort(key=lambda sc: sc.score, reverse=True)
    return final[:top_k]


# ---------------------------------------------------------------------------
# Rendering for the mind prompt
# ---------------------------------------------------------------------------


def render_menu(scored: list[ScoredCandidate], *, max_chars: int = 4000) -> str:
    """Format ranked candidates as a compact menu for the mind LLM.

    The whole point of the arbiter is to shrink the prompt — the mind
    no longer reads identity, affect, ego, missions, and goals as
    parallel sections. It reads a numbered list of *specific actions
    each with a transparent score*, and picks one. We keep this
    rendering plain and parseable so audit / dashboard surfaces can
    re-use it.

    Long candidate_specs are truncated to keep the menu under
    ``max_chars`` overall — the LLM picks by score and headline, not
    by long-form proposal text.
    """
    if not scored:
        return "(no candidates — fall through to dream phase)"

    lines: list[str] = []
    total = 0
    per_cap = max(120, max_chars // max(1, len(scored)))
    for i, sc in enumerate(scored, start=1):
        c = sc.candidate
        spec = c.action_spec.strip().replace("\n", " ")
        if len(spec) > per_cap:
            spec = spec[: per_cap - 1].rstrip() + "…"
        meta_bits: list[str] = [f"source={c.source}"]
        if c.mission_id:
            meta_bits.append(f"mission={c.mission_id}")
        if c.feasibility != 0.7 or c.expected_value != 5.0:
            meta_bits.append(f"value={c.expected_value:.1f} feas={c.feasibility:.2f}")
        if c.staleness_bonus > 0:
            meta_bits.append(f"stale_bonus={c.staleness_bonus:.1f}")
        if c.affect_bias != 0:
            meta_bits.append(f"affect={c.affect_bias:+.1f}")
        meta = " · ".join(meta_bits)
        line = f"{i}. [score={sc.score:.2f}] ({meta})\n   {spec}"
        # Always include the first candidate — even a giant single
        # candidate gets rendered (truncated by per_cap above), so the
        # mind never sees an empty menu when the arbiter ranked
        # something. Subsequent candidates obey max_chars.
        if lines and total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)
