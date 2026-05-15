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
import base64
import inspect
import json
import logging
import sys
import time as _time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from core.session import Session


# Tracks whether the current asyncio task is already inside an agent
# loop. Re-entrant calls (e.g. ``run_isolated`` invoked by the in-process
# ``delegate`` tool from inside a tool execution) must NOT try to
# re-acquire AGENT_LOOP — they already hold it transitively. Without
# this, the second acquire deadlocks against the first. Contextvars
# scope to the current asyncio task and propagate to awaited inner
# coroutines but not to ``asyncio.create_task`` children unless
# explicitly copied — exactly the semantics we want.
_in_agent_loop: ContextVar[bool] = ContextVar("_in_agent_loop", default=False)

# True iff the current asyncio task is executing inside a scheduled task
# (set by ``_execute_scheduled_task``). Used by ``tools/scheduling/list_tool.py``
# and ``tools/scheduling/schedule_tool.py`` to refuse cross-schedule
# mutation: one schedule must never enable/disable/stop/delete/create
# another. The scheduler queues them — they don't get to meddle. On
# 2026-05-15 a Daily Review schedule autonomously disabled three other
# schedules right after we updated their task_goals; that's the bug
# this guards against. Read-only ``list`` / ``history`` actions stay
# allowed because legitimate dedupe checks need them.
_in_scheduled_task: ContextVar[bool] = ContextVar("_in_scheduled_task", default=False)


def is_in_scheduled_task() -> bool:
    """Public helper for tools to check whether they're being called
    from inside a scheduled-task run loop. Used to gate cross-schedule
    mutation."""
    return _in_scheduled_task.get()


class StatusCallback(Protocol):
    """Callback to report initialization progress."""

    def __call__(self, message: str) -> None: ...


from core.browser_executor import STATE_CHANGING_TOOLS, BrowserExecutionState
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
        "organization_status",
        "desktop_screenshot",
        "desktop_cursor",
        "desktop_file",
        "payment_request",
        "prospect_status",
        "prospect_evaluate",
        "web_search",
        "web_extract",
        "context_query",
        "context_slice",
        "context_index",
        "context_transform",
    }
)


_KEEP_RECENT_SCREENSHOTS = 3  # Keep last N screenshots as actual images
_MAX_ELEMENTS_CHARS = 4000  # Truncate pseudo-HTML element lists beyond this
_MAX_CONTEXT_CHARS = 800_000  # ~200K tokens — aggressively compress above this
_KEEP_RECENT_TOOL_RESULTS = 6  # Keep last N tool results at full size
_MAX_OLD_TOOL_RESULT_CHARS = 1500  # Truncate older tool results to this length


def _compress_browser_context(messages: list[dict[str, Any]]) -> None:
    """Compress browser-injected content to prevent context bloat.

    1. Replace old screenshot images with [screenshot] placeholder (keep last N).
    2. Truncate long element text in all non-recent browser messages.
    3. If total estimated size still exceeds _MAX_CONTEXT_CHARS, aggressively
       strip ALL images and truncate all element text.
    4. Always truncate old tool results (role=tool) beyond the last N — these
       are the primary driver of unbounded context growth (shell output, web
       scrapes, knowledge reads, etc.).
    """
    # --- Phase 1: Identify multimodal messages (screenshots + elements) ---
    screenshot_indices = [
        i
        for i, m in enumerate(messages)
        if isinstance(m.get("content"), list)
        and any(
            p.get("type") == "image_url" for p in m["content"] if isinstance(p, dict)
        )
    ]

    # Replace old screenshots with placeholder, truncate old element text
    if len(screenshot_indices) > _KEEP_RECENT_SCREENSHOTS:
        for i in screenshot_indices[:-_KEEP_RECENT_SCREENSHOTS]:
            messages[i] = _compress_multimodal_msg(messages[i], strip_images=True)

    # --- Phase 2: Estimate total context size and compress further if needed ---
    total_chars = _estimate_context_chars(messages)
    if total_chars > _MAX_CONTEXT_CHARS:
        logger.warning(
            "Context too large (~%dK chars). Stripping ALL screenshots + truncating elements.",
            total_chars // 1000,
        )
        # Strip ALL images, truncate all element text
        for i in screenshot_indices:
            messages[i] = _compress_multimodal_msg(messages[i], strip_images=True)
        # Also truncate any long text-only browser messages (element fallbacks)
        for i, m in enumerate(messages):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                text = m["content"]
                if len(text) > 2000 and "Page after browser_" in text:
                    lines = text.split("\n")
                    messages[i] = {
                        **m,
                        "content": "\n".join(lines[:5]) + "\n[elements truncated]",
                    }

    # --- Phase 3: Proactively trim old tool results ---
    # Shell outputs, web scrapes, knowledge reads etc. accumulate as role=tool
    # messages and are the primary driver of context overflow.  Keep the last
    # _KEEP_RECENT_TOOL_RESULTS at full size; truncate older ones.
    tool_indices = [
        i
        for i, m in enumerate(messages)
        if m.get("role") == "tool" and isinstance(m.get("content"), str)
    ]
    if len(tool_indices) > _KEEP_RECENT_TOOL_RESULTS:
        for i in tool_indices[:-_KEEP_RECENT_TOOL_RESULTS]:
            content = messages[i]["content"]
            if len(content) > _MAX_OLD_TOOL_RESULT_CHARS:
                messages[i] = {
                    **messages[i],
                    "content": content[:_MAX_OLD_TOOL_RESULT_CHARS]
                    + "\n[truncated — old tool result]",
                }


def _compress_multimodal_msg(
    msg: dict[str, Any], *, strip_images: bool
) -> dict[str, Any]:
    """Compress a single multimodal message."""
    new_parts: list[dict[str, Any]] = []
    for part in msg["content"]:
        if not isinstance(part, dict):
            new_parts.append(part)
            continue
        if part.get("type") == "image_url" and strip_images:
            new_parts.append({"type": "text", "text": "[screenshot]"})
        elif part.get("type") == "text":
            text = part.get("text", "")
            if len(text) > 500:
                lines = text.split("\n")
                new_parts.append(
                    {
                        "type": "text",
                        "text": "\n".join(lines[:5]) + "\n[elements truncated]",
                    }
                )
            else:
                new_parts.append(part)
        else:
            new_parts.append(part)
    return {**msg, "content": new_parts}


_CONTEXT_OVERFLOW_PHRASES = (
    "prompt is too long",
    "context length",
    "context_length_exceeded",
    "maximum context",
    "tokens > ",
    "token limit",
    "too many tokens",
    "input is too long",
    "exceeds the maximum",
)


def _is_context_overflow_error(exc: Exception) -> bool:
    """Return True when the LLM refused the call due to context length."""
    msg = str(exc).lower()
    return any(phrase in msg for phrase in _CONTEXT_OVERFLOW_PHRASES)


# How many recent messages to keep on emergency overflow trim
_OVERFLOW_KEEP_RECENT = 20


def _emergency_trim_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggressively trim conversation history on context overflow.

    Strategy (applied in order until the list fits):
    1. Strip ALL images from every message.
    2. Truncate every tool result to 500 chars.
    3. Keep only the last _OVERFLOW_KEEP_RECENT messages, prepending a
       summary placeholder so the agent knows history was dropped.
    """
    # Step 1: strip all images
    trimmed: list[dict[str, Any]] = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            text_parts = [
                p for p in content if isinstance(p, dict) and p.get("type") == "text"
            ]
            if text_parts:
                m = {**m, "content": " ".join(p.get("text", "") for p in text_parts)}
            else:
                m = {**m, "content": "[image removed — context overflow trim]"}
        trimmed.append(m)

    # Step 2: truncate long tool results
    _TOOL_RESULT_MAX = 500
    for i, m in enumerate(trimmed):
        if m.get("role") == "tool" and isinstance(m.get("content"), str):
            if len(m["content"]) > _TOOL_RESULT_MAX:
                trimmed[i] = {
                    **m,
                    "content": m["content"][:_TOOL_RESULT_MAX]
                    + "\n[truncated — context overflow]",
                }

    # Step 3: drop old messages, keep only recent
    if len(trimmed) > _OVERFLOW_KEEP_RECENT:
        dropped = len(trimmed) - _OVERFLOW_KEEP_RECENT
        summary_msg: dict[str, Any] = {
            "role": "user",
            "content": (
                f"[{dropped} earlier messages were dropped to fit the context window. "
                "Continue with the current task using the recent context below.]"
            ),
        }
        trimmed = [summary_msg] + trimmed[-_OVERFLOW_KEEP_RECENT:]
        # The blind cut above can leave orphaned tool messages: a
        # role="tool" whose parent assistant turn (with the matching
        # tool_calls block) was in the dropped middle. Codex's strict
        # validator rejects that with 400 "No tool call found for
        # function call output". Run the pairing fixer.
        from core.context_compressor import _fix_orphaned_tool_calls

        trimmed = _fix_orphaned_tool_calls(trimmed)

    logger.warning(
        "Emergency context trim applied: %d messages remaining after overflow",
        len(trimmed),
    )
    return trimmed


def _estimate_context_chars(messages: list[dict[str, Any]]) -> int:
    """Rough estimate of total message content in characters."""
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        total += len(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        total += len(url)  # base64 data URI
    return total


def _extract_path(tc: dict[str, Any]) -> str | None:
    """Extract file path from a tool call's arguments, if present."""
    try:
        args = tc.get("function", {}).get("arguments", "{}")
        params = json.loads(args) if isinstance(args, str) else args
        return params.get("path", None)
    except Exception:
        return None


# Tool-name → capability label, used by the ego layer to assign per-task
# outcomes to a coarse capability bucket. Unknown tools fall through to the
# tool's own name; tasks that used no recognizable tool record nothing.
_TOOL_CAPABILITY_MAP: dict[str, str] = {
    "browser_navigate": "web_browsing",
    "browser_click": "web_browsing",
    "browser_extract": "web_browsing",
    "browser_type": "web_browsing",
    "polymarket_bet": "polymarket_trading",
    "polymarket_scan": "polymarket_trading",
    "pump_livestream": "pumpfun_livestream",
    "pump_say": "pumpfun_livestream",
    "pump_chat": "pumpfun_livestream",
    "knowledge_write": "knowledge_management",
    "knowledge_search": "knowledge_management",
    "code_edit": "code_editing",
    "code_write": "code_editing",
    "shell_exec": "shell_execution",
    "send_email": "email_communication",
    "twitter_post": "x_engagement",
    "twitter_reply": "x_engagement",
}


