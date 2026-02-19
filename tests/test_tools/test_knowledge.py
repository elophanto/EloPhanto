"""Knowledge tools tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.database import Database
from core.embeddings import EmbeddingClient, EmbeddingResult
from core.indexer import KnowledgeIndexer
from tools.base import PermissionLevel
from tools.knowledge.index_tool import KnowledgeIndexTool
from tools.knowledge.search import KnowledgeSearchTool
from tools.knowledge.writer import KnowledgeWriteTool


def _make_mock_embedder() -> EmbeddingClient:
    embedder = EmbeddingClient.__new__(EmbeddingClient)

    async def fake_embed(text: str, model: str = "nomic-embed-text") -> EmbeddingResult:
        import hashlib

        h = hashlib.md5(text.encode()).hexdigest()
        vec = [int(c, 16) / 15.0 for c in h] * 48
        return EmbeddingResult(vector=vec[:768], model=model, dimensions=768)

    embedder.embed = fake_embed
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


class TestKnowledgeSearchTool:
    def test_interface(self) -> None:
        tool = KnowledgeSearchTool()
        assert tool.name == "knowledge_search"
        assert tool.permission_level == PermissionLevel.SAFE
        assert "query" in tool.input_schema["properties"]
        schema = tool.to_llm_schema()
        assert schema["type"] == "function"

    @pytest.mark.asyncio
    async def test_search_not_initialized(self) -> None:
        tool = KnowledgeSearchTool()
        result = await tool.execute({"query": "test"})
        assert not result.success
        assert "not initialized" in result.error

    @pytest.mark.asyncio
    async def test_keyword_search(self, db: Database, knowledge_dir: Path) -> None:
        """Keyword search finds chunks by content match."""
        tool = KnowledgeSearchTool()
        tool._db = db
        tool._embedder = None  # Force keyword fallback

        # Insert test chunks directly
        await db.execute_insert(
            "INSERT INTO knowledge_chunks "
            "(file_path, heading_path, content, tags, scope, "
            "token_count, file_updated_at, indexed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "caps.md",
                "Tools",
                "shell_execute runs shell commands",
                '["tools"]',
                "system",
                10,
                "2026-01-01",
                "2026-01-01",
            ),
        )
        await db.execute_insert(
            "INSERT INTO knowledge_chunks "
            "(file_path, heading_path, content, tags, scope, "
            "token_count, file_updated_at, indexed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "arch.md",
                "Design",
                "The agent uses a plan-execute loop",
                '["architecture"]',
                "system",
                10,
                "2026-01-01",
                "2026-01-01",
            ),
        )

        result = await tool.execute({"query": "shell commands"})
        assert result.success
        assert result.data["count"] >= 1
        assert "shell" in result.data["results"][0]["content"].lower()

    @pytest.mark.asyncio
    async def test_scope_filter(self, db: Database) -> None:
        """Scope filter limits results."""
        tool = KnowledgeSearchTool()
        tool._db = db
        tool._embedder = None

        await db.execute_insert(
            "INSERT INTO knowledge_chunks "
            "(file_path, heading_path, content, tags, scope, "
            "token_count, file_updated_at, indexed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "sys.md",
                "H",
                "system content about tools",
                "[]",
                "system",
                10,
                "2026-01-01",
                "2026-01-01",
            ),
        )
        await db.execute_insert(
            "INSERT INTO knowledge_chunks "
            "(file_path, heading_path, content, tags, scope, "
            "token_count, file_updated_at, indexed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "usr.md",
                "H",
                "user content about tools",
                "[]",
                "user",
                10,
                "2026-01-01",
                "2026-01-01",
            ),
        )

        result = await tool.execute({"query": "tools", "scope": "system"})
        assert result.success
        assert all(r["scope"] == "system" for r in result.data["results"])


class TestKnowledgeWriteTool:
    def test_interface(self) -> None:
        tool = KnowledgeWriteTool()
        assert tool.name == "knowledge_write"
        assert tool.permission_level == PermissionLevel.MODERATE
        assert "path" in tool.input_schema["properties"]

    @pytest.mark.asyncio
    async def test_write_creates_file(self, knowledge_dir: Path) -> None:
        """Writing creates a file with frontmatter."""
        tool = KnowledgeWriteTool()
        tool._knowledge_dir = knowledge_dir

        result = await tool.execute(
            {
                "path": "learned/test-doc.md",
                "content": "# Test\n\nSome content.",
                "title": "Test Document",
                "tags": "test, example",
                "scope": "learned",
            }
        )

        assert result.success
        file_path = knowledge_dir / "learned" / "test-doc.md"
        assert file_path.exists()

        content = file_path.read_text()
        assert "---" in content
        assert "Test Document" in content
        assert "test, example" in content
        assert "Some content" in content

    @pytest.mark.asyncio
    async def test_write_preserves_created(self, knowledge_dir: Path) -> None:
        """Updating a file preserves the original created date."""
        tool = KnowledgeWriteTool()
        tool._knowledge_dir = knowledge_dir

        await tool.execute(
            {
                "path": "test.md",
                "content": "V1",
                "title": "Test",
            }
        )

        # Read original created date
        content1 = (knowledge_dir / "test.md").read_text()
        assert "created:" in content1

        await tool.execute(
            {
                "path": "test.md",
                "content": "V2",
                "title": "Test Updated",
            }
        )

        content2 = (knowledge_dir / "test.md").read_text()
        assert "V2" in content2
        assert "created:" in content2

    @pytest.mark.asyncio
    async def test_write_not_configured(self) -> None:
        tool = KnowledgeWriteTool()
        result = await tool.execute({"path": "test.md", "content": "Hi"})
        assert not result.success


class TestKnowledgeIndexTool:
    def test_interface(self) -> None:
        tool = KnowledgeIndexTool()
        assert tool.name == "knowledge_index"
        assert tool.permission_level == PermissionLevel.SAFE

    @pytest.mark.asyncio
    async def test_index_not_initialized(self) -> None:
        tool = KnowledgeIndexTool()
        result = await tool.execute({})
        assert not result.success

    @pytest.mark.asyncio
    async def test_incremental_index(self, db: Database, knowledge_dir: Path) -> None:
        """Index tool delegates to indexer."""
        indexer = KnowledgeIndexer(
            db=db,
            embedder=_make_mock_embedder(),
            knowledge_dir=knowledge_dir,
        )
        (knowledge_dir / "test.md").write_text(
            "---\ntitle: Test\n---\n\n## Section\n\nContent."
        )

        tool = KnowledgeIndexTool()
        tool._indexer = indexer

        result = await tool.execute({"full": False})
        assert result.success
        assert result.data["files_indexed"] >= 1
        assert result.data["mode"] == "incremental"
