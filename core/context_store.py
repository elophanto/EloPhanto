"""ContextStore — indexed, queryable, sliceable context for RLM Phase 2.

Replaces "dump everything into messages" with a structured context layer.
The agent gets a context index (table of contents) in its prompt and uses
tools to pull specific slices on demand. Sub-agents share the same store
for coordinated reasoning over arbitrarily large inputs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import struct
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Token estimation: ~4 chars per token (same convention used across EloPhanto)
_CHARS_PER_TOKEN = 4

# Default chunk size
_DEFAULT_MAX_TOKENS = 800
_DEFAULT_OVERLAP_TOKENS = 100


def _estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


@dataclass
class ContextChunk:
    """A single chunk of ingested context."""

    chunk_id: str
    context_id: str
    source: str  # file path, URL, or label
    content: str
    token_count: int
    chunk_index: int
    section_title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ContextStore:
    """External context that the agent can query during inference.

    Each context has a unique ID. Sources (files, text, URLs) are ingested
    into chunks, embedded for semantic search, and made available via
    query/slice/transform operations.
    """

    # SQL for the context tables (created on first use)
    _SCHEMA_DDL = [
        """
        CREATE TABLE IF NOT EXISTS context_stores (
            context_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            session_id TEXT,
            created_at TEXT NOT NULL,
            source_count INTEGER DEFAULT 0,
            chunk_count INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS context_sources (
            source_id TEXT PRIMARY KEY,
            context_id TEXT NOT NULL REFERENCES context_stores(context_id),
            source_type TEXT NOT NULL,
            source_path TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL,
            chunk_count INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            ingested_at TEXT NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_context_sources_ctx
            ON context_sources(context_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS context_chunks (
            chunk_id TEXT PRIMARY KEY,
            context_id TEXT NOT NULL REFERENCES context_stores(context_id),
            source_id TEXT NOT NULL REFERENCES context_sources(source_id),
            source_path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            token_count INTEGER NOT NULL,
            section_title TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}'
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_context_chunks_ctx
            ON context_chunks(context_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_context_chunks_source
            ON context_chunks(source_id)
        """,
    ]

    def __init__(self, db: Any, embedder: Any = None) -> None:
        self._db = db
        self._embedder = embedder
        self._schema_initialized = False
        self._vec_table_created = False

    async def _ensure_schema(self) -> None:
        """Create context tables if they don't exist."""
        if self._schema_initialized:
            return
        for ddl in self._SCHEMA_DDL:
            await self._db.execute_insert(ddl)
        self._schema_initialized = True

    async def _ensure_vec_table(self, dimensions: int) -> None:
        """Create context_chunks_vec if sqlite-vec is available."""
        if self._vec_table_created or not self._db.vec_available:
            return
        try:
            await self._db.execute_insert(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS context_chunks_vec USING vec0("
                f"chunk_id TEXT PRIMARY KEY, "
                f"embedding float[{dimensions}])"
            )
            self._vec_table_created = True
        except Exception as e:
            logger.warning("Failed to create context_chunks_vec: %s", e)

    # ── Create / Delete ──────────────────────────────────────────────

    async def create(self, name: str, session_id: str | None = None) -> str:
        """Create a new context store. Returns context_id."""
        await self._ensure_schema()
        context_id = f"ctx_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "INSERT INTO context_stores (context_id, name, session_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (context_id, name, session_id, now),
        )
        logger.info("[context_store] Created %s (%s)", context_id, name)
        return context_id

    async def delete(self, context_id: str) -> bool:
        """Delete a context store and all its chunks/sources."""
        await self._ensure_schema()
        # Delete vector embeddings
        if self._db.vec_available and self._vec_table_created:
            try:
                chunks = await self._db.execute(
                    "SELECT chunk_id FROM context_chunks WHERE context_id = ?",
                    (context_id,),
                )
                for chunk in chunks:
                    await self._db.execute_insert(
                        "DELETE FROM context_chunks_vec WHERE chunk_id = ?",
                        (chunk["chunk_id"],),
                    )
            except Exception:
                pass
        await self._db.execute_insert(
            "DELETE FROM context_chunks WHERE context_id = ?", (context_id,)
        )
        await self._db.execute_insert(
            "DELETE FROM context_sources WHERE context_id = ?", (context_id,)
        )
        result = await self._db.execute_insert(
            "DELETE FROM context_stores WHERE context_id = ?", (context_id,)
        )
        return result > 0

    # ── Ingest ───────────────────────────────────────────────────────

    async def ingest_text(
        self,
        context_id: str,
        source: str,
        content: str,
        source_type: str = "text",
        metadata: dict[str, Any] | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> list[str]:
        """Ingest text content into the store. Returns chunk IDs."""
        await self._ensure_schema()

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        source_id = f"src_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC).isoformat()

        # Chunk the content
        chunks = self._chunk_text(content, source, max_tokens, metadata or {})

        # Insert source record
        await self._db.execute_insert(
            "INSERT INTO context_sources "
            "(source_id, context_id, source_type, source_path, label, "
            "content_hash, chunk_count, total_tokens, ingested_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source_id,
                context_id,
                source_type,
                source,
                source,
                content_hash,
                len(chunks),
                sum(c.token_count for c in chunks),
                now,
            ),
        )

        # Insert chunks
        chunk_ids = []
        for chunk in chunks:
            chunk.context_id = context_id
            chunk.chunk_id = f"chk_{uuid.uuid4().hex[:12]}"
            await self._db.execute_insert(
                "INSERT INTO context_chunks "
                "(chunk_id, context_id, source_id, source_path, chunk_index, "
                "content, token_count, section_title, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    chunk.chunk_id,
                    context_id,
                    source_id,
                    chunk.source,
                    chunk.chunk_index,
                    chunk.content,
                    chunk.token_count,
                    chunk.section_title,
                    json.dumps(chunk.metadata),
                ),
            )
            chunk_ids.append(chunk.chunk_id)

            # Embed the chunk
            if self._embedder:
                try:
                    result = await self._embedder.embed(chunk.content)
                    await self._ensure_vec_table(result.dimensions)
                    blob = struct.pack(f"{len(result.vector)}f", *result.vector)
                    await self._db.execute_insert(
                        "INSERT OR REPLACE INTO context_chunks_vec "
                        "(chunk_id, embedding) VALUES (?, ?)",
                        (chunk.chunk_id, blob),
                    )
                except Exception as e:
                    logger.debug("Embedding failed for chunk %s: %s", chunk.chunk_id, e)

        # Update store counters
        await self._db.execute_insert(
            "UPDATE context_stores SET "
            "source_count = source_count + 1, "
            "chunk_count = chunk_count + ?, "
            "total_tokens = total_tokens + ? "
            "WHERE context_id = ?",
            (len(chunks), sum(c.token_count for c in chunks), context_id),
        )

        logger.info(
            "[context_store] Ingested %s → %d chunks into %s",
            source,
            len(chunks),
            context_id,
        )
        return chunk_ids

    async def ingest_file(
        self,
        context_id: str,
        file_path: str,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> list[str]:
        """Ingest a file into the store. Returns chunk IDs."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        content = path.read_text(encoding="utf-8", errors="replace")
        return await self.ingest_text(
            context_id=context_id,
            source=file_path,
            content=content,
            source_type="file",
            max_tokens=max_tokens,
        )

    # ── Query (semantic search) ──────────────────────────────────────

    async def query(
        self,
        context_id: str,
        query: str,
        max_chunks: int = 5,
    ) -> list[dict[str, Any]]:
        """Semantic search over stored context. Falls back to keyword search."""
        await self._ensure_schema()

        # Try semantic search first
        if self._embedder and self._db.vec_available and self._vec_table_created:
            try:
                return await self._semantic_search(context_id, query, max_chunks)
            except Exception as e:
                logger.debug("Semantic search failed, falling back to keyword: %s", e)

        # Keyword fallback
        return await self._keyword_search(context_id, query, max_chunks)

    async def _semantic_search(
        self, context_id: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        """Semantic search using sqlite-vec."""
        result = await self._embedder.embed(query)
        blob = struct.pack(f"{len(result.vector)}f", *result.vector)

        rows = await self._db.execute(
            "SELECT c.chunk_id, c.source_path, c.chunk_index, c.content, "
            "c.token_count, c.section_title, c.metadata, v.distance "
            "FROM context_chunks_vec v "
            "JOIN context_chunks c ON c.chunk_id = v.chunk_id "
            "WHERE c.context_id = ? AND v.embedding MATCH ? AND k = ? "
            "ORDER BY v.distance",
            (context_id, blob, limit * 2),
        )

        # Score and rank
        query_words = set(query.lower().split())
        results = []
        for r in rows:
            score = 1.0 - r["distance"]
            content_lower = r["content"].lower()
            for word in query_words:
                if word in content_lower:
                    score += 0.1
            results.append(
                {
                    "chunk_id": r["chunk_id"],
                    "source": r["source_path"],
                    "chunk_index": r["chunk_index"],
                    "content": r["content"],
                    "token_count": r["token_count"],
                    "section_title": r["section_title"],
                    "score": round(score, 3),
                }
            )

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    async def _keyword_search(
        self, context_id: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        """Keyword-based fallback search."""
        words = query.lower().split()[:5]
        if not words:
            return []

        conditions = " OR ".join(["c.content LIKE ?"] * len(words))
        params: list[Any] = [context_id] + [f"%{w}%" for w in words]

        rows = await self._db.execute(
            f"SELECT c.chunk_id, c.source_path, c.chunk_index, c.content, "
            f"c.token_count, c.section_title "
            f"FROM context_chunks c "
            f"WHERE c.context_id = ? AND ({conditions}) "
            f"LIMIT ?",
            (*params, limit * 3),
        )

        results = []
        for r in rows:
            content_lower = r["content"].lower()
            score = sum(0.2 for w in words if w in content_lower)
            results.append(
                {
                    "chunk_id": r["chunk_id"],
                    "source": r["source_path"],
                    "chunk_index": r["chunk_index"],
                    "content": r["content"],
                    "token_count": r["token_count"],
                    "section_title": r["section_title"],
                    "score": round(score, 3),
                }
            )

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    # ── Slice (exact retrieval) ──────────────────────────────────────

    async def slice(
        self,
        context_id: str,
        source: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> str:
        """Get exact content by source path and optional line range.

        If start_line/end_line are provided, extracts those lines from the
        concatenated source content. Otherwise returns all content from the source.
        """
        await self._ensure_schema()

        rows = await self._db.execute(
            "SELECT content FROM context_chunks "
            "WHERE context_id = ? AND source_path = ? "
            "ORDER BY chunk_index",
            (context_id, source),
        )

        if not rows:
            # Try partial match
            rows = await self._db.execute(
                "SELECT content FROM context_chunks "
                "WHERE context_id = ? AND source_path LIKE ? "
                "ORDER BY source_path, chunk_index",
                (context_id, f"%{source}%"),
            )

        if not rows:
            return ""

        full_content = "\n".join(r["content"] for r in rows)

        if start_line is not None or end_line is not None:
            lines = full_content.splitlines()
            start = (start_line or 1) - 1
            end = end_line or len(lines)
            return "\n".join(lines[start:end])

        return full_content

    # ── Index (table of contents) ────────────────────────────────────

    async def index(self, context_id: str) -> str:
        """Return a table of contents / summary of the context store.

        This is what goes into the system prompt so the agent knows
        what's available without loading full content.
        """
        await self._ensure_schema()

        store = await self._db.execute(
            "SELECT name, source_count, chunk_count, total_tokens "
            "FROM context_stores WHERE context_id = ?",
            (context_id,),
        )
        if not store:
            return f"Context {context_id} not found."

        s = store[0]
        lines = [
            f"# Context: {s['name']} ({context_id})",
            f"Sources: {s['source_count']} | Chunks: {s['chunk_count']} | "
            f"Tokens: {s['total_tokens']:,}",
            "",
            "## Sources",
        ]

        sources = await self._db.execute(
            "SELECT source_path, source_type, chunk_count, total_tokens "
            "FROM context_sources WHERE context_id = ? "
            "ORDER BY ingested_at",
            (context_id,),
        )

        for src in sources:
            lines.append(
                f"- **{src['source_path']}** ({src['source_type']}) — "
                f"{src['chunk_count']} chunks, {src['total_tokens']:,} tokens"
            )

        # Add section titles if available
        sections = await self._db.execute(
            "SELECT DISTINCT source_path, section_title FROM context_chunks "
            "WHERE context_id = ? AND section_title != '' "
            "ORDER BY source_path, chunk_index",
            (context_id,),
        )
        if sections:
            lines.extend(["", "## Sections"])
            current_source = ""
            for sec in sections:
                if sec["source_path"] != current_source:
                    current_source = sec["source_path"]
                    lines.append(f"### {current_source}")
                lines.append(f"  - {sec['section_title']}")

        return "\n".join(lines)

    # ── Transform ────────────────────────────────────────────────────

    async def transform(
        self,
        context_id: str,
        operation: str,
        params: dict[str, Any] | None = None,
    ) -> str:
        """Apply transformations to context: filter, group, summarize, diff."""
        await self._ensure_schema()
        params = params or {}

        if operation == "filter":
            return await self._transform_filter(context_id, params)
        elif operation == "group":
            return await self._transform_group(context_id)
        elif operation == "stats":
            return await self._transform_stats(context_id)
        elif operation == "sources":
            return await self._transform_sources(context_id)
        else:
            return f"Unknown transform operation: {operation}. Available: filter, group, stats, sources"

    async def _transform_filter(self, context_id: str, params: dict[str, Any]) -> str:
        """Filter chunks by keyword or source pattern."""
        keyword = params.get("keyword", "")
        source_pattern = params.get("source", "")
        max_results = params.get("max_results", 20)

        conditions = ["c.context_id = ?"]
        sql_params: list[Any] = [context_id]

        if keyword:
            conditions.append("c.content LIKE ?")
            sql_params.append(f"%{keyword}%")
        if source_pattern:
            conditions.append("c.source_path LIKE ?")
            sql_params.append(f"%{source_pattern}%")

        where = " AND ".join(conditions)
        rows = await self._db.execute(
            f"SELECT source_path, chunk_index, section_title, content, token_count "
            f"FROM context_chunks c WHERE {where} "
            f"ORDER BY source_path, chunk_index LIMIT ?",
            (*sql_params, max_results),
        )

        if not rows:
            return "No chunks match the filter."

        lines = [f"Filtered {len(rows)} chunks:"]
        for r in rows:
            title = f" ({r['section_title']})" if r["section_title"] else ""
            lines.append(f"\n--- {r['source_path']} [#{r['chunk_index']}]{title} ---")
            lines.append(r["content"])
        return "\n".join(lines)

    async def _transform_group(self, context_id: str) -> str:
        """Group chunks by source with counts."""
        rows = await self._db.execute(
            "SELECT source_path, COUNT(*) as cnt, SUM(token_count) as tokens "
            "FROM context_chunks WHERE context_id = ? "
            "GROUP BY source_path ORDER BY tokens DESC",
            (context_id,),
        )
        lines = ["Source | Chunks | Tokens"]
        lines.append("---|---|---")
        for r in rows:
            lines.append(f"{r['source_path']} | {r['cnt']} | {r['tokens']:,}")
        return "\n".join(lines)

    async def _transform_stats(self, context_id: str) -> str:
        """Get statistics about the context store."""
        store = await self._db.execute(
            "SELECT * FROM context_stores WHERE context_id = ?", (context_id,)
        )
        if not store:
            return "Context not found."
        s = store[0]
        return (
            f"Context: {s['name']}\n"
            f"Sources: {s['source_count']}\n"
            f"Chunks: {s['chunk_count']}\n"
            f"Total tokens: {s['total_tokens']:,}\n"
            f"Created: {s['created_at']}"
        )

    async def _transform_sources(self, context_id: str) -> str:
        """List all sources in the context."""
        rows = await self._db.execute(
            "SELECT source_path, source_type, chunk_count, total_tokens, ingested_at "
            "FROM context_sources WHERE context_id = ? ORDER BY ingested_at",
            (context_id,),
        )
        lines = []
        for r in rows:
            lines.append(
                f"- {r['source_path']} ({r['source_type']}) — "
                f"{r['chunk_count']} chunks, {r['total_tokens']:,} tokens "
                f"[{r['ingested_at'][:10]}]"
            )
        return "\n".join(lines) if lines else "No sources ingested."

    # ── List contexts ────────────────────────────────────────────────

    async def list_contexts(self) -> list[dict[str, Any]]:
        """List all context stores."""
        await self._ensure_schema()
        rows = await self._db.execute(
            "SELECT context_id, name, source_count, chunk_count, total_tokens, "
            "created_at FROM context_stores ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]

    # ── Chunking ─────────────────────────────────────────────────────

    def _chunk_text(
        self,
        content: str,
        source: str,
        max_tokens: int,
        metadata: dict[str, Any],
    ) -> list[ContextChunk]:
        """Split text into chunks using heading-aware splitting."""
        chunks: list[ContextChunk] = []
        max_chars = max_tokens * _CHARS_PER_TOKEN

        # Try splitting by headings first
        sections = self._split_by_headings(content)

        if len(sections) > 1:
            for title, body in sections:
                if _estimate_tokens(body) <= max_tokens:
                    chunks.append(
                        ContextChunk(
                            chunk_id="",
                            context_id="",
                            source=source,
                            content=body,
                            token_count=_estimate_tokens(body),
                            chunk_index=len(chunks),
                            section_title=title,
                            metadata=metadata,
                        )
                    )
                else:
                    # Sub-chunk large sections
                    for sub in self._split_by_size(body, max_chars):
                        chunks.append(
                            ContextChunk(
                                chunk_id="",
                                context_id="",
                                source=source,
                                content=sub,
                                token_count=_estimate_tokens(sub),
                                chunk_index=len(chunks),
                                section_title=title,
                                metadata=metadata,
                            )
                        )
        else:
            # No headings — split by size
            for sub in self._split_by_size(content, max_chars):
                chunks.append(
                    ContextChunk(
                        chunk_id="",
                        context_id="",
                        source=source,
                        content=sub,
                        token_count=_estimate_tokens(sub),
                        chunk_index=len(chunks),
                        metadata=metadata,
                    )
                )

        # Filter empty chunks
        return [c for c in chunks if c.content.strip()]

    @staticmethod
    def _split_by_headings(content: str) -> list[tuple[str, str]]:
        """Split content by markdown headings (## or #)."""
        import re

        sections: list[tuple[str, str]] = []
        pattern = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
        matches = list(pattern.finditer(content))

        if not matches:
            return [("", content)]

        # Content before first heading
        if matches[0].start() > 0:
            preamble = content[: matches[0].start()].strip()
            if preamble:
                sections.append(("", preamble))

        for i, match in enumerate(matches):
            title = match.group(2).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            body = content[start:end].strip()
            if body:
                sections.append((title, body))

        return sections if sections else [("", content)]

    @staticmethod
    def _split_by_size(text: str, max_chars: int) -> list[str]:
        """Split text into size-limited chunks at paragraph boundaries."""
        overlap_chars = _DEFAULT_OVERLAP_TOKENS * _CHARS_PER_TOKEN
        paragraphs = text.split("\n\n")
        chunks: list[str] = []
        current = ""

        for para in paragraphs:
            if len(current) + len(para) + 2 > max_chars and current:
                chunks.append(current.strip())
                # Overlap: keep last bit of previous chunk
                if overlap_chars > 0 and len(current) > overlap_chars:
                    current = current[-overlap_chars:] + "\n\n" + para
                else:
                    current = para
            else:
                current = current + "\n\n" + para if current else para

        if current.strip():
            chunks.append(current.strip())

        return chunks
