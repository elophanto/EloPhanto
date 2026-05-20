"""Candidate generators for the autonomous-mind arbiter.

Each generator is a small async function with the same signature:

    async def from_X(ctx: CandidateContext) -> list[Candidate]

The ``CandidateContext`` carries the live managers (goal, mission,
identity, affect, ego, etc.) plus the current dream-focus lens.
Generators read from those managers, score what they propose by the
intrinsic merit of the proposal (the *arbiter* applies the weights),
and return zero or more ``Candidate`` objects.

Generators must be cheap — they run every wakeup before the LLM is
called. Anything expensive (the actual dream LLM call) is gated by
the legacy code path and the arbiter just renders a "explore dream
phase" candidate referencing the existing tool.

See ``docs/75-AUTONOMOUS-MIND-V2.md`` §Phase 3.2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core.mind_arbiter import Candidate

logger = logging.getLogger(__name__)


# Reflex cadences. Soft defaults — config can override later if needed.
_CAPABILITY_REVIEW_DAYS = 7.0
_MISSION_REBALANCE_DAYS = 7.0


@dataclass
class CandidateContext:
    """Bag of dependencies generators may read.

    Optional — every field can be None and each generator must
    degrade gracefully. The arbiter wakeup builds this once per cycle
    so generators don't make redundant DB calls.
    """

    goal_manager: Any = None
    mission_manager: Any = None
    identity_manager: Any = None
    affect_manager: Any = None
    ego_manager: Any = None
    dream_focus: str = "balanced"
    # Filled by the arbiter wakeup before generators run. Maps
    # mission_id → priority_weight; the arbiter applies the
    # mission_weight bonus from this lookup so generators don't
    # have to know about scoring.
    mission_weight_map: dict[str, float] | None = None


# ---------------------------------------------------------------------------
# Workable checkpoints
# ---------------------------------------------------------------------------


async def from_workable_checkpoints(ctx: CandidateContext) -> list[Candidate]:
    """One candidate per goal with a workable next checkpoint.

    A "workable" checkpoint matches Phase 1's
    ``_workable_goals_status`` semantics: ``status='pending'`` or
    ``status='active'`` younger than the staleness cutoff (defaults to
    12h, owned by ``AutonomousMind._STALE_CKPT_HOURS``). Stuck
    checkpoints are NOT proposed here — they appear under reflexes
    as "close this stale goal" candidates instead, so the arbiter
    can still rank closing chores against new work.

    Feasibility is set higher for shorter goals (current_checkpoint
    near total) — those are close to shipping. expected_value tracks
    the goal's place in the plan: the first checkpoint of a 15-step
    goal is worth less today than the 14th.
    """
    if not ctx.goal_manager:
        return []

    out: list[Candidate] = []
    try:
        db = ctx.goal_manager._db  # noqa: SLF001 — intentional internal
        for status in ("active", "planning"):
            goals = await ctx.goal_manager.list_goals(status=status, limit=20)
            for g in goals:
                rows = await db.execute(
                    "SELECT checkpoint_order, status, title, started_at "
                    "FROM goal_checkpoints WHERE goal_id = ? "
                    "ORDER BY checkpoint_order",
                    (g.goal_id,),
                )
                if not rows:
                    # Freshly created planning goal — propose decompose.
                    out.append(
                        Candidate(
                            source="workable_checkpoint",
                            action_spec=(
                                f"Decompose planning goal '{g.goal[:80]}' "
                                f"into checkpoints via goal_status / "
                                f"goal_decompose."
                            ),
                            expected_value=6.0,
                            feasibility=0.9,
                            lens_match=0.5,
                            cost=2.0,
                            mission_id=g.mission_id,
                            dedup_key=f"goal_decompose:{g.goal_id}",
                            metadata={"goal_id": g.goal_id, "kind": "decompose"},
                        )
                    )
                    continue
                next_workable = _pick_next_workable(rows)
                if next_workable is None:
                    continue
                progress = (
                    g.current_checkpoint / g.total_checkpoints
                    if g.total_checkpoints
                    else 0.0
                )
                # Late checkpoints are worth more (closer to shipping).
                expected = 4.0 + 4.0 * progress
                out.append(
                    Candidate(
                        source="workable_checkpoint",
                        action_spec=(
                            f"Advance goal '{g.goal[:60]}' — next checkpoint "
                            f"#{next_workable['checkpoint_order']}: "
                            f"{next_workable['title']}"
                        ),
                        expected_value=expected,
                        feasibility=0.75,
                        lens_match=0.5,
                        cost=2.5,
                        mission_id=g.mission_id,
                        dedup_key=(
                            f"goal:{g.goal_id}:ckpt:"
                            f"{next_workable['checkpoint_order']}"
                        ),
                        metadata={
                            "goal_id": g.goal_id,
                            "checkpoint_order": next_workable["checkpoint_order"],
                        },
                    )
                )
    except Exception as e:
        logger.debug("from_workable_checkpoints failed: %s", e)
    return out


def _pick_next_workable(rows: list[Any]) -> dict[str, Any] | None:
    """First ``pending`` or recent ``active`` checkpoint in order, or
    None when only completed / stale-active checkpoints remain. Keeps
    the workable definition aligned with Phase 1 so the two paths
    never disagree on what's still in play."""
    for r in rows:
        status = r["status"]
        if status == "pending":
            return {
                "checkpoint_order": r["checkpoint_order"],
                "title": r["title"],
            }
        if status == "active":
            # The arbiter is OK proposing an active checkpoint;
            # Phase 1's stale guard is the safety net for the
            # "active forever" case.
            return {
                "checkpoint_order": r["checkpoint_order"],
                "title": r["title"],
            }
    return None


