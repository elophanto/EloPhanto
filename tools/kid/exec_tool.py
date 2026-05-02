"""kid_exec — Send a task to a running kid."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class KidExecTool(BaseTool):
    """Send a task to a running kid via the gateway."""

    @property
    def group(self) -> str:
        return "kids"

    def __init__(self) -> None:
        self._kid_manager: Any = None

    @property
    def name(self) -> str:
        return "kid_exec"

    @property
    def description(self) -> str:
        return (
            "Send a task to a running kid. The kid runs it inside its "
            "container and reports back via the gateway. Use kid_list "
            "first to find live kids by name or kid_id."
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
                "task": {
                    "type": "string",
                    "description": "Task description for the kid.",
                },
                "timeout": {
                    "type": "number",
                    "description": (
                        "Seconds to wait for the kid's response before "
                        "raising TimeoutError. Default 600 (10 min). "
                        "Generous because kids run real agent loops."
                    ),
                },
            },
            "required": ["kid_id_or_name", "task"],
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
        task = (params.get("task") or "").strip()
        if not kid_ref or not task:
            return ToolResult(
                success=False,
                data={},
                error="kid_id_or_name and task are required",
            )
        timeout = float(params.get("timeout") or 600.0)
        try:
            response = await self._kid_manager.exec(kid_ref, task, timeout=timeout)
            return ToolResult(
                success=True,
                data={
                    "kid": kid_ref,
                    "response": response,
                },
            )
        except TimeoutError as e:
            return ToolResult(
                success=False,
                data={"kid": kid_ref},
                error=str(e),
            )
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"Exec failed: {e}")
