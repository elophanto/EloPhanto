"""Storage manager — structured data/ directory for all persistent and temporary data.

Manages file uploads, downloads, document collections, caches, and exports.
Handles directory creation on startup and retention-based cleanup.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from pathlib import Path

from core.config import StorageConfig

logger = logging.getLogger(__name__)

# Subdirectories under data/
_DIRS = [
    "downloads",
    "documents/uploads",
    "documents/collections",
    "cache/embeddings",
    "cache/ocr",
    "exports",
]


class StorageManager:
    """Manages the data/ directory structure, file staging, and retention cleanup."""

    def __init__(self, config: StorageConfig, project_root: Path) -> None:
        self._config = config
        base = Path(config.data_dir)
        self._base = base if base.is_absolute() else project_root / base

    @property
    def base_dir(self) -> Path:
        return self._base

    async def initialize(self) -> None:
        """Create all data/ subdirectories. Called during agent.initialize()."""
        def _create_dirs() -> None:
            for subdir in _DIRS:
                (self._base / subdir).mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(_create_dirs)
        logger.info("Storage initialized at %s", self._base)

    def get_upload_path(self, session_id: str, filename: str) -> Path:
        """Return a unique path for a document upload."""
        safe_name = _safe_filename(filename)
        session_dir = self._base / "documents" / "uploads" / (session_id or "global")
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir / f"{uuid.uuid4().hex[:12]}_{safe_name}"

    def get_download_path(self, session_id: str, filename: str) -> Path:
        """Return a unique path for a general download."""
        safe_name = _safe_filename(filename)
        session_dir = self._base / "downloads" / (session_id or "global")
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir / f"{uuid.uuid4().hex[:12]}_{safe_name}"

    def get_collection_dir(self, collection_id: str) -> Path:
        """Return the directory for a document collection."""
        cdir = self._base / "documents" / "collections" / collection_id
        cdir.mkdir(parents=True, exist_ok=True)
        return cdir

    def validate_file_size(self, size_bytes: int) -> bool:
        """Check against max_file_size_mb."""
        max_bytes = self._config.max_file_size_mb * 1024 * 1024
        return size_bytes <= max_bytes

    async def cleanup_expired(self) -> dict[str, int]:
        """Remove files exceeding retention. Returns counts per category."""
        return await asyncio.to_thread(self._cleanup_sync)

    def _cleanup_sync(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        now = time.time()

        # Clean downloads
        counts["downloads"] = _clean_old_files(
            self._base / "downloads",
            now,
            self._config.download_retention_hours * 3600,
        )

        # Clean document uploads
        counts["uploads"] = _clean_old_files(
            self._base / "documents" / "uploads",
            now,
            self._config.upload_retention_hours * 3600,
        )

        # Clean cache by total size
        cache_dir = self._base / "cache"
        if cache_dir.exists():
            counts["cache"] = _clean_cache_lru(
                cache_dir, self._config.cache_max_mb * 1024 * 1024
            )

        if any(v > 0 for v in counts.values()):
            logger.info("Storage cleanup: %s", counts)
        return counts


def _safe_filename(filename: str) -> str:
    """Sanitize filename — keep only safe characters."""
    safe = "".join(c if c.isalnum() or c in ".-_" else "_" for c in filename)
    return safe[:200] or "unnamed"


def _clean_old_files(directory: Path, now: float, max_age_seconds: float) -> int:
    """Recursively remove files older than max_age_seconds. Remove empty dirs."""
    if not directory.exists():
        return 0
    count = 0
    for root, _dirs, files in os.walk(directory, topdown=False):
        root_path = Path(root)
        for f in files:
            fp = root_path / f
            try:
                if now - fp.stat().st_mtime > max_age_seconds:
                    fp.unlink()
                    count += 1
            except OSError:
                pass
        # Remove empty directories
        try:
            if root_path != directory and not any(root_path.iterdir()):
                root_path.rmdir()
        except OSError:
            pass
    return count


def _clean_cache_lru(directory: Path, max_bytes: int) -> int:
    """Remove oldest files until total size is under max_bytes."""
    files: list[tuple[Path, float, int]] = []
    for root, _, filenames in os.walk(directory):
        root_path = Path(root)
        for f in filenames:
            fp = root_path / f
            try:
                st = fp.stat()
                files.append((fp, st.st_mtime, st.st_size))
            except OSError:
                pass

    total = sum(s for _, _, s in files)
    if total <= max_bytes:
        return 0

    # Sort by mtime ascending (oldest first)
    files.sort(key=lambda x: x[1])
    count = 0
    for fp, _, size in files:
        if total <= max_bytes:
            break
        try:
            fp.unlink()
            total -= size
            count += 1
        except OSError:
            pass
    return count
