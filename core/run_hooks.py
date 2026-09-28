"""Per-task executor hooks for background loops.

The autonomous mind, heartbeat, AutoLoop and goal runner each need their own
approval callback and their own record of which tools ran. They used to get
them by assigning ``executor._approval_callback`` / ``_on_tool_executed`` on
the shared Executor, and restoring the previous values afterwards — and they
did it *before* ``submit_task`` acquired ``AGENT_LOOP``. Two loops waiting for
the slot at the same time therefore saved and restored each other's hooks:
a goal's tool trail (the receipt gate's evidence) could collect another
loop's tools, or lose its own, and a cycle could run under a stale session's
approval callback.

A :class:`contextvars.ContextVar` makes the hooks belong to the asyncio task
that set them, the same way ``core/agent_isolation.py`` isolates subagent
state. Nothing global is mutated, so there is nothing to restore and nothing
for a concurrent waiter to clobber. The executor reads these hooks first and
falls back to its instance attributes (still used by direct-mode callers and
tests).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

ApprovalCallback = Callable[[str, str, dict[str, Any]], Any]
ToolExecutedHook = Callable[[str, dict[str, Any], str | None], None]
ToolResultHook = Callable[[str, dict[str, Any], Any], None]


@dataclass(frozen=True)
class RunHooks:
    """Hooks that apply to every tool call made by the current task."""

    approval_callback: ApprovalCallback | None = None
    on_tool_executed: ToolExecutedHook | None = None
    on_tool_result: ToolResultHook | None = None


_run_hooks: ContextVar[RunHooks | None] = ContextVar(
    "elophanto_run_hooks", default=None
)


def current_run_hooks() -> RunHooks | None:
    """The hooks set by the current task, or None."""
    return _run_hooks.get()


@contextmanager
def run_hooks(
    *,
    approval_callback: ApprovalCallback | None = None,
    on_tool_executed: ToolExecutedHook | None = None,
    on_tool_result: ToolResultHook | None = None,
) -> Iterator[RunHooks]:
    """Set the hooks for the body of a ``with`` block.

    Replaces — does not merge with — any hooks inherited from the parent
    context. A background task created inside a chat run inherits that run's
    context; a loop that sets its own hooks must not keep the chat's
    approval callback by accident.
    """
    hooks = RunHooks(
        approval_callback=approval_callback,
        on_tool_executed=on_tool_executed,
        on_tool_result=on_tool_result,
    )
    token = _run_hooks.set(hooks)
    try:
        yield hooks
    finally:
        _run_hooks.reset(token)
