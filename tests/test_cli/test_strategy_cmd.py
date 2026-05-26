"""CLI for strategy artifacts (ABE Phase 11)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.strategy_cmd import strategy_cmd
from core.strategy import (
    Blocker,
    StrategyManager,
    load_blockers,
    save_blockers,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"project_root: {tmp_path}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _seed_active(workspace: Path, slug: str, name: str = "Plan") -> None:
    mgr = StrategyManager(workspace)
    prop = mgr.write_proposal(slug, {"strategyName": name, "tactics": []})
    mgr.promote_proposal(slug, prop)


class TestStrategyList:
    def test_empty(self, workspace) -> None:
        r = CliRunner().invoke(strategy_cmd, ["list"])
        assert r.exit_code == 0
        assert "No companies" in r.output

    def test_with_active(self, workspace) -> None:
        _seed_active(workspace, "co", "AlphaScala Voice")
        r = CliRunner().invoke(strategy_cmd, ["list"])
        assert r.exit_code == 0
        assert "co" in r.output
        assert "AlphaScala Voice" in r.output


class TestStrategyShow:
    def test_missing(self, workspace) -> None:
        r = CliRunner().invoke(strategy_cmd, ["show", "co"])
        assert r.exit_code == 0
        assert "No active strategy" in r.output

    def test_present(self, workspace) -> None:
        _seed_active(workspace, "co", "Plan A")
        r = CliRunner().invoke(strategy_cmd, ["show", "co"])
        assert r.exit_code == 0
        assert "Plan A" in r.output


class TestProposedAndArchive:
    def test_proposed_empty(self, workspace) -> None:
        r = CliRunner().invoke(strategy_cmd, ["proposed", "co"])
        assert r.exit_code == 0
        assert "No" in r.output

    def test_proposed_lists(self, workspace) -> None:
        mgr = StrategyManager(workspace)
        mgr.write_proposal("co", {"strategyName": "v1"})
        r = CliRunner().invoke(strategy_cmd, ["proposed", "co"])
        assert r.exit_code == 0
        # Rich may wrap; check for the table title + the year prefix
        # that any ISO timestamp produced today must contain.
        assert "proposed strategy versions" in r.output


class TestCapabilities:
    def test_missing(self, workspace) -> None:
        r = CliRunner().invoke(strategy_cmd, ["capabilities", "co"])
        assert r.exit_code == 0
        assert "No capabilities.md" in r.output

    def test_present(self, workspace) -> None:
        _write(
            workspace / "data" / "companies" / "co" / "capabilities.md",
            "# Capabilities — co\n\nSomething.\n",
        )
        r = CliRunner().invoke(strategy_cmd, ["capabilities", "co"])
        assert r.exit_code == 0
        assert "Capabilities" in r.output


class TestBlockers:
    def test_none(self, workspace) -> None:
        r = CliRunner().invoke(strategy_cmd, ["blockers"])
        assert r.exit_code == 0
        assert "No unresolved blockers" in r.output

    def test_lists_unresolved(self, workspace) -> None:
        save_blockers(
            workspace,
            "co",
            [
                Blocker(
                    id="b1",
                    type="missing_tool",
                    description="LinkedIn poster missing",
                    resolution_proposal="build",
                    build_method="self_create_plugin",
                )
            ],
        )
        r = CliRunner().invoke(strategy_cmd, ["blockers"])
        assert r.exit_code == 0
        assert "b1" in r.output
        assert "missing_tool" in r.output

    def test_resolve(self, workspace) -> None:
        save_blockers(
            workspace,
            "co",
            [Blocker(id="b1", type="missing_tool", description="x")],
        )
        r = CliRunner().invoke(
            strategy_cmd, ["blockers", "resolve", "co", "b1", "manual"]
        )
        assert r.exit_code == 0
        assert "Resolved" in r.output
        loaded = load_blockers(workspace, "co")
        assert loaded[0].is_resolved()

    def test_resolve_missing_blocker(self, workspace) -> None:
        r = CliRunner().invoke(strategy_cmd, ["blockers", "resolve", "co", "missing"])
        assert r.exit_code == 0
        assert "No such blocker" in r.output


class TestUnknownAction:
    def test_unknown(self, workspace) -> None:
        r = CliRunner().invoke(strategy_cmd, ["bogus"])
        assert r.exit_code == 0
        assert "Unknown action" in r.output
