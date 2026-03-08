"""RPC server for sandboxed code execution.

Listens on a Unix domain socket and dispatches tool calls from the
sandbox child process. Runs in the parent (agent) process so all
tool execution goes through the normal permission/approval flow.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

# Tools the sandbox is allowed to call
ALLOWED_TOOLS = frozenset(
    {
        "web_search",
        "web_extract",
        "file_read",
        "file_write",
        "file_list",
        "knowledge_search",
        "shell_execute",
    }
)

# Max tool calls per sandbox session
MAX_TOOL_CALLS = 50


class RPCServer:
    """Unix socket RPC server for sandbox tool dispatch."""

    def __init__(self, registry: Any, executor: Any) -> None:
        self._registry = registry
        self._executor = executor
        self._socket_path = ""
        self._server: asyncio.AbstractServer | None = None
        self._call_count = 0

    @property
    def socket_path(self) -> str:
        return self._socket_path

    async def start(self) -> str:
        """Start the RPC server and return the socket path."""
        self._socket_path = os.path.join(
            tempfile.gettempdir(), f"elophanto_rpc_{os.getpid()}.sock"
        )
        # Clean up stale socket
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)

        self._call_count = 0
        self._server = await asyncio.start_unix_server(
            self._handle_client, path=self._socket_path
        )
        logger.info("RPC server listening on %s", self._socket_path)
        return self._socket_path

    async def stop(self) -> None:
        """Stop the RPC server and clean up."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._socket_path and os.path.exists(self._socket_path):
            os.unlink(self._socket_path)
            self._socket_path = ""

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single RPC connection (one per sandbox session)."""
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break

                try:
                    request = json.loads(line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    response = {"id": 0, "success": False, "error": "Invalid JSON"}
                    writer.write(json.dumps(response).encode("utf-8") + b"\n")
                    await writer.drain()
                    continue

                req_id = request.get("id", 0)
                tool_name = request.get("tool", "")
                params = request.get("params", {})

                response = await self._dispatch(req_id, tool_name, params)
                writer.write(json.dumps(response).encode("utf-8") + b"\n")
                await writer.drain()

        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _dispatch(
        self, req_id: int, tool_name: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Dispatch a single tool call."""
        if tool_name not in ALLOWED_TOOLS:
            return {
                "id": req_id,
                "success": False,
                "error": f"Tool '{tool_name}' not available in sandbox. "
                f"Allowed: {', '.join(sorted(ALLOWED_TOOLS))}",
            }

        self._call_count += 1
        if self._call_count > MAX_TOOL_CALLS:
            return {
                "id": req_id,
                "success": False,
                "error": f"Tool call limit exceeded ({MAX_TOOL_CALLS})",
            }

        tool = self._registry.get(tool_name)
        if not tool:
            return {
                "id": req_id,
                "success": False,
                "error": f"Tool '{tool_name}' not registered",
            }

        try:
            result = await tool.execute(params)
            return {
                "id": req_id,
                "success": result.success,
                "data": result.data if result.success else None,
                "error": result.error if not result.success else None,
            }
        except Exception as e:
            logger.warning("RPC tool error (%s): %s", tool_name, e)
            return {"id": req_id, "success": False, "error": str(e)}
