"""autoloop_control — manage the AutoLoop focus lock."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

_AUTOLOOP_LOCK_PATH = Path("data/autoloop.json")


class AutoloopControlTool(BaseTool):
    """Manage the AutoLoop focus lock for the autonomous mind.

    When the lock is active the autonomous mind skips its normal priority
    stack (goals, schedules, Commune, etc.) and exclusively runs experiment
    iterations — one per wakeup — until a stop condition is reached or the
    user interrupts.
    """

    @property
    def group(self) -> str:
        return "selfdev"

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    @property
    def name(self) -> str:
        return "autoloop_control"

    @property
    def description(self) -> str:
        return (
            "Manage the AutoLoop focus lock. When active, the autonomous mind locks "
            "exclusively onto the running experiment session and skips all other tasks — "
            "Commune, goals, schedules, everything. It runs one experiment iteration per "
            "wakeup, forever, until a stop condition is reached or the user interrupts. "
            "Actions: 'start' (activate lock — called automatically by experiment_setup "
            "with autoloop=true), 'stop' (deactivate — mind returns to normal), "
            "'pause' (suspend without clearing state), "
            "'status' (show active session: iterations, best metric, elapsed time)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "pause", "status"],
                    "description": "Action to perform",
                },
                "tag": {
                    "type": "string",
                    "description": "Experiment tag (required for 'start')",
                },
                "branch": {
                    "type": "string",
                    "description": "Experiment git branch (required for 'start')",
                },
                "max_iterations": {
                    "type": "integer",
                    "description": "Stop after N experiment iterations (default: 100)",
                },
                "max_hours": {
                    "type": "number",
                    "description": "Stop after N hours wall-clock time (default: 8.0)",
                },
                "target_metric": {
                    "type": "number",
                    "description": (
                        "Stop when this metric value is reached (optional). "
                        "Direction (lower/higher) is read from the experiment config."
                    ),
                },
            },
            "required": ["action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        action = params["action"]
        lock_path = self._project_root / _AUTOLOOP_LOCK_PATH

        if action == "status":
            if not lock_path.exists():
                return ToolResult(
                    success=True, data={"active": False, "status": "none"}
                )
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            elapsed_h = (time.time() - lock.get("started_at", time.time())) / 3600
            return ToolResult(
                success=True,
                data={**lock, "elapsed_hours": round(elapsed_h, 2)},
            )

        elif action == "start":
            tag = params.get("tag")
            branch = params.get("branch")
            if not tag or not branch:
                return ToolResult(
                    success=False,
                    error="'start' requires 'tag' and 'branch' parameters.",
                )
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            max_iterations = params.get("max_iterations", 100)
            max_hours = params.get("max_hours", 8.0)
            lock: dict[str, Any] = {
                "active": True,
                "status": "running",
                "tag": tag,
                "branch": branch,
                "started_at": time.time(),
                "max_iterations": max_iterations,
                "max_hours": max_hours,
                "target_metric": params.get("target_metric"),
                "iterations_run": 0,
                "best_metric": None,
            }
            lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")
            return ToolResult(
                success=True,
                data={
                    "message": (
                        f"AutoLoop focus lock active for experiment/{tag}. "
                        f"Mind will run up to {max_iterations} iterations "
                        f"over {max_hours}h. All other mind tasks suspended."
                    ),
                    **lock,
                },
            )

        elif action == "stop":
            if not lock_path.exists():
                return ToolResult(success=True, data={"message": "No active AutoLoop."})
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["active"] = False
            lock["status"] = "stopped"
            lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")
            return ToolResult(
                success=True,
                data={
                    "message": "AutoLoop stopped. Mind returns to normal priority stack.",
                    "iterations_run": lock.get("iterations_run", 0),
                    "best_metric": lock.get("best_metric"),
                },
            )

        elif action == "pause":
            if not lock_path.exists():
                return ToolResult(success=False, error="No active AutoLoop to pause.")
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["status"] = "paused"
            lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")
            return ToolResult(
                success=True,
                data={
                    "message": (
                        "AutoLoop paused. Call autoloop_control action='start' "
                        "with the same tag/branch to resume."
                    )
                },
            )

        return ToolResult(success=False, error=f"Unknown action: {action}")
