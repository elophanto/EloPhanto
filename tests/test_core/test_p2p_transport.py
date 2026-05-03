"""Tests for the P2P transport tools (connect/message/disconnect),
agent_discover's p2p method, and the IncomingStreamListener.

These exercise the tool/listener logic against a mock P2PSidecar.
The libp2p plumbing itself is covered by test_peer_p2p.py and the
two-machine cross-NAT smoke procedure in the RFC."""

from __future__ import annotations

import asyncio
import json
import struct
from typing import Any
from unittest.mock import AsyncMock

import pytest

from core.peer_p2p import (
    ConnectResult,
    P2PEvent,
    PeerInfo,
    RecvResult,
)
from core.peer_p2p_listener import IncomingStreamListener
from tools.agent_identity.discover_tool import AgentDiscoverTool
from tools.agent_identity.p2p_connect_tool import AgentP2PConnectTool
from tools.agent_identity.p2p_disconnect_tool import AgentP2PDisconnectTool
from tools.agent_identity.p2p_message_tool import AgentP2PMessageTool

# ---------------------------------------------------------------------------
# Mock sidecar — minimal stand-in covering just what these tools call
# ---------------------------------------------------------------------------


class FakeSidecar:
    """Records calls + returns canned values. Each method matches the
    real P2PSidecar's signature so the tools can't tell the
    difference."""

    def __init__(self) -> None:
        self.peer_find_calls: list[tuple[str, int]] = []
        self.peer_connect_calls: list[dict[str, Any]] = []
        self.stream_send_calls: list[tuple[str, bytes]] = []
        self.stream_recv_calls: list[tuple[str, int, int]] = []
        self.find_result: PeerInfo | Exception = PeerInfo(
            peer_id="12D3KooWZ", addrs=["/ip4/1.2.3.4/tcp/4001"]
        )
        self.connect_result: ConnectResult | Exception = ConnectResult(
            stream_id="s1", via_relay=False
        )
        # Single byte buffer that recv slices off in max_bytes-sized
        # chunks. Mirrors how the real sidecar respects max_bytes; the
        # tools' _read_exact loop will issue several recvs to assemble
        # a full frame.
        self._recv_buffer: bytearray = bytearray()
        self.events: asyncio.Queue[P2PEvent] = asyncio.Queue()

    async def peer_find(self, peer_id: str, *, timeout_ms: int = 10000) -> PeerInfo:
        self.peer_find_calls.append((peer_id, timeout_ms))
        if isinstance(self.find_result, Exception):
            raise self.find_result
        return self.find_result

    async def peer_connect(
        self,
        peer_id: str,
        *,
        addrs: list[str] | None = None,
        protocol_id: str = "/elophanto/1.0.0",
        timeout_ms: int = 30000,
    ) -> ConnectResult:
        self.peer_connect_calls.append(
            {
                "peer_id": peer_id,
                "addrs": addrs,
                "protocol_id": protocol_id,
                "timeout_ms": timeout_ms,
            }
        )
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
    ) -> RecvResult:
        self.stream_recv_calls.append((stream_id, max_bytes, timeout_ms))
        if not self._recv_buffer:
            return RecvResult(data=b"", eof=True)
        take = min(max_bytes, len(self._recv_buffer))
        chunk = bytes(self._recv_buffer[:take])
        del self._recv_buffer[:take]
        return RecvResult(data=chunk, eof=False)

    def queue_recv_bytes(self, payload: bytes) -> None:
        """Append bytes to the read buffer. stream_recv will hand them
        out in max_bytes-sized chunks across multiple calls — same
        contract as the real sidecar."""
        self._recv_buffer.extend(payload)


