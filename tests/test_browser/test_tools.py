"""Tests for browser tool interface compliance and execution."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tools.base import PermissionLevel
from tools.browser.tools import BridgeBrowserTool, create_browser_tools


class TestBrowserToolInterface:
    def test_all_have_name(self) -> None:
        for tool in create_browser_tools():
            assert isinstance(tool.name, str)
            assert tool.name.startswith("browser_")

    def test_all_have_description(self) -> None:
        for tool in create_browser_tools():
            assert len(tool.description) > 10

    def test_all_have_schema(self) -> None:
        for tool in create_browser_tools():
            schema = tool.input_schema
            assert schema["type"] == "object"
            assert "properties" in schema

    def test_all_have_permission_level(self) -> None:
        for tool in create_browser_tools():
            assert isinstance(tool.permission_level, PermissionLevel)

    def test_llm_schema(self) -> None:
        for tool in create_browser_tools():
            schema = tool.to_llm_schema()
            assert schema["type"] == "function"
            assert "function" in schema

    def test_tool_count(self) -> None:
        tools = create_browser_tools()
        assert len(tools) == 47

    def test_names_are_unique(self) -> None:
        tools = create_browser_tools()
        names = [t.name for t in tools]
        assert len(names) == len(set(names))

    def test_expected_permissions(self) -> None:
        tool_map = {t.name: t for t in create_browser_tools()}
        # SAFE tools
        for name in [
            "browser_extract",
            "browser_read_semantic",
            "browser_screenshot",
            "browser_get_elements",
            "browser_get_html",
            "browser_list_tabs",
            "browser_get_console",
            "browser_get_network",
            "browser_scroll",
            "browser_wait",
            "browser_full_audit",
        ]:
            assert (
                tool_map[name].permission_level == PermissionLevel.SAFE
            ), f"{name} should be SAFE"
        # MODERATE tools
        for name in [
            "browser_navigate",
            "browser_click",
            "browser_click_text",
            "browser_type",
            "browser_new_tab",
            "browser_drag_drop",
            "browser_hover_element",
        ]:
            assert (
                tool_map[name].permission_level == PermissionLevel.MODERATE
            ), f"{name} should be MODERATE"
        # CRITICAL tools
        for name in ["browser_eval", "browser_inject", "browser_close"]:
            assert (
                tool_map[name].permission_level == PermissionLevel.CRITICAL
            ), f"{name} should be CRITICAL"

    def test_key_tools_exist(self) -> None:
        tool_map = {t.name: t for t in create_browser_tools()}
        key_tools = [
            "browser_navigate",
            "browser_click",
            "browser_click_text",
            "browser_click_batch",
            "browser_type",
            "browser_extract",
            "browser_read_semantic",
            "browser_screenshot",
            "browser_get_elements",
            "browser_full_audit",
            "browser_dom_search",
            "browser_drag_drop",
            "browser_drag_solve",
            "browser_hover_element",
            "browser_pointer_path",
            "browser_eval",
            "browser_inject",
            "browser_wait_for_selector",
            "browser_close",
        ]
        for name in key_tools:
            assert name in tool_map, f"Missing key tool: {name}"


class TestBridgeBrowserToolExecution:
    @pytest.mark.asyncio
    async def test_no_manager(self) -> None:
        tool = BridgeBrowserTool(
            "browser_navigate",
            "Navigate to URL",
            {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            PermissionLevel.MODERATE,
        )
        result = await tool.execute({"url": "https://example.com"})
        assert result.success is False
        assert "not available" in (result.error or "")

    @pytest.mark.asyncio
    async def test_call_tool_success(self) -> None:
        tool = BridgeBrowserTool(
            "browser_navigate",
            "Navigate to URL",
            {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            PermissionLevel.MODERATE,
        )
        mock = AsyncMock()
        mock.call_tool.return_value = {
            "url": "https://example.com",
            "title": "Example",
            "elements": [],
        }
        tool._browser_manager = mock
        result = await tool.execute({"url": "https://example.com"})
        assert result.success is True
        assert result.data["url"] == "https://example.com"
        mock.call_tool.assert_called_once_with(
            "browser_navigate", {"url": "https://example.com"}
        )

    @pytest.mark.asyncio
    async def test_call_tool_error(self) -> None:
        tool = BridgeBrowserTool(
            "browser_click",
            "Click element",
            {
                "type": "object",
                "properties": {"index": {"type": "number"}},
                "required": ["index"],
            },
            PermissionLevel.MODERATE,
        )
        mock = AsyncMock()
        mock.call_tool.side_effect = Exception("Element not found")
        tool._browser_manager = mock
        result = await tool.execute({"index": 99})
        assert result.success is False
        assert "Element not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_call_tool_forwards_all_params(self) -> None:
        tool = BridgeBrowserTool(
            "browser_click_text",
            "Click by text",
            {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            PermissionLevel.MODERATE,
        )
        mock = AsyncMock()
        mock.call_tool.return_value = {"success": True, "clicked": "Submit"}
        tool._browser_manager = mock
        result = await tool.execute({"text": "Submit", "exact": True, "nth": 0})
        assert result.success is True
        mock.call_tool.assert_called_once_with(
            "browser_click_text",
            {"text": "Submit", "exact": True, "nth": 0},
        )
