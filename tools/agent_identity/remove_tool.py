"""agent_trust_remove — Drop a peer from the trust ledger entirely."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class AgentTrustRemoveTool(BaseTool):
    """Remove a peer from the trust ledger.

    Distinct from blocking: a removed peer re-enters as TOFU on next
    connection. Use this only when you want to RESET your view of a
    peer (e.g. they legitimately rotated keys and you want a clean
    slate). To prevent reconnection, use ``agent_trust_set
    level=blocked`` instead.
    """

    @property
    def group(self) -> str:
        return "agent_identity"

    def __init__(self) -> None:
        self._trust_ledger: Any = None

    @property
    def name(self) -> str:
        return "agent_trust_remove"

    @property
    def description(self) -> str:
        return (
            "Remove a peer from the trust ledger entirely. WARNING: a "
            "removed peer re-enters as TOFU on next connection — this "
            "is NOT how you block them. Use agent_trust_set "
            "level=blocked to prevent reconnection. Use remove only to "
            "reset your view (e.g. legitimate key rotation)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Peer agent_id (form: elo-<12chars>).",
                },
            },
            "required": ["agent_id"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._trust_ledger:
            return ToolResult(
                success=False, data={}, error="Trust ledger not available."
            )
        agent_id = (params.get("agent_id") or "").strip()
        if not agent_id:
            return ToolResult(success=False, data={}, error="agent_id is required")
        try:
            removed = await self._trust_ledger.remove(agent_id)
            if not removed:
                return ToolResult(
                    success=False,
                    data={},
                    error=f"No peer with agent_id={agent_id!r} in the ledger.",
                )
            return ToolResult(
                success=True,
                data={
                    "agent_id": agent_id,
                    "removed": True,
                    "message": (
                        f"Peer {agent_id} removed from ledger. They will "
                        "re-enter as TOFU on next connection. To prevent "
                        "reconnection, use agent_trust_set level=blocked."
                    ),
                },
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"Remove failed: {e}")
