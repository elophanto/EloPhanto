"""agent_p2p_connect — Open a libp2p stream to a peer by PeerID.

Companion to the WS-based agent_connect, but over the decentralized
transport. Caller hands a PeerID (and optionally cached multiaddrs
from a recent agent_discover --method=p2p); we ask the sidecar to
DHT-resolve the peer (if needed) and open an /elophanto/1.0.0 stream
to it. Returns a stream_id that subsequent agent_p2p_message and
agent_p2p_disconnect calls reference.

DESTRUCTIVE because it allocates a real network connection that
remote operators will see in their logs.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class AgentP2PConnectTool(BaseTool):
    @property
    def group(self) -> str:
        return "agent_identity"

    def __init__(self) -> None:
        self._p2p_sidecar: Any = None

    @property
    def name(self) -> str:
        return "agent_p2p_connect"

    @property
    def description(self) -> str:
        return (
            "Open a libp2p stream to a peer EloPhanto by PeerID. "
            "Decentralized counterpart to agent_connect — no URL, no "
            "Tailscale, no central registry. Returns a stream_id, the "
            "peer's reachable multiaddrs, and via_relay (true means "
            "the connection routes through a circuit-relay node, which "
            "works but is slower than direct). If `addrs` is supplied "
            "(typically from a recent agent_discover), skips the DHT "
            "lookup and dials directly. Hold the stream_id for "
            "agent_p2p_message and agent_p2p_disconnect."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "peer_id": {
                    "type": "string",
                    "description": (
                        "libp2p PeerID of the remote agent (starts with "
                        "'12D3KooW' for Ed25519). Get it from the remote "
                        "operator out of band, or from a prior "
                        "agent_discover --method=p2p result."
                    ),
                },
                "addrs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional cached multiaddrs to dial directly "
                        "(skips DHT lookup). Pass these when you got "
                        "them from a recent agent_discover."
                    ),
                },
                "timeout_ms": {
                    "type": "integer",
                    "description": "Connect timeout in ms. Default 30000.",
                },
            },
            "required": ["peer_id"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._p2p_sidecar is None:
            return ToolResult(
                success=False,
                data={},
                error=(
                    "P2P sidecar not running — set peers.enabled: true in "
                    "config.yaml and restart."
                ),
            )
        peer_id = (params.get("peer_id") or "").strip()
        if not peer_id:
            return ToolResult(success=False, data={}, error="`peer_id` is required")
        addrs = params.get("addrs") or []
        timeout_ms = int(params.get("timeout_ms") or 30000)
        try:
            result = await self._p2p_sidecar.peer_connect(
                peer_id, addrs=addrs, timeout_ms=timeout_ms
            )
            return ToolResult(
                success=True,
                data={
                    "peer_id": peer_id,
                    "stream_id": result.stream_id,
                    "via_relay": result.via_relay,
                    "transport_hint": (
                        "Routed via circuit-relay (slower; ~50-200ms "
                        "latency overhead). DCUtR will try to upgrade "
                        "to direct in the background."
                        if result.via_relay
                        else "Direct connection (no relay in path)."
                    ),
                    "next_step": (
                        f"agent_p2p_message(stream_id='{result.stream_id}', "
                        "content=...) to send a message; "
                        "agent_p2p_disconnect when done."
                    ),
                },
            )
        except Exception as e:
            return ToolResult(
                success=False,
                data={"peer_id": peer_id},
                error=f"libp2p connect failed: {e}",
            )
