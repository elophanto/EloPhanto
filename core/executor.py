"""Tool execution orchestration.

Takes a tool call from the planner, validates it, checks permissions,
and executes the tool. Supports external permission overrides via
permissions.yaml and a persistent approval queue.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

import yaml

from core.config import Config
from core.registry import ToolRegistry
from tools.base import BaseTool, PermissionLevel, ToolResult

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

        # Execute
        try:
            logger.info(f"Executing tool '{tool_name}' with params: {params}")
            result = await tool.execute(params)
            return ExecutionResult(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                result=result,
            )
        except Exception as e:
            logger.error(f"Tool '{tool_name}' execution failed: {e}")
            return ExecutionResult(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                error=f"Tool execution failed: {e}",
            )

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
