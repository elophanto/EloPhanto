"""Tests for the browser manager (Node.js bridge client)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.browser_manager import (
    _PROFILE_COPY_META,
    _SESSION_FILES,
    BrowserManager,
    _clean_crash_state,
    _prepare_profile_copy,
    _remove_lock_files,
    get_chrome_profiles,
    get_default_chrome_user_data_dir,
)


class TestBrowserManager:
    def test_init_defaults(self) -> None:
        mgr = BrowserManager()
        assert mgr.mode == "fresh"
        assert mgr.is_ready is False
        assert mgr._headless is False
        assert mgr._use_system_chrome is True
        assert mgr._viewport == {"width": 1280, "height": 720}

    def test_init_cdp_port_mode(self) -> None:
        mgr = BrowserManager(mode="cdp_port", cdp_port=9333)
        assert mgr.mode == "cdp_port"
        assert mgr._cdp_port == 9333

    def test_init_cdp_ws_mode(self) -> None:
        mgr = BrowserManager(
            mode="cdp_ws", cdp_ws_endpoint="ws://localhost:9222/devtools"
        )
        assert mgr.mode == "cdp_ws"
        assert mgr._cdp_ws_endpoint == "ws://localhost:9222/devtools"

    def test_init_profile_mode(self) -> None:
        mgr = BrowserManager(mode="profile", user_data_dir="/tmp/chrome-profile")
        assert mgr.mode == "profile"
        assert mgr._user_data_dir == "/tmp/chrome-profile"
        assert mgr._profile_directory == "Default"

    def test_init_profile_directory(self) -> None:
        mgr = BrowserManager(
            mode="profile", user_data_dir="/tmp/chrome", profile_directory="Profile 1"
        )
        assert mgr._profile_directory == "Profile 1"

    def test_init_headless(self) -> None:
        mgr = BrowserManager(headless=True)
        assert mgr._headless is True

    def test_init_custom_viewport(self) -> None:
        mgr = BrowserManager(viewport_width=1920, viewport_height=1080)
        assert mgr._viewport == {"width": 1920, "height": 1080}

    def test_is_ready_before_init(self) -> None:
        mgr = BrowserManager()
        assert mgr.is_ready is False

    @pytest.mark.asyncio
    async def test_close_without_init(self) -> None:
        mgr = BrowserManager()
        await mgr.close()  # Should not raise
        assert mgr.is_ready is False

    def test_from_config(self) -> None:
        class MockConfig:
            mode = "cdp_port"
            headless = True
            cdp_port = 8888
            cdp_ws_endpoint = ""
            user_data_dir = ""
            use_system_chrome = False
            viewport_width = 800
            viewport_height = 600

        mgr = BrowserManager.from_config(MockConfig())
        assert mgr.mode == "cdp_port"
        assert mgr._headless is True
        assert mgr._cdp_port == 8888
        assert mgr._use_system_chrome is False
        assert mgr._viewport == {"width": 800, "height": 600}

    def test_has_call_tool_method(self) -> None:
        mgr = BrowserManager()
        assert hasattr(mgr, "call_tool")

    def test_has_list_tools_method(self) -> None:
        mgr = BrowserManager()
        assert hasattr(mgr, "list_tools")


class TestProfileCopy:
    """Tests for Chrome profile copying and lock file removal."""

    def test_remove_lock_files(self, tmp_path: Path) -> None:
        """Lock files are removed from profile directory."""
        (tmp_path / "SingletonLock").touch()
        (tmp_path / "SingletonCookie").touch()
        (tmp_path / "SingletonSocket").touch()
        (tmp_path / "RunningChromeVersion").touch()
        (tmp_path / "lockfile").touch()
        (tmp_path / "some.lock").touch()
        (tmp_path / "Preferences").touch()
        default = tmp_path / "Default"
        default.mkdir()
        (default / "SingletonLock").touch()
        (default / "data.json").touch()

        _remove_lock_files(tmp_path)

        assert not (tmp_path / "SingletonLock").exists()
        assert not (tmp_path / "SingletonCookie").exists()
        assert not (tmp_path / "SingletonSocket").exists()
        assert not (tmp_path / "RunningChromeVersion").exists()
        assert not (tmp_path / "lockfile").exists()
        assert not (tmp_path / "some.lock").exists()
        assert (tmp_path / "Preferences").exists()
        assert not (default / "SingletonLock").exists()
        assert (default / "data.json").exists()

    def test_prepare_profile_full_copy_skips_caches(self, tmp_path: Path) -> None:
        """Full profile is copied but cache directories are skipped."""
        source = tmp_path / "chrome-profile"
        source.mkdir()
        (source / "Local State").write_text('{"key": "val"}')
        (source / "SingletonLock").touch()

        default = source / "Default"
        default.mkdir()
        (default / "Cookies").write_text("cookie-data")
        (default / "Preferences").write_text('{"prefs": true}')
        (default / "Login Data").write_text("logins")
        ext = default / "Extensions"
        ext.mkdir()
        (ext / "abc123").mkdir()
        (ext / "abc123" / "manifest.json").write_text('{"name": "ext"}')
        local_storage = default / "Local Storage"
        local_storage.mkdir()
        (local_storage / "leveldb").mkdir()
        (local_storage / "leveldb" / "000001.log").write_text("ls-data")
        for skip_dir in ["Cache", "Service Worker", "Code Cache", "GPUCache"]:
            d = default / skip_dir
            d.mkdir()
            (d / "data_0").write_text("cache data")

        with patch("core.browser_manager._PROFILE_COPY_DIR", tmp_path / "copy"):
            result = _prepare_profile_copy(str(source))

        dest = Path(result)
        assert dest.exists()
        assert (dest / "Local State").read_text() == '{"key": "val"}'
        assert (dest / "Default" / "Cookies").read_text() == "cookie-data"
        assert (dest / "Default" / "Login Data").read_text() == "logins"
        assert (dest / "Default" / "Extensions" / "abc123" / "manifest.json").exists()
        assert (dest / "Default" / "Local Storage" / "leveldb" / "000001.log").exists()
        import json

        prefs = json.loads((dest / "Default" / "Preferences").read_text())
        assert prefs["prefs"] is True
        assert prefs["profile"]["exit_type"] == "Normal"
        assert prefs["profile"]["exited_cleanly"] is True
        assert not (dest / "Default" / "Cache").exists()
        assert not (dest / "Default" / "Service Worker").exists()
        assert not (dest / "Default" / "Code Cache").exists()
        assert not (dest / "Default" / "GPUCache").exists()
        assert not (dest / "SingletonLock").exists()

    def test_session_files_removed(self, tmp_path: Path) -> None:
        """Session restore files are deleted so old tabs don't reopen."""
        source = tmp_path / "chrome-profile"
        source.mkdir()
        default = source / "Default"
        default.mkdir()
        (default / "Cookies").write_text("cookies")
        (default / "Preferences").write_text("{}")
        for sf in _SESSION_FILES:
            (default / sf).write_bytes(b"\x00session-data")

        with patch("core.browser_manager._PROFILE_COPY_DIR", tmp_path / "copy"):
            result = _prepare_profile_copy(str(source))

        dest = Path(result)
        for sf in _SESSION_FILES:
            assert not (dest / "Default" / sf).exists(), f"{sf} should be deleted"
        assert (dest / "Default" / "Cookies").exists()

    def test_prepare_profile_reuses_existing_copy(self, tmp_path: Path) -> None:
        """Existing copy is reused (not re-copied)."""
        source = tmp_path / "chrome-profile"
        source.mkdir()
        default = source / "Default"
        default.mkdir()
        (default / "Cookies").write_text("fresh-cookies")

        copy_dir = tmp_path / "copy"
        copy_dir.mkdir()
        copy_default = copy_dir / "Default"
        copy_default.mkdir()
        (copy_default / "Cookies").write_text("existing-cookies")
        (copy_default / "Preferences").write_text("{}")
        (copy_dir / _PROFILE_COPY_META).write_text(
            json.dumps(
                {
                    "source": str(source),
                    "profile_directory": "Default",
                    "updated_at": 0,
                }
            )
        )

        with patch("core.browser_manager._PROFILE_COPY_DIR", copy_dir):
            result = _prepare_profile_copy(str(source))

        assert (Path(result) / "Default" / "Cookies").read_text() == "existing-cookies"

    def test_prepare_profile_force_refresh(self, tmp_path: Path) -> None:
        """force_refresh=True re-copies from source."""
        source = tmp_path / "chrome-profile"
        source.mkdir()
        default = source / "Default"
        default.mkdir()
        (default / "Cookies").write_text("fresh-cookies")
        (default / "Preferences").write_text("{}")

        copy_dir = tmp_path / "copy"
        copy_dir.mkdir()
        copy_default = copy_dir / "Default"
        copy_default.mkdir()
        (copy_default / "Cookies").write_text("stale-cookies")

        with patch("core.browser_manager._PROFILE_COPY_DIR", copy_dir):
            result = _prepare_profile_copy(str(source), force_refresh=True)

        assert (Path(result) / "Default" / "Cookies").read_text() == "fresh-cookies"

    def test_sessions_directory_removed(self, tmp_path: Path) -> None:
        """Sessions/ directory is cleaned from copied profile."""
        source = tmp_path / "chrome-profile"
        source.mkdir()
        default = source / "Default"
        default.mkdir()
        (default / "Preferences").write_text("{}")
        sessions = default / "Sessions"
        sessions.mkdir()
        (sessions / "Session_123").write_bytes(b"session-data")

        with patch("core.browser_manager._PROFILE_COPY_DIR", tmp_path / "copy"):
            result = _prepare_profile_copy(str(source))

        assert not (Path(result) / "Default" / "Sessions").exists()

    def test_prepare_profile_custom_directory(self, tmp_path: Path) -> None:
        """Copies the selected profile subdir as 'Default' in the temp copy."""
        source = tmp_path / "chrome-data"
        source.mkdir()
        (source / "Local State").write_text('{"key": "val"}')

        profile1 = source / "Profile 1"
        profile1.mkdir()
        (profile1 / "Cookies").write_text("profile1-cookies")
        (profile1 / "Preferences").write_text('{"prefs": 1}')

        default = source / "Default"
        default.mkdir()
        (default / "Cookies").write_text("default-cookies")

        with patch("core.browser_manager._PROFILE_COPY_DIR", tmp_path / "copy"):
            result = _prepare_profile_copy(str(source), "Profile 1")

        dest = Path(result)
        assert (dest / "Default" / "Cookies").read_text() == "profile1-cookies"
        assert not (dest / "Profile 1").exists()


