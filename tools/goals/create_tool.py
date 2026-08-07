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
        self._dream_journal: Any = None

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
                "dream_id": {
                    "type": "integer",
                    "description": (
                        "The dream this goal came from, if goal_dream proposed "
                        "it — goal_dream returns dream_id in its result. Links "
                        "the goal back to its dream so we can measure which "
                        "dreams became real work."
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

    async def _link_dream(self, dream_id: Any, goal_id: str) -> None:
        """Attribute this goal back to the dream that proposed it.

        Closes the only feedback loop dreaming has. Without it every
        ``dream_journal.chosen_goal_id`` stays NULL, so "which dreams became
        real work?" — the question the column exists to answer — is
        unanswerable, and there is no way to tell a dreaming problem from a
        bookkeeping gap. Best-effort: attribution must never fail a goal that
        was otherwise created successfully.
        """
        if dream_id in (None, "") or self._dream_journal is None:
            return
        try:
            await self._dream_journal.set_chosen_goal(int(dream_id), goal_id)
        except Exception as e:  # noqa: BLE001 - bookkeeping is not load-bearing
            import logging

            logging.getLogger(__name__).warning(
                "goal_create: dream attribution failed (dream_id=%r): %s",
                dream_id,
                e,
            )

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
            await self._link_dream(params.get("dream_id"), goal.goal_id)
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
