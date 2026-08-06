"""Autonomous background goal execution — checkpoint-by-checkpoint via asyncio tasks.

Runs goal checkpoints in the background without requiring user interaction.
Sends progress events to all connected channels via the gateway.
Pauses automatically when the user sends a message.

See docs/10-ROADMAP.md (Phase 13) and the GoalManager for checkpoint state.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.config import GoalsConfig
from core.protocol import EventType, event_message

if TYPE_CHECKING:
    from core.gateway import Gateway
    from core.goal_manager import Goal, GoalManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Checkpoint prompt template
# ---------------------------------------------------------------------------

_CHECKPOINT_PROMPT = """\
You are autonomously executing a goal checkpoint.

GOAL: {goal}

CURRENT CHECKPOINT ({order} of {total}):
  Title: {title}
  Stage: {stage}
  Description: {description}
  Success Criteria: {criteria}

CONTEXT FROM PREVIOUS CHECKPOINTS:
{context}

INSTRUCTIONS:
- Focus ONLY on this checkpoint's objective.
- Use the success criteria to determine when you are done.
- If the Stage is `validate`, you are looking for a signal that a real outside
  party will PAY (pre-order, LOI, paid pilot, advertiser/sponsor/affiliate
  commitment). Do not substitute interest signals (signups, follows, likes) for
  it, and do not slide into building — that is a later stage.
