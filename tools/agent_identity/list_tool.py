"""agent_trust_list — List peers known to the trust ledger."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class AgentTrustListTool(BaseTool):
    """List agents this instance has shaken hands with."""

    @property
    def group(self) -> str:
        return "agent_identity"

    def __init__(self) -> None:
        self._trust_ledger: Any = None

    @property
    def name(self) -> str:
        return "agent_trust_list"

    @property
    def description(self) -> str:
        return (
            "List peer agents recorded in the trust ledger. Each entry "
            "shows agent_id, public_key (truncated), trust_level "
            "(blocked / tofu / verified), first_seen, last_seen, and "
            "connection_count. Use this before promoting a peer to "
            "verified or blocking one."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_blocked": {
                    "type": "boolean",
                    "description": "Include blocked peers (default true).",
                },
            },
            "required": [],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._trust_ledger:
            return ToolResult(
                success=False,
                data={},
                error=(
                    "Trust ledger not available — agent identity layer "
                    "is not initialized."
                ),
            )
        try:
            include_blocked = bool(params.get("include_blocked", True))
            entries = await self._trust_ledger.list_all(include_blocked=include_blocked)
            return ToolResult(
                success=True,
                data={
                    "count": len(entries),
                    "peers": [
                        {
                            "agent_id": e.agent_id,
                            "public_key_prefix": e.public_key[:16] + "...",
                            "trust_level": e.trust_level,
                            "first_seen": e.first_seen,
                            "last_seen": e.last_seen,
                            "connection_count": e.connection_count,
                            "notes": e.notes,
                        }
                        for e in entries
                    ],
                },
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"List failed: {e}")
