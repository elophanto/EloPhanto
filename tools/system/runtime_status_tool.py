"""``runtime_status`` — what is actually running, and how to stop it.

The agent already had status tools for the *spawn* tiers — ``swarm_status``,
``kid_list``, ``organization_status``. It had none for the things that run
without anyone asking: the goal runner, the heartbeat, the autonomous mind,
the scheduler.

That gap produced a concrete failure. Asked "are the multiagents still
running?", the agent checked the three spawn tiers, found zero, and answered
"managed multiagents are not still working — I have not resumed the learning
goal or autonomous mind." The log for that same minute reads:

    10:28:25  REL src=USER  held=42.78s
    10:28:25  ACQ src=GOAL             <- resumed the instant it finished
    10:28:25  _run_with_history entered for: ... CURRENT CHECKPOINT (9 of 16)

The GoalRunner had auto-resumed on startup, been preempted by the question,
and taken the loop straight back. The answer was false, and nothing the agent
could reach would have told it otherwise.

Auto-resume is wanted behaviour. Being unable to answer honestly about it is
not, and being told without being able to act on it is worse. So this tool
reports every autonomous execution surface in one place, and every entry
carries the exact command that stops it — a status report that leaves the
operator without a lever is only half an answer.

CORE tier deliberately: "is anything running?" must be answerable under every
tool profile, including the trimmed ones.
"""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult, ToolTier

logger = logging.getLogger(__name__)


