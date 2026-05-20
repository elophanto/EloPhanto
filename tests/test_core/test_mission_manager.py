"""Mission manager — durable drives, momentum, decay, neglect ranking.

Locks in the Phase 2 contract from docs/75-AUTONOMOUS-MIND-V2.md:
- Missions are NEVER auto-completed; only paused or retired.
- Momentum is persisted as a running sum; decay is read-side only.
- Neglect ranking biases the scorer toward high-weight stale missions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.database import Database
from core.mission_manager import (
    STATUS_ACTIVE,
    STATUS_PAUSED,
    STATUS_RETIRED,
    Mission,
    MissionManager,
)


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.initialize()
    return db


@pytest.fixture
async def mgr(db):
    return MissionManager(db)


class TestCreateAndGet:
    @pytest.mark.asyncio
    async def test_create_with_explicit_id(self, mgr: MissionManager) -> None:
        m = await mgr.create(
            "Promote alphascala", "GTM + launch", 2.5, mission_id="alphascala"
        )
        assert m.mission_id == "alphascala"
        assert m.priority_weight == 2.5
        assert m.status == STATUS_ACTIVE
        assert m.momentum_score == 0.0
        assert m.last_touched_at is None

        again = await mgr.get("alphascala")
        assert again is not None
        assert again.title == "Promote alphascala"

    @pytest.mark.asyncio
    async def test_create_generates_id_when_omitted(self, mgr: MissionManager) -> None:
        m = await mgr.create("Ad-hoc mission")
        assert m.mission_id.startswith("m_")
        assert len(m.mission_id) > 4

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, mgr: MissionManager) -> None:
        assert await mgr.get("nope") is None


class TestStatus:
    @pytest.mark.asyncio
    async def test_set_status_active_paused_retired(self, mgr: MissionManager) -> None:
        await mgr.create("M", mission_id="m1")
        assert await mgr.set_status("m1", STATUS_PAUSED) is True
        assert (await mgr.get("m1")).status == STATUS_PAUSED
        assert await mgr.set_status("m1", STATUS_RETIRED) is True
        assert (await mgr.get("m1")).status == STATUS_RETIRED
        assert await mgr.set_status("m1", STATUS_ACTIVE) is True
        assert (await mgr.get("m1")).status == STATUS_ACTIVE

    @pytest.mark.asyncio
    async def test_set_status_rejects_unknown(self, mgr: MissionManager) -> None:
        await mgr.create("M", mission_id="m1")
        with pytest.raises(ValueError):
            await mgr.set_status("m1", "completed")  # missions are never "completed"

    @pytest.mark.asyncio
    async def test_set_status_missing_returns_false(self, mgr: MissionManager) -> None:
        assert await mgr.set_status("nope", STATUS_PAUSED) is False

    @pytest.mark.asyncio
    async def test_list_defaults_to_active_only(self, mgr: MissionManager) -> None:
        await mgr.create("A", mission_id="a")
        await mgr.create("B", mission_id="b")
        await mgr.set_status("b", STATUS_PAUSED)
        active = await mgr.list_missions()
        assert {m.mission_id for m in active} == {"a"}
        everything = await mgr.list_missions(status=None)
        assert {m.mission_id for m in everything} == {"a", "b"}


class TestTouch:
    @pytest.mark.asyncio
    async def test_touch_bumps_momentum_and_timestamp(
        self, mgr: MissionManager
    ) -> None:
        await mgr.create("M", priority_weight=1.0, mission_id="m1")
        m = await mgr.touch("m1", bump=2.0)
        assert m is not None
        assert m.momentum_score == 2.0
        assert m.last_touched_at is not None

        m2 = await mgr.touch("m1", bump=0.5)
        # Persisted is a running sum — decay is read-side.
        assert m2.momentum_score == pytest.approx(2.5)

    @pytest.mark.asyncio
    async def test_touch_missing_returns_none(self, mgr: MissionManager) -> None:
        assert await mgr.touch("nope") is None


class TestDecayAndStaleness:
    """The persisted momentum is a raw sum so two missions touched on
    different days can be compared. Decay is applied only when the
    scorer reads, via ``Mission.decayed_momentum``. Direct construction
    of Mission lets us pin the math without time-travel."""

    def _make(self, *, momentum: float, touched: str | None) -> Mission:
        return Mission(
            mission_id="x",
            title="x",
            description="",
            status=STATUS_ACTIVE,
            priority_weight=1.0,
            momentum_score=momentum,
            last_touched_at=touched,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )

    def test_decay_half_life_seven_days(self) -> None:
        now = datetime(2026, 5, 20, tzinfo=UTC)
        seven_days_ago = (now - timedelta(days=7)).isoformat()
        m = self._make(momentum=4.0, touched=seven_days_ago)
        assert m.decayed_momentum(now) == pytest.approx(2.0, abs=0.01)

    def test_decay_fresh_returns_full(self) -> None:
        now = datetime(2026, 5, 20, tzinfo=UTC)
        m = self._make(momentum=4.0, touched=now.isoformat())
        assert m.decayed_momentum(now) == pytest.approx(4.0, abs=0.01)

    def test_decay_untouched_returns_raw(self) -> None:
        m = self._make(momentum=0.0, touched=None)
        assert m.decayed_momentum() == 0.0

    def test_staleness_inf_when_never_touched(self) -> None:
        m = self._make(momentum=0.0, touched=None)
        assert m.staleness_hours() == float("inf")


class TestListByNeglect:
    """High-weight stale missions outrank low-weight fresh ones — the
    whole reason the missions tier exists. Paused / retired missions
    must not appear (they aren't candidates for new work)."""

    @pytest.mark.asyncio
    async def test_high_weight_stale_outranks_low_weight_fresh(
        self, mgr: MissionManager, db: Database
    ) -> None:
        # Two active missions: A has high weight but is stale, B has
        # low weight but was touched recently. A should rank first.
        await mgr.create("A", priority_weight=3.0, mission_id="A")
        await mgr.create("B", priority_weight=0.5, mission_id="B")

        # Stamp A as stale by direct DB write (the manager has no
        # time-machine API — tests for staleness ranking are easier
        # this way than waiting hours).
        stale = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        fresh = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        await db.execute_insert(
            "UPDATE missions SET last_touched_at = ? WHERE mission_id = 'A'",
            (stale,),
        )
        await db.execute_insert(
            "UPDATE missions SET last_touched_at = ? WHERE mission_id = 'B'",
            (fresh,),
        )

        ranked = await mgr.list_by_neglect(limit=5)
        assert [m.mission_id for m in ranked][0] == "A"

    @pytest.mark.asyncio
    async def test_paused_excluded(self, mgr: MissionManager) -> None:
        await mgr.create("A", mission_id="A")
        await mgr.create("B", mission_id="B")
        await mgr.set_status("B", STATUS_PAUSED)
        ranked = await mgr.list_by_neglect()
        assert {m.mission_id for m in ranked} == {"A"}

    @pytest.mark.asyncio
    async def test_fresh_missions_saturate(self, mgr: MissionManager, db) -> None:
        """A mission touched within FRESH_HOURS contributes neglect=0 and
        falls behind any mission past the threshold. Confirms the
        ``max(0, stale_h - FRESH_HOURS)`` clip is doing its job."""
        await mgr.create("Fresh", priority_weight=5.0, mission_id="fresh")
        await mgr.create("Stale", priority_weight=1.0, mission_id="stale")
        now = datetime.now(UTC)
        await db.execute_insert(
            "UPDATE missions SET last_touched_at = ? WHERE mission_id = 'fresh'",
            ((now - timedelta(hours=1)).isoformat(),),
        )
        await db.execute_insert(
            "UPDATE missions SET last_touched_at = ? WHERE mission_id = 'stale'",
            ((now - timedelta(days=3)).isoformat(),),
        )
        ranked = await mgr.list_by_neglect()
        assert ranked[0].mission_id == "stale"


class TestUpdate:
    @pytest.mark.asyncio
    async def test_partial_update_only_touches_passed_fields(
        self, mgr: MissionManager
    ) -> None:
        await mgr.create("Old title", "Old desc", priority_weight=1.0, mission_id="m")
        ok = await mgr.update("m", title="New title")
        assert ok
        m = await mgr.get("m")
        assert m.title == "New title"
        assert m.description == "Old desc"
        assert m.priority_weight == 1.0

    @pytest.mark.asyncio
    async def test_update_missing_returns_false(self, mgr: MissionManager) -> None:
        assert await mgr.update("nope", title="x") is False

    @pytest.mark.asyncio
    async def test_update_with_no_fields_is_noop(self, mgr: MissionManager) -> None:
        await mgr.create("M", mission_id="m")
        assert await mgr.update("m") is False
