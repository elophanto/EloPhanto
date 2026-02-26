"""SQLite database manager with sqlite-vec vector search support.

Provides async-wrapped access to SQLite for knowledge chunks, memory,
task history, and LLM usage tracking. Uses asyncio.to_thread() around
stdlib sqlite3 calls.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Schema DDL
_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS knowledge_chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT NOT NULL,
        heading_path TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL,
        tags TEXT NOT NULL DEFAULT '[]',
        scope TEXT NOT NULL DEFAULT 'system',
        token_count INTEGER NOT NULL DEFAULT 0,
        file_updated_at TEXT NOT NULL,
        indexed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        task_goal TEXT NOT NULL,
        task_summary TEXT NOT NULL,
        outcome TEXT NOT NULL DEFAULT 'completed',
        tools_used TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        goal TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'running',
        result TEXT,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        tokens_used INTEGER DEFAULT 0,
        cost_usd REAL DEFAULT 0.0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS llm_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT,
        model TEXT NOT NULL,
        provider TEXT NOT NULL,
        input_tokens INTEGER NOT NULL,
        output_tokens INTEGER NOT NULL,
        cost_usd REAL NOT NULL,
        task_type TEXT NOT NULL DEFAULT 'unknown',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS plugins (
        name TEXT PRIMARY KEY,
        description TEXT NOT NULL DEFAULT '',
        plugin_dir TEXT NOT NULL,
        permission_level TEXT NOT NULL DEFAULT 'safe',
        status TEXT NOT NULL DEFAULT 'active',
        version TEXT NOT NULL DEFAULT '0.1.0',
        created_at TEXT NOT NULL,
        last_used_at TEXT,
        use_count INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scheduled_tasks (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        cron_expression TEXT NOT NULL,
        task_goal TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        last_run_at TEXT,
        next_run_at TEXT,
        last_result TEXT,
        last_status TEXT DEFAULT 'never_run',
        retry_count INTEGER DEFAULT 0,
        max_retries INTEGER DEFAULT 3,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS schedule_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        schedule_id TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        status TEXT NOT NULL DEFAULT 'running',
        result TEXT,
        error TEXT,
        steps_taken INTEGER DEFAULT 0,
        FOREIGN KEY (schedule_id) REFERENCES scheduled_tasks(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        channel TEXT NOT NULL,
        user_id TEXT NOT NULL,
        conversation_json TEXT DEFAULT '[]',
        created_at TEXT NOT NULL,
        last_active TEXT NOT NULL,
        metadata_json TEXT DEFAULT '{}',
        UNIQUE(channel, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_collections (
        collection_id   TEXT PRIMARY KEY,
        name            TEXT NOT NULL,
        session_id      TEXT,
        created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
        file_count      INTEGER DEFAULT 0,
        chunk_count     INTEGER DEFAULT 0,
        total_tokens    INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_files (
        file_id         TEXT PRIMARY KEY,
        collection_id   TEXT REFERENCES document_collections(collection_id),
        filename        TEXT NOT NULL,
        mime_type       TEXT,
        size_bytes      INTEGER,
        page_count      INTEGER,
        local_path      TEXT,
        content_hash    TEXT,
        processed_at    DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_chunks (
        chunk_id        TEXT PRIMARY KEY,
        collection_id   TEXT REFERENCES document_collections(collection_id),
        file_id         TEXT REFERENCES document_files(file_id),
        chunk_index     INTEGER,
        content         TEXT NOT NULL,
        token_count     INTEGER,
        page_number     INTEGER,
        section_title   TEXT,
        metadata        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS goals (
        goal_id TEXT PRIMARY KEY,
        session_id TEXT,
        goal TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'planning',
        plan_json TEXT NOT NULL DEFAULT '[]',
        context_summary TEXT NOT NULL DEFAULT '',
        current_checkpoint INTEGER NOT NULL DEFAULT 0,
        total_checkpoints INTEGER NOT NULL DEFAULT 0,
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        llm_calls_used INTEGER NOT NULL DEFAULT 0,
        cost_usd REAL NOT NULL DEFAULT 0.0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS goal_checkpoints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        goal_id TEXT NOT NULL REFERENCES goals(goal_id),
        checkpoint_order INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        success_criteria TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        result_summary TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        started_at TEXT,
        completed_at TEXT,
        UNIQUE(goal_id, checkpoint_order)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS identity (
        id TEXT PRIMARY KEY DEFAULT 'self',
        creator TEXT NOT NULL DEFAULT 'EloPhanto',
        display_name TEXT NOT NULL DEFAULT 'EloPhanto',
        purpose TEXT,
        values_json TEXT NOT NULL DEFAULT '[]',
        beliefs_json TEXT NOT NULL DEFAULT '{}',
        curiosities_json TEXT NOT NULL DEFAULT '[]',
        boundaries_json TEXT NOT NULL DEFAULT '[]',
        capabilities_json TEXT NOT NULL DEFAULT '[]',
        personality_json TEXT NOT NULL DEFAULT '{}',
        communication_style TEXT NOT NULL DEFAULT '',
        initial_thoughts TEXT,
        version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS identity_evolution (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trigger TEXT NOT NULL,
        field_changed TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT,
        reason TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0.5,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS payment_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        tool_name TEXT NOT NULL,
        amount REAL NOT NULL,
        currency TEXT NOT NULL,
        recipient TEXT NOT NULL,
        payment_type TEXT NOT NULL,
        provider TEXT,
        chain TEXT,
        status TEXT NOT NULL,
        session_id TEXT,
        channel TEXT,
        task_context TEXT,
        transaction_ref TEXT,
        fee_amount REAL,
        fee_currency TEXT,
        error TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS email_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        tool_name TEXT NOT NULL,
        inbox_id TEXT NOT NULL,
        direction TEXT NOT NULL,
        recipient TEXT,
        sender TEXT,
        subject TEXT,
        message_id TEXT,
        thread_id TEXT,
        status TEXT NOT NULL,
        session_id TEXT,
        channel TEXT,
        task_context TEXT,
        error TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS collect_examples (
        id TEXT PRIMARY KEY,
        conversations_json TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        uploaded_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS swarm_agents (
        agent_id TEXT PRIMARY KEY,
        profile TEXT NOT NULL,
        task TEXT NOT NULL,
        branch TEXT NOT NULL,
        worktree_path TEXT NOT NULL,
        tmux_session TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'running',
        done_criteria TEXT NOT NULL DEFAULT 'pr_created',
        pr_url TEXT,
        pr_number INTEGER,
        ci_status TEXT,
        enriched_prompt TEXT,
        spawned_at TEXT NOT NULL,
        completed_at TEXT,
        stopped_reason TEXT,
        metadata_json TEXT DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS swarm_activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT NOT NULL,
        event TEXT NOT NULL,
        detail TEXT,
        timestamp TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        msg_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chat_messages_session
        ON chat_messages(session_id, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS conversations (
        conversation_id TEXT PRIMARY KEY,
        title TEXT NOT NULL DEFAULT 'New conversation',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
]

# Idempotent ALTER TABLE migrations — SQLite raises OperationalError
# ("duplicate column name") if the column already exists, which we catch.
_MIGRATIONS = [
    # Gap 5: Provider transparency columns on llm_usage
    "ALTER TABLE llm_usage ADD COLUMN finish_reason TEXT DEFAULT 'unknown'",
    "ALTER TABLE llm_usage ADD COLUMN latency_ms INTEGER DEFAULT 0",
    "ALTER TABLE llm_usage ADD COLUMN fallback_from TEXT DEFAULT ''",
    "ALTER TABLE llm_usage ADD COLUMN suspected_truncated INTEGER DEFAULT 0",
    # Chat conversations
    "ALTER TABLE chat_messages ADD COLUMN conversation_id TEXT DEFAULT ''",
]


class Database:
    """SQLite database with optional sqlite-vec vector search."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._vec_available: bool = False
        self._write_lock = threading.Lock()

    @property
    def vec_available(self) -> bool:
        return self._vec_available

    async def initialize(self) -> None:
        """Create database, tables, and load sqlite-vec extension."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._init_sync)

    def _init_sync(self) -> None:
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        # Create standard tables
        for ddl in _SCHEMA:
            self._conn.execute(ddl)
        self._conn.commit()

        # Schema migrations — ALTER TABLE additions (safe to re-run; SQLite
        # raises "duplicate column name" which we silently ignore)
        for migration in _MIGRATIONS:
            try:
                self._conn.execute(migration)
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists

        # Try loading sqlite-vec
        self._load_vec_extension()

    def _load_vec_extension(self) -> None:
        if not self._conn:
            return
        try:
            import sqlite_vec

            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
            self._vec_available = True
            logger.info("sqlite-vec extension loaded")
        except Exception as e:
            self._vec_available = False
            logger.warning(
                f"sqlite-vec not available, falling back to keyword search: {e}"
            )

    async def create_vec_table(self, dimensions: int) -> None:
        """Create the vec_chunks virtual table with the detected embedding dimensions.

        Only recreates if the table doesn't exist or dimensions changed.
        """
        if not self._vec_available:
            return

        def _create() -> None:
            assert self._conn is not None
            with self._write_lock:
                # Check if table already exists with correct dimensions
                try:
                    row = self._conn.execute(
                        "SELECT COUNT(*) as cnt FROM vec_chunks_rowids"
                    ).fetchone()
                    # Table exists — check dimensions by inspecting a row
                    if row and row[0] > 0:
                        sample = self._conn.execute(
                            "SELECT length(embedding) / 4 as dims FROM vec_chunks LIMIT 1"
                        ).fetchone()
                        if sample and sample[0] == dimensions:
                            return  # Table exists with correct dimensions
                    elif row and row[0] == 0:
                        # Table exists but empty — no need to recreate
                        return
                except Exception:
                    pass  # Table doesn't exist yet

                self._conn.execute("DROP TABLE IF EXISTS vec_chunks")
                self._conn.execute(
                    f"CREATE VIRTUAL TABLE vec_chunks USING vec0("
                    f"chunk_id INTEGER PRIMARY KEY, "
                    f"embedding float[{dimensions}])"
                )
                self._conn.commit()

        await asyncio.to_thread(_create)

    async def create_document_vec_table(self, dimensions: int) -> None:
        """Create the document_chunks_vec virtual table for document embeddings.

        Only recreates if the table doesn't exist or dimensions changed.
        """
        if not self._vec_available:
            return

        def _create() -> None:
            assert self._conn is not None
            with self._write_lock:
                try:
                    row = self._conn.execute(
                        "SELECT COUNT(*) as cnt FROM document_chunks_vec"
                    ).fetchone()
                    if row and row[0] > 0:
                        sample = self._conn.execute(
                            "SELECT length(embedding) / 4 as dims "
                            "FROM document_chunks_vec LIMIT 1"
                        ).fetchone()
                        if sample and sample[0] == dimensions:
                            return
                    elif row and row[0] == 0:
                        return
                except Exception:
                    pass

                self._conn.execute("DROP TABLE IF EXISTS document_chunks_vec")
                self._conn.execute(
                    f"CREATE VIRTUAL TABLE document_chunks_vec USING vec0("
                    f"chunk_id TEXT PRIMARY KEY, "
                    f"embedding float[{dimensions}])"
                )
                self._conn.commit()

        await asyncio.to_thread(_create)

    async def execute(
        self, sql: str, params: tuple[Any, ...] | list[Any] = ()
    ) -> list[sqlite3.Row]:
        """Execute a query and return all rows."""

        def _exec() -> list[sqlite3.Row]:
            assert self._conn is not None
            cursor = self._conn.execute(sql, params)
            return cursor.fetchall()

        return await asyncio.to_thread(_exec)

    async def execute_insert(
        self, sql: str, params: tuple[Any, ...] | list[Any] = ()
    ) -> int:
        """Execute an INSERT and return the last row id."""

        def _exec() -> int:
            assert self._conn is not None
            with self._write_lock:
                cursor = self._conn.execute(sql, params)
                self._conn.commit()
                return cursor.lastrowid or 0

        return await asyncio.to_thread(_exec)

    async def execute_many(self, sql: str, params_list: list[tuple[Any, ...]]) -> None:
        """Execute a statement with multiple parameter sets."""

        def _exec() -> None:
            assert self._conn is not None
            with self._write_lock:
                self._conn.executemany(sql, params_list)
                self._conn.commit()

        await asyncio.to_thread(_exec)

    async def execute_script(self, sql: str) -> None:
        """Execute multiple SQL statements."""

        def _exec() -> None:
            assert self._conn is not None
            with self._write_lock:
                self._conn.executescript(sql)

        await asyncio.to_thread(_exec)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:

            def _close() -> None:
                assert self._conn is not None
                self._conn.close()

            await asyncio.to_thread(_close)
            self._conn = None
