"""The run ledger (docs/94 §9): what a goal's later runs start from."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.database import Database
from core.execution_context import execution_context
from core.run_ledger import RunLedger, extract_artifacts
from tools.goals.note_tool import GoalNoteTool


@pytest.fixture
async def db(tmp_path: Path):
    d = Database(tmp_path / "ledger.db")
    await d.initialize()
    yield d
    await d.close()


class TestArtifactsComeFromTheTrail:
    def test_producers_params_and_returned_paths_count_reads_do_not(self) -> None:
        trail: list[dict[str, Any]] = [
            {"tool": "file_write", "status": "ok", "data": {"path": "/w/report.md"}},
            {"tool": "file_read", "status": "ok", "data": {"path": "/w/input.md"}},
            {
                "tool": "deploy_website",
                "status": "ok",
                "data": {},
                "result_data": {"url": "https://site.example", "id": "dep_1"},
            },
            {
                "tool": "file_write",
                "status": "error",
                "error": "x",
                "data": {"path": "/w/bad.md"},
            },
            {"tool": "file_write", "status": "ok", "data": {"path": "/w/report.md"}},
        ]
        refs = [ref for ref, _ in extract_artifacts(trail)]
        assert refs == ["/w/report.md", "https://site.example", "dep_1"]


class TestRender:
    async def test_the_current_checkpoint_sees_its_handoff_and_failures_first(
        self, db: Database
    ) -> None:
        led = RunLedger(db)
        await led.add(
            "g1",
            "artifact",
            "file_write path",
            ref="/w/a.md",
            checkpoint_order=1,
            source="code",
        )
        await led.add(
            "g1",
            "failure",
            "receipt gate refused: no count",
            checkpoint_order=2,
            attempt=1,
        )
        await led.add(
            "g1", "failure", "other checkpoint's failure", checkpoint_order=3, attempt=1
        )
        await led.add(
            "g1",
            "handoff",
            "[time_limit] DONE: a. NEXT: b.",
            checkpoint_order=2,
            attempt=1,
        )
        await led.add("g1", "fact", "price is $19", ref="https://x", checkpoint_order=1)
        qid = await led.add("g1", "question", "which region?", checkpoint_order=1)
        text = await led.render("g1", checkpoint_order=2)
        assert (
            text.index("WHERE THE LAST RUN")
            < text.index("FAILED ATTEMPTS")
            < text.index("ARTIFACTS")
        )
        assert "receipt gate refused" in text and "other checkpoint" not in text
        assert "/w/a.md" in text and "price is $19" in text and "which region?" in text
        await led.close_question(qid)
        assert "which region?" not in await led.render("g1", checkpoint_order=2)

    async def test_it_is_bounded(self, db: Database) -> None:
        led = RunLedger(db)
        for i in range(200):
            await led.add(
                "g2", "fact", f"fact number {i} " + "x" * 200, checkpoint_order=1
            )
        text = await led.render("g2", max_chars=2000)
        assert len(text) <= 2000 and "[ledger truncated]" in text

    async def test_unknown_kinds_are_refused(self, db: Database) -> None:
        with pytest.raises(ValueError):
            await RunLedger(db).add("g", "opinion", "x")

    async def test_the_markdown_mirror(self, db: Database, tmp_path: Path) -> None:
        led = RunLedger(db)
        await led.add(
            "g3",
            "decision",
            "use CSV, not XLSX: the buyer imports CSV",
            checkpoint_order=1,
        )
        out = tmp_path / "ws" / "goals" / "g3" / "LEDGER.md"
        await led.write_markdown("g3", out, title="Export")
        assert (
            "## decisions" in out.read_text() and "buyer imports CSV" in out.read_text()
        )


class TestNoteTool:
    async def test_it_writes_to_the_goal_in_scope_and_its_active_checkpoint(
        self, db: Database
    ) -> None:
        tool = GoalNoteTool()
        tool._ledger = RunLedger(db)
        gm = MagicMock()
        gm._db = MagicMock()
        gm._db.execute = AsyncMock(
            return_value=[{"checkpoint_order": 4, "attempts": 2}]
        )
        tool._goal_manager = gm
        with execution_context(goal_id="goal-9"):
            res = await tool.execute(
                {
                    "kind": "decision",
                    "content": "Skip region B: no payment rails there.",
                }
            )
        assert res.success and res.data["checkpoint"] == 4
        rows = await RunLedger(db).entries("goal-9")
        assert rows[0].kind == "decision" and rows[0].attempt == 2

    async def test_outside_goal_work_it_needs_a_goal_id(self, db: Database) -> None:
        tool = GoalNoteTool()
        tool._ledger = RunLedger(db)
        res = await tool.execute({"kind": "fact", "content": "x"})
        assert not res.success and "goal_id" in (res.error or "")


class TestHandoff:
    async def test_code_only_when_something_is_waiting(self) -> None:
        from core.agent import Agent

        agent = Agent.__new__(Agent)
        agent._router = MagicMock()
        agent._router.complete = AsyncMock()
        text = await Agent._write_handoff(
            agent, "t", "preempted by higher-priority task", "preempted", 5, ["a"], []
        )
        agent._router.complete.assert_not_awaited()
        assert "preempted" in text

    async def test_an_llm_handoff_keeps_the_factual_fallback(self) -> None:
        from core.agent import Agent

        agent = Agent.__new__(Agent)
        agent._router = MagicMock()
        agent._router.complete = AsyncMock(
            return_value=MagicMock(content="DONE: x. IN PROGRESS: y. NEXT: z.")
        )
        text = await Agent._write_handoff(
            agent,
            "t",
            "time limit reached (600s)",
            "time_limit",
            9,
            ["file_write"],
            [{"role": "assistant", "content": "wrote part 1"}],
        )
        assert text.startswith("DONE: x.") and "time limit" in text
