"""MCP client manager — connects to external MCP servers and registers their tools.

Manages the lifecycle of multiple MCP server connections (stdio + HTTP).
Each connection discovers tools via tools/list and creates MCPTool wrappers
that plug into the standard EloPhanto ToolRegistry.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from core.config import MCPServerConfig
from tools.base import PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


def _sanitize_server_name(name: str) -> str:
    """Sanitize server name for use in tool namespacing."""
    return re.sub(r"[^a-z0-9]", "_", name.lower()).strip("_")


def _extract_text_content(content: list[Any]) -> str:
    """Extract text from MCP content array."""
    texts: list[str] = []
    for item in content:
        if hasattr(item, "text"):
            texts.append(item.text)
        elif hasattr(item, "data"):
            texts.append(f"[binary data: {getattr(item, 'mimeType', 'unknown')}]")
    return "\n".join(texts) if texts else ""


def _content_to_data(content: list[Any]) -> dict[str, Any]:
    """Convert MCP content array to EloPhanto ToolResult data dict."""
    if not content:
        return {"output": ""}

    # Single text content → flat output
    if len(content) == 1 and hasattr(content[0], "text"):
        return {"output": content[0].text}

    # Multiple content items → structured list
    items: list[dict[str, Any]] = []
    for item in content:
        if hasattr(item, "text"):
            items.append({"type": "text", "content": item.text})
        elif hasattr(item, "data"):
            items.append(
                {
                    "type": getattr(item, "type", "image"),
                    "mimeType": getattr(item, "mimeType", "application/octet-stream"),
                    "size": len(item.data) if item.data else 0,
                }
            )
        elif hasattr(item, "resource"):
            res = item.resource
            items.append(
                {
                    "type": "resource",
                    "uri": getattr(res, "uri", ""),
                    "text": getattr(res, "text", ""),
                }
            )

    if len(items) == 1:
        return items[0]
    return {"output": items}


class MCPServerConnection:
    """Manages a single MCP server connection (stdio or HTTP)."""

    def __init__(self, config: MCPServerConfig, vault: Any = None) -> None:
        self._config = config
        self._vault = vault
        self._session: Any = None
        self._client_context: Any = None
        self._session_context: Any = None
        self._tools: list[dict[str, Any]] = []
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._session is not None

    @property
    def server_name(self) -> str:
        return self._config.name

    def _resolve_vault_refs(self, mapping: dict[str, str]) -> dict[str, str]:
        """Resolve vault:key references in env vars or headers."""
        resolved: dict[str, str] = {}
        for key, value in mapping.items():
            if isinstance(value, str) and value.startswith("vault:"):
                vault_key = value[6:]
                if self._vault:
                    resolved_value = self._vault.get(vault_key)
                    if resolved_value:
                        resolved[key] = (
                            resolved_value
                            if isinstance(resolved_value, str)
                            else str(resolved_value)
                        )
                    else:
                        logger.warning(
                            "MCP server '%s': vault key '%s' not found",
                            self._config.name,
                            vault_key,
                        )
                else:
                    logger.warning(
                        "MCP server '%s': vault ref '%s' but vault not available",
                        self._config.name,
                        value,
                    )
            else:
                resolved[key] = value
        return resolved

    async def connect(self) -> bool:
        """Establish connection to the MCP server.

        Returns True if connection and initialization succeeded.
        """
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError:
            logger.error("MCP SDK not installed. Run: uv pip install 'mcp[cli]'")
            return False

        try:
            if self._config.transport == "stdio":
                return await self._connect_stdio(
                    ClientSession, StdioServerParameters, stdio_client
                )
            elif self._config.transport == "http":
                return await self._connect_http(ClientSession, streamablehttp_client)
            else:
                logger.error(
                    "MCP server '%s': unknown transport '%s'",
                    self._config.name,
                    self._config.transport,
                )
                return False
        except Exception as e:
            logger.warning(
                "MCP server '%s' connection failed: %s", self._config.name, e
            )
            return False

    async def _connect_stdio(
        self,
        ClientSession: type,
        StdioServerParameters: type,
        stdio_client: Any,
    ) -> bool:
        """Connect to a stdio-based MCP server."""
        env = self._resolve_vault_refs(self._config.env)

        server_params = StdioServerParameters(
            command=self._config.command,
            args=self._config.args,
            env=env if env else None,
            cwd=self._config.cwd or None,
        )

        self._client_context = stdio_client(server_params)
        read_stream, write_stream = await self._client_context.__aenter__()

        self._session_context = ClientSession(read_stream, write_stream)
        self._session = await self._session_context.__aenter__()

        await asyncio.wait_for(
            self._session.initialize(),
            timeout=self._config.startup_timeout_seconds,
        )
        self._connected = True
        logger.info("MCP server '%s' connected (stdio)", self._config.name)
        return True

    async def _connect_http(
        self,
        ClientSession: type,
        streamablehttp_client: Any,
    ) -> bool:
        """Connect to an HTTP-based MCP server."""
        headers = self._resolve_vault_refs(self._config.headers)

        self._client_context = streamablehttp_client(
            self._config.url,
            headers=headers if headers else None,
        )
        streams = await self._client_context.__aenter__()
        # streamablehttp_client yields (read, write, session_id)
        read_stream, write_stream = streams[0], streams[1]

        self._session_context = ClientSession(read_stream, write_stream)
        self._session = await self._session_context.__aenter__()

        await asyncio.wait_for(
            self._session.initialize(),
            timeout=self._config.startup_timeout_seconds,
        )
        self._connected = True
        logger.info("MCP server '%s' connected (http)", self._config.name)
        return True

    async def discover_tools(self) -> list[dict[str, Any]]:
        """Call tools/list and return the raw tool definitions."""
        if not self.is_connected:
            return []
        try:
            result = await self._session.list_tools()
            self._tools = [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": (
                        tool.inputSchema
                        if tool.inputSchema
                        else {"type": "object", "properties": {}}
                    ),
                }
                for tool in result.tools
            ]
            logger.info(
                "MCP server '%s': discovered %d tools",
                self._config.name,
                len(self._tools),
            )
            return self._tools
        except Exception as e:
            logger.warning(
                "MCP server '%s': tools/list failed: %s", self._config.name, e
            )
            return []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """Call an MCP tool and convert the result to EloPhanto ToolResult."""
        if not self.is_connected:
            return ToolResult(success=False, error="MCP server not connected")

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(tool_name, arguments),
                timeout=self._config.timeout_seconds,
            )

            if result.isError:
                error_text = _extract_text_content(result.content)
                return ToolResult(success=False, error=error_text or "MCP tool error")

            data = _content_to_data(result.content)
            return ToolResult(success=True, data=data)

        except TimeoutError:
            return ToolResult(
                success=False,
                error=(
                    f"MCP tool '{tool_name}' timed out "
                    f"after {self._config.timeout_seconds}s"
                ),
            )
        except Exception as e:
            return ToolResult(success=False, error=f"MCP call failed: {e}")

    async def disconnect(self) -> None:
        """Gracefully disconnect from the MCP server."""
        self._connected = False

        if self._session_context:
            try:
                await self._session_context.__aexit__(None, None, None)
            except BaseException as e:
                logger.debug(
                    "MCP session exit error for '%s': %s", self._config.name, e
                )
            self._session_context = None
            self._session = None

        if self._client_context:
            try:
                await self._client_context.__aexit__(None, None, None)
            except BaseException as e:
                logger.debug("MCP client exit error for '%s': %s", self._config.name, e)
            self._client_context = None

        logger.info("MCP server '%s' disconnected", self._config.name)


class MCPClientManager:
    """Manages all MCP server connections and tool registration."""

    def __init__(self, vault: Any = None) -> None:
        self._vault = vault
        self._connections: dict[str, MCPServerConnection] = {}

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    @property
    def connected_servers(self) -> list[str]:
        return [name for name, conn in self._connections.items() if conn.is_connected]

    async def connect_all(
        self,
        servers: dict[str, MCPServerConfig],
    ) -> dict[str, bool]:
        """Connect to all configured MCP servers concurrently.

        Returns a dict of server_name -> success status.
        Failed connections are logged and skipped (not fatal).
        """
        results: dict[str, bool] = {}

        async def _connect_one(name: str, config: MCPServerConfig) -> tuple[str, bool]:
            if not config.enabled:
                logger.info("MCP server '%s' disabled, skipping", name)
                return name, False
            conn = MCPServerConnection(config, vault=self._vault)
            success = await conn.connect()
            if success:
                self._connections[name] = conn
            return name, success

        tasks = [_connect_one(name, config) for name, config in servers.items()]
        for coro_result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(coro_result, BaseException):
                logger.warning("MCP connection task failed: %s", coro_result)
                continue
            assert isinstance(coro_result, tuple)
            name, success = coro_result
            results[name] = success

        connected = [n for n, s in results.items() if s]
        if connected:
            logger.info("MCP servers connected: %s", ", ".join(connected))
        return results

    async def discover_and_create_tools(self) -> list[Any]:
        """Discover tools from all connected servers and create MCPTool wrappers.

        Returns a list of MCPTool instances ready for registry registration.
        """
        from tools.mcp_adapter import MCPTool

        all_tools: list[MCPTool] = []

        for name, conn in self._connections.items():
            if not conn.is_connected:
                continue

            sanitized_name = _sanitize_server_name(name)
            raw_tools = await conn.discover_tools()

            # Determine permission level for this server
            perm_str = conn._config.permission_level
            try:
                permission = PermissionLevel(perm_str)
            except ValueError:
                logger.warning(
                    "MCP server '%s': invalid permission '%s', defaulting to MODERATE",
                    name,
                    perm_str,
                )
                permission = PermissionLevel.MODERATE

            for tool_def in raw_tools:
                tool = MCPTool(
                    server_name=sanitized_name,
                    tool_name=tool_def["name"],
                    tool_description=tool_def["description"],
                    tool_input_schema=tool_def["inputSchema"],
                    tool_permission=permission,
                    connection=conn,
                )
                all_tools.append(tool)

        logger.info(
            "Created %d MCP tools from %d servers",
            len(all_tools),
            len(self._connections),
        )
        return all_tools

    async def shutdown(self) -> None:
        """Disconnect all MCP servers gracefully."""
        tasks = [conn.disconnect() for conn in self._connections.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._connections.clear()
        logger.info("All MCP servers disconnected")
