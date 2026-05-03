"""Gateway hardening tests — TLS cert loading + verified-peers gate.

These are the load-bearing checks for cross-machine peer connections:
TLS encrypts the wire so URL+token can't be sniffed; the verified-peers
gate flips the trust model from "URL+token = trusted" to "must complete
IDENTIFY." Together they make `gateway.host: 0.0.0.0` actually safe.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.gateway import ClientConnection, Gateway
from core.session import SessionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_gateway(**overrides) -> Gateway:
    """Construct a Gateway without starting a real server."""
    sm = SessionManager(MagicMock())
    agent_mock = MagicMock()
    agent_mock._router = None
    agent_mock._config = None
    defaults = dict(
        agent=agent_mock,
        session_manager=sm,
        host="127.0.0.1",
        port=18789,
        max_sessions=10,
    )
    defaults.update(overrides)
    return Gateway(**defaults)


def _client(
    *,
    is_loopback: bool = True,
    peer_verified: bool = False,
    age_seconds: float = 0.0,
) -> ClientConnection:
    """Build a fake ClientConnection for the gate to evaluate."""
    return ClientConnection(
        client_id="c",
        websocket=MagicMock(),
        is_loopback=is_loopback,
        peer_verified=peer_verified,
        connected_at_monotonic=time.monotonic() - age_seconds,
    )


# ---------------------------------------------------------------------------
# TLS support
# ---------------------------------------------------------------------------


class TestGatewayTLS:
    def test_tls_disabled_by_default(self) -> None:
        gw = _build_gateway()
        assert gw._tls_enabled() is False
        assert gw._build_ssl_context() is None
        assert gw.url == "ws://127.0.0.1:18789"

    def test_tls_enabled_when_both_cert_and_key_set(self, tmp_path: Path) -> None:
        # Generate a self-signed cert+key with the cryptography lib so
        # we don't need openssl on the test runner.
        from datetime import UTC, datetime, timedelta

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
        now = datetime.now(UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

        gw = _build_gateway(tls_cert=str(cert_path), tls_key=str(key_path))
        assert gw._tls_enabled() is True
        ctx = gw._build_ssl_context()
        assert ctx is not None
        assert gw.url == "wss://127.0.0.1:18789"

    def test_tls_partial_config_does_not_enable(self) -> None:
        """Only cert OR only key — must not silently enable TLS with
        missing material."""
        gw1 = _build_gateway(tls_cert="/path/to/cert.pem")
        assert gw1._tls_enabled() is False
        gw2 = _build_gateway(tls_key="/path/to/key.pem")
        assert gw2._tls_enabled() is False

    def test_tls_invalid_paths_raise_loudly(self) -> None:
        """Bad paths must fail loudly so the operator notices, not
        silently fall back to plaintext."""
        gw = _build_gateway(
            tls_cert="/nonexistent/cert.pem",
            tls_key="/nonexistent/key.pem",
        )
        with pytest.raises((FileNotFoundError, OSError)):
            gw._build_ssl_context()


# ---------------------------------------------------------------------------
# Verified-peers gate
# ---------------------------------------------------------------------------


class TestVerifiedPeersGate:
    def test_off_by_default_allows_everything(self) -> None:
        gw = _build_gateway(require_verified_peers=False)
        # Even an unverified, expired-grace, non-loopback peer is fine.
        c = _client(is_loopback=False, peer_verified=False, age_seconds=999)
        ok, reason = gw._peer_verification_check(c)
        assert ok is True
        assert reason == ""

    def test_loopback_always_exempt(self) -> None:
        """Local CLI / Web / VSCode adapters connect over loopback. They
        must NEVER be refused even when require_verified_peers=True —
        otherwise the user's own UI breaks."""
        gw = _build_gateway(require_verified_peers=True, verify_grace_seconds=15)
        c = _client(is_loopback=True, peer_verified=False, age_seconds=999)
        ok, _ = gw._peer_verification_check(c)
        assert ok is True

    def test_verified_peer_allowed(self) -> None:
        gw = _build_gateway(require_verified_peers=True, verify_grace_seconds=15)
        c = _client(is_loopback=False, peer_verified=True, age_seconds=999)
        ok, _ = gw._peer_verification_check(c)
        assert ok is True

    def test_grace_window_lets_unverified_peer_chat(self) -> None:
        """The grace window is critical — without it, the peer's first
        chat would race the IDENTIFY handshake and get refused even
        when about to verify successfully."""
        gw = _build_gateway(require_verified_peers=True, verify_grace_seconds=15)
        c = _client(is_loopback=False, peer_verified=False, age_seconds=2)
        ok, _ = gw._peer_verification_check(c)
        assert ok is True

    def test_expired_grace_unverified_peer_refused(self) -> None:
        gw = _build_gateway(require_verified_peers=True, verify_grace_seconds=15)
        c = _client(is_loopback=False, peer_verified=False, age_seconds=999)
        ok, reason = gw._peer_verification_check(c)
        assert ok is False
        assert "verified-peers mode" in reason
        assert "15s" in reason

    def test_grace_seconds_is_configurable(self) -> None:
        """Custom grace_seconds → different cutoff."""
        gw = _build_gateway(require_verified_peers=True, verify_grace_seconds=60)
        # 30s after connect — within 60s window
        c = _client(is_loopback=False, peer_verified=False, age_seconds=30)
        ok, _ = gw._peer_verification_check(c)
        assert ok is True
        # 90s after connect — past 60s window
        c2 = _client(is_loopback=False, peer_verified=False, age_seconds=90)
        ok, _ = gw._peer_verification_check(c2)
        assert ok is False


