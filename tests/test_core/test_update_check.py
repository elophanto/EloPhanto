"""Update check tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.update_check import (
    UpdateCheckResult,
    _is_behind,
    _parse_calver,
    check_for_updates,
    format_banner,
    get_local_version,
    mark_notified,
    should_notify,
)


class TestParseCalver:
    def test_basic(self) -> None:
        assert _parse_calver("v2026.05.07") == (2026, 5, 7, 0)

    def test_no_v_prefix(self) -> None:
        assert _parse_calver("2026.05.07") == (2026, 5, 7, 0)

    def test_with_patch(self) -> None:
        assert _parse_calver("v2026.02.24.3") == (2026, 2, 24, 3)

    def test_garbage_returns_none(self) -> None:
        assert _parse_calver("not-a-tag") is None
        assert _parse_calver("") is None
        assert _parse_calver("v1.2") is None


class TestIsBehind:
    def test_equal_not_behind(self) -> None:
        assert _is_behind("v2026.05.07", "v2026.05.07") is False

    def test_older_is_behind(self) -> None:
        assert _is_behind("v2026.05.02", "v2026.05.07") is True

    def test_newer_local_not_behind(self) -> None:
        assert _is_behind("v2026.05.09", "v2026.05.07") is False

    def test_patch_difference(self) -> None:
        assert _is_behind("v2026.02.24.1", "v2026.02.24.3") is True

    def test_month_rollover(self) -> None:
        assert _is_behind("v2026.04.30", "v2026.05.01") is True

    def test_garbage_falls_back_to_lex(self) -> None:
        # Both unparseable → lex compare
        assert _is_behind("foo", "goo") is True
        assert _is_behind("zoo", "alpha") is False

    def test_empty_handled(self) -> None:
        assert _is_behind("", "v2026.05.07") is False
        assert _is_behind("v2026.05.07", "") is False


class TestGetLocalVersion:
    def test_returns_something_in_repo(self) -> None:
        # Running inside the actual repo — should resolve via git or pyproject
        v = get_local_version()
        assert v != ""
        assert v.startswith("v")

    def test_empty_when_no_repo_or_pyproject(self, tmp_path: Path) -> None:
        v = get_local_version(project_root=tmp_path)
        assert v == ""

    def test_pyproject_fallback(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "2026.05.09"\n'
        )
        v = get_local_version(project_root=tmp_path)
        assert v == "v2026.05.09"


class TestFormatBanner:
    def test_up_to_date_returns_empty(self) -> None:
        r = UpdateCheckResult(local="v2026.05.07", latest="v2026.05.07", behind=False)
        assert format_banner(r) == ""

    def test_behind_renders_banner(self) -> None:
        r = UpdateCheckResult(
            local="v2026.05.02",
            latest="v2026.05.07",
            behind=True,
            release_url="https://github.com/elophanto/EloPhanto/releases/tag/v2026.05.07",
            release_title="v2026.05.07 — Affect layer",
        )
        text = format_banner(r)
        assert "v2026.05.02" in text
        assert "v2026.05.07" in text
        assert "Affect layer" in text
        assert "github.com" in text


class TestCheckForUpdates:
    @pytest.mark.asyncio
    async def test_disabled_returns_none(self) -> None:
        result = await check_for_updates(enabled=False)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_local_version_returns_none(self, tmp_path: Path) -> None:
        # tmp_path has neither .git nor pyproject.toml
        result = await check_for_updates(enabled=True, project_root=tmp_path)
        assert result is None

    @pytest.mark.asyncio
    async def test_uses_cache_when_fresh(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "2026.05.07"\n'
        )
        # Redirect cache to tmp_path
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cache_file = cache_dir / "update_check.json"
        monkeypatch.setattr("core.update_check._cache_path", lambda: cache_file)
        cache_file.write_text(
            json.dumps(
                {
                    "checked_at": 9_999_999_999,  # far future
                    "local": "v2026.05.07",
                    "latest": "v2026.05.07",
                    "behind": False,
                    "release_url": "",
                    "release_title": "",
                }
            )
        )

        async def _should_not_be_called() -> None:
            raise AssertionError("network call made despite fresh cache")

        with patch(
            "core.update_check.fetch_latest_release",
            side_effect=_should_not_be_called,
        ):
            result = await check_for_updates(enabled=True, project_root=tmp_path)
        assert result is not None
        assert result.behind is False
        assert result.latest == "v2026.05.07"

    @pytest.mark.asyncio
    async def test_writes_cache_on_fetch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "2026.05.02"\n'
        )
        cache_file = tmp_path / "cache.json"
        monkeypatch.setattr("core.update_check._cache_path", lambda: cache_file)

        async def _fake_fetch(timeout: float = 5.0) -> tuple[str, str, str]:
            return ("v2026.05.07", "https://example/r", "Big release")

        monkeypatch.setattr("core.update_check.fetch_latest_release", _fake_fetch)
        result = await check_for_updates(
            enabled=True, project_root=tmp_path, use_cache=False
        )
        assert result is not None
        assert result.behind is True
        assert result.latest == "v2026.05.07"
        assert cache_file.exists()
        data = json.loads(cache_file.read_text())
        assert data["local"] == "v2026.05.02"
        assert data["latest"] == "v2026.05.07"
        assert data["behind"] is True

    @pytest.mark.asyncio
    async def test_network_failure_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "2026.05.02"\n'
        )
        cache_file = tmp_path / "cache.json"
        monkeypatch.setattr("core.update_check._cache_path", lambda: cache_file)

        async def _fake_fetch(timeout: float = 5.0) -> None:
            return None

        monkeypatch.setattr("core.update_check.fetch_latest_release", _fake_fetch)
        result = await check_for_updates(
            enabled=True, project_root=tmp_path, use_cache=False
        )
        assert result is None


class TestNotifyOnce:
    def test_should_notify_when_behind_and_unseen(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "core.update_check._cache_path", lambda: tmp_path / "c.json"
        )
        r = UpdateCheckResult(local="v2026.05.02", latest="v2026.05.07", behind=True)
        assert should_notify(r) is True

    def test_should_not_notify_when_already_notified(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache = tmp_path / "c.json"
        monkeypatch.setattr("core.update_check._cache_path", lambda: cache)
        mark_notified("v2026.05.07")
        r = UpdateCheckResult(local="v2026.05.02", latest="v2026.05.07", behind=True)
        assert should_notify(r) is False

    def test_should_notify_again_when_new_version_arrives(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache = tmp_path / "c.json"
        monkeypatch.setattr("core.update_check._cache_path", lambda: cache)
        mark_notified("v2026.05.07")
        # A newer release than the one already notified about
        r = UpdateCheckResult(local="v2026.05.02", latest="v2026.05.09", behind=True)
        assert should_notify(r) is True

    def test_should_not_notify_when_up_to_date(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "core.update_check._cache_path", lambda: tmp_path / "c.json"
        )
        r = UpdateCheckResult(local="v2026.05.09", latest="v2026.05.09", behind=False)
        assert should_notify(r) is False

    def test_should_not_notify_when_none(self) -> None:
        assert should_notify(None) is False

    def test_check_preserves_last_notified_across_recheck(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Re-checking must not wipe last_notified — that's the dedup key
        the periodic notifier relies on."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "2026.05.02"\n'
        )
        cache = tmp_path / "c.json"
        monkeypatch.setattr("core.update_check._cache_path", lambda: cache)
        mark_notified("v2026.05.07")

        async def _fake_fetch(timeout: float = 5.0) -> tuple[str, str, str]:
            return ("v2026.05.07", "https://example/r", "title")

        monkeypatch.setattr("core.update_check.fetch_latest_release", _fake_fetch)
        await_result = check_for_updates(
            enabled=True, project_root=tmp_path, use_cache=False
        )
        import asyncio as _a

        _a.run(await_result)
        data = json.loads(cache.read_text())
        assert data["last_notified"] == "v2026.05.07"
