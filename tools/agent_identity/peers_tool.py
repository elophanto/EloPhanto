"""agent_peers — List currently-open outbound sessions to peer agents."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class AgentPeersTool(BaseTool):
    """List active outbound peer sessions (live state, not the trust ledger)."""

    @property
    def group(self) -> str:
        return "agent_identity"

    def __init__(self) -> None:
        self._peer_manager: Any = None

    @property
    def name(self) -> str:
        return "agent_peers"

    @property
    def description(self) -> str:
        return (
            "List peer agents we currently have open outbound "
            "WebSocket sessions to. Distinct from agent_trust_list, "
            "which shows EVERY peer we've ever shaken hands with — "
            "this only shows live connections you can call right now "
            "via agent_message."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._peer_manager:
            return ToolResult(
                success=False, data={}, error="Peer manager not available."
            )
        try:
            sessions = self._peer_manager.active
            return ToolResult(
                success=True,
                data={
                    "count": len(sessions),
                    "peers": [
                        {
                            "agent_id": s.agent_id,
                            "url": s.url,
                            "trust_level": s.trust_level,
                            "connected_at": s.connected_at,
                            "last_used_at": s.last_used_at,
                        }
                        for s in sessions
                    ],
                },
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"Peers list failed: {e}")
