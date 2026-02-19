"""Document store — collection management, embedding, and RAG retrieval.

Manages document collections in SQLite with sqlite-vec for vector search.
Reuses the existing embedder infrastructure from core/embeddings.py.
"""

from __future__ import annotations

import json
import logging
import struct
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.config import DocumentConfig
from core.database import Database
from core.document_processor import DocumentChunk, DocumentProcessor
from core.storage import StorageManager

logger = logging.getLogger(__name__)


def _serialize_vector(vector: list[float]) -> bytes:
    """Serialize a float vector to bytes for sqlite-vec."""
    return struct.pack(f"{len(vector)}f", *vector)


class DocumentStore:
    """Manages document collections, embedding storage, and RAG retrieval."""

    def __init__(
        self,
        db: Database,
        embedder: Any,  # OllamaEmbedder | OpenRouterEmbedder
        embedding_model: str,
        storage: StorageManager,
        config: DocumentConfig,
    ) -> None:
        self._db = db
        self._embedder = embedder
        self._embedding_model = embedding_model
        self._storage = storage
        self._config = config

    async def create_collection(
        self, name: str, session_id: str | None = None
    ) -> str:
        """Create a new collection, return collection_id."""
        collection_id = uuid.uuid4().hex[:16]
        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "INSERT INTO document_collections (collection_id, name, session_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (collection_id, name, session_id, now),
        )
        self._storage.get_collection_dir(collection_id)
        logger.info("Created document collection '%s' (%s)", name, collection_id[:8])
        return collection_id

    async def add_file(
        self,
        collection_id: str,
        file_path: Path,
        filename: str,
        mime_type: str,
        page_count: int,
        chunks: list[DocumentChunk],
    ) -> str:
        """Store file record and embed+store all chunks. Return file_id."""
        file_id = uuid.uuid4().hex[:16]
        content_hash = DocumentProcessor.content_hash(file_path)
        size_bytes = file_path.stat().st_size
        now = datetime.now(UTC).isoformat()

        # Insert file record
        await self._db.execute_insert(
            "INSERT INTO document_files "
            "(file_id, collection_id, filename, mime_type, size_bytes, page_count, "
            "local_path, content_hash, processed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (file_id, collection_id, filename, mime_type, size_bytes, page_count,
             str(file_path), content_hash, now),
        )

        # Insert chunks and embed
        total_tokens = 0
        for chunk in chunks:
            chunk_id = uuid.uuid4().hex[:16]
            total_tokens += chunk.token_count

            await self._db.execute_insert(
                "INSERT INTO document_chunks "
                "(chunk_id, collection_id, file_id, chunk_index, content, "
                "token_count, page_number, section_title, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (chunk_id, collection_id, file_id, chunk.chunk_index,
                 chunk.content, chunk.token_count, chunk.page_number,
                 chunk.section_title, json.dumps(chunk.metadata)),
            )

            # Embed and store vector
            if self._db.vec_available and self._embedding_model:
                try:
                    embedding = await self._embedder.embed(
                        chunk.content, self._embedding_model
                    )
                    await self._db.execute_insert(
                        "INSERT INTO document_chunks_vec (chunk_id, embedding) VALUES (?, ?)",
                        (chunk_id, _serialize_vector(embedding.vector)),
                    )
                except Exception as e:
                    logger.debug("Failed to embed document chunk %s: %s", chunk_id[:8], e)

        # Update collection counters
        await self._db.execute_insert(
            "UPDATE document_collections SET "
            "file_count = file_count + 1, "
            "chunk_count = chunk_count + ?, "
            "total_tokens = total_tokens + ? "
            "WHERE collection_id = ?",
            (len(chunks), total_tokens, collection_id),
        )

        logger.info(
            "Added '%s' to collection %s (%d chunks, %d tokens)",
            filename, collection_id[:8], len(chunks), total_tokens,
        )
        return file_id

    async def query(
        self, collection_id: str, question: str, top_k: int | None = None
    ) -> list[dict[str, Any]]:
        """Semantic search within a collection. Returns ranked chunks with metadata."""
        if top_k is None:
            top_k = self._config.retrieval_top_k

        results: list[dict[str, Any]] = []

        # Try vector search first
        if self._db.vec_available and self._embedding_model:
            try:
                embedding = await self._embedder.embed(question, self._embedding_model)
                vec_bytes = _serialize_vector(embedding.vector)

                # KNN search — fetch more than top_k to allow post-filtering
                rows = await self._db.execute(
                    "SELECT v.chunk_id, v.distance "
                    "FROM document_chunks_vec v "
                    "WHERE v.embedding MATCH ? "
                    "ORDER BY v.distance "
                    "LIMIT ?",
                    (vec_bytes, top_k * 3),
                )

                # Post-filter by collection_id
                chunk_ids = []
                distances: dict[str, float] = {}
                for row in rows:
                    chunk_ids.append(row["chunk_id"])
                    distances[row["chunk_id"]] = row["distance"]

                if chunk_ids:
                    placeholders = ",".join("?" for _ in chunk_ids)
                    chunk_rows = await self._db.execute(
                        f"SELECT dc.*, df.filename FROM document_chunks dc "
                        f"JOIN document_files df ON dc.file_id = df.file_id "
                        f"WHERE dc.chunk_id IN ({placeholders}) "
                        f"AND dc.collection_id = ?",
                        (*chunk_ids, collection_id),
                    )

                    for row in chunk_rows:
                        cid = row["chunk_id"]
                        score = 1.0 - distances.get(cid, 1.0)

                        # Keyword boost
                        words = question.lower().split()
                        content_lower = row["content"].lower()
                        for word in words:
                            if word in content_lower:
                                score += 0.1

                        results.append({
                            "chunk_id": cid,
                            "content": row["content"],
                            "filename": row["filename"],
                            "page_number": row["page_number"],
                            "section_title": row["section_title"],
                            "token_count": row["token_count"],
                            "score": round(score, 4),
                        })

                    results.sort(key=lambda x: x["score"], reverse=True)
                    return results[:top_k]

            except Exception as e:
                logger.warning("Vector search failed, falling back to keyword: %s", e)

        # Keyword fallback
        return await self._keyword_search(collection_id, question, top_k)

    async def _keyword_search(
        self, collection_id: str, question: str, top_k: int
    ) -> list[dict[str, Any]]:
        """Simple keyword search when vector search is unavailable."""
        words = question.lower().split()
        if not words:
            return []

        # Fetch all chunks in collection
        rows = await self._db.execute(
            "SELECT dc.*, df.filename FROM document_chunks dc "
            "JOIN document_files df ON dc.file_id = df.file_id "
            "WHERE dc.collection_id = ?",
            (collection_id,),
        )

        scored: list[dict[str, Any]] = []
        for row in rows:
            content_lower = row["content"].lower()
            score = sum(0.2 for w in words if w in content_lower)
            if score > 0:
                scored.append({
                    "chunk_id": row["chunk_id"],
                    "content": row["content"],
                    "filename": row["filename"],
                    "page_number": row["page_number"],
                    "section_title": row["section_title"],
                    "token_count": row["token_count"],
                    "score": round(score, 4),
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    async def list_collections(self) -> list[dict[str, Any]]:
        """List all collections with summary stats."""
        rows = await self._db.execute(
            "SELECT * FROM document_collections ORDER BY created_at DESC"
        )
        return [dict(row) for row in rows]

    async def get_collection_info(self, collection_id_or_name: str) -> dict[str, Any] | None:
        """Get detailed info about a collection including file list."""
        col = await self._resolve_collection(collection_id_or_name)
        if not col:
            return None

        cid = col["collection_id"]
        files = await self._db.execute(
            "SELECT * FROM document_files WHERE collection_id = ? ORDER BY processed_at",
            (cid,),
        )
        return {
            **dict(col),
            "files": [dict(f) for f in files],
        }

    async def delete_collection(self, collection_id_or_name: str) -> bool:
        """Delete a collection and all its chunks/files/vectors."""
        col = await self._resolve_collection(collection_id_or_name)
        if not col:
            return False

        cid = col["collection_id"]

        # Get chunk IDs for vector cleanup
        chunks = await self._db.execute(
            "SELECT chunk_id FROM document_chunks WHERE collection_id = ?", (cid,)
        )
        chunk_ids = [r["chunk_id"] for r in chunks]

        # Delete vectors
        if self._db.vec_available and chunk_ids:
            for chunk_id in chunk_ids:
                try:
                    await self._db.execute_insert(
                        "DELETE FROM document_chunks_vec WHERE chunk_id = ?",
                        (chunk_id,),
                    )
                except Exception:
                    pass

        # Delete chunks, files, collection
        await self._db.execute_insert(
            "DELETE FROM document_chunks WHERE collection_id = ?", (cid,)
        )
        await self._db.execute_insert(
            "DELETE FROM document_files WHERE collection_id = ?", (cid,)
        )
        await self._db.execute_insert(
            "DELETE FROM document_collections WHERE collection_id = ?", (cid,)
        )

        logger.info("Deleted collection '%s' (%s)", col["name"], cid[:8])
        return True

    async def _resolve_collection(self, id_or_name: str) -> dict[str, Any] | None:
        """Look up collection by ID or name."""
        # Try by ID first
        rows = await self._db.execute(
            "SELECT * FROM document_collections WHERE collection_id = ?",
            (id_or_name,),
        )
        if rows:
            return dict(rows[0])

        # Try by name (case-insensitive)
        rows = await self._db.execute(
            "SELECT * FROM document_collections WHERE LOWER(name) = LOWER(?)",
            (id_or_name,),
        )
        return dict(rows[0]) if rows else None
