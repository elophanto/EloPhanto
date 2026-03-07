"""Knowledge search tool: hybrid semantic + keyword search.

Searches the indexed knowledge base using vector similarity (sqlite-vec)
combined with keyword boosting, recency boosting, and scope filtering.
Falls back to keyword-only search if embeddings are unavailable.
"""

from __future__ import annotations

import json
import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class KnowledgeSearchTool(BaseTool):
    """Search the knowledge base for relevant information."""

    @property
    def group(self) -> str:
        return "knowledge"

    def __init__(self) -> None:
        self._db: Any = None  # Injected by agent
        self._embedder: Any = None  # Injected by agent
        self._embedding_model: str = "nomic-embed-text"
        self._project_root: Path | None = None  # Injected by agent

    @property
    def name(self) -> str:
        return "knowledge_search"

    @property
    def description(self) -> str:
        return (
            "Search the knowledge base for relevant information. "
            "Use this to look up facts about your capabilities, architecture, "
            "past tasks, conventions, and learned patterns."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query in natural language",
                },
                "scope": {
                    "type": "string",
                    "description": "Filter by scope (system, user, learned, plugin, all)",
                    "enum": ["system", "user", "learned", "plugin", "all"],
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 5)",
                },
            },
            "required": ["query"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        query = params["query"]
        scope = params.get("scope", "all")
        limit = params.get("limit", 5)

        if not self._db:
            return ToolResult(success=False, error="Knowledge database not initialized")

        try:
            # Try semantic search first
            if self._embedder and self._db.vec_available:
                results = await self._semantic_search(query, scope, limit)
            else:
                results = await self._keyword_search(query, scope, limit)

            # Annotate stale results whose covered source files changed
            if self._project_root and results:
                results = await self._annotate_staleness(results)

            return ToolResult(
                success=True,
                data={
                    "results": results,
                    "count": len(results),
                    "search_type": (
                        "semantic"
                        if self._embedder and self._db.vec_available
                        else "keyword"
                    ),
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Search failed: {e}")

    async def _semantic_search(
        self, query: str, scope: str, limit: int
    ) -> list[dict[str, Any]]:
        """Hybrid semantic + keyword search."""
        # Embed the query
        embedding = await self._embedder.embed(query, self._embedding_model)
        query_vec = struct.pack(f"{len(embedding.vector)}f", *embedding.vector)

        # KNN search in vec_chunks
        vec_rows = await self._db.execute(
            "SELECT chunk_id, distance FROM vec_chunks "
            "WHERE embedding MATCH ? ORDER BY distance LIMIT 20",
            (query_vec,),
        )

        if not vec_rows:
            return await self._keyword_search(query, scope, limit)

        # Load full chunk data
        chunk_ids = [row["chunk_id"] for row in vec_rows]
        distances = {row["chunk_id"]: row["distance"] for row in vec_rows}

        placeholders = ",".join("?" for _ in chunk_ids)
        chunks = await self._db.execute(
            f"SELECT * FROM knowledge_chunks WHERE id IN ({placeholders})",
            tuple(chunk_ids),
        )

        # Score and rank
        scored: list[tuple[float, dict[str, Any]]] = []
        query_words = set(query.lower().split())

        for chunk in chunks:
            chunk_id = chunk["id"]
            # Base score from vector similarity (lower distance = better)
            semantic_score = max(0, 1.0 - distances.get(chunk_id, 1.0))

            # Keyword boost
            content_lower = chunk["content"].lower()
            keyword_score = sum(0.1 for word in query_words if word in content_lower)
            try:
                tags = json.loads(chunk["tags"])
                tag_str = " ".join(tags).lower()
                keyword_score += sum(0.2 for word in query_words if word in tag_str)
            except (json.JSONDecodeError, TypeError):
                pass

            # Recency boost
            recency_score = self._recency_boost(chunk["indexed_at"])

            # Scope filter
            if scope != "all" and chunk["scope"] != scope:
                continue

            total_score = semantic_score + keyword_score + recency_score
            scored.append(
                (
                    total_score,
                    {
                        "content": chunk["content"],
                        "source": chunk["file_path"],
                        "heading": chunk["heading_path"],
                        "score": round(total_score, 3),
                        "scope": chunk["scope"],
                        "tags": json.loads(chunk["tags"]) if chunk["tags"] else [],
                    },
                )
            )

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    async def _keyword_search(
        self, query: str, scope: str, limit: int
    ) -> list[dict[str, Any]]:
        """Fallback keyword-only search using LIKE."""
        words = query.lower().split()
        if not words:
            return []

        # Build WHERE clause
        conditions = []
        params: list[str] = []
        for word in words[:5]:  # Limit to 5 search terms
            conditions.append("LOWER(content) LIKE ?")
            params.append(f"%{word}%")

        where = " OR ".join(conditions)
        if scope != "all":
            where = f"({where}) AND scope = ?"
            params.append(scope)

        rows = await self._db.execute(
            f"SELECT * FROM knowledge_chunks WHERE {where} LIMIT ?",
            (*params, limit * 2),
        )

        results: list[dict[str, Any]] = []
        for row in rows:
            content_lower = row["content"].lower()
            score = sum(0.2 for word in words if word in content_lower)
            score += self._recency_boost(row["indexed_at"])

            results.append(
                {
                    "content": row["content"],
                    "source": row["file_path"],
                    "heading": row["heading_path"],
                    "score": round(score, 3),
                    "scope": row["scope"],
                    "tags": json.loads(row["tags"]) if row["tags"] else [],
                }
            )

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def _recency_boost(self, indexed_at: str) -> float:
        """Boost score for recently indexed chunks."""
        try:
            indexed = datetime.fromisoformat(indexed_at)
            now = datetime.now(UTC)
            days_old = (now - indexed).days
            return 0.05 * max(0, 1 - days_old / 365)
        except (ValueError, TypeError):
            return 0.0

    async def _annotate_staleness(
        self, results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Add stale_warning to results whose covered source files changed."""
        if not self._project_root or not self._db:
            return results

        # Collect unique source file paths from results
        source_files = {r.get("source", "") for r in results}
        if not source_files:
            return results

        # Query covers data for matching knowledge files
        placeholders = ",".join("?" for _ in source_files)
        rows = await self._db.execute(
            f"SELECT DISTINCT file_path, covers, file_updated_at "
            f"FROM knowledge_chunks WHERE file_path IN ({placeholders}) "
            f"AND covers != '[]'",
            tuple(source_files),
        )

        # Build staleness map: file_path → list of changed source files
        stale_map: dict[str, list[str]] = {}
        for row in rows:
            try:
                covers = json.loads(row["covers"])
            except (json.JSONDecodeError, TypeError):
                continue
            if not covers:
                continue

            doc_mtime = row["file_updated_at"]
            changed: list[str] = []
            for pattern in covers:
                for source_path in self._project_root.glob(pattern):
                    source_mtime = datetime.fromtimestamp(
                        source_path.stat().st_mtime, tz=UTC
                    ).isoformat()
                    if source_mtime > doc_mtime:
                        try:
                            rel = str(source_path.relative_to(self._project_root))
                        except ValueError:
                            rel = str(source_path)
                        changed.append(rel)
            if changed:
                stale_map[row["file_path"]] = changed

        # Annotate results
        for result in results:
            source = result.get("source", "")
            if source in stale_map:
                result["stale_warning"] = (
                    f"STALE — source files changed: {', '.join(stale_map[source])}"
                )

        return results
