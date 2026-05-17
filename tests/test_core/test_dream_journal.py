"""Dream journal — persistence + recall tests.

The journal exists to kill amnesia in the dream phase: every dream
must be visible to the next one. These tests pin the contract the
dream tool depends on (recall order, count, link-back to chosen
goal). The dream tool's prompt-construction tests live alongside it
in test_dream_tool.py.
"""

from __future__ import annotations

import pytest

from core.database import Database
from core.dream_journal import DreamEntry, DreamJournal


@pytest.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
async def journal(db):
    return DreamJournal(db)


class TestRecord:
    @pytest.mark.asyncio
    async def test_record_returns_row_id(self, journal: DreamJournal) -> None:
        rid = await journal.record(
            focus="research",
            candidates=[{"title": "A", "feasibility": 8}],
            recommendation={"index": 0, "reasoning": "best of 1"},
        )
        assert isinstance(rid, int) and rid > 0

    @pytest.mark.asyncio
    async def test_record_persists_full_candidate_list(
        self, journal: DreamJournal
    ) -> None:
        await journal.record(
            focus="creation",
            candidates=[
                {"title": "Make an essay", "lenses": ["creation"]},
                {"title": "Build a tool", "lenses": ["infrastructure"]},
            ],
            recommendation={"index": 1},
        )
        recent = await journal.recent(limit=10)
        assert len(recent) == 1
        assert len(recent[0].candidates) == 2
        assert recent[0].candidates[0]["title"] == "Make an essay"


class TestRecall:
    @pytest.mark.asyncio
    async def test_recent_newest_first(self, journal: DreamJournal) -> None:
        for i in range(3):
            await journal.record(
                focus=f"f{i}", candidates=[{"title": f"t{i}"}], recommendation={}
            )
        recent = await journal.recent(limit=10)
        assert [r.focus for r in recent] == ["f2", "f1", "f0"]

    @pytest.mark.asyncio
    async def test_recent_respects_limit(self, journal: DreamJournal) -> None:
        for i in range(5):
            await journal.record(
                focus="balanced", candidates=[{"title": f"t{i}"}], recommendation={}
            )
        recent = await journal.recent(limit=2)
        assert len(recent) == 2

    @pytest.mark.asyncio
    async def test_recent_returns_dream_entry_type(self, journal: DreamJournal) -> None:
        await journal.record(
            focus="capability",
            candidates=[{"title": "x"}],
            recommendation={"index": 0},
        )
        recent = await journal.recent()
        assert all(isinstance(r, DreamEntry) for r in recent)
        assert recent[0].focus == "capability"

    @pytest.mark.asyncio
    async def test_count(self, journal: DreamJournal) -> None:
        assert await journal.count() == 0
        await journal.record(focus="a", candidates=[], recommendation={})
        await journal.record(focus="b", candidates=[], recommendation={})
        assert await journal.count() == 2


class TestChosenGoalLink:
    """The journal stores ``chosen_goal_id`` so post-hoc analysis can
    answer which dreams led to actual goals. Pin the link-back path."""

    @pytest.mark.asyncio
    async def test_set_chosen_goal_persists(self, journal: DreamJournal) -> None:
        rid = await journal.record(
            focus="research", candidates=[{"title": "X"}], recommendation={"index": 0}
        )
        await journal.set_chosen_goal(rid, "goal-uuid-123")
        recent = await journal.recent()
        assert recent[0].chosen_goal_id == "goal-uuid-123"

    @pytest.mark.asyncio
    async def test_unset_chosen_goal_is_none(self, journal: DreamJournal) -> None:
        await journal.record(
            focus="research", candidates=[{"title": "X"}], recommendation={}
        )
        recent = await journal.recent()
        assert recent[0].chosen_goal_id is None


class TestMalformedRows:
    """Robustness — the JSON columns could in principle contain bad
    data if the schema is ever rewritten or restored from backup.
    The recall path must not crash on a malformed row."""

    @pytest.mark.asyncio
    async def test_bad_candidates_json_yields_empty_list(
        self, db, journal: DreamJournal
    ) -> None:
        # Insert a row with invalid JSON in candidates_json.
        await db.execute(
            "INSERT INTO dream_journal "
            "(focus, candidates_json, recommendation_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("balanced", "not json", "{}", "2026-05-17T00:00:00Z"),
        )
        recent = await journal.recent()
        assert recent[0].candidates == []
