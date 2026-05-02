"""Daemon CLI tests — service file generation + platform routing.

These tests don't install or remove anything on the host. We verify the
generated launchd plist / systemd unit content has the safety-critical
flags we promise (KeepAlive / Restart, log paths, working dir, env)
and that the platform router reports correctly on the current host.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cli.daemon_cmd import (
    _LAUNCHD_LABEL,
    _SYSTEMD_UNIT,
    _build_launchd_plist,
    _build_systemd_unit,
    _platform,
)


class TestPlatformDetection:
    def test_macos_detected_on_darwin(self) -> None:
        with patch("platform.system", return_value="Darwin"):
            assert _platform() == "macos"

    def test_linux_detected(self) -> None:
        with patch("platform.system", return_value="Linux"):
            assert _platform() == "linux"

    def test_unsupported_for_windows(self) -> None:
        with patch("platform.system", return_value="Windows"):
            assert _platform() == "unsupported"


class TestLaunchdPlist:
    @pytest.fixture
    def plist(self, tmp_path: Path) -> str:
        return _build_launchd_plist(
            python="/usr/local/bin/python3",
            project_root=tmp_path / "elophanto",
            log_dir=tmp_path / "logs",
        )

    def test_includes_correct_label(self, plist: str) -> None:
        assert f"<string>{_LAUNCHD_LABEL}</string>" in plist

    def test_invokes_gateway_module(self, plist: str) -> None:
        assert "<string>cli.gateway_cmd</string>" in plist
        assert "<string>--no-cli</string>" in plist

    def test_keep_alive_on_crash(self, plist: str) -> None:
        """Daemon must auto-restart on crash but not loop on clean exits."""
        # KeepAlive dict with Crashed=true + SuccessfulExit=false is the
        # 'restart only on real failure' contract.
        assert "<key>KeepAlive</key>" in plist
        assert "<key>Crashed</key>" in plist
        assert "<key>SuccessfulExit</key>" in plist
        assert "<key>ThrottleInterval</key>" in plist

    def test_runs_at_load(self, plist: str) -> None:
        assert "<key>RunAtLoad</key>" in plist
        assert "<true/>" in plist

    def test_marks_daemon_env(self, plist: str) -> None:
        """Gateway uses ELOPHANTO_DAEMON=1 to switch to non-interactive
        vault unlock + keychain password lookup."""
        assert "<key>ELOPHANTO_DAEMON</key>" in plist
        assert "<string>1</string>" in plist

    def test_log_paths_are_absolute(self, plist: str, tmp_path: Path) -> None:
        out_log = tmp_path / "logs" / "daemon.out.log"
        err_log = tmp_path / "logs" / "daemon.err.log"
        assert str(out_log) in plist
        assert str(err_log) in plist


class TestSystemdUnit:
    @pytest.fixture
    def unit(self, tmp_path: Path) -> str:
        return _build_systemd_unit(
            python="/usr/bin/python3",
            project_root=tmp_path / "elophanto",
            log_dir=tmp_path / "logs",
        )

    def test_invokes_gateway_module(self, unit: str) -> None:
        assert "ExecStart=/usr/bin/python3 -m cli.gateway_cmd --no-cli" in unit

    def test_restarts_on_failure(self, unit: str) -> None:
        # The contract is "auto-recover from crashes, not from clean exits".
        # Restart=on-failure is exactly that — Restart=always would loop on
        # intentional shutdown.
        assert "Restart=on-failure" in unit
        assert "RestartSec=" in unit

    def test_marks_daemon_env(self, unit: str) -> None:
        assert "Environment=ELOPHANTO_DAEMON=1" in unit

    def test_target_default(self, unit: str) -> None:
        # default.target is the user-session target — correct for a user
        # service that should auto-start at login but NOT at boot before login.
        assert "WantedBy=default.target" in unit

    def test_unit_filename_constant(self) -> None:
        assert _SYSTEMD_UNIT.endswith(".service")
