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
        # Wired in by Agent._inject_p2p_deps when the trust ledger is
        # available. None = no TOFU pinning on outbound connects, same
        # fallback as the listener uses for backward compat.
        self._trust_ledger: Any = None

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

        # Pre-flight TOFU: refuse outbound connect when the peer is in
        # our trust ledger as blocked, or when the PeerID's pubkey
        # doesn't match what we have on file (key rotation suspected).
        # Run before peer_connect so we don't open a real connection
        # we're about to throw away.
        ledger_check = await self._tofu_pre_check(peer_id)
        if ledger_check is not None:
            return ledger_check

        try:
            result = await self._p2p_sidecar.peer_connect(
                peer_id, addrs=addrs, timeout_ms=timeout_ms
            )
        except Exception as e:
            return ToolResult(
                success=False,
                data={"peer_id": peer_id},
                error=f"libp2p connect failed: {e}",
            )

        # Connect succeeded → record the handshake. Best-effort: if the
        # ledger errors we still return the open stream because the
        # caller needs the stream_id to use or close it.
        trust_level = "unpinned"
        try:
            entry = await self._tofu_record(peer_id)
            if entry is not None:
                trust_level = entry.trust_level
        except Exception as e:
            # Already logged below — surface the connect-vs-pin status
            # split in the result so callers know.
            from logging import getLogger

            getLogger(__name__).warning(
                "p2p outbound TOFU pin failed for %s: %s", peer_id, e
            )

        return ToolResult(
            success=True,
            data={
                "peer_id": peer_id,
                "stream_id": result.stream_id,
                "via_relay": result.via_relay,
                "trust_level": trust_level,
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

    # ------------------------------------------------------------------
    # TOFU helpers — share the trust ledger with the wss:// transport
    # ------------------------------------------------------------------

    async def _tofu_pre_check(self, peer_id: str) -> ToolResult | None:
        """Return a ToolResult to abort the connect, or None to proceed.

        We can derive the peer's pubkey from the PeerID without any
        network round trip — libp2p Ed25519 PeerIDs are the protobuf
        pubkey wrapped in an identity multihash. So we can answer
        'is this peer in my ledger? blocked? key rotated?' BEFORE
        opening the libp2p connection.
        """
        if self._trust_ledger is None:
            return None
        from core.agent_identity import derive_agent_id_from_public_key
        from core.peer_p2p_identity import (
            PeerIDDecodeError,
            peer_id_to_ed25519_pubkey_b64,
        )

        try:
            pubkey_b64 = peer_id_to_ed25519_pubkey_b64(peer_id)
        except PeerIDDecodeError:
            # Non-Ed25519 peer or odd encoding. Don't refuse outbound
            # — noise still authenticates them; we just can't pin.
            return None
        agent_id = derive_agent_id_from_public_key(pubkey_b64)
        existing = await self._trust_ledger.get(agent_id)
        if existing is None:
            return None
        if existing.is_blocked:
            return ToolResult(
                success=False,
                data={"peer_id": peer_id, "agent_id": agent_id},
                error=(
                    f"refusing outbound connect: peer {agent_id} is "
                    "blocked in the trust ledger. Use agent_trust_set "
                    "to change the trust level if this is intentional."
                ),
            )
        if existing.public_key != pubkey_b64:
            return ToolResult(
                success=False,
                data={
                    "peer_id": peer_id,
                    "agent_id": agent_id,
                    "stored_pubkey": existing.public_key,
                    "claimed_pubkey": pubkey_b64,
                },
                error=(
                    f"refusing outbound connect: trust ledger has a "
                    f"different pubkey for {agent_id} (key rotation or "
                    "impersonation suspected). Confirm out of band, "
                    "then use agent_trust_set --rotate to allow."
                ),
            )
        return None

    async def _tofu_record(self, peer_id: str) -> Any:
        """Record the successful handshake in the trust ledger. Returns
        the KnownAgent entry, or None when the ledger isn't wired or
        the PeerID isn't decodable."""
        if self._trust_ledger is None:
            return None
        from core.agent_identity import derive_agent_id_from_public_key
        from core.peer_p2p_identity import (
            PeerIDDecodeError,
            peer_id_to_ed25519_pubkey_b64,
        )

        try:
            pubkey_b64 = peer_id_to_ed25519_pubkey_b64(peer_id)
        except PeerIDDecodeError:
            return None
        agent_id = derive_agent_id_from_public_key(pubkey_b64)
        return await self._trust_ledger.record_handshake(
            agent_id=agent_id, public_key=pubkey_b64
        )
