"""Provider transparency tracker — detect truncation, censorship, and fallback patterns.

Tracks per-provider metrics (finish_reason, latency, fallbacks, truncations)
so the agent can be transparent about provider behavior. Detection-only —
does not prevent anything, just surfaces the data.

See docs/27-SECURITY-HARDENING.md (Gap 5: Provider Bias and Silent Censorship).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

# Terminal punctuation that indicates a complete response
_TERMINAL_CHARS = frozenset('.!?}])"\u2019\u201d`')


@dataclass
class ProviderEvent:
    """A single LLM provider interaction record."""

    provider: str
    model: str
    task_type: str = "unknown"
    timestamp: float = 0.0
    finish_reason: str = "stop"
    latency_ms: int = 0
    fallback_from: str = ""
    error_message: str = ""
    suspected_truncated: bool = False
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.time()


@dataclass
class ProviderStats:
    """Aggregated stats for a single provider."""

    total_calls: int = 0
    failures: int = 0
    truncations: int = 0
    content_filters: int = 0
    fallbacks_to: int = 0
    total_latency_ms: int = 0

    @property
    def avg_latency_ms(self) -> int:
        if self.total_calls == 0:
            return 0
        return self.total_latency_ms // self.total_calls

    def to_dict(self) -> dict[str, int]:
        return {
            "total_calls": self.total_calls,
            "failures": self.failures,
            "truncations": self.truncations,
            "content_filters": self.content_filters,
            "fallbacks_to": self.fallbacks_to,
            "avg_latency_ms": self.avg_latency_ms,
        }


def detect_truncation(
    finish_reason: str,
    output_tokens: int,
    content: str | None,
) -> bool:
    """Heuristically detect if an LLM response was truncated or censored.

    Returns True if:
    - finish_reason is "length" (hit max_tokens limit)
    - finish_reason is "content_filter" (provider blocked content)
    - Content ends mid-sentence AND output_tokens > 500 (suspicious cutoff)
    """
    if finish_reason == "length":
        return True
    if finish_reason == "content_filter":
        return True

    # Heuristic: long response that ends mid-sentence
    if content and output_tokens > 500:
        stripped = content.rstrip()
        if stripped and stripped[-1] not in _TERMINAL_CHARS:
            return True

    return False


class ProviderTracker:
    """Tracks provider-level metrics for transparency reporting."""

    def __init__(self) -> None:
        # Bounded ring — only get_recent_events(limit=20) ever reads this,
        # and flush(db) is never called anywhere. Pre-2026-05-09 the list
        # grew 1:1 with LLM calls.
        self._events: deque[ProviderEvent] = deque(maxlen=100)
        self._stats: dict[str, ProviderStats] = defaultdict(ProviderStats)
        # Sticky auth-failure flag per provider. Set by record_auth_failure
        # when the router classifies a 401-style error; cleared on the
        # next successful call (router calls clear_auth_failure on
        # ``record(ProviderEvent(... finish_reason='success' ...))``). The
        # dashboard / status command reads ``auth_failures`` so operators
        # see "codex auth dead — run codex login" without log-diving.
        # Value is the last error message (truncated) so the operator
        # gets context.
        self._auth_failures: dict[str, str] = {}

    def record(self, event: ProviderEvent) -> None:
        """Record a provider interaction event."""
        self._events.append(event)

        stats = self._stats[event.provider]
        stats.total_calls += 1
        stats.total_latency_ms += event.latency_ms

        if event.finish_reason == "error":
            stats.failures += 1
        else:
            # Any non-error event from this provider means auth is
            # back online — clear the sticky failure flag.
            self._auth_failures.pop(event.provider, None)
        if event.suspected_truncated:
            stats.truncations += 1
        if event.finish_reason == "content_filter":
            stats.content_filters += 1
        if event.fallback_from:
            stats.fallbacks_to += 1

    def record_auth_failure(self, provider: str, model: str, error: str) -> None:
        """Mark a provider as auth-failed. Sticky until next success.

        Called by ``LLMRouter._call_with_retries`` when it classifies an
        error as authentication (401, "token refresh failed", etc.).
        The flag is read by:
          - ``/status`` chat command + dashboard 'providers' tile
          - operator-facing warning banners in the TUI
        Cleared automatically on the next successful event from the
        same provider via ``record()``.
        """
        self._auth_failures[provider] = f"{model}: {error}"
        # Also bump the failure count so aggregate stats reflect it.
        self._stats[provider].failures += 1

    def get_auth_failures(self) -> dict[str, str]:
        """Return ``{provider: last_error}`` for providers currently in
        an authentication-failure state."""
        return dict(self._auth_failures)

    def get_provider_stats(self) -> dict[str, dict[str, int]]:
        """Get aggregated stats per provider as plain dicts."""
        return {provider: stats.to_dict() for provider, stats in self._stats.items()}

    def get_recent_events(self, limit: int = 20) -> list[ProviderEvent]:
        """Get the most recent provider events."""
        events = list(self._events)
        return events[-limit:]

    async def flush(self, db: Any) -> None:
        """Persist pending events to the llm_usage table.

        Extends the existing CostTracker flush with new columns.
        Events are written with the extra transparency columns
        (finish_reason, latency_ms, fallback_from, suspected_truncated).
        """
        if not db or not self._events:
            return

        from datetime import UTC, datetime

        for event in self._events:
            try:
                await db.execute_insert(
                    "UPDATE llm_usage SET "
                    "finish_reason = ?, latency_ms = ?, "
                    "fallback_from = ?, suspected_truncated = ? "
                    "WHERE provider = ? AND model = ? "
                    "AND created_at >= ? "
                    "ORDER BY id DESC LIMIT 1",
                    (
                        event.finish_reason,
                        event.latency_ms,
                        event.fallback_from,
                        1 if event.suspected_truncated else 0,
                        event.provider,
                        event.model,
                        datetime.fromtimestamp(event.timestamp - 5, UTC).isoformat(),
                    ),
                )
            except Exception:
                pass  # Non-fatal — CostTracker handles the primary INSERT
        self._events.clear()
