"""Tests for storage quota enforcement in core/storage.py."""

from __future__ import annotations

from pathlib import Path

from core.config import StorageConfig
from core.storage import StorageManager


def _make_manager(
    tmp_path: Path,
    quota_mb: int = 2000,
    alert_pct: float = 80.0,
    max_file_mb: int = 100,
) -> StorageManager:
    config = StorageConfig(
        data_dir=str(tmp_path),
        workspace_quota_mb=quota_mb,
        alert_threshold_pct=alert_pct,
        max_file_size_mb=max_file_mb,
    )
    return StorageManager(config, project_root=tmp_path.parent)


class TestCheckQuota:
    def test_empty_directory(self, tmp_path: Path) -> None:
        """Empty directory should report 0 usage, ok status."""
        mgr = _make_manager(tmp_path)
        used, quota, status = mgr.check_quota()
        assert used == 0.0
        assert quota == 2000.0
        assert status == "ok"

    def test_under_threshold(self, tmp_path: Path) -> None:
        """Usage under alert threshold should report ok."""
        # Create 1MB of data (well under 2000MB quota)
        data_file = tmp_path / "test.bin"
        data_file.write_bytes(b"\0" * (1024 * 1024))
        mgr = _make_manager(tmp_path)
        used, quota, status = mgr.check_quota()
        assert status == "ok"
        assert used > 0

    def test_warning_threshold(self, tmp_path: Path) -> None:
        """Usage at 80%+ of quota should report warning."""
        # Use a tiny quota so we can easily exceed the threshold
        data_file = tmp_path / "test.bin"
        data_file.write_bytes(b"\0" * (900 * 1024))  # ~900KB
        mgr = _make_manager(tmp_path, quota_mb=1)  # 1MB quota
        used, quota, status = mgr.check_quota()
        assert status == "warning"

    def test_exceeded_threshold(self, tmp_path: Path) -> None:
        """Usage at 100%+ of quota should report exceeded."""
        data_file = tmp_path / "test.bin"
        data_file.write_bytes(b"\0" * (1100 * 1024))  # ~1.1MB
        mgr = _make_manager(tmp_path, quota_mb=1)  # 1MB quota
        used, quota, status = mgr.check_quota()
        assert status == "exceeded"

    def test_disabled_quota(self, tmp_path: Path) -> None:
        """Quota of 0 should disable checking."""
        data_file = tmp_path / "test.bin"
        data_file.write_bytes(b"\0" * (1024 * 1024))
        mgr = _make_manager(tmp_path, quota_mb=0)
        used, quota, status = mgr.check_quota()
        assert status == "ok"
        assert used == 0.0

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        """Nonexistent base dir should report 0 usage."""
        config = StorageConfig(
            data_dir=str(tmp_path / "nonexistent"),
            workspace_quota_mb=2000,
        )
        mgr = StorageManager(config, project_root=tmp_path)
        used, quota, status = mgr.check_quota()
        assert used == 0.0
        assert status == "ok"


class TestValidateWrite:
    def test_valid_write(self, tmp_path: Path) -> None:
        """Small write under quota should be allowed."""
        mgr = _make_manager(tmp_path)
        allowed, msg = mgr.validate_write(1024)
        assert allowed is True
        assert msg == "ok"

    def test_file_too_large(self, tmp_path: Path) -> None:
        """Write exceeding max_file_size_mb should be rejected."""
        mgr = _make_manager(tmp_path, max_file_mb=1)
        allowed, msg = mgr.validate_write(2 * 1024 * 1024)
        assert allowed is False
        assert "max size" in msg

    def test_quota_exceeded(self, tmp_path: Path) -> None:
        """Write when quota exceeded should be rejected."""
        data_file = tmp_path / "test.bin"
        data_file.write_bytes(b"\0" * (1100 * 1024))  # 1.1MB
        mgr = _make_manager(tmp_path, quota_mb=1, max_file_mb=100)
        allowed, msg = mgr.validate_write(1024)
        assert allowed is False
        assert "quota exceeded" in msg.lower()
