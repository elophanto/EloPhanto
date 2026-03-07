"""experiment_status — view experiment journal and current state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class ExperimentStatusTool(BaseTool):
    """View the current experiment session status and journal."""

    @property
    def group(self) -> str:
        return "selfdev"

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    @property
    def name(self) -> str:
        return "experiment_status"

    @property
    def description(self) -> str:
        return (
            "View the current experiment session: config, best metric, total "
            "experiments, keep/discard/crash counts, and the last N journal entries."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "last_n": {
                    "type": "integer",
                    "description": "Number of recent journal entries to show (default: 10)",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        last_n = params.get("last_n", 10)

        config_path = self._project_root / ".experiment.json"
        if not config_path.exists():
            return ToolResult(
                success=False,
                error="No active experiment. Run experiment_setup first.",
            )

        config = json.loads(config_path.read_text(encoding="utf-8"))

        journal_path = self._project_root / "experiments.tsv"
        if not journal_path.exists():
            return ToolResult(
                success=False,
                error="Experiment journal (experiments.tsv) not found.",
            )

        lines = journal_path.read_text(encoding="utf-8").strip().splitlines()
        if len(lines) < 2:
            return ToolResult(
                success=True,
                data={"config": config, "total_experiments": 0, "entries": []},
            )

        # Parse entries
        entries = []
        keep_count = discard_count = crash_count = 0
        best_metric = None
        direction = config.get("metric_direction", "lower")

        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            commit, metric_str, status, desc = parts[0], parts[1], parts[2], parts[3]
            try:
                metric_val = float(metric_str)
            except ValueError:
                metric_val = 0.0

            entries.append(
                {
                    "commit": commit,
                    "metric": metric_val,
                    "status": status,
                    "description": desc,
                }
            )

            if status == "keep":
                keep_count += 1
                if best_metric is None:
                    best_metric = metric_val
                elif direction == "lower" and metric_val < best_metric:
                    best_metric = metric_val
                elif direction == "higher" and metric_val > best_metric:
                    best_metric = metric_val
            elif status == "discard":
                discard_count += 1
            elif status == "crash":
                crash_count += 1

        total = len(entries)
        recent = entries[-last_n:] if last_n < total else entries

        return ToolResult(
            success=True,
            data={
                "tag": config.get("tag"),
                "branch": config.get("branch"),
                "direction": direction,
                "target_files": config.get("target_files"),
                "baseline": config.get("baseline"),
                "best_metric": best_metric,
                "total_experiments": total,
                "kept": keep_count,
                "discarded": discard_count,
                "crashed": crash_count,
                "recent_entries": recent,
            },
        )
