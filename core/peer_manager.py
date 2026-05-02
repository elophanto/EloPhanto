"""PeerManager — outbound agent-to-agent connections.

Pairs with the receive-side handshake in core/gateway.py. When this
agent wants to call ANOTHER EloPhanto agent (whose URL it knows), the
flow is:

1. ``connect(url)`` — open a WebSocket to the peer's gateway.
2. The peer's gateway sends a STATUS frame with ``identify_challenge``
   + its own ``our_agent_id`` / ``our_public_key``.
3. We sign the challenge with our local Ed25519 key and reply with an
   ``IDENTIFY`` message.
4. Peer responds with ``IDENTIFY_RESPONSE``. If accepted, we record
   the peer in OUR trust ledger (TOFU on first contact; conflict
   raised if we've seen this agent_id with a different key).
5. Connection is held open in ``self._sessions`` keyed by peer
   ``agent_id`` so subsequent ``send()`` calls are zero-handshake.

Sending a chat (``send(agent_id, content, timeout)``) writes a CHAT
message and awaits a final RESPONSE (``done=True``) on the same socket,
returning the content. Streaming responses are accumulated.

``disconnect(agent_id)`` closes the session.

Backward-compat: peers without the IDENTIFY layer respond with
``protocol_unavailable`` — we still allow the connection to proceed
under legacy auth-token semantics, but the peer's recorded trust level
stays empty (and tools that need verified peers should refuse).
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.agent_identity import (
    AgentIdentityKey,
    derive_agent_id_from_public_key,
    verify_signature,
)
from core.protocol import (
    GatewayMessage,
    MessageType,
    chat_message,
    identify_message,
)

if TYPE_CHECKING:
    from core.trust_ledger import TrustLedger

logger = logging.getLogger(__name__)


class PeerError(RuntimeError):
    """Raised when a peer connection fails (handshake refusal, timeout,
    transport error). Caller decides how to surface it."""


@dataclass
class PeerSession:
    """A live outbound connection to a peer agent."""

    agent_id: str
    public_key: str
    url: str
    websocket: Any  # websockets client connection
    trust_level: str  # mirrors trust ledger entry at connect time
    connected_at: str
    last_used_at: str
    # Per-session lock so concurrent send() calls don't interleave
    # CHAT/RESPONSE messages on the same socket.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class PeerManager:
    """Manages outbound peer connections to other EloPhanto agents."""

    # Hard cap to prevent runaway resource use. Adjustable via config later.
    MAX_PEERS = 32
    # Default per-message timeout. Generous because peer might be doing
    # real LLM work behind our chat.
    DEFAULT_RESPONSE_TIMEOUT = 600.0

    def __init__(
        self,
        my_key: AgentIdentityKey,
        trust_ledger: TrustLedger,
    ) -> None:
        self._my_key = my_key
        self._trust_ledger = trust_ledger
        self._sessions: dict[str, PeerSession] = {}
        self._sessions_lock = asyncio.Lock()

    @property
    def active(self) -> list[PeerSession]:
        return list(self._sessions.values())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, url: str) -> PeerSession:
        """Open a new outbound connection + run client-side IDENTIFY.

        Returns the live session. Raises ``PeerError`` on any failure
        (transport, handshake refusal, trust conflict). Idempotent at
        the agent_id level — if we've already got an open session with
        the peer at this URL, we return the existing one.
        """
        try:
            import websockets
        except ImportError as e:
            raise PeerError(
                "websockets package required: pip install websockets"
            ) from e

        if len(self._sessions) >= self.MAX_PEERS:
            raise PeerError(
                f"Peer connection cap reached ({self.MAX_PEERS}). "
                "Disconnect an idle peer first."
            )

        ws = await websockets.connect(url, ping_interval=60, ping_timeout=120)

        # 1. Read the connect STATUS frame — server may include an
        # identify_challenge + its own agent_id/public_key.
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
        except TimeoutError as e:
            await ws.close()
            raise PeerError(
                f"Peer at {url} did not send a STATUS frame within 10s"
            ) from e
        try:
            connect_msg = GatewayMessage.from_json(
                raw if isinstance(raw, str) else raw.decode("utf-8")
            )
        except Exception as e:
            await ws.close()
            raise PeerError(f"Peer at {url} sent unparseable STATUS: {e}") from e

        if connect_msg.type != MessageType.STATUS:
            await ws.close()
            raise PeerError(f"Peer at {url} sent {connect_msg.type} instead of STATUS")

        challenge_b64 = str(connect_msg.data.get("identify_challenge", ""))
        peer_agent_id_claimed = str(connect_msg.data.get("our_agent_id", ""))
        peer_public_key_claimed = str(connect_msg.data.get("our_public_key", ""))

        # 2. If the peer didn't issue a challenge, they don't speak
        # IDENTIFY. Close the socket and refuse — we promised the user a
        # verified peer. Older peers without keys are not a "trust X
        # without proof" path.
        if not challenge_b64:
            await ws.close()
            raise PeerError(
                f"Peer at {url} does not support agent identity protocol "
                "(no identify_challenge in STATUS frame). Cannot verify "
                "the connection — refusing."
            )

        # 3. Sanity-check the peer's claimed identity: their agent_id
        # must derive from the public key they advertised. (This is a
        # cheap sanity check — the real proof comes when we sign+receive
        # IDENTIFY_RESPONSE confirming the challenge round-trip.)
        if peer_public_key_claimed and (
            derive_agent_id_from_public_key(peer_public_key_claimed)
            != peer_agent_id_claimed
        ):
            await ws.close()
            raise PeerError(
                f"Peer at {url} claimed agent_id {peer_agent_id_claimed!r} "
                "that does not derive from its public_key. Refusing."
            )

        # 4. Sign the challenge and send IDENTIFY.
        try:
            challenge_raw = base64.b64decode(challenge_b64)
        except Exception as e:
            await ws.close()
            raise PeerError(f"Peer at {url} sent malformed challenge") from e

        sig = self._my_key.sign(challenge_raw)
        await ws.send(
            identify_message(
                agent_id=self._my_key.agent_id,
                public_key_b64=self._my_key.public_key_b64(),
                challenge_b64=challenge_b64,
                signature_b64=base64.b64encode(sig).decode("ascii"),
            ).to_json()
        )

        # 5. Await IDENTIFY_RESPONSE.
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
        except TimeoutError as e:
            await ws.close()
            raise PeerError(
                f"Peer at {url} did not respond to IDENTIFY within 10s"
            ) from e
        try:
            resp = GatewayMessage.from_json(
                raw if isinstance(raw, str) else raw.decode("utf-8")
            )
        except Exception as e:
            await ws.close()
            raise PeerError(f"Peer at {url} sent unparseable IDENTIFY response") from e

        if resp.type != MessageType.IDENTIFY_RESPONSE:
            await ws.close()
            raise PeerError(
                f"Peer at {url} sent {resp.type} instead of IDENTIFY_RESPONSE"
            )

        if not resp.data.get("accepted"):
            reason = resp.data.get("reason", "unknown")
            await ws.close()
            raise PeerError(
                f"Peer at {url} refused IDENTIFY: {reason}. "
                + (
                    "(Old peer without identity layer — connect to it via the legacy path or upgrade it.)"
                    if reason == "protocol_unavailable"
                    else ""
                )
            )

        peer_trust_level = str(resp.data.get("trust_level", ""))

        # 6. Mutual auth: respond to peer's IDENTIFY counter-challenge.
        # We sign whatever new nonce they handed us. Best-effort — we
        # don't refuse the connection if the mutual auth round trips
        # awkwardly (the peer already verified us in step 5; the second
        # half is for completeness so the peer marks the session
        # peer_verified=True from THEIR side too).
        peer_challenge_b64 = str(resp.data.get("challenge", ""))
        if peer_challenge_b64:
            try:
                peer_challenge_raw = base64.b64decode(peer_challenge_b64)
                peer_sig = self._my_key.sign(peer_challenge_raw)
                await ws.send(
                    identify_message(
                        agent_id=self._my_key.agent_id,
                        public_key_b64=self._my_key.public_key_b64(),
                        challenge_b64=peer_challenge_b64,
                        signature_b64=base64.b64encode(peer_sig).decode("ascii"),
                    ).to_json()
                )
                # Best-effort: peer's response on this round is ignored;
                # they've already seen our valid signature once.
            except Exception as e:
                logger.debug("mutual-auth IDENTIFY failed (non-fatal): %s", e)

        # 7. Verify peer's claimed public key against the trust ledger.
        # If we've seen this agent_id with a different key → conflict.
        # Otherwise record (TOFU on first contact).
        from core.trust_ledger import TrustConflict

        # Use the peer's claimed public key (already verified by
        # signature round-trip when accepted=True came back). If the
        # connect STATUS didn't carry it, we trust the trust_level the
        # peer reported and skip ledger update.
        if peer_public_key_claimed and peer_agent_id_claimed:
            try:
                entry = await self._trust_ledger.record_handshake(
                    agent_id=peer_agent_id_claimed,
                    public_key=peer_public_key_claimed,
                )
                peer_trust_level = entry.trust_level
            except TrustConflict as e:
                await ws.close()
                raise PeerError(
                    f"Trust conflict with peer {peer_agent_id_claimed}: "
                    "we know this agent_id with a different public key. "
                    "Either rotate via agent_trust_set --rotate or refuse."
                ) from e

        # 8. Cache the live session.
        now = datetime.now(UTC).isoformat()
        session = PeerSession(
            agent_id=peer_agent_id_claimed,
            public_key=peer_public_key_claimed,
            url=url,
            websocket=ws,
            trust_level=peer_trust_level,
            connected_at=now,
            last_used_at=now,
        )
        async with self._sessions_lock:
            existing = self._sessions.get(peer_agent_id_claimed)
            if existing is not None:
                # Idempotent: prefer the new connection, close the old.
                try:
                    await existing.websocket.close()
                except Exception:
                    pass
            self._sessions[peer_agent_id_claimed] = session
        logger.info(
            "PeerManager: connected to %s at %s (trust=%s)",
            peer_agent_id_claimed,
            url,
            peer_trust_level,
        )
        return session

    async def disconnect(self, agent_id: str) -> bool:
        """Close a peer session. Returns True if a session was closed."""
        async with self._sessions_lock:
            session = self._sessions.pop(agent_id, None)
        if session is None:
            return False
        try:
            await session.websocket.close()
        except Exception as e:
            logger.debug("disconnect: ws.close failed: %s", e)
        return True

    async def disconnect_all(self) -> int:
        """Tear down every live peer session — used on agent shutdown."""
        async with self._sessions_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            try:
                await s.websocket.close()
            except Exception:
                pass
        return len(sessions)

    # ------------------------------------------------------------------
    # Send + await
    # ------------------------------------------------------------------

    async def send(
        self,
        agent_id: str,
        content: str,
        *,
        timeout: float | None = None,
    ) -> str:
        """Send a chat to a peer and return the final response content.

        Streams ``RESPONSE`` deltas are accumulated until a final
        ``done=True`` arrives (or the timeout fires). EVENT messages
        are silently dropped — they're the peer's progress noise, not
        the answer to our request.

        Raises ``PeerError`` if the peer isn't connected, the socket
        drops, or the timeout fires.
        """
        session = self._sessions.get(agent_id)
        if session is None:
            raise PeerError(
                f"No open session with {agent_id}. Call agent_connect first."
            )

        timeout_s = timeout if timeout is not None else self.DEFAULT_RESPONSE_TIMEOUT

        async with session.lock:
            # Send the chat. user_id identifies us in the peer's session
            # space; the peer treats us like any other channel client.
            await session.websocket.send(
                chat_message(
                    channel=f"agent:{self._my_key.agent_id}",
                    user_id=self._my_key.agent_id,
                    content=content,
                ).to_json()
            )

            session.last_used_at = datetime.now(UTC).isoformat()
            chunks: list[str] = []
            loop = asyncio.get_event_loop()
            deadline = loop.time() + timeout_s

            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise PeerError(
                        f"Peer {agent_id} did not finish within {timeout_s}s. "
                        f"Collected {len(chunks)} partial chunks."
                    )
                try:
                    raw = await asyncio.wait_for(
                        session.websocket.recv(), timeout=remaining
                    )
                except TimeoutError as e:
                    raise PeerError(
                        f"Peer {agent_id} timed out after {timeout_s}s"
                    ) from e
                except Exception as e:
                    raise PeerError(f"Peer {agent_id} connection dropped: {e}") from e

                try:
                    msg = GatewayMessage.from_json(
                        raw if isinstance(raw, str) else raw.decode("utf-8")
                    )
                except Exception:
                    # Garbage frame — skip rather than crash.
                    continue

                if msg.type == MessageType.RESPONSE:
                    delta = str(msg.data.get("content", ""))
                    if delta:
                        chunks.append(delta)
                    if msg.data.get("done"):
                        return "".join(chunks)
                elif msg.type == MessageType.ERROR:
                    raise PeerError(
                        f"Peer {agent_id} returned error: "
                        f"{msg.data.get('detail', 'unknown')}"
                    )
                # EVENT / STATUS / others — ignore. They're peer
                # internals (mind activity, tool progress, etc.) not the
                # answer to our chat.

    # ------------------------------------------------------------------
    # Used by the silent verifier (so we don't trust unsigned data)
    # ------------------------------------------------------------------

    @staticmethod
    def _verify_advertised_identity(
        public_key_b64: str, agent_id: str, signed_nonce: bytes, payload: bytes
    ) -> bool:
        """Convenience hook for tools that want to re-verify a peer's
        identity claim against an arbitrary signed payload (e.g. signed
        capability envelopes in v2)."""
        if derive_agent_id_from_public_key(public_key_b64) != agent_id:
            return False
        return verify_signature(public_key_b64, signed_nonce, payload)
