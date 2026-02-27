"""Main agent class and loop.

Orchestrates the plan-execute-reflect cycle:
1. User provides a goal
2. PLAN: LLM decides which tool to call (or responds with text if complete)
3. EXECUTE: Run the tool with permission check
4. REFLECT: Feed result back to LLM via conversation history
5. Repeat until LLM responds with text (no tool_call) or max_steps reached

Phase 1 additions: database, knowledge indexing, working memory, task memory.
Phase 2-4 additions: plugin system, self-dev tools, browser, scheduling.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import sys
import time as _time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from core.session import Session


class StatusCallback(Protocol):
    """Callback to report initialization progress."""

    def __call__(self, message: str) -> None: ...


from core.config import Config
from core.database import Database
from core.embeddings import create_embedder
from core.executor import ExecutionResult, Executor
from core.indexer import KnowledgeIndexer
from core.injection_guard import wrap_tool_result
from core.memory import MemoryManager, WorkingMemory
from core.planner import build_system_prompt
from core.plugin_loader import PluginLoader
from core.reflector import Reflector
from core.registry import ToolRegistry
from core.router import LLMRouter
from core.skills import SkillManager

logger = logging.getLogger(__name__)


_MAX_CONVERSATION_HISTORY = 20  # Max messages to carry across turns

# Tools that are read-only and safe to execute concurrently via asyncio.gather().
# Mutating tools (file_write, shell_execute, browser_*, etc.) form sequential barriers.
_PARALLEL_SAFE_TOOLS = frozenset(
    {
        "file_read",
        "file_list",
        "knowledge_search",
        "llm_call",
        "skill_read",
        "skill_list",
        "self_list_capabilities",
        "self_read_source",
        "vault_lookup",
        "hub_search",
        "document_query",
        "document_collections",
        "identity_status",
        "goal_status",
        "payment_balance",
        "wallet_status",
        "payment_history",
        "payment_validate",
        "email_list",
        "email_read",
        "email_search",
        "schedule_list",
        "swarm_status",
    }
)


def _group_tool_calls(tool_calls: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group tool calls into parallelizable batches.

    Consecutive parallel-safe tools form one group.
    Any non-safe tool gets its own single-item group (sequential barrier).
    """
    groups: list[list[dict[str, Any]]] = []
    current_safe: list[dict[str, Any]] = []

    for tc in tool_calls:
        name = tc.get("function", {}).get("name", "")
        if name in _PARALLEL_SAFE_TOOLS:
            current_safe.append(tc)
        else:
            if current_safe:
                groups.append(current_safe)
                current_safe = []
            groups.append([tc])  # Sequential barrier

    if current_safe:
        groups.append(current_safe)

    return groups if groups else [[tc] for tc in tool_calls]


@dataclass
class AgentResponse:
    """Final response from the agent to the user."""

    content: str
    steps_taken: int
    tool_calls_made: list[str] = field(default_factory=list)