class RuntimeStatusTool(BaseTool):
    """Report every autonomous loop, and how to halt each one."""

    def __init__(self) -> None:
        self._agent: Any = None  # injected by Agent at startup

    @property
    def name(self) -> str:
        return "runtime_status"

    @property
    def group(self) -> str:
        return "system"

    @property
    def tier(self) -> ToolTier:
        # Always visible. The question this answers must never be
        # unanswerable because of a profile trim.
        return ToolTier.CORE

    @property
    def description(self) -> str:
        return (
            "Report everything currently running on its own: the goal runner "
            "(and which goal/checkpoint), the heartbeat, the autonomous mind, "
            "the scheduler, plus swarm/kid/organization agents. ALWAYS call "
            "this before telling the user whether anything is running, is "
            "paused, or has resumed — those loops restart themselves and the "
            "spawn-tier status tools do not see them. Also returns the exact "
            "command to stop each one."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._agent is None:
            return ToolResult(
                success=False, error="runtime_status needs an agent context."
            )

        agent = self._agent
        loops: list[dict[str, Any]] = []

        # ── Goal runner: the one that auto-resumes on startup ──────────
        runner = getattr(agent, "_goal_runner", None)
        goal_entry: dict[str, Any] = {
            "name": "goal_runner",
            "running": False,
            "detail": "no goal executing",
            "stop_with": "say 'stop' (cancels the run) or 'stop --cancel-goals'",
        }
        if runner is not None:
            try:
                running = bool(runner.is_running)
                goal_entry["running"] = running
                goal_id = getattr(runner, "current_goal_id", None)
                if running and goal_id:
                    goal_entry["goal_id"] = goal_id
                    goal_entry["detail"] = f"executing goal {goal_id}"
                    manager = getattr(agent, "_goal_manager", None)
                    if manager is not None:
                        try:
                            goal = await manager.get_goal(goal_id)
                            if goal is not None:
                                goal_entry["goal"] = getattr(goal, "goal", "")[:200]
                                goal_entry["status"] = getattr(goal, "status", "")
                        except Exception:  # pragma: no cover — best effort
                            pass
            except Exception as exc:  # pragma: no cover — never break the report
                goal_entry["detail"] = f"unavailable: {exc}"
        loops.append(goal_entry)

        # ── Heartbeat ──────────────────────────────────────────────────
        heartbeat = getattr(agent, "_heartbeat_engine", None)
        hb: dict[str, Any] = {
            "name": "heartbeat",
            "running": False,
            "detail": "not started",
            "stop_with": "set heartbeat.enabled: false, or `elophanto stop`",
        }
        if heartbeat is not None:
            try:
                hb["running"] = bool(heartbeat.is_running)
                interval = getattr(
                    getattr(heartbeat, "_config", None), "check_interval_seconds", None
                )
                hb["detail"] = (
                    f"checking HEARTBEAT.md every {interval}s"
                    if hb["running"] and interval
                    else ("running" if hb["running"] else "not started")
                )
            except Exception as exc:  # pragma: no cover
                hb["detail"] = f"unavailable: {exc}"
        loops.append(hb)

        # ── Autonomous mind ────────────────────────────────────────────
        mind = getattr(agent, "_autonomous_mind", None)
        mind_entry: dict[str, Any] = {
            "name": "autonomous_mind",
            "running": False,
            "detail": "not started",
            "stop_with": "set autonomous_mind.enabled: false, or `elophanto stop`",
        }
        if mind is not None:
            try:
                running = bool(mind.is_running)
                paused = bool(getattr(mind, "is_paused", False))
                mind_entry["running"] = running
                mind_entry["paused"] = paused
                mind_entry["detail"] = (
                    "paused"
                    if running and paused
                    else ("thinking" if running else "not started")
                )
            except Exception as exc:  # pragma: no cover
                mind_entry["detail"] = f"unavailable: {exc}"
        loops.append(mind_entry)

        # ── Scheduler ──────────────────────────────────────────────────
        scheduler = getattr(agent, "_scheduler", None)
        sched: dict[str, Any] = {
            "name": "scheduler",
            "running": False,
            "detail": "not started",
            "stop_with": "`elophanto schedule disable <id>`, or `elophanto stop`",
        }
        if scheduler is not None:
            try:
                sched["running"] = bool(scheduler.is_running)
                jobs = getattr(getattr(scheduler, "_scheduler", None), "get_jobs", None)
                if callable(jobs):
                    sched["armed_jobs"] = len(jobs())
                sched["detail"] = (
                    f"{sched.get('armed_jobs', '?')} job(s) armed"
                    if sched["running"]
                    else "not started"
                )
            except Exception as exc:  # pragma: no cover
                sched["detail"] = f"unavailable: {exc}"
        loops.append(sched)

        # ── Spawn tiers ────────────────────────────────────────────────
        spawned = await self._spawn_counts(agent)

        # ── Kill-switch state ──────────────────────────────────────────
        stopped = spend_frozen = False
        try:
            from core.kill_switch import is_spend_frozen, is_stopped, resolve_data_dir

            data_dir = resolve_data_dir(agent._config)
            stopped = is_stopped(data_dir)
            spend_frozen = is_spend_frozen(data_dir)
        except Exception as exc:  # pragma: no cover
            logger.debug("kill-switch state unavailable: %s", exc)

        active = [entry["name"] for entry in loops if entry.get("running")]
        active += [f"{k} ({v})" for k, v in spawned.items() if isinstance(v, int) and v]

        return ToolResult(
            success=True,
            data={
                "anything_running": bool(active),
                "active": active,
                "loops": loops,
                "spawned_agents": spawned,
                "kill_switch": {
                    "stopped": stopped,
                    "spend_frozen": spend_frozen,
                },
                "how_to_stop_everything": (
                    "`elophanto stop` (or say 'stop --hard') writes the STOP "
                    "sentinel, which every loop checks between rounds and "
                    "wakeups. `elophanto resume` clears it."
                ),
                "note": (
                    "The goal runner resumes an active goal automatically on "
                    "startup, so it can be running without the user having "
                    "asked in this session. Report that plainly rather than "
                    "saying nothing is running."
                ),
            },
        )

    @staticmethod
    async def _spawn_counts(agent: Any) -> dict[str, Any]:
        """Counts for the spawn tiers, each degrading to 'unavailable'."""
        out: dict[str, Any] = {}

        swarm = getattr(agent, "_swarm_manager", None)
        try:
            out["swarm"] = len(await swarm.list_projects()) if swarm is not None else 0
        except Exception:
            out["swarm"] = "unavailable"

        kids = getattr(agent, "_kid_manager", None)
        try:
            out["kids"] = len(await kids.list_kids()) if kids is not None else 0
        except Exception:
            out["kids"] = "unavailable"

        # list_children is synchronous here, unlike its two neighbours.
        org = getattr(agent, "_organization_manager", None)
        try:
            out["organization"] = len(org.list_children()) if org is not None else 0
        except Exception:
            out["organization"] = "unavailable"

        return out
