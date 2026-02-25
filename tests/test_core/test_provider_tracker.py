"""Tests for core/provider_tracker.py — provider transparency tracking."""

from __future__ import annotations

from core.provider_tracker import (
    ProviderEvent,
    ProviderStats,
    ProviderTracker,
    detect_truncation,
)

# ---------------------------------------------------------------------------
# detect_truncation
# ---------------------------------------------------------------------------


class TestDetectTruncation:
    def test_finish_reason_length(self) -> None:
        """finish_reason='length' should be detected as truncation."""
        assert detect_truncation("length", 100, "Some text") is True

    def test_finish_reason_content_filter(self) -> None:
        """finish_reason='content_filter' should be detected as truncation."""
        assert detect_truncation("content_filter", 50, "Blocked content") is True

    def test_finish_reason_stop_not_truncated(self) -> None:
        """finish_reason='stop' with complete text should NOT be truncated."""
        assert detect_truncation("stop", 100, "Complete sentence.") is False

    def test_mid_sentence_heuristic(self) -> None:
        """Long response ending mid-sentence should be detected as truncated."""
        content = "This is a long response that ends abruptly without any punctuation"
        assert detect_truncation("stop", 600, content) is True

    def test_short_response_not_flagged(self) -> None:
        """Short response ending mid-sentence should NOT be flagged (< 500 tokens)."""
        content = "Short incomplete"
        assert detect_truncation("stop", 50, content) is False

    def test_none_content_not_truncated(self) -> None:
        """None content with stop reason should not be truncated."""
        assert detect_truncation("stop", 0, None) is False

    def test_terminal_punctuation_not_truncated(self) -> None:
        """Response ending with various terminal punctuation should not be truncated."""
        assert detect_truncation("stop", 600, "Ends with period.") is False
        assert detect_truncation("stop", 600, "Ends with question?") is False
        assert detect_truncation("stop", 600, "Ends with exclamation!") is False
        assert detect_truncation("stop", 600, 'Ends with quote"') is False
        assert detect_truncation("stop", 600, "Ends with bracket)") is False
        assert detect_truncation("stop", 600, "Ends with code`") is False


# ---------------------------------------------------------------------------
# ProviderEvent
# ---------------------------------------------------------------------------


class TestProviderEvent:
    def test_default_values(self) -> None:
        """Event should have sensible defaults."""
        event = ProviderEvent(provider="openrouter", model="claude-sonnet")
        assert event.provider == "openrouter"
        assert event.model == "claude-sonnet"
        assert event.finish_reason == "stop"
        assert event.latency_ms == 0
        assert event.fallback_from == ""
        assert not event.suspected_truncated
        assert event.timestamp > 0

    def test_all_fields(self) -> None:
        """Event with all fields should preserve values."""
        event = ProviderEvent(
            provider="zai",
            model="glm-4.7",
            task_type="coding",
            timestamp=1000.0,
            finish_reason="length",
            latency_ms=1200,
            fallback_from="openrouter",
            error_message="",
            suspected_truncated=True,
            input_tokens=500,
            output_tokens=200,
        )
        assert event.provider == "zai"
        assert event.finish_reason == "length"
        assert event.latency_ms == 1200
        assert event.fallback_from == "openrouter"
        assert event.suspected_truncated is True


# ---------------------------------------------------------------------------
# ProviderStats
# ---------------------------------------------------------------------------


class TestProviderStats:
    def test_default_stats(self) -> None:
        """Default stats should be all zeros."""
        stats = ProviderStats()
        assert stats.total_calls == 0
        assert stats.avg_latency_ms == 0

    def test_avg_latency(self) -> None:
        """Average latency should be total / calls."""
        stats = ProviderStats(total_calls=4, total_latency_ms=4000)
        assert stats.avg_latency_ms == 1000

    def test_to_dict(self) -> None:
        """to_dict should return all stats."""
        stats = ProviderStats(
            total_calls=10,
            failures=2,
            truncations=1,
            content_filters=0,
            fallbacks_to=3,
            total_latency_ms=5000,
        )
        d = stats.to_dict()
        assert d["total_calls"] == 10
        assert d["failures"] == 2
        assert d["truncations"] == 1
        assert d["avg_latency_ms"] == 500


