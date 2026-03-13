"""Tests for autonomous experimentation tools."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tools.base import PermissionLevel
from tools.experimentation.autoloop_tool import AutoloopControlTool
from tools.experimentation.run_tool import ExperimentRunTool
from tools.experimentation.setup_tool import ExperimentSetupTool
from tools.experimentation.status_tool import ExperimentStatusTool

# ─── ExperimentSetupTool ───


class TestExperimentSetup:
    @pytest.fixture
    def tool(self, tmp_path: Path) -> ExperimentSetupTool:
        # Initialize a git repo in tmp_path
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
        )
        # Create a target file and initial commit
        (tmp_path / "target.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True
        )
        return ExperimentSetupTool(tmp_path)

    def test_interface(self, tool: ExperimentSetupTool) -> None:
        assert tool.name == "experiment_setup"
        assert tool.group == "selfdev"
        assert tool.permission_level == PermissionLevel.MODERATE
        schema = tool.input_schema
        assert "tag" in schema["properties"]
        assert "metric_command" in schema["properties"]
        assert "metric_extract" in schema["properties"]
        assert "metric_direction" in schema["properties"]
        assert "target_files" in schema["properties"]

    @pytest.mark.asyncio
    async def test_setup_missing_target_file(self, tool: ExperimentSetupTool) -> None:
        result = await tool.execute(
            {
                "tag": "test1",
                "metric_command": "echo 1.0",
                "metric_extract": "echo 1.0",
                "metric_direction": "lower",
                "target_files": ["nonexistent.py"],
            }
        )
        assert result.success is False
        assert "not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_setup_creates_branch_and_journal(
        self, tool: ExperimentSetupTool
    ) -> None:
        result = await tool.execute(
            {
                "tag": "test1",
                "metric_command": "echo 'done' > run.log && echo ok",
                "metric_extract": "echo 42.5",
                "metric_direction": "lower",
                "target_files": ["target.py"],
            }
        )
        assert result.success is True
        assert result.data["branch"] == "experiment/test1"
        assert result.data["baseline"] == 42.5
        assert result.data["direction"] == "lower"

        # Journal should exist with baseline entry
        journal = tool._project_root / "experiments.tsv"
        assert journal.exists()
        lines = journal.read_text().strip().splitlines()
        assert len(lines) == 2  # header + baseline
        assert "baseline" in lines[1]
        assert "42.5" in lines[1]

        # Config file should exist
        config = tool._project_root / ".experiment.json"
        assert config.exists()
        data = json.loads(config.read_text())
        assert data["tag"] == "test1"
        assert data["metric_direction"] == "lower"

    @pytest.mark.asyncio
    async def test_setup_duplicate_branch_fails(
        self, tool: ExperimentSetupTool
    ) -> None:
        # First setup
        await tool.execute(
            {
                "tag": "dup",
                "metric_command": "echo ok",
                "metric_extract": "echo 1.0",
                "metric_direction": "lower",
                "target_files": ["target.py"],
            }
        )
        # Second with same tag
        result = await tool.execute(
            {
                "tag": "dup",
                "metric_command": "echo ok",
                "metric_extract": "echo 1.0",
                "metric_direction": "lower",
                "target_files": ["target.py"],
            }
        )
        assert result.success is False
        assert "already exists" in (result.error or "")

    @pytest.mark.asyncio
    async def test_setup_baseline_failure_cleans_up(
        self, tool: ExperimentSetupTool
    ) -> None:
        result = await tool.execute(
            {
                "tag": "fail",
                "metric_command": "exit 1",
                "metric_extract": "echo 1.0",
                "metric_direction": "lower",
                "target_files": ["target.py"],
            }
        )
        assert result.success is False
        assert "failed" in (result.error or "").lower()


# ─── ExperimentRunTool ───


class TestExperimentRun:
    @pytest.fixture
    def setup(self, tmp_path: Path) -> tuple[ExperimentRunTool, Path]:
        """Create a git repo with an active experiment."""
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
        )
        (tmp_path / "target.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True
        )

        # Create experiment config
        config = {
            "tag": "test1",
            "branch": "experiment/test1",
            "metric_command": "echo ok",
            "metric_extract": "echo 40.0",
            "metric_direction": "lower",
            "target_files": ["target.py"],
            "timeout": 30,
            "baseline": 42.5,
        }
        (tmp_path / ".experiment.json").write_text(json.dumps(config))

        # Create journal with baseline
        journal = (
            "commit\tmetric\tstatus\tdescription\nabc1234\t42.500000\tkeep\tbaseline\n"
        )
        (tmp_path / "experiments.tsv").write_text(journal)

        subprocess.run(
            ["git", "add", ".experiment.json", "experiments.tsv"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "experiment setup"],
            cwd=tmp_path,
            capture_output=True,
        )

        return ExperimentRunTool(tmp_path), tmp_path

    def test_interface(self, setup: tuple[ExperimentRunTool, Path]) -> None:
        tool, _ = setup
        assert tool.name == "experiment_run"
        assert tool.group == "selfdev"
        assert tool.permission_level == PermissionLevel.MODERATE
        schema = tool.input_schema
        assert "description" in schema["properties"]

    @pytest.mark.asyncio
    async def test_no_experiment_configured(self, tmp_path: Path) -> None:
        tool = ExperimentRunTool(tmp_path)
        result = await tool.execute({"description": "test"})
        assert result.success is False
        assert "experiment_setup" in (result.error or "")

    @pytest.mark.asyncio
    async def test_no_changes_to_commit(
        self, setup: tuple[ExperimentRunTool, Path]
    ) -> None:
        tool, _ = setup
        result = await tool.execute({"description": "no changes"})
        assert result.success is False
        assert "No changes" in (result.error or "")

    @pytest.mark.asyncio
    async def test_keep_on_improvement(
        self, setup: tuple[ExperimentRunTool, Path]
    ) -> None:
        tool, tmp_path = setup
        # Make a change
        (tmp_path / "target.py").write_text("x = 2  # optimized\n")

        result = await tool.execute({"description": "optimize x"})
        assert result.success is True
        assert result.data["outcome"] == "keep"
        assert result.data["metric"] == 40.0
        assert result.data["previous_best"] == 42.5

    @pytest.mark.asyncio
    async def test_discard_on_regression(
        self, setup: tuple[ExperimentRunTool, Path]
    ) -> None:
        tool, tmp_path = setup
        # Change the extract command to return a worse metric
        config = json.loads((tmp_path / ".experiment.json").read_text())
        config["metric_extract"] = "echo 50.0"
        (tmp_path / ".experiment.json").write_text(json.dumps(config))

        # Make a change
        (tmp_path / "target.py").write_text("x = 99  # bad change\n")

        result = await tool.execute({"description": "bad change"})
        assert result.success is True
        assert result.data["outcome"] == "discard"
        assert result.data["metric"] == 50.0

    @pytest.mark.asyncio
    async def test_crash_on_run_failure(
        self, setup: tuple[ExperimentRunTool, Path]
    ) -> None:
        tool, tmp_path = setup
        config = json.loads((tmp_path / ".experiment.json").read_text())
        config["metric_command"] = "exit 1"
        (tmp_path / ".experiment.json").write_text(json.dumps(config))

        (tmp_path / "target.py").write_text("x = 3\n")

        result = await tool.execute({"description": "crash test"})
        assert result.success is True
        assert result.data["outcome"] == "crash"

    def test_get_best_metric_lower(self, setup: tuple[ExperimentRunTool, Path]) -> None:
        tool, tmp_path = setup
        journal = tmp_path / "experiments.tsv"
        journal.write_text(
            "commit\tmetric\tstatus\tdescription\n"
            "aaa\t42.5\tkeep\tbaseline\n"
            "bbb\t40.0\tkeep\timproved\n"
            "ccc\t45.0\tdiscard\tworse\n"
        )
        assert tool._get_best_metric(journal, "lower") == 40.0

    def test_get_best_metric_higher(
        self, setup: tuple[ExperimentRunTool, Path]
    ) -> None:
        tool, tmp_path = setup
        journal = tmp_path / "experiments.tsv"
        journal.write_text(
            "commit\tmetric\tstatus\tdescription\n"
            "aaa\t10.0\tkeep\tbaseline\n"
            "bbb\t15.0\tkeep\timproved\n"
        )
        assert tool._get_best_metric(journal, "higher") == 15.0

    def test_append_journal(self, setup: tuple[ExperimentRunTool, Path]) -> None:
        tool, tmp_path = setup
        journal = tmp_path / "experiments.tsv"
        original_lines = len(journal.read_text().strip().splitlines())
        tool._append_journal(journal, "abc1234", 39.5, "keep", "test entry")
        lines = journal.read_text().strip().splitlines()
        assert len(lines) == original_lines + 1
        assert "39.500000" in lines[-1]
        assert "test entry" in lines[-1]

    def test_append_journal_sanitizes_tabs(
        self, setup: tuple[ExperimentRunTool, Path]
    ) -> None:
        tool, tmp_path = setup
        journal = tmp_path / "experiments.tsv"
        tool._append_journal(journal, "abc", 1.0, "keep", "has\ttab\nand\nnewline")
        last_line = journal.read_text().strip().splitlines()[-1]
        assert "\t" not in last_line.split("\t")[3]


# ─── ExperimentStatusTool ───


class TestExperimentStatus:
    @pytest.fixture
    def setup(self, tmp_path: Path) -> ExperimentStatusTool:
        config = {
            "tag": "test1",
            "branch": "experiment/test1",
            "metric_command": "echo ok",
            "metric_extract": "echo 1.0",
            "metric_direction": "lower",
            "target_files": ["target.py"],
            "timeout": 600,
            "baseline": 42.5,
        }
        (tmp_path / ".experiment.json").write_text(json.dumps(config))
        (tmp_path / "experiments.tsv").write_text(
            "commit\tmetric\tstatus\tdescription\n"
            "aaa1234\t42.500000\tkeep\tbaseline\n"
            "bbb2345\t40.000000\tkeep\toptimize x\n"
            "ccc3456\t45.000000\tdiscard\tbad change\n"
            "ddd4567\t0.000000\tcrash\tOOM\n"
            "eee5678\t39.500000\tkeep\tfurther optimize\n"
        )
        return ExperimentStatusTool(tmp_path)

    def test_interface(self, setup: ExperimentStatusTool) -> None:
        assert setup.name == "experiment_status"
        assert setup.group == "selfdev"
        assert setup.permission_level == PermissionLevel.SAFE

    @pytest.mark.asyncio
    async def test_status_returns_summary(self, setup: ExperimentStatusTool) -> None:
        result = await setup.execute({})
        assert result.success is True
        assert result.data["tag"] == "test1"
        assert result.data["total_experiments"] == 5
        assert result.data["kept"] == 3
        assert result.data["discarded"] == 1
        assert result.data["crashed"] == 1
        assert result.data["best_metric"] == 39.5
        assert result.data["baseline"] == 42.5

    @pytest.mark.asyncio
    async def test_status_last_n(self, setup: ExperimentStatusTool) -> None:
        result = await setup.execute({"last_n": 2})
        assert result.success is True
        assert len(result.data["recent_entries"]) == 2
        assert result.data["recent_entries"][-1]["description"] == "further optimize"

    @pytest.mark.asyncio
    async def test_no_config_fails(self, tmp_path: Path) -> None:
        tool = ExperimentStatusTool(tmp_path)
        result = await tool.execute({})
        assert result.success is False
        assert "experiment_setup" in (result.error or "")

    @pytest.mark.asyncio
    async def test_higher_direction(self, tmp_path: Path) -> None:
        config = {
            "tag": "cov",
            "branch": "experiment/cov",
            "metric_command": "echo ok",
            "metric_extract": "echo 1.0",
            "metric_direction": "higher",
            "target_files": ["target.py"],
            "timeout": 600,
            "baseline": 60.0,
        }
        (tmp_path / ".experiment.json").write_text(json.dumps(config))
        (tmp_path / "experiments.tsv").write_text(
            "commit\tmetric\tstatus\tdescription\n"
            "aaa\t60.000000\tkeep\tbaseline\n"
            "bbb\t75.000000\tkeep\tadd tests\n"
            "ccc\t70.000000\tdiscard\tworse\n"
        )
        tool = ExperimentStatusTool(tmp_path)
        result = await tool.execute({})
        assert result.success is True
        assert result.data["best_metric"] == 75.0
        assert result.data["direction"] == "higher"


# ─── AutoloopControlTool ───


class TestAutoloopControl:
    @pytest.fixture
    def tool(self, tmp_path: Path) -> AutoloopControlTool:
        return AutoloopControlTool(tmp_path)

    def test_interface(self, tool: AutoloopControlTool) -> None:
        assert tool.name == "autoloop_control"
        assert tool.group == "selfdev"
        assert tool.permission_level == PermissionLevel.MODERATE
        schema = tool.input_schema
        assert "action" in schema["properties"]
        assert set(schema["properties"]["action"]["enum"]) == {
            "start",
            "stop",
            "pause",
            "status",
        }

    @pytest.mark.asyncio
    async def test_status_no_lock(self, tool: AutoloopControlTool) -> None:
        result = await tool.execute({"action": "status"})
        assert result.success is True
        assert result.data["active"] is False
        assert result.data["status"] == "none"

    @pytest.mark.asyncio
    async def test_start_creates_lock(
        self, tool: AutoloopControlTool, tmp_path: Path
    ) -> None:
        result = await tool.execute(
            {
                "action": "start",
                "tag": "apr1-perf",
                "branch": "experiment/apr1-perf",
                "max_iterations": 50,
                "max_hours": 4.0,
            }
        )
        assert result.success is True
        assert result.data["active"] is True
        assert result.data["tag"] == "apr1-perf"
        assert result.data["max_iterations"] == 50
        assert result.data["max_hours"] == 4.0

        lock_path = tmp_path / "data" / "autoloop.json"
        assert lock_path.exists()
        lock = json.loads(lock_path.read_text())
        assert lock["active"] is True
        assert lock["status"] == "running"
        assert lock["tag"] == "apr1-perf"
        assert lock["branch"] == "experiment/apr1-perf"
        assert "started_at" in lock
        assert lock["iterations_run"] == 0

    @pytest.mark.asyncio
    async def test_start_requires_tag_and_branch(
        self, tool: AutoloopControlTool
    ) -> None:
        result = await tool.execute({"action": "start"})
        assert result.success is False
        assert "tag" in (result.error or "")

    @pytest.mark.asyncio
    async def test_status_active_lock(
        self, tool: AutoloopControlTool, tmp_path: Path
    ) -> None:
        # Create lock manually
        lock_path = tmp_path / "data" / "autoloop.json"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = {
            "active": True,
            "status": "running",
            "tag": "test",
            "branch": "experiment/test",
            "started_at": time.time() - 3600,  # 1 hour ago
            "max_iterations": 100,
            "max_hours": 8.0,
            "target_metric": None,
            "iterations_run": 5,
            "best_metric": 42.0,
        }
        lock_path.write_text(json.dumps(lock))

        result = await tool.execute({"action": "status"})
        assert result.success is True
        assert result.data["active"] is True
        assert result.data["iterations_run"] == 5
        assert result.data["best_metric"] == 42.0
        assert result.data["elapsed_hours"] >= 1.0

    @pytest.mark.asyncio
    async def test_stop_deactivates_lock(
        self, tool: AutoloopControlTool, tmp_path: Path
    ) -> None:
        # Start first
        await tool.execute(
            {"action": "start", "tag": "test", "branch": "experiment/test"}
        )
        # Then stop
        result = await tool.execute({"action": "stop"})
        assert result.success is True
        assert "stopped" in result.data["message"].lower()

        lock_path = tmp_path / "data" / "autoloop.json"
        lock = json.loads(lock_path.read_text())
        assert lock["active"] is False
        assert lock["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_stop_no_lock(self, tool: AutoloopControlTool) -> None:
        result = await tool.execute({"action": "stop"})
        assert result.success is True
        assert "No active" in result.data["message"]

    @pytest.mark.asyncio
    async def test_pause_lock(self, tool: AutoloopControlTool, tmp_path: Path) -> None:
        await tool.execute(
            {"action": "start", "tag": "test", "branch": "experiment/test"}
        )
        result = await tool.execute({"action": "pause"})
        assert result.success is True

        lock_path = tmp_path / "data" / "autoloop.json"
        lock = json.loads(lock_path.read_text())
        assert lock["status"] == "paused"

    @pytest.mark.asyncio
    async def test_pause_no_lock(self, tool: AutoloopControlTool) -> None:
        result = await tool.execute({"action": "pause"})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_unknown_action(self, tool: AutoloopControlTool) -> None:
        result = await tool.execute({"action": "invalid"})
        assert result.success is False
        assert "Unknown action" in (result.error or "")

    @pytest.mark.asyncio
    async def test_start_with_target_metric(
        self, tool: AutoloopControlTool, tmp_path: Path
    ) -> None:
        result = await tool.execute(
            {
                "action": "start",
                "tag": "target-test",
                "branch": "experiment/target-test",
                "target_metric": 0.5,
            }
        )
        assert result.success is True
        lock_path = tmp_path / "data" / "autoloop.json"
        lock = json.loads(lock_path.read_text())
        assert lock["target_metric"] == 0.5


# ─── ExperimentSetup with autoloop / budget_seconds ───


class TestExperimentSetupAutoloop:
    @pytest.fixture
    def tool(self, tmp_path: Path) -> ExperimentSetupTool:
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
        )
        (tmp_path / "target.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True
        )
        return ExperimentSetupTool(tmp_path)

    @pytest.mark.asyncio
    async def test_autoloop_true_creates_lock(
        self, tool: ExperimentSetupTool, tmp_path: Path
    ) -> None:
        result = await tool.execute(
            {
                "tag": "autotest",
                "metric_command": "echo done",
                "metric_extract": "echo 10.0",
                "metric_direction": "lower",
                "target_files": ["target.py"],
                "autoloop": True,
                "max_iterations": 20,
                "max_hours": 2.0,
            }
        )
        assert result.success is True
        assert result.data["autoloop"] is True
        assert "AutoLoop" in result.data["message"]

        lock_path = tmp_path / "data" / "autoloop.json"
        assert lock_path.exists()
        lock = json.loads(lock_path.read_text())
        assert lock["active"] is True
        assert lock["tag"] == "autotest"
        assert lock["max_iterations"] == 20
        assert lock["max_hours"] == 2.0
        assert lock["best_metric"] == 10.0

    @pytest.mark.asyncio
    async def test_autoloop_false_no_lock(
        self, tool: ExperimentSetupTool, tmp_path: Path
    ) -> None:
        result = await tool.execute(
            {
                "tag": "noauto",
                "metric_command": "echo done",
                "metric_extract": "echo 10.0",
                "metric_direction": "lower",
                "target_files": ["target.py"],
                "autoloop": False,
            }
        )
        assert result.success is True
        lock_path = tmp_path / "data" / "autoloop.json"
        assert not lock_path.exists()

    @pytest.mark.asyncio
    async def test_budget_seconds_written_to_config(
        self, tool: ExperimentSetupTool, tmp_path: Path
    ) -> None:
        result = await tool.execute(
            {
                "tag": "budget-test",
                "metric_command": "echo done",
                "metric_extract": "echo 5.0",
                "metric_direction": "higher",
                "target_files": ["target.py"],
                "budget_seconds": 30,
            }
        )
        assert result.success is True
        assert result.data["budget_seconds"] == 30

        config = json.loads((tmp_path / ".experiment.json").read_text())
        assert config["budget_seconds"] == 30

    @pytest.mark.asyncio
    async def test_no_budget_not_written(
        self, tool: ExperimentSetupTool, tmp_path: Path
    ) -> None:
        result = await tool.execute(
            {
                "tag": "no-budget",
                "metric_command": "echo done",
                "metric_extract": "echo 5.0",
                "metric_direction": "higher",
                "target_files": ["target.py"],
            }
        )
        assert result.success is True
        config = json.loads((tmp_path / ".experiment.json").read_text())
        assert "budget_seconds" not in config


# ─── ExperimentRunTool with budget_seconds ───


class TestExperimentRunBudget:
    @pytest.fixture
    def setup_with_budget(self, tmp_path: Path) -> tuple[ExperimentRunTool, Path]:
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
        )
        (tmp_path / "target.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True
        )

        # Config with budget_seconds
        config = {
            "tag": "budget1",
            "branch": "experiment/budget1",
            "metric_command": "echo ok",
            "metric_extract": "echo 35.0",
            "metric_direction": "lower",
            "target_files": ["target.py"],
            "timeout": 30,
            "baseline": 42.5,
            "budget_seconds": 60,
        }
        (tmp_path / ".experiment.json").write_text(json.dumps(config))
        journal = (
            "commit\tmetric\tstatus\tdescription\nabc1234\t42.500000\tkeep\tbaseline\n"
        )
        (tmp_path / "experiments.tsv").write_text(journal)

        subprocess.run(
            ["git", "add", ".experiment.json", "experiments.tsv"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "experiment setup"],
            cwd=tmp_path,
            capture_output=True,
        )
        return ExperimentRunTool(tmp_path), tmp_path

    @pytest.mark.asyncio
    async def test_budget_in_config_is_used(
        self, setup_with_budget: tuple[ExperimentRunTool, Path]
    ) -> None:
        """budget_seconds flows from .experiment.json into run — improvement is kept."""
        tool, tmp_path = setup_with_budget
        (tmp_path / "target.py").write_text("x = 2  # faster\n")

        result = await tool.execute({"description": "speed up x"})
        assert result.success is True
        # The extract returns 35.0 which is better (lower) than 42.5 baseline
        assert result.data["outcome"] == "keep"
        assert result.data["metric"] == 35.0

    @pytest.mark.asyncio
    async def test_budget_seconds_missing_still_runs(self, tmp_path: Path) -> None:
        """Without budget_seconds the tool still runs normally (no regression)."""
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "T"],
            cwd=tmp_path,
            capture_output=True,
        )
        (tmp_path / "target.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True
        )

        config = {
            "tag": "nobud",
            "branch": "experiment/nobud",
            "metric_command": "echo ok",
            "metric_extract": "echo 30.0",
            "metric_direction": "lower",
            "target_files": ["target.py"],
            "timeout": 30,
            "baseline": 42.5,
            # no budget_seconds key
        }
        (tmp_path / ".experiment.json").write_text(json.dumps(config))
        journal = (
            "commit\tmetric\tstatus\tdescription\nabc\t42.500000\tkeep\tbaseline\n"
        )
        (tmp_path / "experiments.tsv").write_text(journal)
        subprocess.run(
            ["git", "add", ".experiment.json", "experiments.tsv"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "setup"], cwd=tmp_path, capture_output=True
        )

        tool = ExperimentRunTool(tmp_path)
        (tmp_path / "target.py").write_text("x = 99\n")
        result = await tool.execute({"description": "no budget run"})
        assert result.success is True
        assert result.data["outcome"] == "keep"
        assert result.data["metric"] == 30.0
