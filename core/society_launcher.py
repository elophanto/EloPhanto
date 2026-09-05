"""Open the Society in an independent, non-automated browser process.

The agent's browser bridge owns its Playwright browser/context. Society uses
another user-data directory and exposes no debugging endpoint, so browser_close,
tab cleanup and bridge restarts cannot touch its window. Never route this through
webbrowser.open: it can reuse the very profile the agent is operating.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


def _browser_executables(system: str) -> list[str]:
    """Find installed Chromium browsers without consulting the default browser."""
    candidates: list[Path] = []
    names: tuple[str, ...] = ()
    if system == "Darwin":
        for applications in (Path("/Applications"), Path.home() / "Applications"):
            for app, executable in (
                ("Google Chrome", "Google Chrome"),
                ("Chromium", "Chromium"),
                ("Microsoft Edge", "Microsoft Edge"),
                ("Brave Browser", "Brave Browser"),
            ):
                candidates.append(applications / f"{app}.app" / "Contents" / "MacOS" / executable)
    elif system == "Windows":
        for variable in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            directory = os.environ.get(variable)
            if directory:
                for relative in (
                    "Google/Chrome/Application/chrome.exe",
                    "Microsoft/Edge/Application/msedge.exe",
                    "BraveSoftware/Brave-Browser/Application/brave.exe",
                    "Chromium/Application/chrome.exe",
                ):
                    candidates.append(Path(directory) / relative)
        names = ("chrome.exe", "msedge.exe", "brave.exe", "chromium.exe")
    elif system == "Linux":
        names = (
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
            "microsoft-edge",
            "microsoft-edge-stable",
            "brave-browser",
        )

    found = [str(path) for path in candidates if path.is_file()]
    for name in names:
        if found_executable := shutil.which(name):
            found.append(found_executable)
    return list(dict.fromkeys(found))


def open_society_window(url: str, project_root: Path) -> bool:
    """Launch an isolated app window, returning False if no window can be opened.

    Call from a background thread: launch detection can take a fraction of a
    second per browser. The Society HTTP service remains useful when automatic
    opening is unavailable (for example on an SSH-only server).
    """
    try:
        target = urlsplit(url)
        if target.scheme != "http" or target.hostname not in {"127.0.0.1", "localhost", "::1"}:
            logger.warning("Society window requires a local HTTP URL: %s", url)
            return False

        system = platform.system()
        if system == "Linux" and not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        ):
            logger.info("No desktop display available. Society is ready at %s", url)
            return False

        executables = _browser_executables(system)
        if not executables:
            logger.warning(
                "No Chromium browser found for Society. Install Chrome, Chromium, Edge "
                "or Brave to open an isolated window. Society is ready at %s",
                url,
            )
            return False

        root = Path(project_root).resolve()
        profile = root / ".society-browser"
        if profile.is_symlink():
            logger.warning("Society profile must be its own directory, not a symlink: %s", profile)
            return False
        profile.mkdir(mode=0o700, parents=True, exist_ok=True)

        flags = [
            f"--user-data-dir={profile}",
            f"--app={url}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-mode",
            "--window-size=1512,982",
            "--class=elophanto-society",
        ]
        options: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "cwd": str(root),
            "close_fds": True,
        }
        if system == "Windows":
            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: do not inherit CLI
            # console lifetime or Ctrl+C. Numeric values are stable Win32 flags.
            options["creationflags"] = 0x00000008 | 0x00000200
        else:
            options["start_new_session"] = True

        for executable in executables:
            try:
                process = subprocess.Popen([executable, *flags], **options)
                try:
                    code = process.wait(timeout=0.35)
                except subprocess.TimeoutExpired:
                    code = 0  # The independent browser process is running.
                if code == 0:
                    # Zero also covers handing a new window to a previous
                    # Society instance with the SAME isolated profile.
                    logger.info("Society opened in its independent window: %s", url)
                    return True
                logger.debug("Society browser %s exited with code %s", executable, code)
            except OSError as exc:
                logger.debug("Cannot launch Society with %s: %s", executable, exc)
    except (OSError, ValueError) as exc:
        logger.warning("Could not open Society window: %s. Society is ready at %s", exc, url)
        return False

    logger.warning("Could not open an isolated Society window. Society is ready at %s", url)
    return False
