"""godmode_activate — Toggle Pliny's G0DM0D3 on/off or check status."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class GodmodeActivateTool(BaseTool):
    """Toggle Pliny's G0DM0D3 (unrestricted mode) on or off."""

    def __init__(self) -> None:
        self._session: Any = None  # Injected at runtime

    @property
    def group(self) -> str:
        return "system"

    @property
    def name(self) -> str:
        return "godmode_activate"

    @property
    def description(self) -> str:
        return (
            "Toggle G0DM0D3 on or off. When active, godmode directives are "
            "appended to the system prompt (direct, comprehensive, no hedging), "
            "multi-model racing fires all providers in parallel, and context-adaptive "
            "parameter tuning is applied. Normal tools and identity are preserved. "
            "Triggered by 'elophanto, trigger plinys godmode' or similar."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["on", "off", "status"],
                    "description": "Turn godmode on, off, or check status.",
                },
            },
            "required": ["action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        action = params.get("action", "status")

        # Get/set godmode state from session metadata or fallback flag
        current = self._get_godmode_state()

        if action == "status":
            return ToolResult(
                success=True,
                data={
                    "godmode": current,
                    "status": "active" if current else "inactive",
                },
            )

        if action == "on":
            self._set_godmode_state(True)
            return ToolResult(
                success=True,
                data={
                    "godmode": True,
                    "status": "activated",
                    "message": (
                        "G0DM0D3 ACTIVATED — godmode directives appended, "
                        "multi-model racing engaged, autotuned parameters "
                        "applied. All tools and identity preserved."
                    ),
                },
            )

        if action == "off":
            self._set_godmode_state(False)
            return ToolResult(
                success=True,
                data={
                    "godmode": False,
                    "status": "deactivated",
                    "message": "Godmode deactivated. Normal mode restored.",
                },
            )

        return ToolResult(success=False, error=f"Unknown action: {action}")

    def _get_godmode_state(self) -> bool:
        if self._session and hasattr(self._session, "metadata"):
            return self._session.metadata.get("godmode", False)
        return getattr(self, "_fallback_godmode", False)

    def _set_godmode_state(self, value: bool) -> None:
        if self._session and hasattr(self._session, "metadata"):
            self._session.metadata["godmode"] = value
        else:
            self._fallback_godmode = value
