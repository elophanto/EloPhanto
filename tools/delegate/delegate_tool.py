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
- Subagents run concurrently, ``_MAX_CONCURRENCY`` at a time. The shared
  semaphores above already bound real resource use, so the cap here is
  about queue fairness rather than safety: one delegate call fanning out
  ten ways must not starve everything else in the process.

This tier dispatches and aggregates. It does not judge the result — for
work that has to clear a quality bar, see ``panel_refine`` in
``tools/panel/``, which reviews and revises until independent lenses
accept it.
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
# Concurrent subagents per delegate call. The shared LLM_BURST / BROWSER
# semaphores already bound real resource use; this bounds how much of the
# queue one call may occupy so peers are not starved.
_MAX_CONCURRENCY = 4


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
                        "List of sub-tasks to delegate. Each runs as an "
                        "isolated subagent, up to "
                        f"{_MAX_CONCURRENCY} at a time. "
                        f"Max {_DEFAULT_MAX_TASKS} per call."
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

        # Fan out concurrently. The subagents already contend correctly on
        # the shared LLM_BURST / BROWSER semaphores, so the wall-clock win is
        # real while rate-limit and resource math stay exactly as they were.
        # A local cap keeps one delegate call from starving the rest of the
        # process — the semaphores bound the work, this bounds the queue.
        semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

        async def _run_one(i: int, task: Any) -> dict[str, Any]:
            if not isinstance(task, dict):
                return {
                    "index": i,
                    "goal": "",
                    "success": False,
                    "error": "task entry must be a dict with 'goal'",
                }
            goal = (task.get("goal") or "").strip()
            if not goal:
                return {
                    "index": i,
                    "goal": "",
                    "success": False,
                    "error": "missing 'goal'",
                }

            context = (task.get("context") or "").strip()
            try:
                max_iter = max(
                    1, int(task.get("max_iterations", _DEFAULT_MAX_ITERATIONS))
                )
            except (TypeError, ValueError):
                max_iter = _DEFAULT_MAX_ITERATIONS

            prompt = goal if not context else f"Context:\n{context}\n\nTask:\n{goal}"

            async with semaphore:
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
                    return {
                        "index": i,
                        "goal": goal,
                        "success": False,
                        "error": f"timed out after {timeout:.0f}s",
                    }
                except Exception as e:  # noqa: BLE001 — a child must not kill its peers
                    logger.exception("delegate: subagent %d crashed", i)
                    return {
                        "index": i,
                        "goal": goal,
                        "success": False,
                        "error": f"crash: {e}",
                    }

            return {
                "index": i,
                "goal": goal,
                "success": True,
                "summary": response.content,
                "steps": response.steps_taken,
                "tools_used": list(set(response.tool_calls_made)),
            }

        # return_exceptions keeps one unexpected failure from cancelling the
        # siblings mid-flight; each is already caught above, this is the net.
        gathered = await asyncio.gather(
            *(_run_one(i, t) for i, t in enumerate(tasks)),
            return_exceptions=True,
        )
        results: list[dict[str, Any]] = []
        for i, item in enumerate(gathered):
            if isinstance(item, BaseException):
                logger.exception("delegate: subagent %d raised past its handler", i)
                results.append(
                    {
                        "index": i,
                        "goal": "",
                        "success": False,
                        "error": f"crash: {item}",
                    }
                )
            else:
                results.append(item)
        results.sort(key=lambda r: r["index"])

        succeeded = sum(1 for r in results if r["success"])
        return ToolResult(
            success=True,
            data={
                "completed": succeeded,
                "failed": len(results) - succeeded,
                "results": results,
            },
        )
