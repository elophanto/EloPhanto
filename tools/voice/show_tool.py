"""voice_show — print the active voice contract for a company."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class VoiceShowTool(BaseTool):
    def __init__(self) -> None:
        self._voice_manager: Any = None

    @property
    def name(self) -> str:
        return "voice_show"

    @property
    def group(self) -> str:
        return "companies"

    @property
    def description(self) -> str:
        return (
            "Show the active voice contract for a company. Returns "
            "has_voice=False when none. Call before drafting. See "
            "voice-extraction-workflow skill."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "string",
                    "description": "Defaults to the active company.",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._voice_manager is None:
            return ToolResult(
                success=False,
                error="voice_show not initialized (missing voice_manager)",
            )
        from core.company import current_company_id

        company_id = str(params.get("company_id") or current_company_id())
        voice = self._voice_manager.get(company_id)
        if voice is None:
            return ToolResult(
                success=True,
                data={
                    "company_id": company_id,
                    "has_voice": False,
                    "next": (
                        "No voice contract for this company. Operator "
                        "can drop exemplars at data/companies/"
                        f"{company_id}/exemplars/<channel>/*.md and "
                        "call voice_extract to propose a voice.yaml."
                    ),
                },
            )
        return ToolResult(
            success=True,
            data={
                "company_id": company_id,
                "has_voice": True,
                "persona": voice.persona,
                "tone": list(voice.tone),
                "length_target": {
                    "min_chars": voice.length_target.min_chars,
                    "max_chars": voice.length_target.max_chars,
                },
                "allowed_hooks": list(voice.allowed_hooks),
                "banned_phrases": list(voice.banned_phrases),
                "banned_patterns": [
                    {"regex": bp.regex, "reason": bp.reason}
                    for bp in voice.banned_patterns
                ],
                "cta_style": voice.cta_style,
                "source_path": voice.source_path,
            },
        )
