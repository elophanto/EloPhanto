"""Tests for self-development tools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.registry import ToolRegistry
from tools.base import BaseTool, PermissionLevel, ToolResult
from tools.self_dev.capabilities import SelfListCapabilitiesTool
from tools.self_dev.pipeline import (
    check_name_available,
    get_timestamp,
    render_template,
    sanitize_plugin_name,
)
from tools.self_dev.reader import SelfReadSourceTool
from tools.self_dev.tester import SelfRunTestsTool

# ─── SelfReadSourceTool ───


class TestSelfReadSource:
    @pytest.fixture
    def reader(self, tmp_path: Path) -> SelfReadSourceTool:
        # Create a mini project structure
        (tmp_path / "core").mkdir()
        (tmp_path / "core" / "agent.py").write_text("# agent code")
        (tmp_path / "tools").mkdir()
        (tmp_path / "tools" / "base.py").write_text("# base tool")
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "readme.md").write_text("# docs")
        (tmp_path / "secret").mkdir()
        (tmp_path / "secret" / "keys.txt").write_text("top secret")
        (tmp_path / "config.yaml").write_text("agent:\n  name: Test")
        return SelfReadSourceTool(tmp_path)

    @pytest.mark.asyncio
    async def test_read_allowed_file(self, reader: SelfReadSourceTool) -> None:
        result = await reader.execute({"path": "core/agent.py"})
        assert result.success is True
        assert "agent code" in result.data["content"]
        assert result.data["language"] == "py"

    @pytest.mark.asyncio
    async def test_read_blocked_directory(self, reader: SelfReadSourceTool) -> None:
        result = await reader.execute({"path": "secret/keys.txt"})
        assert result.success is False
        assert "restricted" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, reader: SelfReadSourceTool) -> None:
        result = await reader.execute({"path": "../../../etc/passwd"})
        assert result.success is False
        assert "traversal" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_list_directory(self, reader: SelfReadSourceTool) -> None:
        result = await reader.execute({"path": "core", "list_dir": True})
        assert result.success is True
        assert result.data["count"] >= 1
        names = [e["name"] for e in result.data["entries"]]
        assert "agent.py" in names

    @pytest.mark.asyncio
    async def test_file_not_found(self, reader: SelfReadSourceTool) -> None:
        result = await reader.execute({"path": "core/nonexistent.py"})
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_root_level_file(self, reader: SelfReadSourceTool) -> None:
        result = await reader.execute({"path": "config.yaml"})
        assert result.success is True

    def test_interface(self, reader: SelfReadSourceTool) -> None:
        assert reader.name == "self_read_source"
        assert reader.permission_level == PermissionLevel.SAFE
        assert "source code" in reader.description.lower()
        schema = reader.input_schema
        assert schema["type"] == "object"
        assert "path" in schema["properties"]


# ─── SelfRunTestsTool ───


class TestSelfRunTests:
    @pytest.fixture
    def tester(self, tmp_path: Path) -> SelfRunTestsTool:
        return SelfRunTestsTool(tmp_path)

    def test_interface(self, tester: SelfRunTestsTool) -> None:
        assert tester.name == "self_run_tests"
        assert tester.permission_level == PermissionLevel.MODERATE
        schema = tester.input_schema
        assert "target" in schema["properties"]

    @pytest.mark.asyncio
    async def test_run_nonexistent_target(self, tester: SelfRunTestsTool) -> None:
        result = await tester.execute({"target": "tests/nonexistent_test.py"})
        # Should complete (pytest returns non-zero) but not crash
        assert isinstance(result, ToolResult)


# ─── SelfListCapabilitiesTool ───


class TestSelfListCapabilities:
    @pytest.fixture
    def caps_tool(self, tmp_path: Path) -> SelfListCapabilitiesTool:
        tool = SelfListCapabilitiesTool()
        registry = ToolRegistry(tmp_path)
        # Register a few mock tools
        mock_tool = MagicMock(spec=BaseTool)
        mock_tool.name = "mock_tool"
        mock_tool.description = "A mock tool for testing"
        mock_tool.permission_level = PermissionLevel.SAFE
        mock_tool.input_schema = {"type": "object", "properties": {}}
        registry.register(mock_tool)
        tool._registry = registry
        return tool

    def test_interface(self, caps_tool: SelfListCapabilitiesTool) -> None:
        assert caps_tool.name == "self_list_capabilities"
        assert caps_tool.permission_level == PermissionLevel.SAFE

    @pytest.mark.asyncio
    async def test_list_capabilities(self, caps_tool: SelfListCapabilitiesTool) -> None:
        result = await caps_tool.execute({})
        assert result.success is True
        assert result.data["total"] >= 1
        names = [c["name"] for c in result.data["capabilities"]]
        assert "mock_tool" in names

    @pytest.mark.asyncio
    async def test_include_schemas(self, caps_tool: SelfListCapabilitiesTool) -> None:
        result = await caps_tool.execute({"include_schemas": True})
        assert result.success is True
        assert "input_schema" in result.data["capabilities"][0]

    @pytest.mark.asyncio
    async def test_no_registry(self) -> None:
        tool = SelfListCapabilitiesTool()
        result = await tool.execute({})
        assert result.success is False


# ─── Pipeline utilities ───


class TestPipelineUtils:
    def test_sanitize_plugin_name(self) -> None:
        assert sanitize_plugin_name("My Cool Tool!") == "my_cool_tool"
        assert sanitize_plugin_name("hello") == "hello"
        assert sanitize_plugin_name("") == "unnamed_plugin"
        assert sanitize_plugin_name("A-B C") == "ab_c"

    def test_check_name_available(self, tmp_path: Path) -> None:
        registry = ToolRegistry(tmp_path)
        assert check_name_available("new_tool", registry) is True

        mock_tool = MagicMock(spec=BaseTool)
        mock_tool.name = "existing_tool"
        registry.register(mock_tool)
        assert check_name_available("existing_tool", registry) is False

    def test_get_timestamp(self) -> None:
        ts = get_timestamp()
        assert len(ts) == 10  # YYYY-MM-DD
        assert "-" in ts

    @pytest.mark.asyncio
    async def test_render_template(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "plugin.py").write_text("class {{ClassName}}:\n    pass")
        (template_dir / "schema.json").write_text('{"name": "{{tool_name}}"}')

        output_dir = tmp_path / "output"
        context = {"ClassName": "MyTool", "tool_name": "my_tool"}
        created = await render_template(template_dir, output_dir, context)

        assert len(created) == 2
        assert (output_dir / "plugin.py").read_text() == "class MyTool:\n    pass"
        assert '"my_tool"' in (output_dir / "schema.json").read_text()
