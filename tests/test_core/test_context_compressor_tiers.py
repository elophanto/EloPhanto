"""Tests for tiered context compression + circuit breaker."""

from __future__ import annotations

import pytest

from core.context_compressor import (
    CompactionCircuitBreaker,
    microcompact,
    _estimate_tokens,
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
