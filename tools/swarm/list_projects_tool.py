"""swarm_list_projects — List long-lived swarm project workspaces."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class SwarmListProjectsTool(BaseTool):
    """List swarm projects so the planner can decide whether to update an
    existing project or spawn a fresh one."""

    @property
    def group(self) -> str:
        return "swarm"

    def __init__(self) -> None:
        self._swarm_manager: Any = None

    @property
    def name(self) -> str:
        return "swarm_list_projects"

    @property
    def description(self) -> str:
        return (
            "List existing swarm projects (long-lived workspaces shared across "
            "multiple agent spawns). Call this BEFORE spawning a new project — "
            "if the user asks to update, extend, or fix something previously "
            "built, find the project name here and pass it to swarm_spawn so "
            "the agent reuses the worktree and sees the prior code."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_archived": {
                    "type": "boolean",
                    "description": "Include archived projects in the listing (default false).",
                },
            },
            "required": [],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._swarm_manager:
            return ToolResult(
                success=False, data={}, error="Swarm manager not available."
            )
        try:
            projects = await self._swarm_manager.list_projects(
                include_archived=bool(params.get("include_archived"))
            )
            return ToolResult(
                success=True,
                data={
                    "count": len(projects),
                    "projects": [
                        {
                            "name": p.name,
                            "repo_kind": p.repo_kind,
                            "repo": p.repo,
                            "worktree_path": p.worktree_path,
                            "main_branch": p.main_branch,
                            "last_branch": p.last_branch,
                            "last_pr_url": p.last_pr_url,
                            "agents_run": p.agents_run,
                            "status": p.status,
                            "created_at": p.created_at,
                            "last_spawn_at": p.last_spawn_at,
                            "description": p.description,
                        }
                        for p in projects
                    ],
                },
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"List failed: {e}")