# ---------------------------------------------------------------------------
# ProviderTracker
# ---------------------------------------------------------------------------


class TestProviderTracker:
    def test_record_event(self) -> None:
        """Recording an event should increment stats."""
        tracker = ProviderTracker()
        event = ProviderEvent(
            provider="openrouter",
            model="claude-sonnet",
            latency_ms=1000,
        )
        tracker.record(event)
        stats = tracker.get_provider_stats()
        assert "openrouter" in stats
        assert stats["openrouter"]["total_calls"] == 1

    def test_empty_tracker(self) -> None:
        """Empty tracker should return empty stats."""
        tracker = ProviderTracker()
        assert tracker.get_provider_stats() == {}
        assert tracker.get_recent_events() == []

    def test_multiple_providers(self) -> None:
        """Multiple providers should be tracked separately."""
        tracker = ProviderTracker()
        tracker.record(
            ProviderEvent(provider="openrouter", model="claude", latency_ms=500)
        )
        tracker.record(ProviderEvent(provider="zai", model="glm", latency_ms=800))
        tracker.record(
            ProviderEvent(provider="openrouter", model="claude", latency_ms=600)
        )

        stats = tracker.get_provider_stats()
        assert stats["openrouter"]["total_calls"] == 2
        assert stats["zai"]["total_calls"] == 1
        assert stats["openrouter"]["avg_latency_ms"] == 550

    def test_failure_tracking(self) -> None:
        """Events with finish_reason='error' should count as failures."""
        tracker = ProviderTracker()
        tracker.record(
            ProviderEvent(provider="zai", model="glm", finish_reason="error")
        )
        tracker.record(ProviderEvent(provider="zai", model="glm", finish_reason="stop"))
        stats = tracker.get_provider_stats()
        assert stats["zai"]["failures"] == 1
        assert stats["zai"]["total_calls"] == 2

    def test_truncation_tracking(self) -> None:
        """Events with suspected_truncated should count as truncations."""
        tracker = ProviderTracker()
        tracker.record(
            ProviderEvent(
                provider="openrouter",
                model="claude",
                suspected_truncated=True,
                finish_reason="length",
            )
        )
        stats = tracker.get_provider_stats()
        assert stats["openrouter"]["truncations"] == 1

    def test_content_filter_tracking(self) -> None:
        """Events with finish_reason='content_filter' should be tracked."""
        tracker = ProviderTracker()
        tracker.record(
            ProviderEvent(
                provider="zai",
                model="glm",
                finish_reason="content_filter",
            )
        )
        stats = tracker.get_provider_stats()
        assert stats["zai"]["content_filters"] == 1

    def test_fallback_tracking(self) -> None:
        """Events with fallback_from should count as fallbacks."""
        tracker = ProviderTracker()
        tracker.record(
            ProviderEvent(
                provider="zai",
                model="glm",
                fallback_from="openrouter",
            )
        )
        stats = tracker.get_provider_stats()
        assert stats["zai"]["fallbacks_to"] == 1

    def test_get_recent_events(self) -> None:
        """get_recent_events should return last N events."""
        tracker = ProviderTracker()
        for i in range(30):
            tracker.record(ProviderEvent(provider="p", model="m", latency_ms=i))
        recent = tracker.get_recent_events(limit=5)
        assert len(recent) == 5
        assert recent[0].latency_ms == 25  # events 25-29

    def test_get_recent_events_empty(self) -> None:
        """get_recent_events on empty tracker should return empty list."""
        tracker = ProviderTracker()
        assert tracker.get_recent_events() == []
