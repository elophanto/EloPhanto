"""agent_p2p_message — Send a message on an open libp2p stream and read the reply.

The libp2p stream is bidirectional but byte-oriented; we frame each
message as a length-prefixed JSON envelope so multiple messages can
share one stream without ambiguity. Frame format:

    [4 bytes BE length][JSON payload]

JSON envelope shape (matches what core/protocol.py uses for the WS
transport, so a future merge with PeerManager is a one-line swap of
the transport layer):

    {"type": "chat", "channel": "p2p", "user_id": "<peer_pubkey>",
     "data": {"content": "<text>"}}

Returns whatever the peer wrote back on the stream within `timeout_ms`.
For a request/response shape (single send + single read), the default
timeout is enough; for streaming responses the caller can poll
agent_p2p_recv (future) or pass a longer timeout.
"""

from __future__ import annotations

import json
import struct
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class AgentP2PMessageTool(BaseTool):
    @property
    def group(self) -> str:
        return "agent_identity"

    def __init__(self) -> None:
        self._p2p_sidecar: Any = None

    @property
    def name(self) -> str:
        return "agent_p2p_message"

    @property
    def description(self) -> str:
        return (
            "Send a chat message to a peer over an open libp2p stream "
            "and read its reply. Requires a stream_id from a prior "
            "agent_p2p_connect. Frames each message as length-prefixed "
            "JSON so multiple messages can share one stream. Default "
            "timeout 10s — long for the round-trip but bounded so a "
            "stalled peer doesn't hang the agent."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "stream_id": {
                    "type": "string",
                    "description": "Stream id returned by agent_p2p_connect.",
                },
                "content": {
                    "type": "string",
                    "description": "Message body to send to the peer.",
                },
                "channel": {
                    "type": "string",
                    "description": (
                        "Logical channel name on the remote side. Default "
                        "'p2p' — peer routes to its main agent loop."
                    ),
                },
                "timeout_ms": {
                    "type": "integer",
                    "description": ("Round-trip timeout in ms. Default 10000."),
                },
            },
            "required": ["stream_id", "content"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._p2p_sidecar is None:
            return ToolResult(success=False, data={}, error="P2P sidecar not running")
        stream_id = (params.get("stream_id") or "").strip()
        content = params.get("content") or ""
        if not stream_id or not content:
            return ToolResult(
                success=False,
                data={},
                error="`stream_id` and `content` are required",
            )
        channel = params.get("channel") or "p2p"
        timeout_ms = int(params.get("timeout_ms") or 10000)

        envelope = {
            "type": "chat",
            "channel": channel,
            "data": {"content": content},
        }
        payload = json.dumps(envelope).encode("utf-8")
        # 4-byte big-endian length prefix. Bounds: max 4 GiB per message,
        # which is overkill but matches the WS transport's own framing
        # so swapping transports later is a no-op for protocol code.
        framed = struct.pack(">I", len(payload)) + payload

        try:
            await self._p2p_sidecar.stream_send(stream_id, framed)
        except Exception as e:
            return ToolResult(
                success=False,
                data={"stream_id": stream_id},
                error=f"send failed: {e}",
            )

        # Read the reply. We need at least the 4-byte length prefix;
        # then read exactly that many bytes. Peer might split the reply
        # across multiple recv calls, so loop until we have the frame.
        try:
            reply_bytes = await _recv_framed(
                self._p2p_sidecar, stream_id, timeout_ms=timeout_ms
            )
        except TimeoutError as e:
            return ToolResult(
                success=False,
                data={"stream_id": stream_id},
                error=f"reply timeout: {e}",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                data={"stream_id": stream_id},
                error=f"recv failed: {e}",
            )

        # Decode the reply. If the peer replied with a non-JSON payload
        # we surface the raw bytes — useful for debugging non-EloPhanto
        # peers that happen to speak the same protocol id.
        try:
            reply_obj = json.loads(reply_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return ToolResult(
                success=True,
                data={
                    "stream_id": stream_id,
                    "reply_raw_bytes": len(reply_bytes),
                    "warning": "peer reply was not JSON",
                },
            )

        return ToolResult(
            success=True,
            data={
                "stream_id": stream_id,
                "reply": reply_obj,
                "channel": channel,
            },
        )


# ---------------------------------------------------------------------------
# Framing helper
# ---------------------------------------------------------------------------


async def _recv_framed(sidecar: Any, stream_id: str, *, timeout_ms: int) -> bytes:
    """Read one length-prefixed frame from the stream.

    Loops on stream.recv until we have the 4-byte prefix + the payload
    it announces. Each individual recv has the same timeout — a peer
    that goes silent mid-frame will time out on the next recv, not
    block forever.
    """
    # Read the 4-byte length prefix (may arrive in pieces).
    header = await _read_exact(sidecar, stream_id, 4, timeout_ms=timeout_ms)
    (length,) = struct.unpack(">I", header)
    if length == 0:
        return b""
    if length > 16 * 1024 * 1024:
        # Sanity bound — anything > 16 MiB is almost certainly a bug
        # (or hostile peer); refusing here keeps memory usage sane.
        raise ValueError(f"frame too large: {length} bytes")
    return await _read_exact(sidecar, stream_id, length, timeout_ms=timeout_ms)


async def _read_exact(
    sidecar: Any, stream_id: str, n: int, *, timeout_ms: int
) -> bytes:
    """Read exactly `n` bytes — loops over partial reads."""
    out = bytearray()
    while len(out) < n:
        result = await sidecar.stream_recv(
            stream_id, max_bytes=n - len(out), timeout_ms=timeout_ms
        )
        if not result.data:
            if result.eof:
                raise EOFError(f"peer closed stream after {len(out)}/{n} bytes")
            # No data + no EOF means timeout; surface as TimeoutError so
            # the tool returns a clean "reply timeout" error.
            raise TimeoutError(
                f"no data received within {timeout_ms}ms (got {len(out)}/{n})"
            )
        out.extend(result.data)
    return bytes(out)
