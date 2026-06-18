"""Goal creation tool — starts a new long-running goal with LLM decomposition."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class GoalCreateTool(BaseTool):
    """Start a long-running goal that spans multiple sessions."""

    @property
    def group(self) -> str:
        return "goals"

    def __init__(self) -> None:
        self._goal_manager: Any = None
        self._goal_runner: Any = None

    @property
    def name(self) -> str:
        return "goal_create"

    @property
    def description(self) -> str:
        return (
            "Start a long-running goal that spans multiple sessions. "
            "The agent decomposes it into ordered checkpoints and executes them "
            "step by step. For any goal that builds, sells, launches, or grows "
            "something, the decomposition enforces validate-before-build and "
            "every goal gets a measurable kill_criterion — provide one if you "
            "already know the abandon-threshold, else the planner writes it."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "The goal to achieve",
                },
                "mission_id": {
                    "type": "string",
                    "description": (
                        "Optional. Parent this goal under a mission "
                        "(durable drive). Use mission_list to see the "
                        "available slugs. Goals parented under a mission "
                        "bump that mission's momentum on completion."
                    ),
                },
                "kill_criterion": {
                    "type": "string",
                    "description": (
                        "Optional. The measurable condition under which this "
                        "goal should be ABANDONED, with a number + date/volume "
                        "(e.g. 'if <5 paid pre-orders in 14 days, abandon'). "
                        "If omitted, the planner derives one from the goal."
                    ),
                },
                "stage": {
                    "type": "string",
                    "enum": [
                        "scan",
                        "validate",
                        "build",
                        "launch",
                        "acquire",
                        "operate",
                        "scale",
                    ],
                    "description": (
                        "Optional founder-loop stage this goal starts in. "
                        "Usually left unset — the planner tags it from the "
                        "first checkpoint."
                    ),
                },
            },
            "required": ["goal"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._goal_manager:
            return ToolResult(success=False, error="Goal system not initialized")

        goal_text = params.get("goal", "").strip()
        if not goal_text:
            return ToolResult(success=False, error="Goal text is required")

        try:
            mission_id = params.get("mission_id")
            if mission_id:
                mission_id = mission_id.strip() or None
            kill_criterion = (params.get("kill_criterion") or "").strip() or None
            stage = (params.get("stage") or "").strip() or "unknown"
            goal = await self._goal_manager.create_goal(
                goal_text,
                mission_id=mission_id,
                stage=stage,
                kill_criterion=kill_criterion,
            )
            checkpoints = await self._goal_manager.decompose(goal)

            if not checkpoints:
                return ToolResult(
                    success=False,
                    error="Failed to decompose goal into checkpoints",
                )

            checkpoint_list = [
                {
                    "order": c.order,
                    "title": c.title,
                    "success_criteria": c.success_criteria,
                }
                for c in checkpoints
            ]

            # Trigger autonomous background execution
            bg_started = False
            if self._goal_runner:
                bg_started = await self._goal_runner.start_goal(goal.goal_id)

            return ToolResult(
                success=True,
                data={
                    "goal_id": goal.goal_id,
                    "goal": goal.goal,
                    "status": goal.status,
                    "total_checkpoints": goal.total_checkpoints,
                    "checkpoints": checkpoint_list,
                    "background_execution": bg_started,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Goal creation failed: {e}")
