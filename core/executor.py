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
    """Load permissions.yaml; Hosted also merges permissions.hosted.yaml."""
    path = project_root / "permissions.yaml"
    data: dict[str, Any] = {}
    if path.exists():
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load permissions.yaml: {e}")
            data = {}
    try:
        from core.hosted import is_hosted

        if is_hosted():
            hosted_path = project_root / "permissions.hosted.yaml"
            if not hosted_path.exists():
                raise FileNotFoundError(
                    f"Hosted refuse-start: {hosted_path} missing — "
                    "image must ship permissions.hosted.yaml"
                )
            with open(hosted_path) as f:
                hosted = yaml.safe_load(f) or {}
            overrides = dict(data.get("tool_overrides") or {})
            overrides.update(hosted.get("tool_overrides") or {})
            disabled = list(data.get("disabled_tools") or [])
            for t in hosted.get("disabled_tools") or []:
                if t not in disabled:
                    disabled.append(t)
            data["tool_overrides"] = overrides
            data["disabled_tools"] = disabled
    except FileNotFoundError:
        raise
    except Exception as e:
        from core.hosted import is_hosted

        if is_hosted():
            raise RuntimeError(
                f"Hosted refuse-start: failed merging permissions.hosted.yaml: {e}"
            ) from e
        logger.warning(f"Failed to merge permissions.hosted.yaml: {e}")
    return data


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
        # Fired after a successful execution WITH the result, so a receipt
        # trail can see what a tool answered — not only what it was asked.
        self._on_tool_result: Callable[[str, dict[str, Any], Any], None] | None = None
        # Affect handle — set by Agent.initialize() when affect is up.
        # Fire mild anxiety on tool-execution exceptions and on
        # ToolResult.success=False outcomes. See docs/69-AFFECT.md.
        # Typed `Any` to keep executor.py free of affect imports —
        # layering is one-way (executor writes to affect, never reads).
        self._affect_manager: Any = None
        # Ego soft-gate — when set, should_attempt(decline) forces an
        # approval ask even under full_auto (behavior-shaping shame).
        self._ego_manager: Any = None
        # ABE Phase 2: role gate handle — set by Agent after construction.
        # When None, role gating is inert (every tool passes through to
        # the standard permission check). When set, the executor consults
        # the current_role contextvar before each call and denies tools
        # outside the role's allowlist. See docs/76-ABE-FRAMEWORK.md.
        self._role_manager: Any = None

        perms = _load_permissions(config.project_root)
        self._tool_overrides: dict[str, str] = perms.get("tool_overrides", {}) or {}
        self._disabled_tools: set[str] = set(perms.get("disabled_tools", []) or [])

    async def _ego_confidence(self, capability: str) -> float:
        """Current confidence for a capability, for the approval message.

        Best-effort: the number is explanatory only, so a failure here must
        never change whether the tool runs.
        """
        try:
            ego = await self._ego_manager.get_ego()
            return float(ego.confidence.get(capability, 0.5))
        except Exception:
            return 0.5

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

        # Hosted L8: owner spend freeze blocks money tools hard (fail-closed).
        from core.kill_switch import is_spend_frozen, resolve_data_dir

        _MONEY_PREFIXES = ("crypto_", "wallet_", "fiat_")
        _MONEY_TOOLS = frozenset(
            {
                "crypto_transfer",
                "crypto_swap",
                "wallet_export",
                "wallet_send",
                "fiat_payout",
                "fiat_transfer",
                "card_create",
                "payment_send",
            }
        )
        if tool_name in _MONEY_TOOLS or tool_name.startswith(_MONEY_PREFIXES):
            try:
                data_dir = resolve_data_dir(self._config)
            except Exception as e:
                return ExecutionResult(
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    error=f"Spend freeze check failed (fail-closed): {e}",
                )
            if is_spend_frozen(data_dir):
                return ExecutionResult(
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    error=(
                        "Spend freeze is active (owner control). "
                        "Unfreeze before any payment or wallet action."
                    ),
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

        # ABE Phase 2: role gate. Runs BEFORE the generic permission
        # check so a role-deny short-circuits even when permission_mode
        # would auto-approve. Inert when no role_manager is wired or no
        # role is active (the default — EloPhanto plays CEO with no
        # constraint). Lookup failures degrade open (logged at debug)
        # so a broken role config can't paralyse tool execution.
        if self._role_manager is not None:
            from core.role import RoleManager
            from core.role_context import current_role

            role_name = current_role()
            if role_name:
                try:
                    role = await self._role_manager.get(role_name)
                except Exception as e:
                    logger.debug("role gate: lookup of %r failed: %s", role_name, e)
                    role = None
                if role is not None and not RoleManager.is_tool_allowed(
                    role, tool_name, getattr(tool, "group", None)
                ):
                    logger.info(
                        "Tool '%s' denied by role gate (role=%s)",
                        tool_name,
                        role_name,
                    )
                    return ExecutionResult(
                        tool_name=tool_name,
                        tool_call_id=tool_call_id,
                        denied=True,
                        error=(
                            f"Tool {tool_name!r} not in role "
                            f"{role_name!r} allowlist"
                        ),
                    )

        # Permission check (per-call callback overrides instance-level).
        # ApprovalTimeoutPause propagates so goal/mind runners can pause
        # as awaiting_approval instead of treating timeout as deny.
        approved = await self._check_permission(
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
            tool_resources: frozenset[Any] = getattr(tool, "resources", frozenset())
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
            if self._on_tool_result:
                try:
                    self._on_tool_result(tool_name, params, result)
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

    async def _check_permission(
        self,
        tool: BaseTool,
        params: dict[str, Any],
        approval_callback: Callable[[str, str, dict[str, Any]], bool] | None = None,
    ) -> bool:
        """Check if execution is permitted, respecting per-tool overrides.

        Args:
            approval_callback: Per-call override for the instance-level callback.
                Used by gateway to route approvals to the correct channel session.

        CRITICAL tools always require approval under ``full_auto`` —
        wallet/self-mod/swap must never auto-fire unattended there.
        ``nuclear`` is the explicit escape hatch: no approval prompts
        at all (CRITICAL included). Only ``tool_overrides: ask`` still
        forces a prompt.
        """
        import inspect

        callback = approval_callback or self._approval_callback
        override = self._tool_overrides.get(tool.name)

        # Per-call permission override. Tools whose risk depends on their
        # arguments (http_request: GET vs DELETE, owned host vs foreign)
        # raise or lower their own tier here. A broken classifier must not
        # be able to block work, so failures fall back to the static tier.
        effective_level = tool.permission_level
        try:
            dynamic = tool.dynamic_permission_level(params)
            # Only honour a genuine PermissionLevel. A tool that returns
            # anything else (a bug, a mock, a stale string) must not be able
            # to slip past the CRITICAL gate by making the comparisons below
            # silently false — an unrecognised value keeps the static tier.
            if isinstance(dynamic, PermissionLevel):
                effective_level = dynamic
            elif dynamic is not None:
                logger.warning(
                    "%s.dynamic_permission_level returned %r (%s), not a "
                    "PermissionLevel — keeping the static tier %s",
                    tool.name,
                    dynamic,
                    type(dynamic).__name__,
                    effective_level,
                )
        except Exception as e:  # pragma: no cover — defensive
            logger.debug("dynamic_permission_level failed for %s: %s", tool.name, e)

        from core.hosted import clamp_permission_mode, is_hosted

        # Hosted L1: never honor nuclear even if config was smuggled in.
        mode = clamp_permission_mode(self._config.permission_mode)
        if is_hosted() and self._config.permission_mode == "nuclear":
            self._config.permission_mode = mode

        async def _ask(reason: str = "") -> bool:
            if not callback:
                return False
            description = self._format_approval_request(tool, params)
            if reason:
                # Say WHY this is being asked. A bare "approve browser_navigate?"
                # under full_auto reads as a bug; the operator needs to see that
                # the ego gate fired and on what evidence, or they cannot tell a
                # deliberate caution from a broken permission mode.
                description = f"{description}\n{reason}"
            result = callback(tool.name, description, params)
            if inspect.isawaitable(result):
                return bool(await result)
            return bool(result)

        # Explicit per-tool ask is the only hard stop that survives nuclear.
        if override == "ask":
            return await _ask()

        # nuclear: operator opted out of ALL approval prompts, including
        # CRITICAL (browser_eval, wallet, trust promotion, etc.).
        if mode == "nuclear":
            return True

        if override == "auto":
            # Explicit per-tool auto still wins — except CRITICAL, which
            # is never auto under non-nuclear modes.
            if effective_level == PermissionLevel.CRITICAL:
                return await _ask()
            return True

        # SAFE tools always run.
        if effective_level == PermissionLevel.SAFE:
            return True

        # CRITICAL always asks — even under full_auto (docs + plan).
        if effective_level == PermissionLevel.CRITICAL:
            return await _ask()

        # Ego soft-gate: when confidence says decline (or caution rule
        # forces ask), require approval even in full_auto. This is the
        # behavioral proof that shame changes what the agent attempts.
        soft_gate_on = getattr(getattr(self._config, "ego", None), "soft_gate", True)
        if (
            soft_gate_on
            and self._ego_manager is not None
            and effective_level
            in (
                PermissionLevel.MODERATE,
                PermissionLevel.CRITICAL,
            )
        ):
            try:
                from core.ego import capability_for_tool

                capability = capability_for_tool(tool.name)
                # Harder default for money / outreach domains.
                difficulty = {
                    "payments": 0.75,
                    "outreach": 0.65,
                    "social": 0.65,
                    "browser": 0.55,
                }.get(capability, 0.5)
                verdict = await self._ego_manager.should_attempt(
                    capability, difficulty=difficulty
                )
                conf = await self._ego_confidence(capability)
                reason = (
                    f"⚑ Ego gate ({verdict}): '{capability}' confidence "
                    f"{conf:.2f} vs difficulty {difficulty:.2f}. Asking despite "
                    f"{mode}. "
                    f"Confidence rises ~0.05 per success; set "
                    f"ego.soft_gate: false in config.yaml to disable this gate."
                )
                if verdict == "decline":
                    logger.info(
                        "Ego soft-gate: decline on %s (%s, conf=%.2f vs %.2f) "
                        "— forcing approval ask",
                        tool.name,
                        capability,
                        conf,
                        difficulty,
                    )
                    return await _ask(reason)
                if verdict == "ask" and mode == "full_auto":
                    logger.info(
                        "Ego soft-gate: ask on %s (%s, conf=%.2f vs %.2f) "
                        "— overriding full_auto",
                        tool.name,
                        capability,
                        conf,
                        difficulty,
                    )
                    return await _ask(reason)
            except Exception as e:
                logger.debug("Ego soft-gate skipped: %s", e)

        if mode == "full_auto":
            return True

        if mode == "smart_auto":
            if tool.name == "shell_execute" and hasattr(tool, "is_safe_command"):
                if tool.is_safe_command(params.get("command", "")):
                    return True

        return await _ask()

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
        if tool.name == "http_request":
            method = str(params.get("method", "GET") or "GET").upper()
            url = params.get("url", "?")
            line = f"{method} {url}"
            if params.get("credential"):
                line += f"\nAuthenticating as: {params['credential']}"
            if params.get("reason"):
                line += f"\nReason: {params['reason']}"
            # Surface the ownership verdict — the operator is being asked
            # precisely because the target may not be theirs.
            guard = getattr(tool, "_scope_guard", None)
            if guard is not None:
                try:
                    from urllib.parse import urlparse

                    verdict = guard.assess(
                        str(url), method, urlparse(str(url)).path or "/"
                    )
                    line += f"\nTarget scope: {verdict.scope} — {verdict.reason}"
                except Exception:
                    pass
            return line
        return f"Execute {tool.name}"
