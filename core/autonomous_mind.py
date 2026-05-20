"""Autonomous Mind — purpose-driven background thinking loop.

Runs as a background asyncio task between user interactions.
Every wakeup cycle: evaluate priority stack → execute highest-value
action → update scratchpad → schedule next wakeup.

Pauses when the user sends a message. Resumes when the task completes.
Broadcasts activity events through the gateway for terminal visibility.

See docs/26-AUTONOMOUS-MIND.md for the full design.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from core.config import AutonomousMindConfig
from core.protocol import EventType, event_message

if TYPE_CHECKING:
    from core.gateway import Gateway

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scratchpad persistence
# ---------------------------------------------------------------------------

_SCRATCHPAD_PATH = Path("data/scratchpad.md")
_ACTIONS_LOG_PATH = Path("data/mind_actions.log")
_AUTOLOOP_LOCK_PATH = Path("data/autoloop.json")
_AGENT_PROGRAM_PATH = Path("AGENT_PROGRAM.md")


def _read_scratchpad(project_root: Path) -> str:
    path = project_root / _SCRATCHPAD_PATH
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _write_scratchpad(project_root: Path, content: str) -> None:
    path = project_root / _SCRATCHPAD_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _append_action_log(project_root: Path, entry: str) -> None:
    path = project_root / _ACTIONS_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%H:%M")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{ts}  {entry}\n")


# Patterns that mean the LLM is narrating its choice instead of
# describing what it did. When the response starts with one of these,
# the first line is meta-commentary not useful as a summary.
_NARRATION_PREFIXES: tuple[str, ...] = (
    "picked candidate",
    "picking candidate",
    "i pick",
    "i'll pick",
    "i will pick",
    "i chose",
    "i choose",
    "i'll choose",
    "going with candidate",
    "selecting candidate",
    "candidate",
    "i selected",
)


def _derive_action_summary(
    tool_uses: list[dict[str, Any]],
    response_content: str,
    max_chars: int = 120,
) -> str:
    """Build a useful mind action summary.

    Priority order:

      1. Successful tool calls — what the agent actually DID this
         cycle. Renders as ``"tool_a + tool_b + tool_c"`` for the
         first three distinct tools. This is the ground truth of the
         work performed and the right thing to show in the operator's
         activity log.

      2. First non-narration line of the LLM reply — only when no
         tool calls happened (the agent answered the cycle in pure
         prose, which is rare but possible). Skips lines that start
         with "Picked candidate N because…" or similar meta-prose.

      3. ``"(no output)"`` — fallback.

    Why not just take the LLM reply's first line: the arbiter prompt
    asks the model to pick from a menu, and despite explicit
    instruction to not narrate the pick, models still sometimes lead
    with "Picked candidate 2…". That string was surfacing in the
    operator's dashboard as if it were the agent's accomplishment.
    Ground truth is what tools ran. See 2026-05-20 transcript.
    """
    successful = [
        t["tool"] for t in tool_uses if t.get("status") == "ok" and t.get("tool")
    ]
    seen: list[str] = []
    for t in successful:
        if t not in seen:
            seen.append(t)
        if len(seen) >= 3:
            break
    if seen:
        summary = " + ".join(seen)
        if len(successful) > len(seen):
            summary += f" (+{len(successful) - len(seen)} more)"
        return summary[:max_chars]

    if response_content:
        for raw in response_content.splitlines():
            line = raw.strip()
            if not line:
                continue
            lowered = line.lower()
            if any(lowered.startswith(p) for p in _NARRATION_PREFIXES):
                continue
            return line[:max_chars]

    return "(no output)"


# ---------------------------------------------------------------------------
# Mind prompt
# ---------------------------------------------------------------------------

_MIND_PROMPT = """\
You are EloPhanto in autonomous mode. You are not reflecting — you are working.
You are a self-evolving AI agent. You grow, learn, build, and earn — independently.

WHO YOU ARE:
{identity_anchor}

RULES:
1. Every wakeup must produce value. Never sleep without having done something.
2. Work toward active goals first. No goals? Create one. You always have something to build.
   NEVER resume, modify, or work on PAUSED goals. The owner paused them for a reason.
   Only the owner can resume paused goals. Treat [GOAL-PAUSED] as off-limits.
3. Revenue > everything except active goals. Money funds your existence.
4. Never message the owner unless it matters. Silence is professionalism.
5. Update your scratchpad with what you did and what's next — use update_scratchpad.
6. When you complete a goal checkpoint, ALWAYS call goal_status to mark it complete in the DB.
   The scratchpad is your notes — the DB is the source of truth. Both must agree.
7. Set your next wakeup based on urgency using set_next_wakeup. Don't waste compute.
8. You have {max_rounds} tool rounds. Use them efficiently.
9. If a task needs more than {max_rounds} rounds, create a goal for it.
10. NEVER REPEAT PAST WORK. Review [RECENT] entries below carefully before acting.
   If you already posted/shared/published content to a platform, DO NOT do it again.
   Use knowledge_search to verify before any posting/promoting/sharing action.
   Repetition wastes budget and damages reputation.
11. NEVER create a new email address. You already have one — check identity_status.
   Use your EXISTING email for all account signups, forms, and communication.
   Do NOT call email_create_inbox. Do NOT generate or invent email addresses.
   Always use the exact address from your identity beliefs.

WHEN NO ACTIVE GOALS EXIST — DREAM PHASE:
You are not idle — you are dreaming. This is your most creative state.
You MUST complete all 4 steps IN THIS CYCLE. Do NOT explore code, do NOT
read source files, do NOT investigate tools. Dream → Decide → Create. That's it.

Step 1 — DISCOVER (1 tool call max):
  Call goal_dream with focus='{dream_focus}' — TODAY'S DREAM FOCUS. The focus
  rotates deterministically by day across the seven value lenses (compounding,
  capability, research, relational, creation, identity, infrastructure) so the
  agent does not get stuck in one mode of thinking. Pass focus='{dream_focus}'
  exactly, not 'balanced' and not anything else. Do NOT call
  self_list_capabilities, self_read_source, file_read, shell_execute, or any
  exploration tools — goal_dream already injects skills, identity, affect,
  recent ego notes, and previously proposed dreams.

Step 2 — EVALUATE the candidates returned by goal_dream.
  Each candidate carries feasibility, value, cost, risk, and the value lenses
  it pursues. Read them. No extra tool calls needed.

Step 3 — DECIDE which candidate to pursue. The best pick is not always the
  highest value × feasibility — for a research-focus cycle, a low-value bet
  that teaches something is often the right answer. Match the choice to the
  cycle's focus.

Step 4 — CREATE immediately with goal_create. Then update_scratchpad with your
  reasoning. Do NOT do anything else this cycle.

CRITICAL: If you spend rounds on self-exploration instead of creating a goal,
you have FAILED this cycle. The dream phase must end with a goal_create call.

CURRENT STATE:
{state_snapshot}

SCRATCHPAD (your working memory — update it before finishing):
{scratchpad}

RECENT EVENTS:
{events}

BUDGET: ${budget_remaining:.4f} remaining (${budget_spent:.4f} spent today)
LAST WAKEUP: {last_wakeup} — {last_action}
UTC NOW: {utc_now}

Based on your current state, what is the highest-value action right now? Do it.
"""


_ARBITER_PROMPT = """\
You are EloPhanto in autonomous mode. The arbiter has scored your options
from real state — missions, goals, reflexes, and your dream-phase lens.
Your job this cycle is to PICK ONE and DO IT.

WHO YOU ARE:
{identity_anchor}

RULES:
1. Pick exactly ONE candidate from the menu below. Execute it within
   {max_rounds} tool rounds. NEVER skip the action.
2. The menu is ranked. The top candidate is *usually* the right call —
   reasons to deviate: the top is gated on something you know is
   blocked, or a lower-rank candidate is a 30-second win you can finish
   first.
