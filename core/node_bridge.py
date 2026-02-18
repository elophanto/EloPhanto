"""Generic async Node.js subprocess bridge (JSON-RPC over stdin/stdout).

Spawns a Node.js script, communicates via newline-delimited JSON, and
provides ``async call(method, params)`` for Python callers.

Usage::

    bridge = NodeBridge("bridge/dist/server.js")
    await bridge.start()
    result = await bridge.call("navigate", {"url": "https://example.com"})
    await bridge.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 120  # seconds per RPC call


class BridgeError(Exception):
    """Raised when a bridge RPC call returns an error."""


class NodeBridge:
    """Async JSON-RPC client that communicates with a Node.js subprocess."""

    def __init__(
        self,
        script: str | Path,
        *,
        cwd: str | Path | None = None,
        node_bin: str = "node",
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._script = str(script)
        self._cwd = str(cwd) if cwd else None
        self._node_bin = node_bin
        self._timeout = timeout

        self._process: asyncio.subprocess.Process | None = None
        self._seq = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._ready = False

    @property
    def is_alive(self) -> bool:
        return (
            self._process is not None
            and self._process.returncode is None
            and self._ready
        )

    async def start(self) -> None:
        """Spawn the Node.js subprocess and wait for the ready signal."""
        if self.is_alive:
            return

        self._process = await asyncio.create_subprocess_exec(
            self._node_bin,
            self._script,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd,
            limit=50 * 1024 * 1024,  # 50 MB — screenshots can be large
        )
        logger.info(
            "Bridge started (pid=%d, script=%s)", self._process.pid, self._script
        )

        # Start background reader for stdout
        self._reader_task = asyncio.create_task(self._read_loop())

        # Start background reader for stderr (logs)
        asyncio.create_task(self._stderr_loop())

        # Wait for the ready signal (id=null, result.ready=true)
        try:
            await asyncio.wait_for(self._wait_ready(), timeout=30)
        except asyncio.TimeoutError:
            await self.stop()
            raise BridgeError("Bridge failed to start within 30 seconds")

    async def stop(self) -> None:
        """Terminate the Node.js subprocess."""
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None

        if self._process and self._process.returncode is None:
            try:
                self._process.stdin.close()  # type: ignore[union-attr]
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except (asyncio.TimeoutError, OSError):
                self._process.kill()
                await self._process.wait()

            logger.info("Bridge stopped (pid=%d)", self._process.pid)

        self._process = None
        self._ready = False

        # Fail all pending calls
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(BridgeError("Bridge stopped"))
        self._pending.clear()

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send an RPC call and return the result.

        Raises ``BridgeError`` on protocol errors or if the bridge returns
        an error response.
        """
        if not self.is_alive:
            raise BridgeError("Bridge is not running")

        self._seq += 1
        msg_id = self._seq
        msg = {"id": msg_id, "method": method, "params": params or {}}

        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future

        line = json.dumps(msg) + "\n"
        self._process.stdin.write(line.encode())  # type: ignore[union-attr]
        await self._process.stdin.drain()  # type: ignore[union-attr]

        try:
            return await asyncio.wait_for(future, timeout=self._timeout)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise BridgeError(f"RPC call '{method}' timed out after {self._timeout}s")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _wait_ready(self) -> None:
        """Wait until the bridge sends the ready signal."""
        while not self._ready:
            await asyncio.sleep(0.05)

    async def _read_loop(self) -> None:
        """Read JSON lines from stdout and dispatch to pending futures."""
        assert self._process and self._process.stdout
        try:
            while True:
                raw = await self._process.stdout.readline()
                if not raw:
                    break  # EOF — process exited

                line = raw.decode().strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Bridge sent non-JSON: %s", line[:200])
                    continue

                msg_id = msg.get("id")

                # Ready signal (id=null)
                if msg_id is None:
                    if msg.get("result", {}).get("ready"):
                        self._ready = True
                        logger.debug("Bridge ready (pid=%s)", msg["result"].get("pid"))
                    continue

                # Match to pending call
                future = self._pending.pop(msg_id, None)
                if not future or future.done():
                    continue

                if "error" in msg:
                    future.set_exception(
                        BridgeError(msg["error"].get("message", "Unknown bridge error"))
                    )
                else:
                    future.set_result(msg.get("result"))

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Bridge reader crashed: %s", exc)
        finally:
            # Fail remaining pending calls
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(BridgeError("Bridge connection lost"))
            self._pending.clear()
            self._ready = False

    async def _stderr_loop(self) -> None:
        """Forward Node.js stderr to Python logging."""
        assert self._process and self._process.stderr
        try:
            while True:
                raw = await self._process.stderr.readline()
                if not raw:
                    break
                line = raw.decode().rstrip()
                if line:
                    logger.debug("[node] %s", line)
        except (asyncio.CancelledError, Exception):
            pass
