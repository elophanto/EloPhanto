"""swarm_spawn — Spawn an external coding agent on a task."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class SwarmSpawnTool(BaseTool):
    """Spawn an external coding agent to work on a task in parallel."""

    @property
    def group(self) -> str:
        return "swarm"

    def __init__(self) -> None:
        self._swarm_manager: Any = None

    @property
    def name(self) -> str:
        return "swarm_spawn"

    @property
    def description(self) -> str:
        return (
            "Spawn an external coding agent (Claude Code, Codex, etc.) to work "
            "on a task in parallel. By default works on the current EloPhanto project "
            "(self-dev). CRITICAL: For ANY task that is NOT about modifying EloPhanto "
            "itself (e.g. building a website, creating an app, new project), you MUST "
            "set repo='new'. This prevents the agent from creating branches and PRs "
            "on our main GitHub repo. Only omit 'repo' for actual self-dev tasks "
            "(bug fixes, features, refactoring of EloPhanto)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Description of the task for the agent",
                },
                "repo": {
                    "type": "string",
                    "description": (
                        "Target repository. Can be a GitHub URL "
                        "(e.g. 'https://github.com/org/repo'), a local path, "
                        "or 'new' to create a fresh project. "
                        "Omit to work on the current project (self-dev)."
                    ),
                },
                "profile": {
                    "type": "string",
                    "description": (
                        "Agent profile (e.g. 'claude-code', 'codex'). "
                        "Auto-selects if omitted."
                    ),
                },
                "branch_name": {
                    "type": "string",
                    "description": "Custom git branch name (auto-generated if omitted)",
                },
                "extra_context": {
                    "type": "string",
                    "description": "Additional context to include in the agent's prompt",
                },
            },
            "required": ["task"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._swarm_manager:
            import shutil

            hints: list[str] = []
            if not shutil.which("tmux"):
                hints.append("tmux is not installed (run: brew install tmux)")
            if not shutil.which("git"):
                hints.append("git is not installed")
            hint_str = "; ".join(hints) if hints else "swarm.enabled is false in config"
            return ToolResult(
                success=False,
                data={},
                error=f"Swarm not available: {hint_str}. "
                "Tell the user what's missing so they can fix it.",
            )

        task = params.get("task", "").strip()
        if not task:
            return ToolResult(
                success=False, data={}, error="Task description is required"
            )

        try:
            agent = await self._swarm_manager.spawn(
                task=task,
                repo=params.get("repo"),
                profile_name=params.get("profile"),
                branch_name=params.get("branch_name"),
                extra_context=params.get("extra_context", ""),
            )
            return ToolResult(
                success=True,
                data={
                    "agent_id": agent.agent_id,
                    "profile": agent.profile,
                    "branch": agent.branch,
                    "worktree_path": agent.worktree_path,
                    "tmux_session": agent.tmux_session,
                    "message": (
                        f"Agent '{agent.profile}' spawned on branch "
                        f"'{agent.branch}' at {agent.worktree_path}. "
                        f"I'll notify you when it completes."
                    ),
                },
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"Spawn failed: {e}")