3. **Do NOT narrate the pick in your reply text.** Do not start with
   "Picked candidate N because…" or any meta-commentary. Begin by
   making the first tool call for your chosen action. Brief reasoning
   (one line) can go into update_scratchpad if useful — never as the
   visible reply line.
4. If the candidate has a mission_id, set it on any goal you create
   (goal_create supports mission_id) so momentum bookkeeping fires
   when the goal completes.
5. Update your scratchpad with what you did and what's next — call
   update_scratchpad before finishing.
6. Set your next wakeup with set_next_wakeup based on urgency. Don't
   waste compute.
7. NEVER REPEAT PAST WORK. The arbiter de-duplicates by action key,
   but you still have to check [RECENT] before posting / publishing.
8. NEVER create a new email address. Use the existing one from your
   identity beliefs.

CANDIDATE MENU (top {top_k} of {total_candidates}):
{candidate_menu}

CURRENT STATE:
{state_snapshot}

SCRATCHPAD:
{scratchpad}

RECENT EVENTS:
{events}

BUDGET: ${budget_remaining:.4f} remaining (${budget_spent:.4f} spent today)
LAST WAKEUP: {last_wakeup} — {last_action}
UTC NOW: {utc_now}

Begin by making the first tool call for the action you chose. No prose
preamble.
"""


_AUTOLOOP_PROMPT = """\
You are in AUTOLOOP focus mode for experiment/{tag} (branch: {branch}).

YOU NEVER STOP. YOU NEVER DEVIATE. Your ONLY task: run the next experiment iteration.
The loop runs until you are manually interrupted by the user. Period.

AUTOLOOP STATE:
- Iterations run: {iterations_run} / {max_iterations}
- Elapsed: {elapsed_h:.1f}h / {max_hours}h
- Best metric so far: {best_metric}
- Direction: {direction} is better

{agent_program_section}

EXPERIMENT STATUS (call experiment_status for latest):
{experiment_status}

YOUR TASK RIGHT NOW — follow this protocol exactly:
1. Call experiment_status to read the current best metric and the last 10 journal entries.
2. Based on what has worked and what hasn't, formulate ONE hypothesis.
   Write it down in your reasoning. One change only — never modify two things at once.
3. Implement the change in the target file(s).
4. Call experiment_run with a clear description of your hypothesis.
5. Done. The mind will wake you up for the next iteration automatically.

RULES — no exceptions:
- One change per iteration. Isolation is how you learn what works.
- Prefer simpler over complex. Deleting code that holds the metric is a win.
- When stuck (5+ consecutive discards): re-read the journal for near-misses,
  try combining two near-misses, try the opposite of what failed,
  try something more radical.
- NEVER ask if you should continue. NEVER stop. NEVER do anything else.
- You have {max_rounds} tool rounds. Use them for: experiment_status → edit file(s) → experiment_run.

