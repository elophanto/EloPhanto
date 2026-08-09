"""Hosted product laws — nuclear absent, custody label, spend freeze."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.hosted import (
    HOSTED_CUSTODY_LABEL,
    allowed_permission_modes,
    clamp_permission_mode,
    custody_banner,
    is_hosted,
    nuclear_forbidden_reason,
)
from core.kill_switch import (
    clear_spend_freeze,
    is_spend_frozen,
    write_spend_freeze,
)


@pytest.fixture
def hosted_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELOPHANTO_CLOUD", "1")
    yield
    monkeypatch.delenv("ELOPHANTO_CLOUD", raising=False)


@pytest.fixture
def open_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ELOPHANTO_CLOUD", raising=False)
    yield


class TestHostedLaws:
    def test_is_hosted(self, hosted_env) -> None:
        assert is_hosted() is True

    def test_open_not_hosted(self, open_env) -> None:
        assert is_hosted() is False

    def test_nuclear_absent_on_hosted(self, hosted_env) -> None:
        assert "nuclear" not in allowed_permission_modes()
        assert clamp_permission_mode("nuclear") == "full_auto"
        assert nuclear_forbidden_reason() is not None

    def test_nuclear_allowed_on_open(self, open_env) -> None:
        assert "nuclear" in allowed_permission_modes()
        assert clamp_permission_mode("nuclear") == "nuclear"
        assert nuclear_forbidden_reason() is None

    def test_custody_banner_hosted(self, hosted_env) -> None:
        assert custody_banner() == HOSTED_CUSTODY_LABEL

    def test_custody_banner_open(self, open_env) -> None:
        assert custody_banner() is None


class TestSpendFreeze:
    def test_freeze_roundtrip(self, tmp_path: Path) -> None:
        assert is_spend_frozen(tmp_path) is False
        assert write_spend_freeze(tmp_path) is True
        assert is_spend_frozen(tmp_path) is True
        assert write_spend_freeze(tmp_path) is False
        assert clear_spend_freeze(tmp_path) is True
        assert is_spend_frozen(tmp_path) is False


@pytest.mark.asyncio
async def test_executor_blocks_money_when_frozen(tmp_path: Path) -> None:
    from core.config import Config, DatabaseConfig
    from core.executor import Executor
    from core.registry import ToolRegistry
    from tools.base import BaseTool, PermissionLevel, ToolResult

    class Pay(BaseTool):
        name = "crypto_transfer"
        description = "pay"
        permission_level = PermissionLevel.CRITICAL

        @property
        def input_schema(self):
            return {"type": "object", "properties": {}}

        async def execute(self, **kwargs):
            return ToolResult(success=True, output="sent")

    write_spend_freeze(tmp_path)
    cfg = Config(
        permission_mode="full_auto",
        database=DatabaseConfig(db_path=str(tmp_path / "t.db")),
        project_root=tmp_path,
    )

    reg = ToolRegistry(tmp_path)
    reg.register(Pay())
    ex = Executor(cfg, reg)
    result = await ex.execute(
        {
            "id": "call-1",
            "function": {"name": "crypto_transfer", "arguments": "{}"},
        }
    )
    assert result.error
    assert "Spend freeze" in result.error


def test_provision_mints_secrets() -> None:
    from cloud import provision as prov

    token = prov._mint_gateway_token()
    pw = prov._mint_vault_password()
    assert len(token) >= 20
    assert len(pw) >= 16
    assert token != pw


def test_missing_config_still_clamps_on_hosted(
    hosted_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.config import load_config

    missing = tmp_path / "nope.yaml"
    monkeypatch.setenv("ELOPHANTO_CONFIG", str(missing))
    cfg = load_config(missing)
    assert cfg.permission_mode != "nuclear"
    assert clamp_permission_mode(cfg.permission_mode) in (
        "ask_always",
        "smart_auto",
        "full_auto",
    )


def test_hosted_permissions_file_exists() -> None:
    root = Path(__file__).resolve().parents[2]
    assert (root / "permissions.hosted.yaml").is_file()
    assert (root / "config.hosted.yaml").is_file()
    assert (root / "profiles" / "hosted.yaml").is_file()
    assert (root / "install.sh").is_file()
    assert (root / "cloud" / "entrypoint.sh").is_file()


def test_unknown_mode_does_not_promote_on_hosted(hosted_env) -> None:
    assert clamp_permission_mode("totally_fake") == "ask_always"
    assert clamp_permission_mode("nuclear") == "full_auto"