class TestGetChromeProfiles:
    """Tests for multi-profile detection."""

    def test_returns_list(self, tmp_path: Path) -> None:
        import json

        (tmp_path / "Default").mkdir()
        (tmp_path / "Default" / "Preferences").write_text(
            json.dumps(
                {
                    "profile": {"name": "Main"},
                    "account_info": [{"email": "main@example.com"}],
                }
            )
        )
        (tmp_path / "Profile 1").mkdir()
        (tmp_path / "Profile 1" / "Preferences").write_text(
            json.dumps({"profile": {"name": "Work"}})
        )
        (tmp_path / "System Profile").mkdir()
        (tmp_path / "System Profile" / "Preferences").write_text(
            json.dumps({"profile": {"name": "System"}})
        )

        with patch(
            "core.browser_manager.get_default_chrome_user_data_dir",
            return_value=str(tmp_path),
        ):
            profiles = get_chrome_profiles()

        assert len(profiles) == 2
        names = {p["name"] for p in profiles}
        assert "Main" in names
        assert "Work" in names
        by_name = {p["name"]: p for p in profiles}
        assert by_name["Main"]["email"] == "main@example.com"
        assert by_name["Work"]["email"] == ""

    def test_returns_empty_no_chrome(self) -> None:
        with patch(
            "core.browser_manager.get_default_chrome_user_data_dir", return_value=None
        ):
            profiles = get_chrome_profiles()
        assert profiles == []


