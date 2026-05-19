"""Tool execution orchestration.

Takes a tool call from the planner, validates it, checks permissions,
and executes the tool. Supports external permission overrides via
permissions.yaml and a persistent approval queue.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from core.config import Config
from core.registry import ToolRegistry
from tools.base import BaseTool, PermissionLevel, ToolResult

# ── Pre-Tool Guards ──────────────────────────────────────────────────
# Block or warn before dangerous tool calls. Runs before execution.

_PRETOOL_GUARDS = [
    # Block hardcoded API keys in file writes
    {
        "tool": "file_write",
        "param": "content",
        "pattern": re.compile(
            r"(sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36}|"
            r"AKIA[0-9A-Z]{16}|xox[bpras]-[0-9a-zA-Z-]+)",
        ),
        "action": "block",
        "message": "Blocked: potential API key or secret detected in file content.",
    },
    {
        "tool": "file_patch",
        "param": "new",
        "pattern": re.compile(
            r"(sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36}|"
            r"AKIA[0-9A-Z]{16}|xox[bpras]-[0-9a-zA-Z-]+)",
        ),
        "action": "block",
        "message": "Blocked: potential API key or secret detected in patch content.",
    },
    # Warn before git push
    {
        "tool": "shell_execute",
        "param": "command",
        "pattern": re.compile(r"\bgit\s+push\b"),
        "action": "warn",
        "message": "Pre-tool guard: git push detected. Ensure changes are reviewed.",
    },
    # Warn before npm publish
    {
        "tool": "shell_execute",
        "param": "command",
        "pattern": re.compile(r"\bnpm\s+publish\b"),
        "action": "warn",
        "message": "Pre-tool guard: npm publish detected. Verify package before publishing.",
    },
]

logger = logging.getLogger(__name__)


class ExecutionResult:
    """Result of attempting to execute a tool call."""

    def __init__(
        self,
        tool_name: str,
        tool_call_id: str,
        result: ToolResult | None = None,
        denied: bool = False,
        error: str | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.tool_call_id = tool_call_id
        self.result = result
        self.denied = denied
        self.error = error


def _load_permissions(project_root: Path) -> dict[str, Any]:
    """Load permissions.yaml if it exists."""
    path = project_root / "permissions.yaml"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Failed to load permissions.yaml: {e}")
        return {}


class Executor:
    """Orchestrates tool execution with permission checks."""

    def __init__(self, config: Config, registry: ToolRegistry) -> None:
        self._config = config
        self._registry = registry
        self._approval_callback: Callable[[str, str, dict[str, Any]], bool] | None = (
            None
        )
        self._on_tool_executed: (
            Callable[[str, dict[str, Any], str | None], None] | None
        ) = None
        # Affect handle — set by Agent.initialize() when affect is up.
        # Fire mild anxiety on tool-execution exceptions and on
        # ToolResult.success=False outcomes. See docs/69-AFFECT.md.
        # Typed `Any` to keep executor.py free of affect imports —
        # layering is one-way (executor writes to affect, never reads).
        self._affect_manager: Any = None

        perms = _load_permissions(config.project_root)
        self._tool_overrides: dict[str, str] = perms.get("tool_overrides", {}) or {}
        self._disabled_tools: set[str] = set(perms.get("disabled_tools", []) or [])

    def set_approval_callback(
        self, callback: Callable[[str, str, dict[str, Any]], bool]
    ) -> None:
        """Set the callback for asking user approval.

        Callback signature: (tool_name, description, params) -> approved: bool
        """
        self._approval_callback = callback

    async def execute(
        self,
        tool_call: dict[str, Any],
        approval_callback: Callable[[str, str, dict[str, Any]], bool] | None = None,
    ) -> ExecutionResult:
        """Execute a single tool call from the LLM.

        Args:
            tool_call: Tool call dict from LLM response.
            approval_callback: Optional per-call approval callback. If provided,
                overrides the instance-level callback for this execution only.
                Used by gateway to route approvals to the correct channel.
        """
        func = tool_call.get("function", {})
        tool_name = func.get("name", "")
        tool_call_id = tool_call.get("id", "")

        # Parse arguments
        try:
            raw_args = func.get("arguments", "{}")
            params = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError as e:
            return ExecutionResult(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                error=f"Invalid tool arguments: {e}",
            )

        # Check if tool is disabled via permissions.yaml
        if tool_name in self._disabled_tools:
            return ExecutionResult(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                error=f"Tool '{tool_name}' is disabled in permissions.yaml",
            )

        # Look up tool
        tool = self._registry.get(tool_name)
        if tool is None:
            return ExecutionResult(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                error=f"Unknown tool: {tool_name}",
            )

        # Validate input
        errors = tool.validate_input(params)
        if errors:
            return ExecutionResult(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                error=f"Invalid parameters: {'; '.join(errors)}",
            )

        # Permission check (per-call callback overrides instance-level)
        approved = self._check_permission(
            tool, params, approval_callback=approval_callback
        )
        if not approved:
            logger.info(f"Tool '{tool_name}' denied by user")
            return ExecutionResult(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                denied=True,
            )

        # Reset file read loop tracker when a non-read tool is called
        if tool_name != "file_read":
            from tools.system.filesystem import reset_read_tracker

            reset_read_tracker()

        # Pre-tool guards: block or warn before execution
        for guard in _PRETOOL_GUARDS:
            if guard["tool"] == tool_name:
                param_val = str(params.get(guard["param"], ""))
                pattern = guard["pattern"]
                assert isinstance(pattern, re.Pattern)
                if pattern.search(param_val):
                    if guard["action"] == "block":
                        return ExecutionResult(
                            tool_name=tool_name,
                            tool_call_id=tool_call_id,
                            error=str(guard["message"]),
                        )
                    elif guard["action"] == "warn":
                        logger.warning("[guard] %s", guard["message"])

        # Execute — wrapped in tool-declared resource acquisition.
        # See tools/base.py BaseTool.resources for the contract and
        # core/task_resources.py for the per-session vs per-call split.
        # BROWSER / DESKTOP are acquired session-lazily (first browser
        # tool in a run holds the lock for the rest of the cycle);
        # VAULT_WRITE / LLM_BURST are acquired around just this call.
        try:
            logger.info(f"Executing tool '{tool_name}' with params: {params}")
            tool_resources = getattr(tool, "resources", frozenset())
            if tool_resources:
                result = await self._execute_with_resources(
                    tool, params, tool_resources
                )
            else:
                # No declared resources — invoke directly. Same as
                # legacy behavior for tools that don't contend.
                result = await tool.execute(params)
            if self._on_tool_executed:
                try:
                    self._on_tool_executed(tool_name, params, None)
                except Exception:
                    pass
            # Affect: a clean exception didn't fire, but the tool may
            # have returned success=False. Treat that as mild anxiety —
            # softer than an exception, but still a failure signal that
            # should color the next response.
            if (
                self._affect_manager is not None
                and result is not None
                and getattr(result, "success", True) is False
            ):
                await self._fire_affect_safe("anxiety", "executor")

            # Content-affect inference: scan the tool result for
            # high-signal phrases (scam DMs, hostile replies, warm
            # praise) and fire affect events. Closes the content
            # boundary that the LLM-callable ``affect_record_event``
            # tool was supposed to cover but isn't used in practice
            # (0 calls in 17h of production). See
            # ``core/affect_content_inference.py``.
            if (
                self._affect_manager is not None
                and result is not None
                and getattr(result, "success", True)
            ):
                await self._infer_content_affect(tool_name, params, result)

            return ExecutionResult(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                result=result,
            )
        except Exception as e:
            logger.error(f"Tool '{tool_name}' execution failed: {e}")
            if self._on_tool_executed:
                try:
                    self._on_tool_executed(tool_name, params, str(e))
                except Exception:
                    pass
            # Affect: an unhandled exception is the strongest tool-side
            # failure signal. Fire anxiety at full weight.
            if self._affect_manager is not None:
                await self._fire_affect_safe("anxiety", "executor")
            return ExecutionResult(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                error=f"Tool execution failed: {e}",
            )

    async def _execute_with_resources(
        self,
        tool: Any,
        params: dict[str, Any],
        tool_resources: frozenset[Any],
    ) -> Any:
        """Invoke ``tool.execute(params)`` with proper resource acquisition.

        Splits the tool's declared resources into:
          - session-lazy (BROWSER, DESKTOP) — acquired once per
            agent.run() via the ResourceLeaseScope and held until
            the run exits, so multi-step workflows stay coherent.
          - per-call (VAULT_WRITE, LLM_BURST) — acquired around just
            this invocation, released as soon as it returns.

        Skipped silently when no ResourceLeaseScope is on the
        contextvar (test harness, direct-tool fast path) — calling
        the tool directly preserves backward compatibility.
        """
        from core.task_resources import (
            _PER_CALL_RESOURCES,
            _SESSION_LAZY_RESOURCES,
            current_scope,
        )

        scope = current_scope()
        if scope is None:
            # No active scope — caller didn't open one. Fall back to
            # the legacy direct invocation. Documented in the
            # current_scope() docstring.
            return await tool.execute(params)

        # Session-lazy resources: ensure each is held by the scope.
        # ensure_held is idempotent — second call for the same
        # resource within the same scope is a no-op.
        for resource in tool_resources:
            if resource in _SESSION_LAZY_RESOURCES:
                await scope.ensure_held(resource)

        # Per-call resources: acquire around just this invocation.
        per_call = [r for r in tool_resources if r in _PER_CALL_RESOURCES]
        if per_call:
            async with scope.per_call_acquire(per_call):
                return await tool.execute(params)
        return await tool.execute(params)

    async def _fire_affect_safe(self, label: str, source: str) -> None:
        """Best-effort affect emission. Never raises — affect failure
        must not break tool execution. Handles the import indirection so
        executor.py stays free of affect imports at module top level."""
        try:
            from core.affect import (
                emit_anger,
                emit_anxiety,
                emit_frustration,
                emit_joy,
                emit_relief,
            )

            emitters = {
                "anxiety": emit_anxiety,
                "anger": emit_anger,
                "frustration": emit_frustration,
                "joy": emit_joy,
                "relief": emit_relief,
            }
            emitter = emitters.get(label)
            if emitter is not None:
                await emitter(self._affect_manager, source=source)
        except Exception as e:  # pragma: no cover — defensive
            logger.debug("Affect emit (%s) from executor failed: %s", label, e)

    async def _infer_content_affect(
        self,
        tool_name: str,
        params: dict[str, Any],
        result: Any,
    ) -> None:
        """Run content-affect inference on a tool result and emit
        suggested affect events. Best-effort — never raises. The
        inference module is pure / regex-only (no LLM call, no I/O),
        so the cost is negligible per tool call. See
        ``core/affect_content_inference.py``."""
        try:
            from core.affect import _LABEL_VECTORS
            from core.affect_content_inference import infer_from_tool_result

            # Identity tokens for the self-relevance amplifier. "Scam in
            # MY DMs" must fire harder than "scam screenshot in someone
            # else's thread"; without this gate both fire identically.
            # We pass the agent's configured name; the inference module
            # case-folds when matching, so "elophanto" / "EloPhanto" /
            # "@elophanto" all amplify.
            identities: tuple[str, ...] = ()
            agent_name = getattr(self._config, "agent_name", "") or ""
            if agent_name:
                identities = (agent_name,)

            suggestions = infer_from_tool_result(
                tool_name, params, result, identities=identities
            )
            for sug in suggestions:
                # Look up canonical PAD vector for the label. We move
                # toward it at fixed scale; the per-pattern weight and
                # repeat-compounding live inside record_event.
                vec = _LABEL_VECTORS.get(sug.label)
                if vec is None:
                    continue
                p_target, a_target, d_target = vec
                # Source tag: "content:browser" / "content:email" so the
                # audit trail tells the operator where mood came from.
                # Falls back to bare "content" if the tool isn't routed.
                source = (
                    f"content:{sug.source_suffix}" if sug.source_suffix else "content"
                )
                # Direction-only scaling — match the emit_* helpers'
                # ~0.2-magnitude deltas. The label vector is a target
                # in PAD space; we move toward it at scaled magnitude.
                scale = 0.4
                await self._affect_manager.record_event(
                    label=f"{sug.label}: {sug.summary[:120]}",
                    source=source,
                    pleasure_delta=p_target * scale,
                    arousal_delta=a_target * scale,
                    dominance_delta=d_target * scale,
                    weight=sug.weight,
                )
                logger.info(
                    "[affect-content] %s w=%.2f src=%s (from %s): %s",
                    sug.label,
                    sug.weight,
                    source,
                    tool_name,
                    sug.summary,
                )
        except Exception as e:  # pragma: no cover — defensive
            logger.debug("Content-affect inference failed for %s: %s", tool_name, e)

    def _check_permission(
        self,
        tool: BaseTool,
        params: dict[str, Any],
        approval_callback: Callable[[str, str, dict[str, Any]], bool] | None = None,
    ) -> bool:
        """Check if execution is permitted, respecting per-tool overrides.

        Args:
            approval_callback: Per-call override for the instance-level callback.
                Used by gateway to route approvals to the correct channel session.
        """
        callback = approval_callback or self._approval_callback
        override = self._tool_overrides.get(tool.name)

        if override == "auto":
            return True
        if override == "ask":
            if callback:
                description = self._format_approval_request(tool, params)
                return callback(tool.name, description, params)
            return False

        # Default behavior: follow global permission mode
        if tool.permission_level == PermissionLevel.SAFE:
            return True

        if self._config.permission_mode == "full_auto":
            return True

        if self._config.permission_mode == "smart_auto":
            if tool.name == "shell_execute" and hasattr(tool, "is_safe_command"):
                if tool.is_safe_command(params.get("command", "")):
                    return True

        if callback:
            description = self._format_approval_request(tool, params)
            return callback(tool.name, description, params)

        return False

    def _format_approval_request(self, tool: BaseTool, params: dict[str, Any]) -> str:
        """Format a human-readable description of what the tool wants to do."""
        if tool.name == "shell_execute":
            return f"Run shell command: {params.get('command', '?')}"
        if tool.name == "file_write":
            return f"Write to file: {params.get('path', '?')}"
        if tool.name == "file_delete":
            return f"Delete: {params.get('path', '?')}"
        if tool.name == "file_move":
            return (
                f"Move {params.get('source', '?')} → {params.get('destination', '?')}"
            )
        return f"Execute {tool.name}"