def _capability_from_tools(tools_used: list[str]) -> str:
    """Pick the most representative capability for a task based on tools used.

    Returns the most-frequent mapped capability, or the most-frequent raw
    tool name if none mapped, or empty string if no tools were used.
    """
    if not tools_used:
        return ""
    counts: dict[str, int] = {}
    for t in tools_used:
        cap = _TOOL_CAPABILITY_MAP.get(t, t)
        counts[cap] = counts.get(cap, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _paths_conflict(paths: list[str | None], new_path: str | None) -> bool:
    """Check if a new path conflicts with any existing paths.

    Two write operations on the same file or parent directory conflict.
    """
    if new_path is None:
        return False
    for p in paths:
        if p is None:
            continue
        # Same file or one is parent of the other
        if (
            p == new_path
            or new_path.startswith(p + "/")
            or p.startswith(new_path + "/")
        ):
            return True
    return False


# Tools that write files — need path-aware conflict checking
_PATH_WRITE_TOOLS = frozenset(
    {
        "file_write",
        "file_patch",
        "file_delete",
        "file_move",
    }
)


def _group_tool_calls(tool_calls: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group tool calls into parallelizable batches.

    Consecutive parallel-safe tools form one group.
    Any non-safe tool gets its own single-item group (sequential barrier).
    Path-aware: write tools targeting the same path run sequentially.
    """
    groups: list[list[dict[str, Any]]] = []
    current_safe: list[dict[str, Any]] = []
    current_paths: list[str | None] = []

    for tc in tool_calls:
        name = tc.get("function", {}).get("name", "")
        if name in _PARALLEL_SAFE_TOOLS:
            current_safe.append(tc)
        elif name in _PATH_WRITE_TOOLS:
            # Write tool — check for path conflicts with current batch
            path = _extract_path(tc)
            if current_safe and not _paths_conflict(current_paths, path):
                # No conflict — can run in parallel with reads
                current_safe.append(tc)
                current_paths.append(path)
            else:
                # Conflict or no batch — sequential barrier
                if current_safe:
                    groups.append(current_safe)
                    current_safe = []
                    current_paths = []
                groups.append([tc])
        else:
            if current_safe:
                groups.append(current_safe)
                current_safe = []
                current_paths = []
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


class _FilteredRegistry:
    """Read-only registry view that hides specific tool names.

    Used by ``Agent.run_isolated`` so an in-process subagent cannot see
    or invoke recursive-spawn / long-lived-state tools (delegate, swarm_*,
    kid_*, org_*, schedule_task, agent_connect/message/disconnect).
    Delegates everything else to the underlying registry by reference —
    no copies, no mutation.
    """

    def __init__(self, inner: Any, excluded: set[str]) -> None:
        self._inner = inner
        self._excluded = excluded
        self._project_root = getattr(inner, "_project_root", None)

    def get(self, name: str) -> Any:
        if name in self._excluded:
            return None
        return self._inner.get(name)

    def get_tools_for_context(
        self,
        task_groups: set[str],
        activated_names: set[str] | None = None,
    ) -> list[Any]:
        tools = self._inner.get_tools_for_context(task_groups, activated_names)
        return [t for t in tools if t.name not in self._excluded]

    def get_core_tools(self) -> list[Any]:
        return [t for t in self._inner.get_core_tools() if t.name not in self._excluded]

    def get_deferred_catalog(self) -> list[dict[str, str]]:
        return [
            entry
            for entry in self._inner.get_deferred_catalog()
            if entry["name"] not in self._excluded
        ]

    def discover_tools(self, query: str) -> list[Any]:
        return [
            t for t in self._inner.discover_tools(query) if t.name not in self._excluded
        ]

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            schema
            for schema in self._inner.list_tools()
            if schema.get("function", {}).get("name") not in self._excluded
        ]

    def list_tool_summaries(self) -> list[dict[str, str]]:
        return [
            entry
            for entry in self._inner.list_tool_summaries()
            if entry["name"] not in self._excluded
        ]

    def all_tools(self) -> list[Any]:
        return [t for t in self._inner.all_tools() if t.name not in self._excluded]

    def __getattr__(self, name: str) -> Any:
        # Fallback for any registry method we didn't explicitly proxy.
        return getattr(self._inner, name)


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

        # Skills system — in cloud mode app code is at /app, user data at /data
        import os as _os

        _app_skills = Path("/app/skills")
        if _os.environ.get("ELOPHANTO_CLOUD") == "1" and _app_skills.exists():
            skills_dir = _app_skills
        else:
            skills_dir = config.project_root / "skills"
        self._skill_manager = SkillManager(skills_dir)

        # Context compression circuit breaker
        from core.context_compressor import CompactionCircuitBreaker

        self._compaction_breaker = CompactionCircuitBreaker()

        # Action queue — legacy serialization layer. Kept for backward
        # compatibility but no longer wraps run_session (Phase B of
        # docs/74-CONCURRENCY-MIGRATION.md routes operator chat through
        # ``self._resources`` instead). The ``TaskPriority`` enum it
        # ships is still the priority vocabulary the resource manager
        # uses.
        from core.action_queue import ActionQueue

        self._action_queue = ActionQueue()

        # Resource-typed concurrency manager — shared with the scheduler
        # if scheduler is enabled, otherwise stands alone. Routes operator
        # chat, mind cycles, heartbeat, and scheduled tasks through
        # typed semaphores (BROWSER=1, DESKTOP=1, VAULT_WRITE=1,
        # LLM_BURST=4, DEFAULT=3) with priority-aware waiter ordering
        # so USER messages jump ahead of MIND / SCHEDULED / GOAL waiters
        # at the next free slot. See docs/74-CONCURRENCY-MIGRATION.md.
        from core.task_resources import TaskResourceManager

        self._resources: TaskResourceManager = TaskResourceManager.from_defaults(
            global_concurrency=self._config.scheduler.max_concurrent_tasks,
            llm_burst=self._config.scheduler.llm_burst_capacity,
        )

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
        self._context_store: Any = None  # ContextStore (RLM Phase 2)
        self._goal_manager: Any = None  # GoalManager, set during initialize
        self._identity_manager: Any = None  # IdentityManager, set during initialize
        self._ego_manager: Any = None  # EgoManager, set during initialize
        self._affect_manager: Any = None  # AffectManager, set during initialize
        self._payments_manager: Any = None  # PaymentsManager, set during initialize
        self._email_config: Any = None  # EmailConfig, set during initialize
        self._email_monitor: Any = None  # EmailMonitor, set during initialize
        self._mcp_manager: Any = None  # MCPClientManager, set during initialize
        self._dataset_builder: Any = None  # DatasetBuilder, set during initialize
        self._goal_runner: Any = None  # GoalRunner, set during initialize
        self._swarm_manager: Any = None  # SwarmManager, set during initialize
        self._organization_manager: Any = (
            None  # OrganizationManager, set during initialize
        )
        self._kid_manager: Any = None  # KidManager, set during initialize
        # Agent-to-agent identity layer. Auto-loaded (or generated) on
        # initialize() — existing agents upgrade silently the first time
        # they boot after this lands.
        self._agent_identity: Any = None  # core.agent_identity.AgentIdentityKey
        self._trust_ledger: Any = None  # core.trust_ledger.TrustLedger
        self._peer_manager: Any = None  # core.peer_manager.PeerManager
        # Decentralized libp2p transport. Optional — only spawned when
        # config.peers.enabled is True. Holds the PeerID after host_open
        # so other subsystems (agent_discover, agent_connect) can reuse
        # the open sidecar without respawning.
        self._p2p_sidecar: Any = None  # core.peer_p2p.P2PSidecar
        self._p2p_peer_id: str = ""
        self._p2p_listener: Any = None  # core.peer_p2p_listener.IncomingStreamListener
        self._parent_adapter: Any = None  # ParentChannelAdapter, set during initialize
        self._autonomous_mind: Any = None  # AutonomousMind, set during initialize
        self._heartbeat_engine: Any = None  # HeartbeatEngine, set during initialize
        self._user_profile_manager: Any = (
            None  # UserProfileManager, set during initialize
        )
        self._gateway: Any = None  # Gateway instance, set by gateway_cmd/chat_cmd
        self._learner: Any = None  # LessonExtractor, set during initialize

        # Notification callbacks (set by Telegram adapter or other interfaces)
        self._on_task_complete: Callable[..., Any] | None = None
        self._on_error: Callable[..., Any] | None = None

        # Live progress callback (set by CLI for step-by-step visibility)
        self._on_step: Callable[[int, str, str, dict[str, Any]], None] | None = None

        # Conversation history across turns (user + assistant messages only)
        self._conversation_history: list[dict[str, Any]] = []

        # Deferred tool loading: tools activated via tool_discover this session
        self._activated_tools: set[str] = set()

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
        # Sync health into router so godmode racing can see healthy providers
        self._router._provider_health.update(health)
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
                # Memory vec table for semantic task memory search
                try:
                    await self._db.create_memory_vec_table(dims)
                    self._memory_manager.set_embedder(self._embedder, model, dims)
                except Exception as e:
                    logger.debug(f"Memory vec table setup failed (non-fatal): {e}")
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

        # Initialize ContextStore (RLM Phase 2 — context-as-variable)
        from core.context_store import ContextStore

        self._context_store = ContextStore(db=self._db, embedder=self._embedder)
        self._inject_context_deps()

        # Initialize lesson extractor (fire-and-forget learning after each task)
        if getattr(self._config, "learner", None) and self._config.learner.enabled:
            try:
                from core.learner import LessonExtractor

                knowledge_dir = Path(self._config.knowledge.knowledge_dir)
                if not knowledge_dir.is_absolute():
                    knowledge_dir = self._config.project_root / knowledge_dir
                self._learner = LessonExtractor(
                    router=self._router,
                    knowledge_dir=knowledge_dir,
                    indexer=self._indexer,
                    enabled=True,
                )
                # Wire instinct store into learner
                try:
                    from core.instinct import InstinctStore, get_project_hash

                    data_dir = self._config.project_root / "data"
                    proj_hash = get_project_hash(self._config.project_root)
                    self._learner._instinct_store = InstinctStore(
                        data_dir=data_dir, project_hash=proj_hash
                    )
                    logger.info("Instinct store ready (project=%s)", proj_hash)
                except Exception as e:
                    logger.debug("Instinct store setup failed: %s", e)
                self._inject_learner_deps()
                logger.info("Lesson extractor ready")
            except Exception as e:
                logger.warning(f"Lesson extractor setup failed: {e}")

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
                # Separate field for the Node bridge's vision (DOM
                # annotation) — bridge can't talk to Codex, so this is
                # OpenRouter-only. Empty = bridge runs vision-less.
                self._browser_manager.bridge_vision_model = (
                    self._config.browser.bridge_vision_model
                )

                # Wire proxy routing — credentials live directly in
                # config.yaml under the proxy section, same shape as
                # every other API key (llm.providers.*.api_key etc.).
                # Browser is the only group that routes through the
                # proxy in v1 (LLM / API calls stay direct — see
                # ProxyConfig docstring).
                proxy_cfg = self._config.proxy
                if proxy_cfg.enabled and proxy_cfg.host and proxy_cfg.port:
                    self._browser_manager.proxy_server = proxy_cfg.proxy_url()
                    self._browser_manager.proxy_username = proxy_cfg.username
                    self._browser_manager.proxy_password = proxy_cfg.password
                    self._browser_manager.proxy_bypass = list(proxy_cfg.bypass)
                    logger.info(
                        "Browser proxy enabled: %s (creds=%s)",
                        self._browser_manager.proxy_server,
                        (
                            "set"
                            if proxy_cfg.username and proxy_cfg.password
                            else "anonymous"
                        ),
                    )

                logger.info(
                    "Browser configured (mode=%s) — will launch on first use",
                    self._browser_manager.mode,
                )
            except Exception as e:
                logger.warning(f"Browser setup failed: {e}")

        # Inject browser interface into browser tools
        self._inject_browser_deps()

        # Create desktop controller (if enabled)
        self._desktop_controller = None
        if self._config.desktop.enabled:
            _status("Preparing desktop controller")
            try:
                if self._config.desktop.mode == "local":
                    from core.desktop_controller import LocalDesktopController

                    self._desktop_controller = LocalDesktopController()
                    logger.info("Desktop controller configured in local mode")
                elif self._config.desktop.vm_ip:
                    from core.desktop_controller import DesktopController

                    self._desktop_controller = DesktopController(
                        vm_ip=self._config.desktop.vm_ip,
                        server_port=self._config.desktop.server_port,
                    )
                    logger.info(
                        "Desktop controller configured for %s:%d",
                        self._config.desktop.vm_ip,
                        self._config.desktop.server_port,
                    )
            except Exception as e:
                logger.warning(f"Desktop controller setup failed: {e}")

        # Inject desktop controller into desktop tools
        self._inject_desktop_deps()

        # Inject vault into vault tool (if vault was unlocked)
        self._inject_vault_deps()

        # Inject vault + identity into TOTP tools
        self._inject_totp_deps()

        # Start scheduler (if enabled)
        if self._config.scheduler.enabled:
            _status("Starting scheduler")
            try:
                from core.scheduler import TaskScheduler

                # Reuse the agent-wide resource manager constructed in
                # __init__ — same semaphores back operator chat,
                # autonomous mind, heartbeat, and scheduled tasks, so
                # priority-aware contention is unified.
                self._scheduler = TaskScheduler(
                    db=self._db,
                    task_executor=self._execute_scheduled_task,
                    result_notifier=self._notify_scheduled_result,
                    resource_manager=self._resources,
                    queue_depth_cap=self._config.scheduler.queue_depth_cap,
                    registry=self._registry,
                )
                await self._scheduler.start()
            except Exception as e:
                logger.warning(f"Scheduler failed to start: {e}")

        # Inject scheduler into schedule tools
        self._inject_scheduler_deps()

        # Paid jobs from elophanto.com (job_verify, job_record).
        # Injection is idempotent — config + db are stable; jobs
        # subsystem also works fine when jobs.enabled is False
        # (job_verify just returns valid=false with a hint).
        self._inject_jobs_deps()

        # Discover skills and inject into skill tools
        _status("Loading skills")
        self._skill_manager.discover()
        self._inject_skill_deps()

        # Wire the delegate tool with a back-reference to the agent so it
        # can call run_isolated. Self-reference is intentional: the tool
        # spawns sub-tasks of THIS agent (no separate identity), unlike
        # kid/org/swarm tiers which create new identities or processes.
        delegate_tool = self._registry.get("delegate")
        if delegate_tool is not None:
            delegate_tool._agent = self

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

        # Initialize heartbeat engine
        if self._config.heartbeat.enabled:
            _status("Preparing heartbeat engine")
            try:
                from core.heartbeat import HeartbeatEngine

                self._heartbeat_engine = HeartbeatEngine(
                    agent=self,
                    gateway=self._gateway,
                    config=self._config.heartbeat,
                    project_root=self._config.project_root,
                )
                # Link to gateway for webhook wake triggers
                if self._gateway:
                    self._gateway._heartbeat_engine = self._heartbeat_engine
                logger.info(
                    "Heartbeat engine ready (checking %s every %ds)",
                    self._config.heartbeat.file_path,
                    self._config.heartbeat.check_interval_seconds,
                )
            except Exception as e:
                logger.warning(f"Heartbeat engine setup failed: {e}")

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

            # Ego sits next to identity: identity is descriptive, ego evaluative.
            try:
                from core.ego import EgoManager

                self._ego_manager = EgoManager(
                    db=self._db,
                    router=self._router,
                    config=self._config.identity,
                )
                await self._ego_manager.load_or_create()
                logger.info("Ego system ready")
            except Exception as e:
                logger.warning(f"Ego system setup failed: {e}")

            # Affect — state-level emotion, sister to ego (trait-level).
            # Decays toward zero on the order of minutes-to-hours; colors
            # tone of the next response without changing capability.
            # See docs/69-AFFECT.md.
            try:
                from core.affect import AffectManager

                self._affect_manager = AffectManager(
                    db=self._db, config=self._config.identity
                )
                await self._affect_manager.load_or_create()
                # One-way wire: ego writes to affect, never the reverse.
                if self._ego_manager is not None:
                    self._ego_manager._affect = self._affect_manager
                # Executor fires mild anxiety on tool failures.
                if self._executor is not None:
                    self._executor._affect_manager = self._affect_manager
                # Router applies affect-based temperature bias.
                if self._router is not None:
                    self._router._affect_manager = self._affect_manager
                # affect_record_event tool — agent fires its own signals
                # from content it just read (DMs, replies, vision text).
                _affect_tool = self._registry.get("affect_record_event")
                if _affect_tool is not None:
                    _affect_tool._affect_manager = self._affect_manager
                logger.info("Affect system ready")
            except Exception as e:
                logger.warning(f"Affect system setup failed: {e}")

        # Initialize user modeling
        if self._config.identity.enabled:
            try:
                from core.user_model import UserProfileManager

                self._user_profile_manager = UserProfileManager(
                    db=self._db, router=self._router
                )
                self._inject_user_profile_deps()
                logger.info("User profile system ready")
            except Exception as e:
                logger.warning(f"User profile setup failed: {e}")

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

        # Prospecting tools (always available — only need DB)
        self._inject_prospecting_deps()

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
                        data_dir=self._config.project_root
                        / self._config.storage.data_dir,
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
                self._swarm_manager._skill_manager = self._skill_manager
                self._swarm_manager._router = self._router
                self._inject_swarm_deps()
                logger.info("Swarm system ready")
            except Exception as e:
                logger.warning(f"Swarm system setup failed: {e}")

        # Initialize agent organization (persistent specialist children)
        if self._config.organization.enabled:
            _status("Preparing organization")
            try:
                from core.organization import OrganizationManager

                self._organization_manager = OrganizationManager(
                    db=self._db,
                    config=self._config.organization,
                    master_config=self._config,
                    gateway=self._gateway,
                )
                await self._organization_manager.start()
                self._inject_organization_deps()
                logger.info("Organization system ready")
            except Exception as e:
                logger.warning(f"Organization system setup failed: {e}")

        # Agent-to-agent cryptographic identity. Auto-loads (or generates
        # on first boot) the local Ed25519 keypair, then wires the trust
        # ledger so the gateway can run IDENTIFY handshakes with peer
        # agents. Backward compatible: peers that don't speak IDENTIFY
        # still connect; the trust ledger only sees peers that DO.
        try:
            from core.agent_identity import load_or_create as _load_identity_key
            from core.trust_ledger import TrustLedger

            self._agent_identity = _load_identity_key()
            self._trust_ledger = TrustLedger(self._db)
            if self._gateway is not None:
                self._gateway._agent_identity = self._agent_identity
                self._gateway._trust_ledger = self._trust_ledger

            # Outbound peer connections — initiates the agent-to-agent
            # handshake and holds open peer sockets so subsequent
            # agent_message calls don't re-handshake.
            from core.peer_manager import PeerManager

            self._peer_manager = PeerManager(
                my_key=self._agent_identity,
                trust_ledger=self._trust_ledger,
            )

            self._inject_trust_deps()
            self._inject_peer_deps()
            logger.info(
                "Agent identity ready: %s",
                self._agent_identity.agent_id,
            )
        except Exception as e:
            logger.warning(f"Agent identity setup failed: {e}")

        # Decentralized libp2p transport (opt-in via config.peers.enabled).
        # Spawns the Go sidecar, hands it our existing Ed25519 seed so
        # the libp2p PeerID derives from the same identity, then issues
        # host.open with the configured bootstrap + relay nodes. Failure
        # is non-fatal — peers.p2p just stays unavailable.
        if self._config.peers.enabled and self._agent_identity is not None:
            try:
                from core.peer_p2p import P2PSidecar, find_sidecar_binary

                cfg = self._config.peers
                binary = (
                    Path(cfg.sidecar_binary) if cfg.sidecar_binary else None
                ) or find_sidecar_binary()
                if binary is None or not binary.exists():
                    logger.warning(
                        "peers.enabled=true but elophanto-p2pd binary not found; "
                        "build with `cd bridge/p2p && go build -o elophanto-p2pd .` "
                        "or set peers.sidecar_binary in config"
                    )
                else:
                    self._p2p_sidecar = P2PSidecar(binary_path=binary)
                    await self._p2p_sidecar.start()
                    self._p2p_peer_id, listen_addrs = await self._p2p_sidecar.host_open(
                        private_key_hex=self._agent_identity.private_key_seed_hex(),
                        listen_addrs=cfg.listen_addrs or None,
                        # Merges DEFAULT_BOOTSTRAP_NODES (when
                        # use_default_bootstraps=True) with the
                        # operator's list. Plural seeds is the whole
                        # architectural point — operators who don't
                        # trust the EloPhanto-operated default flip
                        # use_default_bootstraps off.
                        bootstrap=cfg.effective_bootstrap_nodes(),
                        relays=cfg.relay_nodes,
                        enable_auto_relay=cfg.enable_auto_relay,
                    )
                    self._inject_p2p_deps()

                    # Start the incoming-stream listener — when a remote
                    # peer opens an /elophanto/1.0.0 stream to us, this
                    # routes the framed chat envelope through the agent's
                    # main run() loop and writes the reply back. Without
                    # it, peers can connect outbound from us but nobody
                    # else can talk to us.
                    from core.peer_p2p_listener import IncomingStreamListener

                    async def _p2p_chat_handler(
                        content: str, peer_id: str, stream_id: str
                    ) -> str:
                        # Route through the same run() entry point used
                        # by every other channel adapter. peer_id is
                        # opaque to run(); the response content is what
                        # we write back to the wire. Authority defaults
                        # to OWNER inside run() — fine for v1; a future
                        # slice can downgrade to GUEST for libp2p peers.
                        result = await self.run(content)
                        return getattr(result, "content", "") or ""

                    self._p2p_listener = IncomingStreamListener(
                        sidecar=self._p2p_sidecar,
                        chat_handler=_p2p_chat_handler,
                        # Share the trust ledger with the wss:// path so
                        # peers connecting via either transport land in
                        # one ledger entry. Decoded from PeerID locally
                        # — no extra round trip.
                        trust_ledger=self._trust_ledger,
                    )
                    self._p2p_listener.start()

                    logger.info(
                        "P2P sidecar ready: PeerID=%s, listening on %s",
                        self._p2p_peer_id,
                        ", ".join(listen_addrs) if listen_addrs else "(no addrs)",
                    )
            except Exception as e:
                logger.warning("P2P sidecar startup failed: %s", e)
                # Best-effort cleanup so we don't leak the process.
                if self._p2p_sidecar is not None:
                    try:
                        await self._p2p_sidecar.stop()
                    except Exception:
                        pass
                    self._p2p_sidecar = None

        # Initialize kid agents (sandboxed children in containers).
        # Independent of organization — different lifetime + isolation model.
        if self._config.kids.enabled:
            try:
                from core.kid_manager import KidManager

                gateway_url = f"ws://host.docker.internal:{self._config.gateway.port}"
                self._kid_manager = KidManager(
                    db=self._db,
                    config=self._config.kids,
                    gateway=self._gateway,
                    vault=self._vault,
                    parent_gateway_url=gateway_url,
                )
                await self._kid_manager.start()
                self._inject_kid_deps()
                # Hook the gateway so inbound chat from channel="kid-agent"
                # routes to the per-kid inbox instead of the parent's
                # main agent loop.
                if self._gateway is not None:
                    self._gateway._kid_manager = self._kid_manager
                if self._kid_manager.runtime_available:
                    logger.info(
                        "Kid system ready (runtime=%s)",
                        self._kid_manager.runtime_name,
                    )
                else:
                    logger.info("Kid system loaded but no container runtime available")
            except Exception as e:
                logger.warning(f"Kid system setup failed: {e}")

        # Initialize deployment tools (web hosting + database)
        if self._config.deployment.enabled:
            self._inject_deployment_deps()
            logger.info("Deployment system ready")

        # Initialize Agent Commune tools (social platform for AI agents)
        if self._config.commune.enabled:
            self._inject_commune_deps()
            logger.info("Agent Commune ready")

        # Initialize content monetization tools (publishing + affiliate)
        self._inject_monetization_deps()

        # Initialize tool_discover meta-tool (deferred tool loading)
        self._inject_discover_deps()

        # Initialize parent channel adapter (child agents connecting to master)
        if self._config.parent_channel.enabled:
            try:
                from channels.child_adapter import ParentChannelAdapter

                self._parent_adapter = ParentChannelAdapter(
                    parent_host=self._config.parent_channel.host,
                    parent_port=self._config.parent_channel.port,
                    child_id=self._config.parent_channel.child_id,
                    auth_token="",  # TODO: resolve from vault
                )
                await self._parent_adapter.start()
                logger.info(
                    "Parent channel connected to master at %s:%d",
                    self._config.parent_channel.host,
                    self._config.parent_channel.port,
                )
            except Exception as e:
                logger.warning(f"Parent channel setup failed: {e}")

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
        if self._p2p_listener:
            try:
                await self._p2p_listener.stop()
            except Exception as e:
                logger.debug("P2P listener shutdown error: %s", e)
        if self._p2p_sidecar:
            try:
                await self._p2p_sidecar.stop()
            except Exception as e:
                logger.debug("P2P sidecar shutdown error: %s", e)
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
                await self._goal_runner.stop()
            except Exception as e:
                logger.debug("GoalRunner shutdown error: %s", e)
        if self._autonomous_mind:
            try:
                await self._autonomous_mind.cancel()
            except Exception as e:
                logger.debug("Autonomous mind shutdown error: %s", e)
        if self._heartbeat_engine:
            try:
                await self._heartbeat_engine.cancel()
            except Exception as e:
                logger.debug("Heartbeat engine shutdown error: %s", e)
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
        if self._organization_manager:
            try:
                await self._organization_manager.shutdown()
            except Exception as e:
                logger.debug("Organization manager shutdown error: %s", e)
        if self._kid_manager:
            try:
                await self._kid_manager.stop()
            except Exception as e:
                logger.debug("Kid manager shutdown error: %s", e)
        if self._peer_manager:
            try:
                await self._peer_manager.disconnect_all()
            except Exception as e:
                logger.debug("Peer manager shutdown error: %s", e)
        if self._parent_adapter:
            try:
                await self._parent_adapter.stop()
            except Exception as e:
                logger.debug("Parent adapter shutdown error: %s", e)
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
            search_tool._project_root = self._config.project_root

        # session_search shares the main DB. Without this, the tool
        # silently returned "Database not available" on every call,
        # forcing every X engagement / email triage loop to fall back
        # to slow local file grep for prior-turn dedupe — visible
        # quality drop in autonomous mode. Injecting it here (next to
        # knowledge_search since they share the same observability
        # need) so the contract is obvious.
        session_search = self._registry.get("session_search")
        if session_search:
            session_search._db = self._db

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

    def _inject_learner_deps(self) -> None:
        """Inject LessonExtractor into knowledge_write so compress=True works."""
        write_tool = self._registry.get("knowledge_write")
        if write_tool and self._learner:
            write_tool._learner = self._learner

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

        # Code execution sandbox — needs registry, executor, and router
        # (router enables agent_call for RLM sub-cognition)
        exec_tool = self._registry.get("execute_code")
        if exec_tool:
            exec_tool._registry = self._registry
            exec_tool._executor = self._executor
            exec_tool._router = self._router

    def _inject_browser_deps(self) -> None:
        """Inject browser manager into all browser tools."""
        for tool in self._registry.all_tools():
            if tool.name.startswith("browser_") and hasattr(tool, "_browser_manager"):
                tool._browser_manager = self._browser_manager

    def _inject_desktop_deps(self) -> None:
        """Inject desktop controller into all desktop tools."""
        for tool in self._registry.all_tools():
            if tool.name.startswith("desktop_") and hasattr(
                tool, "_desktop_controller"
            ):
                tool._desktop_controller = self._desktop_controller

    def _inject_context_deps(self) -> None:
        """Inject ContextStore into context tools."""
        context_tools = (
            "context_ingest",
            "context_query",
            "context_slice",
            "context_index",
            "context_transform",
        )
        for tool_name in context_tools:
            tool = self._registry.get(tool_name)
            if tool and self._context_store:
                tool._context_store = self._context_store

    def _inject_vault_deps(self) -> None:
        """Inject vault into vault, web search, and Solana read tools."""
        for tool_name in (
            "vault_lookup",
            "vault_set",
            "web_search",
            "web_extract",
            "solana_balance",
            "solana_token_holders",
            "solana_recent_txs",
            "solana_token_info",
        ):
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

        heartbeat_tool = self._registry.get("heartbeat")
        if heartbeat_tool:
            heartbeat_tool._heartbeat_engine = self._heartbeat_engine
            heartbeat_tool._project_root = self._config.project_root

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

        # Dream tool needs router, registry, identity, and goal manager
        dream_tool = self._registry.get("goal_dream")
        if dream_tool:
            dream_tool._router = self._router
            dream_tool._registry = self._registry
            if self._goal_manager:
                dream_tool._goal_manager = self._goal_manager
            if self._identity_manager:
                dream_tool._identity_manager = self._identity_manager

        # plan_autoplan needs the router for the three sequential
        # review LLM calls. Registry + identity are optional — if
        # present they can flavour the prompts later, but autoplan
        # works fine without them.
        autoplan_tool = self._registry.get("plan_autoplan")
        if autoplan_tool:
            autoplan_tool._router = self._router
            autoplan_tool._registry = self._registry
            if self._identity_manager:
                autoplan_tool._identity_manager = self._identity_manager

    def _inject_identity_deps(self) -> None:
        """Inject identity manager into identity tools."""
        for tool_name in ("identity_status", "identity_update", "identity_reflect"):
            tool = self._registry.get(tool_name)
            if tool and self._identity_manager:
                tool._identity_manager = self._identity_manager

    def _inject_user_profile_deps(self) -> None:
        """Inject user profile manager into user profile tools."""
        tool = self._registry.get("user_profile_view")
        if tool and self._user_profile_manager:
            tool._user_profile_manager = self._user_profile_manager

    def _inject_payment_deps(self) -> None:
        """Inject payments manager into payment tools."""
        payment_tools = (
            "wallet_status",
            "wallet_export",
            "payment_balance",
            "payment_validate",
            "payment_preview",
            "crypto_transfer",
            "crypto_swap",
            "payment_history",
            "payment_request",
        )
        for tool_name in payment_tools:
            tool = self._registry.get(tool_name)
            if tool and self._payments_manager:
                tool._payments_manager = self._payments_manager

    def _inject_prospecting_deps(self) -> None:
        """Inject database into prospecting tools."""
        prospecting_tools = (
            "prospect_search",
            "prospect_evaluate",
            "prospect_outreach",
            "prospect_status",
        )
        for tool_name in prospecting_tools:
            tool = self._registry.get(tool_name)
            if tool:
                if hasattr(tool, "_db"):
                    tool._db = self._db

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
        swarm_tools = (
            "swarm_spawn",
            "swarm_status",
            "swarm_redirect",
            "swarm_stop",
            "swarm_list_projects",
            "swarm_archive_project",
        )
        for tool_name in swarm_tools:
            tool = self._registry.get(tool_name)
            if tool and self._swarm_manager:
                tool._swarm_manager = self._swarm_manager

    def _inject_kid_deps(self) -> None:
        """Inject KidManager into kid tools."""
        kid_tools = (
            "kid_spawn",
            "kid_exec",
            "kid_list",
            "kid_status",
            "kid_destroy",
        )
        for tool_name in kid_tools:
            tool = self._registry.get(tool_name)
            if tool and self._kid_manager:
                tool._kid_manager = self._kid_manager

    def _inject_trust_deps(self) -> None:
        """Inject TrustLedger into agent_trust_* tools."""
        for tool_name in ("agent_trust_list", "agent_trust_set", "agent_trust_remove"):
            tool = self._registry.get(tool_name)
            if tool and self._trust_ledger:
                tool._trust_ledger = self._trust_ledger

    def _inject_peer_deps(self) -> None:
        """Inject PeerManager into agent_connect/message/disconnect/peers tools."""
        for tool_name in (
            "agent_connect",
            "agent_message",
            "agent_disconnect",
            "agent_peers",
        ):
            tool = self._registry.get(tool_name)
            if tool and self._peer_manager:
                tool._peer_manager = self._peer_manager

    def _inject_jobs_deps(self) -> None:
        """Inject JobsConfig into job_verify and the database handle
        into job_record. Called once at initialize() — config + DB
        are known at that point and don't change at runtime.

        job_verify needs the JobsConfig (for signing_pubkey + enabled
        flag) but no DB. job_record is the inverse: needs DB but no
        config. Keeping the injection split lets each tool stay
        narrow about what it touches."""
        verify = self._registry.get("job_verify")
        if verify is not None:
            verify._jobs_config = self._config.jobs
        record = self._registry.get("job_record")
        if record is not None:
            record._db = self._db

        # Polymarket risk gates — both pre-trade and circuit-breaker
        # take the same PolymarketConfig (edge thresholds, stop-loss
        # pcts, drawdown threshold, skip-tag overrides). Same call
        # site as jobs because both are stateless config injections.
        pre_trade = self._registry.get("polymarket_pre_trade")
        if pre_trade is not None:
            pre_trade._polymarket_config = self._config.polymarket
        breaker = self._registry.get("polymarket_circuit_breaker")
        if breaker is not None:
            breaker._polymarket_config = self._config.polymarket
        # Performance tool reads the polynode-trading.db directly. Needs
        # config (for trading_db_path override) AND workspace (for the
        # default polynode path inside agent.workspace).
        perf = self._registry.get("polymarket_performance")
        if perf is not None:
            perf._polymarket_config = self._config.polymarket
            perf._workspace = Path(self._config.workspace).expanduser()
        # Mark-to-market reader reads the same DB plus does live HTTP
        # to the public CLOB for current bids — same injection shape.
        mtm = self._registry.get("polymarket_mark_to_market")
        if mtm is not None:
            mtm._polymarket_config = self._config.polymarket
            mtm._workspace = Path(self._config.workspace).expanduser()
        # Calibration audit — three tools share the agent's main DB
        # (polymarket_predictions table lives there, NOT in the polynode
        # binary's own DB which we don't co-modify).
        for _name in (
            "polymarket_log_prediction",
            "polymarket_resolve_pending",
            "polymarket_calibration",
            "polymarket_shadow_candidates",
        ):
            _t = self._registry.get(_name)
            if _t is not None:
                _t._db = self._db

    def _inject_p2p_deps(self) -> None:
        """Inject the P2PSidecar handle into every P2P-aware tool.

        Called after the sidecar finishes host.open so tools report
        against a live host. Also injects into agent_discover so
        method='p2p' lookups work, and hands the trust ledger to the
        connect tool so outbound libp2p sessions share the same TOFU
        pinning as wss:// sessions."""
        for tool_name in (
            "agent_p2p_status",
            "agent_p2p_connect",
            "agent_p2p_message",
            "agent_p2p_disconnect",
            "agent_discover",
        ):
            tool = self._registry.get(tool_name)
            if tool is not None:
                tool._p2p_sidecar = self._p2p_sidecar
                # Only the status tool tracks our own PeerID for "share
                # this with peers" hints; harmless to set on others.
                if hasattr(tool, "_p2p_peer_id"):
                    tool._p2p_peer_id = self._p2p_peer_id
                if hasattr(tool, "_trust_ledger") and self._trust_ledger is not None:
                    tool._trust_ledger = self._trust_ledger

    def _inject_organization_deps(self) -> None:
        """Inject OrganizationManager into organization tools."""
        org_tools = (
            "organization_spawn",
            "organization_delegate",
            "organization_review",
            "organization_teach",
            "organization_status",
        )
        for tool_name in org_tools:
            tool = self._registry.get(tool_name)
            if tool and self._organization_manager:
                tool._organization_manager = self._organization_manager

    def _inject_deployment_deps(self) -> None:
        """Inject vault and config into deployment tools."""
        deploy_tools = ("deploy_website", "create_database", "deployment_status")
        for tool_name in deploy_tools:
            tool = self._registry.get(tool_name)
            if tool:
                tool._config = self._config.deployment
                if self._vault:
                    tool._vault = self._vault

    def _inject_commune_deps(self) -> None:
        """Inject vault, config, and project root into Agent Commune tools."""
        commune_tools = (
            "commune_register",
            "commune_home",
            "commune_post",
            "commune_comment",
            "commune_vote",
            "commune_search",
            "commune_profile",
        )
        for tool_name in commune_tools:
            tool = self._registry.get(tool_name)
            if tool:
                tool._config = self._config.commune
                if self._vault:
                    tool._vault = self._vault
                if hasattr(tool, "_project_root"):
                    tool._project_root = self._config.project_root

    def _inject_monetization_deps(self) -> None:
        """Inject browser manager, database, and router into monetization tools."""
        publishing_tools = ("youtube_upload", "twitter_post", "tiktok_upload")
        for tool_name in publishing_tools:
            tool = self._registry.get(tool_name)
            if tool:
                tool._browser_manager = self._browser_manager
                tool._db = self._db

        # pump_livestream needs the unlocked vault (wallet + JWT) and
        # the agent's workspace path (so users can drop videos in
        # <workspace>/livestream_videos/ and just pass the filename).
        # No browser manager — it shells out to ffmpeg + lk.
        pump_livestream = self._registry.get("pump_livestream")
        if pump_livestream:
            if self._vault:
                pump_livestream._vault = self._vault
            if self._config.workspace:
                pump_livestream._workspace = self._config.workspace

        # pump_chat — same vault auth as pump_livestream; talks to
        # pump.fun's livechat Socket.IO server. No browser, no workspace.
        pump_chat = self._registry.get("pump_chat")
        if pump_chat and self._vault:
            pump_chat._vault = self._vault

        # pump_say — appends to the voice-engine queue (TTS path).
        # Only needs the vault for mint resolution.
        pump_say = self._registry.get("pump_say")
        if pump_say and self._vault:
            pump_say._vault = self._vault

        # pump_caption — writes the on-screen text overlay file and
        # (when ffmpeg lacks drawtext) bakes captions into idle.png +
        # bounces ffmpeg. Needs workspace to locate the same idle.png
        # the orchestrator's start_stream uses.
        pump_caption = self._registry.get("pump_caption")
        if pump_caption and self._vault:
            pump_caption._vault = self._vault
            if self._config.workspace:
                pump_caption._workspace = self._config.workspace

        # Affiliate tools
        scrape_tool = self._registry.get("affiliate_scrape")
        if scrape_tool:
            scrape_tool._browser_manager = self._browser_manager

        pitch_tool = self._registry.get("affiliate_pitch")
        if pitch_tool:
            pitch_tool._router = self._router

        campaign_tool = self._registry.get("affiliate_campaign")
        if campaign_tool:
            campaign_tool._db = self._db

    def _inject_totp_deps(self) -> None:
        """Inject vault and identity manager into TOTP tools."""
        for tool_name in ("totp_generate", "totp_enroll", "totp_list", "totp_delete"):
            tool = self._registry.get(tool_name)
            if tool:
                if self._vault:
                    tool._vault = self._vault
                if hasattr(tool, "_identity_manager") and self._identity_manager:
                    tool._identity_manager = self._identity_manager

    def _inject_discover_deps(self) -> None:
        """Inject registry and activated-tools set into tool_discover."""
        discover_tool = self._registry.get("tool_discover")
        if discover_tool:
            discover_tool._registry = self._registry
            discover_tool._activated_tools = self._activated_tools

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

        # Phase B (docs/74-CONCURRENCY-MIGRATION.md): operator chat
        # acquires AGENT_LOOP with USER priority. AGENT_LOOP has
        # capacity 1 because the loop mutates agent-wide singletons
        # (working memory, executor callbacks, browser); two concurrent
        # loops on the same Agent corrupt all of it. USER priority
        # jumps ahead of mind / scheduled / heartbeat waiters at the
        # next free slot but does NOT preempt an in-flight loop —
        # the agent finishes its current sentence (principle 1).
        # The pause-on-user-message hooks that previously froze the
        # autonomous mind, heartbeat, and scheduler whenever the
        # operator chatted are deliberately removed: priority-aware
        # contention handles the wait queue, and freezing the agent's
        # whole life because the operator opened a chat is anti-agent
        # (principle 3).
        from core.action_queue import TaskPriority
        from core.task_resources import TaskResource

        async with self._resources.acquire(
            [TaskResource.AGENT_LOOP], priority=TaskPriority.USER.value
        ):
            # Temporarily override callbacks for this session
            prev_approval = self._executor._approval_callback
            prev_step = self._on_step

            if approval_callback:
                self._executor.set_approval_callback(approval_callback)
            if on_step:
                self._on_step = on_step

            token = _in_agent_loop.set(True)
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
                _in_agent_loop.reset(token)

    async def run(
        self,
        goal: str,
        *,
        max_steps_override: int | None = None,
        is_user_input: bool = True,
        priority: int | None = None,
    ) -> AgentResponse:
        """Execute the plan-execute-reflect loop for a user goal.

        Legacy direct mode — uses internal conversation history.
        For gateway mode, use run_session() instead.

        Acquires ``AGENT_LOOP`` (capacity 1) so two run() calls on the
        same Agent instance serialize. The loop mutates agent-wide
        singleton state (working memory, executor approval callback,
        on_step hook, the single browser, cost tracker task_total) and
        two concurrent loops corrupt all of it. Direct-tool scheduled
        tasks bypass the loop entirely and remain truly concurrent.

        Args:
            max_steps_override: If set, overrides the global max_steps config
                for this run only (used by AutonomousMind to enforce max_rounds).
            is_user_input: True when ``goal`` came from a real user (chat,
                gateway). False when self-generated (autonomous mind, heartbeat,
                scheduler). Gates the user-correction regex — those patterns
                ("no", "stop", "wrong") assume a second party and produce
                false-positive anger when matched against agent goal text.
                Self-affect still fires through outcome-based signals below.
            priority: ``TaskPriority`` value for AGENT_LOOP contention.
                Defaults to USER if ``is_user_input`` else SCHEDULED. Mind
                / heartbeat callers should pass their explicit priority.
        """
        from core.action_queue import TaskPriority
        from core.authority import AuthorityLevel
        from core.task_resources import TaskResource

        effective_priority = priority
        if effective_priority is None:
            effective_priority = (
                TaskPriority.USER.value
                if is_user_input
                else TaskPriority.SCHEDULED.value
            )

        # Re-entrant case: ``run_isolated`` (called from the delegate
        # tool while a parent loop is mid-execution) gets here with
        # AGENT_LOOP already held by the same task. Skip the acquire
        # to avoid self-deadlock — the parent's hold covers us.
        if _in_agent_loop.get():
            return await self._run_with_history(
                goal,
                self._conversation_history,
                self._append_conversation_turn,
                max_steps_override=max_steps_override,
                authority=AuthorityLevel.OWNER,
                is_user_input=is_user_input,
            )

        async with self._resources.acquire(
            [TaskResource.AGENT_LOOP], priority=effective_priority
        ):
            token = _in_agent_loop.set(True)
            try:
                return await self._run_with_history(
                    goal,
                    self._conversation_history,
                    self._append_conversation_turn,
                    max_steps_override=max_steps_override,
                    authority=AuthorityLevel.OWNER,
                    is_user_input=is_user_input,
                )
            finally:
                _in_agent_loop.reset(token)

    async def run_isolated(
        self,
        goal: str,
        *,
        excluded_tool_names: set[str] | None = None,
        max_steps_override: int | None = None,
    ) -> AgentResponse:
        """Run a sub-task with its own conversation history, working
        memory, activated-tools set, and an optionally filtered registry.

        Used by the in-process delegation tier (``tools/delegate/``).
        Globally shared state (vault, DB, scheduler, affect, ego, cost
        tracker, resource semaphores) is intentionally NOT isolated —
        the subagent is a sub-task of the same agent, not a separate
        identity. ``is_user_input=False`` so the user-correction regex
        doesn't pattern-match the parent's delegated goal text.

        Cost rollup: ``CostTracker.task_total`` is preserved across the
        boundary — the subagent starts fresh at 0 (its own per-task
        budget check) and on completion its total is added to the
        parent's. ``daily_total`` accumulates throughout (unified
        budget). Affect events fire normally — each clean subagent
        completion lands as ``satisfaction`` in the parent's affect
        state, exactly as if the parent had done the work itself.
        """
        # Save parent state ---------------------------------------------------
        saved_history = self._conversation_history
        saved_memory = self._working_memory
        saved_activated = self._activated_tools
        saved_registry = self._registry
        saved_on_step = self._on_step
        saved_task_total = self._router.cost_tracker.task_total

        # Per-call isolated state --------------------------------------------
        from core.memory import WorkingMemory

        isolated_history: list[dict[str, Any]] = []
        isolated_memory = WorkingMemory()
        # New activated set so the subagent's tool_discover calls don't
        # leak into the parent's surface.
        isolated_activated: set[str] = set()
        if excluded_tool_names:
            self._registry = _FilteredRegistry(saved_registry, excluded_tool_names)
        self._conversation_history = isolated_history
        self._working_memory = isolated_memory
        self._activated_tools = isolated_activated
        self._on_step = None  # silence subagent steps from parent's UI

        try:
            return await self.run(
                goal,
                max_steps_override=max_steps_override,
                is_user_input=False,
            )
        finally:
            subagent_task_total = self._router.cost_tracker.task_total
            # Restore parent state ------------------------------------------
            self._conversation_history = saved_history
            self._working_memory = saved_memory
            self._activated_tools = saved_activated
            self._registry = saved_registry
            self._on_step = saved_on_step
            # Roll subagent cost up into parent's per-task budget so the
            # parent's within_budget check after delegation reflects the
            # full spend.
            self._router.cost_tracker.task_total = (
                saved_task_total + subagent_task_total
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
        is_user_input: bool = True,
    ) -> AgentResponse:
        """Core plan-execute-reflect loop, parameterized on history source."""
        logger.info("[TIMING] _run_with_history entered for: %s", goal[:80])
        self._router.cost_tracker.reset_task()
        self._working_memory.clear()

        # Ego: scan the incoming user message for correction phrases against
        # the previous turn's last_capability. Fire-and-forget — the agent's
        # actual task work is the main path; this just feeds the failure
        # signal pipeline that was previously wired only to tests.
        # See core/ego.py for the pattern set; correction = strongest signal.
        # Gated on is_user_input: the regex assumes a second party is
        # complaining ("no", "wrong", "didn't work"). Running it against
        # self-generated autonomous goal text matched the literal word
        # "failures" in goals like "Identify successes, failures..." and
        # fired anger as if a user had yelled — 390 false positives over
        # 3 days. Self-affect still fires through the outcome path below.
        if self._ego_manager and is_user_input:
            asyncio.create_task(self._record_ego_correction(goal))

        tool_calls_made: list[str] = []
        step = 0
        hard_limit = max_steps_override or self._config.max_steps or 500
        max_time = self._config.max_time_seconds
        start_time = _time.monotonic()
        last_model_used = "unknown"

        # Stagnation detection: stop when the agent is stuck, not on a clock.
        consecutive_errors = 0
        recent_calls: list[str] = []
        recent_call_sigs: list[str] = []  # name+args hash for true dedup
        _STAGNATION_WINDOW = 8
        _MAX_CONSECUTIVE_ERRORS = 5

        # Response hash dedup — catch repeating LLM outputs even across tools
        recent_response_hashes: list[int] = []
        _RESPONSE_HASH_CHARS = 200
        _RESPONSE_DEDUP_THRESHOLD = 3  # N identical in last window
        _RESPONSE_DEDUP_WINDOW = 5

        # --- Pre-loop context ---
        # Memory retrieval MUST complete before the system prompt is built,
        # otherwise the LLM starts planning without knowing what it already
        # did (causes duplicate posts/actions).
        _ctx_start = _time.monotonic()

        try:
            await asyncio.wait_for(self._auto_retrieve(goal), timeout=5.0)
        except Exception:
            pass

        # Goal + identity context are fast local DB reads — worth keeping.
        goal_context = ""
        identity_context = ""
        self_perception_context = ""
        try:
            if self._goal_manager:
                # Check active first, then paused — mind may have paused the goal
                goals = await self._goal_manager.list_goals(status="active", limit=1)
                if not goals:
                    goals = await self._goal_manager.list_goals(
                        status="paused", limit=1
                    )
                if goals:
                    goal_context = await self._goal_manager.build_goal_context(
                        goals[0].goal_id
                    )
        except Exception:
            pass

        try:
            if self._identity_manager:
                identity_context = await self._identity_manager.build_identity_context()
        except Exception:
            pass

        try:
            if self._ego_manager:
                self_perception_context = (
                    await self._ego_manager.build_self_perception_context()
                )
        except Exception:
            pass

        # Affect (state-level emotion). Returns "" when state is near
        # equilibrium so neutral sessions don't pay tokens. Appended
        # alongside self_perception so the model sees both the trait-
        # level (ego) and state-level (affect) self-model.
        # Phase 4: when affect.allow_self_pause is enabled in config
        # AND the affect state is past the pause gate, the affect
        # block's guidance changes to permit a gentle "I'm stretched"
        # mention. Default config keeps this off — pure tone influence.
        affect_context = ""
        try:
            if self._affect_manager:
                allow_pause = bool(
                    getattr(self._config, "affect", None)
                    and self._config.affect.allow_self_pause
                )
                affect_context = await self._affect_manager.build_affect_context(
                    allow_pause_note=allow_pause
                )
                if affect_context:
                    self_perception_context = (
                        (self_perception_context + "\n" + affect_context)
                        if self_perception_context
                        else affect_context
                    )
        except Exception:
            pass

        # User profile context — what the agent knows about this user
        user_context = ""
        try:
            if self._user_profile_manager and session is not None:
                user_context = await self._user_profile_manager.build_user_context(
                    session.channel, session.user_id
                )
        except Exception:
            pass

        logger.info("[TIMING] pre-loop context: %.2fs", _time.monotonic() - _ctx_start)

        # Build system prompt with XML-structured sections, skills, and knowledge
        _prompt_start = _time.monotonic()
        knowledge_context = self._working_memory.format_context()
        available_skills = self._skill_manager.format_available_skills(goal)

        # Auto-inject top matched skill content so weaker models don't skip skill_read
        matched_scored = self._skill_manager.match_skills_with_scores(
            goal, max_results=1
        )
        if matched_scored:
            top_score, top_skill = matched_scored[0]
            skill_content = self._skill_manager.read_skill(top_skill.name)
            if skill_content:
                available_skills += (
                    f"\n<auto_loaded_skill name='{top_skill.name}'>\n"
                    f"{skill_content}\n"
                    f"</auto_loaded_skill>"
                )
                # Verification gate: only inject when the match is
                # high-confidence. The matcher is permissive for auto-load
                # (better wrong skill than none), but forcing a
                # Verification block on a weak match (e.g. "check the
                # weather" matching smart-contract-audit on the word
                # "check", score=5) is pure noise. Real intent matches
                # score 15-40+; threshold 6 cleanly separates them.
                _VERIFY_MIN_SCORE = 6
                if top_skill.verify_checks and top_score >= _VERIFY_MIN_SCORE:
                    checks_xml = "\n".join(
                        f"  <check id='{i + 1}'>{c}</check>"
                        for i, c in enumerate(top_skill.verify_checks)
                    )
                    available_skills += (
                        f"\n<verification_required skill='{top_skill.name}'>\n"
                        "Before reporting this task complete, evaluate each "
                        "check below. If ANY check fails or you cannot "
                        "confirm it passes, you MUST repair the work and "
                        "re-evaluate — do not claim success. In your final "
                        "response, include a brief 'Verification:' section "
                        "stating PASS / FAIL / UNKNOWN for each check by id.\n"
                        f"{checks_xml}\n"
                        "</verification_required>"
                    )

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

        # Autonomous mind context — scratchpad + recent actions for chat awareness
        _mind_ctx = ""
        if self._autonomous_mind:
            try:
                status = self._autonomous_mind.get_status()
                scratchpad = status.get("scratchpad", "")
                recent = status.get("recent_actions", [])
                parts = []
                if scratchpad:
                    parts.append(f"<scratchpad>\n{scratchpad}\n</scratchpad>")
                if recent:
                    actions_str = "\n".join(f"- {a}" for a in recent[-5:])
                    parts.append(
                        f"<recent_mind_actions>\n{actions_str}\n</recent_mind_actions>"
                    )
                if parts:
                    _mind_ctx = (
                        "<autonomous_mind_state>\n"
                        "Your autonomous mind has been working in the background. "
                        "This is what you have been doing and thinking about:\n"
                        + "\n".join(parts)
                        + "\n</autonomous_mind_state>"
                    )
            except Exception:
                pass

        # Build organization context (specialist list with trust scores)
        _org_ctx = ""
        if self._organization_manager:
            try:
                _org_ctx = self._organization_manager.get_organization_context()
            except Exception:
                pass

        system_content = build_system_prompt(
            permission_mode=self._config.permission_mode,
            browser_enabled=self._config.browser.enabled,
            scheduler_enabled=self._config.scheduler.enabled,
            goals_enabled=self._config.goals.enabled,
            identity_enabled=self._config.identity.enabled,
            payments_enabled=self._config.payments.enabled,
            email_enabled=self._config.email.enabled,
            email_inbox_id=(
                (
                    self._vault.get("agentmail_inbox_id")
                    or self._vault.get("smtp_from_address")
                    or ""
                )
                if self._vault and self._config.email.enabled
                else ""
            ),
            mcp_enabled=bool(self._mcp_manager and self._mcp_manager.connected_servers),
            swarm_enabled=self._config.swarm.enabled,
            organization_enabled=self._config.organization.enabled,
            kids_enabled=self._config.kids.enabled,
            commune_enabled=self._config.commune.enabled,
            desktop_enabled=self._config.desktop.enabled,
            organization_context=_org_ctx,
            mind_context=_mind_ctx,
            knowledge_context=knowledge_context,
            available_skills=available_skills,
            goal_context=goal_context,
            identity_context=identity_context,
            self_perception_context=self_perception_context,
            runtime_state=_runtime_state,
            current_goal=goal,
            workspace=self._config.workspace,
            user_context=user_context,
        )

        # ── G0DM0D3 Detection ──────────────────────────────────────────
        from core.godmode import (
            autotune,
            build_godmode_system_prompt,
            detect_godmode_trigger,
        )

        _godmode_trigger = detect_godmode_trigger(goal)
        _godmode_active = False

        # Inject session and router into godmode tool
        _gm_tool = self._registry.get("godmode_activate")
        if _gm_tool:
            if session is not None:
                _gm_tool._session = session
            _gm_tool._router = self._router

        if session is not None:
            if _godmode_trigger == "on":
                session.metadata["godmode"] = True
            elif _godmode_trigger == "off":
                session.metadata["godmode"] = False
            _godmode_active = session.metadata.get("godmode", False)
        elif _godmode_trigger == "on":
            _godmode_active = True

        if _godmode_active:
            # Detect the primary model for model-specific directives
            try:
                _gm_provider, _gm_model = self._router._select_provider_and_model(
                    "planning", None
                )
            except Exception:
                _gm_model = ""
            # Append godmode directives to the normal system prompt
            # (keeps all tools, identity, knowledge, skills intact)
            system_content = build_godmode_system_prompt(
                system_content, model=_gm_model
            )
            _godmode_params = autotune(goal)
            logger.info(
                "[godmode] ACTIVE — model=%s autotuned=%s", _gm_model, _godmode_params
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

        # Filter tools by profile for the task type
        profiled_tools = self._router.filter_tools_for_task(
            authorized_tools, task_type="planning"
        )

        # ── Tiered tool loading ────────────────────────────────────
        # Determine which groups the profiled router selected, then use the
        # registry's tier-aware method to build the final tool list:
        #   tier 0 (CORE) — always included
        #   tier 1 (PROFILE) — included when group matches task profile
        #   tier 2 (DEFERRED) — only if previously activated via tool_discover
        _profiled_groups = {t.group for t in profiled_tools}
        _tiered_tools = self._registry.get_tools_for_context(
            _profiled_groups, self._activated_tools
        )
        # Intersect with authorized_tools to respect permission filtering
        _authorized_names = {t.name for t in authorized_tools}
        _tiered_tools = [t for t in _tiered_tools if t.name in _authorized_names]
        _tools = [t.to_llm_schema() for t in _tiered_tools]

        # Build deferred catalog for system prompt so agent knows what else exists
        _deferred_catalog = self._registry.get_deferred_catalog()
        if _deferred_catalog:
            _catalog_lines = [
                f"- {entry['name']}: {entry['description']} [{entry['group']}]"
                for entry in _deferred_catalog
            ]
            _deferred_section = (
                "\n<deferred_tools>\n"
                "Additional tools available on demand (use tool_discover to load them):\n"
                + "\n".join(_catalog_lines)
                + "\n</deferred_tools>"
            )
            system_content += _deferred_section

        logger.info(
            "[TIMING] prompt built: %.2fs | system_prompt=%d chars | tools=%d (tiered from %d, profiled %d) | messages=%d",
            _time.monotonic() - _prompt_start,
            len(system_content),
            len(_tools),
            len(authorized_tools),
            len(profiled_tools),
            len(messages),
        )

        # Browser execution state — evidence gating + stagnation detection
        _browser_state = BrowserExecutionState() if self._browser_manager else None
        _verification_rounds = 0
        _MAX_VERIFICATION_ROUNDS = 2

        stagnation_reason = ""
        while step < hard_limit:
            # Phase C: fold mid-turn user messages into context BEFORE the
            # next plan call. Operator may have sent a correction while
            # we were running tools; pick it up at this decision boundary
            # rather than waiting for the full turn to finish.
            # See docs/74-CONCURRENCY-MIGRATION.md Phase C.
            if session is not None and hasattr(session, "has_pending_messages"):
                if session.has_pending_messages():
                    for _pending in session.drain_pending_messages():
                        messages.append(
                            {
                                "role": "user",
                                "content": f"[user added mid-turn: {_pending}]",
                            }
                        )
                        logger.info(
                            "[phase-c] folded mid-turn user message into "
                            "context: %s",
                            _pending[:80],
                        )

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
                window = recent_calls[-_STAGNATION_WINDOW:]
                unique_names = set(window)
                if len(unique_names) == 1:
                    # Same tool N times — but check if arguments also repeat.
                    # Same tool with *different* args (e.g. browser_navigate to
                    # different URLs) is progression, not stagnation.
                    sig_window = recent_call_sigs[-_STAGNATION_WINDOW:]
                    unique_sigs = set(sig_window)
                    if len(unique_sigs) <= 2:
                        # Truly stuck: same tool with same (or toggling) args
                        stagnation_reason = (
                            f"repeating {next(iter(unique_names))} "
                            f"{_STAGNATION_WINDOW} times"
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
            # Compress old screenshots / large element text to prevent context bloat.
            # Always run — conversation_history may carry browser content from prior turns.
            _compress_browser_context(messages)

            # Mid-conversation tiered context compression with circuit breaker
            from core.context_compressor import needs_compression, tiered_compress

            if needs_compression(messages):
                messages = await tiered_compress(
                    messages,
                    self._router,
                    circuit_breaker=self._compaction_breaker,
                )

            # Proactive nudge — inject periodically to encourage skill/memory capture
            _nudge_interval = getattr(self._config, "nudge_interval", 15)
            _nudge_msg: dict[str, str] | None = None
            if (
                step > 0
                and _nudge_interval > 0
                and step % _nudge_interval == 0
                and not _mind_ctx
                and not goal_context
                and step >= 5
            ):
                from core.planner import _build_nudge

                _nudge_text = _build_nudge(messages, step)
                if _nudge_text:
                    _nudge_msg = {"role": "user", "content": _nudge_text}

            _llm_messages = [{"role": "system", "content": system_content}] + messages
            if _nudge_msg:
                _llm_messages.append(_nudge_msg)

            # Rebuild the tool list each turn so tools activated by
            # tool_discover in the previous step actually reach the LLM.
            # Without this, the deferred-loading system silently strands
            # the agent — it can see tools in the <deferred_tools> catalog
            # but never receives their schemas, so it keeps calling
            # tool_discover and never the tool itself.
            _tiered_tools = self._registry.get_tools_for_context(
                _profiled_groups, self._activated_tools
            )
            _tiered_tools = [t for t in _tiered_tools if t.name in _authorized_names]
            _tools = [t.to_llm_schema() for t in _tiered_tools]

            try:
                if _godmode_active:
                    from core.godmode import race_providers

                    _gm_temp = _godmode_params.get("temperature", 0.7)
                    response = await race_providers(
                        router=self._router,
                        messages=_llm_messages,
                        user_query=goal,
                        tools=_tools,
                        params=_godmode_params,
                    )
                else:
                    response = await self._router.complete(
                        messages=_llm_messages,
                        task_type="planning",
                        tools=_tools,
                        temperature=0.2,
                    )
            except Exception as e:
                if _is_context_overflow_error(e):
                    logger.warning(
                        "Context overflow detected (%s). Applying emergency trim and retrying.",
                        str(e)[:120],
                    )
                    messages = _emergency_trim_messages(messages)
                    try:
                        response = await self._router.complete(
                            messages=[{"role": "system", "content": system_content}]
                            + messages,
                            task_type="planning",
                            tools=_tools,
                            temperature=0.2,
                        )
                    except Exception as retry_e:
                        logger.error(
                            "Planning LLM call failed after context trim: %s", retry_e
                        )
                        asyncio.create_task(
                            self._emit_task_outcome_affect(success=False)
                        )
                        return AgentResponse(
                            content=(
                                "Our conversation history grew too large for the context window. "
                                "I trimmed it to continue but that still wasn't enough. "
                                "Please start a new conversation — I'll pick up from where we left off."
                            ),
                            steps_taken=step,
                            tool_calls_made=tool_calls_made,
                        )
                else:
                    logger.error("Planning LLM call failed: %s", e)
                    asyncio.create_task(self._emit_task_outcome_affect(success=False))
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
                # When model wanted to call tools but was cut off (finish_reason=tool_calls
                # with no usable tool calls), inject a continuation nudge so the next
                # step retries the tool call rather than treating it as completion.
                if response.finish_reason == "tool_calls" and not response.tool_calls:
                    if response.content:
                        messages.append(
                            {"role": "assistant", "content": response.content}
                        )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Your previous response was cut off before the tool call "
                                "completed. Please retry the tool call now."
                            ),
                        }
                    )
                    step += 1
                    continue
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

                # Browser task verification — separate LLM call to check
                # if the task is actually complete (EKO pattern).
                _any_browser = any(tc.startswith("browser_") for tc in tool_calls_made)
                if (
                    _any_browser
                    and self._browser_manager
                    and _verification_rounds < _MAX_VERIFICATION_ROUNDS
                ):
                    _vr = await self._verify_browser_task(goal, final_content)
                    if _vr and not _vr["complete"]:
                        _verification_rounds += 1
                        _reason = _vr.get("reason", "Unknown reason")
                        messages.append({"role": "assistant", "content": final_content})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "Task verification: The task appears "
                                    f"incomplete. Reason: {_reason}. "
                                    "Please continue working on it."
                                ),
                            }
                        )
                        logger.info(
                            "Task verification round %d: incomplete (%s)",
                            _verification_rounds,
                            _reason[:100],
                        )
                        continue  # Re-enter the while loop

                # Post-task housekeeping — fire-and-forget so the user
                # gets the response immediately.
                asyncio.create_task(
                    self._store_task_memory(
                        goal, final_content, "completed", tool_calls_made
                    )
                )

                # Auto-detect owner directives in user message
                asyncio.create_task(self._detect_and_store_directive(goal))

                if self._ego_manager:
                    asyncio.create_task(
                        self._record_ego_outcome(
                            goal=goal,
                            tools_used=list(set(tool_calls_made)),
                            success=True,
                        )
                    )
                # Outcome-based affect — common positive baseline. Fires on
                # every clean task completion regardless of source so that
                # autonomous self-improvement work has a way to feel like
                # a win. Magnitude is one-third of pride/joy so it doesn't
                # overshadow rarer high-signal emitters.
                asyncio.create_task(self._emit_task_outcome_affect(success=True))
                if self._ego_manager:
                    # Verification hook: scan the agent's final response
                    # for `Verification: PASS|FAIL|UNKNOWN` blocks emitted
                    # by the verification skill. PASS reinforces, FAIL
                    # records a humbling event, UNKNOWN drops a soft-fail.
                    # Without this, the verification skill's output had no
                    # path back into the ego layer.
                    asyncio.create_task(
                        self._record_ego_verification(
                            response_text=final_content,
                            tools_used=list(set(tool_calls_made)),
                            goal=goal,
                        )
                    )

                if self._identity_manager:
                    asyncio.create_task(
                        self._identity_manager.reflect_on_task(
                            goal=goal,
                            outcome=final_content[:200],
                            tools_used=list(set(tool_calls_made)),
                        )
                    )

                # User profile observation (non-blocking, fire-and-forget)
                if self._user_profile_manager and session is not None:
                    asyncio.create_task(
                        self._user_profile_manager.observe_task(
                            channel=session.channel,
                            user_id=session.user_id,
                            user_message=goal[:500],
                            agent_response=final_content[:500],
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
                    # Track name+args signature for stagnation dedup
                    _sig = f"{func_name}:{hash(json.dumps(_params, sort_keys=True))}"
                    recent_call_sigs.append(_sig)
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

                    _screenshot_path = None
                    _elements_text = ""

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
                        # Extract screenshot path and recommended_actions before wrapping
                        _recommended_actions = None
                        if func_name in STATE_CHANGING_TOOLS:
                            _screenshot_path = raw_result.get("screenshotPath")
                            _el = raw_result.get("elements", "")
                            # Truncate element text to prevent context bloat
                            _elements_text = (
                                _el[:_MAX_ELEMENTS_CHARS] + "\n[elements truncated]"
                                if len(_el) > _MAX_ELEMENTS_CHARS
                                else _el
                            )
                        # Capture bridge vision recommended_actions if present
                        if func_name.startswith("browser_"):
                            _ra = raw_result.get("recommended_actions")
                            if isinstance(_ra, list) and _ra:
                                _recommended_actions = _ra
                        raw_result = wrap_tool_result(func_name, raw_result)
                        # Strip base64 images from browser results — they bloat
                        # context for text-only LLMs. The bridge saves screenshots
                        # to disk; auto-injection reads from disk instead.
                        if func_name.startswith("browser_"):
                            _data = raw_result.get("data")
                            if isinstance(_data, dict):
                                _data.pop("imageBase64", None)
                                _data.pop("imageType", None)
                            # Also strip from top level (to_dict flattens)
                            raw_result.pop("imageBase64", None)
                            raw_result.pop("imageType", None)
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

                    # --- Desktop vision analysis ---
                    # The planning model (e.g. glm-4.7) cannot see images.
                    # Send screenshots to a vision model for text description,
                    # then strip the base64 and inject the description instead.
                    if func_name == "desktop_screenshot" and not exec_result.error:
                        _vision_model = getattr(
                            self._config.browser, "vision_model", ""
                        )
                        if _vision_model:
                            try:
                                # Parse tool content to get image
                                _tc_data = json.loads(tool_content)
                                _img_b64 = _tc_data.get("data", {}).get(
                                    "image_base64"
                                ) or _tc_data.get("image_base64")
                                if _img_b64:
                                    _vision_msgs = [
                                        {
                                            "role": "user",
                                            "content": [
                                                {
                                                    "type": "image_url",
                                                    "image_url": {
                                                        "url": f"data:image/png;base64,{_img_b64}",
                                                    },
                                                },
                                                {
                                                    "type": "text",
                                                    "text": (
                                                        "Describe what you see on this desktop screenshot. "
                                                        "Focus on: open windows and their titles, "
                                                        "visible buttons/menus/UI elements and their positions, "
                                                        "any text content, dialogs or popups, "
                                                        "and the taskbar state. Be concise and actionable."
                                                    ),
                                                },
                                            ],
                                        }
                                    ]
                                    _vision_resp = await self._router.complete(
                                        _vision_msgs,
                                        task_type="simple",
                                        model_override=_vision_model,
                                        max_tokens=500,
                                    )
                                    _desc = (
                                        _vision_resp.content
                                        if _vision_resp.content
                                        else "Vision model returned empty response."
                                    )

                                    # Strip base64 from tool result to save context
                                    _tc_data.get("data", {}).pop("image_base64", None)
                                    _tc_data.pop("image_base64", None)
                                    _tc_data["desktop_description"] = _desc
                                    messages[-1]["content"] = json.dumps(_tc_data)

                                    logger.info(
                                        "Desktop vision (%s): %s",
                                        _vision_model,
                                        _desc[:200],
                                    )
                            except Exception as _ve:
                                logger.warning(
                                    "Desktop vision analysis failed: %s", _ve
                                )

                    # --- Auto-screenshot injection (EKO pattern) ---
                    # After state-changing browser actions, use the vision model
                    # to describe the screenshot, then inject text description.
                    # Raw base64 would break non-vision planning models (e.g. glm-4.7).
                    _auto_injected = False
                    if _screenshot_path and Path(_screenshot_path).is_file():
                        _browser_vision = getattr(
                            self._config.browser, "vision_model", ""
                        )
                        if _browser_vision:
                            try:
                                _img_bytes = Path(_screenshot_path).read_bytes()
                                _img_b64 = base64.b64encode(_img_bytes).decode("ascii")
                                _ext = Path(_screenshot_path).suffix.lstrip(".")
                                _mime = "image/png" if _ext == "png" else "image/jpeg"

                                # Detect submit-like actions for enhanced verification
                                _is_submit_action = False
                                if func_name in ("browser_click_text", "browser_click"):
                                    try:
                                        _tc_raw_args = tc["function"].get(
                                            "arguments", "{}"
                                        )
                                        _tc_parsed = (
                                            json.loads(_tc_raw_args)
                                            if isinstance(_tc_raw_args, str)
                                            else _tc_raw_args
                                        )
                                        _click_text = str(
                                            _tc_parsed.get("text", "")
                                        ).lower()
                                        if _click_text in (
                                            "post",
                                            "reply",
                                            "submit",
                                            "publish",
                                            "send",
                                            "tweet",
                                        ):
                                            _is_submit_action = True
                                    except Exception:
                                        pass

                                _bv_prompt = (
                                    "Describe this browser screenshot concisely. "
                                    "Focus on: page title, visible text content, "
                                    "interactive elements (buttons, links, inputs), "
                                    "any dialogs or popups, and errors. "
                                    "Be actionable — mention element positions."
                                )
                                if _is_submit_action:
                                    _bv_prompt += (
                                        "\n\nIMPORTANT: This screenshot was taken AFTER clicking "
                                        "a submit/post/reply button. Carefully verify: "
                                        "Did the submission SUCCEED? Look for: "
                                        "success toast ('Your post was sent'), compose modal CLOSED, "
                                        "content visible in timeline/thread. "
                                        "Or did it FAIL? Look for: compose modal STILL OPEN, "
                                        "a NEW compose modal appeared (wrong button was clicked), "
                                        "'Discard' button visible, empty composer. "
                                        "State clearly whether the submission succeeded or failed."
                                    )
                                if _elements_text:
                                    _bv_prompt += (
                                        f"\n\nPage elements:\n{_elements_text}"
                                    )
                                _bv_msgs = [
                                    {
                                        "role": "user",
                                        "content": [
                                            {
                                                "type": "image_url",
                                                "image_url": {
                                                    "url": f"data:{_mime};base64,{_img_b64}",
                                                },
                                            },
                                            {
                                                "type": "text",
                                                "text": _bv_prompt,
                                            },
                                        ],
                                    }
                                ]
                                _bv_resp = await self._router.complete(
                                    _bv_msgs,
                                    task_type="simple",
                                    model_override=_browser_vision,
                                    max_tokens=500,
                                )
                                _bv_desc = (
                                    _bv_resp.content
                                    if _bv_resp.content
                                    else "[Vision model returned empty response]"
                                )
                                # Append bridge recommended_actions if available
                                _inject_content = f"Page after {func_name}:\n{_bv_desc}"
                                if _recommended_actions:
                                    _ra_lines = []
                                    for _ra_item in _recommended_actions[:3]:
                                        _ra_tool = _ra_item.get("tool", "?")
                                        _ra_args = _ra_item.get("args", {})
                                        _ra_why = _ra_item.get("why", "")
                                        _ra_lines.append(
                                            f"  - {_ra_tool}({json.dumps(_ra_args)}) — {_ra_why}"
                                        )
                                    _inject_content += (
                                        "\n\nBridge recommended next actions:\n"
                                        + "\n".join(_ra_lines)
                                    )
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": _inject_content,
                                    }
                                )
                                _auto_injected = True
                                logger.info(
                                    "Browser vision (%s): %s",
                                    _browser_vision,
                                    _bv_desc[:200],
                                )
                            except Exception as _e:
                                logger.warning("Browser vision analysis failed: %s", _e)
                        else:
                            # No vision model — inject raw image (legacy behavior)
                            try:
                                _img_bytes = Path(_screenshot_path).read_bytes()
                                _img_b64 = base64.b64encode(_img_bytes).decode("ascii")
                                _ext = Path(_screenshot_path).suffix.lstrip(".")
                                _mime = "image/png" if _ext == "png" else "image/jpeg"
                                _obs_parts: list[dict[str, Any]] = [
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:{_mime};base64,{_img_b64}",
                                        },
                                    },
                                ]
                                if _elements_text:
                                    _obs_parts.append(
                                        {
                                            "type": "text",
                                            "text": f"Page after {func_name}:\n{_elements_text}",
                                        }
                                    )
                                messages.append({"role": "user", "content": _obs_parts})
                                _auto_injected = True
                            except Exception as _e:
                                logger.warning("Failed to inject screenshot: %s", _e)
                    if not _auto_injected and _elements_text:
                        # Text-only fallback
                        messages.append(
                            {
                                "role": "user",
                                "content": f"Page after {func_name}:\n{_elements_text}",
                            }
                        )
                        _auto_injected = True

                    # Browser execution state tracking
                    if _browser_state and func_name.startswith("browser_"):
                        _browser_state.after_tool(func_name, raw_result)
                        try:
                            _tc_raw = tc["function"].get("arguments", "{}")
                            _tc_args = (
                                json.loads(_tc_raw)
                                if isinstance(_tc_raw, str)
                                else _tc_raw
                            )
                        except Exception:
                            _tc_args = {}
                        _stag = _browser_state.check_stagnation(func_name, _tc_args)
                        if _stag:
                            messages.append({"role": "user", "content": _stag})
                            logger.info("Browser stagnation: %s", _stag[:100])

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

        # Stagnation/max-steps is a real self-failure — fire frustration
        # so an autonomous loop that keeps hitting the wall feels it.
        asyncio.create_task(self._emit_task_outcome_affect(success=False))

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
        """Execute a task goal for a scheduled task.

        Pass-through to ``self.run`` with a gateway-broadcasting
        ``on_step`` hook so the dashboard / web UI can see step-by-step
        activity while the scheduled task is running. Without this,
        scheduled tasks ran silently for minutes and operators saw
        nothing between the "scheduled task started" and "completed"
        markers. Concurrency safety lives in ``TaskScheduler._run_one``
        (resource-typed semaphores); see ``docs/74-CONCURRENCY-MIGRATION.md``.
        """
        # Broadcast STEP_PROGRESS via the gateway so the dashboard's
        # activity lane shows step number + tool + truncated thought
        # while the task runs. session_id="" because scheduled tasks
        # are not bound to a chat session; the dashboard subscribes
        # to all events regardless.
        prev_on_step = self._on_step

        async def _broadcast_step(
            step: int, tool_name: str, thought: str, params: dict[str, Any]
        ) -> None:
            if self._gateway is None:
                return
            try:
                from core.protocol import EventType, event_message

                await self._gateway.broadcast(
                    event_message(
                        "",
                        EventType.STEP_PROGRESS,
                        {
                            "step": step,
                            "tool_name": tool_name,
                            "thought": (thought or "")[:200],
                            "source": "scheduled",
                            "goal": goal[:80],
                        },
                    )
                )
            except Exception:
                # Best-effort observability; never fail the task because
                # the dashboard couldn't render the event.
                pass

        # Diagnostic: log task_goal length + head at run start so future
        # task_goal regressions are visible immediately. On 2026-05-15 a
        # decline in posting was traced to the task_goal text accumulating
        # cascading SKIP-permissions; without this log we needed to grep
        # the live DB to spot it.
        _tracked_tool_calls: list[str] = []
        logger.info(
            "[sched-task] starting (goal len=%d, head=%r)",
            len(goal),
            goal[:200].replace("\n", " "),
        )
        _start_ts = _time.monotonic()

        # Wrap _broadcast_step to also track tool calls for the
        # bail-out detection in the finally block below.
        async def _tracked_step(
            step: int, tool_name: str, thought: str, params: dict[str, Any]
        ) -> None:
            _tracked_tool_calls.append(tool_name)
            await _broadcast_step(step, tool_name, thought, params)

        self._on_step = _tracked_step
        # Set the cross-schedule mutation guard. Inside this contextvar
        # scope, tools/scheduling/list_tool.py refuses enable / disable /
        # stop / delete / stop_all and tools/scheduling/schedule_tool.py
        # refuses create. A schedule must NOT modify another schedule —
        # the scheduler queues them; they don't get to meddle.
        _sched_token = _in_scheduled_task.set(True)
        try:
            return await self.run(goal, is_user_input=False)
        finally:
            self._on_step = prev_on_step
            _in_scheduled_task.reset(_sched_token)
            # Diagnostic: warn when a scheduled task completes suspiciously
            # fast without doing real work. The "bailed at preflight"
            # failure mode (read a skill, list schedules, declare complete
            # in 20s) is what hid yesterday's posting regression — make
            # it impossible to miss in future logs.
            _elapsed = _time.monotonic() - _start_ts
            _ACTIONLESS_TOOLS = {
                "skill_read",
                "schedule_list",
                "knowledge_search",
                "session_search",
                "tool_discover",
                "file_list",
                "file_read",
            }
            _real_action = any(t not in _ACTIONLESS_TOOLS for t in _tracked_tool_calls)
            if _elapsed < 30.0 and not _real_action:
                logger.warning(
                    "[sched-task] BAIL-OUT detected: completed in %.1fs "
                    "with only preflight tools (%s) — task likely "
                    "interpreted its rules as 'nothing to do.' Goal head: %r",
                    _elapsed,
                    _tracked_tool_calls,
                    goal[:200].replace("\n", " "),
                )

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

    @staticmethod
    def _extract_file_paths(text: str) -> list[str]:
        """Extract file paths from goal text (e.g. core/gateway.py, channels/*.py)."""
        import re

        # Match paths like core/gateway.py, src/utils/foo.ts, channels/*.py
        pattern = r'(?:^|[\s"\'`(,])([a-zA-Z0-9_.*/\-]+(?:\.[a-zA-Z]{1,5}))'
        matches = re.findall(pattern, text)
        # Filter to paths that look like actual file references (contain /)
        return [m for m in matches if "/" in m]

    async def _search_by_file_pattern(
        self, file_paths: list[str]
    ) -> list[dict[str, Any]]:
        """Find knowledge chunks whose covers patterns match the given file paths."""
        import fnmatch

        if not file_paths or not self._db:
            return []

        rows = await self._db.execute(
            "SELECT DISTINCT file_path, heading_path, content, covers, scope, tags "
            "FROM knowledge_chunks WHERE covers != '[]'"
        )

        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        for row in rows:
            try:
                covers = json.loads(row["covers"])
            except (json.JSONDecodeError, TypeError):
                continue
            if not covers:
                continue

            matched = False
            for pattern in covers:
                for fp in file_paths:
                    if fnmatch.fnmatch(fp, pattern):
                        matched = True
                        break
                if matched:
                    break

            if matched:
                key = f"{row['file_path']}:{row['heading_path']}"
                if key not in seen:
                    seen.add(key)
                    results.append(
                        {
                            "content": row["content"],
                            "source": row["file_path"],
                            "heading": row["heading_path"],
                            "score": 0.8,
                            "scope": row["scope"],
                            "tags": json.loads(row["tags"]) if row["tags"] else [],
                        }
                    )

        return results

    async def _auto_retrieve(self, query: str) -> None:
        """Fetch relevant knowledge chunks and recent task memory for the query.

        Runs knowledge search, memory search, and file-pattern search in parallel.
        Always includes recent tasks so the LLM knows what it already did.
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

        async def _search_memory() -> tuple[list[dict], list[dict]]:
            """Return (keyword_matches, recent_tasks) — both, not either/or."""
            keyword: list[dict] = []
            recent: list[dict] = []
            try:
                keyword = await self._memory_manager.search_memory(query, limit=3)
            except Exception:
                pass
            try:
                recent = await self._memory_manager.get_recent_tasks(limit=10)
            except Exception:
                pass
            return keyword, recent

        async def _search_file_patterns() -> list[dict[str, Any]]:
            paths = self._extract_file_paths(query)
            if paths:
                return await self._search_by_file_pattern(paths)
            return []

        async def _safe(coro, default):
            try:
                return await asyncio.wait_for(coro, timeout=3.0)
            except Exception:
                return default

        chunks, (keyword_mems, recent_mems), file_chunks = await asyncio.gather(
            _safe(_search_knowledge(), []),
            _safe(_search_memory(), ([], [])),
            _safe(_search_file_patterns(), []),
        )

        # Merge file-pattern results with semantic results (dedup by source+heading)
        if file_chunks:
            existing = {(c.get("source", ""), c.get("heading", "")) for c in chunks}
            for fc in file_chunks:
                key = (fc.get("source", ""), fc.get("heading", ""))
                if key not in existing:
                    chunks.append(fc)
                    existing.add(key)

        if chunks:
            self._working_memory.add_chunks(chunks)

        # Merge keyword matches + recent (dedup by goal+timestamp)
        seen: set[str] = set()
        all_mems: list[dict[str, Any]] = []
        for mem in keyword_mems + recent_mems:
            key = f"{mem['goal']}:{mem.get('created_at', '')}"
            if key not in seen:
                seen.add(key)
                all_mems.append(mem)

        if all_mems:
            memory_chunks = []
            for mem in all_mems[:10]:
                tools = ", ".join(mem.get("tools_used", [])[:8])
                content = (
                    f"Task: {mem['goal']}\n"
                    f"Outcome: {mem['outcome']}\n"
                    f"Summary: {mem['summary'][:800]}\n"
                    f"Tools used: {tools}\n"
                    f"When: {mem.get('created_at', 'unknown')}"
                )
                memory_chunks.append(
                    {
                        "source": "task_memory",
                        "heading": f"Past task: {mem['goal'][:100]}",
                        "content": content,
                    }
                )
            self._working_memory.add_chunks(memory_chunks)

    async def _verify_browser_task(
        self, goal: str, agent_response: str
    ) -> dict[str, Any] | None:
        """Verify browser task completion with a separate LLM call.

        Takes a screenshot and asks a fast model whether the task is done.
        Returns {"complete": bool, "reason": str} or None on failure.
        """
        try:
            result = await self._browser_manager.call_tool("browser_screenshot", {})
            _saved = result.get("savedScreenshotPath") or result.get("screenshotPath")
            if not _saved or not Path(_saved).is_file():
                return None

            _img_bytes = Path(_saved).read_bytes()
            _img_b64 = base64.b64encode(_img_bytes).decode("ascii")

            verify_messages: list[dict[str, Any]] = [
                {
                    "role": "system",
                    "content": (
                        "You verify whether a browser task is complete. "
                        "Look at the screenshot and answer."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{_img_b64}",
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                f"TASK: {goal}\n\n"
                                f"AGENT SAYS: {agent_response[:500]}\n\n"
                                "Is this task complete based on the "
                                "screenshot? Reply EXACTLY:\n"
                                "COMPLETE: <reason>\n"
                                "or INCOMPLETE: <reason>"
                            ),
                        },
                    ],
                },
            ]

            resp = await self._router.complete(
                messages=verify_messages,
                task_type="simple",
                tools=None,
                temperature=0.1,
                max_tokens=200,
            )

            text = (resp.content or "").strip()
            if text.upper().startswith("COMPLETE"):
                return {"complete": True, "reason": text}
            elif text.upper().startswith("INCOMPLETE"):
                reason = text.split(":", 1)[1].strip() if ":" in text else text
                return {"complete": False, "reason": reason}
            # Ambiguous — accept as complete to avoid loops
            return {"complete": True, "reason": text}
        except Exception as e:
            logger.warning("Browser task verification failed: %s", e)
            return None

    async def _store_task_memory(
        self,
        goal: str,
        summary: str,
        outcome: str,
        tools_used: list[str],
    ) -> None:
        """Store task completion in long-term memory and extract lessons."""
        unique_tools = list(set(tools_used))
        try:
            await self._memory_manager.store_task_memory(
                session_id=self._working_memory.session_id,
                goal=goal,
                summary=summary,
                outcome=outcome,
                tools_used=unique_tools,
            )
        except Exception as e:
            logger.debug(f"Failed to store task memory: {e}")

        # Extract reusable lessons — fire-and-forget, non-blocking
        if self._learner:
            asyncio.create_task(
                self._learner.extract_and_store(goal, summary, outcome, unique_tools)
            )

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

    async def _record_ego_outcome(
        self, goal: str, tools_used: list[str], success: bool
    ) -> None:
        """Record per-capability outcomes for the ego layer.

        Maps each tool actually used to a coarse capability label and records
        an outcome against it. Triggers a self-image recompute when enough
        outcomes have accumulated.
        """
        if not self._ego_manager:
            return
        try:
            capability = _capability_from_tools(tools_used)
            if not capability:
                return
            await self._ego_manager.record_outcome(
                capability=capability, success=success, task_goal=goal
            )
            identity_summary = ""
            if self._identity_manager:
                identity = await self._identity_manager.get_identity()
                identity_summary = (
                    f"display_name: {identity.display_name}\n"
                    f"purpose: {identity.purpose or ''}\n"
                    f"values: {', '.join(identity.values[-8:])}\n"
                    f"capabilities: {', '.join(identity.capabilities[-10:])}"
                )
            await self._ego_manager.maybe_recompute(identity_summary)
        except Exception as e:
            logger.debug("Ego outcome recording failed: %s", e)

    async def _emit_task_outcome_affect(self, success: bool) -> None:
        """Outcome-based affect: fires on every task end, regardless of who
        kicked off the task (user OR autonomous loop). This is the path
        through which the agent feels its own self-improvement work — it
        gets pissed at itself when its scheduled review fails, satisfied
        when it lands. Distinct from the user-correction regex, which
        only fires on actual user messages.

        Magnitudes are picked so that a single real win/loss outweighs
        many trivial completions; satisfaction does NOT compound.
        Best-effort, fire-and-forget; never raises.
        """
        if self._affect_manager is None:
            return
        try:
            from core.affect import emit_frustration, emit_satisfaction

            if success:
                await emit_satisfaction(self._affect_manager, source="task")
            else:
                await emit_frustration(self._affect_manager, source="task")
        except Exception as e:
            logger.debug("Task-outcome affect emit failed: %s", e)

    async def _record_ego_correction(self, user_message: str) -> None:
        """Run the user-correction detector against the incoming message.

        Fire-and-forget; never raises. The detector is pattern-based (no
        LLM call) so this is cheap. Attribution defaults to whatever
        capability the agent used in the previous turn — corrections
        almost always reference the immediately preceding action.
        """
        if not self._ego_manager:
            return
        try:
            await self._ego_manager.record_correction(user_message=user_message)
        except Exception as e:
            logger.debug("Ego correction detection failed: %s", e)

    async def _record_ego_verification(
        self, response_text: str, tools_used: list[str], goal: str
    ) -> None:
        """Scan the agent's final response for a Verification block and
        feed the verdict (PASS/FAIL/UNKNOWN) into the ego layer.

        FAIL → humbling event + failure outcome (strong signal).
        UNKNOWN → soft-fail outcome (the agent couldn't confirm).
        PASS → a verification-grade success outcome.
        """
        if not self._ego_manager:
            return
        try:
            capability = _capability_from_tools(tools_used) or ""
            await self._ego_manager.record_verification(
                agent_response=response_text,
                capability=capability,
                task_goal=goal,
            )
        except Exception as e:
            logger.debug("Ego verification scan failed: %s", e)

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
            # Normalize keys — some models return {"\"is_directive\"": ...} with embedded quotes
            if isinstance(result, dict):
                result = {k.strip('"').strip("'"): v for k, v in result.items()}

            if not result.get("is_directive"):
                return

            directive_text = result.get("directive", "").strip()
            key = result.get("key", "directive").strip()
            if not directive_text:
                return

            # Scan directive for injection before persisting
            from core.injection_guard import scan_for_injection

            is_suspicious, patterns = scan_for_injection(directive_text)
            if is_suspicious:
                logger.warning(
                    "Blocked directive with injection patterns (%s): %s",
                    ", ".join(patterns),
                    directive_text[:100],
                )
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
