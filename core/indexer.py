"""Knowledge indexer: parses markdown, chunks, embeds, and stores.

Implements the chunking strategy from the spec:
1. Split by H2 headings
2. If chunk > max_tokens → split by H3
3. If still > max_tokens → split by paragraphs
4. Merge chunks < min_tokens with next
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from core.database import Database
from core.embeddings import EmbeddingClient

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 characters per token."""
    return max(1, len(text) // 4)


@dataclass
class Chunk:
    """A single indexed chunk of knowledge."""

    content: str
    heading_path: str
    file_path: str
    tags: list[str]
    scope: str
    token_count: int


@dataclass
class IndexResult:
    """Result of an indexing operation."""

    files_indexed: int = 0
    chunks_created: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


class KnowledgeIndexer:
    """Indexes markdown knowledge files into the database with embeddings."""

    def __init__(
        self,
        db: Database,
        embedder: EmbeddingClient,
        knowledge_dir: Path,
        max_tokens: int = 1000,
        min_tokens: int = 50,
    ) -> None:
        self._db = db
        self._embedder = embedder
        self._knowledge_dir = knowledge_dir
        self._max_tokens = max_tokens
        self._min_tokens = min_tokens
        self._embedding_model: str = "nomic-embed-text"

    def set_embedding_model(self, model: str) -> None:
        self._embedding_model = model

    async def index_all(self) -> IndexResult:
        """Full reindex of all markdown files in knowledge directory."""
        start = time.monotonic()
        result = IndexResult()

        if not self._knowledge_dir.exists():
            return result

        md_files = list(self._knowledge_dir.rglob("*.md"))
        for file_path in md_files:
            try:
                chunks = await self.index_file(file_path)
                result.files_indexed += 1
                result.chunks_created += chunks
            except Exception as e:
                error = f"Failed to index {file_path}: {e}"
                logger.warning(error)
                result.errors.append(error)

        result.duration_seconds = time.monotonic() - start
        logger.info(
            f"Indexed {result.files_indexed} files, "
            f"{result.chunks_created} chunks in {result.duration_seconds:.1f}s"
        )
        return result

    async def index_file(self, file_path: Path) -> int:
        """Index a single markdown file. Returns the number of chunks created."""
        content = file_path.read_text(encoding="utf-8")
        frontmatter, body = self._parse_frontmatter(content)

        rel_path = str(file_path)
        try:
            rel_path = str(file_path.relative_to(self._knowledge_dir))
        except ValueError:
            pass

        tags = frontmatter.get("tags", "")
        if isinstance(tags, str):
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        elif isinstance(tags, list):
            tag_list = tags
        else:
            tag_list = []

        scope = frontmatter.get("scope", "system")
        file_mtime = datetime.fromtimestamp(
            file_path.stat().st_mtime, tz=UTC
        ).isoformat()

        chunks = self._chunk_markdown(body, frontmatter, rel_path, tag_list, scope)
        chunks = self._merge_small_chunks(chunks)

        await self._store_chunks(chunks, rel_path, file_mtime)
        return len(chunks)

    async def index_incremental(self) -> IndexResult:
        """Only re-index files that have changed since last indexing."""
        start = time.monotonic()
        result = IndexResult()

        if not self._knowledge_dir.exists():
            return result

        # Get last indexed times per file
        rows = await self._db.execute(
            "SELECT DISTINCT file_path, MAX(file_updated_at) as last_update "
            "FROM knowledge_chunks GROUP BY file_path"
        )
        indexed_times: dict[str, str] = {
            row["file_path"]: row["last_update"] for row in rows
        }

        md_files = list(self._knowledge_dir.rglob("*.md"))
        for file_path in md_files:
            rel_path = str(file_path)
            try:
                rel_path = str(file_path.relative_to(self._knowledge_dir))
            except ValueError:
                pass

            file_mtime = datetime.fromtimestamp(
                file_path.stat().st_mtime, tz=UTC
            ).isoformat()

            if rel_path in indexed_times and indexed_times[rel_path] >= file_mtime:
                continue  # File hasn't changed

            try:
                chunks = await self.index_file(file_path)
                result.files_indexed += 1
                result.chunks_created += chunks
            except Exception as e:
                error = f"Failed to index {file_path}: {e}"
                logger.warning(error)
                result.errors.append(error)

        result.duration_seconds = time.monotonic() - start
        return result

    def _parse_frontmatter(self, content: str) -> tuple[dict[str, Any], str]:
        """Parse YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return {}, content

        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content

        try:
            metadata = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            metadata = {}

        body = parts[2].strip()
        return metadata, body

    def _chunk_markdown(
        self,
        content: str,
        frontmatter: dict[str, Any],
        file_path: str,
        tags: list[str],
        scope: str,
    ) -> list[Chunk]:
        """Split markdown into chunks following the spec strategy."""
        chunks: list[Chunk] = []
        title = frontmatter.get("title", "")

        sections = self._split_by_heading(content, r"^## ", level=2)

        if not sections:
            # No H2 headings — treat whole content as one chunk
            token_count = _estimate_tokens(content)
            if token_count > 0:
                chunks.append(
                    Chunk(
                        content=content.strip(),
                        heading_path=title,
                        file_path=file_path,
                        tags=tags,
                        scope=scope,
                        token_count=token_count,
                    )
                )
            return chunks

        for heading, body in sections:
            section_text = f"## {heading}\n{body}" if heading else body
            token_count = _estimate_tokens(section_text)

            if token_count <= self._max_tokens:
                heading_path = (
                    f"{title} > {heading}" if title and heading else (heading or title)
                )
                chunks.append(
                    Chunk(
                        content=section_text.strip(),
                        heading_path=heading_path,
                        file_path=file_path,
                        tags=tags,
                        scope=scope,
                        token_count=token_count,
                    )
                )
            else:
                # Split further by H3
                h3_sections = self._split_by_heading(body, r"^### ", level=3)
                if h3_sections and len(h3_sections) > 1:
                    for h3_heading, h3_body in h3_sections:
                        h3_text = (
                            f"### {h3_heading}\n{h3_body}" if h3_heading else h3_body
                        )
                        h3_tokens = _estimate_tokens(h3_text)

                        if h3_tokens <= self._max_tokens:
                            hp = " > ".join(
                                p for p in [title, heading, h3_heading] if p
                            )
                            chunks.append(
                                Chunk(
                                    content=h3_text.strip(),
                                    heading_path=hp,
                                    file_path=file_path,
                                    tags=tags,
                                    scope=scope,
                                    token_count=h3_tokens,
                                )
                            )
                        else:
                            # Split by paragraphs
                            para_chunks = self._split_by_paragraphs(
                                h3_text,
                                title,
                                heading,
                                h3_heading,
                                file_path,
                                tags,
                                scope,
                            )
                            chunks.extend(para_chunks)
                else:
                    # No H3 subdivisions — split by paragraphs
                    para_chunks = self._split_by_paragraphs(
                        section_text, title, heading, "", file_path, tags, scope
                    )
                    chunks.extend(para_chunks)

        return chunks

    def _split_by_heading(
        self, content: str, pattern: str, level: int
    ) -> list[tuple[str, str]]:
        """Split content by heading pattern. Returns [(heading_text, body), ...]."""
        lines = content.split("\n")
        sections: list[tuple[str, str]] = []
        current_heading = ""
        current_lines: list[str] = []
        prefix = "#" * level + " "

        for line in lines:
            if re.match(pattern, line, re.MULTILINE):
                # Save previous section
                if current_lines or current_heading:
                    sections.append((current_heading, "\n".join(current_lines).strip()))
                current_heading = line[len(prefix) :].strip()
                current_lines = []
            else:
                current_lines.append(line)

        # Don't forget the last section
        if current_lines or current_heading:
            sections.append((current_heading, "\n".join(current_lines).strip()))

        return sections

    def _split_by_paragraphs(
        self,
        text: str,
        title: str,
        h2: str,
        h3: str,
        file_path: str,
        tags: list[str],
        scope: str,
    ) -> list[Chunk]:
        """Split text into paragraph-based chunks with min ~200 tokens each."""
        paragraphs = re.split(r"\n\n+", text.strip())
        chunks: list[Chunk] = []
        current_text = ""
        min_para_tokens = 200

        for para in paragraphs:
            if not para.strip():
                continue
            candidate = f"{current_text}\n\n{para}" if current_text else para
            if _estimate_tokens(candidate) > self._max_tokens and current_text:
                # Flush current
                hp = " > ".join(p for p in [title, h2, h3] if p)
                chunks.append(
                    Chunk(
                        content=current_text.strip(),
                        heading_path=hp,
                        file_path=file_path,
                        tags=tags,
                        scope=scope,
                        token_count=_estimate_tokens(current_text),
                    )
                )
                current_text = para
            else:
                current_text = candidate

        # Flush remaining
        if current_text.strip():
            hp = " > ".join(p for p in [title, h2, h3] if p)
            tok = _estimate_tokens(current_text)
            if chunks and tok < min_para_tokens:
                # Merge with last chunk
                chunks[-1] = Chunk(
                    content=f"{chunks[-1].content}\n\n{current_text.strip()}",
                    heading_path=chunks[-1].heading_path,
                    file_path=chunks[-1].file_path,
                    tags=chunks[-1].tags,
                    scope=chunks[-1].scope,
                    token_count=chunks[-1].token_count + tok,
                )
            else:
                chunks.append(
                    Chunk(
                        content=current_text.strip(),
                        heading_path=hp,
                        file_path=file_path,
                        tags=tags,
                        scope=scope,
                        token_count=tok,
                    )
                )

        return chunks

    def _merge_small_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """Merge chunks smaller than min_tokens with the next chunk."""
        if not chunks:
            return chunks

        merged: list[Chunk] = []
        i = 0
        while i < len(chunks):
            chunk = chunks[i]
            if chunk.token_count < self._min_tokens and i + 1 < len(chunks):
                # Merge with next
                next_chunk = chunks[i + 1]
                merged_chunk = Chunk(
                    content=f"{chunk.content}\n\n{next_chunk.content}",
                    heading_path=next_chunk.heading_path or chunk.heading_path,
                    file_path=chunk.file_path,
                    tags=chunk.tags,
                    scope=chunk.scope,
                    token_count=chunk.token_count + next_chunk.token_count,
                )
                chunks[i + 1] = merged_chunk
                i += 1
            else:
                merged.append(chunk)
                i += 1

        return merged

    async def _store_chunks(
        self, chunks: list[Chunk], file_path: str, file_mtime: str
    ) -> None:
        """Delete old chunks for this file, insert new ones with embeddings."""
        now = datetime.now(UTC).isoformat()

        # Delete existing chunks for this file
        await self._db.execute(
            "DELETE FROM knowledge_chunks WHERE file_path = ?", (file_path,)
        )

        # Delete from vec table too
        if self._db.vec_available:
            # Get IDs to delete from vec table
            existing = await self._db.execute(
                "SELECT id FROM knowledge_chunks WHERE file_path = ?", (file_path,)
            )
            for row in existing:
                await self._db.execute(
                    "DELETE FROM vec_chunks WHERE chunk_id = ?", (row["id"],)
                )

        for chunk in chunks:
            # Redact PII before any storage — embeddings are permanent
            from core.pii_guard import redact_pii

            clean_content = redact_pii(chunk.content)

            # Insert into knowledge_chunks
            chunk_id = await self._db.execute_insert(
                "INSERT INTO knowledge_chunks "
                "(file_path, heading_path, content, tags, scope, "
                "token_count, file_updated_at, indexed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    file_path,
                    chunk.heading_path,
                    clean_content,
                    json.dumps(chunk.tags),
                    chunk.scope,
                    chunk.token_count,
                    file_mtime,
                    now,
                ),
            )

            # Embed and store in vec table
            if self._db.vec_available:
                try:
                    embedding = await self._embedder.embed(
                        clean_content, self._embedding_model
                    )
                    await self._db.execute_insert(
                        "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
                        (chunk_id, _serialize_vector(embedding.vector)),
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to embed chunk {chunk_id} "
                        f"(model={self._embedding_model}): {e}"
                    )


def _serialize_vector(vector: list[float]) -> bytes:
    """Serialize a float vector to bytes for sqlite-vec."""
    import struct

    return struct.pack(f"{len(vector)}f", *vector)