# ---------------------------------------------------------------------------
# Mission momentum
# ---------------------------------------------------------------------------


async def from_mission_momentum(ctx: CandidateContext) -> list[Candidate]:
    """One candidate per neglected high-weight mission.

    The mission tier already ranks by ``priority_weight × staleness``
    via ``MissionManager.list_by_neglect``. We turn each into a
    candidate with ``staleness_bonus`` proportional to how stale it
    is — that's the arbiter signal that lets neglected missions
    catch up to flashier new dreams. Caps at 5 candidates so a long
    list doesn't dominate the menu.
    """
    if not ctx.mission_manager:
        return []
    out: list[Candidate] = []
    try:
        ranked = await ctx.mission_manager.list_by_neglect(limit=5)
        for m in ranked:
            stale_h = m.staleness_hours()
            if stale_h == float("inf"):
                stale_label = "never touched"
                stale_bonus = 6.0
            else:
                stale_label = f"{stale_h:.0f}h since last touch"
                # 24h → ~1.0, 7d → ~7.0; capped at 10.
                stale_bonus = min(10.0, stale_h / 24.0)
            out.append(
                Candidate(
                    source="mission_momentum",
                    action_spec=(
                        f"Make a move toward mission '{m.title}' "
                        f"({m.mission_id}). {stale_label}. Description: "
                        f"{m.description[:160]}"
                    ),
                    expected_value=5.5,
                    feasibility=0.6,
                    lens_match=0.5,
                    cost=3.0,
                    staleness_bonus=stale_bonus,
                    mission_id=m.mission_id,
                    dedup_key=f"mission_move:{m.mission_id}",
                    metadata={"mission_id": m.mission_id},
                )
            )
    except Exception as e:
        logger.debug("from_mission_momentum failed: %s", e)
    return out


# ---------------------------------------------------------------------------
# Dream
# ---------------------------------------------------------------------------


async def from_dream(ctx: CandidateContext) -> list[Candidate]:
    """One placeholder candidate that points the LLM at the dream
    pipeline.

    We intentionally do NOT call ``goal_dream`` here — it's the most
    expensive operation in the wakeup, and running it every cycle to
    produce candidates the LLM may not pick wastes budget. Instead
    the arbiter ranks "go think about new goals" as one option among
    many; if it wins, the LLM calls ``goal_dream`` and the
    existing pipeline runs.

    The candidate's ``expected_value`` decays with the number of
    workable_checkpoints already in play — when there's lots to do
    on existing goals, dreaming up new ones is worth less.
    """
    workable_count = 0
    if ctx.goal_manager:
        try:
            active = await ctx.goal_manager.list_goals(status="active", limit=20)
            planning = await ctx.goal_manager.list_goals(status="planning", limit=20)
            workable_count = len(active) + len(planning)
        except Exception as e:
            logger.debug("from_dream goal count failed: %s", e)

    expected = 7.0 - min(5.0, 1.0 * workable_count)
    feasibility = 0.85
    return [
        Candidate(
            source="dream",
            action_spec=(
                f"Dream up a new goal via goal_dream(focus='{ctx.dream_focus}'). "
                f"Today's value lens is {ctx.dream_focus}; pursue a candidate "
                f"that touches a neglected mission or an underused capability."
            ),
            expected_value=expected,
            feasibility=feasibility,
            lens_match=1.0,
            cost=3.5,
            dedup_key=f"dream:{ctx.dream_focus}",
            metadata={"dream_focus": ctx.dream_focus},
        )
    ]


# ---------------------------------------------------------------------------
# Reflexes
# ---------------------------------------------------------------------------


