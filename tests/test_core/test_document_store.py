"""Tests for DocumentStore — collection CRUD, chunk storage, query."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.config import DocumentConfig, StorageConfig
from core.database import Database
from core.document_processor import DocumentChunk
from core.document_store import DocumentStore
from core.storage import StorageManager


@pytest.fixture
def doc_config() -> DocumentConfig:
    return DocumentConfig(
        enabled=True,
        context_threshold_tokens=8000,
        chunk_size_tokens=512,
        chunk_overlap_tokens=100,
        retrieval_top_k=5,
    )


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(str(tmp_path / "test.db"))
    await database.initialize()
    return database


@pytest.fixture
def mock_embedder() -> MagicMock:
    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=[0.1] * 384)
    return embedder


@pytest.fixture
async def storage(tmp_path: Path) -> StorageManager:
    config = StorageConfig(data_dir="data", max_file_size_mb=10)
    sm = StorageManager(config, tmp_path)
    await sm.initialize()
    return sm


@pytest.fixture
async def store(
    db: Database,
    mock_embedder: MagicMock,
    storage: StorageManager,
    doc_config: DocumentConfig,
) -> DocumentStore:
    return DocumentStore(
        db=db,
        embedder=mock_embedder,
        embedding_model="test-model",
        storage=storage,
        config=doc_config,
    )


# ─── Collection CRUD ───


class TestCollectionCRUD:
    async def test_create_collection(self, store: DocumentStore) -> None:
        cid = await store.create_collection("My Docs")
        assert isinstance(cid, str)
        assert len(cid) > 0

    async def test_list_collections_empty(self, store: DocumentStore) -> None:
        result = await store.list_collections()
        assert isinstance(result, list)
        assert len(result) == 0

    async def test_list_collections_after_create(self, store: DocumentStore) -> None:
        await store.create_collection("Test Collection")
        result = await store.list_collections()
        assert len(result) == 1
        assert result[0]["name"] == "Test Collection"

    async def test_get_collection_info(self, store: DocumentStore) -> None:
        cid = await store.create_collection("Info Test")
        info = await store.get_collection_info(cid)
        assert info is not None
        assert info["name"] == "Info Test"

    async def test_get_collection_info_by_name(self, store: DocumentStore) -> None:
        await store.create_collection("Named Collection")
        info = await store.get_collection_info("Named Collection")
        assert info is not None

    async def test_get_collection_info_not_found(self, store: DocumentStore) -> None:
        info = await store.get_collection_info("nonexistent")
        assert info is None

    async def test_delete_collection(self, store: DocumentStore) -> None:
        cid = await store.create_collection("To Delete")
        deleted = await store.delete_collection(cid)
        assert deleted is True
        result = await store.list_collections()
        assert len(result) == 0

    async def test_delete_nonexistent_collection(self, store: DocumentStore) -> None:
        deleted = await store.delete_collection("no-such-id")
        assert deleted is False


# ─── File + Chunk Storage ───


class TestAddFile:
    async def test_add_file_with_chunks(
        self, store: DocumentStore, tmp_path: Path
    ) -> None:
        cid = await store.create_collection("File Test")
        f = tmp_path / "test.txt"
        f.write_text("Hello world")

        chunks = [
            DocumentChunk(
                content="Hello world",
                chunk_index=0,
                token_count=3,
                page_number=1,
            )
        ]
        file_id = await store.add_file(
            collection_id=cid,
            file_path=f,
            filename="test.txt",
            mime_type="text/plain",
            page_count=1,
            chunks=chunks,
        )
        assert isinstance(file_id, str)

        # Collection should now have updated counts
        info = await store.get_collection_info(cid)
        assert info is not None
        assert info["file_count"] == 1
        assert info["chunk_count"] == 1


# ─── Query ───


class TestQuery:
    async def test_keyword_query_fallback(
        self, store: DocumentStore, tmp_path: Path
    ) -> None:
        cid = await store.create_collection("Query Test")
        f = tmp_path / "doc.txt"
        f.write_text("Python is great for data science")

        chunks = [
            DocumentChunk(
                content="Python is great for data science",
                chunk_index=0,
                token_count=8,
                page_number=1,
            )
        ]
        await store.add_file(
            collection_id=cid,
            file_path=f,
            filename="doc.txt",
            mime_type="text/plain",
            page_count=1,
            chunks=chunks,
        )

        results = await store.query(cid, "Python data science")
        assert isinstance(results, list)