class Agent:
    """The EloPhanto agent — orchestrates plan-execute-reflect."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._router = LLMRouter(config)
        self._registry = ToolRegistry(config.project_root)
        self._executor = Executor(config, self._registry)
        self._reflector = Reflector()

        # Phase 1: Knowledge & Memory
        db_path = Path(config.database.db_path)
        if not db_path.is_absolute():
            db_path = config.project_root / db_path
        self._db = Database(db_path)

        self._embedder = create_embedder(config)

        knowledge_dir = Path(config.knowledge.knowledge_dir)
        if not knowledge_dir.is_absolute():
            knowledge_dir = config.project_root / knowledge_dir
        self._indexer = KnowledgeIndexer(
            db=self._db,
            embedder=self._embedder,
            knowledge_dir=knowledge_dir,
            max_tokens=config.knowledge.chunk_max_tokens,
            min_tokens=config.knowledge.chunk_min_tokens,
        )
        self._memory_manager = MemoryManager(self._db)
        self._working_memory = WorkingMemory()

        # Skills system
        skills_dir = config.project_root / "skills"
        self._skill_manager = SkillManager(skills_dir)

        # Phase 2-4: Plugin loader, browser, scheduler
        self._plugin_loader: PluginLoader | None = None
        self._browser_manager: Any = None
        self._scheduler: Any = None
        self._vault: Any = None  # Set by caller (e.g. chat_cmd) before initialize
        self._approval_queue: Any = None  # Set during initialize if DB available
        self._hub: Any = None  # EloPhantoHub client, set during initialize
        self._storage_manager: Any = None  # StorageManager, set during initialize
        self._document_processor: Any = None  # DocumentProcessor
        self._document_store: Any = None  # DocumentStore
        self._goal_manager: Any = None  # GoalManager, set during initialize
        self._identity_manager: Any = None  # IdentityManager, set during initialize
        self._payments_manager: Any = None  # PaymentsManager, set during initialize
        self._email_config: Any = None  # EmailConfig, set during initialize
        self._email_monitor: Any = None  # EmailMonitor, set during initialize
        self._mcp_manager: Any = None  # MCPClientManager, set during initialize
        self._dataset_builder: Any = None  # DatasetBuilder, set during initialize
        self._goal_runner: Any = None  # GoalRunner, set during initialize
        self._swarm_manager: Any = None  # SwarmManager, set during initialize
        self._autonomous_mind: Any = None  # AutonomousMind, set during initialize
        self._gateway: Any = None  # Gateway instance, set by gateway_cmd/chat_cmd

        # Notification callbacks (set by Telegram adapter or other interfaces)
        self._on_task_complete: Callable[..., Any] | None = None
        self._on_error: Callable[..., Any] | None = None

        # Live progress callback (set by CLI for step-by-step visibility)
        self._on_step: Callable[[int, str, str, dict[str, Any]], None] | None = None

        # Conversation history across turns (user + assistant messages only)
        self._conversation_history: list[dict[str, Any]] = []

        # Security: agent fingerprint (set during initialize if vault available)
        self._fingerprint: str = ""
        self._fingerprint_status: str = "unavailable"

        # Resource exhaustion: process registry for shell subprocess tracking
        from core.process_registry import ProcessRegistry

        self._process_registry = ProcessRegistry(
            max_concurrent=self._config.shell.max_concurrent_processes
        )

    async def initialize(self, on_status: StatusCallback | None = None) -> None:
        """One-time setup: load tools, init DB, index knowledge, check health.

        Parallelizes slow network operations (embedding detection, health
        checks) so startup is limited by the slowest single check, not
        their sum.

        Args:
            on_status: Optional callback invoked with progress messages.
        """

        def _status(msg: str) -> None:
            if on_status:
                on_status(msg)

        _status("Loading tools")
        self._registry.load_builtin_tools(self._config)

        # Inject router into llm_call tool
        llm_tool = self._registry.get("llm_call")
        if llm_tool:
            llm_tool._router = self._router

        # Initialize database
        _status("Setting up database")
        try:
            await self._db.initialize()

            from core.approval_queue import ApprovalQueue

            self._approval_queue = ApprovalQueue(self._db)
            await self._approval_queue.initialize()
        except Exception as e:
            logger.warning(f"Database initialization failed: {e}")

        # --- LLM health check (blocking — fast pings) ---
        _status("Checking LLM providers")
        _hc_start = _time.monotonic()
        health = await self._router.health_check()
        self._provider_health = health
        enabled = [k for k, v in health.items() if v]
        if not enabled:
            logger.warning("No LLM providers are reachable!")
        else:
            logger.info(
                "[TIMING] health check: %.2fs | active: %s",
                _time.monotonic() - _hc_start,
                ", ".join(enabled),
            )

        # --- Embedding detection (must complete before indexing) ---
        _status("Detecting embedding model")
        try:
            from core.embeddings import OpenRouterEmbedder

            kc = self._config.knowledge
            if isinstance(self._embedder, OpenRouterEmbedder):
                primary_model = kc.embedding_openrouter_model
                fallback_model = None
            else:
                primary_model = kc.embedding_model
                fallback_model = kc.embedding_fallback
            model, dims = await self._embedder.detect_model(
                primary=primary_model,
                fallback=fallback_model,
            )
            if model and dims:
                self._indexer.set_embedding_model(model)
                try:
                    await self._db.create_vec_table(dims)
                except Exception as e:
                    logger.warning(f"Failed to create vec table: {e}")
                # Also create document vec table if documents subsystem is active
                if self._document_store:
                    try:
                        await self._db.create_document_vec_table(dims)
                    except Exception:
                        pass
                logger.info(f"Embedding model ready: {model} ({dims}d)")
        except Exception as e:
            logger.info(f"Embeddings not available: {e}")

        # Inject dependencies into knowledge tools
        self._inject_knowledge_deps()

        # Load plugins
        _status("Loading plugins")
        plugins_dir = Path(self._config.plugins.plugins_dir)
        if not plugins_dir.is_absolute():
            plugins_dir = self._config.project_root / plugins_dir
        if plugins_dir.exists() and self._config.plugins.auto_load:
            self._plugin_loader = PluginLoader(plugins_dir, self._config.project_root)
            results = self._plugin_loader.load_all()
            for result in results:
                if result.success and result.tool:
                    self._registry.register(result.tool)
                    logger.info(f"Loaded plugin: {result.name}")
                elif not result.success:
                    logger.warning(
                        f"Failed to load plugin {result.name}: {result.error}"
                    )

        # Inject self-dev tool dependencies
        self._inject_self_dev_deps()

        # Inject process registry into shell tool for resource tracking
        shell_tool = self._registry.get("shell_execute")
        if shell_tool and hasattr(shell_tool, "set_process_registry"):
            shell_tool.set_process_registry(self._process_registry)

        # Create browser manager (if enabled) — lazy init, Chrome opens on first use
        if self._config.browser.enabled:
            _status("Preparing browser")
            try:
                from core.browser_manager import BrowserManager

                self._browser_manager = BrowserManager.from_config(self._config.browser)

                # Pass OpenRouter key + vision model for screenshot analysis
                or_cfg = self._config.llm.providers.get("openrouter")
                if or_cfg and or_cfg.api_key and or_cfg.enabled:
                    self._browser_manager.openrouter_key = or_cfg.api_key
                if self._config.browser.vision_model:
                    self._browser_manager.vision_model = (
                        self._config.browser.vision_model
                    )

                logger.info(
                    "Browser configured (mode=%s) — will launch on first use",
                    self._browser_manager.mode,
                )
            except Exception as e:
                logger.warning(f"Browser setup failed: {e}")

        # Inject browser interface into browser tools
        self._inject_browser_deps()

        # Inject vault into vault tool (if vault was unlocked)
        self._inject_vault_deps()

        # Inject vault + identity into TOTP tools
        self._inject_totp_deps()

        # Start scheduler (if enabled)
        if self._config.scheduler.enabled:
            _status("Starting scheduler")
            try:
                from core.scheduler import TaskScheduler

                self._scheduler = TaskScheduler(
                    db=self._db,
                    task_executor=self._execute_scheduled_task,
                    result_notifier=self._notify_scheduled_result,
                )
                await self._scheduler.start()
            except Exception as e:
                logger.warning(f"Scheduler failed to start: {e}")

        # Inject scheduler into schedule tools
        self._inject_scheduler_deps()

        # Discover skills and inject into skill tools
        _status("Loading skills")
        self._skill_manager.discover()
        self._inject_skill_deps()

        # Initialize EloPhantoHub (skill registry)
        if self._config.hub.enabled:
            _status("Loading EloPhantoHub")
            try:
                from core.hub import HubClient

                self._hub = HubClient(
                    skills_dir=self._config.project_root / "skills",
                    index_url=self._config.hub.index_url,
                    cache_ttl_hours=self._config.hub.cache_ttl_hours,
                )
                self._skill_manager.hub = self._hub
                self._inject_hub_deps()
                # Index is fetched lazily on first search/install
            except Exception as e:
                logger.debug(f"EloPhantoHub initialization failed: {e}")

        # Initialize document analysis subsystem
        if self._config.documents.enabled:
            _status("Preparing document analysis")
            try:
                from core.document_processor import DocumentProcessor
                from core.document_store import DocumentStore
                from core.storage import StorageManager

                self._storage_manager = StorageManager(
                    self._config.storage, self._config.project_root
                )
                await self._storage_manager.initialize()

                self._document_processor = DocumentProcessor(self._config.documents)
                self._document_store = DocumentStore(
                    db=self._db,
                    embedder=self._embedder,
                    embedding_model=self._indexer._embedding_model,
                    storage=self._storage_manager,
                    config=self._config.documents,
                )

                # Document vec table is created lazily when embeddings are detected
                # (background task in _detect_embeddings_bg)

                self._inject_document_deps()
                logger.info("Document analysis ready")
            except Exception as e:
                logger.warning(f"Document analysis setup failed: {e}")

        # Initialize goal loop system
        if self._config.goals.enabled:
            _status("Preparing goal system")
            try:
                from core.goal_manager import GoalManager

                self._goal_manager = GoalManager(
                    db=self._db, router=self._router, config=self._config.goals
                )
                self._inject_goal_deps()
                logger.info("Goal system ready")

                # Initialize GoalRunner for autonomous background execution
                if self._config.goals.auto_continue:
                    from core.goal_runner import GoalRunner

                    self._goal_runner = GoalRunner(
                        agent=self,
                        goal_manager=self._goal_manager,
                        gateway=self._gateway,
                        config=self._config.goals,
                    )
            except Exception as e:
                logger.warning(f"Goal system setup failed: {e}")

        # Initialize autonomous mind
        if self._config.autonomous_mind.enabled:
            _status("Preparing autonomous mind")
            try:
                from core.autonomous_mind import AutonomousMind

                self._autonomous_mind = AutonomousMind(
                    agent=self,
                    gateway=self._gateway,
                    config=self._config.autonomous_mind,
                    project_root=self._config.project_root,
                )
                logger.info("Autonomous mind ready (starts on gateway boot)")
            except Exception as e:
                logger.warning(f"Autonomous mind setup failed: {e}")

        # Initialize identity system
        if self._config.identity.enabled:
            _status("Loading identity")
            try:
                from core.identity import IdentityManager

                self._identity_manager = IdentityManager(
                    db=self._db, router=self._router, config=self._config.identity
                )
                await self._identity_manager.load_or_create()
                self._inject_identity_deps()
                logger.info("Identity system ready")
            except Exception as e:
                logger.warning(f"Identity system setup failed: {e}")

        # Initialize payments system
        if self._config.payments.enabled:
            _status("Loading payments")
            try:
                from core.payments import PaymentsManager

                self._payments_manager = PaymentsManager(
                    db=self._db, config=self._config.payments, vault=self._vault
                )
                await self._payments_manager.initialize()
                self._inject_payment_deps()
                logger.info("Payments system ready")
            except Exception as e:
                logger.warning(f"Payments system setup failed: {e}")

        # Initialize email system
        if self._config.email.enabled:
            _status("Loading email")
            try:
                self._email_config = self._config.email
                self._inject_email_deps()
                # Create email monitor (user starts it via email_monitor tool)
                email_list_tool = self._registry.get("email_list")
                if email_list_tool:
                    from core.email_monitor import EmailMonitor

                    self._email_monitor = EmailMonitor(
                        email_list_tool=email_list_tool,
                        config=self._email_config,
                        data_dir=self._config.project_dir / "data",
                    )
                    self._inject_email_monitor_dep()
                logger.info("Email system ready")
            except Exception as e:
                logger.warning(f"Email system setup failed: {e}")

        # Initialize swarm system (agent orchestration)
        if self._config.swarm.enabled:
            _status("Preparing swarm")
            try:
                from core.swarm import SwarmManager

                self._swarm_manager = SwarmManager(
                    db=self._db,
                    config=self._config.swarm,
                    project_root=self._config.project_root,
                    gateway=self._gateway,
                )
                await self._swarm_manager.start()
                self._inject_swarm_deps()
                logger.info("Swarm system ready")
            except Exception as e:
                logger.warning(f"Swarm system setup failed: {e}")

        # Initialize MCP client (connect to external MCP servers)
        if self._config.mcp.enabled:
            _mcp_available = False
            try:
                import mcp as _mcp_mod  # noqa: F401

                _mcp_available = True
            except ImportError:
                _status("Installing MCP SDK")
                try:
                    proc = await asyncio.create_subprocess_exec(
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "mcp[cli]>=1.0.0",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await asyncio.wait_for(proc.communicate(), timeout=120)
                    if proc.returncode == 0:
                        _mcp_available = True
                        logger.info("MCP SDK installed automatically")
                    else:
                        logger.warning(
                            "MCP SDK auto-install failed (exit %d). "
                            "Run manually: uv pip install -e '.[mcp]'",
                            proc.returncode,
                        )
                except Exception as e:
                    logger.warning("MCP SDK auto-install failed: %s", e)

            if _mcp_available:
                _status("Connecting to MCP servers")
                _mcp_start = _time.monotonic()
                try:
                    from core.mcp_client import MCPClientManager

                    self._mcp_manager = MCPClientManager(vault=self._vault)
                    mcp_results = await self._mcp_manager.connect_all(
                        self._config.mcp.servers
                    )
                    mcp_tools = await self._mcp_manager.discover_and_create_tools()
                    for tool in mcp_tools:
                        self._registry.register(tool)
                    connected = [n for n, ok in mcp_results.items() if ok]
                    logger.info(
                        "[TIMING] MCP connect: %.2fs | %d tools from %s",
                        _time.monotonic() - _mcp_start,
                        len(mcp_tools),
                        ", ".join(connected) if connected else "none",
                    )
                except Exception as e:
                    logger.warning(
                        "[TIMING] MCP failed after %.2fs: %s",
                        _time.monotonic() - _mcp_start,
                        e,
                    )

        # Auto-index knowledge on startup
        if self._config.knowledge.auto_index_on_startup:
            _status("Indexing knowledge")
            try:
                result = await self._indexer.index_incremental()
                if result.files_indexed > 0:
                    logger.info(
                        f"Indexed {result.files_indexed} knowledge files "
                        f"({result.chunks_created} chunks)"
                    )
                if result.errors:
                    for err in result.errors:
                        logger.warning(f"Indexing error: {err}")

                # Check embedding health — auto-recover if broken
                try:
                    total_chunks = await self._db.execute(
                        "SELECT COUNT(*) as cnt FROM knowledge_chunks"
                    )
                    chunk_count = total_chunks[0]["cnt"] if total_chunks else 0
                    vec_count = 0
                    if self._db.vec_available:
                        vec_rows = await self._db.execute(
                            "SELECT COUNT(*) as cnt FROM vec_chunks_rowids"
                        )
                        vec_count = vec_rows[0]["cnt"] if vec_rows else 0

                    if chunk_count > 0 and vec_count == 0:
                        logger.warning(
                            f"⚠ EMBEDDINGS BROKEN: {chunk_count} chunks, "
                            f"0 embeddings — forcing full re-index"
                        )
                        _status("Re-indexing knowledge (fixing embeddings)")
                        reindex = await self._indexer.index_all()
                        logger.info(
                            f"Full re-index: {reindex.files_indexed} files, "
                            f"{reindex.chunks_created} chunks"
                        )
                        # Re-check after full reindex
                        if self._db.vec_available:
                            vec_rows = await self._db.execute(
                                "SELECT COUNT(*) as cnt FROM vec_chunks_rowids"
                            )
                            vec_count = vec_rows[0]["cnt"] if vec_rows else 0
                        total_chunks = await self._db.execute(
                            "SELECT COUNT(*) as cnt FROM knowledge_chunks"
                        )
                        chunk_count = total_chunks[0]["cnt"] if total_chunks else 0
                        if vec_count > 0:
                            logger.info(
                                f"Embeddings recovered: {chunk_count} chunks, "
                                f"{vec_count} embeddings"
                            )
                        else:
                            logger.error(
                                f"⚠ EMBEDDINGS STILL BROKEN after re-index: "
                                f"{chunk_count} chunks, 0 embeddings — "
                                f"check embedding provider config"
                            )
                    else:
                        logger.info(
                            f"Knowledge: {chunk_count} chunks, "
                            f"{vec_count} embeddings, "
                            f"vec_available={self._db.vec_available}"
                        )
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"Knowledge indexing failed: {e}")

        # Census heartbeat (non-blocking, fire-and-forget)
        from core.census import send_heartbeat

        data_dir = self._config.project_root / self._config.storage.data_dir
        asyncio.create_task(send_heartbeat(data_dir))

        # Security: compute agent fingerprint (if vault is available)
        if self._vault:
            try:
                from core.fingerprint import (
                    compute_config_hash,
                    compute_vault_salt_hash,
                    get_or_create_fingerprint,
                )

                config_hash = compute_config_hash(self._config)
                vault_salt_hash = compute_vault_salt_hash(self._config.project_root)
                self._fingerprint, self._fingerprint_status = get_or_create_fingerprint(
                    self._vault, config_hash, vault_salt_hash
                )
            except Exception as e:
                logger.debug("Fingerprint initialization failed: %s", e)

        # Self-learning dataset collection (opt-in)
        if self._config.self_learning.enabled:
            try:
                from core.dataset_builder import DatasetBuilder

                self._dataset_builder = DatasetBuilder(
                    db=self._db,
                    config=self._config.self_learning,
                    data_dir=data_dir,
                )
                logger.info("Dataset collection ready")
            except Exception as e:
                logger.debug("Dataset collection setup failed: %s", e)

    async def shutdown(self) -> None:
        """Clean up all subsystems gracefully."""
        if self._mcp_manager:
            try:
                await self._mcp_manager.shutdown()
            except Exception as e:
                logger.debug("MCP shutdown error: %s", e)
        if self._browser_manager:
            try:
                await self._browser_manager.close()
            except Exception as e:
                logger.debug("Browser shutdown error: %s", e)
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception as e:
                logger.debug("Scheduler shutdown error: %s", e)
        if self._goal_runner:
            try:
                await self._goal_runner.cancel()
            except Exception as e:
                logger.debug("GoalRunner shutdown error: %s", e)
        if self._autonomous_mind:
            try:
                await self._autonomous_mind.cancel()
            except Exception as e:
                logger.debug("Autonomous mind shutdown error: %s", e)
        if self._email_monitor:
            try:
                await self._email_monitor.stop()
            except Exception as e:
                logger.debug("Email monitor shutdown error: %s", e)
        if self._swarm_manager:
            try:
                await self._swarm_manager.stop()
            except Exception as e:
                logger.debug("Swarm manager shutdown error: %s", e)
        if self._dataset_builder:
            try:
                await self._dataset_builder.flush()
            except Exception as e:
                logger.debug("Dataset collection flush error: %s", e)
        if self._db:
            try:
                await self._db.close()
            except Exception as e:
                logger.debug("DB close error: %s", e)

    def _inject_knowledge_deps(self) -> None:
        """Inject database, embedder, and indexer into knowledge tools."""
        search_tool = self._registry.get("knowledge_search")
        if search_tool:
            search_tool._db = self._db
            search_tool._embedder = self._embedder
            search_tool._embedding_model = self._indexer._embedding_model

        write_tool = self._registry.get("knowledge_write")
        if write_tool:
            knowledge_dir = Path(self._config.knowledge.knowledge_dir)
            if not knowledge_dir.is_absolute():
                knowledge_dir = self._config.project_root / knowledge_dir
            write_tool._knowledge_dir = knowledge_dir
            write_tool._indexer = self._indexer

        index_tool = self._registry.get("knowledge_index")
        if index_tool:
            index_tool._indexer = self._indexer

    def _inject_self_dev_deps(self) -> None:
        """Inject dependencies into self-development tools."""
        capabilities_tool = self._registry.get("self_list_capabilities")
        if capabilities_tool:
            capabilities_tool._registry = self._registry

        creator_tool = self._registry.get("self_create_plugin")
        if creator_tool:
            creator_tool._router = self._router
            creator_tool._registry = self._registry
            creator_tool._plugin_loader = self._plugin_loader
            creator_tool._db = self._db

        modifier_tool = self._registry.get("self_modify_source")
        if modifier_tool:
            modifier_tool._router = self._router

    def _inject_browser_deps(self) -> None:
        """Inject browser manager into all browser tools."""
        for tool in self._registry.all_tools():
            if tool.name.startswith("browser_") and hasattr(tool, "_browser_manager"):
                tool._browser_manager = self._browser_manager

    def _inject_vault_deps(self) -> None:
        """Inject vault into vault tools."""
        for tool_name in ("vault_lookup", "vault_set"):
            tool = self._registry.get(tool_name)
            if tool and self._vault:
                tool._vault = self._vault

    def _inject_scheduler_deps(self) -> None:
        """Inject scheduler into scheduling tools."""
        schedule_tool = self._registry.get("schedule_task")
        if schedule_tool and self._scheduler:
            schedule_tool._scheduler = self._scheduler

        list_tool = self._registry.get("schedule_list")
        if list_tool and self._scheduler:
            list_tool._scheduler = self._scheduler

    def _inject_skill_deps(self) -> None:
        """Inject skill manager into skill tools."""
        skill_read = self._registry.get("skill_read")
        if skill_read:
            skill_read._skill_manager = self._skill_manager

        skill_list = self._registry.get("skill_list")
        if skill_list:
            skill_list._skill_manager = self._skill_manager

    def _inject_hub_deps(self) -> None:
        """Register and inject EloPhantoHub tools."""
        from tools.knowledge.hub_tool import HubInstallTool, HubSearchTool

        hub_search = HubSearchTool()
        hub_search._hub = self._hub
        self._registry.register(hub_search)

        hub_install = HubInstallTool()
        hub_install._hub = self._hub
        self._registry.register(hub_install)

    def _inject_document_deps(self) -> None:
        """Inject document subsystem into document tools."""
        analyze_tool = self._registry.get("document_analyze")
        if analyze_tool:
            analyze_tool._processor = self._document_processor
            analyze_tool._store = self._document_store
            analyze_tool._storage = self._storage_manager
            analyze_tool._router = self._router
            analyze_tool._config = self._config.documents

        query_tool = self._registry.get("document_query")
        if query_tool:
            query_tool._store = self._document_store

        collections_tool = self._registry.get("document_collections")
        if collections_tool:
            collections_tool._store = self._document_store

    def _inject_goal_deps(self) -> None:
        """Inject goal manager and goal runner into goal tools."""
        for tool_name in ("goal_create", "goal_status", "goal_manage"):
            tool = self._registry.get(tool_name)
            if tool and self._goal_manager:
                tool._goal_manager = self._goal_manager
            if (
                tool
                and self._goal_runner
                and tool_name in ("goal_create", "goal_manage")
            ):
                tool._goal_runner = self._goal_runner

    def _inject_identity_deps(self) -> None:
        """Inject identity manager into identity tools."""
        for tool_name in ("identity_status", "identity_update", "identity_reflect"):
            tool = self._registry.get(tool_name)
            if tool and self._identity_manager:
                tool._identity_manager = self._identity_manager

    def _inject_payment_deps(self) -> None:
        """Inject payments manager into payment tools."""
        payment_tools = (
            "wallet_status",
            "payment_balance",
            "payment_validate",
            "payment_preview",
            "crypto_transfer",
            "crypto_swap",
            "payment_history",
        )
        for tool_name in payment_tools:
            tool = self._registry.get(tool_name)
            if tool and self._payments_manager:
                tool._payments_manager = self._payments_manager

    def _inject_email_deps(self) -> None:
        """Inject email config, vault, db, and identity into email tools."""
        email_tools = (
            "email_create_inbox",
            "email_send",
            "email_list",
            "email_read",
            "email_reply",
            "email_search",
        )
        for tool_name in email_tools:
            tool = self._registry.get(tool_name)
            if tool:
                tool._config = self._email_config
                if self._vault:
                    tool._vault = self._vault
                if hasattr(tool, "_db"):
                    tool._db = self._db
                if hasattr(tool, "_identity_manager") and self._identity_manager:
                    tool._identity_manager = self._identity_manager

    def _inject_email_monitor_dep(self) -> None:
        """Inject EmailMonitor instance into the email_monitor tool."""
        tool = self._registry.get("email_monitor")
        if tool and self._email_monitor:
            tool._email_monitor = self._email_monitor

    def _inject_swarm_deps(self) -> None:
        """Inject SwarmManager into swarm tools."""
        swarm_tools = ("swarm_spawn", "swarm_status", "swarm_redirect", "swarm_stop")
        for tool_name in swarm_tools:
            tool = self._registry.get(tool_name)
            if tool and self._swarm_manager:
                tool._swarm_manager = self._swarm_manager

    def _inject_totp_deps(self) -> None:
        """Inject vault and identity manager into TOTP tools."""
        for tool_name in ("totp_generate", "totp_enroll", "totp_list", "totp_delete"):
            tool = self._registry.get(tool_name)
            if tool:
                if self._vault:
                    tool._vault = self._vault
                if hasattr(tool, "_identity_manager") and self._identity_manager:
                    tool._identity_manager = self._identity_manager

    def set_approval_callback(
        self, callback: Callable[[str, str, dict[str, Any]], bool]
    ) -> None:
        """Set the user approval callback (from CLI layer)."""
        self._executor.set_approval_callback(callback)

    def clear_conversation(self) -> None:
        """Clear conversation history (start a fresh context)."""
        self._conversation_history.clear()

    async def run_session(
        self,
        goal: str,
        session: Session,
        approval_callback: Callable[..., Any] | None = None,
        on_step: Callable[..., Any] | None = None,
        authority: Any | None = None,
    ) -> AgentResponse:
        """Execute a goal with session-scoped conversation history.

        This is the gateway-compatible entry point. The Agent instance is
        shared (tools, router, registry), but conversation state is
        isolated per session.

        Args:
            goal: User's natural-language request.
            session: Isolated session with its own conversation_history.
            approval_callback: Async callback for tool approval (routed
                to the correct channel via gateway).
            on_step: Async callback for step progress reporting.
            authority: AuthorityLevel for the requesting user (from gateway).
        """

        # Pause background execution if user sends a message
        if self._goal_runner and self._goal_runner.is_running:
            self._goal_runner.notify_user_interaction()
        if self._autonomous_mind and self._autonomous_mind.is_running:
            self._autonomous_mind.notify_user_interaction()

        # Temporarily override callbacks for this session
        prev_approval = self._executor._approval_callback
        prev_step = self._on_step

        if approval_callback:
            self._executor.set_approval_callback(approval_callback)
        if on_step:
            self._on_step = on_step

        try:
            response = await self._run_with_history(
                goal,
                session.conversation_history,
                session.append_conversation_turn,
                authority=authority,
                session=session,
            )
            session.touch()
            return response
        finally:
            # Restore previous callbacks
            self._executor._approval_callback = prev_approval
            self._on_step = prev_step
            # Resume autonomous mind after user task
            if self._autonomous_mind and self._autonomous_mind.is_paused:
                asyncio.create_task(self._autonomous_mind.notify_task_complete())

    async def run(
        self, goal: str, *, max_steps_override: int | None = None
    ) -> AgentResponse:
        """Execute the plan-execute-reflect loop for a user goal.

        Legacy direct mode — uses internal conversation history.
        For gateway mode, use run_session() instead.

        Args:
            max_steps_override: If set, overrides the global max_steps config
                for this run only (used by AutonomousMind to enforce max_rounds).
        """
        from core.authority import AuthorityLevel

        return await self._run_with_history(
            goal,
            self._conversation_history,
            self._append_conversation_turn,
            max_steps_override=max_steps_override,
            authority=AuthorityLevel.OWNER,
        )

    async def _run_with_history(
        self,
        goal: str,
        conversation_history: list[dict[str, Any]],
        append_turn: Callable[[str, str], None],
        *,
        max_steps_override: int | None = None,
        authority: Any | None = None,
        session: Any | None = None,
    ) -> AgentResponse:
        """Core plan-execute-reflect loop, parameterized on history source."""
        logger.info("[TIMING] _run_with_history entered for: %s", goal[:80])
        self._router.cost_tracker.reset_task()
        self._working_memory.clear()

        tool_calls_made: list[str] = []
        step = 0
        hard_limit = max_steps_override or self._config.max_steps or 500
        max_time = self._config.max_time_seconds
        start_time = _time.monotonic()
        last_model_used = "unknown"

        # Stagnation detection: stop when the agent is stuck, not on a clock.
        consecutive_errors = 0
        recent_calls: list[str] = []
        _STAGNATION_WINDOW = 8
        _MAX_CONSECUTIVE_ERRORS = 5

        # Response hash dedup — catch repeating LLM outputs even across tools
        recent_response_hashes: list[int] = []
        _RESPONSE_HASH_CHARS = 200
        _RESPONSE_DEDUP_THRESHOLD = 3  # N identical in last window
        _RESPONSE_DEDUP_WINDOW = 5

        # --- Pre-loop context (non-blocking) ---
        # Knowledge retrieval is fire-and-forget: results populate working
        # memory for the *next* turn.  The LLM can call knowledge_search
        # explicitly when it needs context — no reason to block here.
        _ctx_start = _time.monotonic()

        async def _background_retrieve() -> None:
            try:
                await self._auto_retrieve(goal)
            except Exception:
                pass

        asyncio.create_task(_background_retrieve())

        # Goal + identity context are fast local DB reads — worth keeping.
        goal_context = ""
        identity_context = ""
        try:
            if self._goal_manager:
                active = await self._goal_manager.list_goals(status="active", limit=1)
                if active:
                    goal_context = await self._goal_manager.build_goal_context(
                        active[0].goal_id
                    )
        except Exception:
            pass

        try:
            if self._identity_manager:
                identity_context = await self._identity_manager.build_identity_context()
        except Exception:
            pass

        logger.info("[TIMING] pre-loop context: %.2fs", _time.monotonic() - _ctx_start)

        # Build system prompt with XML-structured sections, skills, and knowledge
        _prompt_start = _time.monotonic()
        knowledge_context = self._working_memory.format_context()
        available_skills = self._skill_manager.format_available_skills(goal)

        # --- Authority: resolve and filter tools ---
        from core.authority import (
            AuthorityLevel,
            check_tool_authority,
            filter_tools_for_authority,
        )
        from core.runtime_state import build_runtime_state

        _authority = authority if authority is not None else AuthorityLevel.OWNER
        all_tool_objs = self._registry.all_tools()
        authorized_tools = filter_tools_for_authority(all_tool_objs, _authority)

        # Build runtime state XML for the system prompt
        _channel = "cli"
        if session is not None:
            _channel = getattr(session, "channel", "cli") or "cli"

        # Storage quota snapshot (quick sync check)
        _storage_used, _storage_quota, _storage_status = 0.0, 0.0, ""
        if hasattr(self, "_storage_manager") and self._storage_manager:
            try:
                _storage_used, _storage_quota, _storage_status = (
                    self._storage_manager.check_quota()
                )
            except Exception:
                pass

        _runtime_state = build_runtime_state(
            fingerprint=self._fingerprint,
            fingerprint_status=self._fingerprint_status,
            tools=authorized_tools,
            authority=_authority.value,
            channel=_channel,
            storage_status=_storage_status,
            storage_used_mb=_storage_used,
            storage_quota_mb=_storage_quota,
            active_processes=self._process_registry.count,
            max_processes=self._config.shell.max_concurrent_processes,
            provider_stats=self._router.provider_tracker.get_provider_stats(),
        )

        system_content = build_system_prompt(
            permission_mode=self._config.permission_mode,
            browser_enabled=self._config.browser.enabled,
            scheduler_enabled=self._config.scheduler.enabled,
            goals_enabled=self._config.goals.enabled,
            identity_enabled=self._config.identity.enabled,
            payments_enabled=self._config.payments.enabled,
            email_enabled=self._config.email.enabled,
            mcp_enabled=bool(self._mcp_manager and self._mcp_manager.connected_servers),
            swarm_enabled=self._config.swarm.enabled,
            knowledge_context=knowledge_context,
            available_skills=available_skills,
            goal_context=goal_context,
            identity_context=identity_context,
            runtime_state=_runtime_state,
            current_goal=goal,
            workspace=self._config.workspace,
        )

        # Forward task context to browser bridge for goal-aware vision analysis
        if self._browser_manager:
            try:
                await self._browser_manager.set_task_context(goal)
            except Exception:
                pass

        # Build conversation for LLM: prior turns + current user message
        messages: list[dict[str, Any]] = list(conversation_history)
        messages.append({"role": "user", "content": goal})

        _tools = [t.to_llm_schema() for t in authorized_tools]
        logger.info(
            "[TIMING] prompt built: %.2fs | system_prompt=%d chars | tools=%d | messages=%d",
            _time.monotonic() - _prompt_start,
            len(system_content),
            len(_tools),
            len(messages),
        )

        stagnation_reason = ""
        while step < hard_limit:
            if max_time and (_time.monotonic() - start_time) > max_time:
                stagnation_reason = (
                    f"time limit reached ({int(_time.monotonic() - start_time)}s)"
                )
                logger.info("Time limit reached")
                break
            if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                stagnation_reason = f"{consecutive_errors} consecutive errors"
                logger.info("Stagnation: %s", stagnation_reason)
                break
            if len(recent_calls) >= _STAGNATION_WINDOW:
                unique = set(recent_calls[-_STAGNATION_WINDOW:])
                if len(unique) == 1:
                    stagnation_reason = (
                        f"repeating {next(iter(unique))} {_STAGNATION_WINDOW} times"
                    )
                    logger.info("Stagnation: %s", stagnation_reason)
                    break
            # Response hash dedup — agent repeating itself
            if len(recent_response_hashes) >= _RESPONSE_DEDUP_WINDOW:
                from collections import Counter as _Counter

                _hash_counts = _Counter(
                    recent_response_hashes[-_RESPONSE_DEDUP_WINDOW:]
                )
                _most_common = _hash_counts.most_common(1)[0][1]
                if _most_common >= _RESPONSE_DEDUP_THRESHOLD:
                    stagnation_reason = (
                        f"LLM repeating same response "
                        f"({_most_common}/{_RESPONSE_DEDUP_WINDOW})"
                    )
                    logger.info("Stagnation: %s", stagnation_reason)
                    break
            # Budget guard — stop if per-task or daily budget exceeded
            if not self._router.cost_tracker.within_budget(
                self._config.llm.budget.daily_limit_usd,
                self._config.llm.budget.per_task_limit_usd,
            ):
                stagnation_reason = (
                    f"budget exceeded "
                    f"(task=${self._router.cost_tracker.task_total:.2f})"
                )
                logger.warning("Stagnation: %s", stagnation_reason)
                break
            step += 1
            logger.info("Step %d", step)

            # === PLAN ===
            _llm_start = _time.monotonic()
            logger.info("[TIMING] LLM call starting (step %d)...", step)
            try:
                response = await self._router.complete(
                    messages=[{"role": "system", "content": system_content}] + messages,
                    task_type="planning",
                    tools=_tools,
                    temperature=0.2,
                )
            except Exception as e:
                logger.error(f"Planning LLM call failed: {e}")
                return AgentResponse(
                    content=f"I encountered an error while thinking: {e}",
                    steps_taken=step,
                    tool_calls_made=tool_calls_made,
                )
            logger.info(
                "LLM call step %d: %.1fs (%s/%s)",
                step,
                _time.monotonic() - _llm_start,
                response.provider,
                response.model_used,
            )
            if response.suspected_truncated:
                logger.warning(
                    "Truncated response from %s/%s (finish_reason=%s, tokens=%d)",
                    response.provider,
                    response.model_used,
                    response.finish_reason,
                    response.output_tokens,
                )
            last_model_used = response.model_used

            # Track response hash for dedup detection
            _resp_text = (response.content or "")[:_RESPONSE_HASH_CHARS]
            if _resp_text:
                recent_response_hashes.append(hash(_resp_text))
                if len(recent_response_hashes) > _RESPONSE_DEDUP_WINDOW:
                    recent_response_hashes = recent_response_hashes[
                        -_RESPONSE_DEDUP_WINDOW:
                    ]

            # Check if LLM responded with text (no tool calls) = task complete
            if not response.tool_calls:
                final_content = response.content or "Task complete."

                # Post-task housekeeping — fire-and-forget so the user
                # gets the response immediately.
                asyncio.create_task(
                    self._store_task_memory(
                        goal, final_content, "completed", tool_calls_made
                    )
                )

                # Auto-detect owner directives in user message
                asyncio.create_task(self._detect_and_store_directive(goal))

                if self._identity_manager:
                    asyncio.create_task(
                        self._identity_manager.reflect_on_task(
                            goal=goal,
                            outcome=final_content[:200],
                            tools_used=list(set(tool_calls_made)),
                        )
                    )

                # Dataset collection (non-blocking, fire-and-forget)
                if self._dataset_builder:
                    asyncio.create_task(
                        self._dataset_builder.record_task(
                            messages=messages,
                            tool_calls_made=tool_calls_made,
                            success=True,
                            duration_seconds=_time.monotonic() - start_time,
                            model_used=response.model_used,
                        )
                    )

                # Persist user+assistant to conversation history for next turn
                append_turn(goal, final_content)

                agent_response = AgentResponse(
                    content=final_content,
                    steps_taken=step,
                    tool_calls_made=tool_calls_made,
                )

                if self._on_task_complete:
                    try:
                        cost = self._router.cost_tracker.task_total
                        await self._on_task_complete(goal, final_content, step, cost)
                    except Exception:
                        pass

                return agent_response

            # LLM wants to call tool(s) — add assistant message to history
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": response.tool_calls,
            }
            messages.append(assistant_msg)

            # === EXECUTE tool calls (parallel where safe) ===
            groups = _group_tool_calls(response.tool_calls)

            for group in groups:
                # Fire progress callbacks for all tools in the group
                for tc in group:
                    func_name = tc["function"]["name"]
                    tool_calls_made.append(func_name)
                    recent_calls.append(func_name)
                    try:
                        _raw = tc["function"].get("arguments", "{}")
                        _params = json.loads(_raw) if isinstance(_raw, str) else _raw
                    except Exception:
                        _params = {}
                    if self._on_step:
                        try:
                            result = self._on_step(
                                step, func_name, response.content or "", _params
                            )
                            if inspect.isawaitable(result):
                                await result
                        except Exception:
                            pass

                # Authority pre-check: block tools not allowed for this tier
                # (safety net in case LLM hallucinates a tool not in its schema)
                authority_blocked: list[tuple[dict, ExecutionResult]] = []
                allowed_group: list[dict] = []
                for tc in group:
                    _tc_name = tc.get("function", {}).get("name", "")
                    if not check_tool_authority(_tc_name, _authority):
                        authority_blocked.append(
                            (
                                tc,
                                ExecutionResult(
                                    tool_name=_tc_name,
                                    tool_call_id=tc.get("id", ""),
                                    error=f"Tool '{_tc_name}' is not available for {_authority.value} users.",
                                ),
                            )
                        )
                    else:
                        allowed_group.append(tc)

                # Execute allowed tools
                if len(allowed_group) > 1:
                    exec_results_raw = await asyncio.gather(
                        *(self._executor.execute(tc) for tc in allowed_group)
                    )
                elif allowed_group:
                    exec_results_raw = [await self._executor.execute(allowed_group[0])]
                else:
                    exec_results_raw = []

                # Merge: blocked results in original order, then allowed results
                exec_results: list[ExecutionResult] = []
                allowed_iter = iter(exec_results_raw)
                blocked_map = {id(tc): er for tc, er in authority_blocked}
                for tc in group:
                    if id(tc) in blocked_map:
                        exec_results.append(blocked_map[id(tc)])
                    else:
                        exec_results.append(next(allowed_iter))

                # Process results in original order
                for tc, exec_result in zip(group, exec_results, strict=True):
                    reflection = self._reflector.reflect(exec_result)
                    logger.info(f"Reflection: {reflection.summary}")

                    if exec_result.error or exec_result.denied:
                        consecutive_errors += 1
                    else:
                        consecutive_errors = 0

                    if exec_result.denied:
                        tool_content = json.dumps(
                            {
                                "error": "User denied this tool execution.",
                                "suggestion": (
                                    "Try a different approach or ask the user"
                                    " for guidance."
                                ),
                            }
                        )
                    elif exec_result.error:
                        tool_content = json.dumps({"error": exec_result.error})
                    elif exec_result.result:
                        raw_result = exec_result.result.to_dict()
                        func_name = tc["function"]["name"]
                        raw_result = wrap_tool_result(func_name, raw_result)
                        # Strip base64 images from browser results — they bloat
                        # context for text-only LLMs. The bridge saves screenshots
                        # to disk and returns a path instead.
                        if func_name.startswith("browser_"):
                            _data = raw_result.get("data")
                            if isinstance(_data, dict):
                                _data.pop("imageBase64", None)
                                _data.pop("imageType", None)
                        # PII redaction — non-owner users get PII stripped
                        if _authority != AuthorityLevel.OWNER:
                            from core.pii_guard import redact_pii_in_dict

                            raw_result = redact_pii_in_dict(raw_result)
                        tool_content = json.dumps(raw_result)
                    else:
                        tool_content = json.dumps({"error": "No result returned"})

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": tool_content,
                        }
                    )

        if stagnation_reason:
            reason = stagnation_reason
        else:
            reason = f"safety limit ({step} steps)"
        max_steps_msg = (
            f"Task stopped: {reason} after {step} steps. "
            f"You can continue by sending a follow-up message."
        )
        asyncio.create_task(
            self._store_task_memory(
                goal, "Max steps reached", "incomplete", tool_calls_made
            )
        )

        # Dataset collection for incomplete tasks
        if self._dataset_builder:
            asyncio.create_task(
                self._dataset_builder.record_task(
                    messages=messages,
                    tool_calls_made=tool_calls_made,
                    success=False,
                    duration_seconds=_time.monotonic() - start_time,
                    model_used=last_model_used,
                )
            )

        # Persist to conversation history even on max steps
        append_turn(goal, max_steps_msg)

        return AgentResponse(
            content=max_steps_msg,
            steps_taken=step,
            tool_calls_made=tool_calls_made,
        )

    def _append_conversation_turn(self, user_msg: str, assistant_msg: str) -> None:
        """Store a user/assistant pair in conversation history for context continuity."""
        self._conversation_history.append({"role": "user", "content": user_msg})
        self._conversation_history.append(
            {"role": "assistant", "content": assistant_msg}
        )
        # Trim to keep only the last N messages (user+assistant pairs)
        if len(self._conversation_history) > _MAX_CONVERSATION_HISTORY:
            self._conversation_history = self._conversation_history[
                -_MAX_CONVERSATION_HISTORY:
            ]

    async def _execute_scheduled_task(self, goal: str) -> AgentResponse:
        """Execute a task goal for a scheduled task."""
        return await self.run(goal)

    async def _notify_scheduled_result(
        self, task_name: str, status: str, result: str
    ) -> None:
        """Push scheduled task result to connected channels.

        Gateway mode: broadcast NOTIFICATION event to all connected clients.
        """
        if self._gateway:
            from core.protocol import EventType, event_message

            await self._gateway.broadcast(
                event_message(
                    "",
                    EventType.NOTIFICATION,
                    {
                        "notification_type": "scheduled_result",
                        "task_name": task_name,
                        "status": status,
                        "result": result,
                    },
                ),
                session_id=None,  # broadcast to ALL clients
            )

    async def _auto_retrieve(self, query: str) -> None:
        """Fetch relevant knowledge chunks and recent task memory for the query.

        Runs knowledge search and memory search in parallel for speed.
        """

        async def _search_knowledge() -> list[dict[str, Any]]:
            search_tool = self._registry.get("knowledge_search")
            if search_tool and hasattr(search_tool, "_db") and search_tool._db:
                try:
                    result = await search_tool.execute({"query": query, "limit": 3})
                    if result.success and result.data.get("results"):
                        return result.data["results"]
                except Exception:
                    pass
            return []

        async def _search_memory() -> list[dict[str, Any]]:
            try:
                memories = await self._memory_manager.search_memory(query, limit=3)
                if not memories:
                    memories = await self._memory_manager.get_recent_tasks(limit=5)
                return memories or []
            except Exception:
                return []

        chunks, memories = await asyncio.gather(_search_knowledge(), _search_memory())

        if chunks:
            self._working_memory.add_chunks(chunks)
        if memories:
            memory_chunks = []
            for mem in memories:
                tools = ", ".join(mem.get("tools_used", [])[:5])
                content = (
                    f"Task: {mem['goal']}\n"
                    f"Outcome: {mem['outcome']}\n"
                    f"Summary: {mem['summary'][:300]}\n"
                    f"Tools used: {tools}\n"
                    f"When: {mem.get('created_at', 'unknown')}"
                )
                memory_chunks.append(
                    {
                        "source": "task_memory",
                        "heading": f"Past task: {mem['goal'][:60]}",
                        "content": content,
                    }
                )
            self._working_memory.add_chunks(memory_chunks)

    async def _store_task_memory(
        self,
        goal: str,
        summary: str,
        outcome: str,
        tools_used: list[str],
    ) -> None:
        """Store task completion in long-term memory."""
        try:
            await self._memory_manager.store_task_memory(
                session_id=self._working_memory.session_id,
                goal=goal,
                summary=summary,
                outcome=outcome,
                tools_used=list(set(tools_used)),
            )
        except Exception as e:
            logger.debug(f"Failed to store task memory: {e}")

    # ------------------------------------------------------------------
    # Automatic directive detection
    # ------------------------------------------------------------------

    _DIRECTIVE_CLASSIFY_PROMPT = """\
