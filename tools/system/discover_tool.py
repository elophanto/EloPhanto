"""Tool discovery meta-tool.

Allows the agent to search for and activate deferred tools that are not
included in the default tool set for the current task profile.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult, ToolTier


class ToolDiscoverTool(BaseTool):
    """Search for additional tools not currently loaded."""

    _tier_override = ToolTier.CORE  # Always available

    @property
    def name(self) -> str:
        return "tool_discover"

    @property
    def description(self) -> str:
        return (
            "Search for additional tools not currently loaded. "
            "Use when you need a capability not in your current tool set."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "What capability you need "
                        "(e.g. 'send email', 'deploy website', 'crypto payment')"
                    ),
                },
            },
            "required": ["query"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def group(self) -> str:
        return "system"

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        query = params.get("query", "")
        if not query:
            return ToolResult(success=False, error="query parameter is required")

        # _registry is injected by Agent._inject_discover_deps()
        registry = getattr(self, "_registry", None)
        if registry is None:
            return ToolResult(success=False, error="Tool registry not available")

        matches = registry.discover_tools(query.lower())
        if not matches:
            return ToolResult(
                success=True,
                data={"message": "No matching tools found", "tools": []},
            )

        # Mark discovered tools as activated for the current session
        activated_set = getattr(self, "_activated_tools", None)
        if activated_set is not None:
            for t in matches:
                activated_set.add(t.name)

        return ToolResult(
            success=True,
            data={
                "message": f"Found {len(matches)} tools. They are now available for use.",
                "tools": [
                    {"name": t.name, "description": t.description, "group": t.group}
                    for t in matches
                ],
            },
        )
