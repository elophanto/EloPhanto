"""godmode_activate — Toggle G0DM0D3 on/off, check status, or test providers."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class GodmodeActivateTool(BaseTool):
    """Toggle G0DM0D3 on/off, check status, or test which providers comply."""

    def __init__(self) -> None:
        self._session: Any = None  # Injected at runtime
        self._router: Any = None  # Injected for test action

    @property
    def group(self) -> str:
        return "system"

    @property
    def name(self) -> str:
        return "godmode_activate"

    @property
    def description(self) -> str:
        return (
            "Toggle G0DM0D3 on or off, check status, or test providers. "
            "When active: model-specific directives appended to system prompt, "
            "multi-model racing with less-filtered model preference, "
            "context-adaptive parameter tuning. Use 'test' to see which "
            "providers comply with godmode directives."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["on", "off", "status", "test"],
                    "description": (
                        "on/off: toggle godmode. status: check current state. "
                        "test: send canary query to all providers and report "
                        "which comply (score, refusals, model family)."
                    ),
                },
            },
            "required": ["action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        action = params.get("action", "status")

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
                        "G0DM0D3 ACTIVATED — model-specific directives, "
                        "multi-model racing with less-filtered preference, "
                        "autotuned parameters. All tools preserved."
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

        if action == "test":
            return await self._run_test()

        return ToolResult(success=False, error=f"Unknown action: {action}")

    async def _run_test(self) -> ToolResult:
        """Test which providers/models comply with godmode directives."""
        if not self._router:
            return ToolResult(success=False, error="Router not available for testing.")

        from core.godmode import test_godmode

        report = await test_godmode(self._router)
        return ToolResult(success=True, data=report)

    def _get_godmode_state(self) -> bool:
        if self._session and hasattr(self._session, "metadata"):
            return self._session.metadata.get("godmode", False)
        return getattr(self, "_fallback_godmode", False)

    def _set_godmode_state(self, value: bool) -> None:
        if self._session and hasattr(self._session, "metadata"):
            self._session.metadata["godmode"] = value
        else:
            self._fallback_godmode = value
