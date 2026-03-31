"""Action queue — serializes all agent task execution.

Prevents concurrent browser/tool access by ensuring only one task
(manual, scheduled, heartbeat, autonomous mind) runs at a time.
Manual user tasks get priority — background tasks yield and wait.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import IntEnum

logger = logging.getLogger(__name__)


class TaskPriority(IntEnum):
    """Execution priority — lower number = higher priority."""

    USER = 0  # Manual chat messages — highest priority
    HEARTBEAT = 1  # Heartbeat standing orders
    SCHEDULED = 2  # Scheduled cron tasks
    MIND = 3  # Autonomous mind background cycles
    GOAL = 4  # Goal runner background execution


class ActionQueue:
    """Serializes agent task execution with priority preemption.

    Only one task runs at a time. When a higher-priority task arrives,
    the current holder's ``preempted`` event is set so it can yield
    at a safe checkpoint.

    Usage::

        async with action_queue.acquire(TaskPriority.USER) as slot:
            await agent.run(goal)

        # Or check if preempted mid-task:
        async with action_queue.acquire(TaskPriority.SCHEDULED) as slot:
            for step in task_steps:
                if slot.preempted.is_set():
                    break  # Yield to higher-priority task
                await execute_step(step)
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._current_priority: TaskPriority | None = None
        self._current_preempted: asyncio.Event | None = None
        self._waiters: int = 0

    @property
    def is_busy(self) -> bool:
        """True if a task is currently executing."""
        return self._lock.locked()

    @property
    def current_priority(self) -> TaskPriority | None:
        """Priority of the currently running task, or None."""
        return self._current_priority

    @asynccontextmanager
    async def acquire(
        self, priority: TaskPriority, timeout: float | None = None
    ) -> AsyncIterator[_Slot]:
        """Acquire exclusive execution slot.

        If a lower-priority task is running and this is a higher-priority
        request, signals preemption to the current holder. The current
        holder should check ``slot.preempted`` and yield.

        Args:
            priority: Task priority level.
            timeout: Max seconds to wait for the lock. None = wait forever.
        """
        # Signal preemption to lower-priority holder
        if (
            self._lock.locked()
            and self._current_priority is not None
            and priority < self._current_priority
            and self._current_preempted is not None
        ):
            logger.info(
                "Preempting %s task (priority %d > %d)",
                self._current_priority.name,
                priority,
                self._current_priority,
            )
            self._current_preempted.set()

        self._waiters += 1
        start = time.monotonic()
        try:
            if timeout is not None:
                try:
                    await asyncio.wait_for(self._lock.acquire(), timeout)
                except TimeoutError:
                    logger.warning(
                        "Action queue timeout after %.1fs for %s task",
                        timeout,
                        priority.name,
                    )
                    raise
            else:
                await self._lock.acquire()
        finally:
            self._waiters -= 1

        waited = time.monotonic() - start
        if waited > 0.1:
            logger.info(
                "Action queue acquired by %s task (waited %.1fs)",
                priority.name,
                waited,
            )

        preempted = asyncio.Event()
        self._current_priority = priority
        self._current_preempted = preempted
        slot = _Slot(priority=priority, preempted=preempted)

        try:
            yield slot
        finally:
            self._current_priority = None
            self._current_preempted = None
            self._lock.release()


class _Slot:
    """Handle returned by ActionQueue.acquire().

    Check ``preempted.is_set()`` between steps to yield to a
    higher-priority task.
    """

    __slots__ = ("priority", "preempted")

    def __init__(self, priority: TaskPriority, preempted: asyncio.Event) -> None:
        self.priority = priority
        self.preempted = preempted
