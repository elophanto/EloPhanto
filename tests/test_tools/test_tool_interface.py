"""Tool interface compliance tests.

Verifies that every built-in tool correctly implements the BaseTool interface.
"""

from __future__ import annotations

from core.config import Config
from tools.base import BaseTool, PermissionLevel
from tools.browser.tools import create_browser_tools
from tools.data.llm import LLMCallTool
from tools.documents.analyze_tool import DocumentAnalyzeTool
from tools.documents.collections_tool import DocumentCollectionsTool
from tools.documents.query_tool import DocumentQueryTool
from tools.goals.create_tool import GoalCreateTool
from tools.goals.manage_tool import GoalManageTool
from tools.goals.status_tool import GoalStatusTool
from tools.knowledge.index_tool import KnowledgeIndexTool
from tools.knowledge.search import KnowledgeSearchTool
from tools.knowledge.writer import KnowledgeWriteTool
from tools.scheduling.list_tool import ScheduleListTool
from tools.scheduling.schedule_tool import ScheduleTaskTool
from tools.self_dev.capabilities import SelfListCapabilitiesTool
from tools.self_dev.creator import SelfCreatePluginTool
from tools.self_dev.reader import SelfReadSourceTool
from tools.self_dev.tester import SelfRunTestsTool
from tools.system.filesystem import FileListTool, FileReadTool, FileWriteTool
from tools.system.shell import ShellExecuteTool
from tools.system.vault_tool import VaultLookupTool


def _make_tools(test_config: Config) -> list[BaseTool]:
    return [
        # System tools (6)
        ShellExecuteTool(test_config),
        FileReadTool(),
        FileWriteTool(),
        FileListTool(),
        LLMCallTool(),
        VaultLookupTool(),
        # Knowledge tools (3)
        KnowledgeSearchTool(),
        KnowledgeWriteTool(),
        KnowledgeIndexTool(),
        # Self-dev tools (4)
        SelfReadSourceTool(test_config.project_root),
        SelfRunTestsTool(test_config.project_root),
        SelfListCapabilitiesTool(),
        SelfCreatePluginTool(test_config.project_root),
        # Browser tools (47)
        *create_browser_tools(),
        # Scheduling tools (2)
        ScheduleTaskTool(),
        ScheduleListTool(),
        # Document tools (3)
        DocumentAnalyzeTool(),
        DocumentQueryTool(),
        DocumentCollectionsTool(),
        # Goal tools (3)
        GoalCreateTool(),
        GoalStatusTool(),
        GoalManageTool(),
    ]


class TestToolInterface:
    def test_all_tools_have_name(self, test_config: Config) -> None:
        for tool in _make_tools(test_config):
            assert isinstance(tool.name, str)
            assert len(tool.name) > 0
            assert "_" in tool.name or tool.name.isalpha()

    def test_all_tools_have_description(self, test_config: Config) -> None:
        for tool in _make_tools(test_config):
            assert isinstance(tool.description, str)
            assert len(tool.description) > 10

    def test_all_tools_have_input_schema(self, test_config: Config) -> None:
        for tool in _make_tools(test_config):
            schema = tool.input_schema
            assert isinstance(schema, dict)
            assert schema.get("type") == "object"
            assert "properties" in schema

    def test_all_tools_have_permission_level(self, test_config: Config) -> None:
        for tool in _make_tools(test_config):
            assert isinstance(tool.permission_level, PermissionLevel)

    def test_all_tools_have_llm_schema(self, test_config: Config) -> None:
        for tool in _make_tools(test_config):
            schema = tool.to_llm_schema()
            assert schema["type"] == "function"
            assert "function" in schema
            assert "name" in schema["function"]
            assert "description" in schema["function"]
            assert "parameters" in schema["function"]

    def test_tool_names_are_unique(self, test_config: Config) -> None:
        tools = _make_tools(test_config)
        names = [t.name for t in tools]
        assert len(names) == len(set(names))

    def test_expected_tool_count(self, test_config: Config) -> None:
        tools = _make_tools(test_config)
        assert len(tools) == 68  # 6 + 3 + 4 + 47 + 2 + 3 + 3

    def test_expected_permission_levels(self, test_config: Config) -> None:
        tool_map = {t.name: t for t in _make_tools(test_config)}
        # System
        assert tool_map["shell_execute"].permission_level == PermissionLevel.DESTRUCTIVE
        assert tool_map["file_read"].permission_level == PermissionLevel.SAFE
        assert tool_map["file_write"].permission_level == PermissionLevel.MODERATE
        assert tool_map["file_list"].permission_level == PermissionLevel.SAFE
        assert tool_map["llm_call"].permission_level == PermissionLevel.SAFE
        # Knowledge
        assert tool_map["knowledge_search"].permission_level == PermissionLevel.SAFE
        assert tool_map["knowledge_write"].permission_level == PermissionLevel.MODERATE
        assert tool_map["knowledge_index"].permission_level == PermissionLevel.SAFE
        # Self-dev
        assert tool_map["self_read_source"].permission_level == PermissionLevel.SAFE
        assert tool_map["self_run_tests"].permission_level == PermissionLevel.MODERATE
        assert (
            tool_map["self_list_capabilities"].permission_level == PermissionLevel.SAFE
        )
        assert (
            tool_map["self_create_plugin"].permission_level == PermissionLevel.CRITICAL
        )
        # Browser (key tools)
        assert tool_map["browser_navigate"].permission_level == PermissionLevel.MODERATE
        assert tool_map["browser_extract"].permission_level == PermissionLevel.SAFE
        assert tool_map["browser_click"].permission_level == PermissionLevel.MODERATE
        assert (
            tool_map["browser_click_text"].permission_level == PermissionLevel.MODERATE
        )
        assert tool_map["browser_type"].permission_level == PermissionLevel.MODERATE
        assert tool_map["browser_screenshot"].permission_level == PermissionLevel.SAFE
        assert tool_map["browser_get_elements"].permission_level == PermissionLevel.SAFE
        assert tool_map["browser_eval"].permission_level == PermissionLevel.CRITICAL
        assert tool_map["browser_inject"].permission_level == PermissionLevel.CRITICAL
        assert tool_map["browser_close"].permission_level == PermissionLevel.CRITICAL
        assert tool_map["browser_list_tabs"].permission_level == PermissionLevel.SAFE
        assert (
            tool_map["browser_read_semantic"].permission_level == PermissionLevel.SAFE
        )
        assert tool_map["browser_full_audit"].permission_level == PermissionLevel.SAFE
        # Scheduling
        assert tool_map["schedule_task"].permission_level == PermissionLevel.MODERATE
        assert tool_map["schedule_list"].permission_level == PermissionLevel.SAFE
        # Documents
        assert tool_map["document_analyze"].permission_level == PermissionLevel.SAFE
        assert tool_map["document_query"].permission_level == PermissionLevel.SAFE
        assert tool_map["document_collections"].permission_level == PermissionLevel.SAFE
        # Goals
        assert tool_map["goal_create"].permission_level == PermissionLevel.MODERATE
        assert tool_map["goal_status"].permission_level == PermissionLevel.SAFE
        assert tool_map["goal_manage"].permission_level == PermissionLevel.MODERATE
