"""Autonomous background goal execution — checkpoint-by-checkpoint via asyncio tasks.

Runs goal checkpoints in the background without requiring user interaction.
Sends progress events to all connected channels via the gateway.
Pauses automatically when the user sends a message.

See docs/10-ROADMAP.md (Phase 13) and the GoalManager for checkpoint state.
"""

from __future__ import annotations

import asyncio
import inspect
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

CONTEXT FROM PREVIOUS CHECKPOINTS (prose summary):
{context}

RUN LEDGER (the durable record of this goal — where it and the summary
disagree, the ledger is right):
{ledger}

INSTRUCTIONS:
- Focus ONLY on this checkpoint's objective.
- Start from the ledger: reuse artifacts that exist, do not repeat failed
  attempts, and if a handoff says where the last run stopped, continue from
  there after checking it.
- Record what a later run must not have to rediscover with goal_note:
  facts you establish (with their source), decisions and why, open
  questions. Files and URLs your tools produce are recorded automatically.
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


def build_checkpoint_prompt(
    *,
    goal: str,
    order: int,
    total: int,
    title: str,
    stage: str,
    description: str,
    criteria: str,
    context: str,
    ledger: str,
) -> str:
    """The acting prompt for one checkpoint — shared with the benchmark
    (core/bench.py), so a replay measures the prompt production uses."""
    return _CHECKPOINT_PROMPT.format(
        goal=goal,
        order=order,
        total=total,
        title=title,
        stage=stage or "unknown",
        description=description,
        criteria=criteria,
        context=context or "(no prior context)",
        ledger=ledger or "(empty — this is the first run of this goal)",
    )


def _attach_tool_output(tool_trace: list[dict[str, Any]], name: str, result: Any) -> None:
    """Attach what a tool ANSWERED to its trace row, so the receipt gate can
    ground counts in outputs, not only in the parameters it was called with
    (2026-08-16: "exactly 14 subjects" could never be grounded because the
    register listing was a result, and results were never recorded)."""
    try:
        payload = result.to_dict() if hasattr(result, "to_dict") else result
        text = str(payload)
    except Exception:
        text = ""
    data = getattr(result, "data", None)
    for row in reversed(tool_trace):
        if row.get("tool") == name and "output" not in row:
            row["output"] = text[:2000]
            from core.tool_traces import output_json

            row["output_json"] = output_json(result)
            if isinstance(data, dict):
                # Top-level scalars only: enough for the run ledger to find
                # the path / url / id a tool returned.
                row["result_data"] = {
                    k: v for k, v in list(data.items())[:40] if isinstance(v, (str, int, float))
                }
            return


_PREEMPT_PREFIX = "Preempted"


