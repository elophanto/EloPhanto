"""Exit criteria tests for Phase 1.

Tests that the knowledge system can:
1. Answer "What tools do you have?" by finding capabilities.md
2. Store and retrieve task memory
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from core.database import Database
from core.embeddings import EmbeddingClient, EmbeddingResult
from core.indexer import KnowledgeIndexer
from core.memory import MemoryManager
from tools.knowledge.search import KnowledgeSearchTool


def _make_mock_embedder() -> EmbeddingClient:
    embedder = EmbeddingClient.__new__(EmbeddingClient)

    async def fake_embed(text: str, model: str = "nomic-embed-text") -> EmbeddingResult:
        h = hashlib.md5(text.encode()).hexdigest()
        vec = [int(c, 16) / 15.0 for c in h] * 48
        return EmbeddingResult(vector=vec[:768], model=model, dimensions=768)

    embedder.embed = fake_embed
    return embedder


KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "knowledge"


class TestExitCriteria:
    @pytest.mark.asyncio
    async def test_find_capabilities(self, tmp_path: Path) -> None:
        """Indexing capabilities.md and searching 'What tools do you have?'
        returns relevant results."""
        db = Database(tmp_path / "test.db")
        await db.initialize()
        await db.create_vec_table(768)

        embedder = _make_mock_embedder()
        indexer = KnowledgeIndexer(
            db=db, embedder=embedder, knowledge_dir=KNOWLEDGE_DIR
        )

        # Index just the capabilities file
        caps_file = KNOWLEDGE_DIR / "system" / "capabilities.md"
        assert caps_file.exists(), "capabilities.md must exist"
        await indexer.index_file(caps_file)

        # Search for it
        tool = KnowledgeSearchTool()
        tool._db = db
        tool._embedder = embedder

        result = await tool.execute({"query": "What tools do you have?"})
        assert result.success
        assert result.data["count"] >= 1

        # At least one result should contain tool names
        all_content = " ".join(r["content"] for r in result.data["results"])
        assert "shell_execute" in all_content or "knowledge_search" in all_content

        await db.close()

    @pytest.mark.asyncio
    async def test_recall_past_task(self, tmp_path: Path) -> None:
        """Storing a task and searching for it works."""
        db = Database(tmp_path / "test.db")
        await db.initialize()

        mgr = MemoryManager(db)
        await mgr.store_task_memory(
            session_id="s1",
            goal="list all Python files in home directory",
            summary="Found 47 Python files using file_list tool",
            outcome="completed",
            tools_used=["file_list"],
        )

        results = await mgr.search_memory("Python files")
        assert len(results) >= 1
        assert "Python" in results[0]["goal"]

        await db.close()
