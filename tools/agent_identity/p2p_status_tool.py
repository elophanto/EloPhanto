"""agent_p2p_status — Diagnostics for the libp2p sidecar.

Reports whether the sidecar is running, our PeerID (so we can hand it
out for cross-internet connections), the listen multiaddrs, current
peer count, and AutoNAT's reachability verdict (public / private /
unknown). This is the canonical "is decentralized peers working?"
check the doctor leans on, and the first thing to call when
troubleshooting agent-to-agent connectivity issues.

Read-only — never mutates state.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class AgentP2PStatusTool(BaseTool):
    """Report libp2p sidecar status: PeerID, listen addrs, peer count,
    NAT verdict."""

    @property
    def group(self) -> str:
        return "agent_identity"

    def __init__(self) -> None:
        # Wired in by Agent._inject_p2p_deps after sidecar startup.
        self._p2p_sidecar: Any = None
        self._p2p_peer_id: str = ""

    @property
    def name(self) -> str:
        return "agent_p2p_status"

    @property
    def description(self) -> str:
        return (
            "Report libp2p peer-to-peer transport status: our PeerID, "
            "listen multiaddrs, connected peer count, and NAT reachability "
            "(public / private / unknown). Use this to confirm the "
            "decentralized transport is up before attempting cross-internet "
            "agent_connect, and to share your PeerID with another operator "
            "so they can connect to you. Returns disabled=true with a "
            "reason when peers.enabled is false in config or the sidecar "
            "binary is missing."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._p2p_sidecar is None:
            return ToolResult(
                success=True,
                data={
                    "enabled": False,
                    "reason": (
                        "P2P sidecar not running. Set peers.enabled: true in "
                        "config.yaml and ensure the binary is built "
                        "(`cd bridge/p2p && go build -o elophanto-p2pd .`). "
                        "See docs/68-DECENTRALIZED-PEERS-RFC.md."
                    ),
                },
            )
        try:
            status = await self._p2p_sidecar.host_status()
        except Exception as e:
            return ToolResult(
                success=False,
                data={"enabled": True, "peer_id": self._p2p_peer_id},
                error=f"sidecar host_status failed: {e}",
            )

        # NAT-aware hint — the most common operator question is "why
        # can't anyone reach me?" The verdict drives the answer.
        hint = ""
        if status.nat_reachability == "private":
            hint = (
                "Reachability=private means incoming connections will "
                "route through a relay. Direct connections still work "
                "outbound. If no relays are configured/discovered, peers "
                "will not be able to reach you at all."
            )
        elif status.nat_reachability == "public":
            hint = (
                "Reachability=public — peers can dial you directly without " "a relay."
            )
        else:
            hint = (
                "Reachability=unknown — AutoNAT hasn't classified this "
                "host yet (needs at least one peer to probe). Try again "
                "in 30-60s or after connecting to a bootstrap peer."
            )

        return ToolResult(
            success=True,
            data={
                "enabled": True,
                "peer_id": status.peer_id,
                "listen_addrs": status.listen_addrs,
                "peer_count": status.peer_count,
                "nat_reachability": status.nat_reachability,
                "hint": hint,
                "share_with_peers": (
                    f"Give other operators your PeerID `{status.peer_id}` "
                    "so they can `agent_connect` to you over the DHT "
                    "(once cross-internet bootstrap is wired)."
                ),
            },
        )
