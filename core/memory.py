"""Working memory and long-term memory management.

WorkingMemory holds in-session context (relevant knowledge chunks).
MemoryManager handles persistent task memory in the database.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.database import Database


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class WorkingMemory:
    """In-session context that accumulates relevant knowledge chunks."""

    relevant_chunks: list[dict[str, Any]] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def add_chunks(self, chunks: list[dict[str, Any]]) -> None:
        """Add knowledge chunks to working memory."""
        for chunk in chunks:
            # Avoid duplicates by source+heading
            key = (chunk.get("source", ""), chunk.get("heading", ""))
            existing_keys = {
                (c.get("source", ""), c.get("heading", ""))
                for c in self.relevant_chunks
            }
            if key not in existing_keys:
                self.relevant_chunks.append(chunk)

    def format_context(self, max_tokens: int = 2000) -> str:
        """Format relevant chunks as markdown context for the system prompt."""
        if not self.relevant_chunks:
            return ""

        lines: list[str] = ["## Relevant Knowledge\n"]
        total_tokens = 0

        for chunk in self.relevant_chunks:
            source = chunk.get("source", "unknown")
            heading = chunk.get("heading", "")
            content = chunk.get("content", "")

            chunk_tokens = _estimate_tokens(content)
            if total_tokens + chunk_tokens > max_tokens:
                break

            header = f"### From: {source}"
            if heading:
                header += f" > {heading}"
            lines.append(header)
            lines.append(content)
            lines.append("")
            total_tokens += chunk_tokens

        return "\n".join(lines).strip()

    def clear(self) -> None:
        """Reset working memory for a new task."""
        self.relevant_chunks.clear()


class MemoryManager:
    """Manages persistent task memory in the database."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def store_task_memory(
        self,
        session_id: str,
        goal: str,
        summary: str,
        outcome: str = "completed",
        tools_used: list[str] | None = None,
    ) -> int:
        """Store a completed task's summary for future recall."""
        now = datetime.now(UTC).isoformat()
        return await self._db.execute_insert(
            "INSERT INTO memory (session_id, task_goal, task_summary, outcome, "
            "tools_used, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                session_id,
                goal,
                summary,
                outcome,
                json.dumps(tools_used or []),
                now,
            ),
        )

    async def search_memory(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search task memory by keyword matching on goal and summary."""
        words = query.lower().split()
        if not words:
            return []

        conditions: list[str] = []
        params: list[str] = []
        for word in words[:5]:
            conditions.append("(LOWER(task_goal) LIKE ? OR LOWER(task_summary) LIKE ?)")
            params.extend([f"%{word}%", f"%{word}%"])

        where = " OR ".join(conditions)
        rows = await self._db.execute(
            f"SELECT * FROM memory WHERE {where} " f"ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        )

        results: list[dict[str, Any]] = []
        for row in rows:
            results.append(
                {
                    "goal": row["task_goal"],
                    "summary": row["task_summary"],
                    "outcome": row["outcome"],
                    "tools_used": json.loads(row["tools_used"]),
                    "created_at": row["created_at"],
                }
            )
        return results

    async def get_recent_tasks(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get the most recent task memories."""
        rows = await self._db.execute(
            "SELECT * FROM memory ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )

        results: list[dict[str, Any]] = []
        for row in rows:
            results.append(
                {
                    "goal": row["task_goal"],
                    "summary": row["task_summary"],
                    "outcome": row["outcome"],
                    "tools_used": json.loads(row["tools_used"]),
                    "created_at": row["created_at"],
                }
            )
        return results

    async def clear_all(self) -> int:
        """Delete all task memories. Returns count deleted."""
        rows = await self._db.execute("SELECT COUNT(*) as cnt FROM memory")
        count = rows[0]["cnt"] if rows else 0
        if count:
            await self._db.execute("DELETE FROM memory")
        return count
