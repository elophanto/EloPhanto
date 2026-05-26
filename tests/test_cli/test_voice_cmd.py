"""CLI for voice contracts (ABE Phase 10 — operator-visibility loop).

Locks in:
- `elophanto voice list` shows per-company status (configured / not /
  proposal-present, exemplar counts per channel)
- `elophanto voice show <slug>` prints the active contract or a hint
- `elophanto voice proposed <slug>` prints the proposal
- `elophanto voice approve <slug>` promotes voice_proposed.yaml →
  voice.yaml; backs up an existing contract
- `elophanto voice reject <slug> <reason>` archives the proposal
  under voice_rejected/ with the reason
- `elophanto voice exemplars <slug>` shows per-channel counts
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.voice_cmd import voice_cmd


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Project workspace with a config.yaml pointing at tmp_path so
    `load_config(None)` resolves project_root = tmp_path."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"project_root: {tmp_path}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestVoiceList:
    def test_no_companies(self, workspace) -> None:
        r = CliRunner().invoke(voice_cmd, ["list"])
        assert r.exit_code == 0
        assert "No companies" in r.output

    def test_shows_configured_and_unconfigured(self, workspace) -> None:
        _write(
            workspace / "data" / "companies" / "co1" / "voice.yaml",
            "banned_phrases: [leverage]\n",
        )
        # co2: no voice but exemplars exist
        _write(
            workspace / "data" / "companies" / "co2" / "exemplars" / "twitter" / "a.md",
            "x",
        )
        _write(
            workspace / "data" / "companies" / "co2" / "exemplars" / "twitter" / "b.md",
            "y",
        )
        r = CliRunner().invoke(voice_cmd, ["list"])
        assert r.exit_code == 0
        assert "co1" in r.output
        assert "configured" in r.output
        assert "co2" in r.output
        assert "twitter=2" in r.output


class TestVoiceShow:
    def test_missing_hints_at_proposed(self, workspace) -> None:
        _write(
            workspace / "data" / "companies" / "co" / "voice_proposed.yaml",
            "persona: founder\n",
        )
        r = CliRunner().invoke(voice_cmd, ["show", "co"])
        assert r.exit_code == 0
        assert "No voice.yaml" in r.output
        # Rich may wrap; check for the keyword tokens.
        assert "approve co" in r.output.replace("\n", " ")

    def test_present(self, workspace) -> None:
        _write(
            workspace / "data" / "companies" / "co" / "voice.yaml",
            "persona: founder\nbanned_phrases: [leverage]\n",
        )
        r = CliRunner().invoke(voice_cmd, ["show", "co"])
        assert r.exit_code == 0
        assert "persona: founder" in r.output


class TestVoiceApprove:
    def test_promotes_proposed(self, workspace) -> None:
        _write(
            workspace / "data" / "companies" / "co" / "voice_proposed.yaml",
            "persona: founder\n",
        )
        r = CliRunner().invoke(voice_cmd, ["approve", "co"])
        assert r.exit_code == 0
        assert "Approved" in r.output
        assert (workspace / "data" / "companies" / "co" / "voice.yaml").is_file()
        assert not (
            workspace / "data" / "companies" / "co" / "voice_proposed.yaml"
        ).is_file()

    def test_backs_up_existing(self, workspace) -> None:
        _write(
            workspace / "data" / "companies" / "co" / "voice.yaml",
            "persona: old\n",
        )
        _write(
            workspace / "data" / "companies" / "co" / "voice_proposed.yaml",
            "persona: new\n",
        )
        r = CliRunner().invoke(voice_cmd, ["approve", "co"])
        assert r.exit_code == 0
        # New contract active
        target = workspace / "data" / "companies" / "co" / "voice.yaml"
        assert "new" in target.read_text()
        # A backup of the old one exists
        backups = list(
            (workspace / "data" / "companies" / "co").glob("voice.yaml.bak.*")
        )
        assert len(backups) == 1
        assert "old" in backups[0].read_text()

    def test_no_proposal(self, workspace) -> None:
        r = CliRunner().invoke(voice_cmd, ["approve", "co"])
        assert r.exit_code == 0
        assert "No proposal" in r.output


class TestVoiceReject:
    def test_archives_with_reason(self, workspace) -> None:
        _write(
            workspace / "data" / "companies" / "co" / "voice_proposed.yaml",
            "persona: dud\n",
        )
        r = CliRunner().invoke(voice_cmd, ["reject", "co", "too-corporate"])
        assert r.exit_code == 0
        assert "Rejected" in r.output
        # Original proposal gone
        assert not (
            workspace / "data" / "companies" / "co" / "voice_proposed.yaml"
        ).is_file()
        # Archived with reason embedded
        archived = list(
            (workspace / "data" / "companies" / "co" / "voice_rejected").glob(
                "voice_proposed.*.yaml"
            )
        )
        assert len(archived) == 1
        assert "too-corporate" in archived[0].read_text()


class TestVoiceExemplars:
    def test_shows_counts(self, workspace) -> None:
        for name in ("a.md", "b.md", "c.md"):
            _write(
                workspace
                / "data"
                / "companies"
                / "co"
                / "exemplars"
                / "twitter"
                / name,
                "x",
            )
        _write(
            workspace / "data" / "companies" / "co" / "exemplars" / "email" / "x.md",
            "y",
        )
        r = CliRunner().invoke(voice_cmd, ["exemplars", "co"])
        assert r.exit_code == 0
        assert "twitter" in r.output
        assert "3" in r.output
        # email has only 1 — marker should appear
        assert "email" in r.output
        assert "need" in r.output  # the "(need ≥2)" warning

    def test_empty(self, workspace) -> None:
        r = CliRunner().invoke(voice_cmd, ["exemplars", "co"])
        assert r.exit_code == 0
        assert "No exemplars" in r.output


class TestVoiceExtract:
    def test_hints_at_agent_path(self, workspace) -> None:
        r = CliRunner().invoke(voice_cmd, ["extract", "co"])
        assert r.exit_code == 0
        assert "elophanto chat" in r.output
        assert "voice_extract" in r.output


class TestUnknownAction:
    def test_unknown(self, workspace) -> None:
        r = CliRunner().invoke(voice_cmd, ["bogus"])
        assert r.exit_code == 0
        assert "Unknown action" in r.output
