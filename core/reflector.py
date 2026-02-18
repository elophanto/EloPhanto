"""Post-action reflection and evaluation.

For Phase 0, the reflector handles terminal error conditions.
Real reflection (deciding if the task is complete) is embedded in the
planning LLM call — the tool result is fed back and the LLM decides.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.executor import ExecutionResult


@dataclass
class ReflectionResult:
    """Outcome of reflection on a tool execution."""

    is_complete: bool
    summary: str
    should_continue: bool = True
    error: str | None = None


class Reflector:
    """Evaluates tool execution results for terminal conditions."""

    def reflect(self, execution_result: ExecutionResult) -> ReflectionResult:
        """Evaluate the result of a tool execution."""
        if execution_result.denied:
            return ReflectionResult(
                is_complete=False,
                summary=f"Tool '{execution_result.tool_name}' was denied by user.",
                should_continue=True,
            )

        if execution_result.error:
            return ReflectionResult(
                is_complete=False,
                summary=f"Tool '{execution_result.tool_name}' failed: {execution_result.error}",
                should_continue=True,
            )

        if execution_result.result and execution_result.result.success:
            return ReflectionResult(
                is_complete=False,
                summary=f"Tool '{execution_result.tool_name}' succeeded.",
                should_continue=True,
            )

        # Tool returned but with success=False
        error_msg = ""
        if execution_result.result:
            error_msg = execution_result.result.error or "unknown error"
        return ReflectionResult(
            is_complete=False,
            summary=f"Tool '{execution_result.tool_name}' returned an error: {error_msg}",
            should_continue=True,
        )
