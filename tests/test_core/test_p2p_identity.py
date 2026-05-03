"""Tests for the PeerID <-> Ed25519 pubkey bridge and trust ledger
integration on both inbound (listener) and outbound (connect tool)
P2P paths."""

from __future__ import annotations

import asyncio
import json
import struct
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.agent_identity import (
    AgentIdentityKey,
    derive_agent_id_from_public_key,
)
from core.peer_p2p import P2PEvent
from core.peer_p2p_identity import (
    PeerIDDecodeError,
    peer_id_to_ed25519_pubkey_b64,
)
from core.peer_p2p_listener import IncomingStreamListener
from tools.agent_identity.p2p_connect_tool import AgentP2PConnectTool

# Reuse the FakeSidecar pattern from test_p2p_transport.py — copied
# verbatim here rather than imported across test files (test files
# shouldn't depend on each other).


class FakeSidecar:
    def __init__(self) -> None:
        self.peer_connect_calls: list[dict[str, Any]] = []
        self.stream_send_calls: list[tuple[str, bytes]] = []
        self._recv_buffer: bytearray = bytearray()
        self.events: asyncio.Queue[P2PEvent] = asyncio.Queue()
        from core.peer_p2p import ConnectResult, RecvResult

        self._RecvResult = RecvResult
        self.connect_result: ConnectResult | Exception = ConnectResult(
            stream_id="s1", via_relay=False
        )

    async def peer_connect(
        self,
        peer_id: str,
        *,
        addrs: list[str] | None = None,
        protocol_id: str = "/elophanto/1.0.0",
        timeout_ms: int = 30000,
    ) -> Any:
        self.peer_connect_calls.append({"peer_id": peer_id, "addrs": addrs})
        if isinstance(self.connect_result, Exception):
            raise self.connect_result
        return self.connect_result

    async def stream_send(self, stream_id: str, data: bytes) -> None:
        self.stream_send_calls.append((stream_id, data))

    async def stream_recv(
        self,
        stream_id: str,
        *,
        max_bytes: int = 65536,
        timeout_ms: int = 5000,
    ) -> Any:
        if not self._recv_buffer:
            return self._RecvResult(data=b"", eof=True)
        take = min(max_bytes, len(self._recv_buffer))
        chunk = bytes(self._recv_buffer[:take])
        del self._recv_buffer[:take]
        return self._RecvResult(data=chunk, eof=False)

    def queue_recv_bytes(self, payload: bytes) -> None:
        self._recv_buffer.extend(payload)


