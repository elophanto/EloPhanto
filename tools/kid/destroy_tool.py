"""kid_destroy — Stop, remove the container, drop the volume."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class KidDestroyTool(BaseTool):
    """Destroy a kid: stop the container, remove it, drop its named volume."""

    @property
    def group(self) -> str:
        return "kids"

    def __init__(self) -> None:
        self._kid_manager: Any = None

    @property
    def name(self) -> str:
        return "kid_destroy"

    @property
    def description(self) -> str:
        return (
            "Destroy a kid: stop the container, remove it, drop the named "
            "volume. The kid's outputs are GONE after this — read them "
            "first if you need them. Always destroy kids when done; idle "
            "kids consume the concurrency budget."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "kid_id_or_name": {
                    "type": "string",
                    "description": "kid_id (8-char hex) or name slug.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why destroying (recorded in metadata).",
                },
            },
            "required": ["kid_id_or_name"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

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
            ok = await self._kid_manager.destroy(
                kid_ref, reason=(params.get("reason") or "").strip()
            )
            if not ok:
                return ToolResult(
                    success=False,
                    data={},
                    error=f"No kid found with id or name {kid_ref!r}",
                )
            return ToolResult(
                success=True,
                data={"kid": kid_ref, "destroyed": True},
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"Destroy failed: {e}")
