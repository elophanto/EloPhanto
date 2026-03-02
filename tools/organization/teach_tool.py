"""organization_teach — Push knowledge to a specialist child agent."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class OrganizationTeachTool(BaseTool):
    """Push knowledge or instructions to a specialist agent."""

    def __init__(self) -> None:
        self._organization_manager: Any = None

    @property
    def name(self) -> str:
        return "organization_teach"

    @property
    def description(self) -> str:
        return (
            "Push knowledge, guidelines, or instructions to a specialist "
            "child agent. The content is written to the child's knowledge "
            "vault and indexed for future use. Use this to proactively "
            "train specialists on domain-specific knowledge."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "child_id": {
                    "type": "string",
                    "description": "ID of the specialist to teach.",
                },
                "role": {
                    "type": "string",
                    "description": (
                        "Role of the specialist (alternative to child_id). "
                        "Auto-resolves to the specialist for this role."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Knowledge content to push (markdown format). "
                        "This will be stored in the child's knowledge vault."
                    ),
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for the knowledge file.",
                },
            },
            "required": ["content"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._organization_manager:
            return ToolResult(error="Organization system is not enabled.")

        content = kwargs.get("content", "")
        if not content:
            return ToolResult(error="'content' is required.")

        child_id = kwargs.get("child_id", "")
        role = kwargs.get("role", "")
        tags = kwargs.get("tags")

        if not child_id and not role:
            return ToolResult(error="Either 'child_id' or 'role' must be provided.")

        if not child_id and role:
            child = self._organization_manager._find_by_role(role)
            if not child:
                return ToolResult(error=f"No specialist found for role '{role}'.")
            child_id = child.child_id

        try:
            await self._organization_manager.teach(child_id, content, tags)
            return ToolResult(
                data={
                    "status": "taught",
                    "child_id": child_id,
                    "content_preview": content[:100],
                }
            )
        except Exception as e:
            return ToolResult(error=str(e))
