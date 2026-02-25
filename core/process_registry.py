"""Process registry — tracks spawned subprocesses for resource exhaustion protection.

Prevents unbounded process spawning by maintaining a registry of active child
processes with creation time and purpose. Provides a reaper for expired processes.

See docs/27-SECURITY-HARDENING.md (Gap 6: Resource Exhaustion Protection).
"""

from __future__ import annotations

import logging
import os
import signal
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ProcessEntry:
    """A tracked child process."""

    pid: int
    purpose: str
    created_at: float = field(default_factory=time.monotonic)


class ProcessRegistry:
    """Registry for tracking spawned child processes."""

    def __init__(self, max_concurrent: int = 10) -> None:
        self._max = max_concurrent
        self._processes: dict[int, ProcessEntry] = {}

    @property
    def count(self) -> int:
        return len(self._processes)

    @property
    def at_capacity(self) -> bool:
        return self.count >= self._max

    def register(self, pid: int, purpose: str) -> None:
        """Register a newly spawned process."""
        self._processes[pid] = ProcessEntry(pid=pid, purpose=purpose)
        logger.debug(
            "Process registered: pid=%d purpose=%s (total=%d)",
            pid,
            purpose[:80],
            self.count,
        )

    def unregister(self, pid: int) -> None:
        """Remove a completed process from the registry."""
        self._processes.pop(pid, None)

    def active_processes(self) -> list[ProcessEntry]:
        """Return list of currently tracked processes."""
        return list(self._processes.values())

    def reap_expired(self, max_age_seconds: float = 300) -> int:
        """Kill and remove processes older than *max_age_seconds*.

        Returns count of reaped processes.
        """
        now = time.monotonic()
        expired_pids = [
            entry.pid
            for entry in self._processes.values()
            if (now - entry.created_at) > max_age_seconds
        ]
        reaped = 0
        for pid in expired_pids:
            try:
                os.kill(pid, signal.SIGTERM)
                logger.warning("Reaped expired process pid=%d", pid)
            except (ProcessLookupError, PermissionError):
                pass  # Already dead
            self._processes.pop(pid, None)
            reaped += 1
        return reaped

    def cleanup_dead(self) -> int:
        """Remove entries whose PIDs no longer exist. Returns count removed."""
        dead: list[int] = []
        for pid in self._processes:
            try:
                os.kill(pid, 0)  # Signal 0 = existence check
            except (ProcessLookupError, PermissionError):
                dead.append(pid)
        for pid in dead:
            self._processes.pop(pid, None)
        return len(dead)
