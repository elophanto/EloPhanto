"""Tests for {{plugin_name}}."""

from __future__ import annotations

import pytest

from plugins.{{plugin_dir}}.plugin import {{ClassName}}


class Test{{ClassName}}:
    def test_interface(self) -> None:
        """Tool implements the required BaseTool interface."""
        tool = {{ClassName}}()
        assert tool.name == "{{tool_name}}"
        assert len(tool.description) > 0
        assert tool.input_schema["type"] == "object"
        assert tool.permission_level is not None

    @pytest.mark.asyncio
    async def test_basic_execution(self) -> None:
        """Tool executes without error."""
        tool = {{ClassName}}()
        result = await tool.execute({})
        assert result.success