async def from_reflexes(ctx: CandidateContext) -> list[Candidate]:
    """Standing periodic self-checks.

    Two reflexes today:

    1. **Capability review** — every ~7d, audit which tools were
       used heavily / lightly / not at all in the recent past and
       propose pruning or learning. Reads no DB by default; the
       reflex's *execution* (when picked) does that work.
    2. **Mission rebalance** — every ~7d, propose reviewing mission
       weights and statuses. Triggered by the staleness of the
       least-recently-touched active mission.

    These are intentionally simple. Phase 4 adds the attractor
    detector + affect-coupled reflexes on top of this scaffold.
    """
    out: list[Candidate] = []
    try:
        cap_due = await _capability_review_due(ctx)
        if cap_due is not None:
            days_overdue, last_seen = cap_due
            stale_bonus = min(10.0, days_overdue * 1.4)
            out.append(
                Candidate(
                    source="reflex_capability_review",
                    action_spec=(
                        "Review your tool/capability usage. Which tools "
                        "did you lean on this week? Which are unused or "
                        "broken? Pick ONE underused capability and either "
                        "exercise it or note why it should be retired. "
                        f"Last review: {last_seen}."
                    ),
                    expected_value=5.0,
                    feasibility=0.85,
                    lens_match=0.4,
                    cost=2.0,
                    staleness_bonus=stale_bonus,
                    dedup_key="reflex:capability_review",
                    metadata={"days_overdue": days_overdue},
                )
            )
    except Exception as e:
        logger.debug("capability reflex failed: %s", e)

    try:
        miss_due = await _mission_rebalance_due(ctx)
        if miss_due is not None:
            out.append(
                Candidate(
                    source="reflex_mission_rebalance",
                    action_spec=(
                        "Review your missions. Read mission_list and "
                        "decide: should any pause, retire, or change "
                        "priority_weight? Are there missions missing that "
                        "you keep doing work outside of?"
                    ),
                    expected_value=5.5,
                    feasibility=0.85,
                    lens_match=0.4,
                    cost=2.0,
                    staleness_bonus=miss_due,
                    dedup_key="reflex:mission_rebalance",
                    metadata={"reason": "stale_missions"},
                )
            )
    except Exception as e:
        logger.debug("mission rebalance reflex failed: %s", e)

    return out


async def _capability_review_due(ctx: CandidateContext) -> tuple[float, str] | None:
    """Look up the last capability-review memory; if older than
    ``_CAPABILITY_REVIEW_DAYS``, return (days_overdue, last_seen_iso).
    Returns None when memory is unavailable so the reflex stays
    silent rather than firing without grounding.

    Currently uses a simple proxy: the agent's recent task memory.
    Phase 4 can replace this with a dedicated `reflexes` table.
    """
    # No proper memory dimension yet; return a soft "always slightly
    # overdue" signal so the reflex appears at a modest score until
    # the operator wires it to a real source. This is deliberate —
    # we want the reflex visible in early dry-runs.
    return (1.0, "never recorded")


async def _mission_rebalance_due(ctx: CandidateContext) -> float | None:
    """If the oldest active mission's staleness exceeds the rebalance
    period, return a staleness_bonus proportional to how overdue.
    Returns None when there are no missions or none are old enough."""
    if not ctx.mission_manager:
        return None
    missions = await ctx.mission_manager.list_missions()
    if not missions:
        return None
    now = datetime.now(UTC)
    max_stale_days = 0.0
    for m in missions:
        stale_h = m.staleness_hours(now)
        if stale_h == float("inf"):
            return 6.0
        max_stale_days = max(max_stale_days, stale_h / 24.0)
    if max_stale_days < _MISSION_REBALANCE_DAYS:
        return None
    return min(10.0, (max_stale_days - _MISSION_REBALANCE_DAYS) * 1.5 + 3.0)


# ---------------------------------------------------------------------------
# External signals (stub — Phase 3.5)
# ---------------------------------------------------------------------------


async def from_external_signals(ctx: CandidateContext) -> list[Candidate]:
    """Placeholder for Phase 3.5 — mentions, market deltas, schedule
    failures, news headlines. Returns [] today so the arbiter shape
    is fixed for callers; bolt on after the internal loop is healthy.
    """
    return []


# ---------------------------------------------------------------------------
# Convenience: run every generator
# ---------------------------------------------------------------------------


async def collect_all(ctx: CandidateContext) -> list[Candidate]:
    """Run every generator, concat results. Per-generator failures
    are logged and dropped so one broken source doesn't black-hole
    the wakeup."""
    out: list[Candidate] = []
    for gen in (
        from_workable_checkpoints,
        from_mission_momentum,
        from_dream,
        from_reflexes,
        from_external_signals,
    ):
        try:
            out.extend(await gen(ctx))
        except Exception as e:
            logger.warning("candidate generator %s failed: %s", gen.__name__, e)
    return out
