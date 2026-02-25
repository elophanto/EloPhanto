"""Goal management tool — pause, resume, cancel, or revise goals."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class GoalManageTool(BaseTool):
    """Pause, resume, cancel, or revise an active goal."""

    def __init__(self) -> None:
        self._goal_manager: Any = None
        self._goal_runner: Any = None

    @property
    def name(self) -> str:
        return "goal_manage"

    @property
    def description(self) -> str:
        return "Pause, resume, cancel, or revise an active goal's plan."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "goal_id": {
                    "type": "string",
                    "description": "The goal ID to manage",
                },
                "action": {
                    "type": "string",
                    "enum": ["pause", "resume", "cancel", "revise"],
                    "description": "Action to perform on the goal",
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for revision (required for revise action)",
                },
            },
            "required": ["goal_id", "action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._goal_manager:
            return ToolResult(success=False, error="Goal system not initialized")

        goal_id = params.get("goal_id", "")
        action = params.get("action", "")
        reason = params.get("reason", "")

        if not goal_id:
            return ToolResult(success=False, error="goal_id is required")
        if not action:
            return ToolResult(success=False, error="action is required")

        try:
            if action == "pause":
                # Pause background runner if active for this goal
                if self._goal_runner and self._goal_runner.current_goal_id == goal_id:
                    await self._goal_runner.pause()
                else:
                    ok = await self._goal_manager.pause_goal(goal_id)
                    if not ok:
                        return ToolResult(
                            success=False,
                            error="Cannot pause (goal not active or not found)",
                        )
                return ToolResult(
                    success=True, data={"goal_id": goal_id, "action": "paused"}
                )

            elif action == "resume":
                # Resume via GoalRunner for background execution
                if self._goal_runner:
                    ok = await self._goal_runner.resume(goal_id)
                else:
                    ok = await self._goal_manager.resume_goal(goal_id)
                if not ok:
                    return ToolResult(
                        success=False,
                        error="Cannot resume (goal not paused or not found)",
                    )
                return ToolResult(
                    success=True,
                    data={
                        "goal_id": goal_id,
                        "action": "resumed",
                        "background_execution": bool(self._goal_runner),
                    },
                )

            elif action == "cancel":
                # Cancel background runner if active for this goal
                if self._goal_runner and self._goal_runner.current_goal_id == goal_id:
                    await self._goal_runner.cancel()
                ok = await self._goal_manager.cancel_goal(goal_id)
                if not ok:
                    return ToolResult(success=False, error="Goal not found")
                # Clear scratchpad so the mind doesn't act on stale goal state
                self._clear_scratchpad()
                return ToolResult(
                    success=True, data={"goal_id": goal_id, "action": "cancelled"}
                )

            elif action == "revise":
                if not reason:
                    return ToolResult(
                        success=False, error="reason is required for revise action"
                    )
                goal = await self._goal_manager.get_goal(goal_id)
                if not goal:
                    return ToolResult(success=False, error="Goal not found")

                new_checkpoints = await self._goal_manager.revise_plan(goal, reason)
                if not new_checkpoints:
                    return ToolResult(
                        success=False, error="Revision produced no checkpoints"
                    )

                cp_list = [
                    {
                        "order": c.order,
                        "title": c.title,
                        "success_criteria": c.success_criteria,
                    }
                    for c in new_checkpoints
                ]
                return ToolResult(
                    success=True,
                    data={
                        "goal_id": goal_id,
                        "action": "revised",
                        "new_checkpoints": cp_list,
                        "total_checkpoints": goal.total_checkpoints,
                    },
                )

            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(success=False, error=f"Goal management failed: {e}")

    def _clear_scratchpad(self) -> None:
        """Clear the mind's scratchpad after goal cancellation."""
        try:
            if self._goal_manager and self._goal_manager._db:
                # Access project root from goal_runner's agent config
                if self._goal_runner and hasattr(self._goal_runner, "_agent"):
                    project_root = self._goal_runner._agent._config.project_root
                    path = project_root / Path("data/scratchpad.md")
                    if path.exists():
                        path.write_text("", encoding="utf-8")
                        logger.info("Scratchpad cleared after goal cancellation")
        except Exception as e:
            logger.warning("Failed to clear scratchpad: %s", e)
