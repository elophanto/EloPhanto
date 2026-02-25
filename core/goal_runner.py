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
  Description: {description}
  Success Criteria: {criteria}

CONTEXT FROM PREVIOUS CHECKPOINTS:
{context}

INSTRUCTIONS:
- Focus ONLY on this checkpoint's objective.
- Use the success criteria to determine when you are done.
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

        ok = await self._gm.resume_goal(goal_id)
        if not ok:
            return False

        await self._broadcast_event(EventType.GOAL_RESUMED, {"goal_id": goal_id})
        return await self.start_goal(goal_id)

    async def cancel(self) -> None:
        """Cancel the current background goal execution and clear scratchpad."""
        self._stop_requested = True
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except (asyncio.CancelledError, Exception):
                pass
        self._current_task = None
        self._current_goal_id = None
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
                    await self._pause_goal(goal_id, f"Budget limit: {reason}")
                    return

                # Time limit
                elapsed = time.monotonic() - start_time
                if elapsed > self._config.max_total_time_per_goal_seconds:
                    await self._pause_goal(goal_id, "Total time limit reached")
                    return

                # Cost limit
                if goal.cost_usd >= self._config.cost_budget_per_goal_usd:
                    await self._pause_goal(
                        goal_id, f"Cost limit reached (${goal.cost_usd:.2f})"
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

                # --- Execute checkpoint ---
                success = await self._execute_checkpoint(goal, checkpoint)

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
                    # mark_checkpoint_failed handles retry/pause logic
                    goal = await self._gm.get_goal(goal_id)
                    if goal and goal.status == "paused":
                        await self._broadcast_event(
                            EventType.GOAL_PAUSED,
                            {
                                "goal_id": goal_id,
                                "reason": f"Checkpoint {checkpoint.order} failed after max retries",
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
                            logger.info(
                                "Goal %s needs revision: %s", goal_id, evaluation.reason
                            )
                            await self._gm.revise_plan(goal, evaluation.reason)

                # Brief pause between checkpoints
                if self._config.pause_between_checkpoints_seconds > 0:
                    await asyncio.sleep(self._config.pause_between_checkpoints_seconds)

        except asyncio.CancelledError:
            logger.info("Goal %s execution cancelled", goal_id)
            self._clear_scratchpad()
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

            try:
                response = await asyncio.wait_for(
                    self._agent.run(prompt),
                    timeout=self._config.max_time_per_checkpoint_seconds,
                )
            finally:
                # Restore conversation history and approval callback
                self._agent._conversation_history = saved_history
                self._agent._executor._approval_callback = prev_approval

            # Mark complete with summary
            summary = (response.content or "")[:500]
            await self._gm.mark_checkpoint_complete(
                goal.goal_id, checkpoint.order, summary
            )

            # Update context summary for next checkpoint
            goal_refreshed = await self._gm.get_goal(goal.goal_id)
            if goal_refreshed:
                messages = [{"role": "assistant", "content": response.content or ""}]
                ctx = await self._gm.summarize_context(goal_refreshed, messages)
                if ctx:
                    goal_refreshed.context_summary = ctx
                    await self._gm._persist_goal(goal_refreshed)

            return True

        except TimeoutError:
            logger.warning(
                "Checkpoint %d of goal %s timed out", checkpoint.order, goal.goal_id
            )
            await self._gm.mark_checkpoint_failed(
                goal.goal_id, checkpoint.order, "Checkpoint timed out"
            )
            return False

        except Exception as e:
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

    def _make_broadcast_approval(self) -> Any:
        """Create an approval callback that broadcasts to all gateway clients."""
        gateway = self._gateway

        async def _approval(
            tool_name: str, description: str, params: dict[str, Any]
        ) -> bool:
            if not gateway:
                # No gateway — auto-approve in autonomous mode
                return True

            from core.protocol import approval_request_message

            msg = approval_request_message(
                session_id="",
                tool_name=tool_name,
                description=description,
                params=params,
            )

            # Register a future in the gateway's pending approvals dict
            future: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
            gateway._pending_approvals[msg.id] = future

            await gateway.broadcast(msg, session_id=None)

            try:
                return await asyncio.wait_for(future, timeout=300)
            except TimeoutError:
                logger.warning("Approval timeout for %s — auto-denying", tool_name)
                return False
            finally:
                gateway._pending_approvals.pop(msg.id, None)

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

    async def _pause_goal(self, goal_id: str, reason: str) -> None:
        """Pause a goal and broadcast the event."""
        await self._gm.pause_goal(goal_id)
        await self._broadcast_event(
            EventType.GOAL_PAUSED,
            {"goal_id": goal_id, "reason": reason},
        )
        logger.info("Goal %s paused: %s", goal_id, reason)

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