def _utc_day() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%d")


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _preemption_note(response: Any, tool_trace: list[dict[str, Any]]) -> str:
    """What an interrupted attempt had already done, for the next attempt.

    A preempted checkpoint used to restart from zero with no note at all —
    and because the attempt is refunded it could restart that way forever
    (docs/94 F9). The note lists the successful calls this attempt made so
    the resumed run verifies them instead of repeating them.
    """
    steps = int(getattr(response, "steps_taken", 0) or 0)
    done = [
        f"{row.get('tool')}: {str(row.get('summary') or '')[:120]}"
        for row in tool_trace
        if (row.get("status") or "") == "ok"
    ]
    note = f"{_PREEMPT_PREFIX} after {steps} steps (attempt refunded)."
    if done:
        note += " Already done in that attempt: " + "; ".join(done[-12:])
    return note[:1000]


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
        # Set when a checkpoint stops for a reason outside the goal (the
        # operator STOP sentinel, the day's LLM budget): the loop exits and
        # leaves the goal active instead of burning attempts.
        self._halted_by_stop: bool = False
        self._pause_reason: str = ""
        # Whether the loop that just ended should hand over to the next goal.
        self._chain_after_exit: bool = True
        # goal_id → monotonic time before which the watchdog won't restart it.
        self._cooldown_until: dict[str, float] = {}
        self._watchdog_task: asyncio.Task[None] | None = None
        self._closed: bool = False
        # (goal_id, checkpoint order) → the current attempt's plan and the
        # recalled lessons it applied; scored when the attempt ends.
        self._attempt_plans: dict[tuple[str, int], tuple[Any, list[Any]]] = {}
        self._bench_task: asyncio.Task[Any] | None = None

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
        self._pause_reason = ""
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
        from core.run_hooks import run_hooks

        # goal_id tells _run_with_history which goal's plan to show
        # (docs/94 F3). run_hooks() with no arguments drops any hooks this
        # task inherited from the chat run that created it.
        with (
            execution_context(source=TaskSource.GOAL, in_agent_loop=False, goal_id=goal_id),
            run_hooks(),
        ):
            await self._run_goal_loop(goal_id)
        if self._chain_after_exit and not self._stop_requested and not self._closed:
            # Hand the runner to the next active goal that has work. Done
            # inline (not in a detached task) so it finishes before anyone
            # awaiting this task moves on. _run_goal_loop's finally already
            # cleared _current_task, so start_goal can launch the next one.
            try:
                await self.start_next_goal(exclude=goal_id)
            except Exception as e:  # pragma: no cover
                logger.debug("chain to next goal failed: %s", e)

    async def pause(self, reason: str = "") -> None:
        """Request the current goal to pause after the current checkpoint."""
        if not self.is_running:
            return
        self._pause_reason = reason or "pause requested"
        self._stop_requested = True
        # Wait for the loop to finish the current checkpoint
        if self._current_task:
            try:
                await asyncio.wait_for(asyncio.shield(self._current_task), timeout=5)
            except (TimeoutError, asyncio.CancelledError):
                pass

    async def resume(self, goal_id: str) -> bool:
        """Resume a paused goal's background execution.

        If another goal is running, the resumed goal is queued: it is active
        in the DB and the runner starts it when the current goal stops. It
        used to be flipped to active and then refused, which stranded it
        active with nothing running it (docs/94 F10).
        """
        ok = await self._gm.resume_goal(
            goal_id,
            cost_budget_usd=self._config.cost_budget_per_goal_usd,
            max_time_seconds=float(self._config.max_total_time_per_goal_seconds),
            max_llm_calls=self._config.max_llm_calls_per_goal,
        )
        if not ok:
            # Already active but nothing running it: "resume" means start.
            goal = await self._gm.get_goal(goal_id)
            if goal is None or goal.status != "active":
                return False
            if self.current_goal_id == goal_id:
                return True

        await self._broadcast_event(EventType.GOAL_RESUMED, {"goal_id": goal_id})
        self._cooldown_until.pop(goal_id, None)
        if self.is_running:
            logger.info(
                "Goal %s resumed and queued behind running goal %s",
                goal_id,
                self._current_goal_id,
            )
            return True
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
        """Resume active goals on agent startup (if auto_continue is enabled),
        and keep resuming them: the watchdog starts the next active goal
        whenever the runner is idle."""
        if not self._config.auto_continue:
            return
        try:
            started = await self.start_next_goal()
            if started:
                logger.info("Resumed active goal on startup: %s", started)
        except Exception as e:
            logger.warning("Failed to resume goals on startup: %s", e)

    async def start_next_goal(self, *, exclude: str | None = None) -> str | None:
        """Start the least recently touched active goal that has work left.

        Returns the started goal_id, or None. A goal is 'active' because the
        operator or the agent wants it pursued; before this, only the one
        goal resumed at startup ever ran, and every other active goal waited
        for someone to notice (docs/94 F10).
        """
        if self.is_running or self._closed:
            return None
        if self._stop_file_present():
            return None
        try:
            for gid in await self._gm.resume_envelope_paused():
                logger.info("Goal %s: new day — daily envelope lifted", gid)
        except Exception as e:
            logger.debug("envelope resume failed: %s", e)
        try:
            active = await self._gm.list_goals(status="active", limit=50)
            planning = await self._gm.list_goals(status="planning", limit=20)
        except Exception as e:
            logger.debug("start_next_goal: list failed: %s", e)
            return None
        now = time.monotonic()
        candidates = sorted(active + planning, key=lambda g: g.updated_at or "")
        for goal in candidates:
            if goal.goal_id == exclude:
                continue
            if self._cooldown_until.get(goal.goal_id, 0.0) > now:
                continue
            if goal.status == "active":
                nxt = await self._gm.get_next_checkpoint(goal.goal_id)
                if nxt is None:
                    continue
            if await self.start_goal(goal.goal_id):
                await self._broadcast_event(
                    EventType.GOAL_RESUMED,
                    {"goal_id": goal.goal_id, "goal": goal.goal},
                )
                return goal.goal_id
        return None

    _WATCHDOG_INTERVAL_S = 300.0

    def start_watchdog(self) -> None:
        """Start the idle-goal watchdog. Called by the gateway / chat entry
        points after ``resume_on_startup``; stopped by ``close()``."""
        if not self._config.auto_continue:
            return
        if self._watchdog_task is not None and not self._watchdog_task.done():
            return
        self._watchdog_task = asyncio.create_task(
            self._watchdog_loop(), name="goal-runner-watchdog"
        )

    async def _watchdog_loop(self) -> None:
        """Pick up active goals whenever the runner is idle.

        Covers the paths that activate a goal without starting it: a second
        goal_create while one runs, a goal the mind decomposed, a resume
        while busy, the STOP sentinel being cleared.
        """
        try:
            while not self._closed:
                await asyncio.sleep(self._WATCHDOG_INTERVAL_S)
                if self._closed:
                    return
                try:
                    await self.start_next_goal()
                except Exception as e:  # pragma: no cover — never kill the watchdog
                    logger.debug("goal watchdog tick failed: %s", e)
                try:
                    await self.maybe_send_health_digest()
                except Exception as e:  # pragma: no cover
                    logger.debug("health digest failed: %s", e)
                try:
                    await self.daily_upkeep()
                except Exception as e:  # pragma: no cover
                    logger.debug("daily upkeep failed: %s", e)
        except asyncio.CancelledError:
            return

    async def _once_today(self, key: str) -> bool:
        """True the first time it is asked for ``key`` on a UTC day."""
        db = self._gm._db
        today = _utc_day()
        rows = await db.execute("SELECT value FROM metadata WHERE key = ?", (key,))
        if rows and rows[0]["value"] == today:
            return False
        await db.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, today)
        )
        return True

    async def daily_upkeep(self) -> bool:
        """Prune old failed tool traces, and — when ``bench.enabled`` — capture
        new benchmark cases and replay them at ``bench.hour_utc`` while no
        goal is running (docs/95 Phase E). Returns True if a run started."""
        from datetime import UTC, datetime

        if await self._once_today("tool_traces_pruned_day"):
            from core.tool_traces import prune

            await prune(self._gm._db)
        cfg = getattr(getattr(self._agent, "_config", None), "bench", None)
        if cfg is None or getattr(cfg, "enabled", False) is not True:
            return False
        if self.is_running or (self._bench_task is not None and not self._bench_task.done()):
            return False
        if datetime.now(UTC).hour < int(cfg.hour_utc):
            return False
        if not await self._once_today("bench_last_day"):
            return False
        from core.bench import capture, cases_dir, load_cases, run_bench

        directory = cases_dir(self._agent._config)
        await capture(self._gm._db, directory, limit=int(cfg.max_cases))
        cases = load_cases(directory, int(cfg.max_cases))
        if not cases:
            return False
        logger.info("[bench] nightly run: %d case(s)", len(cases))
        self._bench_task = asyncio.get_running_loop().create_task(
            run_bench(
                self._agent,
                cases,
                db=self._gm._db,
                time_budget=float(cfg.time_budget_seconds),
            ),
            name="bench-nightly",
        )
        return True

    async def maybe_send_health_digest(self) -> bool:
        """Broadcast the autonomy health digest once per UTC day.

        Sent at ``goals.health_digest_hour_utc``; the day it was last sent is
        kept in the metadata table so a restart does not send it twice.
        """
        hour = int(getattr(self._config, "health_digest_hour_utc", -1))
        if hour < 0 or self._gateway is None:
            return False
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        if now.hour < hour:
            return False
        db = self._gm._db
        today = now.strftime("%Y-%m-%d")
        rows = await db.execute(
            "SELECT value FROM metadata WHERE key = 'autonomy_health_last_day'"
        )
        if rows and rows[0]["value"] == today:
            return False
        from core.autonomy_health import alerts, collect, render

        report = await collect(db, hours=24.0, runner=self)
        await db.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("autonomy_health_last_day", today),
        )
        problems = alerts(report)
        await self._gateway.broadcast(
            event_message(
                "",
                EventType.NOTIFICATION,
                {
                    "notification_type": "autonomy_health",
                    "title": "Autonomy health"
                    + (f" — {len(problems)} need you" if problems else ""),
                    "text": render(report),
                },
            ),
            session_id=None,
        )
        return True

    async def close(self) -> None:
        """Shut down: stop the running goal and the watchdog."""
        self._closed = True
        if self._watchdog_task is not None and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except (asyncio.CancelledError, Exception):
                pass
        self._watchdog_task = None
        await self.stop()

    def _stop_file_present(self) -> bool:
        try:
            return self._agent._stop_file_present() is True
        except Exception:
            return False

    def _daily_budget_exhausted(self) -> bool:
        try:
            tracker = self._agent._router.cost_tracker
            limit = float(self._agent._config.llm.budget.daily_limit_usd)
            return float(tracker.daily_total) >= limit
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Main execution loop
    # ------------------------------------------------------------------

    async def _run_goal_loop(self, goal_id: str) -> None:
        """Execute checkpoints one by one until done, paused, or failed.

        Leaves ``_chain_after_exit`` True when the runner should move on to
        the next active goal, False after the STOP sentinel, the daily
        budget, or cancellation.
        """
        self._chain_after_exit = True
        goal = await self._gm.get_goal(goal_id)
        if not goal:
            return

        checkpoints_since_eval = 0
        self._halted_by_stop = False
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
                    await self._pause_goal(
                        goal_id, self._pause_reason or "User interaction or pause requested"
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

                # Time limit — total work time across every run and restart.
                # It used to be wall-clock since this loop started, so every
                # resume or restart reset it.
                usage = await self._gm.usage(goal_id)
                if usage["total_seconds"] > self._config.max_total_time_per_goal_seconds:
                    await self._budget_pause(goal, "Total time limit reached")
                    return

                # Daily envelopes: pause for today, resume tomorrow by itself.
                envelope = self._envelope_reached(usage)
                if envelope:
                    await self._pause_goal(
                        goal_id,
                        f"envelope_day={_utc_day()} | {envelope} — resumes tomorrow",
                        status="budget_paused",
                    )
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
                if not checkpoint and goal.status == "planning":
                    # Never decomposed (or decomposition returned nothing).
                    # Plan it here rather than leaving it for someone else.
                    cps = await self._gm.get_checkpoints(goal_id)
                    if not cps:
                        planned = await self._gm.decompose(goal)
                        if not planned:
                            await self._pause_goal(
                                goal_id,
                                "decomposition produced no checkpoints — "
                                "restate the goal or revise it",
                            )
                            return
                        continue
                if not checkpoint:
                    # "No pending checkpoint" is not "done". Say which it is
                    # instead of exiting and leaving an unfinished goal
                    # 'active' with nothing running it (docs/94 F10).
                    state, detail = await self._gm.diagnose_no_pending(goal_id)
                    if state == "all_done":
                        outcome = await self._finish_goal(goal_id)
                        if outcome == "revised":
                            continue
                        return
                    if state == "completed":
                        goal = await self._gm.get_goal(goal_id)
                        await self._broadcast_event(
                            EventType.GOAL_COMPLETED,
                            {"goal_id": goal_id, "goal": goal.goal if goal else ""},
                        )
                        return
                    if state == "in_progress":
                        # Another executor holds a checkpoint; don't race it.
                        return
                    await self._pause_goal(goal_id, detail)
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
                if self._halted_by_stop:
                    # STOP sentinel or daily budget: not this goal's failure.
                    self._chain_after_exit = False
                    return

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
                    rotate = self._config.round_robin and await self._another_goal_waiting(goal_id)
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
                    if goal and goal.status == "paused" and await self._try_recover(
                        goal, checkpoint
                    ):
                        continue
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
                            # an evaluation that READ as on track. An
                            # unparseable answer is not progress.
                            if evaluation.parsed and evaluation.on_track:
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
                            reason = evaluation.reason
                            if evaluation.suggested_changes:
                                # Dropped before: the evaluator said what to
                                # change and the reviser was never told.
                                reason += f" Suggested changes: {evaluation.suggested_changes}"
                            await self._gm.revise_plan(goal, reason)

                if success and rotate:
                    # Round-robin: this goal goes to the back of the queue.
                    logger.info("Goal %s yields to the next active goal (round-robin)", goal_id)
                    return

                # Brief pause between checkpoints
                if self._config.pause_between_checkpoints_seconds > 0:
                    await asyncio.sleep(self._config.pause_between_checkpoints_seconds)

        except asyncio.CancelledError:
            logger.info("Goal %s execution cancelled", goal_id)
            self._chain_after_exit = False
            raise
        except Exception as e:
            logger.error("Goal %s execution error: %s", goal_id, e, exc_info=True)
            await self._broadcast_event(
                EventType.GOAL_FAILED,
                {"goal_id": goal_id, "error": str(e)},
            )
            # Pause, don't leave it 'active': an active goal is one the
            # watchdog restarts, and an error that repeats would loop.
            try:
                await self._pause_goal(goal_id, f"runner error: {str(e)[:300]}")
            except Exception:  # pragma: no cover
                pass
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
    def _retry_note(attempt_no: int, last_failure: str = "") -> str:
        """Prompt addendum for retries: finished work is real, keep it —
        and say WHY the last attempt failed, so the retry can fix that
        instead of repeating it. On 2026-08-16 a checkpoint did all four
        brand analyses, failed the receipt gate three times over one
        ungrounded count ("exactly 14 subjects"), and every retry was told
        nothing about it."""
        reason = (last_failure or "").strip()
        if reason.startswith(_PREEMPT_PREFIX):
            # Interrupted, not failed: the attempt was refunded, so this can
            # be "attempt 1" again — but the work done so far is real.
            return (
                "\nRESUME NOTE: an earlier run of this checkpoint was interrupted "
                "by higher-priority work before it finished. What it did is "
                "real — verify it in the relevant store or files and continue "
                "from there; do not redo it.\n"
                f"{reason[:1000]}\n"
            )
        if attempt_no <= 1:
            return ""
        note = (
            f"\nRETRY NOTE (attempt {attempt_no}): a previous attempt of this "
            "checkpoint did not pass. The work it completed is real and its "
            "receipts count for THIS run — first check which parts are "
            "already done (query the relevant store or organ for rows "
            "created during this run), then do ONLY the remainder. Redoing "
            "finished work is how the previous attempt died.\n"
        )
        if reason:
            note += f"Why the last attempt failed: {reason[:400]}\n"
        if "receipt_gate" in reason or "not grounded" in reason:
            note += (
                "The receipt gate checks that every count named in the "
                "success criteria appears in a TOOL RESULT from this attempt "
                "(what a tool answered, not what you wrote). Do the missing "
                "remainder if any, then finish by calling the tool whose "
                "output states those facts — list the register, count the "
                "rows, show the file — so the numbers are in the trail. "
                "Restating them in prose does not count.\n"
            )
        return note

    async def _execute_checkpoint(self, goal: Goal, checkpoint: Any) -> bool:
        """Execute a single checkpoint via agent.run(). Returns True on success."""
        tool_trace: list[dict[str, Any]] = []
        attempt_no = int(getattr(checkpoint, "attempts", 0) or 0) + 1
        from datetime import UTC, datetime

        started_at = datetime.now(UTC).isoformat()
        try:
            timeout_s = self._checkpoint_timeout(attempt_no)
            await self._gm.mark_checkpoint_active(goal.goal_id, checkpoint.order)
            ledger = self._ledger()
            ledger_text = ""
            if ledger is not None:
                ledger_text = await ledger.render(
                    goal.goal_id, checkpoint_order=checkpoint.order
                )

            # Build focused prompt
            prompt = build_checkpoint_prompt(
                goal=goal.goal,
                order=checkpoint.order,
                total=goal.total_checkpoints,
                title=checkpoint.title,
                stage=checkpoint.stage or "",
                description=checkpoint.description,
                criteria=checkpoint.success_criteria,
                context=goal.context_summary or "",
                ledger=ledger_text,
            )
            prompt += self._retry_note(
                attempt_no, str(getattr(checkpoint, "result_summary", "") or "")
            )
            plan_text = await self._deliberate(goal, checkpoint, ledger, ledger_text, attempt_no)
            if plan_text:
                prompt += (
                    "\nYOUR PLAN FOR THIS ATTEMPT (made before starting — follow "
                    "it; if what you find contradicts it, record a decision with "
                    "goal_note and adapt):\n" + plan_text + "\n"
                )

            # Approval requests for background work go to every channel.
            approval_cb = self._make_broadcast_approval() if self._gateway else None

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
            from core.run_hooks import run_hooks
            from core.tool_traces import redact_params

            def _on_tool(name: str, params: dict[str, Any], error: str | None) -> None:
                tool_trace.append(
                    {
                        "tool": name,
                        "status": "error" if error else "ok",
                        "error": error,
                        "summary": summarize_call(name, params or {}),
                        "data": {k: str(v)[:200] for k, v in list((params or {}).items())[:8]},
                        "call_params": redact_params(name, params),
                    }
                )

            def _on_result(name: str, params: dict[str, Any], result: Any) -> None:
                _attach_tool_output(tool_trace, name, result)

            # Hooks, history and the time budget all belong to THIS task
            # (docs/94 F2/F4). Nothing agent-wide is swapped, so a mind or
            # heartbeat waiting for the slot at the same time can neither
            # clobber this trail nor inherit this approval callback. The
            # budget starts when AGENT_LOOP is acquired, so time spent queued
            # behind chat or heartbeats never burns an attempt.
            with run_hooks(
                approval_callback=approval_cb,
                on_tool_executed=_on_tool,
                on_tool_result=_on_result,
            ):
                response = await self._agent.submit_task(
                    TaskSource.GOAL,
                    prompt,
                    time_budget_seconds=timeout_s,
                    isolated_history=True,
                    handoff=True,
                    memory_label=(
                        f"Goal {goal.goal_id} checkpoint {checkpoint.order}/"
                        f"{goal.total_checkpoints}: {checkpoint.title}"
                    ),
                )

            # Charge what this run spent, and how long it worked, to the goal
            # (docs/94 F1, §12). Work time excludes queueing.
            try:
                await self._gm.record_usage(
                    goal.goal_id,
                    cost_usd=float(
                        getattr(self._agent._router.cost_tracker, "task_total", 0.0) or 0.0
                    ),
                    seconds=_as_float(getattr(response, "elapsed_seconds", 0.0)),
                )
            except Exception as ce:  # pragma: no cover — accounting must not fail work
                logger.debug("goal usage accounting failed: %s", ce)

            stop_reason = str(getattr(response, "stop_reason", "") or "")
            db = getattr(self._gm, "_db", None)
            if db is not None:
                from core.tool_traces import persist

                await persist(
                    db,
                    goal_id=goal.goal_id,
                    checkpoint_order=checkpoint.order,
                    attempt=attempt_no,
                    trace=tool_trace,
                    started_at=started_at,
                )

            # What the attempt produced exists whether or not it passes.
            if ledger is not None:
                await ledger.record_artifacts(
                    goal.goal_id,
                    tool_trace,
                    checkpoint_order=checkpoint.order,
                    attempt=attempt_no,
                )
                handoff_text = str(getattr(response, "handoff", "") or "")
                if stop_reason and stop_reason != "completed":
                    note = handoff_text or _preemption_note(response, tool_trace)
                    await ledger.add(
                        goal.goal_id,
                        "handoff",
                        f"[{stop_reason}] {note}",
                        checkpoint_order=checkpoint.order,
                        attempt=attempt_no,
                        source="code",
                    )

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
            if getattr(response, "preempted", False) or stop_reason == "preempted":
                logger.info(
                    "Checkpoint %d of goal %s preempted — resetting to pending (attempt refunded)",
                    checkpoint.order,
                    goal.goal_id,
                )
                await self._reset_checkpoint_pending(
                    goal.goal_id,
                    checkpoint.order,
                    refund_attempt=True,
                    note=_preemption_note(response, tool_trace),
                )
                await asyncio.sleep(2)  # let the preempting task take the slot
                return False

            if stop_reason == "stop_file":
                # The operator's STOP sentinel is not the checkpoint's fault.
                # Hand the attempt back and stop the loop; the goal stays
                # active and resumes when STOP is cleared.
                logger.warning(
                    "Checkpoint %d of goal %s halted by the STOP sentinel — "
                    "attempt refunded, goal left active",
                    checkpoint.order,
                    goal.goal_id,
                )
                await self._reset_checkpoint_pending(
                    goal.goal_id, checkpoint.order, refund_attempt=True
                )
                self._halted_by_stop = True
                return False

            if stop_reason == "budget" and self._daily_budget_exhausted():
                # The day's LLM budget ran out mid-checkpoint: nothing is
                # wrong with the checkpoint. Refund, and let the watchdog
                # retry after the cooldown.
                logger.warning(
                    "Checkpoint %d of goal %s stopped by the daily LLM budget — "
                    "attempt refunded",
                    checkpoint.order,
                    goal.goal_id,
                )
                await self._reset_checkpoint_pending(
                    goal.goal_id, checkpoint.order, refund_attempt=True
                )
                self._cooldown_until[goal.goal_id] = time.monotonic() + 1800
                self._halted_by_stop = True
                return False

            if stop_reason == "time_limit":
                raise TimeoutError(f"checkpoint time budget {int(timeout_s)}s spent")

            summary = (response.content or "")[:500]
            from core.checkpoint_receipt import verify_checkpoint_receipt

            # No sor_text: the goal's context_summary is the model's own
            # digest, not a system of record, and it let a checkpoint with
            # zero tool calls pass on numbers from an earlier summary
            # (docs/94 F8). Evidence is what tools returned in THIS attempt.
            verdict = verify_checkpoint_receipt(
                checkpoint.success_criteria or "",
                tool_trace=tool_trace,
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
                await self._ledger_failure(
                    goal.goal_id,
                    checkpoint.order,
                    attempt_no,
                    f"receipt gate refused: {verdict.reason}",
                    tool_trace,
                )
                await self._record_outcome(
                    goal,
                    checkpoint,
                    attempt_no,
                    passed=False,
                    gate="receipt",
                    failure=f"receipt gate refused: {verdict.reason}",
                    stop_reason=stop_reason,
                    steps_used=len(tool_trace),
                )
                await self._broadcast_checkpoint_failed(
                    goal, checkpoint, f"receipt gate: {verdict.reason}"
                )
                return False

            vres = await self._verify(goal, checkpoint, tool_trace, response, ledger)
            if not vres.ok:
                reason = f"verification: {vres.reason}"
                if vres.findings:
                    reason += " Findings: " + "; ".join(vres.findings[:6])
                logger.warning(
                    "Checkpoint %d of goal %s failed verification: %s",
                    checkpoint.order,
                    goal.goal_id,
                    reason[:300],
                )
                await self._gm.mark_checkpoint_failed(goal.goal_id, checkpoint.order, reason)
                await self._ledger_failure(
                    goal.goal_id, checkpoint.order, attempt_no, reason, tool_trace
                )
                await self._record_outcome(
                    goal,
                    checkpoint,
                    attempt_no,
                    passed=False,
                    gate="verification",
                    failure=reason,
                    stop_reason=stop_reason,
                    steps_used=len(tool_trace),
                )
                await self._broadcast_checkpoint_failed(goal, checkpoint, reason[:300])
                return False

            await self._gm.mark_checkpoint_complete(
                goal.goal_id,
                checkpoint.order,
                f"{summary}\n[receipt] {verdict.reason}\n[verified] {vres.reason}",
                # The goal is completed by _finish_goal after it is verified
                # as a whole, not by the last checkpoint passing.
                defer_completion=True,
            )
            await self._record_outcome(
                goal,
                checkpoint,
                attempt_no,
                passed=True,
                stop_reason=stop_reason,
                steps_used=len(tool_trace),
            )
            if db is not None:
                from core.tool_traces import mark_passed

                await mark_passed(
                    db, goal_id=goal.goal_id, checkpoint_order=checkpoint.order, attempt=attempt_no
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

            await self._write_ledger_file(goal)

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
                await self._ledger_failure(
                    goal.goal_id,
                    checkpoint.order,
                    attempt_no,
                    f"ran out of its {int(timeout_s)}s budget",
                    [],
                )
                await self._record_outcome(
                    goal,
                    checkpoint,
                    attempt_no,
                    passed=False,
                    gate="timeout",
                    failure=(
                        f"ran out of its {int(timeout_s)}s time budget after "
                        f"{len(tool_trace)} tool calls"
                    ),
                    stop_reason="time_limit",
                    steps_used=len(tool_trace),
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
            await self._ledger_failure(
                goal.goal_id, checkpoint.order, attempt_no, f"error: {str(e)[:300]}", []
            )
            await self._record_outcome(
                goal,
                checkpoint,
                attempt_no,
                passed=False,
                gate="error",
                failure=f"error: {str(e)[:300]}",
                steps_used=len(tool_trace),
            )
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _deliberate(
        self,
        goal: Goal,
        checkpoint: Any,
        ledger: Any,
        ledger_text: str,
        attempt_no: int,
    ) -> str:
        """Think before acting: plan this attempt in a separate call.

        Records the plan in the ledger (so a later attempt can see what was
        tried and why) and returns it for the checkpoint prompt. Returns ""
        when disabled or when planning fails — it never blocks the work.
        """
        # A plan belongs to one attempt; never score a stale one.
        self._attempt_plans.pop((goal.goal_id, checkpoint.order), None)
        if not getattr(self._config, "deliberate", False):
            return ""
        router = getattr(self._agent, "_router", None)
        if router is None:
            return ""
        from core.deliberation import plan_checkpoint
        from core.plan_outcomes import lessons_by_label, render_offered

        lessons = ""
        offered: list[Any] = []
        recall = getattr(self._agent, "recall_lesson_items", None)
        if inspect.iscoroutinefunction(recall):
            try:
                offered = list(await recall(f"{checkpoint.title}. {checkpoint.description}"))
                lessons = render_offered(offered)
            except Exception as e:
                logger.debug("lesson recall failed: %s", e)
        last = str(getattr(checkpoint, "result_summary", "") or "")
        plan = await plan_checkpoint(
            router,
            goal=goal.goal,
            order=checkpoint.order,
            total=goal.total_checkpoints,
            title=checkpoint.title,
            description=checkpoint.description,
            criteria=checkpoint.success_criteria or "",
            stage=checkpoint.stage or "unknown",
            ledger_text=ledger_text,
            attempt=attempt_no,
            last_failure=last if attempt_no > 1 or last.startswith(_PREEMPT_PREFIX) else "",
            effort=str(getattr(self._config, "deliberation_effort", "") or ""),
            lessons=lessons,
        )
        if plan is None:
            return ""
        self._attempt_plans[(goal.goal_id, checkpoint.order)] = (
            plan,
            lessons_by_label(offered, plan.lessons_used),
        )
        text = plan.render()
        if ledger is not None:
            record = text
            if plan.reasoning:
                record += "\nREASONING (summary): " + plan.reasoning[:1200]
            await ledger.add(
                goal.goal_id,
                "plan",
                record,
                checkpoint_order=checkpoint.order,
                attempt=attempt_no,
                source="model",
            )
        try:
            await self._gm.add_cost(goal.goal_id, plan.cost)
        except Exception:
            pass
        return text

    async def _record_outcome(
        self,
        goal: Goal,
        checkpoint: Any,
        attempt_no: int,
        *,
        passed: bool,
        gate: str = "",
        failure: str = "",
        stop_reason: str = "",
        steps_used: int = 0,
    ) -> None:
        """Score this attempt's plan (docs/95 Phases C, D).

        A failure the plan did not foresee is a surprise: one post-mortem
        call names the assumption that broke, which goes into the ledger for
        the next attempt and, generalised, becomes a lesson. The lessons the
        plan applied are credited or debited. Without a plan there was no
        prediction, so nothing is recorded. Never raises.
        """
        entry = self._attempt_plans.pop((goal.goal_id, checkpoint.order), None)
        db = getattr(self._gm, "_db", None)
        if entry is None or db is None:
            return
        plan, used = entry
        surprise, broken = False, ""
        try:
            router = getattr(self._agent, "_router", None)
            if not passed and failure and router is not None:
                from core.deliberation import postmortem

                pm = await postmortem(
                    router,
                    checkpoint=f"{checkpoint.title}: {checkpoint.description}",
                    plan=plan,
                    failure=failure,
                    effort=str(getattr(self._config, "deliberation_effort", "") or ""),
                )
                if pm is not None:
                    await self._gm.add_cost(goal.goal_id, pm.cost)
                    surprise, broken = not pm.foreseen, pm.broken_assumption
                if pm is not None and surprise:
                    ledger = self._ledger()
                    if ledger is not None and broken:
                        await ledger.add(
                            goal.goal_id,
                            "fact",
                            f"Assumption that broke on attempt {attempt_no}: {broken}",
                            checkpoint_order=checkpoint.order,
                            attempt=attempt_no,
                            source="model",
                        )
                    learner = getattr(self._agent, "_learner", None)
                    write = getattr(learner, "record_lesson", None)
                    if pm.lesson and inspect.iscoroutinefunction(write):
                        await write(pm.lesson, f"{goal.goal[:200]} — {checkpoint.title}")
        except Exception as e:
            logger.debug("post-mortem skipped: %s", e)
        try:
            from core.plan_outcomes import PlanOutcomes

            skills = getattr(self._agent, "_skill_manager", None)
            await PlanOutcomes(
                db,
                project_root=getattr(getattr(self._agent, "_config", None), "project_root", None),
                on_promote=(lambda _p: skills.discover()) if skills is not None else None,
            ).record(
                goal_id=goal.goal_id,
                checkpoint_order=checkpoint.order,
                attempt=attempt_no,
                passed=passed,
                gate=gate,
                steps_planned=len(plan.steps),
                steps_used=steps_used,
                stop_reason=stop_reason,
                surprise=surprise,
                broken_assumption=broken,
                lessons_used=used,
            )
        except Exception as e:
            logger.debug("plan outcome not recorded: %s", e)

    async def _verify(
        self, goal: Goal, checkpoint: Any, tool_trace: list[dict[str, Any]], response: Any, ledger: Any
    ) -> Any:
        """Run the checkpoint's declared verification (docs/94 §11)."""
        from core.checkpoint_verify import VerificationResult, verify_checkpoint

        raw = getattr(checkpoint, "verification", "") or ""
        if not raw:
            return VerificationResult(ok=True, reason="no verification declared")
        refs: list[str] = []
        if ledger is not None:
            refs = [e.ref for e in await ledger.entries(goal.goal_id, kinds=("artifact",))]
        workspace = getattr(getattr(self._agent, "_config", None), "workspace", "")
        return await verify_checkpoint(
            raw,
            tool_trace=tool_trace,
            artifact_refs=refs,
            workspace=workspace if isinstance(workspace, str) else "",
            router=getattr(self._agent, "_router", None),
            criteria=checkpoint.success_criteria or "",
            result_text=str(getattr(response, "content", "") or ""),
        )

    async def _count_ledger(self, goal_id: str, kind: str, prefix: str) -> int:
        ledger = self._ledger()
        if ledger is None:
            return 0
        return sum(
            1 for e in await ledger.entries(goal_id, kinds=(kind,)) if e.content.startswith(prefix)
        )

    async def _finish_goal(self, goal_id: str) -> str:
        """Verify the goal as a whole, then complete, extend, or pause it.

        Returns "completed", "revised" (new checkpoints to run) or "paused".
        """
        from core.company import ALL_COMPANIES

        goal = await self._gm.get_goal(goal_id, company_id=ALL_COMPANIES)
        if goal is None:
            return "paused"
        ledger = self._ledger()
        prior_misses = await self._count_ledger(goal_id, "failure", "Final verification: not met")
        verdict = await self._gm.verify_goal_met(
            goal, effort=str(getattr(self._config, "deliberation_effort", "") or "")
        )

        async def _note(kind: str, text: str) -> None:
            if ledger is not None:
                await ledger.add(goal_id, kind, text, source="code")

        if verdict is None or verdict.get("met"):
            if verdict is None:
                await _note(
                    "decision",
                    "Final verification unavailable — completed on checkpoint results.",
                )
            else:
                await _note("decision", f"Final verification: met — {verdict.get('evidence', '')}")
            await self._gm.complete_goal(goal_id)
            await self._write_ledger_file(goal)
            await self._broadcast_event(
                EventType.GOAL_COMPLETED, {"goal_id": goal_id, "goal": goal.goal}
            )
            return "completed"

        missing = "; ".join(verdict.get("missing") or []) or "not specified"
        await _note("failure", f"Final verification: not met — missing: {missing}")
        self._learn_from(
            goal.goal,
            f"Every checkpoint passed, yet the goal was not met. Missing: {missing}. "
            "The plan did not cover what the goal asked for.",
        )
        if prior_misses >= 2:
            await self._pause_goal(
                goal_id,
                f"final verification found the goal not met three times; missing: {missing}",
            )
            return "paused"
        new = await self._gm.revise_plan(
            goal,
            "Final verification found the goal not met. Missing: "
            f"{missing}. Add checkpoints that do exactly this missing work — "
            "nothing already done.",
        )
        if not new:
            await self._pause_goal(goal_id, f"final verification: not met, missing: {missing}")
            return "paused"
        await self._broadcast_event(
            EventType.GOAL_REVISED,
            {"goal_id": goal_id, "reason": f"final verification: missing {missing}"[:300]},
        )
        return "revised"

    async def _try_recover(self, goal: Goal, checkpoint: Any) -> bool:
        """A checkpoint failed out: re-plan it once before pausing the goal.

        The mind used to be the only thing that could recover a goal paused
        this way, and only when it was running. The runner now revises the
        plan with the failure history itself — at most twice per goal — and
        pauses only when that fails too.
        """
        failed = await self._gm.get_checkpoints(goal.goal_id, status="failed")
        if not any(c.order == checkpoint.order for c in failed):
            return False  # paused for another reason
        if await self._count_ledger(goal.goal_id, "decision", "Automatic recovery") >= 2:
            return False
        ledger = self._ledger()
        history = ""
        if ledger is not None:
            history = await ledger.render(goal.goal_id, checkpoint_order=checkpoint.order, max_chars=1500)
        reason = (
            f"Automatic recovery: checkpoint {checkpoint.order} '{checkpoint.title}' "
            f"failed all its attempts. Replace it with a different approach — split "
            f"it into smaller steps or change the method; do not repeat what failed. "
            f"History: {history[:1200]}"
        )
        if ledger is not None:
            await ledger.add(
                goal.goal_id,
                "decision",
                reason[:1500],
                checkpoint_order=checkpoint.order,
                source="code",
            )
        try:
            new = await self._gm.revise_plan(goal, reason)
        except Exception as e:
            logger.warning("automatic recovery failed for %s: %s", goal.goal_id, e)
            return False
        self._learn_from(
            f"{goal.goal} — checkpoint {checkpoint.order}: {checkpoint.title}",
            f"The checkpoint failed every attempt. {history[:1200]}",
        )
        if not new:
            return False
        await self._gm._update_status(goal.goal_id, "active", from_statuses=("paused",))
        await self._broadcast_event(
            EventType.GOAL_REVISED,
            {
                "goal_id": goal.goal_id,
                "reason": f"automatic recovery of checkpoint {checkpoint.order}",
            },
        )
        logger.info(
            "Goal %s: checkpoint %d failed out — plan revised automatically",
            goal.goal_id,
            checkpoint.order,
        )
        return True

    def _envelope_reached(self, usage: dict[str, float]) -> str:
        cost_cap = float(getattr(self._config, "daily_cost_envelope_usd", 0.0) or 0.0)
        time_cap = float(getattr(self._config, "daily_time_envelope_seconds", 0) or 0)
        if cost_cap > 0 and usage["today_cost_usd"] >= cost_cap:
            return f"daily cost envelope ${cost_cap:.2f} reached (${usage['today_cost_usd']:.2f})"
        if time_cap > 0 and usage["today_seconds"] >= time_cap:
            return f"daily time envelope {int(time_cap)}s reached"
        return ""

    async def _another_goal_waiting(self, goal_id: str) -> bool:
        try:
            for g in await self._gm.list_goals(status="active", limit=20):
                if g.goal_id != goal_id and await self._gm.get_next_checkpoint(g.goal_id):
                    return True
        except Exception:
            return False
        return False

    def _learn_from(self, task: str, what_happened: str) -> None:
        """Hand a failure to the learner, in the background (docs/94 §13)."""
        learner = getattr(self._agent, "_learner", None)
        fn = getattr(learner, "learn_from_failure", None)
        if not inspect.iscoroutinefunction(fn):
            return
        asyncio.get_running_loop().create_task(fn(task, what_happened, []))

    def _ledger(self) -> Any:
        """The run ledger over the goal manager's DB (None if unavailable)."""
        db = getattr(self._gm, "_db", None)
        if db is None:
            return None
        from core.run_ledger import RunLedger

        return RunLedger(db)

    async def _ledger_failure(
        self,
        goal_id: str,
        order: int,
        attempt: int,
        reason: str,
        tool_trace: list[dict[str, Any]],
    ) -> None:
        ledger = self._ledger()
        if ledger is None:
            return
        tried = [str(r.get("tool")) for r in tool_trace if r.get("tool")]
        tail = f" Tools used: {', '.join(tried[-10:])}." if tried else ""
        await ledger.add(
            goal_id,
            "failure",
            f"{reason}.{tail}",
            checkpoint_order=order,
            attempt=attempt,
            source="code",
        )

    async def _write_ledger_file(self, goal: Goal) -> None:
        """Mirror the ledger to <agent.workspace>/goals/<id>/LEDGER.md."""
        ledger = self._ledger()
        if ledger is None:
            return
        try:
            workspace = getattr(self._agent._config, "workspace", "")
        except Exception:
            workspace = ""
        if not isinstance(workspace, str) or not workspace.strip():
            return
        await ledger.write_markdown(
            goal.goal_id,
            Path(workspace) / "goals" / goal.goal_id / "LEDGER.md",
            title=goal.goal[:120],
        )

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
        self,
        goal_id: str,
        order: int,
        *,
        refund_attempt: bool = False,
        note: str | None = None,
    ) -> None:
        """Return an in-flight checkpoint to pending so resume retries it.

        ``refund_attempt`` un-counts the attempt that ``mark_checkpoint_active``
        recorded — used when the checkpoint never got to run (preemption),
        so external interruptions cannot exhaust ``max_checkpoint_attempts``.
        ``note`` replaces ``result_summary`` so the next attempt is told
        where the interrupted one got to.
        """
        sets = "status = 'pending'"
        params: list[Any] = []
        if refund_attempt:
            sets += ", attempts = MAX(attempts - 1, 0)"
        if note:
            sets += ", result_summary = ?"
            params.append(note)
        await self._gm._db.execute(
            f"UPDATE goal_checkpoints SET {sets} WHERE goal_id = ? AND checkpoint_order = ?",
            (*params, goal_id, order),
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
