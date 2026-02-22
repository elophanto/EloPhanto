"""MCP tool adapter — wraps a single MCP server tool as a BaseTool.

Each instance holds a reference to its parent MCPServerConnection (which owns
the ClientSession). Tool execution delegates to session.call_tool().
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from tools.base import BaseTool, PermissionLevel, ToolResult

if TYPE_CHECKING:
    from core.mcp_client import MCPServerConnection

logger = logging.getLogger(__name__)


class MCPTool(BaseTool):
    """Wraps a single tool from an MCP server as an EloPhanto BaseTool."""

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        tool_description: str,
        tool_input_schema: dict[str, Any],
        tool_permission: PermissionLevel,
        connection: MCPServerConnection,
    ) -> None:
        self._server_name = server_name
        self._raw_tool_name = tool_name
        self._namespaced_name = f"mcp_{server_name}_{tool_name}"
        self._description = tool_description
        self._input_schema = tool_input_schema
        self._permission = tool_permission
        self._connection = connection

    @property
    def name(self) -> str:
        return self._namespaced_name

    @property
    def description(self) -> str:
        return f"[MCP:{self._server_name}] {self._description}"

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def permission_level(self) -> PermissionLevel:
        return self._permission

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Execute the MCP tool via the server connection."""
        if not self._connection.is_connected:
            return ToolResult(
                success=False,
                error=f"MCP server '{self._server_name}' is not connected",
            )
        try:
            return await self._connection.call_tool(self._raw_tool_name, params)
        except Exception as e:
            logger.error("MCP tool '%s' failed: %s", self._namespaced_name, e)
            return ToolResult(success=False, error=f"MCP tool execution failed: {e}")