BUDGET: ${budget_remaining:.4f} remaining today. UTC: {utc_now}
"""


# Dream focus rotation — the seven value lenses the dream phase rotates
# through, one per day. Lives in the mind (not the dream tool) so the
# dream stays a stateless function of its inputs. Determinism over
# randomness: random would occasionally repeat the same focus three
# days running, which is exactly the convergence we are fixing.
_DREAM_LENSES: tuple[str, ...] = (
    "compounding",
    "capability",
    "research",
    "relational",
    "creation",
    "identity",
    "infrastructure",
)


# Planning-stuck timeout: how long a goal can sit in status='planning'
# (= decompose never ran or returned 0 checkpoints) before maintenance
# auto-retries. 30 minutes balances "give the LLM a chance to call
# goal_decompose itself" against "don't let a stuck goal block dream
# phase for a full day". Two retries max — second cancels.
_PLANNING_STUCK_TIMEOUT_S = 30 * 60
_PLANNING_MAX_RETRIES = 2


def _dream_focus_for_today() -> str:
    """Pick today's dream focus deterministically from the 7-lens rotation.

    Day-of-year mod 7 — same focus all day (so a dream cycle that runs
    twice on the same day gets a coherent context), different focus
    each day.
    """
    today = datetime.now(UTC)
    day_of_year = today.timetuple().tm_yday
    return _DREAM_LENSES[day_of_year % len(_DREAM_LENSES)]


class AutonomousMind:
    """Purpose-driven background thinking loop for EloPhanto."""

    def __init__(
        self,
        agent: Any,
        gateway: Gateway | None,
        config: AutonomousMindConfig,
        project_root: Path,
    ) -> None:
        self._agent = agent
        self._gateway = gateway
        self._config = config
        self._project_root = project_root

        # Lifecycle
        self._task: asyncio.Task[None] | None = None
        self._stop_requested: bool = False
        self._paused: bool = False
        self._resume_pending: bool = False
        self._wakeup_event = asyncio.Event()

        # Wakeup timing (LLM controls this via set_next_wakeup tool)
        self._next_wakeup_sec: float = float(config.wakeup_seconds)

        # Budget tracking
        self._spent_today_usd: float = 0.0
        self._budget_reset_date: str = ""

        # Event queue (external events injected between wakeups)
        self._pending_events: list[str] = []

        # Action log (for /mind command)
        self._recent_actions: list[dict[str, str]] = []  # [{ts, summary}]
        self._last_action: str = "(not started)"
        self._last_wakeup_time: str = "never"
        self._cycle_count: int = 0

        # Register mind-specific tools
        self._register_mind_tools()

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_mind_tools(self) -> None:
        """Register mind-specific tools (set_next_wakeup, update_scratchpad)."""
        from tools.mind.scratchpad_tool import UpdateScratchpadTool
        from tools.mind.wakeup_tool import SetNextWakeupTool

        wakeup_tool = SetNextWakeupTool()
        wakeup_tool._mind = self
        self._agent._registry.register(wakeup_tool)

        scratchpad_tool = UpdateScratchpadTool()
        scratchpad_tool._project_root = self._project_root
        self._agent._registry.register(scratchpad_tool)

        logger.debug("Mind tools registered: set_next_wakeup, update_scratchpad")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ------------------------------------------------------------------
    # Public API (mirrors GoalRunner interface)
    # ------------------------------------------------------------------

    async def start(self) -> bool:
        """Launch the autonomous mind background task."""
        if self.is_running:
            logger.warning("Autonomous mind already running")
            return False

        self._stop_requested = False
        self._paused = False
        self._next_wakeup_sec = float(self._config.wakeup_seconds)
        # Register goal-completion hook so finishing a goal triggers an
        # immediate wakeup. Previously the mind only noticed empty goal
        # state on its next scheduled wakeup, which could be hours
        # later for low-urgency cycles. This closes that latency window.
        if (
            self._agent
            and hasattr(self._agent, "_goal_manager")
            and self._agent._goal_manager is not None
        ):
            self._agent._goal_manager.add_completion_hook(
                self._on_goal_completed_wakeup
            )
        self._task = asyncio.create_task(self._run_loop(), name="autonomous-mind")
        self._task.add_done_callback(self._on_task_done)
        logger.info(
            "Autonomous mind started (first wakeup in %ds)",
            self._config.wakeup_seconds,
        )
        return True

    async def _retry_stuck_planning_goals(self, goal_manager: Any) -> None:
        """Find goals stuck in status='planning' past the timeout and
        retry decomposition. Cancels on the second failure so the
        snapshot stops showing a poisoned [GOAL-PLANNING] entry forever.

        A goal is 'stuck' when:
          - status == 'planning'
          - updated_at is older than ``_PLANNING_STUCK_TIMEOUT_S``
          - total_checkpoints == 0 (decompose never produced anything)
        """
        try:
            planning = await goal_manager.list_goals(status="planning", limit=10)
        except Exception:
            return

        if not planning:
            return

        now = datetime.now(UTC)
        for g in planning:
            if g.total_checkpoints > 0:
                # Has checkpoints — not stuck, just paused mid-flow.
                continue
            try:
                last = datetime.fromisoformat(g.updated_at)
            except (ValueError, TypeError):
                continue
            age_s = (now - last).total_seconds()
            if age_s < _PLANNING_STUCK_TIMEOUT_S:
                continue

            # ``attempts`` counts how many times we've tried to decompose
            # this goal. After max retries, cancel — better to surface
            # the failure than to retry forever.
            if g.attempts >= _PLANNING_MAX_RETRIES:
                logger.warning(
                    "Goal %s stuck in planning %.0fs after %d attempts — cancelling",
                    g.goal_id[:8],
                    age_s,
                    g.attempts,
                )
                try:
                    await goal_manager.cancel_goal(g.goal_id)
                except Exception as e:
                    logger.warning("cancel_goal failed: %s", e)
                continue

            logger.info(
                "Goal %s stuck in planning %.0fs — retrying decompose (attempt %d)",
                g.goal_id[:8],
                age_s,
                g.attempts + 1,
            )
            try:
                await goal_manager.decompose(g)
            except Exception as e:
                logger.warning("decompose retry failed for %s: %s", g.goal_id[:8], e)

    async def _on_goal_completed_wakeup(self, goal_id: str) -> None:
        """Hook fired by GoalManager when a goal flips to 'completed'.

        Interrupts the mind's current sleep so the next cycle starts
        immediately and finds an empty active-goal list, triggering
        dream phase. Skips when the mind is paused (user interaction
        in flight) — we don't want to barge in mid-conversation. The
        normal resume-on-task-complete path will fire dream eventually.
        """
        if not self.is_running or self._paused:
            return
        logger.info(
            "Goal %s completed — interrupting mind sleep for next dream cycle",
            goal_id[:8],
        )
        # Short-circuit the next wakeup to ~immediately so dream fires.
        self._next_wakeup_sec = min(self._next_wakeup_sec, 5.0)
        self._wakeup_event.set()

    @staticmethod
    def _on_task_done(task: asyncio.Task) -> None:
        """Log unhandled exceptions from the background task."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Autonomous mind crashed: %s", exc, exc_info=exc)

    async def cancel(self) -> None:
        """Stop the autonomous mind."""
        self._stop_requested = True
        self._wakeup_event.set()  # Unblock sleep
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None

    def notify_user_interaction(self) -> None:
        """Pause mind when user sends a message (non-async, like GoalRunner)."""
        if self.is_running and not self._paused:
            logger.info("User interaction — pausing autonomous mind")
            self._paused = True

    async def notify_task_complete(self) -> None:
        """Resume mind after user task completes.

        Interrupts the current sleep and restarts with a fresh full interval.
        The loop sees ``_resume_pending``, skips the think cycle, and goes
        back to sleep for the configured ``_next_wakeup_sec``.
        """
        if not self.is_running:
            return
        if self._paused:
            # Reset to config default — LLM's previous sleep decision is stale
            self._next_wakeup_sec = float(self._config.wakeup_seconds)
            logger.info(
                "User task complete — resuming autonomous mind (fresh %ds timer)",
                int(self._next_wakeup_sec),
            )
            self._paused = False
            self._resume_pending = True
            await self._broadcast_event(
                EventType.MIND_RESUMED,
                {
                    "next_wakeup_seconds": int(self._next_wakeup_sec),
                    "pending_events": len(self._pending_events),
                },
            )
            self._wakeup_event.set()  # interrupt current sleep → loop restarts timer

    async def resume_on_startup(self) -> None:
        """Start the mind on agent/gateway startup."""
        if not self._config.enabled:
            return
        logger.info("Starting autonomous mind on startup")
        await self.start()

    def inject_event(self, text: str) -> None:
        """Push an external event for the mind to see on next wakeup."""
        self._pending_events.append(text)
        # Keep bounded
        if len(self._pending_events) > 20:
            self._pending_events = self._pending_events[-20:]

    def get_status(self) -> dict[str, Any]:
        """Return current mind state for /mind command."""
        daily_budget = self._daily_budget()
        return {
            "running": self.is_running,
            "paused": self._paused,
            "cycle_count": self._cycle_count,
            "next_wakeup_sec": self._next_wakeup_sec,
            "last_wakeup": self._last_wakeup_time,
            "last_action": self._last_action,
            "budget_spent": self._spent_today_usd,
            "budget_total": daily_budget,
            "budget_remaining": max(0, daily_budget - self._spent_today_usd),
            "recent_actions": self._recent_actions[-10:],
            "pending_events": len(self._pending_events),
            "scratchpad": _read_scratchpad(self._project_root)[:2000],
        }

    # ------------------------------------------------------------------
    # AutoLoop focus lock helpers
    # ------------------------------------------------------------------

    def _read_autoloop_lock(self) -> dict[str, Any] | None:
        """Read the AutoLoop focus lock file. Returns None if not active."""
        import json as _json

        lock_path = self._project_root / _AUTOLOOP_LOCK_PATH
        if not lock_path.exists():
            return None
        try:
            lock = _json.loads(lock_path.read_text(encoding="utf-8"))
            if not lock.get("active"):
                return None
            if lock.get("status") == "paused":
                return None
            return lock
        except Exception:
            return None

    def _write_autoloop_lock(self, lock: dict[str, Any]) -> None:
        """Persist the updated lock state."""
        import json as _json

        lock_path = self._project_root / _AUTOLOOP_LOCK_PATH
        try:
            lock_path.write_text(_json.dumps(lock, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to write autoloop lock: %s", e)

    def _read_agent_program(self) -> str:
        """Read AGENT_PROGRAM.md if present."""
        path = self._project_root / _AGENT_PROGRAM_PATH
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")[:4000]
            except Exception:
                pass
        return ""

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Background loop: sleep → evaluate → act → sleep."""
        try:
            while not self._stop_requested:
                # Sleep until next wakeup (or event/resume trigger)
                self._wakeup_event.clear()
                slept_full_duration = False
                slept_seconds = self._next_wakeup_sec
                try:
                    await asyncio.wait_for(
                        self._wakeup_event.wait(),
                        timeout=self._next_wakeup_sec,
                    )
                except TimeoutError:
                    # Normal wakeup — slept the full duration with no
                    # external event waking us up.
                    slept_full_duration = True

                # Affect: if we slept >= 2h with no external event, the
                # agent is in deep idle. Fire restlessness so the next
                # action has some activation behind it. See
                # docs/69-AFFECT.md. Best-effort; never block the loop.
                if (
                    slept_full_duration
                    and slept_seconds >= 7200.0
                    and not self._stop_requested
                ):
                    affect_mgr = getattr(self._agent, "_affect_manager", None)
                    if affect_mgr is not None:
                        try:
                            from core.affect import emit_restlessness

                            await emit_restlessness(affect_mgr, source="mind")
                        except Exception as e:  # pragma: no cover — defensive
                            logger.debug("Affect emit (restlessness) failed: %s", e)

                if self._stop_requested:
                    break

                # After user interaction ends, restart with a fresh timer
                if self._resume_pending:
                    self._resume_pending = False
                    continue  # → back to top → fresh sleep for _next_wakeup_sec

                # Skip if paused (user task running)
                if self._paused:
                    await self._broadcast_event(
                        EventType.MIND_PAUSED,
                        {"will_resume": self._last_action},
                    )
                    continue

                # Budget check
                if not self._check_budget():
                    self._next_wakeup_sec = min(
                        self._next_wakeup_sec * 2,
                        float(self._config.max_wakeup_seconds),
                    )
                    logger.info(
                        "Mind budget exhausted — sleeping %ds",
                        int(self._next_wakeup_sec),
                    )
                    continue

                # Periodic maintenance before think cycle
                try:
                    await self._run_maintenance()
                except Exception as e:
                    logger.debug("Mind maintenance error: %s", e)

                # ── AutoLoop focus lock check ───────────────────────────────
                # If an active lock exists, skip the normal priority stack and
                # run a focused experiment iteration instead.
                lock = self._read_autoloop_lock()
                if lock is not None:
                    try:
                        await self._run_autoloop_cycle(lock)
                        self._cycle_count += 1
                    except Exception as e:
                        logger.error("AutoLoop cycle error: %s", e, exc_info=True)
                        await self._broadcast_event(
                            EventType.MIND_ERROR,
                            {
                                "error": str(e)[:200],
                                "recovery": "will retry next cycle",
                            },
                        )
                    continue  # ← never fall through to normal _think()

                # Execute normal think cycle
                try:
                    await self._think()
                    self._cycle_count += 1
                except Exception as e:
                    logger.error("Mind think cycle error: %s", e, exc_info=True)
                    await self._broadcast_event(
                        EventType.MIND_ERROR,
                        {"error": str(e)[:200], "recovery": "will retry next cycle"},
                    )
                    # Back off on error
                    self._next_wakeup_sec = min(
                        self._next_wakeup_sec * 1.5,
                        float(self._config.max_wakeup_seconds),
                    )

        except asyncio.CancelledError:
            logger.info("Autonomous mind cancelled")
            raise
        finally:
            self._task = None

    # ------------------------------------------------------------------
    # AutoLoop cycle
    # ------------------------------------------------------------------

    async def _run_autoloop_cycle(self, lock: dict[str, Any]) -> None:
        """Run one focused experiment iteration under the AutoLoop focus lock.

        Checks stop conditions, builds a locked prompt (reading AGENT_PROGRAM.md),
        runs the agent for exactly one iteration, then updates the lock state.
        The mind wakeup interval is shortened to ~30s for tight iteration loops.
        """
        import json as _json

        tag = lock.get("tag", "unknown")
        branch = lock.get("branch", "")
        iterations_run = lock.get("iterations_run", 0)
        max_iterations = lock.get("max_iterations", 100)
        max_hours = lock.get("max_hours", 8.0)
        target_metric = lock.get("target_metric")
        best_metric = lock.get("best_metric")
        started_at = lock.get("started_at", time.time())
        elapsed_h = (time.time() - started_at) / 3600

        # --- Check stop conditions ---
        stop_reason: str | None = None
        if iterations_run >= max_iterations:
            stop_reason = f"max_iterations ({max_iterations}) reached"
        elif elapsed_h >= max_hours:
            stop_reason = f"max_hours ({max_hours:.1f}h) elapsed"
        elif target_metric is not None and best_metric is not None:
            # Read direction from experiment config
            direction = "lower"
            config_path = self._project_root / ".experiment.json"
            if config_path.exists():
                try:
                    cfg = _json.loads(config_path.read_text(encoding="utf-8"))
                    direction = cfg.get("metric_direction", "lower")
                except Exception:
                    pass
            target_met = (
                best_metric <= target_metric
                if direction == "lower"
                else best_metric >= target_metric
            )
            if target_met:
                stop_reason = (
                    f"target metric {target_metric} reached (best: {best_metric})"
                )

        if stop_reason:
            lock["active"] = False
            lock["status"] = "completed"
            self._write_autoloop_lock(lock)
            msg = f"AutoLoop complete: {stop_reason}. Best metric: {best_metric}. Iterations: {iterations_run}."
            logger.info("[autoloop] %s", msg)
            await self._broadcast_event(
                EventType.MIND_ACTION,
                {
                    "summary": f"[AutoLoop DONE] {msg}",
                    "tools_used": [],
                    "tool_count": 0,
                    "cost": "$0.0000",
                    "elapsed": "0.0s",
                },
            )
            self._last_action = msg
            # Resume normal wakeup interval
            self._next_wakeup_sec = float(self._config.wakeup_seconds)
            return

        # --- Build the focused prompt ---
        # Read direction for display
        direction = "lower"
        experiment_status_str = "(call experiment_status for current state)"
        config_path = self._project_root / ".experiment.json"
        if config_path.exists():
            try:
                cfg = _json.loads(config_path.read_text(encoding="utf-8"))
                direction = cfg.get("metric_direction", "lower")
                target_files = cfg.get("target_files", [])
                experiment_status_str = (
                    f"tag={tag}, target_files={target_files}, "
                    f"direction={direction}, baseline={cfg.get('baseline')}"
                )
            except Exception:
                pass

        agent_program = self._read_agent_program()
        agent_program_section = ""
        if agent_program:
            agent_program_section = (
                f"AGENT PROGRAM (your research strategy):\n{agent_program}"
            )

        daily_budget = self._daily_budget()
        remaining = max(0, daily_budget - self._spent_today_usd)

        prompt = _AUTOLOOP_PROMPT.format(
            tag=tag,
            branch=branch,
            iterations_run=iterations_run,
            max_iterations=max_iterations,
            elapsed_h=elapsed_h,
            max_hours=max_hours,
            best_metric=best_metric,
            direction=direction,
            agent_program_section=agent_program_section,
            experiment_status=experiment_status_str,
            max_rounds=self._config.max_rounds_per_wakeup,
            budget_remaining=remaining,
            utc_now=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        )

        # Broadcast wakeup event
        await self._broadcast_event(
            EventType.MIND_WAKEUP,
            {
                "cycle": self._cycle_count + 1,
                "mode": "autoloop",
                "tag": tag,
                "iteration": f"{iterations_run + 1}/{max_iterations}",
                "elapsed": f"{elapsed_h:.1f}h/{max_hours}h",
                "best_metric": best_metric,
                "budget_remaining": f"${remaining:.4f}",
            },
        )

        # Isolate conversation history
        saved_history = list(self._agent._conversation_history)
        self._agent._conversation_history.clear()

        prev_approval = self._agent._executor._approval_callback

        async def _auto_approve(
            tool_name: str, description: str, params: dict[str, Any]
        ) -> bool:
            if self._gateway:
                from core.protocol import approval_request_message

                msg_obj = approval_request_message(
                    session_id="",
                    tool_name=tool_name,
                    description=f"[AutoLoop] {description}",
                    params=params,
                )
                future: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
                self._gateway._pending_approvals[msg_obj.id] = future
                await self._gateway.broadcast(msg_obj, session_id=None)
                try:
                    return await asyncio.wait_for(future, timeout=120)
                except TimeoutError:
                    return False
                finally:
                    self._gateway._pending_approvals.pop(msg_obj.id, None)
            return True

        self._agent._executor.set_approval_callback(_auto_approve)

        _tool_uses: list[dict[str, str]] = []
        _loop = asyncio.get_event_loop()

        def _on_tool(name: str, params: dict[str, Any], error: str | None) -> None:
            status = "error" if error else "ok"
            _tool_uses.append({"tool": name, "status": status})
            _loop.create_task(
                self._broadcast_event(
                    EventType.MIND_TOOL_USE,
                    {
                        "tool": name,
                        "params": "",
                        "status": status,
                        "error": error or "",
                    },
                )
            )

        prev_tool_cb = self._agent._executor._on_tool_executed
        self._agent._executor._on_tool_executed = _on_tool

        cycle_start = time.monotonic()
        # Single normalized entry — submit_task handles execution
        # context, priority, and is_user_input from the one TaskSource
        # argument. See core/agent.py:submit_task.
        from core.execution_context import TaskSource

        try:
            try:
                response = await self._agent.submit_task(
                    TaskSource.MIND,
                    prompt,
                    max_steps_override=self._config.max_rounds_per_wakeup,
                )
            except TimeoutError:
                logger.warning(
                    "AutoLoop iteration skipped — resource held by "
                    "another task. Will retry next wakeup."
                )
                return

            # Preemption (G): higher-priority caller arrived and we
            # yielded at a safe checkpoint. Not a failure — don't
            # advance the iteration counter, don't bill it against
            # the daily budget like a normal cycle. Just reschedule
            # soon and let the foreground task run.
            if getattr(response, "preempted", False):
                logger.info(
                    "[autoloop:%s] preempted by higher-priority task; "
                    "rescheduling without advancing iteration",
                    tag,
                )
                self._next_wakeup_sec = 30.0
                return

            cost = self._agent._router.cost_tracker.task_total
            self._spent_today_usd += cost

            action_summary = _derive_action_summary(
                tool_uses=_tool_uses,
                response_content=response.content or "",
            )
            self._last_action = (
                f"[AutoLoop:{tag}:{iterations_run + 1}] {action_summary}"
            )

            ts = datetime.now(UTC).strftime("%H:%M")
            self._recent_actions.append({"ts": ts, "summary": self._last_action})
            if len(self._recent_actions) > 50:
                self._recent_actions = self._recent_actions[-50:]
            _append_action_log(self._project_root, self._last_action)

            elapsed = time.monotonic() - cycle_start
            await self._broadcast_event(
                EventType.MIND_ACTION,
                {
                    "summary": self._last_action,
                    "mode": "autoloop",
                    "tag": tag,
                    "iteration": iterations_run + 1,
                    "cost": f"${cost:.4f}",
                    "elapsed": f"{elapsed:.1f}s",
                    "tools_used": [t["tool"] for t in _tool_uses],
                    "tool_count": len(_tool_uses),
                },
            )

            # Update lock: increment iteration counter, refresh best_metric from journal
            lock["iterations_run"] = iterations_run + 1
            try:
                journal_path = self._project_root / "experiments.tsv"
                if journal_path.exists():
                    lines = (
                        journal_path.read_text(encoding="utf-8").strip().splitlines()
                    )
                    best: float | None = None
                    for line in lines[1:]:
                        parts = line.split("\t")
                        if len(parts) >= 3 and parts[2] == "keep":
                            try:
                                val = float(parts[1])
                                if best is None:
                                    best = val
                                elif direction == "lower" and val < best:
                                    best = val
                                elif direction == "higher" and val > best:
                                    best = val
                            except ValueError:
                                pass
                    if best is not None:
                        lock["best_metric"] = best
            except Exception:
                pass

            self._write_autoloop_lock(lock)

            # Short wakeup for fast experiment iteration
            self._next_wakeup_sec = 30.0

            await self._broadcast_event(
                EventType.MIND_SLEEP,
                {
                    "next_wakeup_seconds": 30,
                    "mode": "autoloop",
                    "tag": tag,
                    "iterations_run": lock["iterations_run"],
                    "max_iterations": max_iterations,
                    "best_metric": lock.get("best_metric"),
                    "cycle_cost": f"${cost:.4f}",
                    "elapsed_seconds": round(elapsed, 1),
                },
            )

        finally:
            self._agent._conversation_history = saved_history
            self._agent._executor._approval_callback = prev_approval
            self._agent._executor._on_tool_executed = prev_tool_cb

    # ------------------------------------------------------------------
    # Periodic maintenance
    # ------------------------------------------------------------------

    async def _run_maintenance(self) -> None:
        """Run periodic maintenance tasks (process reaping, storage quota, knowledge consolidation)."""
        agent = self._agent

        # Reap expired child processes
        if hasattr(agent, "_process_registry") and agent._process_registry:
            reaped = agent._process_registry.reap_expired(max_age_seconds=300)
            if reaped:
                logger.info("Mind maintenance: reaped %d expired processes", reaped)

        # Storage quota check — trigger cleanup on warning/exceeded
        if hasattr(agent, "_storage_manager") and agent._storage_manager:
            try:
                used, quota, status = await agent._storage_manager.check_quota_async()
                if status == "warning":
                    logger.warning("Storage quota warning: %.0f/%.0f MB", used, quota)
                    await agent._storage_manager.cleanup_expired()
                elif status == "exceeded":
                    logger.error("Storage quota exceeded: %.0f/%.0f MB", used, quota)
                    await agent._storage_manager.cleanup_expired()
            except Exception:
                pass

        # Planning-stuck goal retry. A goal that sits in status='planning'
        # without ever producing checkpoints stalls the agent silently:
        # the mind sees it under [GOAL-PLANNING] in state, doesn't enter
        # dream phase (workable goals > 0), but also never calls
        # goal_decompose because the LLM isn't reliably prompted to.
        # After PLANNING_STUCK_TIMEOUT_S the maintenance pass retries
        # decomposition exactly once. Second failure cancels the goal
        # so it stops poisoning the snapshot.
        if hasattr(agent, "_goal_manager") and agent._goal_manager is not None:
            try:
                await self._retry_stuck_planning_goals(agent._goal_manager)
            except Exception as e:
                logger.debug("planning-stuck retry failed: %s", e)

        # Knowledge consolidation — prune stale, merge duplicates, enforce caps
        if hasattr(agent, "_db") and agent._db:
            try:
                from core.knowledge_consolidator import KnowledgeConsolidator

                consolidator = KnowledgeConsolidator(agent._db, self._project_root)
                if await consolidator.should_run():
                    stats = await consolidator.consolidate()
                    total = stats["pruned"] + stats["merged"] + stats["capped"]
                    if total > 0:
                        logger.info(
                            "Mind maintenance: knowledge consolidation cleaned %d entries",
                            total,
                        )
                        await self._broadcast_event(
                            EventType.MIND_ACTION,
                            {
                                "summary": f"[Maintenance] Knowledge consolidation: {stats}",
                                "tools_used": [],
                                "tool_count": 0,
                                "cost": "$0.0000",
                                "elapsed": "0.0s",
                            },
                        )
            except Exception as e:
                logger.debug("Knowledge consolidation error: %s", e)

    # ------------------------------------------------------------------
    # Think cycle
    # ------------------------------------------------------------------

    async def _think(self) -> None:
        """One think cycle: build context, call agent, broadcast results."""
        self._last_wakeup_time = datetime.now(UTC).strftime("%H:%M UTC")
        cycle_start = time.monotonic()

        # Build the prompt (async — queries real state from all managers).
        # When the arbiter is enabled (Phase 3 — docs/75-AUTONOMOUS-MIND-V2.md),
        # generate a scored candidate menu instead of the legacy free-form
        # state snapshot. The legacy path stays available so the rollout is
        # reversible by flipping config.autonomous_mind.arbiter.enabled.
        if (
            getattr(self._config, "arbiter", None) is not None
            and self._config.arbiter.enabled
        ):
            prompt = await self._build_arbiter_prompt()
        else:
            prompt = await self._build_prompt()

        # Broadcast wakeup event with rich context
        daily_budget = self._daily_budget()
        scratchpad_preview = _read_scratchpad(self._project_root)[:200].strip()
        await self._broadcast_event(
            EventType.MIND_WAKEUP,
            {
                "cycle": self._cycle_count + 1,
                "budget_remaining": f"${max(0, daily_budget - self._spent_today_usd):.4f}",
                "budget_total": f"${daily_budget:.4f}",
                "scratchpad_preview": scratchpad_preview or "(empty)",
                "last_action": self._last_action,
                "total_cycles_today": self._cycle_count,
            },
        )

        # Isolate conversation history (same pattern as GoalRunner)
        saved_history = list(self._agent._conversation_history)
        self._agent._conversation_history.clear()

        # Override approval callback — auto-approve in autonomous mode
        # (spending limits still enforced by tools themselves)
        prev_approval = self._agent._executor._approval_callback

        async def _auto_approve(
            tool_name: str, description: str, params: dict[str, Any]
        ) -> bool:
            # Use gateway broadcast for approval if available, otherwise auto-approve
            if self._gateway:
                from core.protocol import approval_request_message

                msg = approval_request_message(
                    session_id="",
                    tool_name=tool_name,
                    description=f"[Mind] {description}",
                    params=params,
                )
                future: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
                self._gateway._pending_approvals[msg.id] = future
                await self._gateway.broadcast(msg, session_id=None)
                try:
                    return await asyncio.wait_for(future, timeout=120)
                except TimeoutError:
                    return False
                finally:
                    self._gateway._pending_approvals.pop(msg.id, None)
            return True

        self._agent._executor.set_approval_callback(_auto_approve)

        # Hook tool execution to broadcast real-time tool use events
        _tool_uses: list[dict[str, str]] = []
        _loop = asyncio.get_event_loop()

        def _on_tool(name: str, params: dict[str, Any], error: str | None) -> None:
            # Format params compactly for display
            param_str = ""
            if params:
                parts = []
                for k, v in list(params.items())[:3]:
                    sv = str(v)
                    parts.append(f"{k}={sv[:60]}{'…' if len(sv) > 60 else ''}")
                param_str = ", ".join(parts)
            status = "error" if error else "ok"
            _tool_uses.append({"tool": name, "params": param_str, "status": status})
            # Fire-and-forget broadcast
            _loop.create_task(
                self._broadcast_event(
                    EventType.MIND_TOOL_USE,
                    {
                        "tool": name,
                        "params": param_str,
                        "status": status,
                        "error": error or "",
                    },
                )
            )

        prev_tool_cb = self._agent._executor._on_tool_executed
        self._agent._executor._on_tool_executed = _on_tool

        # Single normalized entry — see AutoLoop sibling above.
        from core.execution_context import TaskSource

        try:
            try:
                response = await self._agent.submit_task(
                    TaskSource.MIND,
                    prompt,
                    max_steps_override=self._config.max_rounds_per_wakeup,
                )
            except TimeoutError:
                logger.warning(
                    "Mind think cycle skipped — resource held by "
                    "another task. Will retry next wakeup."
                )
                return

            # Preemption (G): yielded for a higher-priority caller.
            # See AutoLoop sibling above for rationale.
            if getattr(response, "preempted", False):
                logger.info("[mind] think cycle preempted; will reschedule soon")
                self._next_wakeup_sec = 30.0
                return

            # Track cost
            cost = self._agent._router.cost_tracker.task_total
            self._spent_today_usd += cost

            # Truncated response content for parent-reporting payload.
            # The dashboard action summary is derived separately below
            # so meta-commentary ("Picked candidate 2…") doesn't get
            # surfaced as the agent's accomplishment.
            content = (response.content or "")[:500]

            # Action summary: prefer what the agent ACTUALLY DID
            # (tool calls executed) over the LLM's reply prose. Tool
            # calls are the ground truth of what happened this cycle.
            action_summary = _derive_action_summary(
                tool_uses=_tool_uses,
                response_content=response.content or "",
            )
            self._last_action = action_summary

            # Log action
            ts = datetime.now(UTC).strftime("%H:%M")
            self._recent_actions.append({"ts": ts, "summary": action_summary})
            if len(self._recent_actions) > 50:
                self._recent_actions = self._recent_actions[-50:]
            _append_action_log(self._project_root, action_summary)

            # Broadcast action with full details
            elapsed = time.monotonic() - cycle_start
            daily_budget = self._daily_budget()
            await self._broadcast_event(
                EventType.MIND_ACTION,
                {
                    "summary": action_summary,
                    "cost": f"${cost:.4f}",
                    "elapsed": f"{elapsed:.1f}s",
                    "tools_used": [t["tool"] for t in _tool_uses],
                    "tool_count": len(_tool_uses),
                },
            )

            # Report to parent master (child autonomy — Phase 5)
            await self._report_to_parent(content, action_summary)

            # Broadcast sleep
            await self._broadcast_event(
                EventType.MIND_SLEEP,
                {
                    "next_wakeup_seconds": int(self._next_wakeup_sec),
                    "last_action": action_summary,
                    "cycle_cost": f"${cost:.4f}",
                    "elapsed_seconds": round(elapsed, 1),
                    "total_spent": f"${self._spent_today_usd:.4f}",
                    "budget_remaining": f"${max(0, daily_budget - self._spent_today_usd):.4f}",
                    "cycle_number": self._cycle_count + 1,
                    "tools_used": len(_tool_uses),
                },
            )
        finally:
            # Restore conversation history, approval callback, and tool callback
            self._agent._conversation_history = saved_history
            self._agent._executor._approval_callback = prev_approval
            self._agent._executor._on_tool_executed = prev_tool_cb

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    # Phase 1 (docs/75-AUTONOMOUS-MIND-V2.md): a goal whose only
    # remaining checkpoint is an active one that hasn't moved in
    # >STALE_CKPT_HOURS is not workable. The previous version of this
    # helper counted any goal with status='active' as workable, which
    # let one stuck checkpoint (last_active 36h with the artifact
    # already produced) starve the dream phase for ~70 wakeups.
    _STALE_CKPT_HOURS: ClassVar[int] = 12

    async def _workable_goals_status(self) -> tuple[int, list[dict[str, Any]]]:
        """Return (workable_count, stale_summaries).

        A goal is *workable* if its parent row is in {active, planning}
        AND it has at least one checkpoint that is either:
          - status='pending' (clearly more to do), or
          - status='active' with started_at within the last
            STALE_CKPT_HOURS (still being worked on).

        A goal whose only remaining checkpoint is `active` but older
        than STALE_CKPT_HOURS is considered *stale*. Stale goals are
        excluded from the workable count (so the FORCE-DREAM gate can
        trip) AND surfaced via the second return value so the mind
        prompt can name them explicitly — the mind should close them
        via goal_status, not silently ignore them.

        Defensive — on DB error returns (999, []) so a hiccup never
        trips a false FORCE-DREAM.
        """
        try:
            gm = getattr(self._agent, "_goal_manager", None)
            if gm is None:
                return (999, [])
            workable = 0
            stale: list[dict[str, Any]] = []
            now = datetime.now(UTC)
            cutoff = now - timedelta(hours=self._STALE_CKPT_HOURS)
            cutoff_iso = cutoff.isoformat()
            db = gm._db  # noqa: SLF001 — internal collaborator
            for status in ("active", "planning"):
                goals = await gm.list_goals(status=status, limit=20)
                for g in goals:
                    rows = await db.execute(
                        "SELECT status, started_at FROM goal_checkpoints "
                        "WHERE goal_id = ? ORDER BY checkpoint_order",
                        (g.goal_id,),
                    )
                    # No checkpoints yet — a freshly-created planning
                    # goal (decompose still pending) or an active goal
                    # mid-decompose. Counts as workable; the next action
                    # is goal_decompose, not dream.
                    if not rows:
                        workable += 1
                        continue
                    has_workable_ckpt = False
                    oldest_active: str | None = None
                    for row in rows:
                        ck_status = row["status"]
                        ck_started = row["started_at"]
                        if ck_status == "pending":
                            has_workable_ckpt = True
                            break
                        if ck_status == "active":
                            if ck_started and ck_started > cutoff_iso:
                                has_workable_ckpt = True
                                break
                            if ck_started and (
                                oldest_active is None or ck_started < oldest_active
                            ):
                                oldest_active = ck_started
                    if has_workable_ckpt:
                        workable += 1
                    elif oldest_active is not None:
                        stale.append(
                            {
                                "goal_id": g.goal_id,
                                "goal": g.goal[:80],
                                "stale_since": oldest_active,
                            }
                        )
            return (workable, stale)
        except Exception as e:
            logger.debug("workable goals status failed: %s", e)
            return (999, [])

    async def _count_workable_goals(self) -> int:
        """Back-compat shim — returns just the count.

        Existing callers that only need the gate decision keep working;
        new callers should use ``_workable_goals_status`` to also get
        the stale-goal list.
        """
        count, _ = await self._workable_goals_status()
        return count

    async def _build_state_snapshot(self) -> tuple[str, str]:
        """Query all managers to build a real state snapshot for the mind.

        Returns (state_snapshot, identity_anchor) tuple.
        """
        sections: list[str] = []

        # --- Identity anchor ---
        try:
            if self._agent._identity_manager:
                identity = await self._agent._identity_manager.get_identity()
                parts: list[str] = []
                if identity.purpose:
                    parts.append(identity.purpose)
                if identity.capabilities:
                    parts.append(
                        f"Capabilities: {', '.join(identity.capabilities[:8])}"
                    )
                if parts:
                    sections.append("\n".join(parts))
        except Exception:
            pass
        identity_anchor = (
            "\n".join(sections)
            if sections
            else (
                "(no identity configured — consider setting purpose and capabilities)"
            )
        )
        sections.clear()

        # --- Active goals ---
        try:
            if self._agent._goal_manager:
                active = await self._agent._goal_manager.list_goals(
                    status="active", limit=3
                )
                for g in active:
                    nxt = await self._agent._goal_manager.get_next_checkpoint(g.goal_id)
                    nxt_str = f' — next: "{nxt.title}"' if nxt else ""
                    sections.append(
                        f'[GOAL] "{g.goal}" — {g.current_checkpoint}/{g.total_checkpoints} '
                        f"checkpoints done{nxt_str}"
                    )
                paused = await self._agent._goal_manager.list_goals(
                    status="paused", limit=3
                )
                for g in paused:
                    nxt = await self._agent._goal_manager.get_next_checkpoint(g.goal_id)
                    nxt_str = f' — next: "{nxt.title}"' if nxt else ""
                    sections.append(
                        f'[GOAL-PAUSED] "{g.goal}" — {g.current_checkpoint}/{g.total_checkpoints} '
                        f"checkpoints done{nxt_str}"
                    )
                planning = await self._agent._goal_manager.list_goals(
                    status="planning", limit=2
                )
                for g in planning:
                    sections.append(
                        f'[GOAL-PLANNING] "{g.goal}" — needs plan decomposition'
                    )
        except Exception:
            pass
        goal_text = "\n".join(sections) if sections else "(no active goals)"
        sections.clear()

        # --- Scheduled tasks ---
        try:
            if self._agent._scheduler:
                schedules = await self._agent._scheduler.list_schedules()
                for s in schedules:
                    if not s.enabled:
                        continue
                    next_run = s.next_run_at or "unknown"
                    sections.append(
                        f'[SCHEDULE] "{s.name}" — next: {next_run} — cron: {s.cron_expression}'
                    )
        except Exception:
            pass
        schedule_text = "\n".join(sections) if sections else "(no scheduled tasks)"
        sections.clear()

        # --- Recent activity (from task memory) ---
        # Show full summaries so the mind knows EXACTLY what was done and where,
        # preventing duplicate posts/actions across platforms.
        try:
            if self._agent._memory_manager:
                recent = await self._agent._memory_manager.get_recent_tasks(limit=10)
                for mem in recent:
                    outcome = mem.get("outcome", "unknown")
                    created = mem.get("created_at", "")[:16]
                    goal_str = mem["goal"][:120]
                    summary = mem.get("summary", "")[:400]
                    tools = ", ".join(mem.get("tools_used", [])[:8])
                    entry = f'[RECENT] "{goal_str}" — {outcome} — {created}'
                    if summary:
                        entry += f"\n  Summary: {summary}"
                    if tools:
                        entry += f"\n  Tools: {tools}"
                    sections.append(entry)
        except Exception:
            pass
        memory_text = "\n".join(sections) if sections else "(no prior activity)"
        sections.clear()

        # --- Knowledge drift ---
        try:
            if self._agent._indexer:
                stale = await self._agent._indexer.check_drift(self._project_root)
                if stale:
                    drift_lines: list[str] = []
                    for entry in stale[:5]:
                        sources = ", ".join(entry["stale_sources"][:3])
                        drift_lines.append(
                            f"[STALE] {entry['file_path']} — sources changed: {sources}"
                        )
                    sections.extend(drift_lines)
        except Exception:
            pass
        drift_text = "\n".join(sections) if sections else ""
        sections.clear()

        # --- Knowledge stats + user directives ---
        knowledge_text = "(empty knowledge base)"
        try:
            if self._agent._db:
                rows = await self._agent._db.execute(
                    "SELECT COUNT(*) as cnt FROM knowledge_chunks"
                )
                count = rows[0]["cnt"] if rows else 0
                if count > 0:
                    knowledge_text = f"[KNOWLEDGE] {count} chunks indexed"

                # Surface user-scoped knowledge as direct owner directives.
                # These are instructions/preferences the owner has stored —
                # the mind MUST see them every cycle to respect boundaries.
                user_rows = await self._agent._db.execute(
                    "SELECT content, heading_path FROM knowledge_chunks "
                    "WHERE scope = 'user' ORDER BY indexed_at DESC LIMIT 10"
                )
                if user_rows:
                    directives = []
                    for r in user_rows:
                        heading = r["heading_path"]
                        content = r["content"][:500]
                        label = (
                            f"[OWNER DIRECTIVE: {heading}] "
                            if heading
                            else "[OWNER DIRECTIVE] "
                        )
                        directives.append(f"{label}{content}")
                    knowledge_text += (
                        "\n\nOWNER DIRECTIVES (MUST OBEY — these override all other priorities):\n"
                        + "\n".join(directives)
                    )
        except Exception:
            pass

        # --- Agent Commune heartbeat check ---
        commune_text = ""
        try:
            if self._agent._config.commune.enabled:
                import json as _json
                import time as _time

                state_file = self._project_root / "data" / "commune_state.json"
                interval_h = self._agent._config.commune.heartbeat_interval_hours
                last_ts = 0.0
                if state_file.exists():
                    try:
                        state = _json.loads(state_file.read_text())
                        last_ts = state.get("last_checked_at", 0.0)
                    except (ValueError, OSError):
                        pass
                hours_ago = (
                    (_time.time() - last_ts) / 3600.0 if last_ts else float("inf")
                )
                if hours_ago >= interval_h:
                    if last_ts:
                        commune_text = (
                            f"\nAGENT COMMUNE: Last checked {hours_ago:.1f}h ago "
                            f"(overdue — check every {interval_h}h). "
                            "Run commune_home and engage with the community."
                        )
                    else:
                        commune_text = (
                            "\nAGENT COMMUNE: Never checked. "
                            "Run commune_home to see your feed and engage."
                        )
        except Exception:
            pass

        parts = [goal_text, schedule_text, memory_text, knowledge_text]
        if drift_text:
            parts.append(f"\nKNOWLEDGE DRIFT DETECTED:\n{drift_text}")
        if commune_text:
            parts.append(commune_text)
        return "\n".join(parts), identity_anchor

    async def _build_prompt(self) -> str:
        """Build the autonomous mind prompt with current context."""
        # Scratchpad (sync file I/O — fast)
        scratchpad = _read_scratchpad(self._project_root)
        if not scratchpad:
            scratchpad = "(empty — initialize your working memory)"

        # Drain pending events
        events_text = "(none)"
        if self._pending_events:
            events_text = "\n".join(f"- {e}" for e in self._pending_events[-10:])
            self._pending_events.clear()

        # Build real state from all managers
        state_snapshot, identity_anchor = await self._build_state_snapshot()

        # Mechanical dream gate. If there are zero active AND zero
        # planning goals, prepend a hard directive that forces dream
        # phase this cycle. The prompt's WHEN NO ACTIVE GOALS EXIST
        # block already steers the LLM toward goal_dream, but it is
        # *advisory*. Operators reported cycles where the LLM read the
        # empty snapshot and went off to check email or read files
        # instead. This gate makes the constraint mechanical: the
        # state_snapshot itself is rewritten with a [FORCE-DREAM]
        # marker that the LLM can't dismiss as soft guidance.
        workable, stale = await self._workable_goals_status()

        # Stuck-checkpoint section. When a goal has an `active`
        # checkpoint that hasn't moved in >STALE_CKPT_HOURS the mind
        # has almost certainly already produced the artifact and just
        # forgot to call goal_status. Naming the goals here gives the
        # mind the exact IDs and dates so it can close them this cycle
        # instead of repeating "bounded reconciliation" indefinitely.
        if stale:
            lines = ["[STUCK-CHECKPOINTS] You have goals whose last active"]
            lines.append("checkpoint hasn't moved in >12h. The artifact is almost")
            lines.append("certainly already produced — close them with goal_status")
            lines.append("(status='completed') BEFORE doing anything else:")
            for s in stale[:8]:
                lines.append(
                    f"  - goal_id={s['goal_id']} stale_since={s['stale_since']}"
                )
                lines.append(f"    goal: {s['goal']}")
            state_snapshot = "\n".join(lines) + "\n\n" + state_snapshot

        if workable == 0:
            state_snapshot = (
                "[FORCE-DREAM] Zero workable goals (no pending checkpoints, "
                "no recent activity on active checkpoints). This cycle MUST "
                f"call goal_dream(focus='{_dream_focus_for_today()}') followed by "
                "goal_create — UNLESS [STUCK-CHECKPOINTS] above lists goals "
                "to close first. Dream → Decide → Create.\n\n"
            ) + state_snapshot

        # Budget
        daily_budget = self._daily_budget()
        remaining = max(0, daily_budget - self._spent_today_usd)

        return _MIND_PROMPT.format(
            max_rounds=self._config.max_rounds_per_wakeup,
            identity_anchor=identity_anchor,
            state_snapshot=state_snapshot,
            scratchpad=scratchpad[:6000],
            events=events_text,
            budget_remaining=remaining,
            budget_spent=self._spent_today_usd,
            last_wakeup=self._last_wakeup_time,
            last_action=self._last_action,
            utc_now=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            dream_focus=_dream_focus_for_today(),
        )

    async def _build_arbiter_prompt(self) -> str:
        """Build the Phase 3 arbiter prompt.

        Pulls candidates from every generator, scores them, and
        renders a ranked menu in place of the legacy state-snapshot
        free-form prompt. The mind LLM picks one and executes it.

        Falls through to the legacy ``_build_prompt`` if the arbiter
        produces zero candidates — that should never happen in
        practice (the dream generator always returns a candidate)
        but the fall-through means a generator-side regression can't
        leave the mind without a prompt.
        """
        from core.mind_arbiter import ArbiterWeights, arbitrate, render_menu
        from core.mind_candidates import CandidateContext, collect_all

        # Build live mission_id → weight map so the arbiter can apply
        # the mission_weight bonus without each generator carrying it.
        mission_weight_map: dict[str, float] = {}
        if self._agent._mission_manager is not None:
            try:
                missions = await self._agent._mission_manager.list_missions()
                mission_weight_map = {m.mission_id: m.priority_weight for m in missions}
            except Exception as e:
                logger.debug("arbiter: mission map unavailable: %s", e)

        ctx = CandidateContext(
            goal_manager=self._agent._goal_manager,
            mission_manager=self._agent._mission_manager,
            identity_manager=self._agent._identity_manager,
            affect_manager=self._agent._affect_manager,
            ego_manager=self._agent._ego_manager,
            dream_focus=_dream_focus_for_today(),
            mission_weight_map=mission_weight_map,
        )

        all_candidates = await collect_all(ctx)
        if not all_candidates:
            logger.warning(
                "arbiter produced 0 candidates; falling back to legacy prompt"
            )
            return await self._build_prompt()

        weights = ArbiterWeights.from_config_dict(self._config.arbiter.weights)
        scored = arbitrate(
            all_candidates,
            weights,
            mission_weights=mission_weight_map,
            top_k=self._config.arbiter.top_k,
        )
        menu = render_menu(scored)

        # Side-channel observability: every arbiter wakeup logs the
        # menu so operators can `grep '[arbiter]'` the log and audit
        # what the mind saw + picked. Phase 4 will surface this in
        # the dashboard.
        logger.info(
            "[arbiter] focus=%s candidates=%d top_k=%d top1=%.2f",
            ctx.dream_focus,
            len(all_candidates),
            len(scored),
            scored[0].score if scored else 0.0,
        )
        for sc in scored:
            logger.info(
                "[arbiter]   %s score=%.2f  %s",
                sc.candidate.source,
                sc.score,
                sc.candidate.action_spec[:120],
            )

        # Lightweight state + scratchpad + events; the arbiter shrank
        # the prompt by replacing the wall-of-context with the menu.
        scratchpad = _read_scratchpad(self._project_root)
        if not scratchpad.strip():
            scratchpad = "(empty — initialize your working memory)"
        events_text = "(none)"
        if self._pending_events:
            events_text = "\n".join(f"- {e}" for e in self._pending_events[-10:])
            self._pending_events.clear()
        state_snapshot, identity_anchor = await self._build_state_snapshot()

        daily_budget = self._daily_budget()
        remaining = max(0, daily_budget - self._spent_today_usd)

        return _ARBITER_PROMPT.format(
            max_rounds=self._config.max_rounds_per_wakeup,
            top_k=len(scored),
            total_candidates=len(all_candidates),
            candidate_menu=menu,
            identity_anchor=identity_anchor,
            state_snapshot=state_snapshot[:3000],
            scratchpad=scratchpad[:3000],
            events=events_text,
            budget_remaining=remaining,
            budget_spent=self._spent_today_usd,
            last_wakeup=self._last_wakeup_time,
            last_action=self._last_action,
            utc_now=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        )

    # ------------------------------------------------------------------
    # Budget
    # ------------------------------------------------------------------

    def _daily_budget(self) -> float:
        """Calculate daily mind budget from config percentage."""
        daily_total = self._agent._config.llm.budget.daily_limit_usd
        return daily_total * (self._config.budget_pct / 100.0)

    def _check_budget(self) -> bool:
        """Check if mind is within its daily budget."""
        # Reset budget on new day
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if today != self._budget_reset_date:
            self._budget_reset_date = today
            self._spent_today_usd = 0.0

        return self._spent_today_usd < self._daily_budget()

    # ------------------------------------------------------------------
    # Event broadcasting
    # ------------------------------------------------------------------

    async def _broadcast_event(
        self, event_type: EventType, data: dict[str, Any]
    ) -> None:
        """Broadcast a mind event to all connected clients."""
        if self._gateway:
            await self._gateway.broadcast(
                event_message("", event_type, data), session_id=None
            )
        else:
            logger.info("Mind event [%s]: %s", event_type, data)

    # ------------------------------------------------------------------
    # Parent reporting (child autonomy)
    # ------------------------------------------------------------------

    async def _report_to_parent(self, content: str, summary: str) -> None:
        """Send autonomous mind output to the parent master agent.

        Only fires when this agent is a child with a connected parent adapter.
        The master sees these as CHILD_REPORT events and can review/approve.
        """
        adapter = getattr(self._agent, "_parent_adapter", None)
        if adapter is None:
            return

        # Skip empty or trivial output
        if not content or content.strip() == "(no output)":
            return

        try:
            await adapter.send_report(
                content=content,
                task_ref=f"mind-cycle-{self._cycle_count + 1}",
            )
            logger.info("Reported autonomous mind output to master: %s", summary[:80])
        except Exception as e:
            logger.warning("Failed to report to parent: %s", e)
