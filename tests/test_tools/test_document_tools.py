"""Tests for document analysis tools — interface compliance and error handling."""

from __future__ import annotations

from typing import Any

import pytest

from tools.base import BaseTool, PermissionLevel, ToolResult
from tools.documents.analyze_tool import DocumentAnalyzeTool
from tools.documents.collections_tool import DocumentCollectionsTool
from tools.documents.query_tool import DocumentQueryTool


# ─── Tool Interface Compliance ───


class TestDocumentToolInterface:
    @pytest.fixture
    def tools(self) -> list[BaseTool]:
        return [DocumentAnalyzeTool(), DocumentQueryTool(), DocumentCollectionsTool()]

    def test_all_have_name(self, tools: list[BaseTool]) -> None:
        expected = {"document_analyze", "document_query", "document_collections"}
        names = {t.name for t in tools}
        assert names == expected

    def test_all_have_description(self, tools: list[BaseTool]) -> None:
        for tool in tools:
            assert isinstance(tool.description, str)
            assert len(tool.description) > 10

    def test_all_have_input_schema(self, tools: list[BaseTool]) -> None:
        for tool in tools:
            schema = tool.input_schema
            assert isinstance(schema, dict)
            assert schema.get("type") == "object"
            assert "properties" in schema

    def test_all_have_permission_level(self, tools: list[BaseTool]) -> None:
        for tool in tools:
            assert isinstance(tool.permission_level, PermissionLevel)

    def test_all_produce_valid_llm_schema(self, tools: list[BaseTool]) -> None:
        for tool in tools:
            schema = tool.to_llm_schema()
            assert schema["type"] == "function"
            assert "function" in schema
            assert schema["function"]["name"] == tool.name

    def test_permission_levels(self) -> None:
        assert DocumentAnalyzeTool().permission_level == PermissionLevel.SAFE
        assert DocumentQueryTool().permission_level == PermissionLevel.SAFE
        assert DocumentCollectionsTool().permission_level == PermissionLevel.SAFE


# ─── Analyze Tool Errors ───


class TestDocumentAnalyzeErrors:
    @pytest.fixture
    def tool(self) -> DocumentAnalyzeTool:
        return DocumentAnalyzeTool()

    async def test_no_deps_injected(self, tool: DocumentAnalyzeTool) -> None:
        result = await tool.execute({"files": ["/tmp/fake.pdf"]})
        assert result.success is False
        assert result.error is not None

    async def test_missing_files_param(self, tool: DocumentAnalyzeTool) -> None:
        result = await tool.execute({})
        assert result.success is False

    async def test_empty_files_list(self, tool: DocumentAnalyzeTool) -> None:
        result = await tool.execute({"files": []})
        assert result.success is False


# ─── Query Tool Errors ───


class TestDocumentQueryErrors:
    @pytest.fixture
    def tool(self) -> DocumentQueryTool:
        return DocumentQueryTool()

    async def test_no_deps_injected(self, tool: DocumentQueryTool) -> None:
        result = await tool.execute(
            {"collection": "test", "question": "what?"}
        )
        assert result.success is False
        assert result.error is not None

    async def test_missing_collection(self, tool: DocumentQueryTool) -> None:
        result = await tool.execute({"question": "what?"})
        assert result.success is False

    async def test_missing_question(self, tool: DocumentQueryTool) -> None:
        result = await tool.execute({"collection": "test"})
        assert result.success is False


# ─── Collections Tool Errors ───


class TestDocumentCollectionsErrors:
    @pytest.fixture
    def tool(self) -> DocumentCollectionsTool:
        return DocumentCollectionsTool()

    async def test_no_deps_injected(self, tool: DocumentCollectionsTool) -> None:
        result = await tool.execute({"action": "list"})
        assert result.success is False
        assert result.error is not None

    async def test_missing_action(self, tool: DocumentCollectionsTool) -> None:
        result = await tool.execute({})
        assert result.success is False

    async def test_info_without_collection(self, tool: DocumentCollectionsTool) -> None:
        result = await tool.execute({"action": "info"})
        assert result.success is False

    async def test_delete_without_collection(
        self, tool: DocumentCollectionsTool
    ) -> None:
        result = await tool.execute({"action": "delete"})
        assert result.success is False
