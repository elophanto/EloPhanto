"""Knowledge search tool: hybrid semantic + keyword search.

Searches the indexed knowledge base using vector similarity (sqlite-vec)
combined with keyword boosting, recency boosting, and scope filtering.
Falls back to keyword-only search if embeddings are unavailable.
"""

from __future__ import annotations

import json
import logging
import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


_QUERY_REWRITE_SYSTEM = (
    "You convert imperative user prompts into knowledge-base search queries.\n\n"
    "The query below returned 0 results from a semantic + keyword knowledge "
    "base. The KB stores past lessons, post-mortems, scratchpads, learned "
    "patterns, and operating logs — not directives. Imperative phrasing "
    '("do X", "make Y", "post Z") never matches because the KB has no '
    "chunks shaped like instructions.\n\n"
    "Rewrite the query as 4-8 topic keywords focused on what to LOOK UP, not "
    "what to DO. Strip pronouns, filler, and verbs of intent. Keep concrete "
    "nouns, account/product names, time anchors, and domain terms.\n\n"
    "Examples:\n"
    '  bad:  "do a post on X, you were doing some updates"\n'
    "  good: recent X originals cadence updates @EloPhanto lessons\n\n"
    '  bad:  "stop replying to bot accounts"\n'
    "  good: bot account filter X replies blocked accounts policy\n\n"
    '  bad:  "ship this PR after the migration is green"\n'
    "  good: deployment migration verification PR readiness checklist\n\n"
    "Reply with ONLY the topic keywords on a single line — no quotes, no "
    "preamble, no explanation."
)


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
        # LLM router for one-shot query rewriting on 0-result misses.
        # When ``None`` the rewrite path is skipped and the tool keeps
        # the legacy behaviour of returning the empty result as-is.
        self._router: Any = None  # Injected by agent

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
        # The 0-result auto-rewrite spends one LLM completion. Callers that
        # must not incur an LLM call (e.g. the agent's best-effort pre-loop
        # context retrieval) pass rewrite=False; explicit agent tool calls
        # default to True. Internal flag — not exposed in the LLM schema.
        allow_rewrite = bool(params.get("rewrite", True))

        if not self._db:
            return ToolResult(success=False, error="Knowledge database not initialized")

        try:
            # Cascade: semantic → keyword → (router-rewrite + retry).
            #
            # Loss-of-recall beats loss-of-answer for an autonomous loop
            # that depends on dedupe, so we try every cheap path before
            # accepting an empty result. The old code only fell through
            # to keyword on a thrown exception — observed in production
            # the embedder regularly returns a non-empty vec_rows list
            # that scores below the keyword path's hits, leaving us with
            # 0 results despite the KB having matching chunks.
            results: list[dict[str, Any]] | None = None
            search_type = "keyword"  # actual path taken, not availability

            if self._embedder and self._db.vec_available:
                try:
                    results = await self._semantic_search(query, scope, limit)
                    if results:
                        search_type = "semantic"
                except Exception as embed_err:
                    logger.warning(
                        "Semantic search failed (%s); falling back to keyword",
                        embed_err,
                    )
                    results = None

            # Second fallback layer: when semantic returned EMPTY (not
            # just threw), still try keyword. Catches the most common
            # production miss — embedder hiccup or query embedding far
            # from any indexed chunk but with literal word matches.
            if not results:
                results = await self._keyword_search(query, scope, limit)
                if results:
                    search_type = "keyword"

            # Annotate stale results whose covered source files changed
            if self._project_root and results:
                results = await self._annotate_staleness(results)

            count = len(results)
            effective_query = query
            rewritten_from: str | None = None

            # ── 0-result auto-rewrite ────────────────────────────────
            # Observed pattern from production: agents pass the user's
            # verbatim directive ("do a post on X, you were doing some
            # updates") as the search query. The KB stores topics, not
            # directives, so semantic search misses every time. One
            # bounded LLM rewrite turns the imperative into topic
            # keywords and we retry. If the retry also misses, we
            # return the original empty result — never a loop, never
            # more than one extra LLM call per search.
            if count == 0 and self._router is not None and allow_rewrite:
                rewritten = await self._rewrite_query(query)
                if (
                    rewritten
                    and rewritten.strip()
                    and rewritten.strip() != query.strip()
                ):
                    logger.info(
                        "knowledge_search: rewriting | original=%r → rewritten=%r",
                        query,
                        rewritten,
                    )
                    retry_results: list[dict[str, Any]] | None = None
                    if self._embedder and self._db.vec_available:
                        try:
                            retry_results = await self._semantic_search(
                                rewritten, scope, limit
                            )
                        except Exception as embed_err:
                            logger.warning(
                                "Semantic retry failed (%s); falling back to keyword",
                                embed_err,
                            )
                    if retry_results is None:
                        retry_results = await self._keyword_search(
                            rewritten, scope, limit
                        )
                    if self._project_root and retry_results:
                        retry_results = await self._annotate_staleness(retry_results)
                    if retry_results:
                        results = retry_results
                        count = len(results)
                        effective_query = rewritten
                        rewritten_from = query

            # Hit-rate observability: every search leaves one log line so
            # we can grep for empty-result patterns. The old success log
            # only said "succeeded" — couldn't tell a 0-hit miss from a
            # rich return, so the agent's recall behaviour was invisible.
            # Empty hits escalate to WARNING because they're the actionable
            # signal (search query too narrow, scope filter wrong, or KB
            # genuinely missing the topic, or the rewrite also missed).
            if count == 0:
                logger.warning(
                    "knowledge_search: 0 results | query=%r scope=%s type=%s limit=%d",
                    query,
                    scope,
                    search_type,
                    limit,
                )
            else:
                top_score = results[0].get("score", 0) if results else 0
                if rewritten_from is not None:
                    logger.info(
                        "knowledge_search: %d results AFTER REWRITE | "
                        "from=%r to=%r scope=%s type=%s top_score=%s",
                        count,
                        rewritten_from,
                        effective_query,
                        scope,
                        search_type,
                        top_score,
                    )
                else:
                    logger.info(
                        "knowledge_search: %d results | query=%r scope=%s type=%s top_score=%s",
                        count,
                        query,
                        scope,
                        search_type,
                        top_score,
                    )

            data: dict[str, Any] = {
                "results": results,
                "count": count,
                "search_type": search_type,
            }
            if rewritten_from is not None:
                # Surface the rewrite in the tool result so the LLM can
                # see what happened and reuse the better phrasing next
                # time instead of repeating the same miss.
                data["query_rewritten_from"] = rewritten_from
                data["query_used"] = effective_query
            return ToolResult(success=True, data=data)
        except Exception as e:
            logger.error(
                "knowledge_search failed: %s | query=%r scope=%s", e, query, scope
            )
            return ToolResult(success=False, error=f"Search failed: {e}")

    async def _rewrite_query(self, query: str) -> str | None:
        """Ask the router for a topic-keyword rewrite of an imperative query.

        Bounded to one LLM call per search. Returns the rewritten query
        on success, or ``None`` on any failure (timeout, provider error,
        empty response). The caller decides whether to retry the search.

        We keep this strict: low temperature, small token budget, no
        tools. The model just spits out keywords on one line.
        """
        try:
            response = await self._router.complete(
                messages=[
                    {"role": "system", "content": _QUERY_REWRITE_SYSTEM},
                    {"role": "user", "content": query},
                ],
                task_type="analysis",
                temperature=0.2,
                max_tokens=80,
            )
            text = (response.content or "").strip()
            # Strip common preamble in case the model ignored "no preamble"
            for prefix in ("topics:", "keywords:", "query:", "rewrite:"):
                if text.lower().startswith(prefix):
                    text = text[len(prefix) :].strip()
            # First line only (defensive — the prompt asks for one line)
            text = text.splitlines()[0].strip() if text else ""
            # Strip wrapping quotes if any
            text = text.strip('"').strip("'").strip()
            return text or None
        except Exception as e:
            logger.warning("knowledge_search: rewrite failed (%s)", e)
            return None

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
