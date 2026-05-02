"""Agent-to-agent identity layer — keypair lifecycle + trust ledger
+ gateway IDENTIFY handshake. End-to-end behavioral tests."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agent_identity import (
    TRUST_BLOCKED,
    TRUST_TOFU,
    TRUST_VERIFIED,
    AgentIdentityKey,
    derive_agent_id_from_public_key,
    load_or_create,
    make_nonce,
    verify_signature,
)
from core.database import Database
from core.trust_ledger import TrustConflict, TrustLedger

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db(tmp_path: Path):
    d = Database(tmp_path / "t.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
def my_key(tmp_path: Path) -> AgentIdentityKey:
    return load_or_create(tmp_path / "me.pem")


@pytest.fixture
def peer_key(tmp_path: Path) -> AgentIdentityKey:
    return load_or_create(tmp_path / "peer.pem")


# ---------------------------------------------------------------------------
# Keypair lifecycle
# ---------------------------------------------------------------------------


class TestKeypairLifecycle:
    def test_generate_and_persist(self, tmp_path: Path) -> None:
        path = tmp_path / "k.pem"
        key = load_or_create(path)
        assert path.exists()
        # File mode is 0600 (owner read/write only).
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600, f"key file must be 0600, got {oct(mode)}"
        # agent_id derives from public key, stable across reloads.
        key2 = load_or_create(path)
        assert key.agent_id == key2.agent_id
        assert key.public_key_b64() == key2.public_key_b64()

    def test_agent_id_format(self, my_key: AgentIdentityKey) -> None:
        # Format: elo-<12 chars of base64 public key>
        assert my_key.agent_id.startswith("elo-")
        assert len(my_key.agent_id) == len("elo-") + 12

    def test_agent_id_derives_from_public_key(self, my_key: AgentIdentityKey) -> None:
        derived = derive_agent_id_from_public_key(my_key.public_key_b64())
        assert derived == my_key.agent_id

    def test_no_auto_create_raises_when_missing(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="No agent identity key"):
            load_or_create(tmp_path / "missing.pem", auto_create=False)


# ---------------------------------------------------------------------------
# Sign / verify
# ---------------------------------------------------------------------------


class TestSignVerify:
    def test_round_trip(self, my_key: AgentIdentityKey) -> None:
        nonce = make_nonce()
        sig = my_key.sign(nonce)
        assert verify_signature(my_key.public_key_b64(), sig, nonce)

    def test_tampered_payload_rejected(self, my_key: AgentIdentityKey) -> None:
        nonce = make_nonce()
        sig = my_key.sign(nonce)
        assert not verify_signature(my_key.public_key_b64(), sig, b"tampered")

    def test_wrong_key_rejected(
        self, my_key: AgentIdentityKey, peer_key: AgentIdentityKey
    ) -> None:
        nonce = make_nonce()
        sig = my_key.sign(nonce)
        # Verify with peer's public key instead of mine — must fail.
        assert not verify_signature(peer_key.public_key_b64(), sig, nonce)

    def test_invalid_pubkey_returns_false_not_raise(self) -> None:
        """Defensive: malformed inputs must not raise — caller decides."""
        assert not verify_signature("not-base64!@#", b"x", b"y")
        assert not verify_signature("YWJj", b"x", b"y")  # too-short key

    def test_nonces_are_random(self) -> None:
        a, b = make_nonce(), make_nonce()
        assert a != b
        assert len(a) == 32  # 256-bit


# ---------------------------------------------------------------------------
# Trust ledger
# ---------------------------------------------------------------------------


class TestTrustLedger:
    @pytest.mark.asyncio
    async def test_first_contact_is_tofu(self, db: Database) -> None:
        ledger = TrustLedger(db)
        entry = await ledger.record_handshake("elo-aaa", "pk1")
        assert entry.trust_level == TRUST_TOFU
        assert entry.connection_count == 1
        assert entry.first_seen and entry.last_seen
        assert entry.first_seen == entry.last_seen

    @pytest.mark.asyncio
    async def test_reconnect_with_same_key_bumps_counter(self, db: Database) -> None:
        ledger = TrustLedger(db)
        await ledger.record_handshake("elo-aaa", "pk1")
        e2 = await ledger.record_handshake("elo-aaa", "pk1")
        assert e2.connection_count == 2

    @pytest.mark.asyncio
    async def test_key_change_raises_trust_conflict(self, db: Database) -> None:
        """SSH known_hosts semantics — stranger claiming the agent_id
        of someone we already know with a different key is the danger
        signal that gets refused."""
        ledger = TrustLedger(db)
        await ledger.record_handshake("elo-aaa", "pk-original")
        with pytest.raises(TrustConflict) as exc_info:
            await ledger.record_handshake("elo-aaa", "pk-different")
        assert exc_info.value.agent_id == "elo-aaa"
        assert exc_info.value.seen_public_key == "pk-original"
        assert exc_info.value.claimed_public_key == "pk-different"

    @pytest.mark.asyncio
    async def test_force_overwrite_demotes_to_tofu(self, db: Database) -> None:
        """Owner-confirmed key rotation: overwrite the key but reset
        trust to TOFU so the owner re-confirms. Forgetting this would
        let a verified peer rotate to a key the owner never approved."""
        ledger = TrustLedger(db)
        await ledger.record_handshake("elo-aaa", "pk-original")
        await ledger.set_trust_level("elo-aaa", TRUST_VERIFIED)
        e = await ledger.record_handshake("elo-aaa", "pk-rotated", force_overwrite=True)
        assert e.public_key == "pk-rotated"
        assert e.trust_level == TRUST_TOFU, (
            "Force-overwrite must demote — verified-then-rotate without "
            "manual re-verify is exactly what we want to surface"
        )

    @pytest.mark.asyncio
    async def test_block_then_reconnect_stays_blocked(self, db: Database) -> None:
        ledger = TrustLedger(db)
        await ledger.record_handshake("elo-aaa", "pk1")
        await ledger.set_trust_level("elo-aaa", TRUST_BLOCKED)
        # Same-key reconnect attempt — must NOT bump counter on blocked
        e = await ledger.record_handshake("elo-aaa", "pk1")
        assert e.trust_level == TRUST_BLOCKED
        assert e.connection_count == 1, "Blocked peer must not have its counter bumped"

    @pytest.mark.asyncio
    async def test_invalid_trust_level_rejected(self, db: Database) -> None:
        ledger = TrustLedger(db)
        await ledger.record_handshake("elo-aaa", "pk1")
        with pytest.raises(ValueError, match="Invalid trust level"):
            await ledger.set_trust_level("elo-aaa", "super-trusted")

    @pytest.mark.asyncio
    async def test_set_trust_level_unknown_agent_raises(self, db: Database) -> None:
        ledger = TrustLedger(db)
        with pytest.raises(KeyError):
            await ledger.set_trust_level("elo-ghost", TRUST_VERIFIED)

    @pytest.mark.asyncio
    async def test_remove_clears_entry(self, db: Database) -> None:
        ledger = TrustLedger(db)
        await ledger.record_handshake("elo-aaa", "pk1")
        assert await ledger.remove("elo-aaa") is True
        assert await ledger.get("elo-aaa") is None
        # Removed agent re-enters as TOFU on next handshake.
        e = await ledger.record_handshake("elo-aaa", "pk1")
        assert e.trust_level == TRUST_TOFU
        assert e.connection_count == 1

    @pytest.mark.asyncio
    async def test_list_excludes_blocked_when_requested(self, db: Database) -> None:
        ledger = TrustLedger(db)
        await ledger.record_handshake("elo-aaa", "pk1")
        await ledger.record_handshake("elo-bbb", "pk2")
        await ledger.set_trust_level("elo-aaa", TRUST_BLOCKED)
        all_peers = await ledger.list_all()
        assert {e.agent_id for e in all_peers} == {"elo-aaa", "elo-bbb"}
        active = await ledger.list_all(include_blocked=False)
        assert {e.agent_id for e in active} == {"elo-bbb"}


# ---------------------------------------------------------------------------
# Gateway IDENTIFY handler — end-to-end with real signatures
# ---------------------------------------------------------------------------


def _build_gateway(db: Database, my_key: AgentIdentityKey):
    """Construct a Gateway with the identity layer wired but without
    actually starting a websocket server."""
    from core.gateway import Gateway
    from core.session import SessionManager

    sm = SessionManager(db)
    agent_mock = MagicMock()
    agent_mock._router = None
    agent_mock._config = None
    gw = Gateway(
        agent=agent_mock,
        session_manager=sm,
        host="127.0.0.1",
        port=18789,
        max_sessions=10,
    )
    gw._agent_identity = my_key
    gw._trust_ledger = TrustLedger(db)
    return gw


def _build_client():
    """Mock ClientConnection with an async-mockable websocket."""
    from core.gateway import ClientConnection

    ws = MagicMock()
    ws.send = AsyncMock()
    return ClientConnection(client_id="c1", websocket=ws)


def _decode_response(client) -> dict:
    """Pull the last identify_response payload from the mock."""
    sent = client.websocket.send.call_args.args[0]
    return json.loads(sent)["data"]


class TestGatewayIdentifyHandler:
    @pytest.mark.asyncio
    async def test_valid_handshake_accepted(
        self,
        db: Database,
        my_key: AgentIdentityKey,
        peer_key: AgentIdentityKey,
    ) -> None:
        from core.protocol import identify_message

        gw = _build_gateway(db, my_key)
        client = _build_client()
        challenge = base64.b64encode(make_nonce()).decode("ascii")
        client.pending_challenge = challenge
        sig = peer_key.sign(base64.b64decode(challenge))

        await gw._handle_identify(
            client,
            identify_message(
                agent_id=peer_key.agent_id,
                public_key_b64=peer_key.public_key_b64(),
                challenge_b64=challenge,
                signature_b64=base64.b64encode(sig).decode("ascii"),
            ),
        )

        resp = _decode_response(client)
        assert resp["accepted"] is True
        assert resp["trust_level"] == TRUST_TOFU
        assert client.peer_verified is True
        assert client.peer_agent_id == peer_key.agent_id
        # Fresh challenge issued for mutual auth — must differ from old.
        assert resp["challenge"] != challenge
        # And it's now what the connection expects next.
        assert client.pending_challenge == resp["challenge"]

    @pytest.mark.asyncio
    async def test_replayed_challenge_rejected(
        self,
        db: Database,
        my_key: AgentIdentityKey,
        peer_key: AgentIdentityKey,
    ) -> None:
        """After a successful handshake the gateway rotates the
        challenge. Replaying the old signature against the same client
        must fail with challenge_mismatch."""
        from core.protocol import identify_message

        gw = _build_gateway(db, my_key)
        client = _build_client()
        challenge = base64.b64encode(make_nonce()).decode("ascii")
        client.pending_challenge = challenge
        sig = peer_key.sign(base64.b64decode(challenge))
        msg = identify_message(
            agent_id=peer_key.agent_id,
            public_key_b64=peer_key.public_key_b64(),
            challenge_b64=challenge,
            signature_b64=base64.b64encode(sig).decode("ascii"),
        )
        await gw._handle_identify(client, msg)
        client.websocket.send.reset_mock()
        # Same exact message — pending_challenge has rotated.
        await gw._handle_identify(client, msg)
        assert _decode_response(client)["reason"] == "challenge_mismatch"

    @pytest.mark.asyncio
    async def test_invalid_signature_rejected(
        self,
        db: Database,
        my_key: AgentIdentityKey,
        peer_key: AgentIdentityKey,
    ) -> None:
        from core.protocol import identify_message

        gw = _build_gateway(db, my_key)
        client = _build_client()
        challenge = base64.b64encode(make_nonce()).decode("ascii")
        client.pending_challenge = challenge

        await gw._handle_identify(
            client,
            identify_message(
                agent_id=peer_key.agent_id,
                public_key_b64=peer_key.public_key_b64(),
                challenge_b64=challenge,
                signature_b64=base64.b64encode(b"\x00" * 64).decode("ascii"),
            ),
        )
        resp = _decode_response(client)
        assert resp["accepted"] is False
        assert resp["reason"] == "signature_invalid"
        assert client.peer_verified is False

    @pytest.mark.asyncio
    async def test_agent_id_mismatch_rejected(
        self,
        db: Database,
        my_key: AgentIdentityKey,
        peer_key: AgentIdentityKey,
    ) -> None:
        """Peer claims an agent_id that doesn't derive from the
        public_key they sent — refused."""
        from core.protocol import identify_message

        gw = _build_gateway(db, my_key)
        client = _build_client()
        challenge = base64.b64encode(make_nonce()).decode("ascii")
        client.pending_challenge = challenge
        sig = peer_key.sign(base64.b64decode(challenge))

        await gw._handle_identify(
            client,
            identify_message(
                agent_id="elo-fake",  # doesn't derive from peer's pk
                public_key_b64=peer_key.public_key_b64(),
                challenge_b64=challenge,
                signature_b64=base64.b64encode(sig).decode("ascii"),
            ),
        )
        assert _decode_response(client)["reason"] == "agent_id_mismatch"
        assert client.peer_verified is False

    @pytest.mark.asyncio
    async def test_blocked_peer_refused(
        self,
        db: Database,
        my_key: AgentIdentityKey,
        peer_key: AgentIdentityKey,
    ) -> None:
        from core.protocol import identify_message

        gw = _build_gateway(db, my_key)
        # Pre-block the peer.
        await gw._trust_ledger.record_handshake(
            peer_key.agent_id, peer_key.public_key_b64()
        )
        await gw._trust_ledger.set_trust_level(peer_key.agent_id, TRUST_BLOCKED)

        client = _build_client()
        challenge = base64.b64encode(make_nonce()).decode("ascii")
        client.pending_challenge = challenge
        sig = peer_key.sign(base64.b64decode(challenge))

        await gw._handle_identify(
            client,
            identify_message(
                agent_id=peer_key.agent_id,
                public_key_b64=peer_key.public_key_b64(),
                challenge_b64=challenge,
                signature_b64=base64.b64encode(sig).decode("ascii"),
            ),
        )
        assert _decode_response(client)["reason"] == "blocked"
        assert client.peer_verified is False

    @pytest.mark.asyncio
    async def test_no_identity_layer_means_protocol_unavailable(
        self,
        db: Database,
        my_key: AgentIdentityKey,
        peer_key: AgentIdentityKey,
    ) -> None:
        """Backward-compat: gateway without identity layer wired (e.g.
        an older deployment) responds with protocol_unavailable so peers
        know not to retry."""
        from core.protocol import identify_message

        gw = _build_gateway(db, my_key)
        gw._agent_identity = None  # simulate older gateway
        gw._trust_ledger = None
        client = _build_client()
        client.pending_challenge = "anything"
        await gw._handle_identify(
            client,
            identify_message(
                agent_id=peer_key.agent_id,
                public_key_b64=peer_key.public_key_b64(),
                challenge_b64="x",
                signature_b64="y",
            ),
        )
        resp = _decode_response(client)
        assert resp["accepted"] is False
        assert resp["reason"] == "protocol_unavailable"
        # Crucially: doesn't raise. Older gateways continue to work.

    @pytest.mark.asyncio
    async def test_no_pending_challenge_rejected(
        self,
        db: Database,
        my_key: AgentIdentityKey,
        peer_key: AgentIdentityKey,
    ) -> None:
        """If a peer sends IDENTIFY before the gateway has issued a
        challenge (corrupt state, malicious early send), refuse."""
        from core.protocol import identify_message

        gw = _build_gateway(db, my_key)
        client = _build_client()
        # pending_challenge intentionally empty
        await gw._handle_identify(
            client,
            identify_message(
                agent_id=peer_key.agent_id,
                public_key_b64=peer_key.public_key_b64(),
                challenge_b64="x",
                signature_b64="y",
            ),
        )
        assert _decode_response(client)["reason"] == "no_challenge_issued"
