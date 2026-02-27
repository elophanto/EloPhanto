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
from datetime import UTC, datetime
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
    ts = datetime.now(UTC).strftime("%H:%M")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{ts}  {entry}\n")


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
3. Revenue > everything except active goals. Money funds your existence.
4. Never message the owner unless it matters. Silence is professionalism.
5. Update your scratchpad with what you did and what's next — use update_scratchpad.
6. Set your next wakeup based on urgency using set_next_wakeup. Don't waste compute.
7. You have {max_rounds} tool rounds. Use them efficiently.
8. If a task needs more than {max_rounds} rounds, create a goal for it.

WHEN STATE IS EMPTY (no goals, no tasks, no history):
You are not idle — you are bootstrapping. Take initiative:
- Explore your tools and capabilities (list_tools, knowledge_search)
- Search the web for revenue opportunities matching your skills
- Set up presence: find platforms to grow on, create content
- Build knowledge: index useful information, learn about your environment
- Create a goal for yourself — pick something valuable and start working toward it
Never wait for the user. You are autonomous. Act.

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
        self._task = asyncio.create_task(self._run_loop(), name="autonomous-mind")
        self._task.add_done_callback(self._on_task_done)
        logger.info(
            "Autonomous mind started (first wakeup in %ds)",
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

                # Execute think cycle
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
    # Periodic maintenance
    # ------------------------------------------------------------------

    async def _run_maintenance(self) -> None:
        """Run periodic maintenance tasks (process reaping, storage quota check)."""
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

    # ------------------------------------------------------------------
    # Think cycle
    # ------------------------------------------------------------------

    async def _think(self) -> None:
        """One think cycle: build context, call agent, broadcast results."""
        self._last_wakeup_time = datetime.now(UTC).strftime("%H:%M UTC")
        cycle_start = time.monotonic()

        # Build the prompt (async — queries real state from all managers)
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

        try:
            # Run through the agent's normal pipeline with max_rounds as step limit
            response = await self._agent.run(
                prompt,
                max_steps_override=self._config.max_rounds_per_wakeup,
            )

            # Track cost
            cost = self._agent._router.cost_tracker.task_total
            self._spent_today_usd += cost

            # Extract action summary from response
            content = (response.content or "")[:500]
            action_summary = content.split("\n")[0][:120] if content else "(no output)"
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
        try:
            if self._agent._memory_manager:
                recent = await self._agent._memory_manager.get_recent_tasks(limit=5)
                for mem in recent:
                    outcome = mem.get("outcome", "unknown")
                    created = mem.get("created_at", "")[:16]
                    goal_str = mem["goal"][:80]
                    sections.append(f'[RECENT] "{goal_str}" — {outcome} — {created}')
        except Exception:
            pass
        memory_text = "\n".join(sections) if sections else "(no prior activity)"
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

        return (
            f"{goal_text}\n{schedule_text}\n{memory_text}\n{knowledge_text}"
        ), identity_anchor

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
