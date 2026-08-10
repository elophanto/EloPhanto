"""Loop detection — stop a run that has started repeating itself.

An agent stuck in a loop is not idle: it is spending money and wall-clock
re-reading the same file, re-running the same failing command, or calling
the same endpoint that keeps 404ing, and it will happily do so until
``max_steps`` cuts it off hundreds of calls later. The step ceiling is a
budget, not a diagnosis — by the time it fires the transcript is unusable
and the operator has paid for the whole thing.

What actually identifies a loop is the *triple*: same tool, same arguments,
same result. Any one of those repeating is normal (reading a file twice is
fine; two tools returning "ok" is fine). All three together mean the agent
is not learning from what it is doing.

Escalation is graduated, because a legitimate retry looks identical to the
first repeat of a loop:

    2nd occurrence  → warn, and tell the model it is repeating
    3rd occurrence  → block that specific call, force a different approach
    4th occurrence  → end the run

State is per-run. A scheduled job that legitimately performs the same
action every hour must not inherit counters from its last execution.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

# How much of a tool result to fingerprint. Enough to distinguish outcomes,
# short enough that a huge payload doesn't dominate hashing cost.
_RESULT_FINGERPRINT_CHARS = 2000


class LoopVerdict(StrEnum):
    OK = "ok"
    WARN = "warn"
    BLOCK = "block"
    ABORT = "abort"


@dataclass
class LoopSignal:
    verdict: LoopVerdict
    count: int = 0
    message: str = ""
    tool_name: str = ""

    @property
    def should_stop_run(self) -> bool:
        return self.verdict == LoopVerdict.ABORT

    @property
    def should_block_call(self) -> bool:
        return self.verdict in (LoopVerdict.BLOCK, LoopVerdict.ABORT)


@dataclass
class LoopDetector:
    """Counts identical (tool, args, result) triples within one run."""

    warn_at: int = 2
    block_at: int = 3
    abort_at: int = 4
    enabled: bool = True

    # (tool, args, result) → count. The loop verdict runs off this.
    _counts: dict[str, int] = field(default_factory=dict, repr=False)
    _labels: dict[str, str] = field(default_factory=dict, repr=False)
    # (tool, args) → count, ignoring the result. Used by would_repeat() for
    # a cheap pre-call hint.
    _arg_counts: dict[str, int] = field(default_factory=dict, repr=False)

    def reset(self) -> None:
        """Clear all state. Call at the start of every run."""
        self._counts.clear()
        self._labels.clear()
        self._arg_counts.clear()

    @staticmethod
    def _args_key(tool_name: str, params: Any) -> str:
        try:
            args_repr = json.dumps(params, sort_keys=True, default=str)[:4000]
        except Exception:
            args_repr = repr(params)[:4000]
        return hashlib.sha256(
            f"{tool_name}\x00{args_repr}".encode(errors="replace")
        ).hexdigest()[:32]

    @classmethod
    def _fingerprint(cls, tool_name: str, params: Any, result: Any) -> str:
        result_repr = _result_repr(result)[:_RESULT_FINGERPRINT_CHARS]
        raw = f"{cls._args_key(tool_name, params)}\x00{result_repr}"
        return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:32]

    def record(self, tool_name: str, params: Any, result: Any) -> LoopSignal:
        """Register one completed tool call and rule on whether it loops."""
        if not self.enabled:
            return LoopSignal(LoopVerdict.OK)

        key = self._fingerprint(tool_name, params, result)
        count = self._counts.get(key, 0) + 1
        self._counts[key] = count
        self._labels[key] = tool_name
        args_key = self._args_key(tool_name, params)
        self._arg_counts[args_key] = self._arg_counts.get(args_key, 0) + 1

        if count >= self.abort_at:
            message = (
                f"Loop detected: '{tool_name}' has been called {count} times "
                "with identical arguments and identical results. Ending the "
                "run — continuing would repeat the same work indefinitely. "
                "Report what you learned and what is blocking you."
            )
            logger.error("[loop-detect] abort on %s (x%d)", tool_name, count)
            return LoopSignal(LoopVerdict.ABORT, count, message, tool_name)

        if count >= self.block_at:
            message = (
                f"Blocked: you have already called '{tool_name}' {count} times "
                "with these exact arguments and got the same result each time. "
                "Repeating it will not produce a different answer. Change "
                "approach, or tell the user what is blocking you."
            )
            logger.warning("[loop-detect] block on %s (x%d)", tool_name, count)
            return LoopSignal(LoopVerdict.BLOCK, count, message, tool_name)

        if count >= self.warn_at:
            message = (
                f"You have now called '{tool_name}' {count} times with the same "
                "arguments and received the same result. If the next call would "
                "be identical, do something different instead."
            )
            logger.info("[loop-detect] warn on %s (x%d)", tool_name, count)
            return LoopSignal(LoopVerdict.WARN, count, message, tool_name)

        return LoopSignal(LoopVerdict.OK, count, tool_name=tool_name)

    def would_repeat(self, tool_name: str, params: Any) -> int:
        """How many times this (tool, args) pair has already run, any result.

        A pre-call hint for callers that want to warn before paying for the
        call. Ignores the result, so it counts retries that legitimately
        produced different answers — treat it as a signal, not a verdict.
        """
        return self._arg_counts.get(self._args_key(tool_name, params), 0)

    @property
    def distinct_calls(self) -> int:
        return len(self._counts)

    @property
    def total_calls(self) -> int:
        return sum(self._counts.values())


def _result_repr(result: Any) -> str:
    """Stable text form of a tool result for fingerprinting.

    Uses the success flag plus the payload so that a call which starts
    failing after succeeding is not mistaken for a repeat.
    """
    if result is None:
        return "None"
    success = getattr(result, "success", None)
    data = getattr(result, "data", None)
    error = getattr(result, "error", None)
    if success is None and data is None and error is None:
        return str(result)
    try:
        payload = json.dumps(data, sort_keys=True, default=str)
    except Exception:
        payload = repr(data)
    return f"success={success}\x00error={error}\x00data={payload}"
