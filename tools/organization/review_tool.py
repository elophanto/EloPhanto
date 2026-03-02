"""organization_review — Approve or reject a specialist's work."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class OrganizationReviewTool(BaseTool):
    """Review a specialist's work — approve or reject with feedback."""

    def __init__(self) -> None:
        self._organization_manager: Any = None

    @property
    def name(self) -> str:
        return "organization_review"

    @property
    def description(self) -> str:
        return (
            "Approve or reject a specialist child agent's work. Approvals "
            "reinforce good behavior. Rejections with specific feedback are "
            "stored as corrections in the child's knowledge vault, teaching "
            "it to avoid similar mistakes. This is how specialists learn."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "child_id": {
                    "type": "string",
                    "description": "ID of the specialist being reviewed.",
                },
                "approved": {
                    "type": "boolean",
                    "description": "True to approve, False to reject.",
                },
                "task_ref": {
                    "type": "string",
                    "description": "Brief description of the task being reviewed.",
                },
                "feedback": {
                    "type": "string",
                    "description": (
                        "Feedback text. For rejections, be specific about what "
                        "went wrong and what the correct approach should be — "
                        "this becomes a correction in the child's knowledge."
                    ),
                },
            },
            "required": ["child_id", "approved"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._organization_manager:
            return ToolResult(
                success=False, error="Organization system is not enabled."
            )

        child_id = params.get("child_id", "")
        if not child_id:
            return ToolResult(success=False, error="'child_id' is required.")

        approved = params.get("approved", True)
        task_ref = params.get("task_ref", "")
        feedback = params.get("feedback", "")

        try:
            if approved:
                await self._organization_manager.approve(child_id, task_ref, feedback)
                return ToolResult(
                    success=True,
                    data={
                        "status": "approved",
                        "child_id": child_id,
                        "task_ref": task_ref,
                    },
                )
            else:
                await self._organization_manager.reject(child_id, task_ref, feedback)
                return ToolResult(
                    success=True,
                    data={
                        "status": "rejected",
                        "child_id": child_id,
                        "task_ref": task_ref,
                        "correction_stored": bool(feedback),
                    },
                )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
