"""voice_lint — deterministic check of a draft against the voice contract."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class VoiceLintTool(BaseTool):
    def __init__(self) -> None:
        self._voice_manager: Any = None

    @property
    def name(self) -> str:
        return "voice_lint"

    @property
    def group(self) -> str:
        return "companies"

    @property
    def description(self) -> str:
        return (
            "Check a draft body against the active company's voice "
            "contract. Returns {passed, violations, suggestions}. "
            "Pure / cheap — no LLM call. Run this BEFORE calling "
            "email_draft / outreach_draft / post_draft so you don't "
            "submit drafts that those tools will refuse. When no "
            "voice.yaml exists for the company, lint always passes."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "channel": {
                    "type": "string",
                    "description": "email | outreach | post (informational)",
                },
                "company_id": {
                    "type": "string",
                    "description": "Defaults to the active company.",
                },
            },
            "required": ["text"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._voice_manager is None:
            return ToolResult(
                success=False,
                error="voice_lint not initialized (missing voice_manager)",
            )
        from core.company import current_company_id

        company_id = str(params.get("company_id") or current_company_id())
        text = str(params.get("text") or "")
        channel = str(params.get("channel") or "")
        result = self._voice_manager.lint(text, company_id=company_id, channel=channel)
        return ToolResult(
            success=True,
            data={
                "company_id": company_id,
                "channel": channel,
                **result.as_dict(),
            },
        )
