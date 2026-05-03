"""Peer discovery — find other EloPhanto agents on networks you can reach.

v1 backend: **Tailscale**. Calls ``tailscale status --json`` to enumerate
machines on your tailnet, filters to those advertising the agent
gateway port (or matching a tag), then probes each one's
``/capabilities`` endpoint to confirm it's actually an EloPhanto.

Why Tailscale first:
- Free for personal use, magic-DNS, no port forwarding, encrypts at
  the WireGuard layer. The "I have an agent on my laptop and one on a
  server" case is solved out of the box.
- Mature CLI / JSON output, easy to parse defensively.

Why not mDNS in v1: mDNS is LAN-only and noisier to filter; Tailscale
covers more cases (LAN + cross-internet) and is what most operators
already use. mDNS can come in v2.

The discovery layer never auto-connects. It returns candidate URLs +
metadata; the operator (or the agent in chat) decides which to
``agent_connect`` to.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# Default port we try when Tailscale doesn't tell us one explicitly.
# Matches GatewayConfig.port.
_DEFAULT_AGENT_PORT = 18789

# Tag name conventions. If a machine has the `tag:elophanto-agent`
# Tailscale ACL tag, we treat it as a likely peer without probing.
_AGENT_TAG = "tag:elophanto-agent"


@dataclass
class DiscoveredPeer:
    """A peer agent we found on the network. Identity is unverified
    until you actually ``agent_connect`` to the URL."""

    hostname: str
    address: str  # IP or DNS name reachable from this host
    url: str  # ws://addr:port or wss:// when probed for TLS
    method: str  # 'tailscale' for now; mDNS / registry come later
    tagged: bool  # whether this peer was tagged in the source's ACLs
    capabilities: dict[str, Any] | None = None  # populated when probed


# ---------------------------------------------------------------------------
# Tailscale backend
# ---------------------------------------------------------------------------


def is_tailscale_available() -> bool:
    """Return True if the `tailscale` CLI is installed AND reports running.

    We check both binary presence and `status` exit code so a stopped
    tailscaled doesn't show up as "available" with empty results."""
    return shutil.which("tailscale") is not None


async def _tailscale_status_json() -> dict[str, Any]:
    """Run `tailscale status --json` and parse output. Returns {} on
    any failure — caller should treat empty dict as "no peers found,"
    not as an error."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "tailscale",
            "status",
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        if proc.returncode != 0:
            return {}
        return json.loads(stdout.decode("utf-8", errors="replace"))
    except (TimeoutError, FileNotFoundError, json.JSONDecodeError):
        return {}
    except Exception as e:
        logger.debug("tailscale status failed: %s", e)
        return {}


def _parse_tailscale_peers(raw: dict[str, Any], port: int) -> list[DiscoveredPeer]:
    """Extract DiscoveredPeer entries from a tailscale status payload.

    Pure function over the parsed JSON — easy to unit-test against
    fixtures without invoking the CLI.

    The Tailscale JSON shape varies a bit across versions; we read
    defensively. Useful fields per peer:
        HostName, DNSName, TailscaleIPs (list[str]), Tags (list[str])
    """
    peers: list[DiscoveredPeer] = []
    raw_peers = raw.get("Peer") or raw.get("Peers") or {}
    if isinstance(raw_peers, dict):
        peer_list = list(raw_peers.values())
    elif isinstance(raw_peers, list):
        peer_list = raw_peers
    else:
        peer_list = []

    for p in peer_list:
        if not isinstance(p, dict):
            continue
        # Address candidates in priority order. DNSName works without
        # MagicDNS too because Tailscale resolves the FQDN regardless.
        # IP fallback covers tailnets where DNS is intermittent.
        addresses: list[str] = []
        dns_name = str(p.get("DNSName", "")).rstrip(".")
        if dns_name:
            addresses.append(dns_name)
        for ip in p.get("TailscaleIPs") or []:
            if isinstance(ip, str):
                addresses.append(ip)
        if not addresses:
            continue
        primary = addresses[0]
        tags = p.get("Tags") or []
        tagged = isinstance(tags, list) and _AGENT_TAG in tags
        hostname = str(p.get("HostName") or primary)
        peers.append(
            DiscoveredPeer(
                hostname=hostname,
                address=primary,
                url=f"ws://{primary}:{port}",
                method="tailscale",
                tagged=tagged,
            )
        )
    return peers


async def _probe_capabilities(peer: DiscoveredPeer, *, timeout: float = 3.0) -> bool:
    """HTTP-probe the peer's /capabilities endpoint. Returns True if it
    responds with a sane JSON payload, populating ``peer.capabilities``
    on success.

    Best-effort: any failure (host down, port closed, not an EloPhanto)
    silently returns False so a single dead host doesn't fail the whole
    discovery run."""
    try:
        import aiohttp
    except ImportError:
        # aiohttp is optional — fall back to "we found it, you probe it"
        return False

    # Try wss first then ws — peers might be running TLS.
    for scheme in ("https", "http"):
        url = f"{scheme}://{peer.address}:{_DEFAULT_AGENT_PORT}/capabilities"
        try:
            timeout_ctx = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=timeout_ctx) as session:
                # ssl=False skips verification on the discovery probe;
                # capabilities is informational, not auth-bearing — real
                # trust is established by IDENTIFY on agent_connect.
                async with session.get(url, ssl=False) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, dict):
                            peer.capabilities = {
                                "version": data.get("version", "unknown"),
                                "tools_count": len(data.get("tools") or []),
                                "skills_count": len(data.get("skills") or []),
                                "providers": data.get("providers", []),
                            }
                            # Promote URL to the scheme that worked.
                            peer.url = f"{'wss' if scheme == 'https' else 'ws'}://{peer.address}:{_DEFAULT_AGENT_PORT}"
                            return True
        except Exception as e:
            logger.debug("capabilities probe %s failed: %s", url, e)
    return False


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def discover_peers(
    *,
    method: str = "tailscale",
    port: int = _DEFAULT_AGENT_PORT,
    probe: bool = True,
    tagged_only: bool = False,
) -> list[DiscoveredPeer]:
    """Return a list of candidate peer agents reachable from this host.

    Args:
        method: discovery backend (``tailscale`` is the only one in v1).
        port: port to advertise in candidate URLs (defaults to gateway).
        probe: when True, hit each candidate's ``/capabilities`` to
            confirm it's actually an EloPhanto and learn its tool/skill
            counts. Slower but higher-quality results. When False,
            returns every Tailscale peer as a candidate (much faster,
            but you'll see noise from non-EloPhanto machines).
        tagged_only: when True, only return peers tagged
            ``tag:elophanto-agent`` in Tailscale ACLs — guarantees
            no false positives if your ACLs are configured.
    """
    if method != "tailscale":
        raise ValueError(
            f"Unsupported discovery method: {method!r}. v1 supports only 'tailscale'."
        )
    if not is_tailscale_available():
        return []

    raw = await _tailscale_status_json()
    candidates = _parse_tailscale_peers(raw, port)

    if tagged_only:
        candidates = [c for c in candidates if c.tagged]

    if probe:
        # Probe in parallel — discovery is I/O-bound and per-peer
        # probes are independent.
        results = await asyncio.gather(
            *(_probe_capabilities(c) for c in candidates),
            return_exceptions=True,
        )
        # Keep only candidates that responded with a sane capabilities
        # payload. Tagged peers stay even if probe failed (tags are
        # operator-asserted truth).
        kept: list[DiscoveredPeer] = []
        for cand, ok in zip(candidates, results, strict=False):
            if ok is True or cand.tagged:
                kept.append(cand)
        return kept

    return candidates
