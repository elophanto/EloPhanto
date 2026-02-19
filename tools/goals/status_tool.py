"""Goal status tool — check progress on active or past goals."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class GoalStatusTool(BaseTool):
    """Check progress on active or past goals."""

    def __init__(self) -> None:
        self._goal_manager: Any = None

    @property
    def name(self) -> str:
        return "goal_status"

    @property
    def description(self) -> str:
        return (
            "Check progress on active or past goals. "
            "Shows checkpoints, completion status, and context summary."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "goal_id": {
                    "type": "string",
                    "description": "Goal ID (omit to list all goals)",
                },
                "action": {
                    "type": "string",
                    "enum": ["list", "detail"],
                    "description": "list = all goals, detail = one goal with checkpoints",
                    "default": "list",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._goal_manager:
            return ToolResult(success=False, error="Goal system not initialized")

        action = params.get("action", "list")
        goal_id = params.get("goal_id")

        try:
            if action == "detail" and goal_id:
                goal = await self._goal_manager.get_goal(goal_id)
                if not goal:
                    return ToolResult(success=False, error=f"Goal not found: {goal_id}")

                checkpoints = await self._goal_manager.get_checkpoints(goal_id)
                cp_list = [
                    {
                        "order": c.order,
                        "title": c.title,
                        "status": c.status,
                        "result_summary": c.result_summary,
                        "attempts": c.attempts,
                    }
                    for c in checkpoints
                ]

                return ToolResult(
                    success=True,
                    data={
                        "goal_id": goal.goal_id,
                        "goal": goal.goal,
                        "status": goal.status,
                        "progress": f"{goal.current_checkpoint} of {goal.total_checkpoints}",
                        "context_summary": goal.context_summary[:500]
                        if goal.context_summary
                        else "",
                        "llm_calls_used": goal.llm_calls_used,
                        "checkpoints": cp_list,
                    },
                )
            else:
                goals = await self._goal_manager.list_goals()
                goal_list = [
                    {
                        "goal_id": g.goal_id,
                        "goal": g.goal[:100],
                        "status": g.status,
                        "progress": f"{g.current_checkpoint} of {g.total_checkpoints}",
                        "updated_at": g.updated_at,
                    }
                    for g in goals
                ]
                return ToolResult(
                    success=True,
                    data={"goals": goal_list, "total": len(goal_list)},
                )
        except Exception as e:
            return ToolResult(success=False, error=f"Goal status check failed: {e}")
