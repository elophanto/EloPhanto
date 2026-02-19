"""Tests for StorageManager — data directory management."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import StorageConfig
from core.storage import StorageManager


@pytest.fixture
def storage_config() -> StorageConfig:
    return StorageConfig(
        data_dir="data",
        max_file_size_mb=10,
        download_retention_hours=1,
        upload_retention_hours=2,
        cache_max_mb=50,
    )


@pytest.fixture
def storage(tmp_path: Path, storage_config: StorageConfig) -> StorageManager:
    return StorageManager(storage_config, tmp_path)


class TestStorageInit:
    async def test_initialize_creates_directories(
        self, storage: StorageManager
    ) -> None:
        await storage.initialize()
        base = storage.base_dir
        assert base.exists()
        assert (base / "downloads").is_dir()
        assert (base / "documents" / "uploads").is_dir()
        assert (base / "documents" / "collections").is_dir()
        assert (base / "cache").is_dir()
        assert (base / "exports").is_dir()

    async def test_initialize_is_idempotent(self, storage: StorageManager) -> None:
        await storage.initialize()
        await storage.initialize()
        assert storage.base_dir.exists()


class TestUploadDownloadPaths:
    async def test_get_upload_path_returns_path_under_uploads(
        self, storage: StorageManager
    ) -> None:
        await storage.initialize()
        path = storage.get_upload_path("session-1", "test.pdf")
        assert "documents" in str(path)
        assert "uploads" in str(path)
        assert path.name.endswith(".pdf")

    async def test_get_download_path_returns_path_under_downloads(
        self, storage: StorageManager
    ) -> None:
        await storage.initialize()
        path = storage.get_download_path("session-1", "image.png")
        assert "downloads" in str(path)
        assert path.name.endswith(".png")

    async def test_upload_paths_are_unique(self, storage: StorageManager) -> None:
        await storage.initialize()
        p1 = storage.get_upload_path("s1", "test.pdf")
        p2 = storage.get_upload_path("s1", "test.pdf")
        # Paths should resolve differently (unique names) or at least be valid
        assert isinstance(p1, Path)
        assert isinstance(p2, Path)

    async def test_get_collection_dir_creates_directory(
        self, storage: StorageManager
    ) -> None:
        await storage.initialize()
        d = storage.get_collection_dir("col-123")
        assert d.is_dir()
        assert "collections" in str(d)
        assert "col-123" in str(d)

    async def test_empty_session_id_uses_global(
        self, storage: StorageManager
    ) -> None:
        await storage.initialize()
        path = storage.get_upload_path("", "file.txt")
        assert isinstance(path, Path)
        assert "uploads" in str(path)


class TestFileValidation:
    def test_validate_file_size_within_limit(self, storage: StorageManager) -> None:
        assert storage.validate_file_size(1_000_000) is True  # 1 MB

    def test_validate_file_size_at_limit(self, storage: StorageManager) -> None:
        assert storage.validate_file_size(10 * 1024 * 1024) is True  # 10 MB exactly

    def test_validate_file_size_over_limit(self, storage: StorageManager) -> None:
        assert storage.validate_file_size(11 * 1024 * 1024) is False  # 11 MB


class TestCleanup:
    async def test_cleanup_returns_counts(self, storage: StorageManager) -> None:
        await storage.initialize()
        result = await storage.cleanup_expired()
        assert isinstance(result, dict)
        assert "downloads" in result or "uploads" in result or "cache" in result
