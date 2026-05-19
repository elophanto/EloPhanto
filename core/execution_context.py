"""Unified execution-context tracking for the agent.

Before this module, three separate signals answered overlapping
questions about "where in the system am I right now":

  - ``is_user_input: bool`` (parameter on ``agent.run()``)
    Answer: is the current goal from a real user? Used by the ego
    correction detector at one point in ``_run_with_history`` to
    gate the "no/stop/wrong" regex against agent self-talk.

  - ``_in_scheduled_task`` (contextvar in ``core/agent.py``)
    Answer: am I executing a cron-fired scheduled task? Read by
    ``tools/scheduling/list_tool.py`` and
    ``tools/scheduling/schedule_tool.py`` to refuse one schedule
    mutating another.

  - ``_in_agent_loop`` (contextvar in ``core/agent.py``)
    Answer: am I already holding AGENT_LOOP? Used by ``agent.run``
    to skip the resource re-acquire when ``run_isolated`` (the
    delegate-tool path) nests under an active loop.

Each had exactly one use site, so the three never "overlapped" in
behavior. They DID overlap in concept — they're all variants of
"what's the current execution provenance / posture" — and the
three setters at the four entry points (chat, mind, scheduled,
heartbeat, plus the re-entrant delegate path) were an implicit
contract: every new caller had to remember to flip the right flags
in the right places. The "390 false-positive anger events" bug
the comments at ``core/agent.py:2521`` reference came from one
caller forgetting one flag.

This module consolidates all three into a single
``ExecutionContext`` carried on one contextvar. Reading it answers
each of the three questions via a derived property. Setting it
at an entry point automatically propagates to every nested await.

This is a refactor — no behavior change. The old contextvars and
the ``is_user_input`` parameter still exist; they're now derived
from the new context for callers that read them. The next
refactor (the ``submit_task`` API) will delete the old paths once
all callers go through one normalized entry.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from enum import StrEnum


class TaskSource(StrEnum):
    """What kicked off the current top-of-stack task.

    Mapped 1:1 to ``TaskPriority`` by the dispatch layer but lives
    here because the source is a *property of the work itself*,
    while priority is a *scheduling decision* derived from it.
    Keeping them in separate enums avoids the "operator wants to
    reprioritize mind work" decision being coupled to "what
    semantic gates fire."
    """

    USER = "user"  # Live operator chat / gateway message
    HEARTBEAT = "heartbeat"  # HEARTBEAT.md standing orders
    SCHEDULED = "scheduled"  # Cron-fired scheduled_task
    MIND = "mind"  # Autonomous-mind cycle
    GOAL = "goal"  # Goal-runner background execution
    # In-process subagent via the delegate tool. Inherits the source
    # of the parent task in semantic terms (a user-initiated chat
    # that spawns a delegate is still user-context for correction
    # purposes) but flags itself for resource reentrance via
    # ``in_agent_loop``.
    DELEGATE = "delegate"


@dataclass(frozen=True)
class ExecutionContext:
    """The execution provenance of the current asyncio task.

    Frozen so concurrent tasks can't mutate a shared instance — each
    contextvar transition produces a new value via ``replace``.

    Fields:
        source: Who initiated this work.
        in_agent_loop: True iff the AGENT_LOOP resource semaphore is
            already held by this asyncio task (or a parent that
            transferred via ``copy_context``). Used by ``agent.run``
            to skip the reacquire and avoid self-deadlock when
            ``run_isolated`` nests under an active loop.
        depth: Reentrance counter. 0 = top-level entry. Incremented
            on each nested ``execution_context`` block. Diagnostic
            only — no behavior depends on it. Useful for debug logs
            when a self-call chain confuses provenance.
    """

    source: TaskSource = TaskSource.USER
    in_agent_loop: bool = False
    depth: int = 0

    @property
    def is_user_input(self) -> bool:
        """True iff the goal text originated from a real second party
        (operator chat or delegate subagent of a user task).

        Mirrors the old ``is_user_input: bool`` parameter on
        ``agent.run``. Used by the ego correction detector to gate
        the user-said-no regex — running it on agent self-talk
        produces false positives because goal text often contains
        the literal words "no" / "wrong" / "didn't work" in
        legitimate non-correction contexts.
        """
        return self.source in (TaskSource.USER, TaskSource.DELEGATE)

    @property
    def is_scheduled(self) -> bool:
        """True iff a scheduled (cron-fired) task is executing.

        Mirrors the old ``is_in_scheduled_task()`` helper. Used by
        scheduling tools to refuse one schedule mutating another.
        """
        return self.source == TaskSource.SCHEDULED


# The single execution-context contextvar. Default is "user", which
# matches the legacy ``is_user_input: bool = True`` default on
# ``agent.run`` — if nothing has set the context yet, the call is
# treated as user-initiated. Override with ``execution_context(...)``
# at every entry point.
_current_context: ContextVar[ExecutionContext] = ContextVar(
    "_execution_context",
    default=ExecutionContext(),  # noqa: B039 — frozen dataclass, safe as default
)


def current_context() -> ExecutionContext:
    """Read-only access to the current execution context.

    Pure function. Safe from any code path. Returns the default
    user-context value if no entry point has set the context yet —
    legacy callers of ``agent.run()`` that don't go through the
    new dispatch layer still get sane behavior.
    """
    return _current_context.get()


@contextmanager
def execution_context(
    *,
    source: TaskSource | None = None,
    in_agent_loop: bool | None = None,
) -> Iterator[ExecutionContext]:
    """Push a new execution context for the body of a `with` block.

    Each parameter that's None is inherited from the parent context.
    ``depth`` is auto-incremented so reentrance is observable in logs.

    Synchronous context manager. Works fine inside async functions
    because ``ContextVar.set/reset`` are sync operations and the
    contextvar propagates through ``await`` naturally.

    Example::

        with execution_context(source=TaskSource.MIND):
            await agent.run(prompt)
    """
    parent = _current_context.get()
    new = replace(
        parent,
        source=source if source is not None else parent.source,
        in_agent_loop=(
            in_agent_loop if in_agent_loop is not None else parent.in_agent_loop
        ),
        depth=parent.depth + 1,
    )
    token = _current_context.set(new)
    try:
        yield new
    finally:
        _current_context.reset(token)
