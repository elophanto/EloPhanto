"""Tests for the libp2p sidecar Python client.

Two flavors:
- **Mock**: a fake sidecar (Unix-socket echo server) verifies the
  client's request/response framing, error surfacing, event delivery,
  and cleanup. No Go binary required.
- **Integration**: spawns the real elophanto-p2pd binary and runs a
  full lifecycle. Skipped automatically when the binary isn't built.

The async pytest fixture chain we tried first kept hanging at teardown
under pytest-asyncio's auto mode. Replaced with an explicit
`async with mock_pair(...)` pattern which is just as readable and
behaves predictably.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import tempfile
from pathlib import Path

import pytest

from core.peer_p2p import P2PError, P2PSidecar, find_sidecar_binary

# ---------------------------------------------------------------------------
# Mock sidecar — Unix-socket echo server speaking our JSON-RPC dialect
# ---------------------------------------------------------------------------


class MockSidecar:
    """Stand-in for elophanto-p2pd. Records incoming requests, replies
    with whatever the test queues up, can push events on demand."""

    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path
        self.requests: list[dict] = []
        self.responses: dict[int, dict] = {}
        self._server: asyncio.AbstractServer | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._handler_task: asyncio.Task | None = None

    async def start(self) -> None:
        # Pre-clean stale socket from a prior run.
        if self.socket_path.exists():
            self.socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle, path=str(self.socket_path)
        )

    async def stop(self) -> None:
        # Close the active connection first so the handler exits cleanly,
        # otherwise wait_closed() can sit on the open conn.
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        if self._handler_task is not None and not self._handler_task.done():
            self._handler_task.cancel()
            with contextlib.suppress(BaseException):
                await self._handler_task
            self._handler_task = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self.socket_path.exists():
            with contextlib.suppress(OSError):
                self.socket_path.unlink()

    def queue_response(
        self, req_id: int, *, result=None, error: str | None = None
    ) -> None:
        self.responses[req_id] = (
            {"id": req_id, "error": error}
            if error is not None
            else {"id": req_id, "result": result or {}}
        )

    async def push_event(self, name: str, data: dict) -> None:
        """Send a server-pushed event. Must be called after the client
        has connected (otherwise there's no writer yet)."""
        # Wait briefly for the writer to appear.
        for _ in range(50):
            if self._writer is not None:
                break
            await asyncio.sleep(0.01)
        assert self._writer is not None, "no client connected"
        self._writer.write((json.dumps({"event": name, "data": data}) + "\n").encode())
        await self._writer.drain()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._writer = writer
        self._handler_task = asyncio.current_task()
        try:
            while True:
                line = await reader.readline()
                if not line:
                    return
                try:
                    req = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.requests.append(req)
                resp = self.responses.get(req["id"]) or {
                    "id": req["id"],
                    "result": {},
                }
                writer.write((json.dumps(resp) + "\n").encode())
                await writer.drain()
        except (
            ConnectionResetError,
            asyncio.IncompleteReadError,
            asyncio.CancelledError,
        ):
            return


def _short_sock_path() -> Path:
    """macOS caps Unix socket paths at 104 chars; pytest's tmp_path
    blows past that under /private/var/folders/.... Use /tmp + a short
    random suffix instead."""
    f = tempfile.NamedTemporaryFile(
        prefix="ep-", suffix=".sock", delete=False, dir="/tmp"
    )
    f.close()
    p = Path(f.name)
    p.unlink()
    return p


@contextlib.asynccontextmanager
async def mock_pair():
    """Spin up a MockSidecar + connect a P2PSidecar client (skipping the
    binary spawn) directly to its socket. Yields (sidecar, client).

    Inline context manager instead of pytest async fixtures because the
    fixture chain kept hanging at teardown under pytest-asyncio auto
    mode (cause unidentified — direct asyncio works fine, fixture
    machinery doesn't). This pattern sidesteps the issue cleanly."""
    sock = _short_sock_path()
    sidecar = MockSidecar(sock)
    await sidecar.start()
    client = P2PSidecar(binary_path="/nonexistent", socket_path=sock)
    client._reader, client._writer = await asyncio.open_unix_connection(str(sock))
    client._reader_task = asyncio.create_task(client._read_loop())
    try:
        yield sidecar, client
    finally:
        await client.stop()
        await sidecar.stop()


# ---------------------------------------------------------------------------
# Client framing tests
# ---------------------------------------------------------------------------


class TestClientFraming:
    @pytest.mark.asyncio
    async def test_host_open_request_shape(self) -> None:
        """The client must encode params with the exact field names the
        Go side expects — snake_case, not camelCase. Drift here breaks
        the wire silently (Go ignores unknown fields)."""
        async with mock_pair() as (sidecar, client):
            sidecar.queue_response(
                1,
                result={
                    "peer_id": "12D3KooWFake",
                    "listen_addrs": ["/ip4/1.2.3.4/tcp/4001"],
                },
            )
            peer_id, addrs = await client.host_open(
                private_key_hex="aa" * 32,
                listen_addrs=["/ip4/0.0.0.0/tcp/0"],
                bootstrap=["/ip4/9.9.9.9/tcp/4001/p2p/12D3KooWBoot"],
            )
            assert peer_id == "12D3KooWFake"
            assert addrs == ["/ip4/1.2.3.4/tcp/4001"]
            req = sidecar.requests[0]
            assert req["method"] == "host.open"
            assert req["params"]["private_key_hex"] == "aa" * 32
            assert req["params"]["listen_addrs"] == ["/ip4/0.0.0.0/tcp/0"]
            assert req["params"]["bootstrap"] == [
                "/ip4/9.9.9.9/tcp/4001/p2p/12D3KooWBoot"
            ]
            assert req["params"]["enable_auto_relay"] is True

    @pytest.mark.asyncio
    async def test_error_response_raises_p2perror(self) -> None:
        async with mock_pair() as (sidecar, client):
            sidecar.queue_response(1, error="connect failed: timeout")
            with pytest.raises(P2PError, match="connect failed: timeout"):
                await client.peer_connect("12D3KooWFake")

    @pytest.mark.asyncio
    async def test_stream_send_base64_round_trip(self) -> None:
        """Binary payloads must survive base64 — random bytes including
        zero bytes that would otherwise break newline framing."""
        async with mock_pair() as (sidecar, client):
            payload = secrets.token_bytes(512) + b"\x00\xff\n\r"
            sidecar.queue_response(1, result={"ok": True})
            await client.stream_send("s1", payload)
            from base64 import b64decode

            sent = b64decode(sidecar.requests[0]["params"]["data_b64"])
            assert sent == payload

    @pytest.mark.asyncio
    async def test_concurrent_requests_match_by_id(self) -> None:
        """Two requests in flight at once must be matched back to their
        callers by id — never crosswire."""
        async with mock_pair() as (sidecar, client):
            sidecar.queue_response(
                1, result={"peer_id": "A", "addrs": ["/ip4/1.1.1.1/tcp/1"]}
            )
            sidecar.queue_response(
                2, result={"peer_id": "B", "addrs": ["/ip4/2.2.2.2/tcp/2"]}
            )
            a_task = asyncio.create_task(client.peer_find("A"))
            b_task = asyncio.create_task(client.peer_find("B"))
            a, b = await asyncio.gather(a_task, b_task)
            assert a.peer_id == "A" and a.addrs == ["/ip4/1.1.1.1/tcp/1"]
            assert b.peer_id == "B" and b.addrs == ["/ip4/2.2.2.2/tcp/2"]


class TestEventDelivery:
    @pytest.mark.asyncio
    async def test_server_pushed_event_lands_in_queue(self) -> None:
        async with mock_pair() as (sidecar, client):
            await sidecar.push_event(
                "peer.connected",
                {
                    "peer_id": "12D3KooWX",
                    "stream_id": "s1",
                    "direction": "incoming",
                },
            )
            ev = await asyncio.wait_for(client.events.get(), timeout=2)
            assert ev.name == "peer.connected"
            assert ev.data["peer_id"] == "12D3KooWX"
            assert ev.data["stream_id"] == "s1"

    @pytest.mark.asyncio
    async def test_event_with_id_is_not_an_event(self) -> None:
        """Sanity: the read loop only treats messages with no `id` AND
        an `event` field as events. A response that happens to contain
        an `event` key in result must not pollute the queue."""
        async with mock_pair() as (sidecar, client):
            sidecar.queue_response(
                1,
                result={
                    "peer_id": "12D3KooWP",
                    "listen_addrs": [],
                    "peer_count": 0,
                    "nat_reachability": "unknown",
                    # The trap field — must NOT be treated as an event by
                    # the read loop, since the message also has an "id".
                    "event": "not-a-real-event",
                },
            )
            result = await client.host_status()
            assert result.peer_id == "12D3KooWP"
            assert client.events.empty()


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_fails_loudly_when_binary_missing(self) -> None:
        sidecar = P2PSidecar(
            binary_path=Path("/tmp/nope-elophanto-p2pd"),
            socket_path=_short_sock_path(),
        )
        with pytest.raises(P2PError, match="binary not found"):
            await sidecar.start()


# ---------------------------------------------------------------------------
# find_sidecar_binary
# ---------------------------------------------------------------------------


class TestBinaryDiscovery:
    def test_env_var_takes_precedence(self, tmp_path: Path, monkeypatch) -> None:
        fake = tmp_path / "fake-p2pd"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        monkeypatch.setenv("ELOPHANTO_P2PD", str(fake))
        assert find_sidecar_binary() == fake

    def test_returns_none_or_real_path(self, monkeypatch) -> None:
        """If the binary is built locally we'll find it; if not, None.
        Both are valid outcomes for this test."""
        monkeypatch.delenv("ELOPHANTO_P2PD", raising=False)
        result = find_sidecar_binary()
        assert result is None or result.exists()


# ---------------------------------------------------------------------------
# Integration test against the real Go binary (skipped if not built)
# ---------------------------------------------------------------------------


_BINARY = find_sidecar_binary()


@pytest.mark.skipif(
    _BINARY is None,
    reason="elophanto-p2pd binary not built (run `cd bridge/p2p && go build -o elophanto-p2pd .`)",
)
class TestRealSidecar:
    @pytest.mark.asyncio
    async def test_open_status_reports_real_peer_id(self) -> None:
        """Spawn the real binary, open the host, confirm the PeerID is
        well-formed and the listener bound a real local port."""
        sidecar = P2PSidecar(
            binary_path=_BINARY,  # type: ignore[arg-type]
            socket_path=_short_sock_path(),
        )
        async with sidecar:
            peer_id, addrs = await sidecar.host_open(
                private_key_hex=secrets.token_hex(32),
                listen_addrs=["/ip4/127.0.0.1/tcp/0"],
                enable_auto_relay=False,
            )
            # libp2p Ed25519 PeerIDs start with "12D3KooW".
            assert peer_id.startswith("12D3KooW"), f"unexpected peer id: {peer_id}"
            assert any("/ip4/127.0.0.1/tcp/" in a for a in addrs)

            status = await sidecar.host_status()
            assert status.peer_id == peer_id
            assert status.peer_count == 0
