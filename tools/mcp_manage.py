"""MCP server management tool — lets the agent manage MCP config and connections.

The agent can list, add, remove, and test MCP servers through this tool,
as well as install the MCP SDK if missing. Config changes are written to
config.yaml and take effect on next agent restart.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

import yaml

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_ACTIONS = ("list", "add", "remove", "test", "install")


class MCPManageTool(BaseTool):
    """Manage MCP tool server configuration."""

    @property
    def name(self) -> str:
        return "mcp_manage"

    @property
    def description(self) -> str:
        return (
            "Manage MCP (Model Context Protocol) tool servers. "
            "List, add, remove, or test MCP server connections, "
            "or install the MCP SDK. Config changes are written to config.yaml "
            "and require an agent restart to take effect."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": list(_ACTIONS),
                    "description": (
                        "Action to perform: "
                        "list (show servers), "
                        "add (add a server), "
                        "remove (remove a server), "
                        "test (test a connection), "
                        "install (install MCP SDK)"
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Server name (required for add/remove/test)",
                },
                "transport": {
                    "type": "string",
                    "enum": ["stdio", "http"],
                    "description": "Transport type (for add, default: stdio)",
                },
                "command": {
                    "type": "string",
                    "description": "Command to run (for add, stdio transport)",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command arguments (for add, stdio transport)",
                },
                "url": {
                    "type": "string",
                    "description": "Server URL (for add, http transport)",
                },
                "env": {
                    "type": "object",
                    "description": (
                        "Environment variables (for add). "
                        "Use vault:key_name for secrets."
                    ),
                },
                "headers": {
                    "type": "object",
                    "description": (
                        "HTTP headers (for add, http transport). "
                        "Use vault:key_name for secrets."
                    ),
                },
                "permission_level": {
                    "type": "string",
                    "enum": ["safe", "moderate", "destructive"],
                    "description": "Permission level for tools from this server (default: moderate)",
                },
                "enabled": {
                    "type": "boolean",
                    "description": "Whether the server is enabled (default: true)",
                },
            },
            "required": ["action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        action = params.get("action", "")
        if action not in _ACTIONS:
            return ToolResult(
                success=False,
                error=f"Unknown action '{action}'. Must be one of: {', '.join(_ACTIONS)}",
            )

        try:
            if action == "list":
                return await self._action_list()
            elif action == "add":
                return await self._action_add(params)
            elif action == "remove":
                return await self._action_remove(params)
            elif action == "test":
                return await self._action_test(params)
            elif action == "install":
                return await self._action_install()
            return ToolResult(success=False, error=f"Unhandled action: {action}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _load_config(self) -> tuple[Path, dict]:
        """Load config.yaml from project root."""
        config_path = Path.cwd() / "config.yaml"
        if not config_path.exists():
            return config_path, {}
        with open(config_path) as f:
            return config_path, yaml.safe_load(f) or {}

    def _save_config(self, path: Path, config: dict) -> None:
        """Write config.yaml."""
        with open(path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    async def _action_list(self) -> ToolResult:
        """List all configured MCP servers."""
        _, config = self._load_config()
        mcp = config.get("mcp", {})
        servers = mcp.get("servers", {})
        enabled = mcp.get("enabled", False)

        # Check SDK
        sdk_installed = self._check_sdk()

        if not servers:
            return ToolResult(
                success=True,
                data={
                    "output": (
                        "No MCP servers configured.\n"
                        f"MCP enabled: {enabled}\n"
                        f"SDK installed: {sdk_installed}"
                    )
                },
            )

        lines = [f"MCP enabled: {enabled}", f"SDK installed: {sdk_installed}", ""]
        for name, srv in servers.items():
            transport = "http" if srv.get("url") else "stdio"
            target = (
                srv.get("url")
                or f"{srv.get('command', '?')} {' '.join(srv.get('args', []))}"
            )
            perm = srv.get("permission_level", "moderate")
            srv_enabled = srv.get("enabled", True)
            lines.append(
                f"  {name}: {transport} | {target} | "
                f"permission={perm} | enabled={srv_enabled}"
            )

        return ToolResult(success=True, data={"output": "\n".join(lines)})

    async def _action_add(self, params: dict[str, Any]) -> ToolResult:
        """Add a new MCP server to config."""
        name = params.get("name")
        if not name:
            return ToolResult(success=False, error="'name' is required for add action")

        transport = params.get("transport", "stdio")
        server_cfg: dict[str, Any] = {}

        if transport == "stdio":
            command = params.get("command")
            if not command:
                return ToolResult(
                    success=False,
                    error="'command' is required for stdio transport",
                )
            server_cfg["command"] = command
            if params.get("args"):
                server_cfg["args"] = params["args"]
        elif transport == "http":
            url = params.get("url")
            if not url:
                return ToolResult(
                    success=False,
                    error="'url' is required for http transport",
                )
            server_cfg["url"] = url
            if params.get("headers"):
                server_cfg["headers"] = params["headers"]
        else:
            return ToolResult(
                success=False,
                error=f"Unknown transport '{transport}'. Must be 'stdio' or 'http'.",
            )

        if params.get("env"):
            server_cfg["env"] = params["env"]
        if params.get("permission_level") and params["permission_level"] != "moderate":
            server_cfg["permission_level"] = params["permission_level"]
        if params.get("enabled") is False:
            server_cfg["enabled"] = False

        config_path, config = self._load_config()
        mcp = config.setdefault("mcp", {"enabled": False, "servers": {}})
        servers = mcp.setdefault("servers", {})

        existed = name in servers
        servers[name] = server_cfg
        mcp["enabled"] = True
        self._save_config(config_path, config)

        action_word = "Updated" if existed else "Added"
        return ToolResult(
            success=True,
            data={
                "output": (
                    f"{action_word} MCP server '{name}' ({transport}). "
                    f"MCP enabled in config.\n"
                    f"Restart the agent to connect to this server."
                )
            },
        )

    async def _action_remove(self, params: dict[str, Any]) -> ToolResult:
        """Remove an MCP server from config."""
        name = params.get("name")
        if not name:
            return ToolResult(
                success=False, error="'name' is required for remove action"
            )

        config_path, config = self._load_config()
        servers = config.get("mcp", {}).get("servers", {})

        if name not in servers:
            available = ", ".join(servers.keys()) if servers else "none"
            return ToolResult(
                success=False,
                error=f"Server '{name}' not found. Available: {available}",
            )

        del servers[name]
        self._save_config(config_path, config)

        return ToolResult(
            success=True,
            data={
                "output": (
                    f"Removed MCP server '{name}' from config.\n"
                    f"Restart the agent to apply changes."
                )
            },
        )

    async def _action_test(self, params: dict[str, Any]) -> ToolResult:
        """Test connection to an MCP server."""
        if not self._check_sdk():
            return ToolResult(
                success=False,
                error=(
                    "MCP SDK not installed. " "Use mcp_manage action=install first."
                ),
            )

        name = params.get("name")
        _, config = self._load_config()
        servers = config.get("mcp", {}).get("servers", {})

        if name:
            if name not in servers:
                available = ", ".join(servers.keys()) if servers else "none"
                return ToolResult(
                    success=False,
                    error=f"Server '{name}' not found. Available: {available}",
                )
            targets = {name: servers[name]}
        else:
            if not servers:
                return ToolResult(
                    success=True,
                    data={"output": "No MCP servers configured."},
                )
            targets = servers

        results = await self._test_servers(targets)
        return ToolResult(success=True, data={"output": results})

    async def _test_servers(self, targets: dict) -> str:
        """Connect to servers, discover tools, and return results."""
        from core.config import MCPServerConfig
        from core.mcp_client import MCPServerConnection

        lines: list[str] = []

        for srv_name, srv_dict in targets.items():
            transport = "http" if srv_dict.get("url") else "stdio"
            srv_config = MCPServerConfig(
                name=srv_name,
                transport=transport,
                command=srv_dict.get("command", ""),
                args=srv_dict.get("args", []),
                env=srv_dict.get("env", {}),
                cwd=srv_dict.get("cwd", ""),
                url=srv_dict.get("url", ""),
                headers=srv_dict.get("headers", {}),
                permission_level=srv_dict.get("permission_level", "moderate"),
                timeout_seconds=srv_dict.get("timeout_seconds", 30),
                startup_timeout_seconds=srv_dict.get("startup_timeout_seconds", 30),
            )

            conn = MCPServerConnection(srv_config)
            try:
                ok = await conn.connect()
                if not ok:
                    lines.append(f"{srv_name}: FAILED to connect")
                    continue

                tools = await conn.discover_tools()
                lines.append(f"{srv_name}: Connected — {len(tools)} tools")
                for t in tools:
                    desc = t.get("description", "")
                    if len(desc) > 60:
                        desc = desc[:57] + "..."
                    lines.append(f"  • {t['name']}: {desc}")
            except Exception as e:
                lines.append(f"{srv_name}: ERROR — {e}")
            finally:
                await conn.disconnect()

        return "\n".join(lines)

    async def _action_install(self) -> ToolResult:
        """Install the MCP SDK."""
        if self._check_sdk():
            return ToolResult(
                success=True,
                data={"output": "MCP SDK is already installed."},
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "pip",
                "install",
                "mcp[cli]>=1.0.0",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

            if proc.returncode == 0:
                return ToolResult(
                    success=True,
                    data={
                        "output": (
                            "MCP SDK installed successfully.\n"
                            "Restart the agent to use MCP servers."
                        )
                    },
                )
            else:
                error_text = stderr.decode().strip() if stderr else "Unknown error"
                return ToolResult(
                    success=False,
                    error=f"pip install failed (exit {proc.returncode}): {error_text}",
                )
        except TimeoutError:
            return ToolResult(
                success=False,
                error="MCP SDK installation timed out after 120 seconds.",
            )

    @staticmethod
    def _check_sdk() -> bool:
        """Check if the MCP SDK is importable."""
        try:
            import mcp  # noqa: F401

            return True
        except ImportError:
            return False