def _frame(payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + payload


# ---------------------------------------------------------------------------
# PeerID decoder
# ---------------------------------------------------------------------------


class TestPeerIDDecoder:
    def test_round_trip_against_known_keypair(self) -> None:
        """Decoder MUST recover the same b64 pubkey our identity layer
        emits — that's what makes the trust ledger entries shareable
        across wss:// and libp2p transports."""
        # We don't generate the PeerID ourselves here (that would require
        # libp2p deps). Instead, hard-code a known Ed25519 keypair and
        # the PeerID the Go sidecar produces from it (verified manually
        # via bin/elophanto-p2pd in the spike step). If go-libp2p ever
        # changes its PeerID encoding, this test is the canary.
        seed_hex = "00" * 32
        seed = bytes.fromhex(seed_hex)
        priv = Ed25519PrivateKey.from_private_bytes(seed)
        pub_raw = priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        from base64 import b64encode

        expected = b64encode(pub_raw).decode("ascii")
        # PeerID for a Ed25519 identity-multihashed key derived from
        # all-zero seed. Computed once with the Go sidecar; baked in.
        peer_id = "12D3KooWDpJ7As7BWAwRMfu1VU2WCqNjvq387JEYKDBj4kx6nXTN"
        decoded = peer_id_to_ed25519_pubkey_b64(peer_id)
        assert decoded == expected

    def test_empty_peer_id_raises(self) -> None:
        with pytest.raises(PeerIDDecodeError, match="empty"):
            peer_id_to_ed25519_pubkey_b64("")

    def test_invalid_base58_raises(self) -> None:
        # '0' is not in the base58btc alphabet (no zero, O, I, l).
        with pytest.raises(PeerIDDecodeError, match="base58btc"):
            peer_id_to_ed25519_pubkey_b64("12D3K0oWnotvalid")

    def test_garbage_raises_decode_error_not_random_exception(self) -> None:
        """The bridge surfaces all decode failures as PeerIDDecodeError
        — callers can catch one type and treat it as 'skip TOFU'."""
        # Random non-PeerID base58 string. Must raise our error type,
        # not propagate a struct.error or IndexError.
        with pytest.raises(PeerIDDecodeError):
            peer_id_to_ed25519_pubkey_b64("12345")


# ---------------------------------------------------------------------------
# IncomingStreamListener TOFU integration
# ---------------------------------------------------------------------------


class FakeTrustLedger:
    """Minimal stand-in. Records calls; programmable to refuse
    handshakes (TrustConflict), or block specific peers."""

    def __init__(self) -> None:
        from core.trust_ledger import TRUST_TOFU

        self._tofu_const = TRUST_TOFU
        self.entries: dict[str, Any] = {}
        self.handshake_calls: list[tuple[str, str]] = []
        self.raise_conflict_for: set[str] = set()
        self.block_after_handshake: set[str] = set()

    async def get(self, agent_id: str) -> Any:
        return self.entries.get(agent_id)

    async def record_handshake(
        self, *, agent_id: str, public_key: str, force_overwrite: bool = False
    ) -> Any:
        self.handshake_calls.append((agent_id, public_key))
        if agent_id in self.raise_conflict_for:
            from core.trust_ledger import TrustConflict

            raise TrustConflict(
                agent_id=agent_id,
                seen_public_key="DIFFERENT",
                claimed_public_key=public_key,
            )
        from core.trust_ledger import KnownAgent

        entry = KnownAgent(
            agent_id=agent_id,
            public_key=public_key,
            trust_level=(
                "blocked"
                if agent_id in self.block_after_handshake
                else self._tofu_const
            ),
            first_seen="now",
            last_seen="now",
            connection_count=1,
        )
        self.entries[agent_id] = entry
        return entry


def _make_peer_keypair() -> tuple[str, str, str]:
    """Generate a fresh Ed25519 identity. Returns (peer_id, pubkey_b64,
    expected_agent_id) — peer_id is the libp2p encoding for the same
    pubkey, computed via the same code under test (so the test exercises
    the round-trip end-to-end)."""
    from base64 import b64encode

    priv = Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pubkey_b64 = b64encode(pub_raw).decode("ascii")
    # Build the PeerID by reversing the decoder. Encoding helper lives
    # only in tests so we don't grow production surface area.
    peer_id = _encode_ed25519_peer_id(pub_raw)
    agent_id = derive_agent_id_from_public_key(pubkey_b64)
    return peer_id, pubkey_b64, agent_id


def _encode_ed25519_peer_id(pub_raw: bytes) -> str:
    """Test-only inverse of peer_id_to_ed25519_pubkey_b64. Builds the
    libp2p PeerID for an Ed25519 pubkey — protobuf-wrap, identity
    multihash, base58btc encode."""
    # Protobuf: field 1 (key_type=Ed25519=1) varint + field 2 (data) bytes.
    proto = bytes([0x08, 0x01])  # tag = (1<<3)|0, value 1
    proto += bytes([0x12, len(pub_raw)]) + pub_raw  # tag = (2<<3)|2
    # Identity multihash: code=0x00, length=len(proto), then the bytes.
    mh = bytes([0x00, len(proto)]) + proto
    return _b58btc_encode(mh)


def _b58btc_encode(b: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = int.from_bytes(b, "big")
    out = ""
    while n > 0:
        n, r = divmod(n, 58)
        out = alphabet[r] + out
    # Preserve leading zero bytes as leading '1's.
    for byte in b:
        if byte == 0:
            out = "1" + out
        else:
            break
    return out


class TestListenerTOFU:
    @pytest.mark.asyncio
    async def test_first_contact_pins_in_ledger(self) -> None:
        peer_id, pubkey_b64, agent_id = _make_peer_keypair()
        sidecar = FakeSidecar()
        sidecar.queue_recv_bytes(
            _frame(
                json.dumps(
                    {
                        "type": "chat",
                        "channel": "p2p",
                        "data": {"content": "hi"},
                    }
                ).encode("utf-8")
            )
        )
        ledger = FakeTrustLedger()

        async def handler(*_args: Any) -> str:
            return "hello back"

        listener = IncomingStreamListener(
            sidecar=sidecar, chat_handler=handler, trust_ledger=ledger
        )
        listener.start()
        try:
            await sidecar.events.put(
                P2PEvent(
                    name="peer.connected",
                    data={
                        "stream_id": "s1",
                        "peer_id": peer_id,
                        "direction": "incoming",
                    },
                )
            )
            for _ in range(50):
                if sidecar.stream_send_calls:
                    break
                await asyncio.sleep(0.02)
        finally:
            await listener.stop()

        # Ledger saw the handshake with the right agent_id + pubkey.
        assert (agent_id, pubkey_b64) in ledger.handshake_calls
        # Stream went through and a reply was written.
        assert len(sidecar.stream_send_calls) == 1

    @pytest.mark.asyncio
    async def test_blocked_peer_is_refused_silently(self) -> None:
        peer_id, _, agent_id = _make_peer_keypair()
        ledger = FakeTrustLedger()
        ledger.block_after_handshake.add(agent_id)
        sidecar = FakeSidecar()

        async def handler(*_args: Any) -> str:
            raise AssertionError("handler must NOT be called for blocked peer")

        listener = IncomingStreamListener(
            sidecar=sidecar, chat_handler=handler, trust_ledger=ledger
        )
        listener.start()
        try:
            await sidecar.events.put(
                P2PEvent(
                    name="peer.connected",
                    data={
                        "stream_id": "s1",
                        "peer_id": peer_id,
                        "direction": "incoming",
                    },
                )
            )
            await asyncio.sleep(0.15)
        finally:
            await listener.stop()
        # Listener refused before any reply went out.
        assert sidecar.stream_send_calls == []

    @pytest.mark.asyncio
    async def test_trust_conflict_refuses_connection(self) -> None:
        """Same agent_id with a different stored pubkey -> refuse."""
        peer_id, _, agent_id = _make_peer_keypair()
        ledger = FakeTrustLedger()
        ledger.raise_conflict_for.add(agent_id)
        sidecar = FakeSidecar()

        async def handler(*_args: Any) -> str:
            raise AssertionError("handler must NOT be called on conflict")

        listener = IncomingStreamListener(
            sidecar=sidecar, chat_handler=handler, trust_ledger=ledger
        )
        listener.start()
        try:
            await sidecar.events.put(
                P2PEvent(
                    name="peer.connected",
                    data={
                        "stream_id": "s1",
                        "peer_id": peer_id,
                        "direction": "incoming",
                    },
                )
            )
            await asyncio.sleep(0.15)
        finally:
            await listener.stop()
        assert sidecar.stream_send_calls == []

    @pytest.mark.asyncio
    async def test_no_ledger_means_no_pinning_no_refusal(self) -> None:
        """Opt-out: when trust_ledger=None, the listener processes every
        incoming stream without touching the ledger. Useful for tests
        and operators who haven't enabled the identity layer."""
        peer_id, _, _ = _make_peer_keypair()
        sidecar = FakeSidecar()
        sidecar.queue_recv_bytes(
            _frame(
                json.dumps(
                    {"type": "chat", "channel": "p2p", "data": {"content": "x"}}
                ).encode("utf-8")
            )
        )

        async def handler(*_args: Any) -> str:
            return "ok"

        listener = IncomingStreamListener(
            sidecar=sidecar, chat_handler=handler, trust_ledger=None
        )
        listener.start()
        try:
            await sidecar.events.put(
                P2PEvent(
                    name="peer.connected",
                    data={
                        "stream_id": "s1",
                        "peer_id": peer_id,
                        "direction": "incoming",
                    },
                )
            )
            for _ in range(50):
                if sidecar.stream_send_calls:
                    break
                await asyncio.sleep(0.02)
        finally:
            await listener.stop()
        assert len(sidecar.stream_send_calls) == 1


# ---------------------------------------------------------------------------
# AgentP2PConnectTool TOFU
# ---------------------------------------------------------------------------


class TestConnectToolTOFU:
    @pytest.mark.asyncio
    async def test_outbound_first_contact_pins_and_returns_trust_level(self) -> None:
        peer_id, pubkey_b64, agent_id = _make_peer_keypair()
        sidecar = FakeSidecar()
        ledger = FakeTrustLedger()
        tool = AgentP2PConnectTool()
        tool._p2p_sidecar = sidecar
        tool._trust_ledger = ledger

        result = await tool.execute({"peer_id": peer_id})
        assert result.success
        assert result.data["trust_level"] == "tofu"
        # Sidecar peer_connect was called with the right peer id.
        assert sidecar.peer_connect_calls[0]["peer_id"] == peer_id
        # Ledger received the handshake with derived agent_id + pubkey.
        assert (agent_id, pubkey_b64) in ledger.handshake_calls

    @pytest.mark.asyncio
    async def test_outbound_to_blocked_peer_refused_before_connect(self) -> None:
        """Pre-flight refusal — we don't even open the connection if
        the peer is blocked. Ledger gets queried via .get(); no handshake
        is recorded."""
        peer_id, pubkey_b64, agent_id = _make_peer_keypair()
        ledger = FakeTrustLedger()
        # Pre-seed a blocked entry.
        from core.trust_ledger import KnownAgent

        ledger.entries[agent_id] = KnownAgent(
            agent_id=agent_id,
            public_key=pubkey_b64,
            trust_level="blocked",
            first_seen="now",
            last_seen="now",
            connection_count=1,
        )
        sidecar = FakeSidecar()
        tool = AgentP2PConnectTool()
        tool._p2p_sidecar = sidecar
        tool._trust_ledger = ledger

        result = await tool.execute({"peer_id": peer_id})
        assert not result.success
        assert "blocked" in result.error
        # Critical: peer_connect was NOT called — the refusal is pre-flight.
        assert sidecar.peer_connect_calls == []
        # No handshake recorded either.
        assert ledger.handshake_calls == []

    @pytest.mark.asyncio
    async def test_outbound_pubkey_mismatch_refused(self) -> None:
        peer_id, _, agent_id = _make_peer_keypair()
        ledger = FakeTrustLedger()
        from core.trust_ledger import KnownAgent

        ledger.entries[agent_id] = KnownAgent(
            agent_id=agent_id,
            public_key="DIFFERENT_PUBKEY",
            trust_level="tofu",
            first_seen="now",
            last_seen="now",
            connection_count=1,
        )
        sidecar = FakeSidecar()
        tool = AgentP2PConnectTool()
        tool._p2p_sidecar = sidecar
        tool._trust_ledger = ledger

        result = await tool.execute({"peer_id": peer_id})
        assert not result.success
        assert "rotation" in result.error or "impersonation" in result.error
        assert sidecar.peer_connect_calls == []

    @pytest.mark.asyncio
    async def test_outbound_no_ledger_still_works(self) -> None:
        """Backward compat: tool works with just the sidecar wired —
        no ledger needed."""
        peer_id, _, _ = _make_peer_keypair()
        sidecar = FakeSidecar()
        tool = AgentP2PConnectTool()
        tool._p2p_sidecar = sidecar
        # No ledger.

        result = await tool.execute({"peer_id": peer_id})
        assert result.success
        assert result.data["trust_level"] == "unpinned"


# ---------------------------------------------------------------------------
# Cross-transport: same peer via wss:// and libp2p shares one ledger entry
# ---------------------------------------------------------------------------


class TestCrossTransportTrust:
    @pytest.mark.asyncio
    async def test_one_peer_across_two_transports_is_one_ledger_entry(
        self,
    ) -> None:
        """The whole point of the bridge: a peer that handshakes with
        us via wss://IDENTIFY today and via libp2p tomorrow lands in
        the SAME trust ledger entry — one agent_id, one pubkey, one
        trust decision."""
        peer_id, pubkey_b64, agent_id = _make_peer_keypair()

        # Reconstruct the AgentIdentityKey from the same pubkey to
        # mirror what would land via wss://IDENTIFY.
        from base64 import b64decode

        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )

        pubkey_obj = Ed25519PublicKey.from_public_bytes(b64decode(pubkey_b64))
        # We don't need the private key here — only the pubkey is
        # exchanged in IDENTIFY. This mocks what the WS gateway would
        # do after verifying the peer's signature.
        AgentIdentityKey(
            private_key=None,  # type: ignore[arg-type]
            public_key=pubkey_obj,
            agent_id=agent_id,
        )

        ledger = FakeTrustLedger()

        # Step 1: peer connects via wss:// — gateway records handshake.
        await ledger.record_handshake(agent_id=agent_id, public_key=pubkey_b64)

        # Step 2: same peer connects via libp2p — connect tool records.
        sidecar = FakeSidecar()
        tool = AgentP2PConnectTool()
        tool._p2p_sidecar = sidecar
        tool._trust_ledger = ledger

        result = await tool.execute({"peer_id": peer_id})
        assert result.success

        # Ledger has exactly one entry for this agent_id, with the same
        # pubkey, after both transports recorded handshakes.
        assert agent_id in ledger.entries
        assert ledger.entries[agent_id].public_key == pubkey_b64
        # Both record_handshake calls used the same pair of values —
        # i.e. the ledger never saw two different (agent_id, pubkey)
        # rows for what is logically one peer.
        for recorded_agent_id, recorded_pubkey in ledger.handshake_calls:
            assert recorded_agent_id == agent_id
            assert recorded_pubkey == pubkey_b64
