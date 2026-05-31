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

    @pytest.mark.asyncio
    async def test_zero_result_triggers_rewrite_retry(
        self, db: Database, knowledge_dir: Path
    ) -> None:
        """When the first search returns 0, the router is asked to
        rewrite and the search retries with the new query."""
        tool = KnowledgeSearchTool()
        tool._db = db
        tool._embedder = None

        await db.execute_insert(
            "INSERT INTO knowledge_chunks "
            "(file_path, heading_path, content, tags, scope, "
            "token_count, file_updated_at, indexed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "x_lessons.md",
                "Lessons",
                "recent X originals about pumpfun updates cadence dedupe",
                '["x","lessons"]',
                "learned",
                10,
                "2026-01-01",
                "2026-01-01",
            ),
        )

        # Stub router whose .complete returns a topic-keyword rewrite
        class _StubResp:
            def __init__(self, text: str) -> None:
                self.content = text

        class _StubRouter:
            def __init__(self) -> None:
                self.calls: list[str] = []

            async def complete(self, *, messages, **_):
                self.calls.append(messages[-1]["content"])
                return _StubResp("pumpfun updates cadence dedupe X originals")

        stub = _StubRouter()
        tool._router = stub

        # Imperative query with no word overlap with any indexed chunk —
        # must miss on first pass so the rewrite path fires.
        original = "ship the thing already please"
        result = await tool.execute({"query": original})
        assert result.success
        assert result.data["count"] >= 1
        assert len(stub.calls) == 1  # rewrite called exactly once
        assert result.data.get("query_rewritten_from") == original
        assert "pumpfun" in result.data["query_used"]

    @pytest.mark.asyncio
    async def test_rewrite_failure_returns_original_empty(self, db: Database) -> None:
        """If the rewrite call raises or returns empty, the tool falls back
        to the original empty result — never crashes the loop."""
        tool = KnowledgeSearchTool()
        tool._db = db
        tool._embedder = None

        class _BrokenRouter:
            async def complete(self, **_):
                raise RuntimeError("provider down")

        tool._router = _BrokenRouter()

        result = await tool.execute(
            {"query": "do a post on something the kb has nothing about"}
        )
        assert result.success
        assert result.data["count"] == 0
        # No rewrite metadata when retry failed/skipped
        assert "query_rewritten_from" not in result.data

    @pytest.mark.asyncio
    async def test_no_router_means_no_rewrite(self, db: Database) -> None:
        """Legacy callers without a router get the pre-rewrite behaviour."""
        tool = KnowledgeSearchTool()
        tool._db = db
        tool._embedder = None
        # _router stays None

        result = await tool.execute({"query": "do a post on nothing"})
        assert result.success
        assert result.data["count"] == 0
        assert "query_rewritten_from" not in result.data

    @pytest.mark.asyncio
    async def test_semantic_empty_falls_through_to_keyword(self, db: Database) -> None:
        """When semantic returns [] cleanly (not via exception), keyword
        fallback must still run. Reproduces the production miss where
        the KB had matching chunks but the search returned 0 because
        the embedder hiccup never raised — just returned nothing."""
        tool = KnowledgeSearchTool()
        tool._db = db

        await db.execute_insert(
            "INSERT INTO knowledge_chunks "
            "(file_path, heading_path, content, tags, scope, "
            "token_count, file_updated_at, indexed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "k.md",
                "H",
                "commune_post usage and recent posting history",
                "[]",
                "learned",
                10,
                "2026-01-01",
                "2026-01-01",
            ),
        )

        # Stub embedder + db.vec_available True, but force _semantic_search to
        # return empty cleanly (the bug pattern). Easiest way: override the
        # method on this instance.
        class _StubEmbedder:
            async def embed(self, *_, **__):
                raise AssertionError("should not be reached — patched below")

        tool._embedder = _StubEmbedder()

        # Force the "semantic returns empty list" branch
        async def _empty_semantic(*_, **__):
            return []

        tool._semantic_search = _empty_semantic  # type: ignore[method-assign]

        # vec_available may be False in test DB; patch _db.vec_available proxy
        # via a small shim if needed. Most tests use a real Database fixture
        # where vec_available reflects sqlite-vec presence. We force-True
        # here so the semantic branch is entered.
        class _DBShim:
            vec_available = True

            def __getattr__(self, name):
                return getattr(db, name)

        tool._db = _DBShim()

        result = await tool.execute({"query": "commune_post posting history"})
        assert result.success
        assert result.data["count"] >= 1
        assert result.data["search_type"] == "keyword"
        # The keyword fallback actually ran and found the seeded chunk
        assert "commune_post" in result.data["results"][0]["content"]

    @pytest.mark.asyncio
    async def test_rewrite_not_attempted_when_first_search_has_hits(
        self, db: Database
    ) -> None:
        """Healthy searches must not pay the LLM tax."""
        tool = KnowledgeSearchTool()
        tool._db = db
        tool._embedder = None

        await db.execute_insert(
            "INSERT INTO knowledge_chunks "
            "(file_path, heading_path, content, tags, scope, "
            "token_count, file_updated_at, indexed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "f.md",
                "H",
                "shell commands quick reference",
                "[]",
                "system",
                10,
                "2026-01-01",
                "2026-01-01",
            ),
        )

        class _SpyRouter:
            def __init__(self) -> None:
                self.calls = 0

            async def complete(self, **_):
                self.calls += 1
                raise AssertionError("should not be called")

        spy = _SpyRouter()
        tool._router = spy

        result = await tool.execute({"query": "shell commands"})
        assert result.success
        assert result.data["count"] >= 1
        assert spy.calls == 0


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
