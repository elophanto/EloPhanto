"""Tool registry: discovers, loads, and manages available tools.

Provides tool lookup by name and generates LLM-compatible schemas.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.base import BaseTool, ToolTier


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

    # ── Tiered tool access ──────────────────────────────────────────

    def get_core_tools(self) -> list[BaseTool]:
        """Return only tier-0 (CORE) tools — always sent to the LLM."""
        return [t for t in self._tools.values() if t.tier == ToolTier.CORE]

    def get_tools_for_context(
        self,
        task_groups: set[str],
        activated_names: set[str] | None = None,
    ) -> list[BaseTool]:
        """Return tier-0 + tier-1 tools whose group matches *task_groups*.

        Also includes any tier-2 (DEFERRED) tools whose names appear in
        *activated_names* (i.e. previously discovered via tool_discover).
        """
        activated = activated_names or set()
        result: list[BaseTool] = []
        for t in self._tools.values():
            if t.tier == ToolTier.CORE:
                result.append(t)
            elif t.tier == ToolTier.PROFILE and t.group in task_groups:
                result.append(t)
            elif t.name in activated:
                result.append(t)
        return result

    def get_deferred_catalog(self) -> list[dict[str, str]]:
        """Return compact catalog entries for all tier-2 (DEFERRED) tools.

        Used to populate the ``<deferred_tools>`` section in the system
        prompt so the LLM knows what is available on-demand.
        """
        return [
            {"name": t.name, "description": t.description, "group": t.group}
            for t in self._tools.values()
            if t.tier == ToolTier.DEFERRED
        ]

    def discover_tools(self, query: str) -> list[BaseTool]:
        """Fuzzy-match *query* against all registered tools.

        Returns tools whose name, description, or group contain any query
        token.  Intended for use by the ``tool_discover`` meta-tool.
        """
        tokens = query.lower().split()
        if not tokens:
            return []
        matches: list[BaseTool] = []
        for t in self._tools.values():
            haystack = f"{t.name} {t.description} {t.group}".lower()
            if any(tok in haystack for tok in tokens):
                matches.append(t)
        return matches

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
            FilePatchTool,
            FileReadTool,
            FileWriteTool,
        )
        from tools.system.shell import ShellExecuteTool
        from tools.system.vault_tool import VaultLookupTool, VaultSetTool

        # System tools
        self.register(ShellExecuteTool(config))
        self.register(FileReadTool())
        self.register(FileWriteTool())
        self.register(FilePatchTool())
        self.register(FileListTool())
        self.register(FileDeleteTool())
        self.register(FileMoveTool())
        self.register(LLMCallTool())
        self.register(VaultLookupTool())
        self.register(VaultSetTool())

        # Godmode tool (Pliny's G0DM0D3)
        from tools.system.godmode_tool import GodmodeActivateTool

        self.register(GodmodeActivateTool())

        # Session search tool (cross-session FTS5 search)
        from tools.data.session_search import SessionSearchTool

        self.register(SessionSearchTool())

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

        # Code execution sandbox (multi-step tool orchestration)
        from tools.self_dev.execute_code import ExecuteCodeTool

        self.register(ExecuteCodeTool(config.project_root))

        # Experimentation tools (autonomous experiment loop + AutoLoop focus lock)
        from tools.experimentation.autoloop_tool import AutoloopControlTool
        from tools.experimentation.run_tool import ExperimentRunTool
        from tools.experimentation.setup_tool import ExperimentSetupTool
        from tools.experimentation.status_tool import ExperimentStatusTool

        self.register(ExperimentSetupTool(config.project_root))
        self.register(ExperimentRunTool(config.project_root))
        self.register(ExperimentStatusTool(config.project_root))
        self.register(AutoloopControlTool(config.project_root))

        # Browser tools (46 tools from BrowserPlugin via Node.js bridge)
        for tool in create_browser_tools():
            self.register(tool)

        # Desktop tools (GUI control via VM HTTP server)
        from tools.desktop.tools import create_desktop_tools

        for dt in create_desktop_tools():
            self.register(dt)

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
        from tools.goals.dream_tool import GoalDreamTool
        from tools.goals.manage_tool import GoalManageTool
        from tools.goals.status_tool import GoalStatusTool

        self.register(GoalCreateTool())
        self.register(GoalStatusTool())
        self.register(GoalManageTool())
        self.register(GoalDreamTool())

        # Identity tools
        from tools.identity.reflect_tool import IdentityReflectTool
        from tools.identity.status_tool import IdentityStatusTool
        from tools.identity.update_tool import IdentityUpdateTool

        self.register(IdentityStatusTool())
        self.register(IdentityUpdateTool())
        self.register(IdentityReflectTool())

        # User profile tool
        from tools.user.profile_tool import UserProfileViewTool

        self.register(UserProfileViewTool())

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
        from tools.payments.wallet_export_tool import WalletExportTool
        from tools.payments.wallet_status_tool import WalletStatusTool

        self.register(WalletStatusTool())
        self.register(WalletExportTool())
        self.register(PaymentBalanceTool())
        self.register(PaymentValidateTool())
        self.register(PaymentPreviewTool())
        self.register(CryptoTransferTool())
        self.register(CryptoSwapTool())
        self.register(PaymentHistoryTool())

        from tools.payments.request_tool import PaymentRequestTool

        self.register(PaymentRequestTool())

        # Web search tools (Search.sh)
        from tools.data.web_search import WebExtractTool, WebSearchTool

        self.register(WebSearchTool())
        self.register(WebExtractTool())

        # Context tools (RLM Phase 2 — context-as-variable)
        from tools.context.context_tools import (
            ContextIndexTool,
            ContextIngestTool,
            ContextQueryTool,
            ContextSliceTool,
            ContextTransformTool,
        )

        self.register(ContextIngestTool())
        self.register(ContextQueryTool())
        self.register(ContextSliceTool())
        self.register(ContextIndexTool())
        self.register(ContextTransformTool())

        # Prospecting tools
        from tools.prospecting.evaluate_tool import ProspectEvaluateTool
        from tools.prospecting.outreach_tool import ProspectOutreachTool
        from tools.prospecting.search_tool import ProspectSearchTool
        from tools.prospecting.status_tool import ProspectStatusTool

        self.register(ProspectSearchTool())
        self.register(ProspectEvaluateTool())
        self.register(ProspectOutreachTool())
        self.register(ProspectStatusTool())

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

        # Organization tools (persistent specialist agents)
        from tools.organization.delegate_tool import OrganizationDelegateTool
        from tools.organization.review_tool import OrganizationReviewTool
        from tools.organization.spawn_tool import OrganizationSpawnTool
        from tools.organization.status_tool import OrganizationStatusTool
        from tools.organization.teach_tool import OrganizationTeachTool

        self.register(OrganizationSpawnTool())
        self.register(OrganizationDelegateTool())
        self.register(OrganizationReviewTool())
        self.register(OrganizationTeachTool())
        self.register(OrganizationStatusTool())

        # Deployment tools (web hosting + database)
        from tools.deployment.database_tool import CreateDatabaseTool
        from tools.deployment.deploy_tool import DeployWebsiteTool
        from tools.deployment.deployment_status_tool import DeploymentStatusTool

        self.register(DeployWebsiteTool())
        self.register(CreateDatabaseTool())
        self.register(DeploymentStatusTool())

        # Agent Commune tools (social platform for AI agents)
        from tools.commune.comment_tool import CommuneCommentTool
        from tools.commune.home_tool import CommuneHomeTool
        from tools.commune.post_tool import CommunePostTool
        from tools.commune.profile_tool import CommuneProfileTool
        from tools.commune.register_tool import CommuneRegisterTool
        from tools.commune.search_tool import CommuneSearchTool
        from tools.commune.vote_tool import CommuneVoteTool

        self.register(CommuneRegisterTool())
        self.register(CommuneHomeTool())
        self.register(CommunePostTool())
        self.register(CommuneCommentTool())
        self.register(CommuneVoteTool())
        self.register(CommuneSearchTool())
        self.register(CommuneProfileTool())

        # Proactive communication tool (agent briefs)
        from tools.communication.brief_tool import AgentBriefTool

        self.register(AgentBriefTool())

        # Content monetization tools (publishing + affiliate marketing)
        from tools.affiliate.campaign_tool import AffiliateCampaignTool
        from tools.affiliate.pitch_tool import AffiliatePitchTool
        from tools.affiliate.scrape_tool import AffiliateScrapeTool
        from tools.publishing.tiktok_tool import TikTokUploadTool
        from tools.publishing.twitter_tool import TwitterPostTool
        from tools.publishing.youtube_tool import YouTubeUploadTool

        self.register(YouTubeUploadTool())
        self.register(TwitterPostTool())
        self.register(TikTokUploadTool())
        self.register(AffiliateScrapeTool())
        self.register(AffiliatePitchTool())
        self.register(AffiliateCampaignTool())

        # Pump.fun livestream — wraps auth + LiveKit publish for the agent's coin
        from tools.pumpfun.livestream_tool import PumpLivestreamTool

        self.register(PumpLivestreamTool())

        # Tool discover meta-tool (always available — tier 0)
        from tools.system.discover_tool import ToolDiscoverTool

        self.register(ToolDiscoverTool())

        # ── Tier overrides ─────────────────────────────────────────
        # All tools default to ToolTier.PROFILE (tier 1).
        # Override specific tools to CORE (tier 0) or DEFERRED (tier 2).

        _CORE_TOOLS = {
            "shell_execute",
            "file_read",
            "file_write",
            "file_patch",
            "file_list",
            "file_delete",
            "file_move",
            "knowledge_search",
            "knowledge_write",
            "goal_manage",
            "goal_status",
            "browser_navigate",
            "browser_click",
            "browser_type",
            "browser_evaluate",
            "tool_discover",
        }

        _DEFERRED_TOOLS = {
            # Payment tools
            "wallet_status",
            "wallet_export",
            "payment_balance",
            "payment_validate",
            "payment_preview",
            "crypto_transfer",
            "crypto_swap",
            "payment_history",
            "payment_request",
            # Email tools
            "email_create_inbox",
            "email_send",
            "email_list",
            "email_read",
            "email_reply",
            "email_search",
            "email_monitor",
            # TOTP tools
            "totp_generate",
            "totp_enroll",
            "totp_list",
            "totp_delete",
            # Deployment tools
            "deploy_website",
            "create_database",
            "deployment_status",
            # Publishing tools
            "youtube_upload",
            "tiktok_upload",
            "twitter_post",
            # Affiliate tools
            "affiliate_scrape",
            "affiliate_pitch",
            "affiliate_campaign",
            # Prospecting tools
            "prospect_search",
            "prospect_evaluate",
            "prospect_outreach",
            "prospect_status",
            # Commune tools
            "commune_register",
            "commune_home",
            "commune_post",
            "commune_comment",
            "commune_vote",
            "commune_search",
            "commune_profile",
            # Desktop tools — matched by prefix below
            # Experimentation tools
            "experiment_setup",
            "experiment_run",
            "experiment_status",
            "autoloop_control",
            # Self-dev tools
            "self_read_source",
            "self_run_tests",
            "self_list_capabilities",
            "self_create_plugin",
            "self_modify_source",
            "self_rollback",
            "execute_code",
            # Context tools
            "context_ingest",
            "context_query",
            "context_slice",
            "context_index",
            "context_transform",
            # Document tools
            "document_analyze",
            "document_query",
            "document_collections",
            # Swarm / organization tools
            "swarm_spawn",
            "swarm_status",
            "swarm_redirect",
            "swarm_stop",
            "organization_spawn",
            "organization_delegate",
            "organization_review",
            "organization_teach",
            "organization_status",
            # Communication tools
            "agent_brief",
            # Pump.fun
            "pump_livestream",
        }

        for _name, _t in self._tools.items():
            if _name in _CORE_TOOLS:
                _t._tier_override = ToolTier.CORE
            elif _name in _DEFERRED_TOOLS or _name.startswith("desktop_"):
                _t._tier_override = ToolTier.DEFERRED
