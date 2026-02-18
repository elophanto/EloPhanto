"""Hub tools — search and install skills from EloPhantoHub.

These tools let the agent discover and install new skills dynamically
when it encounters tasks without relevant local skills.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class HubSearchTool(BaseTool):
    """Search EloPhantoHub for skills matching a query."""

    _hub: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return "hub_search"

    @property
    def description(self) -> str:
        return (
            "Search the EloPhantoHub skill registry for skills that match "
            "a query or topic. Returns matching skills with descriptions "
            "and install commands."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g. 'gmail automation', 'docker')",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tag filters",
                },
            },
            "required": ["query"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._hub:
            return ToolResult(
                success=False, error="EloPhantoHub not configured"
            )

        try:
            results = await self._hub.search(
                params["query"], tags=params.get("tags")
            )
            return ToolResult(
                success=True,
                data={
                    "results": [
                        {
                            "name": s.name,
                            "description": s.description,
                            "version": s.version,
                            "author": s.author,
                            "tags": s.tags,
                            "downloads": s.downloads,
                        }
                        for s in results
                    ],
                    "count": len(results),
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class HubInstallTool(BaseTool):
    """Install a skill from EloPhantoHub."""

    _hub: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return "hub_install"

    @property
    def description(self) -> str:
        return (
            "Install a skill from EloPhantoHub by name. Use hub_search "
            "first to find available skills."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name to install (from hub_search results)",
                },
            },
            "required": ["name"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._hub:
            return ToolResult(
                success=False, error="EloPhantoHub not configured"
            )

        try:
            installed = await self._hub.install(params["name"])
            return ToolResult(
                success=True,
                data={
                    "installed": installed,
                    "message": (
                        f"Skill '{installed}' installed from EloPhantoHub. "
                        f"Use skill_read to load it."
                    ),
                },
            )
        except FileExistsError:
            return ToolResult(
                success=False,
                error=f"Skill '{params['name']}' is already installed",
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
