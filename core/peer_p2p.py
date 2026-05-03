"""Python client for the libp2p sidecar (`bridge/p2p/elophanto-p2pd`).

The agent talks to the Go binary over a Unix socket using newline-
delimited JSON-RPC. This module hides that wire protocol behind an
async client and a context-managed sidecar lifecycle.

Why Go in the middle: see [docs/68-DECENTRALIZED-PEERS-RFC.md].
Short version: py-libp2p is missing DCUtR + parts of the DHT.
go-libp2p is the canonical implementation that IPFS / Filecoin /
Ethereum rely on. We wrap it in a sidecar the same way we already
wrap Playwright in `bridge/browser/`.

Lifecycle:

    async with P2PSidecar(binary_path, socket_path) as p2p:
        await p2p.host_open(private_key_hex=our_key, ...)
        peer_info = await p2p.peer_find(remote_peer_id)
        result = await p2p.peer_connect(remote_peer_id, addrs=peer_info.addrs)
        await p2p.stream_send(result.stream_id, b"hello")
        chunk = await p2p.stream_recv(result.stream_id)

Server-pushed events arrive on `p2p.events` (an asyncio.Queue) — the
gateway integration subscribes to `peer.connected` / `stream.opened`
to wire incoming streams into the existing channel layer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
from base64 import b64decode, b64encode
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel used to flag responses that came back as errors. We surface
# them as P2PError so callers can write `try/except P2PError` instead of
# inspecting dict shape.


class P2PError(RuntimeError):
    """Raised when the sidecar reports an error response, fails to start,
    or the socket dies mid-call. The message is the sidecar's own error
    string verbatim — callers can grep it but shouldn't depend on
    structured codes (we don't ship any in v1)."""


@dataclass
class HostStatus:
    peer_id: str
    listen_addrs: list[str]
    peer_count: int
    # "public" | "private" | "unknown" — comes from libp2p's AutoNAT
    # subsystem. Drives the doctor warning that a private host needs a
    # relay for incoming connections.
    nat_reachability: str


@dataclass
class PeerInfo:
    peer_id: str
    addrs: list[str]


@dataclass
class ConnectResult:
    stream_id: str
    # True when the connection went through a circuit-relay rather than
    # being direct. Caller surfaces this in the UI ("relayed — slower")
    # and the doctor uses it to flag NAT trouble.
    via_relay: bool


@dataclass
class RecvResult:
    data: bytes
    eof: bool


@dataclass
class P2PEvent:
    """Server-pushed event. `name` examples: peer.connected,
    stream.opened, stream.closed, warning."""

    name: str
    data: dict[str, Any] = field(default_factory=dict)


class P2PSidecar:
    """Async client + lifecycle manager for the Go libp2p sidecar.

    Spawns the binary as a child process, connects to its Unix socket,
    and multiplexes RPC requests over a single connection. Server-pushed
    events go to `self.events`.

    The class is async-context-managed so the sidecar dies when the
    agent does — no orphan processes if the agent crashes.
    """

    def __init__(
        self,
        *,
        binary_path: str | Path,
        socket_path: str | Path | None = None,
    ) -> None:
        self._binary = Path(binary_path)
        # Default socket lives in the user's runtime dir + a random
        # suffix so two agents on the same box don't collide.
        if socket_path is None:
            base = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
            socket_path = base / f"elophanto-p2p-{secrets.token_hex(4)}.sock"
        self._socket_path = Path(socket_path)
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self.events: asyncio.Queue[P2PEvent] = asyncio.Queue(maxsize=1024)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> P2PSidecar:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    async def start(self) -> None:
        """Spawn the sidecar binary and wait for the socket to be ready."""
        if not self._binary.exists():
            raise P2PError(
                f"sidecar binary not found at {self._binary} — "
                "run `cd bridge/p2p && go build -o elophanto-p2pd .` first"
            )
        # Pre-clean stale socket from a prior crash — `listen()` fails
        # if the inode already exists.
        if self._socket_path.exists():
            self._socket_path.unlink()
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)

        self._proc = await asyncio.create_subprocess_exec(
            str(self._binary),
            "--socket",
            str(self._socket_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        # Poll for the socket to appear (sidecar takes a moment to bind).
        for _ in range(50):
            if self._socket_path.exists():
                break
            await asyncio.sleep(0.05)
        else:
            stderr = b""
            if self._proc.stderr is not None:
                try:
                    stderr = await asyncio.wait_for(self._proc.stderr.read(2048), 0.5)
                except TimeoutError:
                    pass
            raise P2PError(
                f"sidecar did not bind socket within 2.5s; stderr={stderr!r}"
            )

        # Connect.
        self._reader, self._writer = await asyncio.open_unix_connection(
            str(self._socket_path)
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        logger.info("p2p sidecar started, pid=%s", self._proc.pid)

    async def stop(self) -> None:
        """Terminate the sidecar and clean up. Idempotent."""
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        if self._proc is not None and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except TimeoutError:
                self._proc.kill()
                await self._proc.wait()
            self._proc = None
        if self._socket_path.exists():
            try:
                self._socket_path.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # RPC verbs
    # ------------------------------------------------------------------

    async def host_open(
        self,
        *,
        private_key_hex: str,
        listen_addrs: list[str] | None = None,
        bootstrap: list[str] | None = None,
        relays: list[str] | None = None,
        enable_auto_relay: bool = True,
    ) -> tuple[str, list[str]]:
        """Open the libp2p host. Returns (peer_id, listen_addrs).

        `private_key_hex` is the same Ed25519 seed EloPhanto already
        uses for IDENTIFY — passing it here means our libp2p PeerID is
        deterministically derived from that key, so the same agent
        always advertises the same identity across restarts.
        """
        result = await self._call(
            "host.open",
            {
                "private_key_hex": private_key_hex,
                "listen_addrs": listen_addrs or [],
                "bootstrap": bootstrap or [],
                "relays": relays or [],
                "enable_auto_relay": enable_auto_relay,
            },
        )
        return result["peer_id"], result["listen_addrs"]

    async def host_status(self) -> HostStatus:
        result = await self._call("host.status", {})
        return HostStatus(
            peer_id=result["peer_id"],
            listen_addrs=result["listen_addrs"],
            peer_count=result["peer_count"],
            nat_reachability=result["nat_reachability"],
        )

    async def peer_find(self, peer_id: str, *, timeout_ms: int = 10000) -> PeerInfo:
        result = await self._call(
            "peer.find", {"peer_id": peer_id, "timeout_ms": timeout_ms}
        )
        return PeerInfo(peer_id=result["peer_id"], addrs=result["addrs"])

    async def peer_connect(
        self,
        peer_id: str,
        *,
        addrs: list[str] | None = None,
        protocol_id: str = "/elophanto/1.0.0",
        timeout_ms: int = 30000,
    ) -> ConnectResult:
        """Open a stream to `peer_id`. If `addrs` is supplied the sidecar
        skips DHT lookup and dials directly — pass them when you have
        them (e.g. from a recent peer.find or bootstrap exchange) to
        save a round trip."""
        result = await self._call(
            "peer.connect",
            {
                "peer_id": peer_id,
                "addrs": addrs or [],
                "protocol_id": protocol_id,
                "timeout_ms": timeout_ms,
            },
        )
        return ConnectResult(
            stream_id=result["stream_id"],
            via_relay=result["via_relay"],
        )

    async def stream_send(self, stream_id: str, data: bytes) -> None:
        await self._call(
            "stream.send",
            {"stream_id": stream_id, "data_b64": b64encode(data).decode("ascii")},
        )

    async def stream_recv(
        self,
        stream_id: str,
        *,
        max_bytes: int = 65536,
        timeout_ms: int = 5000,
    ) -> RecvResult:
        result = await self._call(
            "stream.recv",
            {"stream_id": stream_id, "max_bytes": max_bytes, "timeout_ms": timeout_ms},
        )
        return RecvResult(
            data=b64decode(result["data_b64"]),
            eof=result["eof"],
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._writer is None:
            raise P2PError("sidecar not started — call start() or use async-with")
        req_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[req_id] = fut
        payload = (
            json.dumps({"id": req_id, "method": method, "params": params}) + "\n"
        ).encode()
        self._writer.write(payload)
        await self._writer.drain()
        return await fut

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    # Sidecar closed the socket. Fail every pending request
                    # so callers don't hang forever.
                    self._fail_all(P2PError("sidecar socket closed"))
                    return
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning("p2p sidecar: invalid JSON line: %s", e)
                    continue

                # Server-pushed event (no "id"): drop into the events queue.
                if "event" in obj and "id" not in obj:
                    try:
                        self.events.put_nowait(
                            P2PEvent(name=obj["event"], data=obj.get("data") or {})
                        )
                    except asyncio.QueueFull:
                        # Same policy as the Go side: drop rather than
                        # block. Critical lifecycle events should be rare;
                        # if drops are causing real problems, grow the
                        # queue.
                        logger.warning("p2p events queue full — dropping event")
                    continue

                # Response to a pending request.
                req_id = obj.get("id")
                fut = self._pending.pop(req_id, None) if req_id else None
                if fut is None:
                    logger.warning(
                        "p2p sidecar: response with no pending id %r", req_id
                    )
                    continue
                if obj.get("error"):
                    fut.set_exception(P2PError(obj["error"]))
                else:
                    fut.set_result(obj.get("result") or {})
        except asyncio.CancelledError:
            self._fail_all(P2PError("sidecar reader cancelled"))
            raise
        except Exception as e:
            self._fail_all(P2PError(f"sidecar read loop crashed: {e}"))
            raise

    def _fail_all(self, exc: BaseException) -> None:
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def find_sidecar_binary() -> Path | None:
    """Locate the elophanto-p2pd binary.

    Search order:
    1. `ELOPHANTO_P2PD` env var (operator override)
    2. `bridge/p2p/elophanto-p2pd` relative to this file
    3. `$PATH` lookup
    """
    env = os.environ.get("ELOPHANTO_P2PD")
    if env:
        p = Path(env)
        if p.exists():
            return p

    here = Path(__file__).resolve().parent.parent
    candidate = here / "bridge" / "p2p" / "elophanto-p2pd"
    if candidate.exists():
        return candidate

    found = shutil.which("elophanto-p2pd")
    if found:
        return Path(found)
    return None
