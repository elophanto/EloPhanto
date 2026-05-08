"""Database layer tests."""

from __future__ import annotations

import asyncio
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


class TestThreadSafety:
    """Pin the connection-level lock fix from 2026-05-08.

    Before the fix, ``execute`` (read path) was unprotected. Pre-2026-05-07
    nothing exercised concurrent reads because the scheduler ran one task
    at a time. The resource-typed concurrency rewrite enabled parallel
    ``_run_one`` tasks → multiple to_thread workers calling
    ``self._conn.execute(...)`` simultaneously → SQLite error
    ``bad parameter or other API misuse``. The whole scheduler stopped.

    These tests pin the fix: N parallel reads/writes against one
    Database instance must complete cleanly with no InterfaceError.
    """

    @pytest.mark.asyncio
    async def test_parallel_reads_do_not_race(self, db: Database) -> None:
        """Fire 50 concurrent execute() calls against the same connection.
        Pre-fix this raised ``sqlite3.InterfaceError: bad parameter or
        other API misuse`` after the first few collisions."""
        # Seed a row to read.
        await db.execute_insert(
            "INSERT INTO tasks (id, goal, status, started_at) "
            "VALUES (?, ?, 'completed', '2026-05-08T00:00:00Z')",
            ("t1", "test"),
        )

        async def reader() -> int:
            rows = await db.execute("SELECT goal FROM tasks WHERE id = ?", ("t1",))
            return len(rows)

        # 50 parallel reads — way more than the threadpool default.
        results = await asyncio.gather(*[reader() for _ in range(50)])
        assert all(r == 1 for r in results)

    @pytest.mark.asyncio
    async def test_parallel_mixed_reads_and_writes(self, db: Database) -> None:
        """Realistic scheduler scenario: many parallel _run_one tasks,
        some reading scheduled_tasks, some writing schedule_runs.
        Must complete without any task crashing."""

        async def writer(i: int) -> None:
            await db.execute_insert(
                "INSERT INTO tasks (id, goal, status, started_at) "
                "VALUES (?, ?, 'running', '2026-05-08T00:00:00Z')",
                (f"task-{i}", f"goal-{i}"),
            )

        async def reader() -> int:
            rows = await db.execute("SELECT id FROM tasks WHERE status = 'running'")
            return len(rows)

        # 20 writers + 20 readers, all kicked off concurrently.
        write_tasks = [writer(i) for i in range(20)]
        read_tasks = [reader() for _ in range(20)]
        results = await asyncio.gather(
            *write_tasks, *read_tasks, return_exceptions=True
        )
        # No exceptions — pre-fix at least one would be
        # sqlite3.InterfaceError.
        for r in results:
            assert not isinstance(
                r, Exception
            ), f"Concurrent DB access produced an exception: {r!r}"

    @pytest.mark.asyncio
    async def test_replicates_scheduler_get_schedule_pattern(
        self, db: Database
    ) -> None:
        """Mirrors the exact failure path the scheduler hit on
        2026-05-07 18:00:00 — six crons fire at the same minute, each
        spawning a _run_one that immediately runs
        `SELECT * FROM scheduled_tasks WHERE id = ?`. Six parallel
        cursors against one connection without serialization →
        InterfaceError. With the fix, all six complete cleanly."""
        # Seed several rows.
        for i in range(6):
            await db.execute_insert(
                """INSERT INTO scheduled_tasks
                     (id, name, cron_expression, task_goal, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    f"sched-{i}",
                    f"Schedule {i}",
                    "0 * * * *",
                    f"goal {i}",
                    "2026-05-08T00:00:00Z",
                    "2026-05-08T00:00:00Z",
                ),
            )

        async def get_schedule_like(sid: str) -> int:
            rows = await db.execute(
                "SELECT * FROM scheduled_tasks WHERE id = ?", (sid,)
            )
            return len(rows)

        results = await asyncio.gather(
            *[get_schedule_like(f"sched-{i}") for i in range(6)]
        )
        assert all(r == 1 for r in results)
