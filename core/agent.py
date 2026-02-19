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
from core.executor import Executor
from core.indexer import KnowledgeIndexer
from core.memory import MemoryManager, WorkingMemory
from core.planner import build_system_prompt
from core.plugin_loader import PluginLoader
from core.reflector import Reflector
from core.registry import ToolRegistry
from core.router import LLMRouter
from core.skills import SkillManager

logger = logging.getLogger(__name__)


_MAX_CONVERSATION_HISTORY = 20  # Max messages to carry across turns


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

        # Notification callbacks (set by Telegram adapter or other interfaces)
        self._on_task_complete: Callable[..., Any] | None = None
        self._on_error: Callable[..., Any] | None = None

        # Live progress callback (set by CLI for step-by-step visibility)
        self._on_step: Callable[[int, str, str, dict[str, Any]], None] | None = None

        # Conversation history across turns (user + assistant messages only)
        self._conversation_history: list[dict[str, Any]] = []

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

        # --- Parallel block: embedding detection + health check ---
        _status("Checking LLM providers")

        async def _detect_embeddings() -> tuple[str | None, int | None]:
            try:
                kc = self._config.knowledge
                if kc.embedding_provider == "openrouter":
                    primary_model = kc.embedding_openrouter_model
                    fallback_model = None
                else:
                    primary_model = kc.embedding_model
                    fallback_model = kc.embedding_fallback
                model, dims = await self._embedder.detect_model(
                    primary=primary_model,
                    fallback=fallback_model,
                )
                return model, dims
            except Exception as e:
                logger.warning(f"Embedding model not available: {e}")
                return None, None

        async def _run_health_check() -> dict[str, bool]:
            return await self._router.health_check()

        (embed_model, embed_dims), health = await asyncio.gather(
            _detect_embeddings(),
            _run_health_check(),
        )

        # Apply embedding results
        if embed_model and embed_dims:
            self._indexer.set_embedding_model(embed_model)
            try:
                await self._db.create_vec_table(embed_dims)
            except Exception as e:
                logger.warning(f"Failed to create vec table: {e}")

        # Store health results for the caller
        self._provider_health = health
        enabled = [k for k, v in health.items() if v]
        if not enabled:
            logger.warning("No LLM providers are reachable!")
        else:
            logger.info(f"Active LLM providers: {', '.join(enabled)}")

        # --- End parallel block ---

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
                    logger.warning(f"Failed to load plugin {result.name}: {result.error}")

        # Inject self-dev tool dependencies
        self._inject_self_dev_deps()

        # Create browser manager (if enabled) — lazy init, Chrome opens on first use
        if self._config.browser.enabled:
            _status("Preparing browser")
            try:
                from core.browser_manager import BrowserManager

                self._browser_manager = BrowserManager.from_config(self._config.browser)
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

        # Start scheduler (if enabled)
        if self._config.scheduler.enabled:
            _status("Starting scheduler")
            try:
                from core.scheduler import TaskScheduler

                self._scheduler = TaskScheduler(
                    db=self._db,
                    task_executor=self._execute_scheduled_task,
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

                # Create document vector table if embeddings available
                if embed_model and embed_dims:
                    try:
                        await self._db.create_document_vec_table(embed_dims)
                    except Exception as e:
                        logger.debug(f"Document vec table: {e}")

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
            except Exception as e:
                logger.warning(f"Goal system setup failed: {e}")

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
            except Exception as e:
                logger.warning(f"Knowledge indexing failed: {e}")

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
        """Inject goal manager into goal tools."""
        for tool_name in ("goal_create", "goal_status", "goal_manage"):
            tool = self._registry.get(tool_name)
            if tool and self._goal_manager:
                tool._goal_manager = self._goal_manager

    def _inject_identity_deps(self) -> None:
        """Inject identity manager into identity tools."""
        for tool_name in ("identity_status", "identity_update", "identity_reflect"):
            tool = self._registry.get(tool_name)
            if tool and self._identity_manager:
                tool._identity_manager = self._identity_manager

    def set_approval_callback(self, callback: Callable[[str, str, dict[str, Any]], bool]) -> None:
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
        """

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
            )
            session.touch()
            return response
        finally:
            # Restore previous callbacks
            self._executor._approval_callback = prev_approval
            self._on_step = prev_step

    async def run(self, goal: str) -> AgentResponse:
        """Execute the plan-execute-reflect loop for a user goal.

        Legacy direct mode — uses internal conversation history.
        For gateway mode, use run_session() instead.
        """
        return await self._run_with_history(
            goal,
            self._conversation_history,
            self._append_conversation_turn,
        )

    async def _run_with_history(
        self,
        goal: str,
        conversation_history: list[dict[str, Any]],
        append_turn: Callable[[str, str], None],
    ) -> AgentResponse:
        """Core plan-execute-reflect loop, parameterized on history source."""
        self._router.cost_tracker.reset_task()
        self._working_memory.clear()

        import time as _time

        tool_calls_made: list[str] = []
        step = 0
        hard_limit = self._config.max_steps or 500
        max_time = self._config.max_time_seconds
        start_time = _time.monotonic()

        # Stagnation detection: stop when the agent is stuck, not on a clock.
        consecutive_errors = 0
        recent_calls: list[str] = []
        _STAGNATION_WINDOW = 8
        _MAX_CONSECUTIVE_ERRORS = 5

        # Auto-retrieve relevant knowledge
        try:
            await self._auto_retrieve(goal)
        except Exception:
            pass  # Non-fatal

        # Build system prompt with XML-structured sections, skills, and knowledge
        knowledge_context = self._working_memory.format_context()
        available_skills = self._skill_manager.format_available_skills()

        # Check for active goal context
        goal_context = ""
        if self._goal_manager:
            try:
                # Try to find active goal (session-scoped or global)
                active_goal = await self._goal_manager.list_goals(status="active", limit=1)
                if active_goal:
                    goal_context = await self._goal_manager.build_goal_context(
                        active_goal[0].goal_id
                    )
            except Exception:
                pass

        # Build identity context if available
        identity_context = ""
        if self._identity_manager:
            try:
                identity_context = await self._identity_manager.build_identity_context()
            except Exception:
                pass

        system_content = build_system_prompt(
            permission_mode=self._config.permission_mode,
            browser_enabled=self._config.browser.enabled,
            scheduler_enabled=self._config.scheduler.enabled,
            goals_enabled=self._config.goals.enabled,
            knowledge_context=knowledge_context,
            available_skills=available_skills,
            goal_context=goal_context,
            identity_context=identity_context,
        )

        # Build conversation for LLM: prior turns + current user message
        messages: list[dict[str, Any]] = list(conversation_history)
        messages.append({"role": "user", "content": goal})

        stagnation_reason = ""
        while step < hard_limit:
            if max_time and (_time.monotonic() - start_time) > max_time:
                stagnation_reason = f"time limit reached ({int(_time.monotonic() - start_time)}s)"
                logger.info("Time limit reached")
                break
            if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                stagnation_reason = f"{consecutive_errors} consecutive errors"
                logger.info("Stagnation: %s", stagnation_reason)
                break
            if len(recent_calls) >= _STAGNATION_WINDOW:
                unique = set(recent_calls[-_STAGNATION_WINDOW:])
                if len(unique) == 1:
                    stagnation_reason = f"repeating {next(iter(unique))} {_STAGNATION_WINDOW} times"
                    logger.info("Stagnation: %s", stagnation_reason)
                    break
            step += 1
            logger.info("Step %d", step)

            # === PLAN ===
            try:
                response = await self._router.complete(
                    messages=[{"role": "system", "content": system_content}] + messages,
                    task_type="planning",
                    tools=self._registry.list_tools(),
                    temperature=0.2,
                )
            except Exception as e:
                logger.error(f"Planning LLM call failed: {e}")
                return AgentResponse(
                    content=f"I encountered an error while thinking: {e}",
                    steps_taken=step,
                    tool_calls_made=tool_calls_made,
                )

            # Check if LLM responded with text (no tool calls) = task complete
            if not response.tool_calls:
                final_content = response.content or "Task complete."

                # Store task memory
                await self._store_task_memory(goal, final_content, "completed", tool_calls_made)

                # Identity reflection after task completion
                if self._identity_manager:
                    try:
                        await self._identity_manager.reflect_on_task(
                            goal=goal,
                            outcome=final_content[:200],
                            tools_used=list(set(tool_calls_made)),
                        )
                    except Exception:
                        pass

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

            # === EXECUTE each tool call ===
            for tool_call in response.tool_calls:
                func_name = tool_call["function"]["name"]
                tool_calls_made.append(func_name)
                recent_calls.append(func_name)

                # Parse params for progress display
                try:
                    _raw = tool_call["function"].get("arguments", "{}")
                    _params = json.loads(_raw) if isinstance(_raw, str) else _raw
                except Exception:
                    _params = {}

                if self._on_step:
                    try:
                        result = self._on_step(step, func_name, response.content or "", _params)
                        if inspect.isawaitable(result):
                            await result
                    except Exception:
                        pass

                exec_result = await self._executor.execute(tool_call)

                # === REFLECT ===
                reflection = self._reflector.reflect(exec_result)
                logger.info(f"Reflection: {reflection.summary}")

                # Track consecutive errors for stagnation detection
                if exec_result.error or exec_result.denied:
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0

                # Build tool result message for conversation history
                if exec_result.denied:
                    tool_content = json.dumps(
                        {
                            "error": "User denied this tool execution.",
                            "suggestion": (
                                "Try a different approach or ask the user for guidance."
                            ),
                        }
                    )
                elif exec_result.error:
                    tool_content = json.dumps({"error": exec_result.error})
                elif exec_result.result:
                    tool_content = json.dumps(exec_result.result.to_dict())
                else:
                    tool_content = json.dumps({"error": "No result returned"})

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
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
        await self._store_task_memory(goal, "Max steps reached", "incomplete", tool_calls_made)

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
        self._conversation_history.append({"role": "assistant", "content": assistant_msg})
        # Trim to keep only the last N messages (user+assistant pairs)
        if len(self._conversation_history) > _MAX_CONVERSATION_HISTORY:
            self._conversation_history = self._conversation_history[-_MAX_CONVERSATION_HISTORY:]

    async def _execute_scheduled_task(self, goal: str) -> AgentResponse:
        """Execute a task goal for a scheduled task."""
        return await self.run(goal)

    async def _auto_retrieve(self, query: str) -> None:
        """Fetch relevant knowledge chunks and recent task memory for the query."""
        # Search knowledge base (markdown files)
        search_tool = self._registry.get("knowledge_search")
        if search_tool and hasattr(search_tool, "_db") and search_tool._db:
            try:
                result = await search_tool.execute({"query": query, "limit": 3})
                if result.success and result.data.get("results"):
                    self._working_memory.add_chunks(result.data["results"])
            except Exception:
                pass

        # Search task memory (past sessions)
        try:
            memories = await self._memory_manager.search_memory(query, limit=3)
            if not memories:
                memories = await self._memory_manager.get_recent_tasks(limit=5)
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
        except Exception:
            pass

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
