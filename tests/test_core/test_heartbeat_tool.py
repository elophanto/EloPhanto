"""Heartbeat tool tests.

Tests the heartbeat management tool (add/remove/list/clear/set orders).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tools.scheduling.heartbeat_tool import HeartbeatTool


@pytest.fixture
def tool(tmp_path: Path) -> HeartbeatTool:
    t = HeartbeatTool()
    t._project_root = tmp_path
    return t


@pytest.fixture
def heartbeat_file(tmp_path: Path) -> Path:
    return tmp_path / "HEARTBEAT.md"


class TestHeartbeatToolActions:
    @pytest.mark.asyncio
    async def test_status_no_engine(self, tool: HeartbeatTool) -> None:
        result = await tool.execute({"action": "status"})
        assert result.success
        assert result.data["file_exists"] is False
        assert result.data["orders_count"] == 0

    @pytest.mark.asyncio
    async def test_list_empty(self, tool: HeartbeatTool) -> None:
        result = await tool.execute({"action": "list"})
        assert result.success
        assert result.data["orders"] == []

    @pytest.mark.asyncio
    async def test_add_order(self, tool: HeartbeatTool, heartbeat_file: Path) -> None:
        result = await tool.execute({"action": "add", "order": "Check email inbox"})
        assert result.success
        assert result.data["total"] == 1
        assert "Check email inbox" in result.data["added"]
        assert heartbeat_file.exists()
        content = heartbeat_file.read_text()
        assert "- Check email inbox" in content

    @pytest.mark.asyncio
    async def test_add_multiple_orders(
        self, tool: HeartbeatTool, heartbeat_file: Path
    ) -> None:
        await tool.execute({"action": "add", "order": "Check email"})
        await tool.execute({"action": "add", "order": "Post metrics"})
        result = await tool.execute({"action": "list"})
        assert result.success
        assert result.data["total"] == 2
        assert result.data["orders"][0]["text"] == "Check email"
        assert result.data["orders"][1]["text"] == "Post metrics"

    @pytest.mark.asyncio
    async def test_add_empty_order_fails(self, tool: HeartbeatTool) -> None:
        result = await tool.execute({"action": "add", "order": ""})
        assert not result.success
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_remove_order(
        self, tool: HeartbeatTool, heartbeat_file: Path
    ) -> None:
        await tool.execute({"action": "add", "order": "First"})
        await tool.execute({"action": "add", "order": "Second"})
        result = await tool.execute({"action": "remove", "number": 1})
        assert result.success
        assert result.data["removed"] == "First"
        assert result.data["remaining"] == 1

    @pytest.mark.asyncio
    async def test_remove_invalid_number(self, tool: HeartbeatTool) -> None:
        await tool.execute({"action": "add", "order": "Only one"})
        result = await tool.execute({"action": "remove", "number": 5})
        assert not result.success
        assert "Invalid" in result.error

    @pytest.mark.asyncio
    async def test_remove_from_empty(self, tool: HeartbeatTool) -> None:
        result = await tool.execute({"action": "remove", "number": 1})
        assert not result.success

    @pytest.mark.asyncio
    async def test_clear_orders(
        self, tool: HeartbeatTool, heartbeat_file: Path
    ) -> None:
        await tool.execute({"action": "add", "order": "Something"})
        result = await tool.execute({"action": "clear"})
        assert result.success
        assert heartbeat_file.exists()
        # File should have template but no orders
        orders = tool._parse_orders(heartbeat_file)
        assert len(orders) == 0

    @pytest.mark.asyncio
    async def test_set_orders(self, tool: HeartbeatTool, heartbeat_file: Path) -> None:
        result = await tool.execute(
            {"action": "set", "orders": ["Task A", "Task B", "Task C"]}
        )
        assert result.success
        assert result.data["total"] == 3
        content = heartbeat_file.read_text()
        assert "- Task A" in content
        assert "- Task B" in content
        assert "- Task C" in content

    @pytest.mark.asyncio
    async def test_set_orders_filters_empty(self, tool: HeartbeatTool) -> None:
        result = await tool.execute(
            {"action": "set", "orders": ["Task A", "", "  ", "Task B"]}
        )
        assert result.success
        assert result.data["total"] == 2


class TestHeartbeatToolTrigger:
    @pytest.mark.asyncio
    async def test_trigger_no_engine(self, tool: HeartbeatTool) -> None:
        result = await tool.execute({"action": "trigger"})
        assert not result.success
        assert "not available" in result.error.lower()

    @pytest.mark.asyncio
    async def test_trigger_engine_not_running(self, tool: HeartbeatTool) -> None:
        engine = MagicMock()
        engine.is_running = False
        tool._heartbeat_engine = engine
        result = await tool.execute({"action": "trigger"})
        assert not result.success
        assert "not running" in result.error.lower()


class TestHeartbeatToolFileFormat:
    @pytest.mark.asyncio
    async def test_template_comments_preserved(
        self, tool: HeartbeatTool, heartbeat_file: Path
    ) -> None:
        await tool.execute({"action": "add", "order": "My task"})
        content = heartbeat_file.read_text()
        assert "# Standing Orders" in content
        assert "heartbeat cycle" in content

    @pytest.mark.asyncio
    async def test_parses_existing_manual_file(
        self, tool: HeartbeatTool, heartbeat_file: Path
    ) -> None:
        """Can parse a HEARTBEAT.md that was manually written."""
        heartbeat_file.write_text(
            "# My Orders\n\n- Check email\n- Post report\n\nSome note.\n",
            encoding="utf-8",
        )
        result = await tool.execute({"action": "list"})
        assert result.success
        assert result.data["total"] == 2
        assert result.data["orders"][0]["text"] == "Check email"

    @pytest.mark.asyncio
    async def test_parses_asterisk_lists(
        self, tool: HeartbeatTool, heartbeat_file: Path
    ) -> None:
        heartbeat_file.write_text("* Task one\n* Task two\n", encoding="utf-8")
        result = await tool.execute({"action": "list"})
        assert result.success
        assert result.data["total"] == 2

    @pytest.mark.asyncio
    async def test_status_with_engine(
        self, tool: HeartbeatTool, heartbeat_file: Path
    ) -> None:
        engine = MagicMock()
        engine.get_status.return_value = {
            "running": True,
            "paused": False,
            "cycle_count": 5,
        }
        engine._file_path = heartbeat_file
        tool._heartbeat_engine = engine
        result = await tool.execute({"action": "status"})
        assert result.success
        assert result.data["engine"]["running"] is True
