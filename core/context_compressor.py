"""Mid-conversation context compression via LLM summarization.

When a conversation grows past a configurable token threshold, replaces
middle turns with an LLM-generated summary — preserving early context
(task setup) and recent turns (current work), while condensing the middle.

This is non-destructive compared to emergency_trim which simply drops
messages. The summary retains key decisions, discoveries, and state.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Defaults
_DEFAULT_THRESHOLD_PCT = 50  # Trigger at N% of context window
_DEFAULT_KEEP_FIRST = 3  # Protected early turns
_DEFAULT_KEEP_LAST = 4  # Protected recent turns
_DEFAULT_CONTEXT_WINDOW = 200_000  # Fallback context window size in tokens

# Tiered compression thresholds (% of context window)
_TIER1_MICROCOMPACT_PCT = 70  # Tier 1: clear old tool results (no LLM call)
_TIER2_SMART_COMPACT_PCT = 85  # Tier 2: LLM summarization
_TIER3_EMERGENCY_TRIM_PCT = 95  # Tier 3: aggressive drop

# Circuit breaker
_MAX_CONSECUTIVE_FAILURES = 3


class CompactionCircuitBreaker:
    """Tracks compression failures and stops retrying after threshold."""

    def __init__(self) -> None:
        self._consecutive_failures: int = 0
        self._tripped: bool = False

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            self._tripped = True
            logger.warning(
                "Compaction circuit breaker TRIPPED after %d failures",
                self._consecutive_failures,
            )

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._tripped = False

    def is_tripped(self) -> bool:
        return self._tripped

    def reset(self) -> None:
        self._consecutive_failures = 0
        self._tripped = False


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


def _message_tokens(msg: dict[str, Any]) -> int:
    """Estimate tokens in a single message (text content only)."""
    content = msg.get("content", "")
    if isinstance(content, str):
        return _estimate_tokens(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                total += _estimate_tokens(part.get("text", ""))
        return total
    return 0


def _total_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens across all messages."""
    return sum(_message_tokens(m) for m in messages)


def needs_compression(
    messages: list[dict[str, Any]],
    context_window: int = _DEFAULT_CONTEXT_WINDOW,
    threshold_pct: int = _DEFAULT_THRESHOLD_PCT,
) -> bool:
    """Check if messages exceed the compression threshold."""
    threshold = (context_window * threshold_pct) // 100
    return _total_tokens(messages) > threshold


def _fix_orphaned_tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fix orphaned tool calls/results after compression.

    Two failure modes happen when compaction cuts the conversation:

    A. **Tool call without result.** The assistant emitted `tool_calls` but
       the `role="tool"` response was dropped. Fixed by inserting a stub
       result so the next API call sees a complete pair.

    B. **Tool result without call.** The `role="tool"` message survived
       but its parent assistant turn was dropped. Strict APIs (OpenAI
       Responses, used by Codex) reject this with
       "No tool call found for function call output with call_id X".
       OpenRouter is lenient about it, which is why only Codex screams.

    This function handles both. It does a forward pass tracking
    declared tool_call_ids; any tool message referencing an id we
    haven't seen is silently dropped (its content is irrecoverable
    once the parent is gone — better to drop than to invent).
    """
    # Pre-pass: collect every tool_call_id that an assistant turn
    # declares ANYWHERE in the surviving history. Dropped parent →
    # the id never appears here → tool result is orphan B.
    declared_call_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id", "")
                if tc_id:
                    declared_call_ids.add(tc_id)

    result: list[dict[str, Any]] = []
    pending_calls: dict[str, str] = {}  # id → tool name (for orphan A stubs)
    dropped_orphan_b = 0

    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id", "")
                tc_name = tc.get("function", {}).get("name", "unknown")
                pending_calls[tc_id] = tc_name
            result.append(msg)
        elif msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id", "")
            if tc_id and tc_id not in declared_call_ids:
                # Orphan B — parent assistant turn was dropped. Skip
                # silently; including this would 400 the next API call.
                dropped_orphan_b += 1
                continue
            pending_calls.pop(tc_id, None)
            result.append(msg)
        else:
            # Before appending a non-tool message, flush any pending
            # tool calls that never got results (orphan A).
            if pending_calls:
                for orphan_id, orphan_name in pending_calls.items():
                    result.append(
                        {
                            "role": "tool",
                            "tool_call_id": orphan_id,
                            "content": (
                                f"[Result from {orphan_name} earlier in conversation "
                                f"— see context summary above]"
                            ),
                        }
                    )
                pending_calls.clear()
            result.append(msg)

    # Flush any remaining pending calls at the end (orphan A)
    for orphan_id, orphan_name in pending_calls.items():
        result.append(
            {
                "role": "tool",
                "tool_call_id": orphan_id,
                "content": (
                    f"[Result from {orphan_name} earlier in conversation "
                    f"— see context summary above]"
                ),
            }
        )

    if dropped_orphan_b:
        logger.info(
            "Dropped %d orphaned tool results (parent assistant turn was "
            "trimmed). Required to keep Codex/OpenAI Responses API happy.",
            dropped_orphan_b,
        )

    return result


_SUMMARIZE_SYSTEM = """\
Summarize this conversation excerpt concisely. Include:
- Key decisions made and their rationale
- Important discoveries, errors encountered, and how they were resolved
- Current state of the task (what's done, what's pending)
- Any file paths, URLs, variable names, or specific values that were referenced

