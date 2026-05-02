"""agent_connect — Open an outbound session to another agent's gateway."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class AgentConnectTool(BaseTool):
    """Connect to another EloPhanto agent's gateway and verify identity."""

    @property
    def group(self) -> str:
        return "agent_identity"

    def __init__(self) -> None:
        self._peer_manager: Any = None

    @property
    def name(self) -> str:
        return "agent_connect"

    @property
    def description(self) -> str:
        return (
            "Open a verified outbound connection to another EloPhanto "
            "agent's gateway. Performs the IDENTIFY handshake (Ed25519 "
            "challenge/response). On success, returns the peer's "
            "agent_id and trust_level (from your local trust ledger), "
            "and the session stays open so subsequent agent_message "
            "calls are zero-handshake. Refuses if: (a) the peer doesn't "
            "support the identity protocol, (b) the peer's claimed "
            "agent_id doesn't derive from its public key, (c) the peer "
            "appears in your ledger with a different key (key rotation "
            "or impersonation), or (d) the peer is blocked. Idempotent: "
            "calling twice with the same URL replaces the prior session."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": (
                        "Peer gateway WebSocket URL — typically "
                        "ws://<host>:18789 or wss:// for TLS. Examples: "
                        "ws://192.168.1.20:18789, "
                        "wss://my-other-agent.tailnet.ts.net:18789."
                    ),
                },
            },
            "required": ["url"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._peer_manager:
            return ToolResult(
                success=False,
                data={},
                error=(
                    "Peer manager not available — agent identity layer "
                    "is not initialized."
                ),
            )
        url = (params.get("url") or "").strip()
        if not url:
            return ToolResult(success=False, data={}, error="url is required")
        try:
            session = await self._peer_manager.connect(url)
            return ToolResult(
                success=True,
                data={
                    "agent_id": session.agent_id,
                    "trust_level": session.trust_level,
                    "url": session.url,
                    "connected_at": session.connected_at,
                    "message": (
                        f"Connected to {session.agent_id} "
                        f"(trust={session.trust_level}). "
                        "Use agent_message to send chats; "
                        "agent_disconnect when done."
                    ),
                },
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"Connect failed: {e}")
