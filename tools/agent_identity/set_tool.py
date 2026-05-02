"""agent_trust_set — Promote / demote / block a peer agent."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class AgentTrustSetTool(BaseTool):
    """Set the trust level of a known peer."""

    @property
    def group(self) -> str:
        return "agent_identity"

    def __init__(self) -> None:
        self._trust_ledger: Any = None

    @property
    def name(self) -> str:
        return "agent_trust_set"

    @property
    def description(self) -> str:
        return (
            "Set the trust level for a peer agent. Levels: 'verified' "
            "(owner-confirmed, strongest), 'tofu' (trust-on-first-use, "
            "default after first handshake), 'blocked' (refuse all "
            "future connections). Use after agent_trust_list to review "
            "the peer. Critical: 'verified' is the only level that "
            "implies you've out-of-band confirmed the peer's public key "
            "matches the entity you think it is."
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
                "level": {
                    "type": "string",
                    "enum": ["verified", "tofu", "blocked"],
                    "description": (
                        "verified = owner-confirmed; tofu = trust-on-"
                        "first-use; blocked = refuse all connections."
                    ),
                },
                "notes": {
                    "type": "string",
                    "description": (
                        "Optional free-form note (why you set this level). "
                        "Stored on the peer's ledger entry."
                    ),
                },
            },
            "required": ["agent_id", "level"],
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
        level = (params.get("level") or "").strip()
        notes = (params.get("notes") or "").strip()
        if not agent_id or not level:
            return ToolResult(
                success=False,
                data={},
                error="agent_id and level are required",
            )
        try:
            entry = await self._trust_ledger.set_trust_level(
                agent_id, level, notes=notes
            )
            return ToolResult(
                success=True,
                data={
                    "agent_id": entry.agent_id,
                    "trust_level": entry.trust_level,
                    "notes": entry.notes,
                    "message": (f"Peer {entry.agent_id} now {entry.trust_level}."),
                },
            )
        except KeyError as e:
            return ToolResult(success=False, data={}, error=str(e))
        except ValueError as e:
            return ToolResult(success=False, data={}, error=str(e))
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"Set failed: {e}")
