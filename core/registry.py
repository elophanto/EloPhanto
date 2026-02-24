"""Tool registry: discovers, loads, and manages available tools.

Provides tool lookup by name and generates LLM-compatible schemas.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.base import BaseTool


class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self, project_root: Path) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._project_root = project_root

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        """Remove a tool by name. Returns True if found and removed."""
        return self._tools.pop(name, None) is not None

    def get(self, name: str) -> BaseTool | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        """Return tool schemas in OpenAI function-calling format for LLM."""
        return [tool.to_llm_schema() for tool in self._tools.values()]

    def list_tool_summaries(self) -> list[dict[str, str]]:
        """Return human-readable tool summaries."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "permission": t.permission_level.value,
            }
            for t in self._tools.values()
        ]

    def all_tools(self) -> list[BaseTool]:
        """Return all registered tool instances."""
        return list(self._tools.values())

    def load_builtin_tools(self, config: Any) -> None:
        """Instantiate and register all built-in tools."""
        from tools.browser.tools import create_browser_tools
        from tools.data.llm import LLMCallTool
        from tools.knowledge.index_tool import KnowledgeIndexTool
        from tools.knowledge.search import KnowledgeSearchTool
        from tools.knowledge.skill_tool import SkillListTool, SkillReadTool
        from tools.knowledge.writer import KnowledgeWriteTool
        from tools.mcp_manage import MCPManageTool
        from tools.scheduling.list_tool import ScheduleListTool
        from tools.scheduling.schedule_tool import ScheduleTaskTool
        from tools.self_dev.capabilities import SelfListCapabilitiesTool
        from tools.self_dev.creator import SelfCreatePluginTool
        from tools.self_dev.modifier import SelfModifySourceTool
        from tools.self_dev.reader import SelfReadSourceTool
        from tools.self_dev.rollback import SelfRollbackTool
        from tools.self_dev.tester import SelfRunTestsTool
        from tools.system.filesystem import (
            FileDeleteTool,
            FileListTool,
            FileMoveTool,
            FileReadTool,
            FileWriteTool,
        )
        from tools.system.shell import ShellExecuteTool
        from tools.system.vault_tool import VaultLookupTool, VaultSetTool

        # System tools
        self.register(ShellExecuteTool(config))
        self.register(FileReadTool())
        self.register(FileWriteTool())
        self.register(FileListTool())
        self.register(FileDeleteTool())
        self.register(FileMoveTool())
        self.register(LLMCallTool())
        self.register(VaultLookupTool())
        self.register(VaultSetTool())

        # Knowledge tools
        self.register(KnowledgeSearchTool())
        self.register(KnowledgeWriteTool())
        self.register(KnowledgeIndexTool())
        self.register(SkillReadTool())
        self.register(SkillListTool())

        # Self-development tools
        self.register(SelfReadSourceTool(config.project_root))
        self.register(SelfRunTestsTool(config.project_root))
        self.register(SelfListCapabilitiesTool())
        self.register(SelfCreatePluginTool(config.project_root))
        self.register(SelfModifySourceTool(config.project_root))
        self.register(SelfRollbackTool(config.project_root))

        # Browser tools (46 tools from BrowserPlugin via Node.js bridge)
        for tool in create_browser_tools():
            self.register(tool)

        # Scheduling tools
        self.register(ScheduleTaskTool())
        self.register(ScheduleListTool())

        # MCP management tool (always available — lets agent manage MCP config)
        self.register(MCPManageTool())

        # Document analysis tools
        from tools.documents.analyze_tool import DocumentAnalyzeTool
        from tools.documents.collections_tool import DocumentCollectionsTool
        from tools.documents.query_tool import DocumentQueryTool

        self.register(DocumentAnalyzeTool())
        self.register(DocumentQueryTool())
        self.register(DocumentCollectionsTool())

        # Goal tools
        from tools.goals.create_tool import GoalCreateTool
        from tools.goals.manage_tool import GoalManageTool
        from tools.goals.status_tool import GoalStatusTool

        self.register(GoalCreateTool())
        self.register(GoalStatusTool())
        self.register(GoalManageTool())

        # Identity tools
        from tools.identity.reflect_tool import IdentityReflectTool
        from tools.identity.status_tool import IdentityStatusTool
        from tools.identity.update_tool import IdentityUpdateTool

        self.register(IdentityStatusTool())
        self.register(IdentityUpdateTool())
        self.register(IdentityReflectTool())

        # Email tools
        from tools.email.create_inbox_tool import EmailCreateInboxTool
        from tools.email.list_tool import EmailListTool
        from tools.email.read_tool import EmailReadTool
        from tools.email.reply_tool import EmailReplyTool
        from tools.email.search_tool import EmailSearchTool
        from tools.email.send_tool import EmailSendTool

        self.register(EmailCreateInboxTool())
        self.register(EmailSendTool())
        self.register(EmailListTool())
        self.register(EmailReadTool())
        self.register(EmailReplyTool())
        self.register(EmailSearchTool())

        # Payment tools
        from tools.payments.balance_tool import PaymentBalanceTool
        from tools.payments.history_tool import PaymentHistoryTool
        from tools.payments.preview_tool import PaymentPreviewTool
        from tools.payments.swap_tool import CryptoSwapTool
        from tools.payments.transfer_tool import CryptoTransferTool
        from tools.payments.validate_tool import PaymentValidateTool
        from tools.payments.wallet_status_tool import WalletStatusTool

        self.register(WalletStatusTool())
        self.register(PaymentBalanceTool())
        self.register(PaymentValidateTool())
        self.register(PaymentPreviewTool())
        self.register(CryptoTransferTool())
        self.register(CryptoSwapTool())
        self.register(PaymentHistoryTool())

        # Email monitor tool
        from tools.email.monitor_tool import EmailMonitorTool

        self.register(EmailMonitorTool())

        # TOTP / verification tools
        from tools.totp.delete_tool import TotpDeleteTool
        from tools.totp.enroll_tool import TotpEnrollTool
        from tools.totp.generate_tool import TotpGenerateTool
        from tools.totp.list_tool import TotpListTool

        self.register(TotpGenerateTool())
        self.register(TotpEnrollTool())
        self.register(TotpListTool())
        self.register(TotpDeleteTool())

        # Swarm tools (agent orchestration)
        from tools.swarm.redirect_tool import SwarmRedirectTool
        from tools.swarm.spawn_tool import SwarmSpawnTool
        from tools.swarm.status_tool import SwarmStatusTool
        from tools.swarm.stop_tool import SwarmStopTool

        self.register(SwarmSpawnTool())
        self.register(SwarmStatusTool())
        self.register(SwarmRedirectTool())
        self.register(SwarmStopTool())
