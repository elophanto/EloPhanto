"""``delegate`` — fan out N sub-tasks as in-process subagents.

The third spawn tier between ``tool_call`` (single API hit) and the
heavier persistence/sandbox tiers (``swarm_spawn`` / ``kid_spawn`` /
``org_spawn`` / ``agent_connect``). Use when the parent wants to run
multiple discrete agent loops, aggregate the summaries, and continue —
no code persistence, no sandbox, no separate process.

What's isolated per subagent (see ``Agent.run_isolated``):
- conversation history
- working memory
- activated-tools set
- registry view (recursive-spawn tools hidden)

What's shared across parent + subagents (intentional global state):
- vault, DB, scheduler, affect, ego, cost tracker, resource semaphores

Hard rules baked in:
- ``role="leaf"`` only — subagents cannot recursively delegate.
- Recursive-spawn / long-lived-state tools hidden from the subagent's
  registry view: ``delegate``, ``swarm_*``, ``kid_*``, ``org_*``,
  ``schedule_task``, ``agent_connect``, ``agent_message``,
  ``agent_disconnect``, ``payment_*``, ``wallet_*``.
- Subagent runs with ``is_user_input=False`` so the user-correction
  regex doesn't pattern-match the parent's delegated goal text.
- One ``action_queue`` slot covers the whole delegation. Subagents
  bypass the queue (they're sub-tasks of the holder). They still go
  through ``LLM_BURST`` / ``BROWSER`` semaphores so rate-limit and
  resource math stay correct.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult, ToolTier

logger = logging.getLogger(__name__)

# Names whose execution would either recurse (more delegate calls), persist
# state outside the parent task (schedule_task, kid/swarm/org), or open
# wide-blast-radius capabilities (payments, wallets, peer connections).
_EXCLUDED_PREFIXES: tuple[str, ...] = (
    "delegate",
    "swarm_",
    "kid_",
    "org_",
    "payment_",
    "wallet_",
    "agent_connect",
    "agent_message",
    "agent_disconnect",
    "schedule_task",
)

_DEFAULT_TIMEOUT_SECONDS = 600.0
_DEFAULT_MAX_TASKS = 10
_DEFAULT_MAX_ITERATIONS = 25


def _build_excluded_set(all_tool_names: list[str]) -> set[str]:
    """Resolve the prefix list against the live registry's tool names."""
    excluded: set[str] = set()
    for name in all_tool_names:
        for prefix in _EXCLUDED_PREFIXES:
            if name == prefix or name.startswith(prefix):
                excluded.add(name)
                break
    return excluded


