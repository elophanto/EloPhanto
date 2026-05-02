"""PeerManager tests — outbound agent-to-agent connections.

Covers the full client-side handshake against a fake gateway: connect,
verify identity, send chat, await streamed response, disconnect. Plus
the refusal paths: peer doesn't speak the protocol, peer claims a
mismatched agent_id, peer signature gets rejected, trust ledger
conflict on connect.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import pytest

from core.agent_identity import (
    AgentIdentityKey,
    load_or_create,
    make_nonce,
    verify_signature,
)
from core.database import Database
from core.peer_manager import PeerError, PeerManager
from core.protocol import (
    GatewayMessage,
    MessageType,
    identify_response_message,
    response_message,
    status_message,
)
from core.trust_ledger import TrustLedger

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
# Fake remote gateway (server side of the handshake)
# ---------------------------------------------------------------------------


class FakeRemoteWebSocket:
    """In-process stand-in for `websockets.client.WebSocketClientProtocol`.

    Backed by two asyncio.Queues — `inbound` is what the peer manager
    reads (.recv()), `outbound` is what the peer manager writes
    (.send()). The fake server runs as a coroutine that pulls from
    outbound and pushes to inbound, simulating the remote gateway's
    behavior.
    """

    def __init__(self) -> None:
        self.inbound: asyncio.Queue[str] = asyncio.Queue()
        self.outbound: asyncio.Queue[str] = asyncio.Queue()
        self.closed = False

    async def recv(self) -> str:
        if self.closed:
            raise RuntimeError("closed")
        return await self.inbound.get()

    async def send(self, raw: str) -> None:
        if self.closed:
            raise RuntimeError("closed")
        await self.outbound.put(raw)

    async def close(self) -> None:
        self.closed = True

    # Helpers used by the simulated remote.
    async def push_to_client(self, msg: GatewayMessage) -> None:
        await self.inbound.put(msg.to_json())

    async def expect_from_client(self) -> GatewayMessage:
        raw = await self.outbound.get()
        return GatewayMessage.from_json(raw)


def _patch_websockets_connect(fake_ws: FakeRemoteWebSocket, monkeypatch):
    """Make `websockets.connect` return our fake instead of opening a
    real socket. Captures the URL passed for assertions."""
    captured = {"url": None}

    async def fake_connect(url, **kwargs):
        captured["url"] = url
        return fake_ws

    import websockets

    monkeypatch.setattr(websockets, "connect", fake_connect)
    return captured


async def _simulate_remote_accept(
    fake_ws: FakeRemoteWebSocket,
    peer_key: AgentIdentityKey,
) -> tuple[str, GatewayMessage]:
    """Drive the server side of a successful IDENTIFY handshake.

    Sends the connect STATUS frame (with our own identity + a nonce),
    waits for the client's IDENTIFY, validates the signature, and
    sends back IDENTIFY_RESPONSE(accepted=True) with a fresh nonce so
    mutual auth can complete. Returns the (nonce_b64, identify_msg)
    pair for assertions."""
    nonce_b64 = base64.b64encode(make_nonce()).decode("ascii")
    await fake_ws.push_to_client(
        status_message(
            "connected",
            {
                "client_id": "fake-client",
                "identify_challenge": nonce_b64,
                "our_agent_id": peer_key.agent_id,
                "our_public_key": peer_key.public_key_b64(),
            },
        )
    )
    client_identify = await fake_ws.expect_from_client()
    # Verify the client's signature like the real gateway would.
    sig_raw = base64.b64decode(client_identify.data["signature"])
    challenge_raw = base64.b64decode(client_identify.data["challenge"])
    assert verify_signature(
        client_identify.data["public_key"], sig_raw, challenge_raw
    ), "client did not sign our challenge correctly"
    # Mutual-auth nonce we want the client to sign back.
    mutual_nonce = base64.b64encode(make_nonce()).decode("ascii")
    await fake_ws.push_to_client(
        identify_response_message(
            accepted=True,
            trust_level="tofu",
            challenge_b64=mutual_nonce,
        )
    )
    return nonce_b64, client_identify


# ---------------------------------------------------------------------------
# Connect / handshake
# ---------------------------------------------------------------------------


class TestPeerConnect:
    @pytest.mark.asyncio
    async def test_successful_handshake(
        self,
        db: Database,
        my_key: AgentIdentityKey,
        peer_key: AgentIdentityKey,
        monkeypatch,
    ) -> None:
        ledger = TrustLedger(db)
        pm = PeerManager(my_key=my_key, trust_ledger=ledger)
        fake_ws = FakeRemoteWebSocket()
        _patch_websockets_connect(fake_ws, monkeypatch)

        # Run the manager's connect() in parallel with the simulated remote.
        async def remote() -> None:
            await _simulate_remote_accept(fake_ws, peer_key)
            # Drain the mutual-auth IDENTIFY the client sends back so
            # connect() doesn't deadlock waiting on a pending send.
            try:
                await asyncio.wait_for(fake_ws.expect_from_client(), timeout=1.0)
            except TimeoutError:
                pass

        remote_task = asyncio.create_task(remote())
        session = await pm.connect("ws://fake:18789")
        await remote_task

        assert session.agent_id == peer_key.agent_id
        assert session.url == "ws://fake:18789"
        assert session.trust_level == "tofu"

        # Trust ledger learned the peer.
        entry = await ledger.get(peer_key.agent_id)
        assert entry is not None
        assert entry.public_key == peer_key.public_key_b64()

        # Session cached for follow-up sends.
        assert pm.active == [session]

    @pytest.mark.asyncio
    async def test_refuses_peer_without_protocol(
        self,
        db: Database,
        my_key: AgentIdentityKey,
        monkeypatch,
    ) -> None:
        """Old gateway: STATUS frame has no identify_challenge. We
        promised the user a verified peer — refuse rather than silently
        downgrade."""
        ledger = TrustLedger(db)
        pm = PeerManager(my_key=my_key, trust_ledger=ledger)
        fake_ws = FakeRemoteWebSocket()
        _patch_websockets_connect(fake_ws, monkeypatch)

        async def remote() -> None:
            # No identify_challenge → legacy peer.
            await fake_ws.push_to_client(
                status_message("connected", {"client_id": "fake"})
            )

        asyncio.create_task(remote())
        with pytest.raises(PeerError, match="does not support agent identity"):
            await pm.connect("ws://legacy:18789")
        assert fake_ws.closed

    @pytest.mark.asyncio
    async def test_refuses_mismatched_advertised_identity(
        self,
        db: Database,
        my_key: AgentIdentityKey,
        peer_key: AgentIdentityKey,
        monkeypatch,
    ) -> None:
        """Peer's claimed agent_id doesn't derive from the public key
        they advertised — refuse before signing anything."""
        ledger = TrustLedger(db)
        pm = PeerManager(my_key=my_key, trust_ledger=ledger)
        fake_ws = FakeRemoteWebSocket()
        _patch_websockets_connect(fake_ws, monkeypatch)

        async def remote() -> None:
            await fake_ws.push_to_client(
                status_message(
                    "connected",
                    {
                        "client_id": "fake",
                        "identify_challenge": base64.b64encode(make_nonce()).decode(
                            "ascii"
                        ),
                        "our_agent_id": "elo-imposter",  # not derived from pk
                        "our_public_key": peer_key.public_key_b64(),
                    },
                )
            )

        asyncio.create_task(remote())
        with pytest.raises(PeerError, match="does not derive"):
            await pm.connect("ws://imposter:18789")
        assert fake_ws.closed

    @pytest.mark.asyncio
    async def test_refuses_when_peer_responds_negative(
        self,
        db: Database,
        my_key: AgentIdentityKey,
        peer_key: AgentIdentityKey,
        monkeypatch,
    ) -> None:
        ledger = TrustLedger(db)
        pm = PeerManager(my_key=my_key, trust_ledger=ledger)
        fake_ws = FakeRemoteWebSocket()
        _patch_websockets_connect(fake_ws, monkeypatch)

        async def remote() -> None:
            await fake_ws.push_to_client(
                status_message(
                    "connected",
                    {
                        "client_id": "fake",
                        "identify_challenge": base64.b64encode(make_nonce()).decode(
                            "ascii"
                        ),
                        "our_agent_id": peer_key.agent_id,
                        "our_public_key": peer_key.public_key_b64(),
                    },
                )
            )
            # Peer reads the IDENTIFY but rejects.
            await fake_ws.expect_from_client()
            await fake_ws.push_to_client(
                identify_response_message(accepted=False, reason="blocked")
            )

        asyncio.create_task(remote())
        with pytest.raises(PeerError, match="blocked"):
            await pm.connect("ws://blocking:18789")
        assert fake_ws.closed

    @pytest.mark.asyncio
    async def test_trust_conflict_on_connect_refuses(
        self,
        db: Database,
        my_key: AgentIdentityKey,
        peer_key: AgentIdentityKey,
        monkeypatch,
    ) -> None:
        """Same agent_id, different public_key from before → refuse the
        connection rather than silently overwriting."""
        ledger = TrustLedger(db)
        # Pre-record a different key for peer's agent_id.
        await ledger.record_handshake(peer_key.agent_id, "stale-different-key")

        pm = PeerManager(my_key=my_key, trust_ledger=ledger)
        fake_ws = FakeRemoteWebSocket()
        _patch_websockets_connect(fake_ws, monkeypatch)

        async def remote() -> None:
            await _simulate_remote_accept(fake_ws, peer_key)
            try:
                await asyncio.wait_for(fake_ws.expect_from_client(), timeout=1.0)
            except TimeoutError:
                pass

        asyncio.create_task(remote())
        with pytest.raises(PeerError, match="Trust conflict"):
            await pm.connect("ws://rotated:18789")
        assert fake_ws.closed


# ---------------------------------------------------------------------------
# Send / receive
# ---------------------------------------------------------------------------


class TestPeerSendReceive:
    @pytest.mark.asyncio
    async def test_send_returns_accumulated_response(
        self,
        db: Database,
        my_key: AgentIdentityKey,
        peer_key: AgentIdentityKey,
        monkeypatch,
    ) -> None:
        ledger = TrustLedger(db)
        pm = PeerManager(my_key=my_key, trust_ledger=ledger)
        fake_ws = FakeRemoteWebSocket()
        _patch_websockets_connect(fake_ws, monkeypatch)

        async def remote_handshake() -> None:
            await _simulate_remote_accept(fake_ws, peer_key)
            try:
                await asyncio.wait_for(fake_ws.expect_from_client(), timeout=1.0)
            except TimeoutError:
                pass

        asyncio.create_task(remote_handshake())
        session = await pm.connect("ws://fake:18789")

        # Now drive the chat exchange. Peer streams 3 deltas then done.
        async def remote_chat() -> None:
            chat = await fake_ws.expect_from_client()
            assert chat.type == MessageType.CHAT
            assert chat.data["content"] == "say hello"
            await fake_ws.push_to_client(response_message("sess", "Hel", done=False))
            await fake_ws.push_to_client(response_message("sess", "lo, ", done=False))
            await fake_ws.push_to_client(response_message("sess", "world!", done=True))

        asyncio.create_task(remote_chat())
        result = await pm.send(session.agent_id, "say hello", timeout=2.0)
        assert result == "Hello, world!"

    @pytest.mark.asyncio
    async def test_send_to_unknown_peer_raises(
        self, db: Database, my_key: AgentIdentityKey
    ) -> None:
        pm = PeerManager(my_key=my_key, trust_ledger=TrustLedger(db))
        with pytest.raises(PeerError, match="No open session"):
            await pm.send("elo-ghost", "hello")

    @pytest.mark.asyncio
    async def test_send_timeout_raises(
        self,
        db: Database,
        my_key: AgentIdentityKey,
        peer_key: AgentIdentityKey,
        monkeypatch,
    ) -> None:
        """Peer never sends a final RESPONSE → caller gets PeerError,
        not an indefinite hang."""
        ledger = TrustLedger(db)
        pm = PeerManager(my_key=my_key, trust_ledger=ledger)
        fake_ws = FakeRemoteWebSocket()
        _patch_websockets_connect(fake_ws, monkeypatch)

        async def remote_handshake() -> None:
            await _simulate_remote_accept(fake_ws, peer_key)
            try:
                await asyncio.wait_for(fake_ws.expect_from_client(), timeout=1.0)
            except TimeoutError:
                pass

        asyncio.create_task(remote_handshake())
        session = await pm.connect("ws://fake:18789")

        async def silent_remote() -> None:
            # Read the chat but never reply.
            await fake_ws.expect_from_client()

        asyncio.create_task(silent_remote())
        with pytest.raises(PeerError, match="(did not finish|timed out) "):
            await pm.send(session.agent_id, "hi", timeout=0.2)

    @pytest.mark.asyncio
    async def test_send_propagates_peer_error_message(
        self,
        db: Database,
        my_key: AgentIdentityKey,
        peer_key: AgentIdentityKey,
        monkeypatch,
    ) -> None:
        """Peer responds with an ERROR frame → raise PeerError with detail."""
        from core.protocol import error_message

        ledger = TrustLedger(db)
        pm = PeerManager(my_key=my_key, trust_ledger=ledger)
        fake_ws = FakeRemoteWebSocket()
        _patch_websockets_connect(fake_ws, monkeypatch)

        async def remote_handshake() -> None:
            await _simulate_remote_accept(fake_ws, peer_key)
            try:
                await asyncio.wait_for(fake_ws.expect_from_client(), timeout=1.0)
            except TimeoutError:
                pass

        asyncio.create_task(remote_handshake())
        session = await pm.connect("ws://fake:18789")

        async def remote_err() -> None:
            await fake_ws.expect_from_client()
            await fake_ws.push_to_client(error_message("rate limited"))

        asyncio.create_task(remote_err())
        with pytest.raises(PeerError, match="rate limited"):
            await pm.send(session.agent_id, "hi", timeout=2.0)


# ---------------------------------------------------------------------------
# Disconnect / cap
# ---------------------------------------------------------------------------


class TestPeerLifecycle:
    @pytest.mark.asyncio
    async def test_disconnect_closes_session(
        self,
        db: Database,
        my_key: AgentIdentityKey,
        peer_key: AgentIdentityKey,
        monkeypatch,
    ) -> None:
        ledger = TrustLedger(db)
        pm = PeerManager(my_key=my_key, trust_ledger=ledger)
        fake_ws = FakeRemoteWebSocket()
        _patch_websockets_connect(fake_ws, monkeypatch)

        async def remote() -> None:
            await _simulate_remote_accept(fake_ws, peer_key)
            try:
                await asyncio.wait_for(fake_ws.expect_from_client(), timeout=1.0)
            except TimeoutError:
                pass

        asyncio.create_task(remote())
        session = await pm.connect("ws://fake:18789")

        assert pm.active != []
        ok = await pm.disconnect(session.agent_id)
        assert ok is True
        assert pm.active == []
        assert fake_ws.closed
        # Disconnecting unknown agent returns False, doesn't raise.
        assert await pm.disconnect("elo-ghost") is False

    @pytest.mark.asyncio
    async def test_disconnect_all_returns_count(
        self, db: Database, my_key: AgentIdentityKey
    ) -> None:
        """Even with no live sessions, disconnect_all is safe."""
        pm = PeerManager(my_key=my_key, trust_ledger=TrustLedger(db))
        assert await pm.disconnect_all() == 0
