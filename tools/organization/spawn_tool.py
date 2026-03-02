"""organization_spawn — Spawn or reuse a persistent specialist child agent."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class OrganizationSpawnTool(BaseTool):
    """Spawn a persistent specialist agent for a specific domain."""

    def __init__(self) -> None:
        self._organization_manager: Any = None

    @property
    def name(self) -> str:
        return "organization_spawn"

    @property
    def description(self) -> str:
        return (
            "Spawn a persistent specialist child agent (e.g. marketing, research, "
            "design). Each specialist is a full EloPhanto instance with its own "
            "identity, knowledge vault, and autonomous mind. If a specialist for "
            "the given role already exists, it will be reused (restarted if stopped). "
            "Use this when you need deep domain expertise or want to delegate "
            "long-running work."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "description": (
                        "Specialist role (e.g. 'marketing', 'research', 'design'). "
                        "If a pre-configured spec exists for this role, it will be used."
                    ),
                },
                "purpose": {
                    "type": "string",
                    "description": (
                        "Purpose description for the specialist's identity. "
                        "Overrides pre-configured purpose if provided."
                    ),
                },
                "seed_knowledge": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Paths to knowledge files to seed the specialist with "
                        "(relative to master's knowledge dir)."
                    ),
                },
                "budget_pct": {
                    "type": "number",
                    "description": (
                        "Percentage of master's daily LLM budget to allocate "
                        "(default: 10.0)."
                    ),
                },
            },
            "required": ["role"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.DESTRUCTIVE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._organization_manager:
            return ToolResult(
                success=False, error="Organization system is not enabled."
            )

        role = params.get("role", "")
        if not role:
            return ToolResult(success=False, error="'role' is required.")

        try:
            child = await self._organization_manager.spawn_specialist(
                role=role,
                purpose=params.get("purpose", ""),
                seed_knowledge=params.get("seed_knowledge"),
                budget_pct=params.get("budget_pct"),
            )
            return ToolResult(
                success=True,
                data={
                    "child_id": child.child_id,
                    "role": child.role,
                    "purpose": child.purpose,
                    "status": child.status,
                    "port": child.port,
                    "trust_score": child.trust_score,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
