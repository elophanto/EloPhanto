"""swarm_archive_project — Archive a swarm project so it's hidden from default listings."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class SwarmArchiveProjectTool(BaseTool):
    """Archive a swarm project. The worktree on disk is left intact for
    inspection; the project is just hidden from default `swarm_list_projects`
    output and rejected by `swarm_spawn` continuation."""

    @property
    def group(self) -> str:
        return "swarm"

    def __init__(self) -> None:
        self._swarm_manager: Any = None

    @property
    def name(self) -> str:
        return "swarm_archive_project"

    @property
    def description(self) -> str:
        return (
            "Archive a swarm project. Use this when a project is dead "
            "(shipped + closed, abandoned, replaced) so it stops appearing "
            "in swarm_list_projects. The worktree on disk is left untouched."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Project name (slug) to archive.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why it's being archived (optional, stored in metadata).",
                },
            },
            "required": ["name"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._swarm_manager:
            return ToolResult(
                success=False, data={}, error="Swarm manager not available."
            )
        name = (params.get("name") or "").strip()
        if not name:
            return ToolResult(success=False, data={}, error="name is required")
        try:
            ok = await self._swarm_manager.archive_project(
                name=name, reason=(params.get("reason") or "").strip()
            )
            if not ok:
                return ToolResult(
                    success=False,
                    data={},
                    error=f"No project named '{name}'.",
                )
            return ToolResult(
                success=True,
                data={"name": name, "archived": True},
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"Archive failed: {e}")
