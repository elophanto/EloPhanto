"""experiment_run — execute one iteration of the experiment loop."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class ExperimentRunTool(BaseTool):
    """Run one experiment iteration: measure, compare, keep or discard."""

    @property
    def group(self) -> str:
        return "selfdev"

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    @property
    def name(self) -> str:
        return "experiment_run"

    @property
    def description(self) -> str:
        return (
            "Run one experiment iteration. Commits current changes, runs the "
            "measurement command, extracts the metric, and decides whether to "
            "keep (metric improved) or discard (revert). Logs the result to "
            "experiments.tsv. Call experiment_setup first."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Short description of what this experiment tries",
                },
            },
            "required": ["description"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        description = params["description"]

        # Load experiment config
        config_path = self._project_root / ".experiment.json"
        if not config_path.exists():
            return ToolResult(
                success=False,
                error="No active experiment. Run experiment_setup first.",
            )

        config = json.loads(config_path.read_text(encoding="utf-8"))
        metric_command = config["metric_command"]
        metric_extract = config["metric_extract"]
        direction = config["metric_direction"]
        timeout = config.get("timeout", 600)
        budget_seconds: int | None = config.get("budget_seconds")

        # Get current best metric from journal
        journal_path = self._project_root / "experiments.tsv"
        best_metric = self._get_best_metric(journal_path, direction)
        if best_metric is None:
            return ToolResult(
                success=False,
                error="Cannot read baseline from experiments.tsv",
            )

        # Commit the experimental change
        rc, _ = await self._git(["add", "-A"])
        rc, diff_out = await self._git(["diff", "--cached", "--stat"])
        if not diff_out.strip():
            return ToolResult(
                success=False,
                error="No changes to experiment with. Modify target files first.",
            )

        commit_msg = f"[experiment] {description}"
        await self._git(["commit", "-m", commit_msg])

        # Get commit hash
        _, commit_hash = await self._git(["rev-parse", "--short", "HEAD"])
        commit_hash = commit_hash.strip()

        # Run the experiment
        logger.info(f"[experiment] Running: {description}")
        metric_value, run_error = await self._run_and_extract(
            metric_command, metric_extract, timeout, budget_seconds=budget_seconds
        )

        if run_error or metric_value is None:
            # Crash — revert
            await self._git(["reset", "--hard", "HEAD~1"])
            self._append_journal(journal_path, commit_hash, 0.0, "crash", description)
            return ToolResult(
                success=True,
                data={
                    "outcome": "crash",
                    "error": run_error or "No metric returned",
                    "description": description,
                    "best_metric": best_metric,
                },
            )

        # Compare metric (metric_value is guaranteed float here)
        improved = (
            (metric_value < best_metric)
            if direction == "lower"
            else (metric_value > best_metric)
        )

        if improved:
            self._append_journal(
                journal_path, commit_hash, metric_value, "keep", description
            )
            # Stage journal update
            await self._git(["add", "experiments.tsv"])
            await self._git(["commit", "--amend", "--no-edit"])
            logger.info(
                f"[experiment] KEEP: {metric_value} (was {best_metric}) — {description}"
            )
            return ToolResult(
                success=True,
                data={
                    "outcome": "keep",
                    "metric": metric_value,
                    "previous_best": best_metric,
                    "improvement": abs(metric_value - best_metric),
                    "description": description,
                },
            )
        else:
            # Discard — revert the commit
            self._append_journal(
                journal_path, commit_hash, metric_value, "discard", description
            )
            await self._git(["reset", "--hard", "HEAD~1"])
            # Re-write journal on the reverted state (it was part of the reverted commit)
            self._append_journal(
                journal_path, commit_hash, metric_value, "discard", description
            )
            logger.info(
                f"[experiment] DISCARD: {metric_value} (best {best_metric}) — {description}"
            )
            return ToolResult(
                success=True,
                data={
                    "outcome": "discard",
                    "metric": metric_value,
                    "best_metric": best_metric,
                    "description": description,
                },
            )

    def _get_best_metric(self, journal_path: Path, direction: str) -> float | None:
        """Read the best metric from kept experiments in the journal."""
        if not journal_path.exists():
            return None
        lines = journal_path.read_text(encoding="utf-8").strip().splitlines()
        if len(lines) < 2:  # header + at least one entry
            return None

        best = None
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            status = parts[2]
            if status != "keep":
                continue
            try:
                val = float(parts[1])
            except ValueError:
                continue
            if best is None:
                best = val
            elif direction == "lower" and val < best:
                best = val
            elif direction == "higher" and val > best:
                best = val
        return best

    def _append_journal(
        self, journal_path: Path, commit: str, metric: float, status: str, desc: str
    ) -> None:
        """Append an entry to the experiment journal."""
        # Sanitize description: no tabs or newlines
        desc_clean = desc.replace("\t", " ").replace("\n", " ")
        line = f"{commit}\t{metric:.6f}\t{status}\t{desc_clean}\n"
        with open(journal_path, "a", encoding="utf-8") as f:
            f.write(line)

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
        wall-clock time (SIGTERM → 2s grace → SIGKILL), ensuring every
        iteration is directly comparable. The metric is still extracted from
        run.log after the kill — autoresearch-style scripts print their
        summary before the time limit.
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
                try:
                    proc.terminate()
                    await asyncio.sleep(2)
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.communicate()
                if not budget_seconds:
                    return None, f"Run timed out after {effective_timeout}s"
                # Budget exhausted — expected, fall through to metric extraction
                logger.info(
                    "[experiment] Budget of %ds exhausted — extracting metric from run.log",
                    budget_seconds,
                )

            # Non-zero exit is only a hard failure without a budget.
            # With budget: the SIGKILL produces returncode=-9 but run.log
            # may still contain a valid metric.
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
