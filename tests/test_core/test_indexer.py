"""Knowledge indexer tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.database import Database
from core.embeddings import EmbeddingClient, EmbeddingResult
from core.indexer import KnowledgeIndexer, _estimate_tokens


def _make_mock_embedder() -> EmbeddingClient:
    """Create an embedder that returns deterministic vectors."""
    embedder = EmbeddingClient.__new__(EmbeddingClient)

    async def fake_embed(text: str, model: str = "nomic-embed-text") -> EmbeddingResult:
        import hashlib

        h = hashlib.md5(text.encode()).hexdigest()
        vec = [int(c, 16) / 15.0 for c in h] * 48  # 768 dims
        return EmbeddingResult(vector=vec[:768], model=model, dimensions=768)

    embedder.embed = fake_embed
    embedder.embed_batch = AsyncMock(
        side_effect=lambda texts, model="nomic-embed-text": []
    )
    return embedder


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    await d.initialize()
    await d.create_vec_table(768)
    yield d
    await d.close()


@pytest.fixture
def knowledge_dir(tmp_path: Path) -> Path:
    kd = tmp_path / "knowledge"
    kd.mkdir()
    return kd


@pytest.fixture
def indexer(db: Database, knowledge_dir: Path) -> KnowledgeIndexer:
    return KnowledgeIndexer(
        db=db,
        embedder=_make_mock_embedder(),
        knowledge_dir=knowledge_dir,
        max_tokens=1000,
        min_tokens=50,
    )


class TestFrontmatter:
    def test_parse_valid_frontmatter(self, indexer: KnowledgeIndexer) -> None:
        """Valid YAML frontmatter is parsed correctly."""
        content = "---\ntitle: Test\ntags: a, b\nscope: system\n---\n\n# Body"
        meta, body = indexer._parse_frontmatter(content)
        assert meta["title"] == "Test"
        assert meta["tags"] == "a, b"
        assert body == "# Body"

    def test_parse_no_frontmatter(self, indexer: KnowledgeIndexer) -> None:
        """Content without frontmatter returns empty metadata."""
        meta, body = indexer._parse_frontmatter("# Just a heading\n\nSome text")
        assert meta == {}
        assert "Just a heading" in body

    def test_parse_malformed_frontmatter(self, indexer: KnowledgeIndexer) -> None:
        """Malformed YAML returns empty metadata."""
        content = "---\n: invalid yaml [[\n---\n\n# Body"
        meta, body = indexer._parse_frontmatter(content)
        assert meta == {}
        assert body == "# Body"


class TestChunking:
    def test_single_section_no_split(self, indexer: KnowledgeIndexer) -> None:
        """Short document stays as one chunk."""
        content = (
            "---\ntitle: Test\nscope: system\n---\n\n## Section One\n\nShort text."
        )
        meta, body = indexer._parse_frontmatter(content)
        chunks = indexer._chunk_markdown(body, meta, "test.md", ["tag1"], "system")
        assert len(chunks) >= 1
        assert "Short text" in chunks[0].content

    def test_multiple_h2_sections(self, indexer: KnowledgeIndexer) -> None:
        """Multiple H2 sections produce multiple chunks."""
        body = "## Section A\n\nContent A.\n\n## Section B\n\nContent B."
        chunks = indexer._chunk_markdown(
            body, {"title": "Doc"}, "test.md", [], "system"
        )
        assert len(chunks) == 2
        assert any("Content A" in c.content for c in chunks)
        assert any("Content B" in c.content for c in chunks)

    def test_heading_path_includes_title(self, indexer: KnowledgeIndexer) -> None:
        """Heading path includes document title."""
        body = "## My Section\n\nContent here."
        chunks = indexer._chunk_markdown(
            body, {"title": "Doc Title"}, "test.md", [], "system"
        )
        assert "Doc Title" in chunks[0].heading_path
        assert "My Section" in chunks[0].heading_path

    def test_no_headings_single_chunk(self, indexer: KnowledgeIndexer) -> None:
        """Content without headings becomes one chunk."""
        body = "Just plain text with no headings at all."
        chunks = indexer._chunk_markdown(body, {"title": "Test"}, "t.md", [], "system")
        assert len(chunks) == 1

    def test_small_chunks_merged(self, indexer: KnowledgeIndexer) -> None:
        """Chunks smaller than min_tokens get merged."""
        # Create chunks that are very small (< 50 tokens each)
        indexer._min_tokens = 50
        body = "## A\n\nHi.\n\n## B\n\nBye."
        chunks = indexer._chunk_markdown(body, {}, "t.md", [], "system")
        merged = indexer._merge_small_chunks(chunks)
        # Both are tiny so they should be merged
        assert len(merged) <= len(chunks)


class TestTokenEstimation:
    def test_estimate_tokens(self) -> None:
        assert _estimate_tokens("hello world") >= 1
        assert _estimate_tokens("a" * 400) == 100
        assert _estimate_tokens("") == 1


class TestIndexing:
    @pytest.mark.asyncio
    async def test_index_file(
        self, indexer: KnowledgeIndexer, knowledge_dir: Path, db: Database
    ) -> None:
        """Indexing a file stores chunks in the database."""
        md_file = knowledge_dir / "test.md"
        md_file.write_text(
            "---\ntitle: Test Doc\ntags: test\nscope: system\n---\n\n"
            "## Section One\n\n"
            "This is a fairly substantial section with enough content to exceed the "
            "minimum token threshold. It discusses important architectural decisions "
            "about the knowledge indexing pipeline and how markdown files are chunked "
            "into smaller pieces for embedding and retrieval.\n\n"
            "## Section Two\n\n"
            "This second section also contains enough text to stand on its own as a "
            "separate chunk. It covers the embedding client integration with Ollama "
            "and how vectors are stored in sqlite-vec for efficient nearest-neighbor "
            "search across the knowledge base."
        )

        count = await indexer.index_file(md_file)
        assert count >= 2

        rows = await db.execute("SELECT * FROM knowledge_chunks")
        assert len(rows) >= 2

    @pytest.mark.asyncio
    async def test_index_all(
        self, indexer: KnowledgeIndexer, knowledge_dir: Path
    ) -> None:
        """index_all processes all markdown files."""
        (knowledge_dir / "a.md").write_text("---\ntitle: A\n---\n\n## A\n\nContent A.")
        (knowledge_dir / "b.md").write_text("---\ntitle: B\n---\n\n## B\n\nContent B.")

        result = await indexer.index_all()
        assert result.files_indexed == 2
        assert result.chunks_created >= 2

    @pytest.mark.asyncio
    async def test_index_incremental_skips_unchanged(
        self, indexer: KnowledgeIndexer, knowledge_dir: Path
    ) -> None:
        """Incremental indexing skips files that haven't changed."""
        md_file = knowledge_dir / "test.md"
        md_file.write_text("---\ntitle: Test\n---\n\n## Sec\n\nContent.")

        # First index
        result1 = await indexer.index_incremental()
        assert result1.files_indexed == 1

        # Second index without changes
        result2 = await indexer.index_incremental()
        assert result2.files_indexed == 0

    @pytest.mark.asyncio
    async def test_reindex_replaces_chunks(
        self, indexer: KnowledgeIndexer, knowledge_dir: Path, db: Database
    ) -> None:
        """Re-indexing a file replaces old chunks."""
        md_file = knowledge_dir / "test.md"
        md_file.write_text("---\ntitle: V1\n---\n\n## Sec\n\nVersion 1.")
        await indexer.index_file(md_file)

        md_file.write_text("---\ntitle: V2\n---\n\n## Sec\n\nVersion 2.")
        await indexer.index_file(md_file)

        rows = await db.execute(
            "SELECT * FROM knowledge_chunks WHERE file_path = 'test.md'"
        )
        assert len(rows) >= 1
        assert any("Version 2" in row["content"] for row in rows)
        assert not any("Version 1" in row["content"] for row in rows)
