"""Tests for tiered context compression + circuit breaker."""

from __future__ import annotations

from core.context_compressor import (
    CompactionCircuitBreaker,
    _estimate_tokens,
    microcompact,
)


class TestCircuitBreaker:
    def test_initial_state(self) -> None:
        cb = CompactionCircuitBreaker()
        assert not cb.is_tripped()

    def test_trips_after_3_failures(self) -> None:
        cb = CompactionCircuitBreaker()
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_tripped()
        cb.record_failure()
        assert cb.is_tripped()

    def test_success_resets(self) -> None:
        cb = CompactionCircuitBreaker()
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert not cb.is_tripped()
        # Need 3 fresh failures to trip again
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_tripped()

    def test_reset(self) -> None:
        cb = CompactionCircuitBreaker()
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.is_tripped()
        cb.reset()
        assert not cb.is_tripped()


class TestMicrocompact:
    def test_no_op_below_threshold(self) -> None:
        messages = [
            {"role": "tool", "content": "short result", "tool_call_id": "1"},
            {"role": "tool", "content": "another result", "tool_call_id": "2"},
        ]
        result, cleared = microcompact(messages, keep_recent=5)
        assert cleared == 0
        assert result[0]["content"] == "short result"

    def test_clears_old_tool_results(self) -> None:
        messages = [
            {"role": "tool", "content": "x" * 500, "tool_call_id": str(i)}
            for i in range(10)
        ]
        result, cleared = microcompact(messages, keep_recent=3)
        assert cleared == 7
        # Last 3 should be untouched
        assert len(result[-1]["content"]) == 500
        assert len(result[-2]["content"]) == 500
        assert len(result[-3]["content"]) == 500
        # Older ones should be cleared
        assert result[0]["content"] == "[result cleared \u2014 context optimization]"

    def test_skips_tiny_results(self) -> None:
        messages = [
            {"role": "tool", "content": "ok", "tool_call_id": "1"},  # 2 chars < 200
            {"role": "tool", "content": "x" * 500, "tool_call_id": "2"},
            {"role": "tool", "content": "y" * 500, "tool_call_id": "3"},
            {"role": "tool", "content": "z" * 500, "tool_call_id": "4"},
        ]
        result, cleared = microcompact(messages, keep_recent=2)
        # First one is too small to bother clearing
        assert cleared == 1
        assert result[0]["content"] == "ok"

    def test_ignores_non_tool_messages(self) -> None:
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
            {"role": "tool", "content": "x" * 500, "tool_call_id": "1"},
        ]
        result, cleared = microcompact(messages, keep_recent=5)
        assert cleared == 0


class TestEstimateTokens:
    def test_basic(self) -> None:
        assert _estimate_tokens("hello world") == 2  # 11 chars / 4

    def test_empty(self) -> None:
        assert _estimate_tokens("") == 1  # max(1, 0)

    def test_long(self) -> None:
        assert _estimate_tokens("a" * 4000) == 1000


