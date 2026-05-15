"""Schedule task tool — create recurring or one-time scheduled tasks."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class ScheduleTaskTool(BaseTool):
    """Create a new scheduled task (recurring or one-time)."""

    @property
    def group(self) -> str:
        return "scheduling"

    def __init__(self) -> None:
        self._scheduler: Any = None

    @property
    def name(self) -> str:
        return "schedule_task"

    @property
    def description(self) -> str:
        return (
            "Schedule a task to run automatically. Supports recurring schedules "
            "(cron, natural language like 'every morning at 9am', or interval "
            "syntax '30s'/'5m'/'2h') and one-time delayed tasks ('in 5 minutes', "
            "'at 3pm'). Two execution shapes — PICK THE RIGHT ONE:\n\n"
            "**Shape A — agent-loop (default):** pass `task_goal` only. The agent "
            "runs a full plan-execute-reflect cycle (LLM calls) when the schedule "
            "fires. Use for anything that needs judgment: 'review last 24h of "
            "activity', 'find new Polymarket bets matching my mandate', 'post a "
            "thread about $ELO if the price moved'.\n\n"
            "**Shape B — direct-tool (fast path):** pass `direct_tool` + "
            "`direct_params`. The scheduler invokes that registry tool directly — "
            "NO LLM call, NO action_queue acquisition, truly concurrent with "
            "everything else. Use for purely mechanical work: 'every 30s call "
            "polymarket_resolve_pending', 'every hour call solana_balance', "
            "'every minute call agent_p2p_status'. Only SAFE tools allowed.\n\n"
            "**Decision rule:** if the goal is 'invoke tool X with fixed params' "
            "AND no judgment is needed between fires, use Shape B. If the goal "
            "involves reasoning, conditional actions, multiple tools, or "
            "interpreting results, use Shape A. When in doubt, use Shape B for "
            "any cadence faster than 5 minutes (Shape A burns ~$0.10/LLM call x "
            "120 fires/hour at 30s cadence = unsustainable cost).\n\n"
            "**Examples (Shape B):**\n"
            "  direct_tool='polymarket_resolve_pending', direct_params={'limit': 200}, schedule='30s'\n"
            "  direct_tool='solana_balance', direct_params={}, schedule='1h'\n"
            "  direct_tool='knowledge_index', direct_params={'incremental': True}, schedule='6h'"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Human-readable name for the task",
                },
                "task_goal": {
                    "type": "string",
                    "description": (
                        "The goal/task to execute when triggered. Required for "
                        "agent-loop schedules; optional for direct-tool schedules "
                        "(auto-generated trace if omitted)."
                    ),
                },
                "schedule": {
                    "type": "string",
                    "description": (
                        "When to run. Recurring: cron expression, natural language "
                        "('every hour', 'every 2 hours', 'every 30 minutes', "
                        "'every monday at 2pm', 'every morning at 9am'), OR short "
                        "interval syntax ('30s', '5m', '2h', '1d' — only useful "
                        "for direct-tool schedules; LLM-bearing schedules at "
                        "sub-minute cadence burn tokens). "
                        "One-time: 'in 5 minutes', 'in 1 hour', 'at 3pm'."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "Optional description",
                },
                "max_retries": {
                    "type": "integer",
                    "description": "Max retries on failure (default: 3 for recurring, 1 for one-time)",
                },
                "direct_tool": {
                    "type": "string",
                    "description": (
                        "Registry tool name to invoke directly on fire, bypassing "
                        "the agent loop. Must be SAFE-permission. When set, "
                        "task_goal is optional and there's no LLM call per fire."
                    ),
                },
                "direct_params": {
                    "type": "object",
                    "description": (
                        "Parameters passed to direct_tool on each fire. Validated "
                        "as JSON-serialisable at schedule-creation time so typos "
                        "fail loudly upfront instead of on every cron."
                    ),
                },
            },
            "required": ["name", "schedule"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._scheduler:
            return ToolResult(success=False, error="Scheduler not available")

        # Cross-schedule creation guard: a scheduled task cannot create
        # new schedules. Same reason as the mutation guard in
        # tools/scheduling/list_tool.py — schedule lifecycle is operator
        # policy, not autonomous-agent decision. Without this, an
        # over-eager Daily Review or self-improvement loop could spawn
        # parallel copies of itself or replacement schedules.
        try:
            from core.agent import is_in_scheduled_task

            if is_in_scheduled_task():
                return ToolResult(
                    success=False,
                    error=(
                        "refused: schedule_task (create) is not allowed "
                        "from inside a scheduled task. Schedule lifecycle "
                        "is operator policy. If you believe a new schedule "
                        "is needed, log the recommendation to workspace/ "
                        "for the operator to apply manually."
                    ),
                )
        except ImportError:
            pass

        from core.scheduler import parse_delay, parse_natural_language_schedule

        schedule_text = params["schedule"]
        direct_tool = params.get("direct_tool") or None
        direct_params = params.get("direct_params") if direct_tool else None
        task_goal = params.get("task_goal", "")

        # Guard: agent-loop schedules need a task_goal
        if not direct_tool and not task_goal:
            return ToolResult(
                success=False,
                error="task_goal is required for agent-loop schedules. "
                "Pass direct_tool to skip the agent loop.",
            )

        # Try one-time schedule first
        run_at = parse_delay(schedule_text)
        if run_at is not None:
            try:
                entry = await self._scheduler.schedule_once(
                    name=params["name"],
                    task_goal=params["task_goal"],
                    run_at=run_at,
                    description=params.get("description", ""),
                )
                return ToolResult(
                    success=True,
                    data={
                        "schedule_id": entry.id,
                        "name": entry.name,
                        "type": "one_time",
                        "run_at": run_at.isoformat(),
                        "task_goal": entry.task_goal,
                    },
                )
            except Exception as e:
                return ToolResult(success=False, error=f"Failed to schedule: {e}")

        # Fall back to recurring schedule. Try natural language first
        # but tolerate raw cron / interval syntax (e.g. '30s', '5m')
        # passing through unchanged — create_schedule validates either.
        try:
            cron = parse_natural_language_schedule(schedule_text)
        except ValueError:
            cron = schedule_text

        try:
            entry = await self._scheduler.create_schedule(
                name=params["name"],
                task_goal=task_goal,
                cron_expression=cron,
                description=params.get("description", ""),
                max_retries=params.get("max_retries", 3),
                direct_tool=direct_tool,
                direct_params=direct_params,
            )
            return ToolResult(
                success=True,
                data={
                    "schedule_id": entry.id,
                    "name": entry.name,
                    "type": "recurring_direct" if direct_tool else "recurring",
                    "cron_expression": cron,
                    "original_schedule": schedule_text,
                    "task_goal": entry.task_goal,
                    "direct_tool": entry.direct_tool,
                    "enabled": entry.enabled,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to create schedule: {e}")
