"""Memory system tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.database import Database
from core.memory import MemoryManager, WorkingMemory


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def memory_mgr(db: Database) -> MemoryManager:
    return MemoryManager(db)


class TestWorkingMemory:
    def test_add_chunks(self) -> None:
        """Chunks are added to working memory."""
        wm = WorkingMemory()
        wm.add_chunks(
            [
                {"source": "a.md", "heading": "H1", "content": "Hello"},
                {"source": "b.md", "heading": "H2", "content": "World"},
            ]
        )
        assert len(wm.relevant_chunks) == 2

    def test_no_duplicate_chunks(self) -> None:
        """Duplicate chunks (same source+heading) are not added."""
        wm = WorkingMemory()
        wm.add_chunks([{"source": "a.md", "heading": "H1", "content": "Hello"}])
        wm.add_chunks([{"source": "a.md", "heading": "H1", "content": "Hello again"}])
        assert len(wm.relevant_chunks) == 1

    def test_format_context_empty(self) -> None:
        """Empty working memory produces empty string."""
        wm = WorkingMemory()
        assert wm.format_context() == ""

    def test_format_context_with_chunks(self) -> None:
        """format_context produces markdown with source headers."""
        wm = WorkingMemory()
        wm.add_chunks(
            [
                {"source": "test.md", "heading": "Section", "content": "Test content"},
            ]
        )
        ctx = wm.format_context()
        assert "Relevant Knowledge" in ctx
        assert "test.md" in ctx
        assert "Test content" in ctx

    def test_format_context_truncates(self) -> None:
        """format_context respects max_tokens limit."""
        wm = WorkingMemory()
        wm.add_chunks(
            [
                {"source": "a.md", "heading": "H1", "content": "x" * 5000},
                {"source": "b.md", "heading": "H2", "content": "should not appear"},
            ]
        )
        ctx = wm.format_context(max_tokens=500)
        # Second chunk shouldn't fit
        assert "should not appear" not in ctx

    def test_clear(self) -> None:
        """clear() removes all chunks."""
        wm = WorkingMemory()
        wm.add_chunks([{"source": "a.md", "heading": "H", "content": "C"}])
        wm.clear()
        assert len(wm.relevant_chunks) == 0


class TestMemoryManager:
    @pytest.mark.asyncio
    async def test_store_task_memory(self, memory_mgr: MemoryManager) -> None:
        """Task memory is stored in database."""
        row_id = await memory_mgr.store_task_memory(
            session_id="s1",
            goal="list files",
            summary="Listed 10 files in /tmp",
            outcome="completed",
            tools_used=["file_list"],
        )
        assert row_id > 0

    @pytest.mark.asyncio
    async def test_search_memory_finds_match(self, memory_mgr: MemoryManager) -> None:
        """search_memory finds relevant entries by keyword."""
        await memory_mgr.store_task_memory(
            session_id="s1",
            goal="list Python files in home",
            summary="Found 47 .py files",
            outcome="completed",
            tools_used=["file_list"],
        )
        await memory_mgr.store_task_memory(
            session_id="s1",
            goal="check disk space",
            summary="80GB free on main drive",
            outcome="completed",
            tools_used=["shell_execute"],
        )

        results = await memory_mgr.search_memory("python files")
        assert len(results) >= 1
        assert any("Python" in r["goal"] for r in results)

    @pytest.mark.asyncio
    async def test_search_memory_no_match(self, memory_mgr: MemoryManager) -> None:
        """search_memory returns empty for unmatched queries."""
        await memory_mgr.store_task_memory(
            session_id="s1",
            goal="check weather",
            summary="Sunny today",
        )
        results = await memory_mgr.search_memory("database migration")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_get_recent_tasks(self, memory_mgr: MemoryManager) -> None:
        """get_recent_tasks returns entries in reverse chronological order."""
        for i in range(3):
            await memory_mgr.store_task_memory(
                session_id="s1",
                goal=f"task {i}",
                summary=f"summary {i}",
            )

        results = await memory_mgr.get_recent_tasks(limit=2)
        assert len(results) == 2
        assert results[0]["goal"] == "task 2"  # Most recent first

    @pytest.mark.asyncio
    async def test_search_empty_query(self, memory_mgr: MemoryManager) -> None:
        """Empty query returns empty results."""
        results = await memory_mgr.search_memory("")
        assert results == []
