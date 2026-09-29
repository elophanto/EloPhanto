"""docs/95 Phases F and G — playbooks tuned against the benchmark, training data."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.bench import bench_editable, is_bench_metric
from core.config import GoalsConfig
from core.database import Database
from core.goal_manager import GoalManager
from core.training_export import export
from tools.experimentation.run_tool import ExperimentRunTool
from tools.experimentation.setup_tool import ExperimentSetupTool

BENCH = ".venv/bin/python -m cli.main bench run --metric > run.log 2>&1"


class TestBoundary:
    def test_what_a_benchmark_experiment_may_touch(self) -> None:
        assert is_bench_metric(BENCH) and is_bench_metric(
            "elophanto bench  run --metric"
        )
        assert not is_bench_metric("uv run train.py > run.log")
        allowed = [
            "skills/a/SKILL.md",
            "skills/",
            "knowledge/system/x.md",
            "AGENT_PROGRAM.md",
        ]
        refused = [
            "core/agent.py",
            "skills/../core/x.py",
            "/etc/hosts",
            "skillsx/a",
            "config.yaml",
        ]
        assert all(bench_editable(p) for p in allowed)
        assert not any(bench_editable(p) for p in refused)

    async def test_setup_refuses_code_targets(self, tmp_path: Path) -> None:
        (tmp_path / "core").mkdir()
        (tmp_path / "core" / "agent.py").write_text("x")
        res = await ExperimentSetupTool(tmp_path).execute(
            {
                "tag": "t",
                "metric_command": BENCH,
                "metric_extract": "grep x",
                "metric_direction": "higher",
                "target_files": ["core/agent.py"],
            }
        )
        assert not res.success and "core/agent.py" in (res.error or "")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "skills" / "a").mkdir(parents=True)
    (tmp_path / "skills" / "a" / "SKILL.md").write_text("v1\n")
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "x.py").write_text("v1\n")
    (tmp_path / "experiments.tsv").write_text(
        "commit\tmetric\tstatus\tdescription\nabc\t0.4\tkeep\tbaseline\n"
    )
    (tmp_path / ".experiment.json").write_text(
        json.dumps(
            {
                "metric_command": "echo 'bench_score: 0.6' > run.log",
                "metric_extract": "grep '^bench_score:' run.log | awk '{print $2}'",
                "metric_direction": "higher",
                "target_files": ["skills/a/SKILL.md"],
                "timeout": 30,
                "restrict_to_targets": True,
            }
        )
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


class TestRunBoundary:
    async def test_a_change_outside_the_targets_is_refused(self, repo: Path) -> None:
        (repo / "skills" / "a" / "SKILL.md").write_text("v2\n")
        (repo / "core" / "x.py").write_text("v2\n")
        res = await ExperimentRunTool(repo).execute({"description": "try"})
        assert not res.success and "core/x.py" in (res.error or "")
        assert _git(repo, "diff", "--cached", "--name-only").strip() == ""
        assert (repo / "core" / "x.py").read_text() == "v2\n"  # unstaged, not destroyed

    async def test_a_playbook_change_is_measured(self, repo: Path) -> None:
        (repo / "skills" / "a" / "SKILL.md").write_text("v2\n")
        res = await ExperimentRunTool(repo).execute({"description": "clearer steps"})
        assert (
            res.success and res.data["outcome"] == "keep" and res.data["metric"] == 0.6
        )


@pytest.fixture
async def db(tmp_path: Path):
    d = Database(tmp_path / "train.db")
    await d.initialize()
    yield d
    await d.close()


async def _trace(
    db: Database, goal_id: str, attempt: int, output: str, passed: int
) -> None:
    await db.execute_insert(
        "INSERT INTO tool_traces (goal_id, checkpoint_order, attempt, seq, tool, params, "
        "status, error, output, passed, created_at) VALUES (?, 1, ?, 0, 'watch_list', "
        "'{\"register\": \"main\"}', 'ok', '', ?, ?, ?)",
        (goal_id, attempt, output, passed, f"2026-09-29T0{attempt}:00:00+00:00"),
    )


class TestTrainingExport:
    async def test_sft_and_preference_from_verified_runs(
        self, db: Database, tmp_path: Path
    ) -> None:
        gm = GoalManager(db=db, router=None, config=GoalsConfig())
        g = await gm.create_goal("List subjects")
        await db.execute_insert(
            "INSERT INTO goal_checkpoints (goal_id, checkpoint_order, title, description, "
            "success_criteria, status, result_summary) VALUES (?, 1, 'List subjects', 'd', "
            "'14 listed', 'completed', 'Listed 14.\n[receipt] ok')",
            (g.goal_id,),
        )
        await _trace(db, g.goal_id, 1, '{"success": true, "count": 12}', 0)
        await _trace(
            db, g.goal_id, 2, '{"success": true, "count": 14, "ssn": "123-45-6789"}', 1
        )
        # A checkpoint that never passed teaches nothing.
        await _trace(db, "other", 1, '{"success": false}', 0)

        result = await export(db, tmp_path / "out")
        assert (result["sft"], result["preference"]) == (1, 1)
        (sft,) = [
            json.loads(line) for line in result["sft_path"].read_text().splitlines()
        ]
        roles = [m["role"] for m in sft["messages"]]
        assert roles == ["user", "assistant", "tool", "assistant"]
        assert "CURRENT CHECKPOINT (1 of" in sft["messages"][0]["content"]
        call = sft["messages"][1]["tool_calls"][0]["function"]
        assert call["name"] == "watch_list" and json.loads(call["arguments"]) == {
            "register": "main"
        }
        assert "123-45-6789" not in sft["messages"][2]["content"]
        assert sft["messages"][3]["content"] == "Listed 14."
        (pair,) = [
            json.loads(line)
            for line in result["preference_path"].read_text().splitlines()
        ]
        assert '"count": 14' in pair["chosen"][1]["content"]
        assert '"count": 12' in pair["rejected"][1]["content"]
        assert pair["metadata"]["rejected_attempt"] == 1