- When finished, provide a summary of what was accomplished.
"""


class GoalRunner:
    """Executes goal checkpoints autonomously as background asyncio tasks."""

    def __init__(
        self,
        agent: Any,
        goal_manager: GoalManager,
        gateway: Gateway | None,
        config: GoalsConfig,
    ) -> None:
        self._agent = agent
        self._gm = goal_manager
        self._gateway = gateway
        self._config = config
        self._current_task: asyncio.Task[None] | None = None
        self._current_goal_id: str | None = None
        self._stop_requested: bool = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._current_task is not None and not self._current_task.done()

    @property
    def current_goal_id(self) -> str | None:
        return self._current_goal_id if self.is_running else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_goal(self, goal_id: str) -> bool:
        """Launch background execution of a goal. Returns False if already running."""
        if self.is_running:
            logger.warning("GoalRunner already running goal %s", self._current_goal_id)
            return False

        goal = await self._gm.get_goal(goal_id)
        if not goal or goal.status not in ("active", "planning"):
            logger.warning(
                "Cannot start goal %s (status=%s)",
                goal_id,
                goal.status if goal else "not found",
            )
            return False

        self._stop_requested = False
        self._current_goal_id = goal_id
        self._current_task = asyncio.create_task(
            self._run_goal_loop(goal_id), name=f"goal-{goal_id[:8]}"
        )
        return True

    async def pause(self) -> None:
        """Request the current goal to pause after the current checkpoint."""
        if not self.is_running:
            return
        self._stop_requested = True
        # Wait for the loop to finish the current checkpoint
        if self._current_task:
            try:
                await asyncio.wait_for(asyncio.shield(self._current_task), timeout=5)
            except (TimeoutError, asyncio.CancelledError):
                pass

    async def resume(self, goal_id: str) -> bool:
        """Resume a paused goal's background execution."""
        if self.is_running:
            return False

        ok = await self._gm.resume_goal(
            goal_id,
            cost_budget_usd=self._config.cost_budget_per_goal_usd,
            max_time_seconds=float(self._config.max_total_time_per_goal_seconds),
            max_llm_calls=self._config.max_llm_calls_per_goal,
        )
        if not ok:
            return False

        await self._broadcast_event(EventType.GOAL_RESUMED, {"goal_id": goal_id})
        return await self.start_goal(goal_id)

    async def stop(self) -> None:
        """Gracefully stop goal execution (e.g. on shutdown). Preserves scratchpad."""
        self._stop_requested = True
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except (asyncio.CancelledError, Exception):
                pass
        self._current_task = None
        self._current_goal_id = None

    async def cancel(self) -> None:
        """Cancel the current goal and clear scratchpad (explicit user cancellation)."""
        await self.stop()
        self._clear_scratchpad()

    def notify_user_interaction(self) -> None:
        """Signal that a user sent a message — pause after current checkpoint."""
        if self.is_running:
            logger.info(
                "User interaction detected, pausing goal after current checkpoint"
            )
            self._stop_requested = True

    async def resume_on_startup(self) -> None:
        """Resume any active goals on agent startup (if auto_continue is enabled)."""
        if not self._config.auto_continue:
            return
        try:
            active = await self._gm.list_goals(status="active", limit=1)
            if active:
                goal = active[0]
                logger.info("Resuming active goal on startup: %s", goal.goal_id)
                await self._broadcast_event(
                    EventType.GOAL_RESUMED,
                    {"goal_id": goal.goal_id, "goal": goal.goal},
                )
                await self.start_goal(goal.goal_id)
        except Exception as e:
            logger.warning("Failed to resume goals on startup: %s", e)

    # ------------------------------------------------------------------
    # Main execution loop
    # ------------------------------------------------------------------

    async def _run_goal_loop(self, goal_id: str) -> None:
        """Execute checkpoints one by one until done, paused, or failed."""
        goal = await self._gm.get_goal(goal_id)
        if not goal:
            return

        start_time = time.monotonic()
        checkpoints_since_eval = 0
        # Revision-without-progress counter. Increments on every
        # revise_plan call; resets every time a checkpoint actually
        # completes. If we revise more than this many times without
        # ANY forward progress, the plan is producing self-
        # contradictory revisions (observed on AlphaScala 2026-05-20:
        # 4+ revisions in 4h, each saying "Day 1 incomplete BUT
        # checkpoint 8 says Day 1 is already verified") and grinding
        # the loop further is pure cost. Pause the goal so the
        # operator can inspect or supersede.
        revisions_without_progress = 0
        _MAX_REVISIONS_WITHOUT_PROGRESS = 3

        await self._broadcast_event(
            EventType.GOAL_STARTED,
            {"goal_id": goal_id, "goal": goal.goal},
        )

        try:
            while True:
                # --- Pre-checkpoint safety checks ---
                if self._stop_requested:
                    await self._pause_goal(
                        goal_id, "User interaction or pause requested"
                    )
                    return

                # Refresh goal state
                goal = await self._gm.get_goal(goal_id)
                if not goal or goal.status not in ("active", "planning"):
                    return

                # Budget check (LLM calls)
                within_budget, reason = self._gm.check_budget(goal)
                if not within_budget:
                    await self._budget_pause(goal, reason)
                    return

                # Time limit
                elapsed = time.monotonic() - start_time
                if elapsed > self._config.max_total_time_per_goal_seconds:
                    await self._budget_pause(goal, "Total time limit reached")
                    return

                # Cost limit
                if goal.cost_usd >= self._config.cost_budget_per_goal_usd:
                    await self._budget_pause(
                        goal,
                        f"Cost limit reached (${goal.cost_usd:.2f})",
                    )
                    return

                # --- Get next checkpoint ---
                checkpoint = await self._gm.get_next_checkpoint(goal_id)
                if not checkpoint:
                    # All done
                    goal = await self._gm.get_goal(goal_id)
                    if goal and goal.status == "completed":
                        await self._broadcast_event(
                            EventType.GOAL_COMPLETED,
                            {"goal_id": goal_id, "goal": goal.goal},
                        )
                    return

                # --- Founder-doctrine validate-first gate ---
                gate_reason = await self._gm.validate_gate_reason(goal_id, checkpoint)
                if gate_reason:
                    handled = await self._handle_validate_gate(
                        goal, checkpoint, gate_reason
                    )
                    if handled == "stop":
                        return
                    if handled == "retry":
                        continue
                    # fall through only if gate cleared (reorder)

                # --- Execute checkpoint ---
                success = await self._execute_checkpoint(goal, checkpoint)

                # Kill criterion after every attempt (success or fail)
                goal = await self._gm.get_goal(goal_id) or goal
                killed, kill_reason = await self._gm.evaluate_kill_criterion(
                    goal, evidence_text=goal.context_summary or ""
                )
                if killed:
                    await self._gm.cancel_goal(goal_id, kill_reason=kill_reason)
                    await self._broadcast_event(
                        EventType.GOAL_FAILED,
                        {
                            "goal_id": goal_id,
                            "error": kill_reason,
                            "kill_criterion": True,
                        },
                    )
                    logger.warning("Goal %s killed: %s", goal_id, kill_reason)
                    return

                if success:
                    checkpoints_since_eval += 1
                    revisions_without_progress = 0
                    await self._broadcast_event(
                        EventType.GOAL_CHECKPOINT_COMPLETE,
                        {
                            "goal_id": goal_id,
                            "checkpoint_order": checkpoint.order,
                            "checkpoint_title": checkpoint.title,
                        },
                    )
                else:
                    goal = await self._gm.get_goal(goal_id)
                    if goal and goal.status in (
                        "paused",
                        "awaiting_approval",
                        "budget_paused",
                        "cancelled",
                    ):
                        await self._broadcast_event(
                            EventType.GOAL_PAUSED,
                            {
                                "goal_id": goal_id,
                                "reason": f"Checkpoint {checkpoint.order} stopped "
                                f"(status={goal.status})",
                                "status": goal.status,
                            },
                        )
                        return

                # --- Self-evaluate periodically ---
                if checkpoints_since_eval >= 2:
                    checkpoints_since_eval = 0
                    goal = await self._gm.get_goal(goal_id)
                    if goal:
                        evaluation = await self._gm.evaluate_progress(goal)
                        if evaluation.revision_needed:
                            revisions_without_progress += 1
                            logger.info(
                                "Goal %s needs revision (%d/%d without progress): %s",
                                goal_id,
                                revisions_without_progress,
                                _MAX_REVISIONS_WITHOUT_PROGRESS,
                                evaluation.reason,
                            )
                            if (
                                revisions_without_progress
                                > _MAX_REVISIONS_WITHOUT_PROGRESS
                            ):
                                await self._pause_goal(
                                    goal_id,
                                    f"Plan revised {revisions_without_progress} "
                                    f"times without any checkpoint completing — "
                                    f"likely self-contradictory revisions. "
                                    f"Operator should inspect, supersede, or cancel.",
                                )
                                return
                            await self._gm.revise_plan(goal, evaluation.reason)

                # Brief pause between checkpoints
                if self._config.pause_between_checkpoints_seconds > 0:
                    await asyncio.sleep(self._config.pause_between_checkpoints_seconds)

        except asyncio.CancelledError:
            logger.info("Goal %s execution cancelled", goal_id)
            raise
        except Exception as e:
            logger.error("Goal %s execution error: %s", goal_id, e, exc_info=True)
            await self._broadcast_event(
                EventType.GOAL_FAILED,
                {"goal_id": goal_id, "error": str(e)},
            )
        finally:
            self._current_task = None
            self._current_goal_id = None

    # ------------------------------------------------------------------
    # Checkpoint execution
    # ------------------------------------------------------------------

    async def _execute_checkpoint(self, goal: Goal, checkpoint: Any) -> bool:
        """Execute a single checkpoint via agent.run(). Returns True on success."""
        try:
            await self._gm.mark_checkpoint_active(goal.goal_id, checkpoint.order)

            # Build focused prompt
            prompt = _CHECKPOINT_PROMPT.format(
                goal=goal.goal,
                order=checkpoint.order,
                total=goal.total_checkpoints,
                title=checkpoint.title,
                stage=checkpoint.stage or "unknown",
                description=checkpoint.description,
                criteria=checkpoint.success_criteria,
                context=goal.context_summary or "(no prior context)",
            )

            # Isolate conversation history — background runs must not pollute user chat
            saved_history = list(self._agent._conversation_history)
            self._agent._conversation_history.clear()

            # Override approval callback for gateway broadcast
            prev_approval = self._agent._executor._approval_callback
            if self._gateway:
                self._agent._executor.set_approval_callback(
                    self._make_broadcast_approval()
                )

            # GoalRunner is BACKGROUND goal execution — must NOT acquire
            # AGENT_LOOP at USER priority. The previous `agent.run(prompt)`
            # defaulted to is_user_input=True → priority 0 (USER), which
            # made the autonomous goal-runner compete with operator chat
            # for the top slot and starved MIND + cadence schedules.
            # On the AlphaScala instance 2026-05-20 a 13-checkpoint goal
            # at USER priority preempted MIND on every wakeup (13 of 14
            # cycles preempted within seconds) and starved SCHEDULED_CADENCE
            # for 1h57m. submit_task(TaskSource.GOAL, …) routes through
            # the canonical source→priority table and lands at GOAL=5
            # (lowest), as the enum doc always intended.
            from core.execution_context import TaskSource
            from core.mind_tool_summary import summarize_call

            tool_trace: list[dict[str, Any]] = []
            prev_on_tool = getattr(self._agent._executor, "_on_tool_executed", None)

            def _on_tool(name: str, params: dict[str, Any], error: str | None) -> None:
                tool_trace.append(
                    {
                        "tool": name,
                        "status": "error" if error else "ok",
                        "error": error,
                        "summary": summarize_call(name, params or {}),
                        "data": {
                            k: str(v)[:200] for k, v in list((params or {}).items())[:8]
                        },
                    }
                )
                if prev_on_tool:
                    try:
                        prev_on_tool(name, params, error)
                    except Exception:
                        pass

            self._agent._executor._on_tool_executed = _on_tool

            try:
                response = await asyncio.wait_for(
                    self._agent.submit_task(TaskSource.GOAL, prompt),
                    timeout=self._config.max_time_per_checkpoint_seconds,
                )
            finally:
                # Restore conversation history and approval callback
                self._agent._conversation_history = saved_history
                self._agent._executor._approval_callback = prev_approval
                self._agent._executor._on_tool_executed = prev_on_tool

            summary = (response.content or "")[:500]
            from core.checkpoint_receipt import verify_checkpoint_receipt

            verdict = verify_checkpoint_receipt(
                checkpoint.success_criteria or "",
                tool_trace=tool_trace,
                sor_text=goal.context_summary or "",
                assistant_summary=summary,
            )
            if not verdict.ok:
                logger.warning(
                    "Checkpoint %d receipt failed for goal %s: %s",
                    checkpoint.order,
                    goal.goal_id,
                    verdict.reason,
                )
                await self._gm.mark_checkpoint_failed(
                    goal.goal_id,
                    checkpoint.order,
                    f"receipt_gate: {verdict.reason}",
                )
                return False

            await self._gm.mark_checkpoint_complete(
                goal.goal_id,
                checkpoint.order,
                f"{summary}\n[receipt] {verdict.reason}",
            )

            # Optional instinct extraction from verified completions (P2).
            try:
                from core.instinct_extract import maybe_extract_instinct

                await maybe_extract_instinct(
                    project_root=self._agent._config.project_root,
                    goal=goal,
                    checkpoint=checkpoint,
                    summary=summary,
                    tool_trace=tool_trace,
                )
            except Exception as ie:  # pragma: no cover
                logger.debug("instinct extract skipped: %s", ie)

            # Affect: a checkpoint hit is a real win.
            affect_mgr = getattr(self._agent, "_affect_manager", None)
            if affect_mgr is not None:
                try:
                    from core.affect import emit_pride

                    await emit_pride(affect_mgr, source="goal")
                except Exception as e:  # pragma: no cover — defensive
                    logger.debug("Affect emit (pride) failed: %s", e)

            # Update context summary for next checkpoint
            goal_refreshed = await self._gm.get_goal(goal.goal_id)
            if goal_refreshed:
                messages = [{"role": "assistant", "content": response.content or ""}]
                ctx = await self._gm.summarize_context(goal_refreshed, messages)
                if ctx:
                    goal_refreshed.context_summary = ctx
                    await self._gm._persist_goal(goal_refreshed)

            return True

        except Exception as e:
            from core.approval_wait import ApprovalTimeoutPause

            if isinstance(e, ApprovalTimeoutPause) or isinstance(
                getattr(e, "__cause__", None), ApprovalTimeoutPause
            ):
                # Unwrap from wait_for / submit_task wrappers.
                pause_exc = (
                    e
                    if isinstance(e, ApprovalTimeoutPause)
                    else e.__cause__  # type: ignore[assignment]
                )
                tool = getattr(pause_exc, "tool_name", "?")
                logger.warning(
                    "Checkpoint %d of goal %s awaiting approval (%s)",
                    checkpoint.order,
                    goal.goal_id,
                    tool,
                )
                # Reset checkpoint to pending so resume retries it.
                await self._reset_checkpoint_pending(goal.goal_id, checkpoint.order)
                await self._pause_goal(
                    goal.goal_id,
                    f"awaiting_approval: operator did not answer for {tool}",
                    status="awaiting_approval",
                )
                return False
            if isinstance(e, TimeoutError):
                logger.warning(
                    "Checkpoint %d of goal %s timed out",
                    checkpoint.order,
                    goal.goal_id,
                )
                await self._gm.mark_checkpoint_failed(
                    goal.goal_id, checkpoint.order, "Checkpoint timed out"
                )
                return False
            logger.error(
                "Checkpoint %d of goal %s failed: %s",
                checkpoint.order,
                goal.goal_id,
                e,
            )
            await self._gm.mark_checkpoint_failed(
                goal.goal_id, checkpoint.order, str(e)
            )
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _budget_pause(self, goal: Goal, reason: str) -> None:
        """Hold goal as budget_paused; resume only when limits are raised."""
        tag = (
            f"limit_cost={self._config.cost_budget_per_goal_usd} "
            f"limit_time={self._config.max_total_time_per_goal_seconds} "
            f"limit_llm={self._config.max_llm_calls_per_goal} | {reason}"
        )
        await self._pause_goal(goal.goal_id, tag, status="budget_paused")

    async def _handle_validate_gate(
        self, goal: Goal, checkpoint: Any, gate_reason: str
    ) -> str:
        """Handle validate-first block: kill / revise / reorder / stop.

        Returns ``stop`` (exit loop), ``retry`` (continue loop), or ``ok``.
        """
        logger.warning(
            "Goal %s blocked by validate gate: %s", goal.goal_id, gate_reason
        )

        # Kill if criterion already met.
        killed, kill_reason = await self._gm.evaluate_kill_criterion(
            goal, evidence_text=goal.context_summary or ""
        )
        if killed:
            await self._gm.cancel_goal(goal.goal_id, kill_reason=kill_reason)
            await self._broadcast_event(
                EventType.GOAL_FAILED,
                {
                    "goal_id": goal.goal_id,
                    "error": kill_reason,
                    "kill_criterion": True,
                },
            )
            return "stop"

        # Failed validate checkpoints → one revise_plan with context.
        failed_validate = await self._gm.get_checkpoints(goal.goal_id, status="failed")
        failed_validate = [c for c in failed_validate if (c.stage or "") == "validate"]
        if failed_validate:
            reason = (
                f"validate-first pivot: validate checkpoint(s) failed "
                f"({', '.join(c.title for c in failed_validate)}). "
                f"Revise plan; do not build. Gate: {gate_reason}"
            )
            try:
                await self._gm.revise_plan(goal, reason)
                return "retry"
            except Exception as e:
                logger.error("revise_plan after validate fail: %s", e)
                await self._pause_goal(goal.goal_id, reason)
                return "stop"

        # Pending validate merely out of order → reorder.
        reordered = await self._gm.reorder_validate_before_build(goal.goal_id)
        if reordered:
            logger.info("Goal %s: reordered validate ahead of build", goal.goal_id)
            return "retry"

        await self._pause_goal(goal.goal_id, gate_reason)
        return "stop"

    def _make_broadcast_approval(self) -> Any:
        """Create an approval callback that broadcasts to all gateway clients.

        On timeout: re-ping once, then raise ApprovalTimeoutPause so the
        checkpoint pauses as awaiting_approval — never silent deny.
        """
        gateway = self._gateway

        async def _approval(
            tool_name: str, description: str, params: dict[str, Any]
        ) -> bool:
            from core.approval_wait import wait_for_operator_approval

            return await wait_for_operator_approval(
                gateway,
                tool_name=tool_name,
                description=description,
                params=params,
                label="Goal",
            )

        return _approval

    def _clear_scratchpad(self) -> None:
        """Clear the mind's scratchpad so stale goal state doesn't persist."""
        try:
            project_root = self._agent._config.project_root
            path = project_root / Path("data/scratchpad.md")
            if path.exists():
                path.write_text("", encoding="utf-8")
                logger.info("Scratchpad cleared after goal cancellation")
        except Exception as e:
            logger.warning("Failed to clear scratchpad: %s", e)

    async def _pause_goal(
        self, goal_id: str, reason: str, *, status: str = "paused"
    ) -> None:
        """Pause a goal and broadcast the event.

        ``status`` may be ``paused``, ``awaiting_approval``, or
        ``budget_paused`` — all are non-active holding states.
        """
        await self._gm.pause_goal(goal_id, status=status, reason=reason)
        await self._broadcast_event(
            EventType.GOAL_PAUSED,
            {"goal_id": goal_id, "reason": reason, "status": status},
        )
        logger.info("Goal %s → %s: %s", goal_id, status, reason)

    async def _reset_checkpoint_pending(self, goal_id: str, order: int) -> None:
        """Return an in-flight checkpoint to pending so resume retries it."""
        await self._gm._db.execute(
            "UPDATE goal_checkpoints SET status = 'pending' "
            "WHERE goal_id = ? AND checkpoint_order = ?",
            (goal_id, order),
        )

    async def _broadcast_event(
        self, event_type: EventType, data: dict[str, Any]
    ) -> None:
        """Broadcast a goal event to all connected clients."""
        if self._gateway:
            await self._gateway.broadcast(
                event_message("", event_type, data), session_id=None
            )
        else:
            logger.info("Goal event [%s]: %s", event_type, data)
