"""agent_message — Send a chat to a connected peer agent and await reply."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class AgentMessageTool(BaseTool):
    """Send a chat message to a peer and return the response."""

    @property
    def group(self) -> str:
        return "agent_identity"

    def __init__(self) -> None:
        self._peer_manager: Any = None

    @property
    def name(self) -> str:
        return "agent_message"

    @property
    def description(self) -> str:
        return (
            "Send a chat message to a connected peer agent and await "
            "the response. Streamed deltas are accumulated into a "
            "single string; EVENT messages (peer's progress noise) are "
            "ignored. Default timeout is 600s (10 min) — generous "
            "because the peer may be doing real LLM work behind the "
            "request. Requires a prior agent_connect to the peer."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Peer agent_id (form: elo-<12chars>) you previously connected to.",
                },
                "content": {
                    "type": "string",
                    "description": "Chat message to send to the peer.",
                },
                "timeout": {
                    "type": "number",
                    "description": "Seconds to wait for the peer's final response. Default 600.",
                },
            },
            "required": ["agent_id", "content"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._peer_manager:
            return ToolResult(
                success=False, data={}, error="Peer manager not available."
            )
        agent_id = (params.get("agent_id") or "").strip()
        content = (params.get("content") or "").strip()
        if not agent_id or not content:
            return ToolResult(
                success=False,
                data={},
                error="agent_id and content are required",
            )
        timeout = float(params.get("timeout") or 600.0)
        try:
            response = await self._peer_manager.send(agent_id, content, timeout=timeout)
            return ToolResult(
                success=True,
                data={
                    "agent_id": agent_id,
                    "response": response,
                },
            )
        except Exception as e:
            return ToolResult(
                success=False, data={}, error=f"agent_message failed: {e}"
            )