class DelegateTool(BaseTool):
    """Spawn N in-process subagents to handle parallel sub-tasks."""

    @property
    def group(self) -> str:
        return "delegate"

    def __init__(self) -> None:
        # Injected by Agent at startup so the tool can call run_isolated.
        self._agent: Any = None

    @property
    def name(self) -> str:
        return "delegate"

    @property
    def description(self) -> str:
        return (
            "Fan out N parallel sub-tasks as in-process subagents and "
            "return aggregated summaries. Use this when the work is a "
            "set of discrete agent-loop sub-tasks (parallel research, "
            "evaluating N candidates, scanning N markets) — NOT for "
            "single tool calls (use the tool directly) and NOT for "
            "anything that needs code persistence (use swarm_spawn), "
            "sandboxing (kid_spawn), or a separate identity (org_spawn). "
            "Each subagent has its own conversation, working memory, "
            "and activated-tools set; vault/DB/scheduler/cost tracker "
            "are shared with the parent. Subagents cannot recursively "
            "delegate, schedule, spawn kids/swarms/orgs, send payments, "
            "or open peer connections."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": (
                        "List of sub-tasks to delegate. Each is run as an "
                        "isolated subagent. Sequential in v1; parallel "
                        f"execution coming. Max {_DEFAULT_MAX_TASKS} per call."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "goal": {
                                "type": "string",
                                "description": (
                                    "What this subagent should accomplish. "
                                    "Self-contained — the subagent has no "
                                    "memory of the parent's history."
                                ),
                            },
                            "context": {
                                "type": "string",
                                "description": (
                                    "Optional extra context to prepend to "
                                    "the subagent's first message."
                                ),
                            },
                            "max_iterations": {
                                "type": "integer",
                                "description": (
                                    "Per-subagent step cap (default "
                                    f"{_DEFAULT_MAX_ITERATIONS})."
                                ),
                            },
                        },
                        "required": ["goal"],
                    },
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": (
                        "Per-subagent timeout in seconds "
                        f"(default {_DEFAULT_TIMEOUT_SECONDS})."
                    ),
                },
            },
            "required": ["tasks"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        # The tool itself is SAFE — what subagents do is governed by
        # the underlying tools' own permission levels and the executor's
        # approval_callback (which subagents inherit from the parent).
        return PermissionLevel.SAFE

    @property
    def tier(self) -> ToolTier:
        # DEFERRED so the LLM only sees this after explicit discovery —
        # keeps the default surface focused on direct tool calls and
        # avoids the model reflexively delegating trivial work.
        return ToolTier.DEFERRED

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._agent is None:
            return ToolResult(
                success=False, error="agent not injected — delegate disabled"
            )

        tasks = params.get("tasks") or []
        if not isinstance(tasks, list) or not tasks:
            return ToolResult(success=False, error="`tasks` must be a non-empty list")
        if len(tasks) > _DEFAULT_MAX_TASKS:
            return ToolResult(
                success=False,
                error=(
                    f"Too many tasks ({len(tasks)}); max {_DEFAULT_MAX_TASKS} "
                    "per delegate call. Split into multiple calls or rethink "
                    "the decomposition."
                ),
            )

        try:
            timeout = float(params.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS))
        except (TypeError, ValueError):
            timeout = _DEFAULT_TIMEOUT_SECONDS
        timeout = max(10.0, min(3600.0, timeout))

        # Resolve the excluded set against the live registry once per call so
        # newly-registered tools auto-pick-up the prefix policy.
        all_names = [t.name for t in self._agent._registry.all_tools()]
        excluded = _build_excluded_set(all_names)

        results: list[dict[str, Any]] = []
        for i, task in enumerate(tasks):
            if not isinstance(task, dict):
                results.append(
                    {
                        "index": i,
                        "goal": "",
                        "success": False,
                        "error": "task entry must be a dict with 'goal'",
                    }
                )
                continue
            goal = (task.get("goal") or "").strip()
            if not goal:
                results.append(
                    {
                        "index": i,
                        "goal": "",
                        "success": False,
                        "error": "missing 'goal'",
                    }
                )
                continue

            context = (task.get("context") or "").strip()
            try:
                max_iter = max(
                    1, int(task.get("max_iterations", _DEFAULT_MAX_ITERATIONS))
                )
            except (TypeError, ValueError):
                max_iter = _DEFAULT_MAX_ITERATIONS

            prompt = goal if not context else f"Context:\n{context}\n\nTask:\n{goal}"

            try:
                response = await asyncio.wait_for(
                    self._agent.run_isolated(
                        prompt,
                        excluded_tool_names=excluded,
                        max_steps_override=max_iter,
                    ),
                    timeout=timeout,
                )
            except TimeoutError:
                logger.warning(
                    "delegate: subagent %d timed out after %.1fs (goal=%.80r)",
                    i,
                    timeout,
                    goal,
                )
                results.append(
                    {
                        "index": i,
                        "goal": goal,
                        "success": False,
                        "error": f"timed out after {timeout:.0f}s",
                    }
                )
                continue
            except Exception as e:  # noqa: BLE001 — child failures must not kill peers
                logger.exception("delegate: subagent %d crashed", i)
                results.append(
                    {
                        "index": i,
                        "goal": goal,
                        "success": False,
                        "error": f"crash: {e}",
                    }
                )
                continue

            results.append(
                {
                    "index": i,
                    "goal": goal,
                    "success": True,
                    "summary": response.content,
                    "steps": response.steps_taken,
                    "tools_used": list(set(response.tool_calls_made)),
                }
            )

        succeeded = sum(1 for r in results if r["success"])
        return ToolResult(
            success=True,
            data={
                "completed": succeeded,
                "failed": len(results) - succeeded,
                "results": results,
            },
        )
