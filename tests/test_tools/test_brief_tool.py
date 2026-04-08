"""Tests for BriefTool — proactive communication."""

from __future__ import annotations

import pytest

from tools.communication.brief_tool import AgentBriefTool, _brief_timestamps


class TestBriefTool:
    def setup_method(self) -> None:
        self.tool = AgentBriefTool()
        _brief_timestamps.clear()

    def test_properties(self) -> None:
        assert self.tool.name == "agent_brief"
        assert self.tool.group == "communication"
        assert self.tool.permission_level.value == "safe"

    @pytest.mark.asyncio
    async def test_basic_brief(self) -> None:
        result = await self.tool.execute(
            {"summary": "Test insight", "priority": "info"}
        )
        assert result.success
        assert "Test insight" in result.data["brief"]
        assert result.data["priority"] == "info"

    @pytest.mark.asyncio
    async def test_with_details(self) -> None:
        result = await self.tool.execute(
            {
                "summary": "Cost anomaly detected",
                "details": "Spending $5.20 today vs $0.80 average",
                "priority": "warning",
            }
        )
        assert result.success
        assert "Cost anomaly" in result.data["brief"]
        assert "$5.20" in result.data["brief"]

    @pytest.mark.asyncio
    async def test_rate_limiting(self) -> None:
        # Send 3 briefs — should work
        for i in range(3):
            result = await self.tool.execute(
                {"summary": f"Brief {i}", "priority": "info"}
            )
            assert result.success

        # 4th should be rate limited
        result = await self.tool.execute(
            {"summary": "One too many", "priority": "info"}
        )
        assert not result.success
        assert "Rate limited" in (result.error or "")

    @pytest.mark.asyncio
    async def test_actionable_bypasses_rate_limit(self) -> None:
        # Fill up rate limit
        for i in range(3):
            await self.tool.execute({"summary": f"Brief {i}", "priority": "info"})

        # Actionable should still work
        result = await self.tool.execute(
            {"summary": "Critical alert", "priority": "actionable"}
        )
        assert result.success