You are a classifier. Given a user message sent to an AI agent, determine if it \
contains an OWNER DIRECTIVE — a standing instruction, preference, or rule that \
should be remembered across all future interactions.

Examples of directives:
- "Don't ever post on Reddit"
- "Always use Python 3.12"
- "Never spend more than $5 per task"
- "My name is Alex"
- "Use dark mode in all UIs you build"
- "I prefer concise answers"

Examples of NON-directives (regular chat):
- "What's the weather today?"
- "Fix the bug in auth.py"
- "How does the indexer work?"
- "Thanks, that looks good"
- "Run the tests"

Respond with EXACTLY this JSON (no other text):
{"is_directive": true/false, "directive": "...", "key": "..."}

- "is_directive": true only if the message contains a standing instruction/preference
- "directive": the directive rephrased as a clear, concise rule (empty string if not a directive)
- "key": a short kebab-case identifier for the directive (e.g. "no-reddit", "prefer-python312")

User message:
{user_message}"""

    async def _detect_and_store_directive(self, user_message: str) -> None:
        """Classify whether user_message contains a directive and persist it.

        Runs a cheap, fast LLM call in the background. Failures are silently
        logged — this must never block or break the main chat flow.
        """
        try:
            prompt = self._DIRECTIVE_CLASSIFY_PROMPT.format(
                user_message=user_message[:1000]
            )
            response = await self._router.complete(
                messages=[{"role": "user", "content": prompt}],
                task_type="simple",
                temperature=0.0,
                max_tokens=200,
            )
            text = (response.content or "").strip()
            # Parse JSON from the response
            # Handle models that wrap in ```json ... ```
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json.loads(text)

            if not result.get("is_directive"):
                return

            directive_text = result.get("directive", "").strip()
            key = result.get("key", "directive").strip()
            if not directive_text:
                return

            # Persist via knowledge_write tool (already has deps injected)
            write_tool = self._registry.get("knowledge_write")
            if not write_tool:
                logger.debug("knowledge_write tool not available for directive storage")
                return

            await write_tool.execute(
                {
                    "path": f"user/directives/{key}.md",
                    "content": f"## Directive\n\n{directive_text}\n\n"
                    f"## Original message\n\n> {user_message[:500]}\n",
                    "title": directive_text[:100],
                    "tags": "directive,owner,auto-detected",
                    "scope": "user",
                }
            )
            logger.info("Auto-stored owner directive: %s -> %s", key, directive_text)

        except json.JSONDecodeError:
            logger.debug("Directive classifier returned non-JSON: %s", text[:200])
        except Exception as e:
            logger.debug("Directive detection failed (non-fatal): %s", e)
