"""Per-task isolation for subagent runs.

``Agent.run_isolated`` needs a subagent to see its own conversation history,
working memory, activated-tool set, filtered registry, step hook, and loop
detector — while everything genuinely global (vault, DB, scheduler, affect,
ego, browser) stays shared.

The original implementation did that by swapping attributes on the Agent and
restoring them in a ``finally``. That is correct for exactly one call at a
time. The moment two overlap it corrupts both:

    saved = self._conversation_history      # A saves the parent's
    self._conversation_history = isolated   # B then saves *A's*
    try:     await self.run(...)            # A now reads B's history
    finally: self._conversation_history = saved   # B restores A's, for good

The registry swap made that a safety bug rather than merely a correctness
one: that filter is what hides payment and spawn tools from subagents, and a
leaked unfiltered view hands them back.

A :class:`contextvars.ContextVar` is the right primitive because asyncio
copies the current context into every Task it creates. ``asyncio.gather``
wraps each coroutine in a Task, so a ``set()`` inside one subagent is
invisible to its siblings and to the parent — isolation by construction
rather than by careful bookkeeping. Direct ``await`` (no Task) is handled by
resetting the token in a ``finally``, which also makes nesting well-defined.

The Agent's ``_conversation_history`` / ``_working_memory`` /
``_activated_tools`` / ``_registry`` / ``_on_step`` / ``_loop_detector``
attributes are properties that read through here, so the ~150 existing
``self._X`` references throughout the agent loop keep working untouched and
resolve per-task automatically.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any


@dataclass
class IsolationState:
    """One subagent's private view of the agent's per-run state."""

    conversation_history: list[dict[str, Any]]
    working_memory: Any
    activated_tools: set[str]
    registry: Any
    on_step: Any = None
    loop_detector: Any = None
    # Per-task spend. ``_run_with_history`` calls ``reset_task()`` on entry,
    # so without this every subagent would zero the *parent's* running total
    # and four concurrent ones would erase its budget accounting outright.
    # The subagent accrues here and the total is rolled into the parent on
    # exit, which keeps the documented semantics (fresh per-task budget,
    # spend still visible to the parent) without shared mutable state.
    cost_task_total: float = 0.0


_isolation: ContextVar[IsolationState | None] = ContextVar(
    "elophanto_agent_isolation", default=None
)


def current_isolation() -> IsolationState | None:
    """The active subagent state, or None when running as the parent."""
    return _isolation.get()


def enter_isolation(state: IsolationState) -> Token[IsolationState | None]:
    """Enter an isolated run. Always pair with :func:`exit_isolation`."""
    return _isolation.set(state)


def exit_isolation(token: Token[IsolationState | None]) -> None:
    """Leave an isolated run, restoring whatever context was active before.

    Token-based rather than ``set(None)`` so nested isolation unwinds to the
    enclosing subagent instead of jumping straight back to the parent.
    """
    _isolation.reset(token)
