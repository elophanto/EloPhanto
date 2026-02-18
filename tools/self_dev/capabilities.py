"""Self-list capabilities tool — lists all available tools."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class SelfListCapabilitiesTool(BaseTool):
    """Lists all tools (built-in + plugins) with metadata."""

    def __init__(self) -> None:
        self._registry: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return "self_list_capabilities"

    @property
    def description(self) -> str:
        return (
            "List all available tools and capabilities, including built-in tools and "
            "self-created plugins. Use this to understand what you can already do "
            "before creating new tools."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_schemas": {
                    "type": "boolean",
                    "description": "Include full input schemas (default: false)",
                },
            },
            "required": [],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._registry:
            return ToolResult(success=False, error="Registry not available")

        include_schemas = params.get("include_schemas", False)
        tools = self._registry.all_tools()

        capabilities = []
        for tool in tools:
            entry: dict[str, Any] = {
                "name": tool.name,
                "description": tool.description,
                "permission_level": tool.permission_level.value,
            }
            if include_schemas:
                entry["input_schema"] = tool.input_schema
            capabilities.append(entry)

        return ToolResult(
            success=True,
            data={
                "capabilities": capabilities,
                "total": len(capabilities),
            },
        )
