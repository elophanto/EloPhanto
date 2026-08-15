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
- Prefer the dedicated tool for the domain over improvising with file/shell
  tools. Competitive intelligence work has a complete pipeline: collection is
  `watch_analyze` (or `watch_observe` per dimension), scoring is
  `watch_score`, deliverables are `watch_scorecard` / `watch_board_report` /
  `watch_executive_deck`. Its evidence lives in the watch register, not in
  CSVs you invent.
- A collect/observe/refresh checkpoint is satisfied ONLY by fetching from the
  live source during THIS execution. Files, CSVs or reports left by earlier
  runs are prior state, not this run's evidence — the receipt gate refuses a
  completion whose tool trail contains no fetches, so reading old artifacts
  harder cannot pass it.
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
        # MUST go through _run_goal_loop_entry — see that method for why
        # we cannot create_task(_run_goal_loop) directly.
        self._current_task = asyncio.create_task(
            self._run_goal_loop_entry(goal_id), name=f"goal-{goal_id[:8]}"
        )
        return True

    async def _run_goal_loop_entry(self, goal_id: str) -> None:
        """Isolate GoalRunner from the caller's ExecutionContext.

        ``asyncio.create_task`` copies ContextVars into the child task.
        When ``start_goal`` is invoked from a tool call inside a Mind
        (or User) agent loop, ``in_agent_loop=True`` leaks into this
        background task. ``agent.submit_task`` then skips AGENT_LOOP
        acquire and runs a *concurrent* agent loop on the same Agent
        while the outer Mind cycle still holds the slot.

        Observed 2026-08-08: MIND ACQ at 14:32 never emitted REL;
        GoalRunner nested checkpoint work for ~80 minutes; USER chat
        blocked forever on ``WAIT in_use=1``. Forcing
        ``in_agent_loop=False`` here makes GoalRunner wait for a real
        AGENT_LOOP lease instead of piggy-backing the parent's.
        """
        from core.execution_context import TaskSource, execution_context

        with execution_context(source=TaskSource.GOAL, in_agent_loop=False):
            await self._run_goal_loop(goal_id)

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
            logger.info("User interaction detected, pausing goal after current checkpoint")
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
        # revise_plan call; resets when an evaluation finds the goal
        # actually on track. If we revise this many times without
        # goal-level progress, the plan is producing self-contradictory
        # revisions (observed on AlphaScala 2026-05-20: 4+ revisions in
        # 4h, each saying "Day 1 incomplete BUT checkpoint 8 says Day 1
        # is already verified") and grinding the loop further is pure
        # cost. Pause the goal so the operator can inspect or supersede.
        #
        # It used to reset on every completed checkpoint, which made it
        # dead: evaluation runs only after two checkpoints complete, and
        # each of those completions zeroed the counter — so it read 1/3
        # forever and the pause below never once fired. The two senses of
        # "progress" disagree, and checkpoint-level was the wrong one:
        # a goal can tick off checkpoints indefinitely while going
        # nowhere. Observed 2026-08-11: 13 revisions and 55 completed
        # checkpoints over two hours, every log line saying 1/3, stopped
        # only by the wall-clock budget cap.
        revisions_without_progress = 0
        _MAX_REVISIONS_WITHOUT_PROGRESS = 3

        await self._broadcast_event(
            EventType.GOAL_STARTED,
            {"goal_id": goal_id, "goal": goal.goal},
        )

        # A checkpoint left 'active' by a dead run (hard cancellation,
        # process kill) is stranded: get_next_checkpoint only looks at
        # 'pending', so the loop would silently skip it forever — observed
        # 2026-08-15, checkpoint 2 stranded active while 3-6 ran around it.
        # This runner is the only executor, so any 'active' checkpoint at
        # loop start is by definition abandoned. Re-pick it.
        stranded = await self._gm._db.execute(
            "SELECT checkpoint_order FROM goal_checkpoints WHERE goal_id = ? AND status = 'active'",
            (goal_id,),
        )
        for row in stranded or []:
            order = row["checkpoint_order"]
            logger.warning(
                "Goal %s: checkpoint %s was stranded active by a previous "
                "run — resetting to pending",
                goal_id,
                order,
            )
            await self._reset_checkpoint_pending(goal_id, order, refund_attempt=True)

        try:
            while True:
                # --- Pre-checkpoint safety checks ---
                if self._stop_requested:
                    await self._pause_goal(goal_id, "User interaction or pause requested")
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
                    handled = await self._handle_validate_gate(goal, checkpoint, gate_reason)
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
                        if not evaluation.revision_needed:
                            # The only thing that counts as progress here:
                            # an evaluation that finds the goal on track.
                            revisions_without_progress = 0
                        else:
                            revisions_without_progress += 1
                            logger.info(
                                "Goal %s needs revision (%d/%d without progress): %s",
                                goal_id,
                                revisions_without_progress,
                                _MAX_REVISIONS_WITHOUT_PROGRESS,
                                evaluation.reason,
                            )
                            await self._broadcast_event(
                                EventType.GOAL_REVISED,
                                {
                                    "goal_id": goal_id,
                                    "revision": revisions_without_progress,
                                    "max_revisions": _MAX_REVISIONS_WITHOUT_PROGRESS,
                                    "reason": evaluation.reason,
                                },
                            )
                            if revisions_without_progress >= _MAX_REVISIONS_WITHOUT_PROGRESS:
                                await self._pause_goal(
                                    goal_id,
                                    f"Plan revised {revisions_without_progress} "
                                    f"times without goal-level progress — likely "
                                    f"self-contradictory revisions. Operator "
                                    f"should inspect, supersede, or cancel.",
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

    def _checkpoint_timeout(self, attempt_no: int) -> float:
        """The time budget for this attempt of a checkpoint.

        A retry that gets the same budget as the attempt that just timed
        out will die the same death — on 2026-08-15 a 4-brand analysis
        batch needed ~25 minutes against a 10-minute budget and burned
        every attempt doing the first 10 minutes over and over. Later
        attempts get proportionally more room, capped at 4× the base so a
        genuinely stuck checkpoint still pauses the goal instead of
        holding it forever.
        """
        base = self._config.max_time_per_checkpoint_seconds
        return float(min(base * max(1, attempt_no), base * 4))

    @staticmethod
    def _retry_note(attempt_no: int) -> str:
        """Prompt addendum for retries: finished work is real, keep it."""
        if attempt_no <= 1:
            return ""
        return (
            f"\nRETRY NOTE (attempt {attempt_no}): a previous attempt of this "
            "checkpoint ran out of time partway through. The work it "
            "completed is real and its receipts count for THIS run — first "
            "check which parts are already done (query the relevant store or "
            "organ for rows created during this run), then do ONLY the "
            "remainder. Redoing finished work is how the previous attempt "
            "died.\n"
        )

    async def _execute_checkpoint(self, goal: Goal, checkpoint: Any) -> bool:
        """Execute a single checkpoint via agent.run(). Returns True on success."""
        try:
            attempt_no = int(getattr(checkpoint, "attempts", 0) or 0) + 1
            timeout_s = self._checkpoint_timeout(attempt_no)
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
            prompt += self._retry_note(attempt_no)

            # Isolate conversation history — background runs must not pollute user chat
            saved_history = list(self._agent._conversation_history)
            self._agent._conversation_history.clear()

            # Override approval callback for gateway broadcast
            prev_approval = self._agent._executor._approval_callback
            if self._gateway:
                self._agent._executor.set_approval_callback(self._make_broadcast_approval())

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
                        "data": {k: str(v)[:200] for k, v in list((params or {}).items())[:8]},
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
                    timeout=timeout_s,
                )
            finally:
                # Restore conversation history and approval callback
                self._agent._conversation_history = saved_history
                self._agent._executor._approval_callback = prev_approval
                self._agent._executor._on_tool_executed = prev_on_tool

            # A preempted response is a YIELD, not a result. The loop gave
            # the slot to a higher-priority task (operator chat, heartbeat)
            # at a safe point; the checkpoint's work is partial by
            # construction. Verifying receipts on the partial trail is how
            # three checkpoints on 2026-08-15 got marked complete with the
            # summary "Task stopped: preempted…" while most of their brands
            # were never collected — the plan reviser then spent its
            # revisions re-adding the missing work. Reset to pending,
            # refund the attempt (an operator asking "is it working?" must
            # not burn the checkpoint's three attempts), and let the loop
            # re-pick it after the foreground drains.
            if getattr(response, "preempted", False):
                logger.info(
                    "Checkpoint %d of goal %s preempted — resetting to pending (attempt refunded)",
                    checkpoint.order,
                    goal.goal_id,
                )
                await self._reset_checkpoint_pending(
                    goal.goal_id, checkpoint.order, refund_attempt=True
                )
                await asyncio.sleep(2)  # let the preempting task take the slot
                return False

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
                await self._broadcast_checkpoint_failed(
                    goal, checkpoint, f"receipt gate: {verdict.reason}"
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
                    e if isinstance(e, ApprovalTimeoutPause) else e.__cause__  # type: ignore[assignment]
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
                next_budget = int(self._checkpoint_timeout(attempt_no + 1))
                logger.warning(
                    "Checkpoint %d of goal %s timed out after %ds "
                    "(attempt %d; next attempt gets %ds)",
                    checkpoint.order,
                    goal.goal_id,
                    int(timeout_s),
                    attempt_no,
                    next_budget,
                )
                await self._gm.mark_checkpoint_failed(
                    goal.goal_id,
                    checkpoint.order,
                    f"Timed out after {int(timeout_s)}s (attempt "
                    f"{attempt_no}). Next attempt gets {next_budget}s and "
                    "is told to keep receipted work instead of redoing it.",
                )
                await self._broadcast_checkpoint_failed(
                    goal,
                    checkpoint,
                    f"timed out after {int(timeout_s)}s "
                    f"(attempt {attempt_no}; next gets {next_budget}s)",
                )
                return False
            logger.error(
                "Checkpoint %d of goal %s failed: %s",
                checkpoint.order,
                goal.goal_id,
                e,
            )
            await self._gm.mark_checkpoint_failed(goal.goal_id, checkpoint.order, str(e))
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

    async def _handle_validate_gate(self, goal: Goal, checkpoint: Any, gate_reason: str) -> str:
        """Handle validate-first block: kill / revise / reorder / stop.

        Returns ``stop`` (exit loop), ``retry`` (continue loop), or ``ok``.
        """
        logger.warning("Goal %s blocked by validate gate: %s", goal.goal_id, gate_reason)

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

        async def _approval(tool_name: str, description: str, params: dict[str, Any]) -> bool:
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

    async def _pause_goal(self, goal_id: str, reason: str, *, status: str = "paused") -> None:
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

    async def _reset_checkpoint_pending(
        self, goal_id: str, order: int, *, refund_attempt: bool = False
    ) -> None:
        """Return an in-flight checkpoint to pending so resume retries it.

        ``refund_attempt`` un-counts the attempt that ``mark_checkpoint_active``
        recorded — used when the checkpoint never got to run (preemption),
        so external interruptions cannot exhaust ``max_checkpoint_attempts``.
        """
        await self._gm._db.execute(
            "UPDATE goal_checkpoints SET status = 'pending'"
            + (", attempts = MAX(attempts - 1, 0)" if refund_attempt else "")
            + " WHERE goal_id = ? AND checkpoint_order = ?",
            (goal_id, order),
        )

    async def _broadcast_checkpoint_failed(self, goal: Any, checkpoint: Any, reason: str) -> None:
        """Tell the operator a checkpoint failed, and how many times.

        Successes were broadcast and failures were not, so from any channel
        a goal failing the same checkpoint for the fifth time was
        indistinguishable from a goal thinking. The attempt count is the
        part that matters — one failure is work, five is a loop.
        """
        await self._broadcast_event(
            EventType.GOAL_CHECKPOINT_FAILED,
            {
                "goal_id": goal.goal_id,
                "checkpoint_order": checkpoint.order,
                "checkpoint_title": checkpoint.title,
                "reason": reason,
                "attempts": getattr(checkpoint, "attempts", 0) + 1,
            },
        )

    async def _broadcast_event(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Broadcast a goal event to all connected clients."""
        if self._gateway:
            await self._gateway.broadcast(event_message("", event_type, data), session_id=None)
        else:
            logger.info("Goal event [%s]: %s", event_type, data)
