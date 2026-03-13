"""Working memory and long-term memory management.

WorkingMemory holds in-session context (relevant knowledge chunks).
MemoryManager handles persistent task memory in the database.

Semantic memory search: when an EmbeddingClient is injected via set_embedder(),
store_task_memory() embeds goal+summary into memory_vec for cosine-similarity
retrieval. search_memory() tries semantic first, falls back to LIKE keyword
matching when embeddings are unavailable.
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

    def format_context(self, max_tokens: int = 4000) -> str:
        """Format relevant chunks as markdown context for the system prompt."""
        if not self.relevant_chunks:
            return ""

        lines: list[str] = ["## Relevant Knowledge\n"]
        total_tokens = 0

        for chunk in self.relevant_chunks:
            source = chunk.get("source", "unknown")
            heading = chunk.get("heading", "")
            content = chunk.get("content", "")
            stale_warning = chunk.get("stale_warning", "")

            chunk_tokens = _estimate_tokens(content)
            if total_tokens + chunk_tokens > max_tokens:
                break

            if stale_warning:
                lines.append(f"**WARNING: {stale_warning}**")
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
        self._embedder: Any = None
        self._embedding_model: str = "nomic-embed-text"
        self._embedding_dimensions: int = 768

    def set_embedder(self, embedder: Any, model: str, dimensions: int) -> None:
        """Inject embedding client for semantic memory search."""
        self._embedder = embedder
        self._embedding_model = model
        self._embedding_dimensions = dimensions

    async def store_task_memory(
        self,
        session_id: str,
        goal: str,
        summary: str,
        outcome: str = "completed",
        tools_used: list[str] | None = None,
    ) -> int:
        """Store a completed task's summary for future recall."""
        from core.pii_guard import redact_pii

        now = datetime.now(UTC).isoformat()
        row_id = await self._db.execute_insert(
            "INSERT INTO memory (session_id, task_goal, task_summary, outcome, "
            "tools_used, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                session_id,
                redact_pii(goal),
                redact_pii(summary),
                outcome,
                json.dumps(tools_used or []),
                now,
            ),
        )

        # Embed goal+summary for semantic retrieval (fire-and-forget safe)
        if self._embedder and row_id:
            try:
                text = f"{goal} {summary}"[:1000]
                result = await self._embedder.embed(text, self._embedding_model)
                await self._db.insert_memory_vec(row_id, result.vector)
            except Exception as e:
                logger.debug("Memory embedding failed (non-fatal): %s", e)

        return row_id

    async def search_memory(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search task memory — semantic when embedder available, keyword fallback."""
        if self._embedder:
            try:
                return await self._search_memory_semantic(query, limit)
            except Exception as e:
                logger.debug(
                    "Semantic memory search failed, falling back to keyword: %s", e
                )
        return await self._search_memory_keyword(query, limit)

    async def _search_memory_semantic(
        self, query: str, limit: int
    ) -> list[dict[str, Any]]:
        """Vector similarity search over memory embeddings."""
        result = await self._embedder.embed(query, self._embedding_model)
        rows = await self._db.search_memory_vec(result.vector, limit)
        return rows

    async def _search_memory_keyword(
        self, query: str, limit: int
    ) -> list[dict[str, Any]]:
        """Keyword LIKE search — fallback when embeddings unavailable."""
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
            f"SELECT * FROM memory WHERE {where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        )

        return [
            {
                "goal": row["task_goal"],
                "summary": row["task_summary"],
                "outcome": row["outcome"],
                "tools_used": json.loads(row["tools_used"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

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
