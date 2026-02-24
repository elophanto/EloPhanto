"""swarm_redirect — Send new instructions to a running agent."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class SwarmRedirectTool(BaseTool):
    """Send new instructions to a running agent mid-task."""

    def __init__(self) -> None:
        self._swarm_manager: Any = None

    @property
    def name(self) -> str:
        return "swarm_redirect"

    @property
    def description(self) -> str:
        return (
            "Send new instructions or guidance to a running agent mid-task. "
            "The instructions are injected into the agent's tmux session. "
            "Use this to course-correct an agent that is going in the wrong "
            "direction, or to provide additional information."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "ID of the running agent to redirect",
                },
                "instructions": {
                    "type": "string",
                    "description": "New instructions or guidance for the agent",
                },
            },
            "required": ["agent_id", "instructions"],
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
        instructions = params.get("instructions", "")
        if not agent_id or not instructions:
            return ToolResult(
                success=False,
                data={},
                error="Both agent_id and instructions are required",
            )

        try:
            ok = await self._swarm_manager.redirect(agent_id, instructions)
            if ok:
                return ToolResult(
                    success=True,
                    data={
                        "agent_id": agent_id,
                        "message": "Instructions sent to the agent.",
                    },
                )
            return ToolResult(
                success=False, data={}, error="Agent not found or not running"
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"Redirect failed: {e}")
