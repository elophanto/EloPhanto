"""agent_discover — Find peer agents on networks you can reach (Tailscale)."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class AgentDiscoverTool(BaseTool):
    """Enumerate candidate peer agents reachable from this host."""

    @property
    def group(self) -> str:
        return "agent_identity"

    def __init__(self) -> None:
        # Sidecar handle for method="p2p" — wired in by Agent
        # ._inject_p2p_deps(). For method="tailscale" no injection
        # is needed (calls discover_peers directly).
        self._p2p_sidecar: Any = None

    @property
    def name(self) -> str:
        return "agent_discover"

    @property
    def description(self) -> str:
        return (
            "Find peer EloPhanto agents reachable on your networks. "
            "Two backends: 'tailscale' (calls `tailscale status --json` and "
            "probes each peer's /capabilities) returns candidate URLs for "
            "agent_connect; 'p2p' (libp2p Kademlia DHT) takes a PeerID "
            "and resolves the multiaddrs the peer is currently listening on "
            "— pair with agent_p2p_connect. The Tailscale path is the "
            "easy mode (no third-party in the data path on a private "
            "tailnet); P2P is decentralized but requires the sidecar to "
            "be enabled (peers.enabled in config) and at least one "
            "bootstrap node to be reachable. Set tagged_only=true on "
            "Tailscale to filter to peers explicitly tagged "
            "'tag:elophanto-agent'."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["tailscale", "p2p"],
                    "description": (
                        "Discovery backend. 'tailscale' enumerates the "
                        "tailnet; 'p2p' resolves a single PeerID via "
                        "the libp2p DHT (requires `peer_id` param)."
                    ),
                },
                "peer_id": {
                    "type": "string",
                    "description": (
                        "libp2p PeerID to look up (only used with "
                        "method='p2p'). Format: starts with '12D3KooW' "
                        "for Ed25519 peers."
                    ),
                },
                "timeout_ms": {
                    "type": "integer",
                    "description": (
                        "DHT lookup timeout in ms (only used with "
                        "method='p2p'). Default 10000."
                    ),
                },
                "tagged_only": {
                    "type": "boolean",
                    "description": (
                        "Only return Tailscale peers with the "
                        "'tag:elophanto-agent' ACL tag. Default false "
                        "(returns all peers + probes /capabilities)."
                    ),
                },
                "probe": {
                    "type": "boolean",
                    "description": (
                        "When true (default), HTTP-probe each peer's "
                        "/capabilities endpoint to confirm it's an "
                        "EloPhanto. When false, return all reachable "
                        "tailnet peers as candidates without verification."
                    ),
                },
                "port": {
                    "type": "integer",
                    "description": "Gateway port to probe. Default 18789.",
                },
            },
            "required": [],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        from core.peer_discovery import (
            discover_peers,
            is_tailscale_available,
        )

        method = (params.get("method") or "tailscale").strip()

        # P2P path — DHT FIND_NODE for a single PeerID. Returns the
        # multiaddrs the peer is currently reachable on, which the
        # caller then hands to agent_p2p_connect.
        if method == "p2p":
            if self._p2p_sidecar is None:
                return ToolResult(
                    success=False,
                    data={"method": "p2p"},
                    error=(
                        "P2P sidecar not running. Set peers.enabled: true "
                        "in config.yaml and ensure the binary is built. "
                        "See docs/68-DECENTRALIZED-PEERS-RFC.md."
                    ),
                )
            peer_id = (params.get("peer_id") or "").strip()
            if not peer_id:
                return ToolResult(
                    success=False,
                    data={},
                    error="method='p2p' requires the `peer_id` parameter",
                )
            timeout_ms = int(params.get("timeout_ms") or 10000)
            try:
                info = await self._p2p_sidecar.peer_find(peer_id, timeout_ms=timeout_ms)
                return ToolResult(
                    success=True,
                    data={
                        "method": "p2p",
                        "peer_id": info.peer_id,
                        "addrs": info.addrs,
                        "reachable": len(info.addrs) > 0,
                        "next_step": (
                            f"agent_p2p_connect(peer_id='{info.peer_id}') "
                            "to open a libp2p stream."
                        ),
                    },
                )
            except Exception as e:
                # The DHT lookup can fail for benign reasons (peer
                # offline, no path to it through the DHT yet) — surface
                # the error but don't pretend it's fatal.
                return ToolResult(
                    success=False,
                    data={"method": "p2p", "peer_id": peer_id},
                    error=f"DHT lookup failed: {e}",
                )

        if method == "tailscale" and not is_tailscale_available():
            return ToolResult(
                success=False,
                data={"available_backends": []},
                error=(
                    "Tailscale CLI not found. Install Tailscale "
                    "(https://tailscale.com/download), join your tailnet, "
                    "then retry. mDNS / registry backends will come in v2."
                ),
            )
        try:
            peers = await discover_peers(
                method=method,
                port=int(params.get("port") or 18789),
                probe=bool(params.get("probe", True)),
                tagged_only=bool(params.get("tagged_only", False)),
            )
            return ToolResult(
                success=True,
                data={
                    "method": method,
                    "count": len(peers),
                    "peers": [
                        {
                            "hostname": p.hostname,
                            "address": p.address,
                            "url": p.url,
                            "method": p.method,
                            "tagged": p.tagged,
                            "capabilities": p.capabilities,
                        }
                        for p in peers
                    ],
                    "next_step": (
                        "Use agent_connect(url=<peer.url>) to open a verified "
                        "session, then agent_message(agent_id, content)."
                    ),
                },
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"Discovery failed: {e}")
