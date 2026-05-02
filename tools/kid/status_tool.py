"""kid_status — Inspect a single kid's full state."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class KidStatusTool(BaseTool):
    """Get full state for a single kid."""

    @property
    def group(self) -> str:
        return "kids"

    def __init__(self) -> None:
        self._kid_manager: Any = None

    @property
    def name(self) -> str:
        return "kid_status"

    @property
    def description(self) -> str:
        return "Get full state for a single kid by kid_id or name."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "kid_id_or_name": {
                    "type": "string",
                    "description": "kid_id (8-char hex) or name slug.",
                },
            },
            "required": ["kid_id_or_name"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._kid_manager:
            return ToolResult(
                success=False, data={}, error="Kid manager not available."
            )
        kid_ref = (params.get("kid_id_or_name") or "").strip()
        if not kid_ref:
            return ToolResult(
                success=False, data={}, error="kid_id_or_name is required"
            )
        try:
            kid = await self._kid_manager.get_kid(kid_ref)
            if not kid:
                return ToolResult(
                    success=False,
                    data={},
                    error=f"No kid found with id or name {kid_ref!r}",
                )
            return ToolResult(
                success=True,
                data={
                    "kid_id": kid.kid_id,
                    "name": kid.name,
                    "status": kid.status,
                    "runtime": kid.runtime,
                    "image": kid.image,
                    "container_id": kid.container_id,
                    "vault_scope": kid.vault_scope,
                    "volume_name": kid.volume_name,
                    "purpose": kid.purpose,
                    "spawned_at": kid.spawned_at,
                    "last_active": kid.last_active,
                    "completed_at": kid.completed_at,
                    "metadata": kid.metadata,
                },
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"Status failed: {e}")
