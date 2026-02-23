"""Tests for TOTP authenticator tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pyotp
import pytest

from tools.totp.delete_tool import TotpDeleteTool
from tools.totp.enroll_tool import TotpEnrollTool
from tools.totp.generate_tool import TotpGenerateTool
from tools.totp.list_tool import TotpListTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A valid Base32 secret for testing
_TEST_SECRET = pyotp.random_base32()


def _make_vault(data: dict[str, Any] | None = None) -> MagicMock:
    """Create a mock vault with get/set/delete/list_keys."""
    store: dict[str, Any] = dict(data) if data else {}
    vault = MagicMock()
    vault.get = MagicMock(side_effect=lambda k: store.get(k))
    vault.set = MagicMock(side_effect=lambda k, v: store.__setitem__(k, v))
    vault.delete = MagicMock(side_effect=lambda k: bool(store.pop(k, None)))
    vault.list_keys = MagicMock(side_effect=lambda: list(store.keys()))
    return vault


# ---------------------------------------------------------------------------
# TotpGenerateTool
# ---------------------------------------------------------------------------


class TestTotpGenerateTool:
    @pytest.fixture
    def tool(self) -> TotpGenerateTool:
        t = TotpGenerateTool()
        t._vault = _make_vault({"totp_github": _TEST_SECRET})
        return t

    def test_name(self) -> None:
        assert TotpGenerateTool().name == "totp_generate"

    def test_permission_safe(self) -> None:
        from tools.base import PermissionLevel

        assert TotpGenerateTool().permission_level == PermissionLevel.SAFE

    async def test_no_vault(self) -> None:
        t = TotpGenerateTool()
        result = await t.execute({"service": "github"})
        assert not result.success
        assert "Vault not available" in result.error

    async def test_service_not_found(self, tool: TotpGenerateTool) -> None:
        result = await tool.execute({"service": "nonexistent"})
        assert not result.success
        assert "No TOTP secret found" in result.error

    async def test_generate_valid_code(self, tool: TotpGenerateTool) -> None:
        result = await tool.execute({"service": "github"})
        assert result.success
        assert len(result.data["code"]) == 6
        assert result.data["code"].isdigit()
        assert 0 < result.data["seconds_remaining"] <= 30
        assert result.data["service"] == "github"

    async def test_service_name_normalized(self, tool: TotpGenerateTool) -> None:
        """Service name should be lowercased and stripped."""
        result = await tool.execute({"service": "  GitHub  "})
        assert result.success
        assert result.data["service"] == "github"

    async def test_code_matches_pyotp(self, tool: TotpGenerateTool) -> None:
        """Generated code should match what pyotp produces."""
        result = await tool.execute({"service": "github"})
        assert result.success
        # Verify the code is valid for the stored secret
        totp = pyotp.TOTP(_TEST_SECRET)
        assert totp.verify(result.data["code"])


# ---------------------------------------------------------------------------
# TotpEnrollTool
# ---------------------------------------------------------------------------


class TestTotpEnrollTool:
    @pytest.fixture
    def tool(self) -> TotpEnrollTool:
        t = TotpEnrollTool()
        t._vault = _make_vault()
        t._identity_manager = AsyncMock()
        return t

    def test_name(self) -> None:
        assert TotpEnrollTool().name == "totp_enroll"

    def test_permission_moderate(self) -> None:
        from tools.base import PermissionLevel

        assert TotpEnrollTool().permission_level == PermissionLevel.MODERATE

    async def test_no_vault(self) -> None:
        t = TotpEnrollTool()
        result = await t.execute({"service": "github", "secret": _TEST_SECRET})
        assert not result.success
        assert "Vault not available" in result.error

    async def test_invalid_secret(self) -> None:
        t = TotpEnrollTool()
        t._vault = _make_vault()
        result = await t.execute({"service": "github", "secret": "not-valid-base32!!!"})
        assert not result.success
        assert "Invalid TOTP secret" in result.error

    async def test_valid_enrollment(self, tool: TotpEnrollTool) -> None:
        result = await tool.execute(
            {
                "service": "github",
                "secret": _TEST_SECRET,
                "account": "agent@example.com",
            }
        )
        assert result.success
        assert result.data["service"] == "github"
        assert result.data["account"] == "agent@example.com"
        assert result.data["enrolled"] is True

        # Verify stored in vault
        tool._vault.set.assert_any_call("totp_github", _TEST_SECRET)

    async def test_metadata_stored(self, tool: TotpEnrollTool) -> None:
        await tool.execute(
            {"service": "aws", "secret": _TEST_SECRET, "account": "admin@corp.com"}
        )
        # Check metadata was stored
        calls = {c[0][0]: c[0][1] for c in tool._vault.set.call_args_list}
        assert "totp_aws_meta" in calls
        meta = calls["totp_aws_meta"]
        assert meta["account"] == "admin@corp.com"
        assert "enrolled_at" in meta

    async def test_backup_codes_stored(self, tool: TotpEnrollTool) -> None:
        codes = ["ABC123", "DEF456", "GHI789"]
        await tool.execute(
            {"service": "github", "secret": _TEST_SECRET, "backup_codes": codes}
        )
        calls = {c[0][0]: c[0][1] for c in tool._vault.set.call_args_list}
        assert calls.get("totp_github_backup") == codes

    async def test_no_backup_codes_no_storage(self, tool: TotpEnrollTool) -> None:
        await tool.execute({"service": "github", "secret": _TEST_SECRET})
        stored_keys = [c[0][0] for c in tool._vault.set.call_args_list]
        assert "totp_github_backup" not in stored_keys

    async def test_identity_beliefs_updated(self, tool: TotpEnrollTool) -> None:
        await tool.execute({"service": "github", "secret": _TEST_SECRET})
        tool._identity_manager.update_field.assert_called_once()
        call_args = tool._identity_manager.update_field.call_args
        assert call_args[0][0] == "beliefs"
        assert call_args[0][1] == {"totp_github": True}

    async def test_no_identity_manager_ok(self) -> None:
        """Should succeed even without identity manager."""
        t = TotpEnrollTool()
        t._vault = _make_vault()
        t._identity_manager = None
        result = await t.execute({"service": "github", "secret": _TEST_SECRET})
        assert result.success

    async def test_secret_not_in_response(self, tool: TotpEnrollTool) -> None:
        """Secret must never be returned to the LLM."""
        result = await tool.execute({"service": "github", "secret": _TEST_SECRET})
        assert _TEST_SECRET not in str(result.data)

    async def test_secret_whitespace_stripped(self, tool: TotpEnrollTool) -> None:
        """Spaces in secret should be stripped (some services format them with spaces)."""
        spaced_secret = " ".join(
            _TEST_SECRET[i : i + 4] for i in range(0, len(_TEST_SECRET), 4)
        )
        result = await tool.execute({"service": "github", "secret": spaced_secret})
        assert result.success
        # Stored secret should have no spaces
        tool._vault.set.assert_any_call("totp_github", _TEST_SECRET)


# ---------------------------------------------------------------------------
# TotpListTool
# ---------------------------------------------------------------------------


class TestTotpListTool:
    @pytest.fixture
    def tool(self) -> TotpListTool:
        t = TotpListTool()
        t._vault = _make_vault(
            {
                "totp_github": _TEST_SECRET,
                "totp_github_meta": {
                    "account": "agent@gh.com",
                    "enrolled_at": "2026-01-01",
                },
                "totp_github_backup": ["ABC", "DEF"],
                "totp_aws": _TEST_SECRET,
                "totp_aws_meta": {
                    "account": "admin@aws.com",
                    "enrolled_at": "2026-02-01",
                },
                "other_key": "not totp",
            }
        )
        return t

    def test_name(self) -> None:
        assert TotpListTool().name == "totp_list"

    def test_permission_safe(self) -> None:
        from tools.base import PermissionLevel

        assert TotpListTool().permission_level == PermissionLevel.SAFE

    async def test_no_vault(self) -> None:
        t = TotpListTool()
        result = await t.execute({})
        assert not result.success
        assert "Vault not available" in result.error

    async def test_empty_vault(self) -> None:
        t = TotpListTool()
        t._vault = _make_vault()
        result = await t.execute({})
        assert result.success
        assert result.data["services"] == []
        assert result.data["count"] == 0

    async def test_lists_services(self, tool: TotpListTool) -> None:
        result = await tool.execute({})
        assert result.success
        assert result.data["count"] == 2
        services = {s["service"] for s in result.data["services"]}
        assert services == {"github", "aws"}

    async def test_includes_metadata(self, tool: TotpListTool) -> None:
        result = await tool.execute({})
        github = next(s for s in result.data["services"] if s["service"] == "github")
        assert github["account"] == "agent@gh.com"
        assert github["enrolled_at"] == "2026-01-01"

    async def test_secrets_never_exposed(self, tool: TotpListTool) -> None:
        """Secrets must never appear in output."""
        result = await tool.execute({})
        result_str = str(result.data)
        assert _TEST_SECRET not in result_str

    async def test_excludes_meta_and_backup_keys(self, tool: TotpListTool) -> None:
        """Only main totp_ keys should appear, not _meta or _backup."""
        result = await tool.execute({})
        service_names = [s["service"] for s in result.data["services"]]
        assert "github_meta" not in service_names
        assert "github_backup" not in service_names


# ---------------------------------------------------------------------------
# TotpDeleteTool
# ---------------------------------------------------------------------------


class TestTotpDeleteTool:
    @pytest.fixture
    def tool(self) -> TotpDeleteTool:
        t = TotpDeleteTool()
        t._vault = _make_vault(
            {
                "totp_github": _TEST_SECRET,
                "totp_github_meta": {"account": "x"},
                "totp_github_backup": ["A", "B"],
            }
        )
        return t

    def test_name(self) -> None:
        assert TotpDeleteTool().name == "totp_delete"

    def test_permission_moderate(self) -> None:
        from tools.base import PermissionLevel

        assert TotpDeleteTool().permission_level == PermissionLevel.MODERATE

    async def test_no_vault(self) -> None:
        t = TotpDeleteTool()
        result = await t.execute({"service": "github"})
        assert not result.success
        assert "Vault not available" in result.error

    async def test_delete_existing(self, tool: TotpDeleteTool) -> None:
        result = await tool.execute({"service": "github"})
        assert result.success
        assert result.data["deleted"] is True
        assert result.data["service"] == "github"
        # All 3 keys should be deleted
        tool._vault.delete.assert_any_call("totp_github")
        tool._vault.delete.assert_any_call("totp_github_meta")
        tool._vault.delete.assert_any_call("totp_github_backup")

    async def test_delete_nonexistent(self) -> None:
        t = TotpDeleteTool()
        t._vault = _make_vault()
        result = await t.execute({"service": "nonexistent"})
        assert result.success
        assert result.data["deleted"] is False

    async def test_service_name_normalized(self, tool: TotpDeleteTool) -> None:
        result = await tool.execute({"service": "  GitHub  "})
        assert result.success
        assert result.data["deleted"] is True
        assert result.data["service"] == "github"
