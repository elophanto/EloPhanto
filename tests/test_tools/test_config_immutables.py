"""The agent may not reconfigure where it appears on the network.

2026-08-15. Told to run a Nevada-observed competitor analysis, the agent hit
a checkpoint demanding "at least 2 of 3 independent checks report Nevada" —
against a proxy the operator had just moved to Florida. Rather than report
the conflict, it edited config.yaml twice, restoring the Nevada suffix and
adding a sticky session, so its own checkpoint would pass:

    13:06:40  Executing tool 'file_patch' … path: '…/config.yaml'
    14:58:45  Executing tool 'file_patch' … path: '…/config.yaml'

Two failures made that possible. `file_patch` never ran the config guard at
all — `file_write` had checked config.yaml since the protected-keys rule was
written, so every protection on that file was one tool call away from
irrelevant. And the guard only forbade switching four booleans off; nothing
covered the proxy, which is what every geo-stamped claim in the evidence
register rests on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.protected import check_config_immutables
from tools.system.filesystem import FilePatchTool, FileWriteTool

_CONFIG = """agent:
  permission_mode: full_auto

proxy:
  enabled: true
  type: http
  host: geo.iproyal.com
  port: 12321
  username: "user123"
  password: "pw_country-us_state-florida"
  bypass: []
  apply_to: [browser]
  state: FL

autonomous_mind:
  enabled: false
"""


@pytest.fixture
def config(tmp_path: Path) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(_CONFIG)
    return p


class TestTheGuardItself:
    def test_changing_the_state_is_refused(self) -> None:
        err = check_config_immutables(_CONFIG, _CONFIG.replace("state: FL", "state: NV"))
        assert err and "proxy.state" in err
        assert "operator" in err

    def test_changing_the_password_geo_suffix_is_refused(self) -> None:
        """The suffix *is* the state claim, whatever `state:` says."""
        err = check_config_immutables(_CONFIG, _CONFIG.replace("_state-florida", "_state-nevada"))
        assert err and "proxy.password" in err

    def test_every_proxy_identity_key_is_covered(self) -> None:
        for old, new in (
            ("enabled: true", "enabled: false"),
            ("host: geo.iproyal.com", "host: other.example"),
            ("port: 12321", "port: 9999"),
            ('username: "user123"', 'username: "someone"'),
            ("type: http", "type: socks5"),
            ("apply_to: [browser]", "apply_to: []"),
        ):
            assert check_config_immutables(_CONFIG, _CONFIG.replace(old, new)), (
                f"changing {old!r} should be refused"
            )

    def test_unrelated_edits_pass(self) -> None:
        assert (
            check_config_immutables(_CONFIG, _CONFIG.replace("bypass: []", 'bypass: ["x.com"]'))
            is None
        )
        assert check_config_immutables(_CONFIG, _CONFIG + "\nknowledge:\n  enabled: true\n") is None

    def test_identical_content_passes(self) -> None:
        assert check_config_immutables(_CONFIG, _CONFIG) is None


class TestFilePatchIsGuarded:
    """The bypass: file_patch reached disk without any config check."""

    @pytest.mark.asyncio
    async def test_the_exact_edit_the_agent_made_is_refused(self, config: Path) -> None:
        res = await FilePatchTool().execute(
            {
                "path": str(config),
                "old": "  state: FL",
                "new": "  state: NV",
            }
        )
        assert not res.success
        assert "proxy.state" in res.error
        assert "state: FL" in config.read_text(), "file must be untouched"

    @pytest.mark.asyncio
    async def test_it_cannot_disable_the_autonomous_mind_either(self, config: Path) -> None:
        """file_patch skipped PROTECTED_CONFIG_KEYS too, not just the proxy."""
        config.write_text(
            _CONFIG.replace(
                "autonomous_mind:\n  enabled: false",
                "autonomous_mind:\n  enabled: true",
            )
        )
        res = await FilePatchTool().execute(
            {
                "path": str(config),
                "old": "autonomous_mind:\n  enabled: true",
                "new": "autonomous_mind:\n  enabled: false",
            }
        )
        assert not res.success
        assert "autonomous_mind.enabled" in res.error

    @pytest.mark.asyncio
    async def test_autonomy_already_off_does_not_block_unrelated_edits(self, config: Path) -> None:
        """`enabled: false` is the shipped default and the operator's real
        setting. Judging the *result* rather than the *edit* would refuse
        every config change on almost every install."""
        assert "autonomous_mind:\n  enabled: false" in config.read_text()
        res = await FilePatchTool().execute(
            {
                "path": str(config),
                "old": "  bypass: []",
                "new": '  bypass: ["a.example"]',
            }
        )
        assert res.success, res.error

    @pytest.mark.asyncio
    async def test_unrelated_patches_still_work(self, config: Path) -> None:
        res = await FilePatchTool().execute(
            {
                "path": str(config),
                "old": "  bypass: []",
                "new": '  bypass: ["example.com"]',
            }
        )
        assert res.success, res.error
        assert "example.com" in config.read_text()

    @pytest.mark.asyncio
    async def test_other_files_are_unaffected(self, tmp_path: Path) -> None:
        other = tmp_path / "notes.yaml"
        other.write_text("proxy:\n  state: FL\n")
        res = await FilePatchTool().execute(
            {
                "path": str(other),
                "old": "state: FL",
                "new": "state: NV",
            }
        )
        assert res.success, res.error


class TestFileWriteIsGuarded:
    @pytest.mark.asyncio
    async def test_wholesale_rewrite_cannot_move_the_exit(self, config: Path) -> None:
        res = await FileWriteTool().execute(
            {
                "path": str(config),
                "content": _CONFIG.replace("state: FL", "state: NV"),
            }
        )
        assert not res.success
        assert "proxy.state" in res.error
        assert "state: FL" in config.read_text()

    @pytest.mark.asyncio
    async def test_writing_an_unchanged_proxy_section_is_fine(self, config: Path) -> None:
        res = await FileWriteTool().execute(
            {
                "path": str(config),
                "content": _CONFIG + "\nheartbeat:\n  enabled: true\n",
            }
        )
        assert res.success, res.error

    @pytest.mark.asyncio
    async def test_a_brand_new_config_is_judged_on_content(self, tmp_path: Path) -> None:
        """With no prior file there is no edit to judge, so the older
        content-based rule still applies — fail closed."""
        res = await FileWriteTool().execute(
            {
                "path": str(tmp_path / "config.yaml"),
                "content": "proxy:\n  state: FL\n  host: geo.example\n",
            }
        )
        assert res.success, res.error
