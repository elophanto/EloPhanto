"""Database layer tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.database import Database


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


class TestDatabase:
    @pytest.mark.asyncio
    async def test_creates_tables(self, db: Database) -> None:
        """All required tables exist after initialization."""
        rows = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        table_names = {row["name"] for row in rows}
        assert "knowledge_chunks" in table_names
        assert "memory" in table_names
        assert "tasks" in table_names
        assert "llm_usage" in table_names

    @pytest.mark.asyncio
    async def test_insert_and_query(self, db: Database) -> None:
        """Basic insert and query works."""
        row_id = await db.execute_insert(
            "INSERT INTO memory (session_id, task_goal, task_summary, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("s1", "test goal", "test summary", "2026-01-01T00:00:00"),
        )
        assert row_id > 0

        rows = await db.execute("SELECT * FROM memory WHERE id = ?", (row_id,))
        assert len(rows) == 1
        assert rows[0]["task_goal"] == "test goal"

    @pytest.mark.asyncio
    async def test_execute_many(self, db: Database) -> None:
        """Batch insert works."""
        await db.execute_many(
            "INSERT INTO memory (session_id, task_goal, task_summary, created_at) "
            "VALUES (?, ?, ?, ?)",
            [
                ("s1", "goal 1", "summary 1", "2026-01-01T00:00:00"),
                ("s1", "goal 2", "summary 2", "2026-01-02T00:00:00"),
            ],
        )
        rows = await db.execute("SELECT COUNT(*) as cnt FROM memory")
        assert rows[0]["cnt"] == 2

    @pytest.mark.asyncio
    async def test_knowledge_chunks_crud(self, db: Database) -> None:
        """CRUD on knowledge_chunks table."""
        row_id = await db.execute_insert(
            "INSERT INTO knowledge_chunks "
            "(file_path, heading_path, content, tags, scope, "
            "token_count, file_updated_at, indexed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "test.md",
                "Title",
                "Hello world",
                '["test"]',
                "system",
                5,
                "2026-01-01",
                "2026-01-01",
            ),
        )
        assert row_id > 0

        rows = await db.execute(
            "SELECT * FROM knowledge_chunks WHERE id = ?", (row_id,)
        )
        assert rows[0]["content"] == "Hello world"
        assert rows[0]["scope"] == "system"

    @pytest.mark.asyncio
    async def test_sqlite_vec_flag_set(self, db: Database) -> None:
        """vec_available flag is a boolean (True or False depending on platform)."""
        assert isinstance(db.vec_available, bool)

    @pytest.mark.asyncio
    async def test_vec_table_creation(self, db: Database) -> None:
        """Vector table can be created when sqlite-vec is available."""
        if not db.vec_available:
            pytest.skip("sqlite-vec not available on this platform")
        await db.create_vec_table(768)
        rows = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='vec_chunks'"
        )
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_close_and_reopen(self, tmp_path: Path) -> None:
        """Database persists across close/reopen."""
        db = Database(tmp_path / "persist.db")
        await db.initialize()
        await db.execute_insert(
            "INSERT INTO memory (session_id, task_goal, task_summary, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("s1", "persist test", "summary", "2026-01-01"),
        )
        await db.close()

        db2 = Database(tmp_path / "persist.db")
        await db2.initialize()
        rows = await db2.execute("SELECT * FROM memory")
        assert len(rows) == 1
        assert rows[0]["task_goal"] == "persist test"
        await db2.close()

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Database creates parent directories if they don't exist."""
        db = Database(tmp_path / "nested" / "deep" / "test.db")
        await db.initialize()
        assert (tmp_path / "nested" / "deep" / "test.db").exists()
        await db.close()
