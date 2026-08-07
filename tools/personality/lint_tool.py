"""personality_lint — deterministic stance lint (re-lint fail-closed)."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class PersonalityLintTool(BaseTool):
    def __init__(self) -> None:
        self._personality_manager: Any = None

    @property
    def group(self) -> str:
        return "identity"

    @property
    def name(self) -> str:
        return "personality_lint"

    @property
    def description(self) -> str:
        return (
            "Lint text against active personality_rules. Applies deterministic "
            "brevity/anti_hype rewrite then re-lints fail-closed."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "enforce": {
                    "type": "boolean",
                    "description": "If true, rewrite+re-lint; else report only",
                },
            },
            "required": ["text"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._personality_manager:
            return ToolResult(success=False, error="Personality system not initialized")
        text = str(params.get("text") or "")
        enforce = bool(params.get("enforce", True))
        if enforce:
            out, result = await self._personality_manager.lint_and_enforce(text)
            if not result.passed:
                return ToolResult(
                    success=False,
                    error="; ".join(result.violations) or "personality_lint failed",
                    data=result.as_dict(),
                )
            return ToolResult(
                success=True,
                data={"text": out, **result.as_dict()},
            )
        result = await self._personality_manager.lint(text)
        return ToolResult(
            success=result.passed,
            data=result.as_dict(),
            error=(
                None
                if result.passed
                else ("; ".join(result.violations) or "personality_lint failed")
            ),
        )
