"""Skill tools — read and list available skills."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class SkillReadTool(BaseTool):
    """Reads a skill's SKILL.md content to learn best practices before starting a task."""

    def __init__(self) -> None:
        self._skill_manager: Any = None

    @property
    def name(self) -> str:
        return "skill_read"

    @property
    def description(self) -> str:
        return (
            "Read a skill's SKILL.md file to learn best practices before starting "
            "a task. Skills contain step-by-step instructions, patterns, and examples "
            "for specific types of work. ALWAYS read the relevant skill before "
            "starting a task if one matches."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill to read (e.g., 'browser-automation')",
                },
            },
            "required": ["skill_name"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._skill_manager:
            return ToolResult(success=False, error="Skill manager not available")

        skill_name = params["skill_name"]
        content = self._skill_manager.read_skill(skill_name)

        if content is None:
            available = [s.name for s in self._skill_manager.list_skills()]
            return ToolResult(
                success=False,
                error=f"Skill '{skill_name}' not found. Available: {', '.join(available)}",
            )

        return ToolResult(
            success=True,
            data={"skill_name": skill_name, "content": content},
        )


class SkillListTool(BaseTool):
    """Lists all available skills with their descriptions and triggers."""

    def __init__(self) -> None:
        self._skill_manager: Any = None

    @property
    def name(self) -> str:
        return "skill_list"

    @property
    def description(self) -> str:
        return (
            "List all available skills with their descriptions and trigger keywords. "
            "Use this to discover which skills are available before starting a task."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._skill_manager:
            return ToolResult(success=False, error="Skill manager not available")

        skills = self._skill_manager.list_skills()
        summaries = [
            {
                "name": s.name,
                "description": s.description,
                "triggers": s.triggers[:5],
                "location": s.location,
            }
            for s in skills
        ]

        return ToolResult(
            success=True,
            data={"skills": summaries, "count": len(summaries)},
        )
