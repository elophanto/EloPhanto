"""SQLite database manager with sqlite-vec vector search support.

Provides async-wrapped access to SQLite for knowledge chunks, memory,
task history, and LLM usage tracking. Uses asyncio.to_thread() around
stdlib sqlite3 calls.
"""

from __future__ import annotations

import asyncio
import json
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
    CREATE TABLE IF NOT EXISTS ego_state (
        id TEXT PRIMARY KEY DEFAULT 'self',
        self_image TEXT NOT NULL DEFAULT '',
        confidence_json TEXT NOT NULL DEFAULT '{}',
        coherence_score REAL NOT NULL DEFAULT 1.0,
        last_self_critique TEXT NOT NULL DEFAULT '',
        tasks_since_recompute INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        proud_of TEXT NOT NULL DEFAULT '',
        embarrassed_by TEXT NOT NULL DEFAULT '',
        aspiration TEXT NOT NULL DEFAULT '',
        prior_self_image TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ego_humbling_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        capability TEXT NOT NULL,
        claimed TEXT NOT NULL,
        actual TEXT NOT NULL,
        task_goal TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ego_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        capability TEXT NOT NULL,
        success INTEGER NOT NULL,
        task_goal TEXT,
        notes TEXT,
        created_at TEXT NOT NULL
    )
    """,
    # Affect (state-level emotion) — PAD substrate, OCC labels on top.
    # See docs/69-AFFECT.md for full design rationale. Distinct from ego:
    # ego is trait-level (rewritten every 25 outcomes); affect is state-
    # level (changes by the minute) and decays toward zero.
    """
    CREATE TABLE IF NOT EXISTS affect_state (
        id TEXT PRIMARY KEY DEFAULT 'self',
        pleasure REAL NOT NULL DEFAULT 0.0,
        arousal REAL NOT NULL DEFAULT 0.0,
        dominance REAL NOT NULL DEFAULT 0.0,
        last_decay_at TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS affect_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT NOT NULL,
        source TEXT NOT NULL,
        pleasure_delta REAL NOT NULL,
        arousal_delta REAL NOT NULL,
        dominance_delta REAL NOT NULL,
        halflife_seconds REAL NOT NULL DEFAULT 300.0,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_affect_events_created
        ON affect_events(created_at)
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
    CREATE TABLE IF NOT EXISTS kid_agents (
        kid_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        parent_agent_id TEXT NOT NULL DEFAULT 'self',
        container_id TEXT,
        runtime TEXT NOT NULL,                          -- 'docker' | 'podman' | 'colima'
        image TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'starting',        -- starting|running|paused|stopped|failed
        role TEXT,
        vault_scope_json TEXT NOT NULL DEFAULT '[]',
        volume_name TEXT NOT NULL,                      -- docker named volume
        parent_gateway_url TEXT NOT NULL,
        purpose TEXT,
        spawned_at TEXT NOT NULL,
        last_active TEXT,
        completed_at TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS swarm_projects (
        name TEXT PRIMARY KEY,
        repo_kind TEXT NOT NULL,         -- 'local' (never github), 'github', 'self-dev'
        repo TEXT,                       -- github URL or local path; NULL for 'new'/local-only
        worktree_path TEXT NOT NULL,
        main_branch TEXT NOT NULL DEFAULT 'main',
        last_branch TEXT,                -- most recent feature/update branch worked on
        last_pr_url TEXT,
        last_agent_id TEXT,
        agents_run INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'active',  -- active | archived
        created_at TEXT NOT NULL,
        last_spawn_at TEXT NOT NULL,
        description TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS known_agents (
        agent_id TEXT PRIMARY KEY,
        public_key TEXT NOT NULL,                  -- base64 Ed25519 public key (32 bytes raw)
        trust_level TEXT NOT NULL DEFAULT 'tofu',  -- blocked | tofu | verified
        first_seen TEXT NOT NULL,                  -- ISO timestamp of first IDENTIFY
        last_seen TEXT NOT NULL,                   -- ISO timestamp of most recent
        connection_count INTEGER NOT NULL DEFAULT 1,
        notes TEXT NOT NULL DEFAULT '',            -- free-form, owner-set
        metadata_json TEXT NOT NULL DEFAULT '{}'   -- discovered capabilities, last URL, etc.
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS organization_children (
        child_id TEXT PRIMARY KEY,
        role TEXT NOT NULL,
        purpose TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'stopped',
        port INTEGER NOT NULL,
        work_dir TEXT NOT NULL,
        config_path TEXT NOT NULL,
        pid INTEGER,
        approved_count INTEGER DEFAULT 0,
        rejected_count INTEGER DEFAULT 0,
        tasks_completed INTEGER DEFAULT 0,
        spawned_at TEXT NOT NULL,
        last_active TEXT,
        metadata_json TEXT DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS organization_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        child_id TEXT NOT NULL,
        task_ref TEXT,
        feedback_type TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (child_id) REFERENCES organization_children(child_id)
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
    """
    CREATE TABLE IF NOT EXISTS session_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        tool_name TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_session_messages_session
        ON session_messages(session_id, created_at)
    """,
    # ── Payment Requests ──────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS payment_requests (
        request_id TEXT PRIMARY KEY,
        wallet_address TEXT NOT NULL,
        chain TEXT NOT NULL,
        token TEXT NOT NULL,
        amount REAL NOT NULL,
        memo TEXT,
        reference TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        matching_tx_hash TEXT,
        matching_amount REAL,
        matching_sender TEXT,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        paid_at TEXT,
        session_id TEXT,
        channel TEXT,
        task_context TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_payment_requests_status
        ON payment_requests(status, expires_at)
    """,
    # ── Prospecting ───────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS prospects (
        prospect_id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        platform TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        url TEXT NOT NULL DEFAULT '',
        contact_email TEXT DEFAULT '',
        contact_name TEXT DEFAULT '',
        budget_min REAL DEFAULT 0,
        budget_max REAL DEFAULT 0,
        currency TEXT DEFAULT 'USD',
        required_skills TEXT NOT NULL DEFAULT '[]',
        match_score REAL DEFAULT 0,
        match_reasoning TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'new',
        priority TEXT NOT NULL DEFAULT 'medium',
        tags TEXT NOT NULL DEFAULT '[]',
        discovered_at TEXT NOT NULL,
        evaluated_at TEXT,
        outreach_sent_at TEXT,
        last_activity_at TEXT,
        metadata_json TEXT DEFAULT '{}'
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_prospects_status ON prospects(status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_prospects_source ON prospects(source, platform)
    """,
    """
    CREATE TABLE IF NOT EXISTS outreach_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prospect_id TEXT NOT NULL,
        action TEXT NOT NULL,
        channel TEXT NOT NULL,
        message_id TEXT DEFAULT '',
        thread_id TEXT DEFAULT '',
        content_preview TEXT DEFAULT '',
        direction TEXT NOT NULL DEFAULT 'outbound',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_outreach_log_prospect
        ON outreach_log(prospect_id, created_at)
    """,
    # ── User Profiles ─────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id TEXT NOT NULL,
        channel TEXT NOT NULL,
        display_name TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL DEFAULT '',
        expertise_json TEXT NOT NULL DEFAULT '[]',
        preferences_json TEXT NOT NULL DEFAULT '{}',
        observations_json TEXT NOT NULL DEFAULT '[]',
        interaction_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (user_id, channel)
    )
    """,
    # ── Metadata (key-value store for consolidation, etc.) ──────────
    """
    CREATE TABLE IF NOT EXISTS metadata (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """,
    # ── Content Monetization ─────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS publishing_log (
        publish_id TEXT PRIMARY KEY,
        platform TEXT NOT NULL,
        content_type TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        local_path TEXT,
        platform_url TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        metadata_json TEXT DEFAULT '{}',
        campaign_id TEXT,
        created_at TEXT NOT NULL,
        published_at TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_publishing_log_platform
        ON publishing_log(platform, status)
    """,
    """
    CREATE TABLE IF NOT EXISTS affiliate_campaigns (
        campaign_id TEXT PRIMARY KEY,
        product_url TEXT NOT NULL,
        product_title TEXT NOT NULL DEFAULT '',
        product_data_json TEXT DEFAULT '{}',
        affiliate_link TEXT NOT NULL,
        platforms_json TEXT DEFAULT '[]',
        pitches_json TEXT DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'active',
        posts_count INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_affiliate_campaigns_status
        ON affiliate_campaigns(status)
    """,
    # Paid jobs from elophanto.com — local view of work the agent has
    # accepted. Dedup primary key on job_id (the website's ULID), so
    # the same envelope arriving via both email + pull transport
    # collapses to one row. status moves
    # seen → accepted → completed/failed; never deletes — audit trail
    # for "did we run this paid job and what did we say back."
    """
    CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY,
        task TEXT NOT NULL,
        requester_email TEXT NOT NULL DEFAULT '',
        requester_wallet TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'seen'
            CHECK (status IN ('seen','accepted','completed','failed')),
        result TEXT NOT NULL DEFAULT '',
        issued_at TEXT NOT NULL DEFAULT '',
        expires_at TEXT NOT NULL DEFAULT '',
        seen_at TEXT NOT NULL,
        completed_at TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_jobs_status_seen_at
        ON jobs(status, seen_at)
    """,
    # Polymarket calibration audit — links the bot's stated probability
    # at order time to the eventual market resolution, so we can answer
    # "when the LLM says 70%, does it actually win 70%?" and "do markets
    # we entered at $0.40 actually pay 40% of the time?". Independent of
    # polynode-trading.db (which is the polynode binary's own DB and we
    # don't co-modify); join by (token_id, created_at) when correlating
    # with on-chain order_history rows.
    """
    CREATE TABLE IF NOT EXISTS polymarket_predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        market_slug TEXT NOT NULL DEFAULT '',
        token_id TEXT NOT NULL,
        side TEXT NOT NULL
            CHECK (side IN ('YES','NO')),
        entry_price REAL NOT NULL,
        size REAL NOT NULL DEFAULT 0.0,
        llm_prob REAL NOT NULL,
        confidence_band TEXT NOT NULL DEFAULT 'medium'
            CHECK (confidence_band IN ('high','medium','low')),
        kelly_fraction REAL DEFAULT NULL,
        order_type TEXT NOT NULL DEFAULT 'GTC',
        rationale TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        resolved_at TEXT DEFAULT NULL,
        settle_price REAL DEFAULT NULL,
        outcome TEXT DEFAULT NULL
            CHECK (outcome IS NULL OR outcome IN ('WIN','LOSS','PUSH')),
        realized_pnl REAL DEFAULT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_polymarket_predictions_resolved
        ON polymarket_predictions(resolved_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_polymarket_predictions_token
        ON polymarket_predictions(token_id)
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
    # Knowledge drift detection — tracks which source files a knowledge doc covers
    "ALTER TABLE knowledge_chunks ADD COLUMN covers TEXT DEFAULT '[]'",
    # Knowledge consolidation — track when a chunk was last accessed
    "ALTER TABLE knowledge_chunks ADD COLUMN last_accessed_at TEXT DEFAULT NULL",
    # Session search FTS5 index (requires FTS5 extension — bundled in Python 3.12+)
    # NOTE: FTS5 virtual table creation handled separately in _init_fts5()
    # Ego v2 — first-person voice fields (pride/shame/aspiration + prior-self continuity)
    "ALTER TABLE ego_state ADD COLUMN proud_of TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE ego_state ADD COLUMN embarrassed_by TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE ego_state ADD COLUMN aspiration TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE ego_state ADD COLUMN prior_self_image TEXT NOT NULL DEFAULT ''",
    # Ego v3 — Higgins three-self model (actual/ideal/ought) + last-capability
    # tracking so user corrections can attribute humbling to a specific tool.
    # ought_self / ideal_self are derived from declared identity each recompute;
    # storing them on ego_state lets the markdown render the gap explicitly.
    "ALTER TABLE ego_state ADD COLUMN ought_self TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE ego_state ADD COLUMN ideal_self TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE ego_state ADD COLUMN last_capability TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE ego_state ADD COLUMN last_decay_at TEXT NOT NULL DEFAULT ''",
    # Ego v3 — outcomes get a "source" column so we can distinguish
    # tool-completion vs verification-fail vs user-correction. Old rows
    # are 'tool' by default.
    "ALTER TABLE ego_outcomes ADD COLUMN source TEXT NOT NULL DEFAULT 'tool'",
    "ALTER TABLE ego_humbling_events ADD COLUMN source TEXT NOT NULL DEFAULT 'system'",
    # Direct-tool scheduled tasks — fast path that bypasses the agent
    # loop entirely. When `direct_tool` is set, the scheduler invokes
    # that registry tool directly (no LLM planning, no agent.run loop)
    # with `direct_params` as the input dict. Lets mechanical cron jobs
    # (polymarket_resolve_pending, solana_balance, etc.) run at
    # sub-minute cadence for ~$0 instead of $5+/day in LLM tokens. See
    # docs/70-SCHEDULER-CONCURRENCY.md (Phase 2 section).
    "ALTER TABLE scheduled_tasks ADD COLUMN direct_tool TEXT",
    "ALTER TABLE scheduled_tasks ADD COLUMN direct_params TEXT",
]


class Database:
    """SQLite database with optional sqlite-vec vector search."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._vec_available: bool = False
        # Connection-level lock. The Python sqlite3 Connection is opened
        # with check_same_thread=False (see _init_sync) so it can be
        # used from the asyncio.to_thread pool, but SQLite's Python
        # wrapper does NOT serialize concurrent calls — that's our job.
        # Pre-2026-05-08 this lock only wrapped writes; reads were
        # serialized incidentally by the scheduler running everything
        # one-task-at-a-time. The 2026-05-07 resource-typed concurrency
        # rewrite enabled parallel _run_one tasks, all of which call
        # self._db.execute() from different to_thread workers — race
        # condition surfaced as `sqlite3.InterfaceError: bad parameter
        # or other API misuse`. Lock now wraps every connection touch.
        self._conn_lock = threading.Lock()

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

        # Initialize FTS5 for session search
        self._init_fts5()

        # Try loading sqlite-vec
        self._load_vec_extension()

    def _init_fts5(self) -> None:
        """Create the FTS5 virtual table for session message search."""
        assert self._conn is not None
        try:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS session_messages_fts USING fts5(
                    content,
                    tool_name,
                    content='session_messages',
                    content_rowid='id',
                    tokenize='porter unicode61'
                )
                """
            )
            # Triggers to keep FTS index in sync
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS session_messages_ai AFTER INSERT ON session_messages BEGIN
                    INSERT INTO session_messages_fts(rowid, content, tool_name)
                    VALUES (new.id, new.content, new.tool_name);
                END
                """
            )
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS session_messages_ad AFTER DELETE ON session_messages BEGIN
                    INSERT INTO session_messages_fts(session_messages_fts, rowid, content, tool_name)
                    VALUES ('delete', old.id, old.content, old.tool_name);
                END
                """
            )
            self._conn.commit()
            logger.info("FTS5 session search index initialized")
        except Exception as e:
            logger.warning("FTS5 not available for session search: %s", e)

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
            with self._conn_lock:
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
            with self._conn_lock:
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

    async def create_memory_vec_table(self, dimensions: int) -> None:
        """Create memory_vec virtual table for semantic memory search.

        Mirrors create_vec_table() but for the memory table. Uses rowid matching
        so memory_vec.rowid == memory.id for O(1) joins.
        """
        if not self._vec_available:
            return

        def _create() -> None:
            assert self._conn is not None
            with self._conn_lock:
                try:
                    row = self._conn.execute(
                        "SELECT COUNT(*) as cnt FROM memory_vec_rowids"
                    ).fetchone()
                    if row and row[0] > 0:
                        sample = self._conn.execute(
                            "SELECT length(embedding) / 4 as dims FROM memory_vec LIMIT 1"
                        ).fetchone()
                        if sample and sample[0] == dimensions:
                            return  # Exists with correct dimensions
                    elif row and row[0] == 0:
                        return  # Exists but empty — fine
                except Exception:
                    pass  # Table doesn't exist yet

                self._conn.execute("DROP TABLE IF EXISTS memory_vec")
                self._conn.execute(
                    f"CREATE VIRTUAL TABLE memory_vec USING vec0("
                    f"memory_id INTEGER PRIMARY KEY, "
                    f"embedding float[{dimensions}])"
                )
                self._conn.commit()

        await asyncio.to_thread(_create)

    async def insert_memory_vec(self, memory_id: int, vector: list[float]) -> None:
        """Insert or replace a memory embedding into memory_vec."""
        if not self._vec_available:
            return

        import struct

        def _insert() -> None:
            assert self._conn is not None
            with self._conn_lock:
                blob = struct.pack(f"{len(vector)}f", *vector)
                self._conn.execute(
                    "INSERT OR REPLACE INTO memory_vec(memory_id, embedding) VALUES (?, ?)",
                    (memory_id, blob),
                )
                self._conn.commit()

        try:
            await asyncio.to_thread(_insert)
        except Exception as e:
            logger.debug("insert_memory_vec failed: %s", e)

    async def search_memory_vec(
        self, vector: list[float], limit: int = 5
    ) -> list[dict[str, Any]]:
        """Semantic similarity search over task memory. Returns memory rows."""
        if not self._vec_available:
            return []

        import struct

        def _search() -> list[dict[str, Any]]:
            assert self._conn is not None
            blob = struct.pack(f"{len(vector)}f", *vector)
            rows = self._conn.execute(
                "SELECT m.task_goal, m.task_summary, m.outcome, m.tools_used, "
                "m.created_at, v.distance "
                "FROM memory_vec v "
                "JOIN memory m ON m.id = v.memory_id "
                "WHERE v.embedding MATCH ? AND k = ? "
                "ORDER BY v.distance",
                (blob, limit),
            ).fetchall()
            return [
                {
                    "goal": r["task_goal"],
                    "summary": r["task_summary"],
                    "outcome": r["outcome"],
                    "tools_used": json.loads(r["tools_used"]),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

        try:
            return await asyncio.to_thread(_search)
        except Exception as e:
            logger.debug("search_memory_vec failed: %s", e)
            return []

    async def execute(
        self, sql: str, params: tuple[Any, ...] | list[Any] = ()
    ) -> list[sqlite3.Row]:
        """Execute a query and return all rows.

        Lock-wrapped — see ``_conn_lock`` docstring. Reads from a
        sqlite3 Connection opened with ``check_same_thread=False``
        require explicit serialization or SQLite returns
        ``InterfaceError: bad parameter or other API misuse``.
        """

        def _exec() -> list[sqlite3.Row]:
            assert self._conn is not None
            with self._conn_lock:
                cursor = self._conn.execute(sql, params)
                return cursor.fetchall()

        return await asyncio.to_thread(_exec)

    async def execute_insert(
        self, sql: str, params: tuple[Any, ...] | list[Any] = ()
    ) -> int:
        """Execute an INSERT and return the last row id."""

        def _exec() -> int:
            assert self._conn is not None
            with self._conn_lock:
                cursor = self._conn.execute(sql, params)
                self._conn.commit()
                return cursor.lastrowid or 0

        return await asyncio.to_thread(_exec)

    async def execute_many(self, sql: str, params_list: list[tuple[Any, ...]]) -> None:
        """Execute a statement with multiple parameter sets."""

        def _exec() -> None:
            assert self._conn is not None
            with self._conn_lock:
                self._conn.executemany(sql, params_list)
                self._conn.commit()

        await asyncio.to_thread(_exec)

    async def execute_script(self, sql: str) -> None:
        """Execute multiple SQL statements."""

        def _exec() -> None:
            assert self._conn is not None
            with self._conn_lock:
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
