"""Tests for deferred tool loading — tiers, discovery, catalog."""

from __future__ import annotations

from tools.base import BaseTool, PermissionLevel, ToolResult, ToolTier


class _MockTool(BaseTool):
    """Minimal tool for testing."""

    def __init__(self, name: str, group: str = "system") -> None:
        self._name = name
        self._group = group

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Mock tool: {self._name}"

    @property
    def group(self) -> str:
        return self._group

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=True)


class TestToolTier:
    def test_default_tier(self) -> None:
        tool = _MockTool("test")
        assert tool.tier == ToolTier.PROFILE

    def test_override_tier(self) -> None:
        tool = _MockTool("test")
        tool._tier_override = ToolTier.CORE
        assert tool.tier == ToolTier.CORE

    def test_deferred_tier(self) -> None:
        tool = _MockTool("test")
        tool._tier_override = ToolTier.DEFERRED
        assert tool.tier == ToolTier.DEFERRED

    def test_enum_values(self) -> None:
        assert ToolTier.CORE == "core"
        assert ToolTier.PROFILE == "profile"
        assert ToolTier.DEFERRED == "deferred"


class TestRegistryTieredMethods:
    def _make_registry(self):
        from pathlib import Path

        from core.registry import ToolRegistry

        reg = ToolRegistry(Path("."))

        core = _MockTool("file_read", "system")
        core._tier_override = ToolTier.CORE
        reg.register(core)

        profile = _MockTool("knowledge_search", "knowledge")
        reg.register(profile)

        deferred = _MockTool("crypto_transfer", "payments")
        deferred._tier_override = ToolTier.DEFERRED
        reg.register(deferred)

        deferred2 = _MockTool("email_send", "comms")
        deferred2._tier_override = ToolTier.DEFERRED
        reg.register(deferred2)

        return reg

    def test_get_core_tools(self) -> None:
        reg = self._make_registry()
        core = reg.get_core_tools()
        names = [t.name for t in core]
        assert "file_read" in names
        assert "knowledge_search" not in names
        assert "crypto_transfer" not in names

    def test_get_deferred_catalog(self) -> None:
        reg = self._make_registry()
        catalog = reg.get_deferred_catalog()
        names = [c["name"] for c in catalog]
        assert "crypto_transfer" in names
        assert "email_send" in names
        assert "file_read" not in names

    def test_get_tools_for_context(self) -> None:
        reg = self._make_registry()
        tools = reg.get_tools_for_context(
            task_groups={"knowledge"}, activated_names=set()
        )
        names = [t.name for t in tools]
        assert "file_read" in names  # core — always included
        assert "knowledge_search" in names  # profile matching group
        assert "crypto_transfer" not in names  # deferred, not activated

    def test_activated_tools_included(self) -> None:
        reg = self._make_registry()
        tools = reg.get_tools_for_context(
            task_groups=set(), activated_names={"crypto_transfer"}
        )
        names = [t.name for t in tools]
        assert "crypto_transfer" in names

    def test_discover_tools(self) -> None:
        reg = self._make_registry()
        matches = reg.discover_tools("crypto payment transfer")
        names = [t.name for t in matches]
        assert "crypto_transfer" in names

    def test_discover_no_match(self) -> None:
        reg = self._make_registry()
        matches = reg.discover_tools("nonexistent feature xyz")
        assert len(matches) == 0