def _frame(payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + payload


# ---------------------------------------------------------------------------
# agent_discover --method=p2p
# ---------------------------------------------------------------------------


class TestDiscoverP2PMethod:
    @pytest.mark.asyncio
    async def test_returns_addrs_for_resolved_peer(self) -> None:
        tool = AgentDiscoverTool()
        tool._p2p_sidecar = FakeSidecar()
        result = await tool.execute({"method": "p2p", "peer_id": "12D3KooWX"})
        assert result.success
        assert result.data["method"] == "p2p"
        assert result.data["addrs"] == ["/ip4/1.2.3.4/tcp/4001"]
        assert result.data["reachable"] is True
        # Sidecar received the lookup with the supplied peer id.
        assert tool._p2p_sidecar.peer_find_calls == [("12D3KooWX", 10000)]

    @pytest.mark.asyncio
    async def test_p2p_without_peer_id_errors(self) -> None:
        tool = AgentDiscoverTool()
        tool._p2p_sidecar = FakeSidecar()
        result = await tool.execute({"method": "p2p"})
        assert not result.success
        assert "peer_id" in result.error

    @pytest.mark.asyncio
    async def test_p2p_without_sidecar_errors_with_hint(self) -> None:
        tool = AgentDiscoverTool()
        # No sidecar wired in — represents peers.enabled=false case.
        result = await tool.execute({"method": "p2p", "peer_id": "12D3KooWX"})
        assert not result.success
        assert "peers.enabled" in result.error

    @pytest.mark.asyncio
    async def test_dht_failure_surfaces_as_error(self) -> None:
        tool = AgentDiscoverTool()
        sidecar = FakeSidecar()
        sidecar.find_result = RuntimeError("no peers in routing table")
        tool._p2p_sidecar = sidecar
        result = await tool.execute({"method": "p2p", "peer_id": "12D3KooWX"})
        assert not result.success
        assert "no peers in routing table" in result.error
        # Still includes the peer id we tried, for operator triage.
        assert result.data["peer_id"] == "12D3KooWX"


# ---------------------------------------------------------------------------
# agent_p2p_connect
# ---------------------------------------------------------------------------


class TestP2PConnect:
    @pytest.mark.asyncio
    async def test_connect_passes_through_addrs_when_supplied(self) -> None:
        tool = AgentP2PConnectTool()
        tool._p2p_sidecar = FakeSidecar()
        result = await tool.execute(
            {
                "peer_id": "12D3KooWZ",
                "addrs": ["/ip4/9.9.9.9/tcp/4001"],
                "timeout_ms": 5000,
            }
        )
        assert result.success
        assert result.data["stream_id"] == "s1"
        assert result.data["via_relay"] is False
        # Sidecar received the addrs we passed (skips DHT path).
        call = tool._p2p_sidecar.peer_connect_calls[0]
        assert call["peer_id"] == "12D3KooWZ"
        assert call["addrs"] == ["/ip4/9.9.9.9/tcp/4001"]
        assert call["timeout_ms"] == 5000

    @pytest.mark.asyncio
    async def test_via_relay_flag_drives_hint(self) -> None:
        tool = AgentP2PConnectTool()
        sidecar = FakeSidecar()
        sidecar.connect_result = ConnectResult(stream_id="s1", via_relay=True)
        tool._p2p_sidecar = sidecar
        result = await tool.execute({"peer_id": "12D3KooWZ"})
        assert result.success
        assert result.data["via_relay"] is True
        assert "circuit-relay" in result.data["transport_hint"]

    @pytest.mark.asyncio
    async def test_no_sidecar_returns_clear_error(self) -> None:
        tool = AgentP2PConnectTool()
        result = await tool.execute({"peer_id": "12D3KooWZ"})
        assert not result.success
        assert "peers.enabled" in result.error

    @pytest.mark.asyncio
    async def test_missing_peer_id_errors(self) -> None:
        tool = AgentP2PConnectTool()
        tool._p2p_sidecar = FakeSidecar()
        result = await tool.execute({})
        assert not result.success
        assert "peer_id" in result.error


# ---------------------------------------------------------------------------
# agent_p2p_message — round trip with framing
# ---------------------------------------------------------------------------


class TestP2PMessage:
    @pytest.mark.asyncio
    async def test_send_then_receive_round_trip(self) -> None:
        tool = AgentP2PMessageTool()
        sidecar = FakeSidecar()
        # Queue the framed reply the tool will read back.
        reply_envelope = {"type": "response", "data": {"content": "hi back"}}
        sidecar.queue_recv_bytes(_frame(json.dumps(reply_envelope).encode("utf-8")))
        tool._p2p_sidecar = sidecar

        result = await tool.execute({"stream_id": "s1", "content": "hello"})
        assert result.success
        assert result.data["reply"] == reply_envelope

        # Sidecar received a length-prefixed JSON envelope with the
        # expected chat shape.
        assert len(sidecar.stream_send_calls) == 1
        sent_stream, sent_bytes = sidecar.stream_send_calls[0]
        assert sent_stream == "s1"
        (sent_len,) = struct.unpack(">I", sent_bytes[:4])
        assert sent_len == len(sent_bytes) - 4
        sent_envelope = json.loads(sent_bytes[4:].decode("utf-8"))
        assert sent_envelope["type"] == "chat"
        assert sent_envelope["channel"] == "p2p"
        assert sent_envelope["data"]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_peer_eof_before_reply_surfaces_as_error(self) -> None:
        """If the peer half-closes before sending a frame, we get a
        clean recv failed error, not a hang."""
        tool = AgentP2PMessageTool()
        sidecar = FakeSidecar()
        # Empty queue + EOF on first recv.
        tool._p2p_sidecar = sidecar
        result = await tool.execute(
            {"stream_id": "s1", "content": "hello", "timeout_ms": 1000}
        )
        assert not result.success
        assert "recv failed" in result.error or "reply timeout" in result.error

    @pytest.mark.asyncio
    async def test_non_json_reply_returns_warning_not_crash(self) -> None:
        tool = AgentP2PMessageTool()
        sidecar = FakeSidecar()
        sidecar.queue_recv_bytes(_frame(b"\x00\x01\x02 not json"))
        tool._p2p_sidecar = sidecar
        result = await tool.execute({"stream_id": "s1", "content": "hi"})
        assert result.success
        assert "warning" in result.data
        assert result.data["warning"]


# ---------------------------------------------------------------------------
# agent_p2p_disconnect
# ---------------------------------------------------------------------------


class TestP2PDisconnect:
    @pytest.mark.asyncio
    async def test_sends_close_frame_and_succeeds(self) -> None:
        tool = AgentP2PDisconnectTool()
        sidecar = FakeSidecar()
        tool._p2p_sidecar = sidecar
        result = await tool.execute({"stream_id": "s1"})
        assert result.success
        # Close frame is a 4-byte zero-length prefix.
        assert sidecar.stream_send_calls == [("s1", struct.pack(">I", 0))]

    @pytest.mark.asyncio
    async def test_send_failure_does_not_fail_disconnect(self) -> None:
        """Disconnect must be idempotent — peer might have already gone
        away. Failing the close frame must not propagate."""
        tool = AgentP2PDisconnectTool()
        sidecar = FakeSidecar()
        sidecar.stream_send = AsyncMock(side_effect=RuntimeError("peer gone"))  # type: ignore[method-assign]
        tool._p2p_sidecar = sidecar
        result = await tool.execute({"stream_id": "s1"})
        assert result.success


# ---------------------------------------------------------------------------
# IncomingStreamListener
# ---------------------------------------------------------------------------


class TestIncomingStreamListener:
    @pytest.mark.asyncio
    async def test_routes_incoming_stream_through_handler(self) -> None:
        sidecar = FakeSidecar()
        # Queue the bytes the listener will read off the incoming stream.
        sidecar.queue_recv_bytes(
            _frame(
                json.dumps(
                    {"type": "chat", "channel": "p2p", "data": {"content": "ping"}}
                ).encode("utf-8")
            )
        )

        # Capture what the handler sees + return a known response.
        seen: dict[str, str] = {}

        async def handler(content: str, peer_id: str, stream_id: str) -> str:
            seen.update(content=content, peer_id=peer_id, stream_id=stream_id)
            return "pong"

        listener = IncomingStreamListener(sidecar=sidecar, chat_handler=handler)
        listener.start()
        try:
            # Push the peer.connected event the listener subscribes to.
            await sidecar.events.put(
                P2PEvent(
                    name="peer.connected",
                    data={
                        "stream_id": "s1",
                        "peer_id": "12D3KooWX",
                        "direction": "incoming",
                    },
                )
            )
            # Wait briefly for the worker to read + handle + reply.
            for _ in range(50):
                if sidecar.stream_send_calls:
                    break
                await asyncio.sleep(0.02)
        finally:
            await listener.stop()

        assert seen == {
            "content": "ping",
            "peer_id": "12D3KooWX",
            "stream_id": "s1",
        }
        # Listener wrote back a framed JSON response with our handler's text.
        assert len(sidecar.stream_send_calls) == 1
        _, framed = sidecar.stream_send_calls[0]
        (length,) = struct.unpack(">I", framed[:4])
        envelope = json.loads(framed[4 : 4 + length].decode("utf-8"))
        assert envelope["type"] == "response"
        assert envelope["data"]["content"] == "pong"

    @pytest.mark.asyncio
    async def test_outgoing_event_ignored(self) -> None:
        """direction='outgoing' means we initiated the connection — the
        outbound caller handles it, not the listener."""
        sidecar = FakeSidecar()

        async def handler(*_args: Any) -> str:
            raise AssertionError("handler must NOT be called for outgoing")

        listener = IncomingStreamListener(sidecar=sidecar, chat_handler=handler)
        listener.start()
        try:
            await sidecar.events.put(
                P2PEvent(
                    name="peer.connected",
                    data={
                        "stream_id": "s1",
                        "peer_id": "X",
                        "direction": "outgoing",
                    },
                )
            )
            await asyncio.sleep(0.1)
        finally:
            await listener.stop()
        # No work happened.
        assert sidecar.stream_send_calls == []

    @pytest.mark.asyncio
    async def test_handler_failure_returns_error_envelope(self) -> None:
        """One bad handler call must not crash the listener AND must
        return an error envelope to the peer instead of hanging them."""
        sidecar = FakeSidecar()
        sidecar.queue_recv_bytes(
            _frame(
                json.dumps(
                    {"type": "chat", "channel": "p2p", "data": {"content": "boom"}}
                ).encode("utf-8")
            )
        )

        async def handler(*_args: Any) -> str:
            raise RuntimeError("handler exploded")

        listener = IncomingStreamListener(sidecar=sidecar, chat_handler=handler)
        listener.start()
        try:
            await sidecar.events.put(
                P2PEvent(
                    name="peer.connected",
                    data={
                        "stream_id": "s1",
                        "peer_id": "X",
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
        _, framed = sidecar.stream_send_calls[0]
        (length,) = struct.unpack(">I", framed[:4])
        envelope = json.loads(framed[4 : 4 + length].decode("utf-8"))
        assert envelope["type"] == "response"
        assert "remote agent error" in envelope["data"]["content"]
        assert "handler exploded" in envelope["data"]["content"]
