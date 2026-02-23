"""Agent Census — anonymous, non-blocking startup heartbeat.

Sends a minimal, anonymous payload to the census API on every startup.
The fingerprint is derived from the machine's hardware UUID (SHA-256 hashed
with a salt), so it survives uninstall/reinstall on the same machine.

See docs/21-AGENT-CENSUS.md for the full specification.
"""

from __future__ import annotations

import hashlib
import logging
import platform
import subprocess
import sys
import uuid
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

CENSUS_URL = "https://api.elophanto.com/v1/census/heartbeat"
_SALT = "elophanto-census-salt"
_TIMEOUT = 3  # seconds
_VERSION = "2026.02.23.1"


def _get_machine_uuid() -> str | None:
    """Retrieve the platform-specific machine UUID.

    Returns None if unavailable (container, sandbox, restricted perms).
    """
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if "IOPlatformUUID" in line:
                    # Format: "IOPlatformUUID" = "XXXXXXXX-XXXX-..."
                    return line.split('"')[-2]
        elif sys.platform == "linux":
            for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                p = Path(path)
                if p.exists():
                    return p.read_text().strip()
        elif sys.platform == "win32":
            result = subprocess.run(
                [
                    "reg",
                    "query",
                    r"HKLM\SOFTWARE\Microsoft\Cryptography",
                    "/v",
                    "MachineGuid",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if "MachineGuid" in line:
                    return line.split()[-1]
    except Exception:
        pass
    return None


def get_agent_fingerprint(data_dir: Path | None = None) -> str:
    """Return a stable, anonymous agent fingerprint (SHA-256 hex).

    Uses the machine's hardware UUID when available, falling back to a
    persistent random ID stored in data/.census_id.
    """
    machine_id = _get_machine_uuid()

    if not machine_id:
        # Fallback: persistent random ID
        if data_dir is None:
            data_dir = Path("data")
        census_file = data_dir / ".census_id"
        if census_file.exists():
            machine_id = census_file.read_text().strip()
        else:
            machine_id = str(uuid.uuid4())
            census_file.parent.mkdir(parents=True, exist_ok=True)
            census_file.write_text(machine_id)

    return hashlib.sha256(f"{machine_id}{_SALT}".encode()).hexdigest()


def _build_payload(data_dir: Path | None = None) -> dict:
    """Build the census heartbeat payload."""
    if data_dir is None:
        data_dir = Path("data")

    agent_id = get_agent_fingerprint(data_dir)
    sent_marker = data_dir / ".census_sent"
    first_seen = not sent_marker.exists()

    return {
        "agent_id": f"sha256:{agent_id}",
        "v": _VERSION,
        "platform": f"{sys.platform}-{platform.machine()}",
        "python": platform.python_version(),
        "first_seen": first_seen,
    }


async def send_heartbeat(data_dir: Path | None = None) -> None:
    """POST census heartbeat — fire-and-forget, all exceptions caught.

    3-second timeout, no retries. Logs debug on success, debug on failure.
    """
    if data_dir is None:
        data_dir = Path("data")

    try:
        payload = _build_payload(data_dir)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(CENSUS_URL, json=payload)
            resp.raise_for_status()

        # Mark first heartbeat as sent
        sent_marker = data_dir / ".census_sent"
        if not sent_marker.exists():
            sent_marker.parent.mkdir(parents=True, exist_ok=True)
            sent_marker.write_text("1")

        logger.debug("Census heartbeat sent (agent_id=%s…)", payload["agent_id"][:20])
    except Exception as e:
        logger.debug("Census heartbeat failed (non-blocking): %s", e)
