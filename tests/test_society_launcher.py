"""Society must never share browser lifetime or a profile with the agent."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from core import society_launcher

URL = "http://127.0.0.1:18790/society/"


@pytest.fixture
def launcher(monkeypatch):
    monkeypatch.setattr(society_launcher.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(society_launcher, "_browser_executables", lambda _: ["/browser"])
    process = Mock()
    process.wait.side_effect = subprocess.TimeoutExpired("browser", 0.35)
    launch = Mock(return_value=process)
    monkeypatch.setattr(society_launcher.subprocess, "Popen", launch)
    return launch


def test_launch_is_isolated_from_agent_browser(tmp_path, launcher):
    assert society_launcher.open_society_window(URL, tmp_path)
    args, options = launcher.call_args
    assert f"--user-data-dir={tmp_path / '.society-browser'}" in args[0]
    assert f"--app={URL}" in args[0]
    assert not any("remote-debugging" in flag for flag in args[0])
    assert options["start_new_session"] is True
    assert options["stdin"] == subprocess.DEVNULL
    assert options["stdout"] == subprocess.DEVNULL
    assert options["stderr"] == subprocess.DEVNULL


def test_windows_detaches_from_console(tmp_path, launcher, monkeypatch):
    monkeypatch.setattr(society_launcher.platform, "system", lambda: "Windows")
    assert society_launcher.open_society_window(URL, tmp_path)
    options = launcher.call_args.kwargs
    assert options["creationflags"] == 0x208
    assert "start_new_session" not in options


def test_missing_browser_keeps_service_available(tmp_path, launcher, monkeypatch, caplog):
    monkeypatch.setattr(society_launcher, "_browser_executables", lambda _: [])
    assert not society_launcher.open_society_window(URL, tmp_path)
    launcher.assert_not_called()
    assert URL in caplog.text


def test_browser_failure_does_not_crash_agent(tmp_path, launcher, caplog):
    launcher.side_effect = OSError("cannot execute browser")
    assert not society_launcher.open_society_window(URL, tmp_path)
    assert URL in caplog.text


def test_immediate_browser_failure_is_not_reported_as_success(tmp_path, launcher):
    launcher.return_value.wait.side_effect = None
    launcher.return_value.wait.return_value = 1
    assert not society_launcher.open_society_window(URL, tmp_path)


def test_reuses_only_own_profile_when_society_is_already_open(tmp_path, launcher):
    launcher.return_value.wait.side_effect = None
    launcher.return_value.wait.return_value = 0
    assert society_launcher.open_society_window(URL, tmp_path)
    assert f"--user-data-dir={tmp_path / '.society-browser'}" in launcher.call_args.args[0]


def test_symlink_cannot_redirect_to_agent_profile(tmp_path, launcher):
    other_profile = tmp_path / "agent-profile"
    other_profile.mkdir()
    (tmp_path / ".society-browser").symlink_to(other_profile, target_is_directory=True)
    assert not society_launcher.open_society_window(URL, tmp_path)
    launcher.assert_not_called()
    assert list(other_profile.iterdir()) == []


def test_ssh_session_does_not_attempt_browser(tmp_path, launcher, monkeypatch):
    monkeypatch.setattr(society_launcher.platform, "system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert not society_launcher.open_society_window(URL, tmp_path)
    launcher.assert_not_called()


@pytest.mark.parametrize(
    "url", ["https://example.com/", "file:///tmp/society", "javascript:alert(1)"]
)
def test_only_opens_local_service(tmp_path, launcher, url):
    assert not society_launcher.open_society_window(url, tmp_path)
    launcher.assert_not_called()


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX session isolation; Windows flags tested separately"
)
def test_window_survives_termination_of_launcher_process_group(tmp_path):
    """Exercise actual OS process isolation without opening Chrome or a live agent."""
    browser = tmp_path / "test-browser"
    marker = tmp_path / "browser.json"
    browser.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text(json.dumps({{'pid': os.getpid(), "
        "'group': os.getpgrp(), 'session': os.getsid(0), 'args': sys.argv[1:]}))\n"
        "time.sleep(30)\n"
    )
    browser.chmod(0o700)
    helper_code = (
        "import time\n"
        "from pathlib import Path\n"
        "from core import society_launcher\n"
        "society_launcher.platform.system = lambda: 'Darwin'\n"
        f"society_launcher._browser_executables = lambda _: [{str(browser)!r}]\n"
        f"assert society_launcher.open_society_window({URL!r}, Path({str(tmp_path)!r}))\n"
        "time.sleep(30)\n"
    )
    helper = subprocess.Popen(
        [sys.executable, "-c", helper_code],
        cwd=Path(__file__).resolve().parents[1],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    browser_pid = None
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline and helper.poll() is None:
            time.sleep(0.01)
        assert marker.exists(), "Isolated test browser did not start"
        details = json.loads(marker.read_text())
        browser_pid = details["pid"]
        assert details["session"] == browser_pid
        assert details["group"] == browser_pid
        assert details["group"] != helper.pid
        assert f"--user-data-dir={tmp_path / '.society-browser'}" in details["args"]
        assert not any("remote-debugging" in flag for flag in details["args"])
        # Terminal or launcher cleanup can signal its whole own process group;
        # the Society process remains in its separate session.
        os.killpg(helper.pid, signal.SIGTERM)
        helper.wait(timeout=3)
        os.kill(browser_pid, 0)
    finally:
        if helper.poll() is None:
            os.killpg(helper.pid, signal.SIGTERM)
            helper.wait(timeout=3)
        if browser_pid is not None:
            try:
                os.kill(browser_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if helper.stderr is not None:
            helper.stderr.close()
