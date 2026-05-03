"""Incoming libp2p stream listener — bridges sidecar events into the agent.

When a remote peer opens an /elophanto/1.0.0 stream to us, the Go
sidecar emits a `peer.connected` event with the new stream_id. This
module subscribes to those events, reads the length-prefixed JSON
frame the peer sends, dispatches it through the agent's chat handler
(same path as a Telegram or Discord message), and writes the response
back on the same stream.

Why a separate module instead of inlining into Agent.initialize():
- Lifecycle is independent of the request loop — keeps Agent's
  startup readable.
- Trivial to unit test with a mock P2PSidecar.
- A future merge with PeerManager (so libp2p peers and ws peers share
  one IDENTIFY/trust pipeline) will replace this module wholesale;
  isolating it now makes that swap mechanical.

Wire format (matches the outbound agent_p2p_message tool):
    [4 bytes BE length][JSON envelope]

Envelope:
    {"type": "chat", "channel": "p2p", "data": {"content": "..."}}

Reply written back on the same stream in the same framing, with
`{"type": "response", "data": {"content": "..."}}`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import struct
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

# Hard ceiling on a single inbound frame. Same value as the outbound
# tool — anything larger is almost certainly a hostile peer, not a
# legitimate chat message. Hitting this closes the stream.
_MAX_FRAME_BYTES = 16 * 1024 * 1024


class IncomingStreamListener:
    """Subscribes to a P2PSidecar's events queue and routes inbound
    streams through a chat handler.

    The chat handler is an async callable `(content: str, peer_id: str,
    stream_id: str) -> str`. Its return value is sent back to the peer
    as the response payload. Raising from the handler is logged but
    does NOT take down the listener — one bad message must not block
    other streams.
    """

    def __init__(
        self,
        sidecar: Any,
        chat_handler: Callable[[str, str, str], Awaitable[str]],
        *,
        trust_ledger: Any = None,
    ) -> None:
        self._sidecar = sidecar
        self._handler = chat_handler
        # Optional. When set, every incoming peer is TOFU-pinned (or
        # refused if blocked) BEFORE the chat handler runs. The pubkey
        # is derived deterministically from the libp2p PeerID, so the
        # same agent connecting via wss:// or libp2p shares one trust
        # entry. Listener works without it (no pinning), useful for
        # tests or operators who haven't enabled the identity layer.
        self._trust_ledger = trust_ledger
        self._task: asyncio.Task | None = None
        # Per-stream worker tasks so multiple peers can talk to us
        # concurrently. Tracked so shutdown can cancel them cleanly.
        self._stream_tasks: dict[str, asyncio.Task] = {}

    def start(self) -> None:
        """Launch the event-pump task. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._pump_events(), name="p2p-listener-pump")

    async def stop(self) -> None:
        """Cancel the pump and any per-stream workers. Idempotent."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, BaseException):
                await self._task
            self._task = None
        for sid, task in list(self._stream_tasks.items()):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, BaseException):
                await task
            self._stream_tasks.pop(sid, None)

    async def _pump_events(self) -> None:
        """Drain the sidecar's events queue. For each `peer.connected`
        event with direction=incoming, spawn a worker that handles
        the stream's full lifecycle."""
        while True:
            try:
                event = await self._sidecar.events.get()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("p2p listener event pump errored: %s", e)
                # Don't busy-loop on a broken queue.
                await asyncio.sleep(1)
                continue

            if event.name != "peer.connected":
                continue
            data = event.data or {}
            if data.get("direction") != "incoming":
                # Outgoing connections (we initiated via agent_p2p_connect)
                # are handled by the caller, not this listener.
                continue

            stream_id_raw = data.get("stream_id")
            if not stream_id_raw or not isinstance(stream_id_raw, str):
                continue
            stream_id: str = stream_id_raw
            peer_id = str(data.get("peer_id") or "")
            # One worker per stream so a slow peer doesn't block others.
            task = asyncio.create_task(
                self._handle_stream(stream_id, peer_id),
                name=f"p2p-stream-{stream_id}",
            )
            self._stream_tasks[stream_id] = task

            def _cleanup(_t: asyncio.Task, sid: str = stream_id) -> None:
                self._stream_tasks.pop(sid, None)

            task.add_done_callback(_cleanup)

    async def _handle_stream(self, stream_id: str, peer_id: str) -> None:
        """Read one frame, dispatch to the chat handler, write the reply.

        v1 is single-shot (one request → one response → close). A
        future revision can keep the stream open for back-and-forth
        chat by looping this method until a close frame arrives.
        """
        try:
            # TOFU pin (or refusal) BEFORE we read the message. Even
            # though noise transport already authenticated the peer's
            # PeerID via the handshake, recording the pin gives the
            # operator a single trust ledger across both transports
            # — and lets them block a peer that misbehaves over libp2p
            # the same way they would over wss://.
            if not await self._tofu_check_or_refuse(peer_id, stream_id):
                return

            frame = await self._read_framed(stream_id)
            if frame is None:
                # EOF or zero-length close-frame — nothing to do.
                return
            try:
                envelope = json.loads(frame.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning("p2p stream %s sent non-JSON frame: %s", stream_id, e)
                return

            content = (
                (envelope.get("data") or {}).get("content")
                if isinstance(envelope, dict)
                else None
            )
            if not isinstance(content, str) or not content:
                logger.debug(
                    "p2p stream %s envelope has no chat content; skipping",
                    stream_id,
                )
                return

            try:
                reply_text = await self._handler(content, peer_id, stream_id)
            except Exception as e:
                # Handler failed — return a structured error so the peer
                # can see it instead of a silent timeout. Log full error
                # locally for the operator to debug.
                logger.exception(
                    "p2p chat handler failed for stream %s: %s", stream_id, e
                )
                reply_text = f"[remote agent error: {e}]"

            reply_envelope = {
                "type": "response",
                "data": {"content": reply_text},
            }
            await self._send_framed(
                stream_id,
                json.dumps(reply_envelope).encode("utf-8"),
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # One bad stream must not crash the whole pump.
            logger.warning("p2p stream %s handler crashed: %s", stream_id, e)

    async def _tofu_check_or_refuse(self, peer_id: str, stream_id: str) -> bool:
        """Run the trust check for an incoming peer. Returns True when
        the stream should proceed, False when we should silently drop
        it (peer is blocked, key conflict, or pubkey couldn't be
        derived from the PeerID).

        No ledger configured? Skip the check entirely — connection
        proceeds with no pinning. Useful in tests and for operators
        who haven't enabled the identity layer yet."""
        if self._trust_ledger is None or not peer_id:
            return True
        try:
            from core.agent_identity import derive_agent_id_from_public_key
            from core.peer_p2p_identity import (
                PeerIDDecodeError,
                peer_id_to_ed25519_pubkey_b64,
            )
            from core.trust_ledger import TrustConflict

            try:
                pubkey_b64 = peer_id_to_ed25519_pubkey_b64(peer_id)
            except PeerIDDecodeError as e:
                # Non-Ed25519 peer or malformed PeerID. Don't refuse —
                # we still authenticated them via noise. Just skip the
                # ledger pin so we don't write garbage entries.
                logger.warning("p2p stream %s: skipping TOFU pin (%s)", stream_id, e)
                return True

            agent_id = derive_agent_id_from_public_key(pubkey_b64)
            try:
                entry = await self._trust_ledger.record_handshake(
                    agent_id=agent_id, public_key=pubkey_b64
                )
            except TrustConflict as e:
                # Same agent_id, different pubkey — looks like key
                # rotation or impersonation. Refuse the connection.
                # The owner can run agent_trust_set --rotate to allow
                # the new key after confirming out of band.
                logger.warning(
                    "p2p stream %s refused: trust conflict for %s — "
                    "stored=%s claimed=%s. Use agent_trust_set --rotate "
                    "after confirming out of band.",
                    stream_id,
                    e.agent_id,
                    e.seen_public_key,
                    e.claimed_public_key,
                )
                return False

            if entry.is_blocked:
                logger.warning(
                    "p2p stream %s refused: peer %s is blocked",
                    stream_id,
                    agent_id,
                )
                return False
            return True
        except Exception as e:
            # Any unexpected ledger error — log and let the connection
            # proceed unpinned. Refusing on a ledger bug would lock the
            # operator out of their own agents.
            logger.warning("p2p stream %s TOFU check errored: %s", stream_id, e)
            return True

    async def _read_framed(self, stream_id: str) -> bytes | None:
        """Read one length-prefixed frame. Returns None on EOF or
        zero-length close-frame."""
        try:
            header = await self._read_exact(stream_id, 4)
        except EOFError:
            return None
        (length,) = struct.unpack(">I", header)
        if length == 0:
            return None
        if length > _MAX_FRAME_BYTES:
            logger.warning(
                "p2p stream %s announced oversized frame %d; dropping",
                stream_id,
                length,
            )
            return None
        return await self._read_exact(stream_id, length)

    async def _read_exact(self, stream_id: str, n: int) -> bytes:
        """Loop on stream.recv until exactly n bytes arrive."""
        out = bytearray()
        while len(out) < n:
            result = await self._sidecar.stream_recv(
                stream_id, max_bytes=n - len(out), timeout_ms=30000
            )
            if not result.data:
                if result.eof:
                    raise EOFError(f"peer closed after {len(out)}/{n} bytes")
                # Timed out with no data — treat as a slow peer; loop
                # would spin, so fail closed.
                raise EOFError(f"no data within 30s ({len(out)}/{n} bytes received)")
            out.extend(result.data)
        return bytes(out)

    async def _send_framed(self, stream_id: str, payload: bytes) -> None:
        framed = struct.pack(">I", len(payload)) + payload
        await self._sidecar.stream_send(stream_id, framed)
