"""GitHub release update check.

Compares the local install version against the latest GitHub release of
elophanto/EloPhanto. Cached at ~/.elophanto/update_check.json so we hit
the GitHub API at most once per day. Surfaced as a one-line banner on
chat/gateway startup and a status line in `elophanto doctor`.

No telemetry sent — the only network call is an unauthenticated GET to
api.github.com/repos/elophanto/EloPhanto/releases/latest.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 24 * 60 * 60  # once per day
_REPO = "elophanto/EloPhanto"
_RELEASES_URL = f"https://api.github.com/repos/{_REPO}/releases/latest"
_REQUEST_TIMEOUT_SECONDS = 5.0
_CALVER_RE = re.compile(r"^v?(\d{4})\.(\d{2})\.(\d{2})(?:\.(\d+))?$")


@dataclass
class UpdateCheckResult:
    local: str
    latest: str
    behind: bool
    release_url: str = ""
    release_title: str = ""


def _parse_calver(tag: str) -> tuple[int, int, int, int] | None:
    """Parse ``v2026.05.07`` / ``2026.05.07.2`` / etc. into a sortable tuple.

    Returns None if the tag doesn't fit the calver shape — caller falls
    back to lex compare in that case.
    """
    m = _CALVER_RE.match(tag.strip())
    if not m:
        return None
    year, month, day, patch = m.groups()
    return (int(year), int(month), int(day), int(patch) if patch else 0)


def _is_behind(local: str, latest: str) -> bool:
    if not local or not latest:
        return False
    if local == latest:
        return False
    lp = _parse_calver(local)
    rp = _parse_calver(latest)
    if lp is not None and rp is not None:
        return lp < rp
    return local < latest  # lex fallback


def get_local_version(project_root: Path | None = None) -> str:
    """Resolve the local install version.

    Priority:
    1. ``git describe --tags --abbrev=0`` (covers git-clone installs).
    2. ``pyproject.toml`` ``version`` field (covers pip installs).
    3. Empty string if neither works.
    """
    root = project_root or Path(__file__).resolve().parent.parent

    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            tag = result.stdout.strip()
            if tag:
                return tag
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            version = data.get("project", {}).get("version", "")
            if version:
                return f"v{version}" if not version.startswith("v") else version
        except Exception:
            pass

    return ""


def _cache_path() -> Path:
    return Path.home() / ".elophanto" / "update_check.json"


def _read_cache() -> dict | None:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        if time.time() - data.get("checked_at", 0) > _CACHE_TTL_SECONDS:
            return None
        return data
    except Exception:
        return None


def _write_cache(payload: dict) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


async def fetch_latest_release(
    timeout: float = _REQUEST_TIMEOUT_SECONDS,
) -> tuple[str, str, str] | None:
    """Hit the GitHub releases/latest endpoint.

    Returns ``(tag_name, html_url, name)`` or None on any failure.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(
                _RELEASES_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "elophanto-update-check",
                },
            )
            if r.status_code != 200:
                return None
            data = r.json()
            tag = data.get("tag_name", "")
            url = data.get("html_url", "")
            name = data.get("name", "")
            if not tag:
                return None
            return (tag, url, name)
    except Exception:
        return None


async def check_for_updates(
    enabled: bool = True,
    project_root: Path | None = None,
    *,
    use_cache: bool = True,
) -> UpdateCheckResult | None:
    """Top-level entry point.

    Returns None when disabled, when local version can't be resolved,
    or when the network call fails. Otherwise returns a populated
    ``UpdateCheckResult`` (``behind=False`` means up-to-date).
    """
    if not enabled:
        return None

    local = get_local_version(project_root)
    if not local:
        return None

    if use_cache:
        cached = _read_cache()
        if cached is not None and cached.get("local") == local:
            return UpdateCheckResult(
                local=local,
                latest=cached.get("latest", ""),
                behind=bool(cached.get("behind", False)),
                release_url=cached.get("release_url", ""),
                release_title=cached.get("release_title", ""),
            )

    fetched = await fetch_latest_release()
    if fetched is None:
        return None
    latest, url, title = fetched

    behind = _is_behind(local, latest)
    result = UpdateCheckResult(
        local=local,
        latest=latest,
        behind=behind,
        release_url=url,
        release_title=title,
    )
    # Preserve last_notified across re-checks so the periodic notifier
    # doesn't lose its dedup key.
    prior = _read_cache_raw() or {}
    _write_cache(
        {
            "checked_at": time.time(),
            "local": local,
            "latest": latest,
            "behind": behind,
            "release_url": url,
            "release_title": title,
            "last_notified": prior.get("last_notified", ""),
        }
    )
    return result


def _read_cache_raw() -> dict | None:
    """Read the cache file regardless of TTL (for state we want to keep
    across cache expiries, like ``last_notified``)."""
    path = _cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def mark_notified(version: str) -> None:
    """Record that the user has been told about ``version`` so the
    periodic notifier doesn't print the same banner repeatedly."""
    raw = _read_cache_raw() or {}
    raw["last_notified"] = version
    _write_cache(raw)


def should_notify(result: UpdateCheckResult | None) -> bool:
    """True when the result represents a *new* update the user hasn't
    been told about yet in this install."""
    if result is None or not result.behind:
        return False
    raw = _read_cache_raw() or {}
    return raw.get("last_notified", "") != result.latest


def format_banner(result: UpdateCheckResult) -> str:
    """One-line banner for chat/gateway startup. Empty string if up-to-date."""
    if not result.behind:
        return ""
    title = f" — {result.release_title}" if result.release_title else ""
    return (
        f"Update available: {result.local} → {result.latest}{title}\n"
        f"  git pull && pip install -e .  ·  {result.release_url}"
    )
