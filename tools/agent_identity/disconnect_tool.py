"""agent_disconnect — Close an outbound session to a peer agent."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class AgentDisconnectTool(BaseTool):
    """Close a peer session opened with agent_connect."""

    @property
    def group(self) -> str:
        return "agent_identity"

    def __init__(self) -> None:
        self._peer_manager: Any = None

    @property
    def name(self) -> str:
        return "agent_disconnect"

    @property
    def description(self) -> str:
        return (
            "Close an outbound session to a peer agent. The trust "
            "ledger entry stays — only the live WebSocket is torn "
            "down. Use this when you're done talking to the peer; "
            "idle sessions count against the peer-connection cap."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Peer agent_id whose session to close.",
                },
            },
            "required": ["agent_id"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._peer_manager:
            return ToolResult(
                success=False, data={}, error="Peer manager not available."
            )
        agent_id = (params.get("agent_id") or "").strip()
        if not agent_id:
            return ToolResult(success=False, data={}, error="agent_id is required")
        try:
            closed = await self._peer_manager.disconnect(agent_id)
            if not closed:
                return ToolResult(
                    success=False,
                    data={},
                    error=f"No open session with {agent_id!r}.",
                )
            return ToolResult(
                success=True,
                data={"agent_id": agent_id, "closed": True},
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"Disconnect failed: {e}")
