"""Session management for multi-channel gateway.

Each channel+user pair gets an isolated session with its own
conversation history, persisted to SQLite for restart survival.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.database import Database

logger = logging.getLogger(__name__)

_MAX_CONVERSATION_HISTORY = 20


@dataclass
class Session:
    """An isolated agent session for one user on one channel."""

    session_id: str
    channel: str
    user_id: str
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_active: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def append_conversation_turn(self, user_msg: str, assistant_msg: str) -> None:
        """Store a user/assistant pair, trimming to max length."""
        self.conversation_history.append({"role": "user", "content": user_msg})
        self.conversation_history.append({"role": "assistant", "content": assistant_msg})
        if len(self.conversation_history) > _MAX_CONVERSATION_HISTORY:
            self.conversation_history = self.conversation_history[
                -_MAX_CONVERSATION_HISTORY:
            ]

    def touch(self) -> None:
        """Update last_active timestamp."""
        self.last_active = datetime.now(UTC)


class SessionManager:
    """Manages sessions with SQLite persistence."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._cache: dict[str, Session] = {}

    async def create(self, channel: str, user_id: str) -> Session:
        """Create a new session for a channel+user pair."""
        session = Session(
            session_id=str(uuid.uuid4()),
            channel=channel,
            user_id=user_id,
        )
        await self._persist(session)
        self._cache[session.session_id] = session
        logger.info(
            "Created session %s for %s/%s",
            session.session_id[:8],
            channel,
            user_id,
        )
        return session

    async def get(self, session_id: str) -> Session | None:
        """Get a session by ID (cache first, then DB)."""
        if session_id in self._cache:
            return self._cache[session_id]

        rows = await self._db.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        if not rows:
            return None

        session = self._row_to_session(rows[0])
        self._cache[session_id] = session
        return session

    async def get_or_create(self, channel: str, user_id: str) -> Session:
        """Get existing session for channel+user, or create one."""
        # Check cache first
        for s in self._cache.values():
            if s.channel == channel and s.user_id == user_id:
                s.touch()
                return s

        # Check DB
        rows = await self._db.execute(
            "SELECT * FROM sessions WHERE channel = ? AND user_id = ?",
            (channel, user_id),
        )
        if rows:
            session = self._row_to_session(rows[0])
            session.touch()
            self._cache[session.session_id] = session
            return session

        return await self.create(channel, user_id)

    async def save(self, session: Session) -> None:
        """Persist session state to database."""
        await self._persist(session)

    async def list_active(self, limit: int = 20) -> list[Session]:
        """List most recently active sessions."""
        rows = await self._db.execute(
            "SELECT * FROM sessions ORDER BY last_active DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_session(r) for r in rows]

    async def cleanup_stale(self, max_age_hours: int = 24) -> int:
        """Remove sessions older than max_age_hours. Returns count removed."""
        from datetime import timedelta

        cutoff = (datetime.now(UTC) - timedelta(hours=max_age_hours)).isoformat()
        rows = await self._db.execute(
            "SELECT session_id FROM sessions WHERE last_active < ?",
            (cutoff,),
        )
        count = len(rows)
        if count:
            await self._db.execute(
                "DELETE FROM sessions WHERE last_active < ?",
                (cutoff,),
            )
            for row in rows:
                self._cache.pop(row["session_id"], None)
            logger.info("Cleaned up %d stale sessions", count)
        return count

    async def _persist(self, session: Session) -> None:
        """Upsert session to database."""
        await self._db.execute_insert(
            """
            INSERT INTO sessions (session_id, channel, user_id, conversation_json,
                                  created_at, last_active, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                conversation_json = excluded.conversation_json,
                last_active = excluded.last_active,
                metadata_json = excluded.metadata_json
            """,
            (
                session.session_id,
                session.channel,
                session.user_id,
                json.dumps(session.conversation_history),
                session.created_at.isoformat(),
                session.last_active.isoformat(),
                json.dumps(session.metadata),
            ),
        )

    @staticmethod
    def _row_to_session(row: Any) -> Session:
        """Convert a database row to a Session object."""
        return Session(
            session_id=row["session_id"],
            channel=row["channel"],
            user_id=row["user_id"],
            conversation_history=json.loads(row["conversation_json"] or "[]"),
            created_at=datetime.fromisoformat(row["created_at"]),
            last_active=datetime.fromisoformat(row["last_active"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
