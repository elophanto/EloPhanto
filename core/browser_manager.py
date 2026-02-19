"""Browser automation via Node.js bridge to BrowserPlugin (44 tools).

Spawns a Node.js subprocess that runs the full BrowserPlugin from
aware-agent.  Python communicates with it via JSON-RPC over stdin/stdout.

The bridge exposes all 44 browser tools (navigate, click_text,
read_semantic, full_audit, vision analysis, etc.) through a single
``call_tool(name, args)`` dispatch method.

Supports 4 connection modes:
1. fresh    — Launch a clean Chrome instance (default)
2. cdp_port — Connect to existing Chrome via CDP port (preserves sessions)
3. cdp_ws   — Connect to existing Chrome via WebSocket endpoint
4. profile  — Launch a second Chrome with your profile (cookies/sessions preserved)
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

from core.node_bridge import NodeBridge

logger = logging.getLogger(__name__)

_BRIDGE_SCRIPT = (
    Path(__file__).resolve().parent.parent / "bridge" / "browser" / "dist" / "server.js"
)


# ------------------------------------------------------------------
# Chrome profile utilities (used by init wizard & tests)
# ------------------------------------------------------------------


def get_default_chrome_user_data_dir() -> str | None:
    """Detect the default Chrome user data directory for the current platform."""
    home = Path.home()
    system = platform.system()

    if system == "Darwin":
        p = home / "Library" / "Application Support" / "Google" / "Chrome"
    elif system == "Windows":
        local = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
        p = Path(local) / "Google" / "Chrome" / "User Data"
    elif system == "Linux":
        p = home / ".config" / "google-chrome"
    else:
        return None

    return str(p) if p.exists() else None


def get_chrome_profiles() -> list[dict[str, str]]:
    """Detect all Chrome profiles with their display names and emails.

    Returns a list of dicts with 'directory', 'name', and 'email'
    for each profile found.
    """
    chrome_dir = get_default_chrome_user_data_dir()
    if not chrome_dir:
        return []

    profiles: list[dict[str, str]] = []
    chrome_path = Path(chrome_dir)
    for entry in sorted(chrome_path.iterdir()):
        prefs = entry / "Preferences"
        if not prefs.exists():
            continue
        if entry.name in ("System Profile", "Guest Profile"):
            continue
        try:
            data = json.loads(prefs.read_text(encoding="utf-8"))
            name = data.get("profile", {}).get("name", entry.name)
            account_info = data.get("account_info", [])
            email = account_info[0].get("email", "") if account_info else ""
            profiles.append(
                {
                    "directory": entry.name,
                    "name": name,
                    "email": email,
                }
            )
        except Exception:
            pass
    return profiles


_PROFILE_COPY_DIR = Path(tempfile.gettempdir()) / "elophanto-chrome-profile"
_PROFILE_COPY_META = ".elophanto_profile_meta.json"

_LOCK_NAMES = frozenset(
    [
        "SingletonLock",
        "SingletonCookie",
        "SingletonSocket",
        "RunningChromeVersion",
        "lockfile",
    ]
)


def _remove_lock_files(dir_path: Path) -> None:
    """Remove Chrome lock files so a copied profile can launch cleanly."""
    try:
        for item in dir_path.iterdir():
            try:
                if item.name in _LOCK_NAMES or "lock" in item.name.lower():
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                elif item.is_dir() and item.name == "Default":
                    _remove_lock_files(item)
            except OSError:
                pass
    except OSError:
        pass


def _clean_crash_state(profile_dir: Path, suppress_restore: bool = True) -> None:
    """Mark the profile as cleanly exited so Chrome skips restore prompts.

    If suppress_restore is True, also prevents Chrome from reopening old tabs.
    """
    prefs_file = profile_dir / "Preferences"
    if not prefs_file.exists():
        return
    try:
        data = json.loads(prefs_file.read_text(encoding="utf-8"))
        data.setdefault("profile", {})["exit_type"] = "Normal"
        data["profile"]["exited_cleanly"] = True
        if suppress_restore:
            data.setdefault("session", {})[
                "restore_on_startup"
            ] = 5  # 5 = open new tab page
            data["session"].pop("startup_urls", None)
        prefs_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


_SESSION_FILES = frozenset(
    [
        "Current Session",
        "Current Tabs",
        "Last Session",
        "Last Tabs",
    ]
)


def _remove_session_files(profile_dir: Path) -> None:
    """Delete Chrome session restore files so old tabs don't reopen.

    Covers both the legacy per-file format (Current Session, etc.) and the
    newer ``Sessions/`` directory that Chrome 100+ uses.
    """
    for name in _SESSION_FILES:
        f = profile_dir / name
        if f.exists():
            try:
                f.unlink()
                logger.debug("Removed session file: %s", f)
            except OSError:
                pass

    sessions_dir = profile_dir / "Sessions"
    if sessions_dir.is_dir():
        try:
            shutil.rmtree(sessions_dir, ignore_errors=True)
            logger.debug("Removed Sessions directory: %s", sessions_dir)
        except OSError:
            pass


_SKIP_PROFILE_DIRS = frozenset(
    [
        "Service Worker",
        "Cache",
        "Code Cache",
        "GPUCache",
        "DawnWebGPUCache",
        "GrShaderCache",
        "ShaderCache",
        "GraphiteDawnCache",
        "blob_storage",
        "File System",
        "Shared Dictionary",
    ]
)


def _is_context_closed_error(error_text: str) -> bool:
    """Detect common Playwright/browser-closed runtime errors."""
    text = (error_text or "").lower()
    return (
        "target page, context or browser has been closed" in text
        or "browsercontext.newpage" in text
        and "closed" in text
        or "browser has been closed" in text
    )


def _cookie_count(db_path: Path) -> int:
    """Return cookie row count from a Chrome Cookies sqlite DB.

    Returns -1 if unreadable or missing.
    """
    if not db_path.exists():
        return -1
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT COUNT(*) FROM cookies").fetchone()
            return int(row[0]) if row else -1
        finally:
            conn.close()
    except Exception:
        return -1


def _profile_cookie_count(user_data_root: Path, profile_directory: str) -> int:
    """Get cookie count for a specific Chrome profile directory."""
    return _cookie_count(user_data_root / profile_directory / "Cookies")


def _read_profile_copy_meta(dest: Path) -> dict[str, Any] | None:
    """Read profile copy metadata, if present."""
    meta_file = dest / _PROFILE_COPY_META
    if not meta_file.exists():
        return None
    try:
        raw = json.loads(meta_file.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return None


def _write_profile_copy_meta(dest: Path, source: str, profile_directory: str) -> None:
    """Write profile copy metadata for deterministic reuse."""
    meta_file = dest / _PROFILE_COPY_META
    data = {
        "source": source,
        "profile_directory": profile_directory,
        "updated_at": int(time.time()),
    }
    try:
        meta_file.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        # Metadata is best-effort only.
        pass


def _get_profile_directories(user_data_root: Path) -> list[str]:
    """List available profile directories (Default, Profile N, etc.)."""
    out: list[str] = []
    try:
        for entry in sorted(user_data_root.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name in ("System Profile", "Guest Profile"):
                continue
            if entry.name == "Default" or entry.name.startswith("Profile "):
                if (entry / "Preferences").exists():
                    out.append(entry.name)
    except Exception:
        return []
    return out


def _format_profile_cookie_stats(source_root: Path) -> str:
    """Format available profile cookie counts for diagnostics."""
    parts: list[str] = []
    for name in _get_profile_directories(source_root):
        parts.append(f"{name}={_profile_cookie_count(source_root, name)}")
    return ", ".join(parts) if parts else "(no profiles detected)"


def _prepare_launch_profile(source: str, selected_profile: str) -> tuple[str, str]:
    """Prepare profile copy with strict, deterministic profile selection."""
    Path(source)
    prepared = _prepare_profile_copy(source, selected_profile)

    logger.info(
        "Profile prepared: selected=%s copy_path=%s",
        selected_profile,
        prepared,
    )

    return prepared, selected_profile


def _prepare_profile_copy(
    source: str,
    profile_directory: str = "Default",
    *,
    force_refresh: bool = False,
) -> str:
    """Copy a Chrome profile to a temp directory for the browser bridge.

    On **first** call the profile is fully copied (skipping caches).  On
    subsequent calls the existing copy is **reused** — this keeps login
    cookies alive and avoids re-copying multi-GB profiles.  Pass
    *force_refresh=True* (or delete the temp dir) to force a fresh copy.

    Args:
        source: Chrome user data directory
                (e.g. ~/Library/Application Support/Google/Chrome).
        profile_directory: Profile subdirectory to copy
                          (e.g. "Default", "Profile 1").  Placed as
                          "Default" in the temp dir.
        force_refresh: Delete the existing copy and re-copy from source.
    """
    src = Path(source)
    dest = _PROFILE_COPY_DIR

    needs_copy = force_refresh or not dest.exists()
    if not needs_copy and dest.exists():
        meta = _read_profile_copy_meta(dest)
        if not meta:
            # One-time deterministic refresh after upgrade from older versions.
            logger.info(
                "Profile copy metadata missing — refreshing copy for profile '%s'.",
                profile_directory,
            )
            needs_copy = True
        else:
            prev_source = str(meta.get("source", ""))
            prev_profile = str(meta.get("profile_directory", ""))
            if prev_source != source or prev_profile != profile_directory:
                logger.info(
                    "Profile copy provenance mismatch (prev_source=%s, prev_profile=%s); "
                    "refreshing for source=%s profile=%s",
                    prev_source,
                    prev_profile,
                    source,
                    profile_directory,
                )
                needs_copy = True

    if needs_copy and dest.exists():
        shutil.rmtree(dest, ignore_errors=True)

    if needs_copy:
        t0 = time.time()
        logger.info("Copying Chrome profile '%s'...", profile_directory)
        dest.mkdir(parents=True, exist_ok=True)

        for item in src.iterdir():
            if item.is_file():
                try:
                    shutil.copy2(str(item), str(dest / item.name))
                except OSError:
                    pass

        src_profile = src / profile_directory
        dst_default = dest / "Default"
        if src_profile.is_dir():

            def _ignore_caches(directory: str, contents: list[str]) -> list[str]:
                """Skip cache directories at the profile root level only."""
                if Path(directory) == src_profile:
                    return [c for c in contents if c in _SKIP_PROFILE_DIRS]
                return []

            shutil.copytree(
                str(src_profile),
                str(dst_default),
                ignore=_ignore_caches,
                dirs_exist_ok=True,
            )
        else:
            logger.warning(
                "Profile directory '%s' not found in %s", profile_directory, src
            )

        elapsed = time.time() - t0
        logger.info("Profile copied to %s (%.1fs)", dest, elapsed)
    else:
        logger.info("Reusing existing profile copy at %s", dest)

    _remove_lock_files(dest)
    _clean_crash_state(dest / "Default")
    _remove_session_files(dest / "Default")
    _write_profile_copy_meta(dest, source, profile_directory)
    return str(dest)


# ------------------------------------------------------------------
# BrowserManager — thin bridge client
# ------------------------------------------------------------------


class BrowserManager:
    """Manages browser automation via Node.js bridge to BrowserPlugin.

    All 44 browser tools are accessed through a single ``call_tool(name, args)``
    method. The bridge handles tool dispatch on the Node.js side.
    """

    def __init__(
        self,
        mode: str = "fresh",
        headless: bool = False,
        cdp_port: int = 9222,
        cdp_ws_endpoint: str = "",
        user_data_dir: str = "",
        profile_directory: str = "Default",
        use_system_chrome: bool = True,
        viewport_width: int = 1280,
        viewport_height: int = 720,
        **kwargs: Any,
    ) -> None:
        self._mode = mode
        self._headless = headless
        self._cdp_port = cdp_port
        self._cdp_ws_endpoint = cdp_ws_endpoint
        self._user_data_dir = user_data_dir
        self._profile_directory = profile_directory
        self._use_system_chrome = use_system_chrome
        self._viewport = {"width": viewport_width, "height": viewport_height}

        self._bridge = NodeBridge(
            str(_BRIDGE_SCRIPT),
            cwd=str(_BRIDGE_SCRIPT.parent.parent),
        )
        self._initialized = False
        self._tool_list: list[dict[str, Any]] = []
        self._active_profile_path: str | None = None
        self._active_profile_name: str | None = None
        self._active_source_path: str | None = None
        self._prefs_backup: str | None = None

    @classmethod
    def from_config(cls, config: Any) -> BrowserManager:
        """Create from a BrowserConfig dataclass."""
        return cls(
            mode=getattr(config, "mode", "fresh"),
            headless=getattr(config, "headless", False),
            cdp_port=getattr(config, "cdp_port", 9222),
            cdp_ws_endpoint=getattr(config, "cdp_ws_endpoint", ""),
            user_data_dir=getattr(config, "user_data_dir", ""),
            profile_directory=getattr(config, "profile_directory", "Default"),
            use_system_chrome=getattr(config, "use_system_chrome", True),
            viewport_width=getattr(config, "viewport_width", 1280),
            viewport_height=getattr(config, "viewport_height", 720),
        )

    @property
    def is_ready(self) -> bool:
        return self._initialized and self._bridge.is_alive

    @property
    def mode(self) -> str:
        return self._mode

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Start the Node.js bridge and initialize the browser."""
        if self._initialized and self._bridge.is_alive:
            return

        await self._bridge.start()

        bridge_mode = self._mode
        if self._mode in ("profile", "direct"):
            bridge_mode = "chrome_profile"
        elif self._mode in ("cdp_port", "cdp_ws"):
            bridge_mode = "cdp"

        config: dict[str, Any] = {
            "mode": bridge_mode,
            "headless": self._headless,
            "viewport": self._viewport,
            "useSystemChrome": self._use_system_chrome,
        }

        if self._mode == "cdp_ws":
            config["cdpWsEndpoint"] = self._cdp_ws_endpoint
            self._active_profile_path = None
            self._active_profile_name = None
            self._active_source_path = None
        elif self._mode == "cdp_port":
            config["cdpPort"] = self._cdp_port
            self._active_profile_path = None
            self._active_profile_name = None
            self._active_source_path = None
        elif self._mode == "direct":
            # Use the REAL Chrome profile directly — no copy, real cookies.
            # Chrome must be closed first (can't share profile with running instance).
            source = self._user_data_dir or get_default_chrome_user_data_dir()
            if source:
                source_root = Path(source)
                profile_dir = source_root / self._profile_directory
                if not profile_dir.exists():
                    logger.warning(
                        "Profile directory '%s' not found in %s, falling back to Default",
                        self._profile_directory,
                        source,
                    )
                    self._profile_directory = "Default"
                    profile_dir = source_root / self._profile_directory

                # Back up Preferences so we can restore the user's session
                # restore settings after the agent closes
                prefs_file = profile_dir / "Preferences"
                self._prefs_backup = None
                if prefs_file.exists():
                    try:
                        self._prefs_backup = prefs_file.read_text(encoding="utf-8")
                    except Exception:
                        pass

                # Prepare the profile for automation
                _remove_lock_files(source_root)
                _remove_lock_files(profile_dir)
                _clean_crash_state(profile_dir, suppress_restore=True)
                _remove_session_files(profile_dir)

                config["userDataDir"] = source
                config["copyProfile"] = False
                self._active_profile_path = source
                self._active_profile_name = self._profile_directory
                self._active_source_path = source
                logger.info(
                    "Using REAL Chrome profile '%s' at %s (direct mode — full cookies)",
                    self._profile_directory,
                    source,
                )
            else:
                logger.warning("No Chrome profile found, falling back to fresh mode")
                config["copyProfile"] = False
                self._active_profile_path = None
                self._active_profile_name = None
                self._active_source_path = None
        elif self._mode == "profile":
            source = self._user_data_dir or get_default_chrome_user_data_dir()
            if source:
                profile_path, effective_profile = _prepare_launch_profile(
                    source, self._profile_directory
                )
                config["userDataDir"] = profile_path
                config["copyProfile"] = False
                self._active_profile_path = profile_path
                self._active_profile_name = effective_profile
                self._active_source_path = source
                logger.info(
                    "Prepared browser profile '%s' at %s",
                    effective_profile,
                    profile_path,
                )
            else:
                config["copyProfile"] = True
                self._active_profile_path = None
                self._active_profile_name = None
                self._active_source_path = None
        else:
            self._active_profile_path = None
            self._active_profile_name = None
            self._active_source_path = None

        result = await self._bridge.call("initialize", config)
        self._initialized = True
        tool_count = result.get("toolCount", 0) if isinstance(result, dict) else 0
        logger.info(
            "Browser initialized via bridge (mode=%s, tools=%d)",
            self._mode,
            tool_count,
        )

    async def close(self) -> None:
        """Close the browser and stop the bridge."""
        try:
            if self._bridge.is_alive:
                await self._bridge.call("close")
        except Exception as e:
            logger.debug("Bridge close error: %s", e)
        finally:
            await self._bridge.stop()
            self._initialized = False

            # Restore original Preferences so the user's Chrome opens normally
            if self._mode == "direct" and getattr(self, "_prefs_backup", None):
                try:
                    source = self._active_source_path
                    profile = self._active_profile_name or "Default"
                    if source:
                        prefs_file = Path(source) / profile / "Preferences"
                        prefs_file.write_text(self._prefs_backup, encoding="utf-8")
                        logger.info("Restored original Chrome Preferences")
                except Exception as e:
                    logger.warning(f"Failed to restore Preferences: {e}")

    # ------------------------------------------------------------------
    # Tool dispatch — single generic method for all 44 tools
    # ------------------------------------------------------------------

    async def call_tool(
        self, name: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Call any browser tool by name.

        This is the primary interface — all 44 browser tools are dispatched
        through this single method. The Node.js bridge handles routing to
        the correct tool implementation.

        Args:
            name: Tool name (e.g. 'browser_navigate', 'browser_click_text')
            args: Tool arguments dict

        Returns:
            Tool result dict from the bridge
        """
        await self._ensure_alive()
        payload = {"name": name, "args": args or {}}
        result = await self._bridge.call("call_tool", payload)
        parsed = result if isinstance(result, dict) else {"result": result}

        # Improve reliability and diagnostics for intermittent browser context crashes.
        if self._mode == "profile":
            error_text = str(parsed.get("error", ""))
            if error_text and _is_context_closed_error(error_text):
                source = self._active_source_path or self._user_data_dir
                source_count = -1
                copy_count = -1
                stats = "(source unknown)"
                selected = self._active_profile_name or self._profile_directory

                if source:
                    source_root = Path(source)
                    source_count = _profile_cookie_count(source_root, selected)
                    stats = _format_profile_cookie_stats(source_root)
                if self._active_profile_path:
                    copy_count = _cookie_count(
                        Path(self._active_profile_path) / "Default" / "Cookies"
                    )

                logger.error(
                    "Profile runtime error on tool '%s': %s "
                    "(selected=%s, source_cookies=%d, copy_cookies=%d, copy_path=%s)",
                    name,
                    error_text,
                    selected,
                    source_count,
                    copy_count,
                    self._active_profile_path,
                )

                # Deterministic hard failure if cookie store collapsed after launch.
                if source_count >= 100 and 0 <= copy_count < max(
                    20, source_count // 10
                ):
                    return {
                        "success": False,
                        "error": (
                            "Copied Chrome profile became unusable after launch "
                            f"(profile={selected}, source_cookies={source_count}, "
                            f"copy_cookies={copy_count}). "
                            f"Available profile cookie counts: {stats}. "
                            "This often indicates Chrome rejected cookie decryption for "
                            "the copied profile on this machine. "
                            "Try a different browser.profile_directory, or switch to "
                            "cdp_port mode with Chrome started using "
                            "--remote-debugging-port=9222."
                        ),
                    }

                # Transient crash: restart bridge/browser once and retry once.
                logger.warning(
                    "Browser context closed unexpectedly for tool '%s'; "
                    "restarting bridge and retrying once.",
                    name,
                )
                try:
                    await self.close()
                    await self.initialize()
                    retry = await self._bridge.call("call_tool", payload)
                    return retry if isinstance(retry, dict) else {"result": retry}
                except Exception as retry_error:
                    return {
                        "success": False,
                        "error": (
                            f"{error_text} (retry after bridge restart failed: "
                            f"{retry_error})"
                        ),
                    }

        return parsed

    async def list_tools(self) -> list[dict[str, Any]]:
        """Get the list of all available browser tools with schemas.

        Returns:
            List of tool dicts with 'name', 'description', 'parameters'
        """
        await self._ensure_alive()
        result = await self._bridge.call("list_tools", {})
        if isinstance(result, dict) and "tools" in result:
            self._tool_list = result["tools"]
            return self._tool_list
        return []

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _ensure_alive(self) -> None:
        """Ensure the bridge is running, reinitializing if needed."""
        if not self._bridge.is_alive:
            self._initialized = False
            await self.initialize()