class TestCrashStateCleanup:
    def test_cleans_exit_type(self, tmp_path: Path) -> None:
        import json

        prefs = {"profile": {"exit_type": "Crashed", "exited_cleanly": False}}
        (tmp_path / "Preferences").write_text(json.dumps(prefs))

        _clean_crash_state(tmp_path)

        result = json.loads((tmp_path / "Preferences").read_text())
        assert result["profile"]["exit_type"] == "Normal"
        assert result["profile"]["exited_cleanly"] is True

    def test_disables_session_restore(self, tmp_path: Path) -> None:
        import json

        prefs = {
            "session": {"restore_on_startup": 1, "startup_urls": ["https://x.com"]}
        }
        (tmp_path / "Preferences").write_text(json.dumps(prefs))

        _clean_crash_state(tmp_path)

        result = json.loads((tmp_path / "Preferences").read_text())
        assert result["session"]["restore_on_startup"] == 4
        assert "startup_urls" not in result["session"]

    def test_handles_missing_prefs(self, tmp_path: Path) -> None:
        _clean_crash_state(tmp_path)  # Should not raise


class TestGetDefaultChromeUserDataDir:
    def test_returns_string_or_none(self) -> None:
        result = get_default_chrome_user_data_dir()
        assert result is None or isinstance(result, str)

    def test_platform_aware(self) -> None:
        result = get_default_chrome_user_data_dir()
        if result:
            assert len(result) > 0
