"""Task resource manager — typed semaphores + a goal-text heuristic.

Why this exists:
    Before this module, the scheduler used a single `_is_executing`
    boolean to gate concurrent task execution. Two consequences:
    (1) max_concurrent_tasks=1 meant pure serial execution — a
        Polymarket scan via API blocked an X reply via browser even
        though they share zero resources.
    (2) When cron fired while a task was running, the new fire was
        DROPPED, not queued. Four every-30-min tasks fighting for
        one slot lost three out of four fires per cycle.

    This module provides resource-typed semaphores so non-overlapping
    tasks run truly in parallel, and exposes status snapshots for
    operability (`elophanto doctor`, dashboard).

    The scheduler owns the queue; this module owns the resource lock
    contention. Layering is one-way — task_resources.py knows nothing
    about the scheduler.

See docs/02-ARCHITECTURE.md (scheduler section) for the full picture.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resource taxonomy
# ---------------------------------------------------------------------------


class TaskResource(StrEnum):
    """Hardware/state-level resources scheduled tasks contend for.

    Only resources where genuine contention exists. Filesystem reads,
    web_search via API, knowledge writes (sqlite WAL handles those),
    and outbound HTTP have no entry here — they're parallel-safe.
    """

    # Single Chrome profile, single CDP — two tasks driving the browser
    # corrupt each other's cookie/tab/network state. Hard contention.
    BROWSER = "browser"

    # One screen, one cursor, one keyboard. Hard contention.
    DESKTOP = "desktop"

    # Vault writes serialize on a single password-derived key. Reads
    # don't contend; writes do (audit trail, key rotation).
    VAULT_WRITE = "vault_write"

    # Soft cap on concurrent LLM-heavy tasks. Two purposes: (a) avoid
    # provider rate limits, (b) cap how fast the daily budget burns.
    # Defaults to a few; configurable.
    LLM_BURST = "llm_burst"

    # Sentinel: when we can't infer resources from a task goal, we
    # default to this. Capacity = scheduler.max_concurrent_tasks so
    # unknown tasks fall back to global parallelism cap.
    DEFAULT = "default"


# ---------------------------------------------------------------------------
# Heuristic: infer resources from the task goal text
# ---------------------------------------------------------------------------
#
# Cheap pattern-match — no LLM call. False-positive bias intentional
# (over-acquire is safe; under-acquire causes browser-state corruption).

_BROWSER_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        # Direct browser keywords — explicit signal.
        # NOTE: bare `\bbrowser\b` was previously here and caused a
        # false positive in production: operator goal text like
        # "Browser screenshots are NOT authoritative — rely on CLOB
        # API" was flagged as browser-needing despite literally
        # instructing the opposite. Word-level regex can't read
        # negation context. Specific verbs below catch the real cases.
        r"\bnavigate to\b",
        r"\bscrape\b",
        # Explicit tool-name references.
        r"\b(twitter|tiktok|youtube)_post\b",
        r"\bpump[\.\-_ ]?(fun|chat|caption|livestream|say|comment)\b",
        r"\bagent.?commune\b",
        # Action+platform combinations — these are unambiguous because
        # both halves must appear together. "post on X" ≠ "I like X".
        r"\bpost on (?:x|twitter|tiktok|youtube|instagram|linkedin|reddit|hn|hacker.?news|product.?hunt)\b",
        r"\b(?:x|twitter)[\s_-]+(?:reply|replies|repost|engagement|growth|comments?|likes?)\b",
        r"\b(?:reply|replies|repost|tweet|tweets|tweeting)\s+on\s+(?:x|twitter)\b",
        r"\btwitter\b",
        r"\btweet\b",
        # NOTE: deliberately NOT matched — too generic, caused false
        # positives in production:
        #   - bare 'x' (matches '10x', 'x-axis', etc. even with \b)
        #   - bare 'reply' or 'like' (matches 'reply to emails',
        #     'I like Polymarket')
        #   - bare 'polymarket' (Polymarket flows use py-clob-client
        #     API, not browser; only mark if the goal text specifically
        #     mentions browser-driven UI flows)
        #   - bare 'click', 'visit' (too generic; both appear in
        #     analyst speak — "click rate", "visit count")
    )
]

_DESKTOP_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bdesktop\b",
        r"\bscreenshot\b",
        r"\bopen (?:excel|photoshop|finder|terminal|gimp|word|sketch)\b",
        r"\bpyautogui\b",
    )
]

_VAULT_WRITE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bvault[_ -](set|store|update|rotate)\b",
        r"\bstore (?:credential|api key|secret|token)\b",
    )
]


def infer_resources(task_goal: str) -> list[TaskResource]:
    """Best-effort guess at which resources a scheduled task will use,
    based on keyword match against its goal text.

    Conservative on browser: when in doubt, declare BROWSER. The
    failure mode of acquiring an unneeded resource is "task waits
    slightly longer in the queue." The failure mode of NOT acquiring
    a needed resource is "two tasks corrupt the browser state at
    the same time." First is cheap; second is a real bug.

    Always declares LLM_BURST because every scheduled task triggers
    the agent loop, which uses the LLM. This is the global throttle
    on parallel LLM work.
    """
    out: set[TaskResource] = {TaskResource.LLM_BURST}
    if not task_goal:
        # Empty goal → assume worst-case (browser+desktop+vault). Better
        # to over-acquire than corrupt state on a malformed task.
        return list({TaskResource.BROWSER, TaskResource.LLM_BURST})

    text = task_goal[:4000]  # cap for cheap matching

    for pat in _BROWSER_PATTERNS:
        if pat.search(text):
            out.add(TaskResource.BROWSER)
            break
    for pat in _DESKTOP_PATTERNS:
        if pat.search(text):
            out.add(TaskResource.DESKTOP)
            break
    for pat in _VAULT_WRITE_PATTERNS:
        if pat.search(text):
            out.add(TaskResource.VAULT_WRITE)
            break

    return sorted(out, key=lambda r: r.value)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


@dataclass
class _ResourceState:
    """Snapshot of one resource — what the doctor command renders."""

    name: str
    capacity: int
    in_use: int
    waiters: int


@dataclass
class TaskResourceManager:
    """Per-resource semaphore pool with status snapshots.

    Acquired via the `acquire(resources)` async context manager —
    blocks until all declared resources are free, releases on
    context exit. Resources are acquired in a canonical order to
    prevent two tasks deadlocking on each other (A holds X waiting
    for Y, B holds Y waiting for X).
    """

    capacities: dict[TaskResource, int]
    _semaphores: dict[TaskResource, asyncio.Semaphore] = field(
        default_factory=dict, init=False
    )
    _waiters: dict[TaskResource, int] = field(default_factory=dict, init=False)
    _running_count: int = field(default=0, init=False)
    _running_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        for resource, capacity in self.capacities.items():
            if capacity < 1:
                raise ValueError(
                    f"resource {resource} capacity must be >= 1, got {capacity}"
                )
            self._semaphores[resource] = asyncio.Semaphore(capacity)
            self._waiters[resource] = 0

    @classmethod
    def from_defaults(
        cls,
        *,
        global_concurrency: int = 3,
        llm_burst: int = 4,
    ) -> TaskResourceManager:
        """Build with sane defaults. Browser/desktop/vault are 1 by
        nature (single instance each). llm_burst defaults to 4 — caps
        concurrent LLM work without serializing it. The DEFAULT slot
        is sized to the global concurrency cap so unknown tasks
        gracefully fall back to a global parallelism limit.
        """
        return cls(
            capacities={
                TaskResource.BROWSER: 1,
                TaskResource.DESKTOP: 1,
                TaskResource.VAULT_WRITE: 1,
                TaskResource.LLM_BURST: max(1, llm_burst),
                TaskResource.DEFAULT: max(1, global_concurrency),
            }
        )

    @asynccontextmanager
    async def acquire(self, resources: list[TaskResource]) -> AsyncIterator[None]:
        """Acquire all declared resources, in canonical order so two
        tasks declaring overlapping sets can't deadlock.

        Raises KeyError if a requested resource isn't configured —
        catches typos in resource lists at acquire time, not at the
        end of a 30-min task.
        """
        # Canonical order = stable sort by enum value. asyncio.Semaphore
        # is FIFO so two tasks acquiring the same set in the same order
        # serialize cleanly.
        ordered = sorted(set(resources), key=lambda r: r.value)
        unknown = [r for r in ordered if r not in self._semaphores]
        if unknown:
            raise KeyError(f"unknown resource(s): {unknown}")

        acquired: list[TaskResource] = []
        try:
            for resource in ordered:
                self._waiters[resource] += 1
                try:
                    await self._semaphores[resource].acquire()
                finally:
                    self._waiters[resource] -= 1
                acquired.append(resource)
            async with self._running_lock:
                self._running_count += 1
            try:
                yield
            finally:
                async with self._running_lock:
                    self._running_count = max(0, self._running_count - 1)
        finally:
            # Release in reverse order — symmetric, doesn't change the
            # FIFO semantics but makes traces easier to read.
            for resource in reversed(acquired):
                self._semaphores[resource].release()

    def is_busy(self) -> bool:
        """True if any task is currently running. Used by the user-
        interaction-pause hook to decide whether pausing matters."""
        return self._running_count > 0

    def status(self) -> dict[str, _ResourceState]:
        """Snapshot for `elophanto doctor` and the dashboard."""
        out: dict[str, _ResourceState] = {}
        for resource, capacity in self.capacities.items():
            sem = self._semaphores[resource]
            # asyncio.Semaphore exposes _value as remaining permits.
            # Computing in_use as capacity - remaining is the standard
            # way; the underscore is unfortunate but the API is stable.
            remaining = sem._value  # type: ignore[attr-defined]
            in_use = max(0, capacity - remaining)
            out[resource.value] = _ResourceState(
                name=resource.value,
                capacity=capacity,
                in_use=in_use,
                waiters=self._waiters.get(resource, 0),
            )
        return out

    def status_dict(self) -> dict[str, dict[str, Any]]:
        """status() but as plain dicts for JSON / logging."""
        return {
            k: {
                "capacity": v.capacity,
                "in_use": v.in_use,
                "waiters": v.waiters,
            }
            for k, v in self.status().items()
        }
