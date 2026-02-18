"""Database-backed approval queue for persistent tool execution approvals.

Allows approval requests to survive restarts and be resolved from
any interface (CLI, Telegram, Web UI).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from core.database import Database

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS approval_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    description TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    resolved_at TEXT
)"""


class ApprovalQueue:
    """Persistent queue for tool execution approvals."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def initialize(self) -> None:
        """Create the approval_queue table if it doesn't exist."""
        await self._db.execute_insert(_CREATE_TABLE, ())

    async def enqueue(
        self,
        tool_name: str,
        description: str,
        params: dict[str, Any],
    ) -> int:
        """Add a new pending approval request. Returns the row ID."""
        now = datetime.now(timezone.utc).isoformat()
        return await self._db.execute_insert(
            "INSERT INTO approval_queue (tool_name, description, params_json, "
            "status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (tool_name, description, json.dumps(params), now),
        )

    async def resolve(self, approval_id: int, approved: bool) -> bool:
        """Resolve a pending approval. Returns True if the item existed."""
        now = datetime.now(timezone.utc).isoformat()
        status = "approved" if approved else "denied"
        rows = await self._db.execute(
            "UPDATE approval_queue SET status = ?, resolved_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (status, now, approval_id),
        )
        return True

    async def pending(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get all pending approval requests."""
        rows = await self._db.execute(
            "SELECT id, tool_name, description, params_json, created_at "
            "FROM approval_queue WHERE status = 'pending' "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        results: list[dict[str, Any]] = []
        for row in rows:
            results.append(
                {
                    "id": row["id"],
                    "tool_name": row["tool_name"],
                    "description": row["description"],
                    "params": json.loads(row["params_json"]),
                    "created_at": row["created_at"],
                }
            )
        return results

    async def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent approval history (all statuses)."""
        rows = await self._db.execute(
            "SELECT id, tool_name, description, status, created_at, resolved_at "
            "FROM approval_queue ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        results: list[dict[str, Any]] = []
        for row in rows:
            results.append(
                {
                    "id": row["id"],
                    "tool_name": row["tool_name"],
                    "description": row["description"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "resolved_at": row["resolved_at"],
                }
            )
        return results
