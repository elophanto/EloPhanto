"""swarm_status — List running/completed agents with status."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class SwarmStatusTool(BaseTool):
    """Check the status of spawned coding agents."""

    def __init__(self) -> None:
        self._swarm_manager: Any = None

    @property
    def name(self) -> str:
        return "swarm_status"

    @property
    def description(self) -> str:
        return (
            "List the status of all spawned coding agents, or get details for "
            "a specific agent. Shows profile, task, branch, PR URL, CI status, "
            "and whether the tmux session is still alive."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Optional agent ID to check a specific agent",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._swarm_manager:
            return ToolResult(
                success=False, data={}, error="Swarm system not initialized"
            )

        try:
            agent_id = params.get("agent_id")
            statuses = await self._swarm_manager.get_status(agent_id)
            return ToolResult(
                success=True,
                data={
                    "agents": statuses,
                    "total": len(statuses),
                    "running": sum(1 for s in statuses if s["status"] == "running"),
                },
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"Status check failed: {e}")