Be factual and dense. Use bullet points. Do NOT include pleasantries or filler.
Target 20% of the original length. Return ONLY the summary."""


async def compress_messages(
    messages: list[dict[str, Any]],
    router: Any,
    context_window: int = _DEFAULT_CONTEXT_WINDOW,
    threshold_pct: int = _DEFAULT_THRESHOLD_PCT,
    keep_first: int = _DEFAULT_KEEP_FIRST,
    keep_last: int = _DEFAULT_KEEP_LAST,
) -> list[dict[str, Any]]:
    """Compress conversation by summarizing middle turns.

    Args:
        messages: The conversation messages (user/assistant/tool, no system).
        router: LLM router for summarization call.
        context_window: Model's context window in tokens.
        threshold_pct: Trigger compression at this % of context window.
        keep_first: Number of early turns to protect.
        keep_last: Number of recent turns to protect.

    Returns:
        Compressed message list (may be unchanged if below threshold).
    """
    if not needs_compression(messages, context_window, threshold_pct):
        return messages

    total = len(messages)
    if total <= keep_first + keep_last + 2:
        return messages  # Too few messages to compress

    head = messages[:keep_first]
    tail = messages[-keep_last:]
    middle = messages[keep_first:-keep_last]

    if not middle:
        return messages

    # Build text representation of middle turns for summarization
    middle_text_parts = []
    for msg in middle:
        role = msg.get("role", "unknown")
        # `.get("content", "")` returns None — not "" — when content is
        # explicitly None, which is the standard shape for assistant
        # messages with tool_calls (OpenAI + Anthropic both emit
        # {role: assistant, content: None, tool_calls: [...]}). Default
        # to "" *after* the lookup so the `+=` below can't blow up on
        # None when we append the [called: ...] suffix.
        content = msg.get("content") or ""
        if isinstance(content, list):
            # Multimodal — extract text parts only
            content = " ".join(
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        if msg.get("tool_calls"):
            calls = msg["tool_calls"]
            call_names = [tc.get("function", {}).get("name", "?") for tc in calls]
            content = f"{content} [called: {', '.join(call_names)}]"
        if content:
            middle_text_parts.append(f"[{role}]: {content[:2000]}")

    middle_text = "\n".join(middle_text_parts)

    # Summarize via cheap model
    try:
        response = await router.complete(
            messages=[
                {"role": "system", "content": _SUMMARIZE_SYSTEM},
                {"role": "user", "content": middle_text},
            ],
            task_type="simple",  # Routes to cheapest model
            temperature=0.1,
        )
        summary = response.content.strip()
    except Exception as e:
        logger.warning("Context compression failed (LLM error): %s", e)
        return messages  # Fallback: return uncompressed

    if not summary:
        return messages

    # Determine role for summary message to maintain alternation
    # The last head message determines what role should follow
    if head and head[-1].get("role") == "user":
        summary_role = "assistant"
    else:
        summary_role = "user"

    summary_msg: dict[str, Any] = {
        "role": summary_role,
        "content": (
            f"[Context summary — {len(middle)} messages compressed]\n\n{summary}"
        ),
    }

    compressed = head + [summary_msg] + tail
    compressed = _fix_orphaned_tool_calls(compressed)

    before_tokens = _total_tokens(messages)
    after_tokens = _total_tokens(compressed)
    logger.info(
        "Context compressed: %d messages → %d | ~%dk → ~%dk tokens",
        total,
        len(compressed),
        before_tokens // 1000,
        after_tokens // 1000,
    )

    return compressed


def microcompact(
    messages: list[dict[str, Any]],
    keep_recent: int = 5,
) -> tuple[list[dict[str, Any]], int]:
    """Clear old tool result contents without LLM call.

    Returns (messages, cleared_count). Mutates in-place for efficiency.
    """
    tool_indices = [
        i
        for i, m in enumerate(messages)
        if m.get("role") == "tool" and isinstance(m.get("content"), str)
    ]
    if len(tool_indices) <= keep_recent:
        return messages, 0

    cleared = 0
    for i in tool_indices[:-keep_recent]:
        content = messages[i]["content"]
        if len(content) > 200:  # Don't bother with tiny results
            messages[i] = {
                **messages[i],
                "content": "[result cleared \u2014 context optimization]",
            }
            cleared += 1

    return messages, cleared


async def tiered_compress(
    messages: list[dict[str, Any]],
    router: Any,
    context_window: int = _DEFAULT_CONTEXT_WINDOW,
    circuit_breaker: CompactionCircuitBreaker | None = None,
) -> list[dict[str, Any]]:
    """Three-tier context compression with circuit breaker.

    Tier 1 (70%): Microcompact \u2014 clear old tool results (free, no LLM)
    Tier 2 (85%): Smart compact \u2014 LLM summarization of middle turns
    Tier 3 (95%): Emergency trim \u2014 drop oldest turns aggressively
    """
    total = _total_tokens(messages)

    # Tier 1: Microcompact
    tier1_threshold = (context_window * _TIER1_MICROCOMPACT_PCT) // 100
    if total > tier1_threshold:
        messages, cleared = microcompact(messages)
        if cleared:
            logger.info("Tier 1 microcompact: cleared %d old tool results", cleared)
            total = _total_tokens(messages)

    # Tier 2: Smart compact (LLM summarization)
    tier2_threshold = (context_window * _TIER2_SMART_COMPACT_PCT) // 100
    if total > tier2_threshold:
        if circuit_breaker and circuit_breaker.is_tripped():
            logger.warning("Circuit breaker tripped \u2014 skipping LLM compaction")
        else:
            try:
                messages = await compress_messages(
                    messages,
                    router,
                    context_window,
                    threshold_pct=0,  # Force compression (we already checked threshold)
                )
                if circuit_breaker:
                    circuit_breaker.record_success()
            except Exception as e:
                logger.warning("Tier 2 compaction failed: %s", e)
                if circuit_breaker:
                    circuit_breaker.record_failure()
            total = _total_tokens(messages)

    # Tier 3: Emergency trim
    tier3_threshold = (context_window * _TIER3_EMERGENCY_TRIM_PCT) // 100
    if total > tier3_threshold:
        logger.warning("Tier 3 emergency trim \u2014 dropping oldest messages")
        keep_first = 2
        keep_last = 5
        if len(messages) > keep_first + keep_last + 2:
            messages = messages[:keep_first] + messages[-keep_last:]
            messages = _fix_orphaned_tool_calls(messages)
            logger.info("Emergency trimmed to %d messages", len(messages))

    return messages
