"""Tests for core/authority.py — authority tier resolution and tool filtering."""

from __future__ import annotations

from unittest.mock import MagicMock

from core.authority import (
    AuthorityLevel,
    check_tool_authority,
    filter_tools_for_authority,
    resolve_authority,
)
from core.config import AuthorityConfig, AuthorityTierConfig
from tools.base import PermissionLevel

# ---------------------------------------------------------------------------
# Helper to create mock tools
# ---------------------------------------------------------------------------


def _mock_tool(
    name: str, permission: PermissionLevel = PermissionLevel.SAFE
) -> MagicMock:
    t = MagicMock()
    t.name = name
    t.permission_level = permission
    return t


# ---------------------------------------------------------------------------
# resolve_authority
# ---------------------------------------------------------------------------


class TestResolveAuthority:
    def test_cli_always_owner(self) -> None:
        """CLI channel should always return OWNER regardless of config."""
        config = AuthorityConfig(
            owner=AuthorityTierConfig(user_ids=["telegram:999"]),
        )
        assert resolve_authority("cli", "anyone", config) == AuthorityLevel.OWNER
        assert resolve_authority("local", "anyone", config) == AuthorityLevel.OWNER
        assert resolve_authority("direct", "anyone", config) == AuthorityLevel.OWNER

    def test_no_config_all_owner(self) -> None:
        """No authority config (None) should default all users to OWNER."""
        assert resolve_authority("telegram", "123456", None) == AuthorityLevel.OWNER
        assert resolve_authority("discord", "789", None) == AuthorityLevel.OWNER

    def test_empty_owner_ids_all_owner(self) -> None:
        """Empty owner.user_ids means unconfigured — everyone is OWNER."""
        config = AuthorityConfig(
            owner=AuthorityTierConfig(user_ids=[]),
        )
        assert resolve_authority("telegram", "123456", config) == AuthorityLevel.OWNER

    def test_owner_resolution_composite(self) -> None:
        """Match composite 'channel:user_id' against owner list."""
        config = AuthorityConfig(
            owner=AuthorityTierConfig(user_ids=["telegram:123456"]),
        )
        assert resolve_authority("telegram", "123456", config) == AuthorityLevel.OWNER

    def test_owner_resolution_bare_id(self) -> None:
        """Match bare user_id (without channel prefix) against owner list."""
        config = AuthorityConfig(
            owner=AuthorityTierConfig(user_ids=["123456"]),
        )
        assert resolve_authority("telegram", "123456", config) == AuthorityLevel.OWNER

    def test_trusted_resolution(self) -> None:
        """User in trusted list should return TRUSTED."""
        config = AuthorityConfig(
            owner=AuthorityTierConfig(user_ids=["telegram:111"]),
            trusted=AuthorityTierConfig(user_ids=["telegram:222"]),
        )
        assert resolve_authority("telegram", "222", config) == AuthorityLevel.TRUSTED

    def test_public_fallback(self) -> None:
        """Unknown user should fall back to PUBLIC."""
        config = AuthorityConfig(
            owner=AuthorityTierConfig(user_ids=["telegram:111"]),
            trusted=AuthorityTierConfig(user_ids=["telegram:222"]),
        )
        assert resolve_authority("telegram", "999", config) == AuthorityLevel.PUBLIC

    def test_discord_owner(self) -> None:
        """Discord user in owner list."""
        config = AuthorityConfig(
            owner=AuthorityTierConfig(user_ids=["discord:abc123"]),
        )
        assert resolve_authority("discord", "abc123", config) == AuthorityLevel.OWNER

    def test_cross_channel_no_match(self) -> None:
        """Telegram owner should not match as Discord owner."""
        config = AuthorityConfig(
            owner=AuthorityTierConfig(user_ids=["telegram:111"]),
        )
        # The composite "discord:111" is not in the list, but bare "111" is not either
        assert resolve_authority("discord", "111", config) == AuthorityLevel.PUBLIC


# ---------------------------------------------------------------------------
# filter_tools_for_authority
# ---------------------------------------------------------------------------


class TestFilterToolsForAuthority:
    def setup_method(self) -> None:
        self.tools = [
            _mock_tool("file_read", PermissionLevel.SAFE),
            _mock_tool("file_write", PermissionLevel.MODERATE),
            _mock_tool("shell_execute", PermissionLevel.DESTRUCTIVE),
            _mock_tool("knowledge_search", PermissionLevel.SAFE),
            _mock_tool("goal_status", PermissionLevel.SAFE),
            _mock_tool("identity_status", PermissionLevel.SAFE),
        ]

    def test_owner_gets_all(self) -> None:
        """OWNER should get all tools."""
        result = filter_tools_for_authority(self.tools, AuthorityLevel.OWNER)
        assert len(result) == len(self.tools)

    def test_trusted_gets_read_only(self) -> None:
        """TRUSTED should only get tools in _TRUSTED_TOOLS."""
        result = filter_tools_for_authority(self.tools, AuthorityLevel.TRUSTED)
        names = {t.name for t in result}
        assert "file_read" in names
        assert "knowledge_search" in names
        assert "goal_status" in names
        assert "identity_status" in names
        assert "file_write" not in names
        assert "shell_execute" not in names

    def test_public_gets_none(self) -> None:
        """PUBLIC should get no tools (chat only)."""
        result = filter_tools_for_authority(self.tools, AuthorityLevel.PUBLIC)
        assert result == []


# ---------------------------------------------------------------------------
# check_tool_authority
# ---------------------------------------------------------------------------


class TestCheckToolAuthority:
    def test_owner_can_use_anything(self) -> None:
        assert check_tool_authority("shell_execute", AuthorityLevel.OWNER) is True
        assert check_tool_authority("file_write", AuthorityLevel.OWNER) is True
        assert check_tool_authority("nonexistent_tool", AuthorityLevel.OWNER) is True

    def test_trusted_allowed_tool(self) -> None:
        assert check_tool_authority("knowledge_search", AuthorityLevel.TRUSTED) is True
        assert check_tool_authority("file_read", AuthorityLevel.TRUSTED) is True

    def test_trusted_denied_tool(self) -> None:
        assert check_tool_authority("shell_execute", AuthorityLevel.TRUSTED) is False
        assert check_tool_authority("file_write", AuthorityLevel.TRUSTED) is False

    def test_public_denied_everything(self) -> None:
        assert check_tool_authority("file_read", AuthorityLevel.PUBLIC) is False
        assert check_tool_authority("knowledge_search", AuthorityLevel.PUBLIC) is False
