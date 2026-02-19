"""Identity tool tests — interface compliance and execution paths."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest

from tools.base import PermissionLevel
from tools.identity.reflect_tool import IdentityReflectTool
from tools.identity.status_tool import IdentityStatusTool
from tools.identity.update_tool import IdentityUpdateTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeIdentity:
    id: str = "self"
    creator: str = "EloPhanto"
    display_name: str = "Phantom"
    purpose: str = "Help users"
    values: list[str] = field(default_factory=lambda: ["accuracy", "persistence"])
    beliefs: dict[str, Any] = field(default_factory=dict)
    curiosities: list[str] = field(default_factory=lambda: ["AI safety"])
    boundaries: list[str] = field(default_factory=lambda: ["Never delete without asking"])
    capabilities: list[str] = field(default_factory=lambda: ["browser automation"])
    personality: dict[str, Any] = field(default_factory=lambda: {"analytical": True})
    communication_style: str = "concise"
    initial_thoughts: str = "I am curious."
    version: int = 3
    created_at: str = "2026-02-19T00:00:00"
    updated_at: str = "2026-02-19T12:00:00"


def _mock_identity_manager() -> AsyncMock:
    mgr = AsyncMock()
    mgr.get_identity.return_value = FakeIdentity()
    mgr.update_field.return_value = True
    mgr.reflect_on_task.return_value = [
        {"field": "capabilities", "value": "file management", "reason": "learned"}
    ]
    mgr.deep_reflect.return_value = [
        {"field": "personality", "value": {"methodical": True}, "reason": "pattern"}
    ]
    mgr.get_evolution_history.return_value = [
        {
            "trigger": "explicit",
            "field": "display_name",
            "old_value": "EloPhanto",
            "new_value": "Phantom",
            "reason": "User chose name",
            "confidence": 0.5,
            "created_at": "2026-02-19",
        }
    ]
    return mgr


# ---------------------------------------------------------------------------
# Interface compliance
# ---------------------------------------------------------------------------


class TestIdentityToolInterface:
    def test_status_tool_interface(self) -> None:
        t = IdentityStatusTool()
        assert t.name == "identity_status"
        assert isinstance(t.description, str) and len(t.description) > 10
        assert t.input_schema["type"] == "object"
        assert t.permission_level == PermissionLevel.SAFE

    def test_update_tool_interface(self) -> None:
        t = IdentityUpdateTool()
        assert t.name == "identity_update"
        assert t.input_schema["type"] == "object"
        assert "field" in t.input_schema["properties"]
        assert "value" in t.input_schema["properties"]
        assert "reason" in t.input_schema["properties"]
        assert t.permission_level == PermissionLevel.MODERATE

    def test_reflect_tool_interface(self) -> None:
        t = IdentityReflectTool()
        assert t.name == "identity_reflect"
        assert t.input_schema["type"] == "object"
        assert "depth" in t.input_schema["properties"]
        assert t.permission_level == PermissionLevel.MODERATE

    def test_llm_schema_format(self) -> None:
        for tool_cls in (IdentityStatusTool, IdentityUpdateTool, IdentityReflectTool):
            tool = tool_cls()
            schema = tool.to_llm_schema()
            assert schema["type"] == "function"
            assert "function" in schema
            assert "name" in schema["function"]
            assert "parameters" in schema["function"]


# ---------------------------------------------------------------------------
# IdentityStatusTool execution
# ---------------------------------------------------------------------------


class TestIdentityStatusTool:
    @pytest.mark.asyncio
    async def test_not_initialized(self) -> None:
        t = IdentityStatusTool()
        result = await t.execute({})
        assert not result.success
        assert "not initialized" in result.error.lower()

    @pytest.mark.asyncio
    async def test_full_identity(self) -> None:
        t = IdentityStatusTool()
        t._identity_manager = _mock_identity_manager()
        result = await t.execute({})
        assert result.success
        assert result.data["creator"] == "EloPhanto"
        assert result.data["display_name"] == "Phantom"
        assert result.data["version"] == 3

    @pytest.mark.asyncio
    async def test_specific_field(self) -> None:
        t = IdentityStatusTool()
        t._identity_manager = _mock_identity_manager()
        result = await t.execute({"field": "capabilities"})
        assert result.success
        assert result.data["field"] == "capabilities"
        assert "browser automation" in result.data["value"]

    @pytest.mark.asyncio
    async def test_unknown_field(self) -> None:
        t = IdentityStatusTool()
        mgr = _mock_identity_manager()
        # FakeIdentity doesn't have "nonexistent", getattr returns None
        t._identity_manager = mgr
        result = await t.execute({"field": "nonexistent"})
        assert not result.success

    @pytest.mark.asyncio
    async def test_include_history(self) -> None:
        t = IdentityStatusTool()
        t._identity_manager = _mock_identity_manager()
        result = await t.execute({"include_history": True})
        assert result.success
        assert "evolution_history" in result.data
        assert len(result.data["evolution_history"]) == 1


# ---------------------------------------------------------------------------
# IdentityUpdateTool execution
# ---------------------------------------------------------------------------


class TestIdentityUpdateTool:
    @pytest.mark.asyncio
    async def test_not_initialized(self) -> None:
        t = IdentityUpdateTool()
        result = await t.execute({"field": "display_name", "value": "X", "reason": "Y"})
        assert not result.success
        assert "not initialized" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_field(self) -> None:
        t = IdentityUpdateTool()
        t._identity_manager = _mock_identity_manager()
        result = await t.execute({"value": "X", "reason": "Y"})
        assert not result.success
        assert "field" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_value(self) -> None:
        t = IdentityUpdateTool()
        t._identity_manager = _mock_identity_manager()
        result = await t.execute({"field": "display_name", "reason": "Y"})
        assert not result.success
        assert "value" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_reason(self) -> None:
        t = IdentityUpdateTool()
        t._identity_manager = _mock_identity_manager()
        result = await t.execute({"field": "display_name", "value": "X"})
        assert not result.success
        assert "reason" in result.error.lower()

    @pytest.mark.asyncio
    async def test_update_success(self) -> None:
        t = IdentityUpdateTool()
        t._identity_manager = _mock_identity_manager()
        result = await t.execute(
            {"field": "display_name", "value": "NewName", "reason": "User chose"}
        )
        assert result.success
        assert result.data["field"] == "display_name"
        assert result.data["version"] == 3  # from FakeIdentity

    @pytest.mark.asyncio
    async def test_update_failure(self) -> None:
        t = IdentityUpdateTool()
        mgr = _mock_identity_manager()
        mgr.update_field.return_value = False
        t._identity_manager = mgr
        result = await t.execute({"field": "creator", "value": "Other", "reason": "Trying"})
        assert not result.success
        assert "immutable" in result.error.lower() or "failed" in result.error.lower()


# ---------------------------------------------------------------------------
# IdentityReflectTool execution
# ---------------------------------------------------------------------------


class TestIdentityReflectTool:
    @pytest.mark.asyncio
    async def test_not_initialized(self) -> None:
        t = IdentityReflectTool()
        result = await t.execute({})
        assert not result.success
        assert "not initialized" in result.error.lower()

    @pytest.mark.asyncio
    async def test_light_reflection(self) -> None:
        t = IdentityReflectTool()
        t._identity_manager = _mock_identity_manager()
        result = await t.execute({})
        assert result.success
        assert result.data["depth"] == "light"
        assert result.data["updates_applied"] == 1
        assert result.data["current_version"] == 3

    @pytest.mark.asyncio
    async def test_deep_reflection(self) -> None:
        t = IdentityReflectTool()
        t._identity_manager = _mock_identity_manager()
        result = await t.execute({"depth": "deep"})
        assert result.success
        assert result.data["depth"] == "deep"
        assert result.data["updates_applied"] == 1
