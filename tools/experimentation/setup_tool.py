"""experiment_setup — initialize an autonomous experiment session."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class ExperimentSetupTool(BaseTool):
    """Set up a new autonomous experimentation session."""

    @property
    def group(self) -> str:
        return "selfdev"

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    @property
    def name(self) -> str:
        return "experiment_setup"

    @property
    def description(self) -> str:
        return (
            "Initialize an autonomous experiment session. Creates a git branch, "
            "runs the baseline measurement, and creates the experiment journal "
            "(experiments.tsv). Use this before starting an experiment loop. "
            "Pass autoloop=true to activate the AutoLoop focus lock so the autonomous "
            "mind runs experiment iterations exclusively until stopped."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tag": {
                    "type": "string",
                    "description": "Experiment session tag (e.g. 'mar7-perf'). Branch: experiment/<tag>",
                },
                "metric_command": {
                    "type": "string",
                    "description": (
                        "Shell command to run the experiment and produce the metric. "
                        "Output should be redirected: 'uv run train.py > run.log 2>&1'"
                    ),
                },
                "metric_extract": {
                    "type": "string",
                    "description": (
                        "Shell command to extract the metric value from run.log. "
                        "Must output a single number. E.g. \"grep '^val_bpb:' run.log | awk '{print $2}'\""
                    ),
                },
                "metric_direction": {
                    "type": "string",
                    "enum": ["lower", "higher"],
                    "description": "Whether lower or higher metric values are better",
                },
                "target_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files the agent is allowed to modify (relative paths)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Soft timeout per experiment run in seconds (default: 600)",
                },
                "budget_seconds": {
                    "type": "integer",
                    "description": (
                        "Hard wall-clock budget per experiment run in seconds. "
                        "The run is killed at exactly this time (SIGTERM then SIGKILL), "
                        "making every iteration directly comparable regardless of what changed. "
                        "Like autoresearch's fixed 5-minute budget. Default: null (no fixed budget)."
                    ),
                },
                "autoloop": {
                    "type": "boolean",
                    "description": (
                        "Activate the AutoLoop focus lock. When true, the autonomous mind "
                        "will lock onto this experiment and skip all other tasks — running "
                        "one iteration per wakeup indefinitely until stopped. Default: false."
                    ),
                },
                "max_iterations": {
                    "type": "integer",
                    "description": "AutoLoop: stop after N iterations (default: 100)",
                },
                "max_hours": {
                    "type": "number",
                    "description": "AutoLoop: stop after N wall-clock hours (default: 8.0)",
                },
                "target_metric": {
                    "type": "number",
                    "description": "AutoLoop: stop when this metric value is reached (optional)",
                },
            },
            "required": [
                "tag",
                "metric_command",
                "metric_extract",
                "metric_direction",
                "target_files",
            ],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        tag = params["tag"]
        metric_command = params["metric_command"]
        metric_extract = params["metric_extract"]
        direction = params["metric_direction"]
        target_files = params["target_files"]
        timeout = min(params.get("timeout", 600), 3600)
        budget_seconds: int | None = params.get("budget_seconds")
        autoloop: bool = params.get("autoloop", False)
        max_iterations: int = params.get("max_iterations", 100)
        max_hours: float = params.get("max_hours", 8.0)
        target_metric: float | None = params.get("target_metric")

        branch = f"experiment/{tag}"
        journal = self._project_root / "experiments.tsv"

        # Validate target files exist
        for f in target_files:
            if not (self._project_root / f).exists():
                return ToolResult(success=False, error=f"Target file not found: {f}")

        # Check branch doesn't already exist
        rc, out = await self._git(["branch", "--list", branch])
        if out.strip():
            return ToolResult(
                success=False,
                error=f"Branch '{branch}' already exists. Pick a different tag.",
            )

        # Create branch
        rc, out = await self._git(["checkout", "-b", branch])
        if rc != 0:
            return ToolResult(success=False, error=f"Failed to create branch: {out}")

        # Run baseline measurement
        logger.info(f"[experiment] Running baseline: {metric_command}")
        run_timeout = budget_seconds if budget_seconds else timeout
        baseline_value, run_error = await self._run_and_extract(
            metric_command, metric_extract, run_timeout, budget_seconds=budget_seconds
        )

        if run_error:
            # Clean up: go back to previous branch
            await self._git(["checkout", "-"])
            await self._git(["branch", "-D", branch])
            return ToolResult(
                success=False,
                error=f"Baseline measurement failed: {run_error}",
            )

        # Get current commit hash
        _, commit_hash = await self._git(["rev-parse", "--short", "HEAD"])
        commit_hash = commit_hash.strip()

        # Create experiment journal
        header = "commit\tmetric\tstatus\tdescription\n"
        baseline_row = f"{commit_hash}\t{baseline_value}\tkeep\tbaseline\n"
        journal.write_text(header + baseline_row, encoding="utf-8")

        # Save experiment config as .experiment.json
        config_data: dict[str, Any] = {
            "tag": tag,
            "branch": branch,
            "metric_command": metric_command,
            "metric_extract": metric_extract,
            "metric_direction": direction,
            "target_files": target_files,
            "timeout": timeout,
            "baseline": baseline_value,
        }
        if budget_seconds:
            config_data["budget_seconds"] = budget_seconds
        config_path = self._project_root / ".experiment.json"
        config_path.write_text(json.dumps(config_data, indent=2), encoding="utf-8")

        # Commit the setup
        await self._git(["add", "experiments.tsv", ".experiment.json"])
        await self._git(
            ["commit", "-m", f"[experiment] Setup: {tag} (baseline={baseline_value})"]
        )

        # Activate AutoLoop focus lock if requested
        autoloop_msg = ""
        if autoloop:
            lock_path = self._project_root / "data" / "autoloop.json"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock: dict[str, Any] = {
                "active": True,
                "status": "running",
                "tag": tag,
                "branch": branch,
                "started_at": time.time(),
                "max_iterations": max_iterations,
                "max_hours": max_hours,
                "target_metric": target_metric,
                "iterations_run": 0,
                "best_metric": baseline_value,
            }
            lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")
            autoloop_msg = (
                f" AutoLoop focus lock active — mind will run up to "
                f"{max_iterations} iterations over {max_hours}h."
            )
            logger.info("[experiment] AutoLoop focus lock written: %s", lock_path)

        return ToolResult(
            success=True,
            data={
                "branch": branch,
                "baseline": baseline_value,
                "direction": direction,
                "target_files": target_files,
                "journal": "experiments.tsv",
                "timeout": timeout,
                "budget_seconds": budget_seconds,
                "autoloop": autoloop,
                "message": f"Experiment session '{tag}' ready.{autoloop_msg}",
            },
        )

    async def _run_and_extract(
        self,
        command: str,
        extract: str,
        timeout: int,
        *,
        budget_seconds: int | None = None,
    ) -> tuple[float | None, str | None]:
        """Run the experiment command and extract the metric value.

        If *budget_seconds* is set the run is hard-killed at exactly that
        wall-clock time (SIGTERM → 2s grace → SIGKILL), making every
        iteration directly comparable regardless of what changed.
        The soft *timeout* is used when no budget is given.
        """
        effective_timeout = budget_seconds if budget_seconds else timeout
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self._project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc.communicate(), timeout=effective_timeout)
            except TimeoutError:
                # Hard kill: SIGTERM then SIGKILL
                try:
                    proc.terminate()
                    await asyncio.sleep(2)
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.communicate()
                if budget_seconds:
                    # Budget exhausted — this is expected, not an error
                    logger.info(
                        "[experiment] Budget of %ds exhausted — evaluating metric",
                        budget_seconds,
                    )
                    # Fall through to metric extraction below
                else:
                    return None, f"Run timed out after {effective_timeout}s"

            # Non-zero exit is only a hard failure when no budget was set.
            # When a budget is set, SIGKILL produces returncode=-9 but the
            # run.log may still contain a valid metric (e.g. autoresearch prints
            # summary before the script would have stopped on its own).
            if proc.returncode not in (0, None) and not budget_seconds:
                run_log = self._project_root / "run.log"
                tail = ""
                if run_log.exists():
                    lines = run_log.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                    tail = "\n".join(lines[-50:])
                return None, f"Run failed (exit {proc.returncode}):\n{tail}"

        except Exception as e:
            return None, f"Run error: {e}"

        # Extract metric
        try:
            proc = await asyncio.create_subprocess_shell(
                extract,
                cwd=str(self._project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            value_str = stdout.decode("utf-8").strip()
            if not value_str:
                return None, "Metric extraction returned empty output"
            return float(value_str), None
        except ValueError:
            return None, f"Metric extraction returned non-numeric: {value_str!r}"
        except Exception as e:
            return None, f"Metric extraction error: {e}"

    async def _git(self, args: list[str]) -> tuple[int, str]:
        """Run a git command and return (returncode, stdout)."""
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(self._project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        return proc.returncode or 0, stdout.decode("utf-8", errors="replace")