class TestFixOrphanedToolCalls:
    """Regression tests for the Codex 400 'No tool call found for function
    call output with call_id X' bug. Compaction must never leave a tool
    result whose parent assistant turn is gone."""

    def test_drops_tool_result_when_parent_was_trimmed(self) -> None:
        """Orphan B: trimmer dropped the assistant turn that emitted
        tool_call_id 'lost', but kept the matching tool result. Strict
        APIs (Codex / OpenAI Responses) 400 on this. Fixer must drop it."""
        from core.context_compressor import _fix_orphaned_tool_calls

        messages = [
            {"role": "user", "content": "do the thing"},
            # Assistant turn with tool_calls "lost" was here, then trimmed.
            {
                "role": "tool",
                "tool_call_id": "lost",
                "content": "result that has no parent",
            },
            {"role": "assistant", "content": "i finished"},
        ]
        fixed = _fix_orphaned_tool_calls(messages)
        assert not any(m.get("tool_call_id") == "lost" for m in fixed)
        assert fixed[0]["role"] == "user"
        assert fixed[-1]["role"] == "assistant"
        assert len(fixed) == 2

    def test_preserves_valid_pair(self) -> None:
        """Sanity: a properly-paired tool call + result must round-trip
        unchanged."""
        from core.context_compressor import _fix_orphaned_tool_calls

        messages = [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "ok",
                        "type": "function",
                        "function": {"name": "shell", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "ok", "content": "done"},
            {"role": "assistant", "content": "shipped"},
        ]
        fixed = _fix_orphaned_tool_calls(messages)
        assert len(fixed) == len(messages)
        assert fixed[2]["tool_call_id"] == "ok"
        assert fixed[2]["content"] == "done"

    def test_inserts_stub_for_unanswered_call(self) -> None:
        """Orphan A: assistant emitted tool_calls but the result was dropped.
        Fixer inserts a stub so the pair is complete."""
        from core.context_compressor import _fix_orphaned_tool_calls

        messages = [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "stub-me",
                        "type": "function",
                        "function": {"name": "shell", "arguments": "{}"},
                    }
                ],
            },
            # No tool result here — was trimmed. Fixer should backfill.
            {"role": "user", "content": "follow-up"},
        ]
        fixed = _fix_orphaned_tool_calls(messages)
        stub = next((m for m in fixed if m.get("tool_call_id") == "stub-me"), None)
        assert stub is not None
        assert stub["role"] == "tool"
        assert "earlier in conversation" in stub["content"]

    def test_drops_orphan_b_keeps_orphan_a_stub(self) -> None:
        """Both orphan modes in the same trim — drop B, stub A. The
        survivor list is API-clean."""
        from core.context_compressor import _fix_orphaned_tool_calls

        messages = [
            {"role": "tool", "tool_call_id": "ghost", "content": "ghost result"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "real",
                        "type": "function",
                        "function": {"name": "f", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "real", "content": "ok"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "missing",
                        "type": "function",
                        "function": {"name": "g", "arguments": "{}"},
                    }
                ],
            },
            {"role": "user", "content": "next"},
        ]
        fixed = _fix_orphaned_tool_calls(messages)
        ids_seen = [m.get("tool_call_id") for m in fixed if m.get("role") == "tool"]
        assert "ghost" not in ids_seen  # orphan B dropped
        assert "real" in ids_seen  # valid pair kept
        assert "missing" in ids_seen  # orphan A stubbed

    def test_emergency_trim_runs_pairing_fixer(self) -> None:
        """End-to-end: _emergency_trim_messages cuts deep enough to
        orphan a tool result and must clean it up before returning."""
        from core.agent import _emergency_trim_messages

        long_msgs: list[dict] = [
            {"role": "user", "content": f"msg-{i}"} for i in range(50)
        ]
        long_msgs.append({"role": "tool", "tool_call_id": "stranded", "content": "x"})
        long_msgs.append({"role": "assistant", "content": "done"})

        fixed = _emergency_trim_messages(long_msgs)
        stranded = [m for m in fixed if m.get("tool_call_id") == "stranded"]
        assert (
            stranded == []
        ), "Emergency trim left an orphaned tool result — Codex would 400"


class TestCompressMessagesNoneContent:
    """Regression: compress_messages crashed with
    `unsupported operand type(s) for +=: 'NoneType' and 'str'` when an
    assistant message in the middle had `content: None` + `tool_calls`,
    which is the standard shape OpenAI/Anthropic emit. The Tier-2
    summarization pass would then fall through to Tier-3 emergency trim
    (worse outcome — drops history wholesale), and on big contexts the
    final prompt was still oversized → context_length_exceeded on Codex
    and 413 on HuggingFace. Both bugs in one trace."""

    import pytest

    @pytest.mark.asyncio
    async def test_assistant_with_tool_calls_none_content_does_not_crash(self) -> None:
        from core.context_compressor import compress_messages

        # Force compression by claiming a tiny context window. Need
        # enough messages to leave a non-empty middle slice after
        # keep_first/keep_last protection.
        msgs: list[dict] = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "ok"},
            # The bug pattern: content=None + tool_calls. Real LLMs
            # emit this exact shape.
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "shell_execute", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "done"},
            {"role": "assistant", "content": "next?"},
            {"role": "user", "content": "yes"},
            {"role": "assistant", "content": "k"},
            {"role": "user", "content": "more"},
            {"role": "assistant", "content": "fin"},
        ]

        # Stub router — returns whatever summary string. The point is
        # to reach the call without crashing.
        class StubRouter:
            async def complete(self, **kwargs):
                class R:
                    content = "summary"

                return R()

        # Should not raise. The exact return shape doesn't matter for
        # the regression — we only assert no exception.
        out = await compress_messages(
            msgs,
            router=StubRouter(),
            context_window=100,  # force compression
            threshold_pct=1,
            keep_first=1,
            keep_last=1,
        )
        # If we got a result back, the compactor didn't crash. Bug
        # surfaced as `TypeError` before the fix.
        assert isinstance(out, list)
