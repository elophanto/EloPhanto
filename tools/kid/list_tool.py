"""kid_list — List active (and optionally stopped) kids."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class KidListTool(BaseTool):
    """List kids known to the manager."""

    @property
    def group(self) -> str:
        return "kids"

    def __init__(self) -> None:
        self._kid_manager: Any = None

    @property
    def name(self) -> str:
        return "kid_list"

    @property
    def description(self) -> str:
        return (
            "List active kid agents. Call this BEFORE kid_spawn to check "
            "if a suitable kid is already running. Pass include_stopped=true "
            "to also see history."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_stopped": {
                    "type": "boolean",
                    "description": "Include stopped/failed kids (default false).",
                },
            },
            "required": [],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._kid_manager:
            return ToolResult(
                success=False, data={}, error="Kid manager not available."
            )
        try:
            kids = await self._kid_manager.list_kids(
                include_stopped=bool(params.get("include_stopped"))
            )
            return ToolResult(
                success=True,
                data={
                    "count": len(kids),
                    "kids": [
                        {
                            "kid_id": k.kid_id,
                            "name": k.name,
                            "status": k.status,
                            "runtime": k.runtime,
                            "image": k.image,
                            "purpose": k.purpose,
                            "spawned_at": k.spawned_at,
                            "last_active": k.last_active,
                            "vault_scope": k.vault_scope,
                        }
                        for k in kids
                    ],
                },
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"List failed: {e}")
