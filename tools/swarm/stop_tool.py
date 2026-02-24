"""swarm_stop — Stop a running agent."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class SwarmStopTool(BaseTool):
    """Stop a running agent by killing its tmux session."""

    def __init__(self) -> None:
        self._swarm_manager: Any = None

    @property
    def name(self) -> str:
        return "swarm_stop"

    @property
    def description(self) -> str:
        return (
            "Stop a running coding agent by killing its tmux session. "
            "The worktree and branch are preserved for manual inspection."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "ID of the agent to stop",
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for stopping the agent",
                },
            },
            "required": ["agent_id"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._swarm_manager:
            return ToolResult(
                success=False, data={}, error="Swarm system not initialized"
            )

        agent_id = params.get("agent_id", "")
        reason = params.get("reason", "user request")
        if not agent_id:
            return ToolResult(success=False, data={}, error="agent_id is required")

        try:
            ok = await self._swarm_manager.stop_agent(agent_id, reason)
            if ok:
                return ToolResult(
                    success=True,
                    data={
                        "agent_id": agent_id,
                        "message": f"Agent stopped. Reason: {reason}",
                    },
                )
            return ToolResult(
                success=False, data={}, error="Agent not found or not running"
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"Stop failed: {e}")
