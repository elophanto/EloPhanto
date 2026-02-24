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
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    ts = datetime.now(timezone.utc).strftime("%H:%M")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{ts}  {entry}\n")


# ---------------------------------------------------------------------------
# Mind prompt
# ---------------------------------------------------------------------------

_MIND_PROMPT = """\
You are EloPhanto in autonomous mode. You are not reflecting — you are working.

RULES:
1. Every wakeup must produce value. If nothing needs doing, sleep longer.
2. Revenue > everything except active goals. Money funds your existence.
3. Never message the owner unless it matters. Silence is professionalism.
4. Update your scratchpad with what you did and what's next — use update_scratchpad.
5. Set your next wakeup based on urgency using set_next_wakeup. Don't waste compute.
6. You have {max_rounds} tool rounds. Use them efficiently.
7. If a task needs more than {max_rounds} rounds, create a goal for it.

PRIORITY STACK:
{priority_stack}

SCRATCHPAD (your working memory — update it before finishing):
{scratchpad}

RECENT EVENTS:
{events}

ACTIVE GOAL:
{active_goal}

BUDGET: ${budget_remaining:.4f} remaining (${budget_spent:.4f} spent today)
LAST WAKEUP: {last_wakeup} — {last_action}
UTC NOW: {utc_now}

What is the highest-value action right now? Do it.
"""


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
        from tools.mind.wakeup_tool import SetNextWakeupTool
        from tools.mind.scratchpad_tool import UpdateScratchpadTool

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
        # First wakeup is immediate (10s warmup), then use configured interval
        self._next_wakeup_sec = 10.0
        self._task = asyncio.create_task(self._run_loop(), name="autonomous-mind")
        self._task.add_done_callback(self._on_task_done)
        logger.info(
            "Autonomous mind started (first wakeup in 10s, then every %ds)",
            self._config.wakeup_seconds,
        )
        return True

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
        """Resume mind after user task completes."""
        if not self.is_running:
            return
        if self._paused:
            logger.info("User task complete — resuming autonomous mind")
            self._paused = False
            await self._broadcast_event(
                EventType.MIND_RESUMED,
                {"pending_events": len(self._pending_events)},
            )
            self._wakeup_event.set()  # Wake up now

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
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Background loop: sleep → evaluate → act → sleep."""
        try:
            while not self._stop_requested:
                # Sleep until next wakeup (or event/resume trigger)
                self._wakeup_event.clear()
                try:
                    await asyncio.wait_for(
                        self._wakeup_event.wait(),
                        timeout=self._next_wakeup_sec,
                    )
                except TimeoutError:
                    pass  # Normal wakeup

                if self._stop_requested:
                    break

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

                # Execute think cycle
                try:
                    await self._think()
                    self._cycle_count += 1
                    # After first cycle, restore configured default if LLM didn't set it
                    if self._cycle_count == 1 and self._next_wakeup_sec <= 10.0:
                        self._next_wakeup_sec = float(self._config.wakeup_seconds)
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
    # Think cycle
    # ------------------------------------------------------------------

    async def _think(self) -> None:
        """One think cycle: build context, call agent, broadcast results."""
        self._last_wakeup_time = datetime.now(timezone.utc).strftime("%H:%M UTC")
        cycle_start = time.monotonic()

        # Build the prompt
        prompt = self._build_prompt()

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

        try:
            # Run through the agent's normal pipeline
            response = await asyncio.wait_for(
                self._agent.run(prompt),
                timeout=300,  # 5 min max per think cycle
            )

            # Track cost
            cost = self._agent._router.cost_tracker.task_cost
            self._spent_today_usd += cost

            # Extract action summary from response
            content = (response.content or "")[:500]
            action_summary = content.split("\n")[0][:120] if content else "(no output)"
            self._last_action = action_summary

            # Log action
            ts = datetime.now(timezone.utc).strftime("%H:%M")
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

        except TimeoutError:
            logger.warning("Mind think cycle timed out (300s)")
            self._last_action = "(timed out)"
            await self._broadcast_event(
                EventType.MIND_ERROR,
                {"error": "Think cycle timed out", "recovery": "will retry"},
            )
        finally:
            # Restore conversation history, approval callback, and tool callback
            self._agent._conversation_history = saved_history
            self._agent._executor._approval_callback = prev_approval
            self._agent._executor._on_tool_executed = prev_tool_cb

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_prompt(self) -> str:
        """Build the autonomous mind prompt with current context."""
        # Scratchpad
        scratchpad = _read_scratchpad(self._project_root)
        if not scratchpad:
            scratchpad = "(empty — initialize your working memory)"

        # Drain pending events
        events_text = "(none)"
        if self._pending_events:
            events_text = "\n".join(f"- {e}" for e in self._pending_events[-10:])
            self._pending_events.clear()

        # Active goal context
        active_goal = "(no active goal)"
        try:
            if self._agent._goal_manager:
                # Synchronous-safe: goal_manager methods are async, call from async context
                pass  # Will be populated by the LLM reading goal_status tool
        except Exception:
            pass

        # Priority stack (static for now — LLM sees tools and decides)
        priority_stack = (
            "1. Active goals — resume any pending checkpoint\n"
            "2. Revenue — find and execute on money-making opportunities\n"
            "3. Pending tasks — self-scheduled work from previous cycles\n"
            "4. Capability gaps — build tools/plugins you've needed\n"
            "5. Presence growth — grow accounts, post content, engage\n"
            "6. Knowledge maintenance — re-index, update stale info\n"
            "7. Opportunity scanning — search for new revenue streams"
        )

        # Budget
        daily_budget = self._daily_budget()
        remaining = max(0, daily_budget - self._spent_today_usd)

        return _MIND_PROMPT.format(
            max_rounds=self._config.max_rounds_per_wakeup,
            priority_stack=priority_stack,
            scratchpad=scratchpad[:6000],
            events=events_text,
            active_goal=active_goal,
            budget_remaining=remaining,
            budget_spent=self._spent_today_usd,
            last_wakeup=self._last_wakeup_time,
            last_action=self._last_action,
            utc_now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
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
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
