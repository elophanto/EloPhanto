"""Dreams must be attributable to the goals they produced.

``dream_journal.chosen_goal_id`` exists to answer "which dreams became real
work?" — but nothing ever wrote it, so every row was NULL and the question was
unanswerable. That made a dreaming problem indistinguishable from a bookkeeping
gap: 118 dreams with no measurable outcome could mean the ideas were bad, or
just that nobody wrote the link down.

goal_create now accepts dream_id and closes the loop.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.database import Database
from core.dream_journal import DreamJournal
from tools.goals.create_tool import GoalCreateTool


class _FakeGoal:
    def __init__(self, goal_id: str) -> None:
        self.goal_id = goal_id
        self.goal = "ship the thing"
        self.status = "active"
        self.total_checkpoints = 1


class _FakeCheckpoint:
    order = 1
    title = "do it"
    success_criteria = "done"


class _FakeGoalManager:
    def __init__(self) -> None:
        self.created: list[str] = []

    async def create_goal(self, goal: str, **kwargs: Any) -> _FakeGoal:
        self.created.append(goal)
        return _FakeGoal("goal_abc")

    async def decompose(self, goal: Any) -> list[_FakeCheckpoint]:
        return [_FakeCheckpoint()]


@pytest.fixture
async def wired(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.initialize()
    journal = DreamJournal(db)
    tool = GoalCreateTool()
    tool._goal_manager = _FakeGoalManager()
    tool._dream_journal = journal
    yield tool, journal, db
    await db.close()


async def _record_dream(journal: DreamJournal) -> int:
    return await journal.record(
        focus="creation",
        candidates=[{"title": "A thing someone pays for"}],
        recommendation={"index": 0, "reasoning": "best of the batch"},
    )


class TestDreamAttribution:
    @pytest.mark.asyncio
    async def test_goal_create_links_back_to_its_dream(self, wired) -> None:
        tool, journal, _ = wired
        dream_id = await _record_dream(journal)

        res = await tool.execute({"goal": "ship the thing", "dream_id": dream_id})
        assert res.success

        entries = await journal.recent(limit=1)
        assert entries[0].chosen_goal_id == "goal_abc"

    @pytest.mark.asyncio
    async def test_goal_without_dream_id_still_works(self, wired) -> None:
        # Most goals are operator-created and have no dream behind them.
        tool, journal, _ = wired
        await _record_dream(journal)

        res = await tool.execute({"goal": "ship the thing"})
        assert res.success
        entries = await journal.recent(limit=1)
        assert entries[0].chosen_goal_id is None

    @pytest.mark.asyncio
    async def test_attribution_failure_never_fails_the_goal(self, wired) -> None:
        """Bookkeeping is not load-bearing — a bad dream_id must not lose the
        goal the agent just decided to pursue."""
        tool, journal, _ = wired
        res = await tool.execute({"goal": "ship the thing", "dream_id": 999999})
        assert res.success
        assert res.data["goal_id"] == "goal_abc"

    @pytest.mark.asyncio
    async def test_non_numeric_dream_id_is_survivable(self, wired) -> None:
        tool, _, _ = wired
        res = await tool.execute({"goal": "ship the thing", "dream_id": "not-an-int"})
        assert res.success

    @pytest.mark.asyncio
    async def test_works_without_a_journal_injected(self, tmp_path) -> None:
        tool = GoalCreateTool()
        tool._goal_manager = _FakeGoalManager()
        # _dream_journal stays None (e.g. db unavailable at boot)
        res = await tool.execute({"goal": "ship the thing", "dream_id": 1})
        assert res.success

    def test_dream_id_is_exposed_in_the_schema(self) -> None:
        props = GoalCreateTool().input_schema["properties"]
        assert "dream_id" in props
        # The LLM has to be told where the value comes from, or it never passes it.
        assert "goal_dream" in props["dream_id"]["description"]