# ---------------------------------------------------------------------------
# End-to-end: _handle_chat refuses with verified-peers + expired-grace
# ---------------------------------------------------------------------------


class TestHandleChatGate:
    @pytest.mark.asyncio
    async def test_handle_chat_refuses_unverified_remote(self) -> None:
        """The full _handle_chat path must reject and send an error
        when the gate denies — not just internally check and proceed."""
        from unittest.mock import AsyncMock

        from core.protocol import GatewayMessage, MessageType

        gw = _build_gateway(require_verified_peers=True, verify_grace_seconds=15)
        c = _client(is_loopback=False, peer_verified=False, age_seconds=999)
        c.websocket.send = AsyncMock()

        msg = GatewayMessage(
            type=MessageType.CHAT,
            channel="some-channel",
            user_id="someone",
            data={"content": "hi"},
        )
        await gw._handle_chat(c, msg)

        sent = c.websocket.send.call_args.args[0]
        assert "chat refused" in sent
        assert "verified-peers" in sent

    @pytest.mark.asyncio
    async def test_handle_chat_allows_loopback_unverified(self) -> None:
        """Loopback unverified must pass the gate. (Downstream chat
        handling will still need an agent / session, but the gate
        itself doesn't refuse.)"""
        from unittest.mock import AsyncMock

        from core.protocol import GatewayMessage, MessageType

        gw = _build_gateway(require_verified_peers=True, verify_grace_seconds=15)
        # Stub out agent/session pieces so _handle_chat can short-circuit
        # past the gate without exploding on missing dependencies.
        gw._agent = MagicMock()
        gw._sessions = MagicMock()
        c = _client(is_loopback=True, peer_verified=False, age_seconds=999)
        c.websocket.send = AsyncMock()

        msg = GatewayMessage(
            type=MessageType.CHAT,
            channel="cli",
            user_id="owner",
            data={"content": "hi"},
        )
        # If the gate had refused, we'd see "chat refused" in the first
        # send call. We're not asserting full chat success — just that
        # the gate didn't shortcut.
        try:
            await gw._handle_chat(c, msg)
        except Exception:
            pass  # downstream may explode on the mocks; gate passing is the assertion
        if c.websocket.send.call_args is not None:
            sent = c.websocket.send.call_args.args[0]
            assert "chat refused" not in sent
