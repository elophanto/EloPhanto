"""who_are_you — compiled self-description from DB artifacts."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class WhoAreYouTool(BaseTool):
    """Return the compiled evidence-backed self-description."""

    def __init__(self) -> None:
        self._personality_manager: Any = None
        self._ego_manager: Any = None

    @property
    def group(self) -> str:
        return "identity"

    @property
    def name(self) -> str:
        return "who_are_you"

    @property
    def description(self) -> str:
        return (
            "Compiled self-description from active personality_rules, "
            "nuclear_scenes, and runtime facts registered by live subsystems "
            "(cite-checked). Call when asked who/what you are, then answer "
            "in your own voice from the result — do not freestyle."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._personality_manager:
            return ToolResult(success=False, error="Personality system not initialized")
        felt = None
        caution: list[dict[str, str]] = []
        if self._ego_manager is not None:
            try:
                ego = await self._ego_manager.get_ego()
                felt = getattr(ego, "felt_state", None)
                caution = list(getattr(ego, "caution_rules", []) or [])
            except Exception:
                pass
        # runtime_facts come from PersonalityManager's registered sources
        # (learner, dataset_builder, opt-in tools) — not hardcoded here.
        payload = await self._personality_manager.compile_who_are_you(
            felt_state=felt,
            caution_rules=caution,
        )
        return ToolResult(success=True, data=payload)
