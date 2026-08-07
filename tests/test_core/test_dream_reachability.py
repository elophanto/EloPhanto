"""Dreaming must stay reachable when goals are wedged, and rate-limited always.

Two production failures, opposite in direction, same root cause — the score
was the only brake:

  * May 2026: 47 dreams in a single day (no rate limit at all).
  * June-August 2026: zero dreams for two months, because ANY active goal row
    demoted dream below every other source, and a stalled goal pool looks
    exactly like a busy one to a plain count.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from core.mind_candidates import (
    MIN_DREAM_INTERVAL_H,
    STALE_GOAL_HOURS,
    CandidateContext,
    from_dream,
)


def _goal(hours_since_update: float) -> SimpleNamespace:
    ts = datetime.now(UTC) - timedelta(hours=hours_since_update)
    return SimpleNamespace(goal_id="g1", updated_at=ts.isoformat())


class _GoalMgr:
    def __init__(self, active=(), planning=()) -> None:
        self._active, self._planning = list(active), list(planning)

    async def list_goals(self, status: str = "", limit: int = 20):
        return {"active": self._active, "planning": self._planning}.get(status, [])


class _Journal:
    def __init__(self, hours_ago: float | None) -> None:
        self._hours = hours_ago

    async def recent(self, limit: int = 1):
        if self._hours is None:
            return []
        ts = datetime.now(UTC) - timedelta(hours=self._hours)
        return [SimpleNamespace(created_at=ts.isoformat())]


class TestCooldown:
    @pytest.mark.asyncio
    async def test_recent_dream_suppresses_the_candidate_entirely(self) -> None:
        ctx = CandidateContext(dream_journal=_Journal(hours_ago=1.0))
        assert await from_dream(ctx) == []

    @pytest.mark.asyncio
    async def test_old_dream_allows_a_new_one(self) -> None:
        ctx = CandidateContext(
            dream_journal=_Journal(hours_ago=MIN_DREAM_INTERVAL_H + 1)
        )
        assert len(await from_dream(ctx)) == 1

    @pytest.mark.asyncio
    async def test_no_history_is_not_a_cooldown(self) -> None:
        ctx = CandidateContext(dream_journal=_Journal(hours_ago=None))
        assert len(await from_dream(ctx)) == 1

    @pytest.mark.asyncio
    async def test_absent_journal_disables_the_limit(self) -> None:
        # None-safe contract: a caller that hasn't wired the journal still works.
        assert len(await from_dream(CandidateContext())) == 1

    @pytest.mark.asyncio
    async def test_cooldown_outranks_an_empty_goal_pool(self) -> None:
        """Rate limit applies even in the state that most wants a dream."""
        ctx = CandidateContext(
            goal_manager=_GoalMgr(), dream_journal=_Journal(hours_ago=0.5)
        )
        assert await from_dream(ctx) == []


class TestWedgedGoalsDoNotSuppress:
    @pytest.mark.asyncio
    async def test_fresh_goal_demotes_dream(self) -> None:
        # Unchanged behaviour: finish what's started before starting new things.
        ctx = CandidateContext(goal_manager=_GoalMgr(active=[_goal(1.0)]))
        assert (await from_dream(ctx))[0].expected_value == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_wedged_goal_does_not_demote_dream(self) -> None:
        """The two-month drought: a stalled goal must not look like a busy one."""
        ctx = CandidateContext(
            goal_manager=_GoalMgr(active=[_goal(STALE_GOAL_HOURS + 10)])
        )
        cands = await from_dream(ctx)
        assert cands[0].expected_value == pytest.approx(7.0)
        assert cands[0].metadata["workable_goals"] == 0

    @pytest.mark.asyncio
    async def test_one_fresh_goal_among_wedged_ones_still_demotes(self) -> None:
        ctx = CandidateContext(
            goal_manager=_GoalMgr(
                active=[_goal(99.0), _goal(0.5)], planning=[_goal(99.0)]
            )
        )
        assert (await from_dream(ctx))[0].expected_value == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_unparseable_timestamp_counts_as_in_flight(self) -> None:
        """Fail safe: on an unknown timestamp keep dreaming suppressed rather
        than spawning new work on a guess."""
        ctx = CandidateContext(
            goal_manager=_GoalMgr(active=[SimpleNamespace(updated_at="not-a-date")])
        )
        assert (await from_dream(ctx))[0].expected_value == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_empty_pool_still_scores_high(self) -> None:
        ctx = CandidateContext(goal_manager=_GoalMgr())
        assert (await from_dream(ctx))[0].expected_value == pytest.approx(7.0)
