"""Loop detection — catch a stuck run long before max_steps does."""

from __future__ import annotations

from core.loop_detect import LoopDetector, LoopVerdict
from tools.base import ToolResult


def _ok(payload: str = "same") -> ToolResult:
    return ToolResult(success=True, data={"content": payload})


class TestEscalation:
    def test_first_call_is_fine(self) -> None:
        detector = LoopDetector()
        assert detector.record("file_read", {"path": "/x"}, _ok()).verdict == (
            LoopVerdict.OK
        )

    def test_escalates_warn_block_abort(self) -> None:
        detector = LoopDetector()
        verdicts = [
            detector.record("file_read", {"path": "/x"}, _ok()).verdict
            for _ in range(4)
        ]
        assert verdicts == [
            LoopVerdict.OK,
            LoopVerdict.WARN,
            LoopVerdict.BLOCK,
            LoopVerdict.ABORT,
        ]

    def test_block_and_abort_flags(self) -> None:
        detector = LoopDetector()
        for _ in range(2):
            detector.record("t", {}, _ok())
        blocked = detector.record("t", {}, _ok())
        assert blocked.should_block_call
        assert not blocked.should_stop_run

        aborted = detector.record("t", {}, _ok())
        assert aborted.should_stop_run

    def test_messages_tell_the_model_what_to_do(self) -> None:
        detector = LoopDetector()
        for _ in range(2):
            detector.record("web_fetch", {"url": "u"}, _ok())
        signal = detector.record("web_fetch", {"url": "u"}, _ok())
        assert "web_fetch" in signal.message
        assert "different" in signal.message.lower()


class TestDiscrimination:
    def test_different_arguments_are_not_a_loop(self) -> None:
        detector = LoopDetector()
        for path in ("/a", "/b", "/c", "/d"):
            verdict = detector.record("file_read", {"path": path}, _ok()).verdict
            assert verdict == LoopVerdict.OK

    def test_different_results_are_not_a_loop(self) -> None:
        """Retrying a call that starts returning something new is progress."""
        detector = LoopDetector()
        for i in range(4):
            verdict = detector.record(
                "http_request", {"url": "u"}, _ok(f"payload-{i}")
            ).verdict
            assert verdict == LoopVerdict.OK

    def test_success_then_failure_is_not_a_repeat(self) -> None:
        detector = LoopDetector()
        detector.record("t", {}, ToolResult(success=True, data={"a": 1}))
        second = detector.record("t", {}, ToolResult(success=False, error="boom"))
        assert second.verdict == LoopVerdict.OK

    def test_unhashable_arguments_do_not_crash(self) -> None:
        detector = LoopDetector()
        weird = {"obj": object()}
        assert detector.record("t", weird, _ok()).verdict == LoopVerdict.OK


class TestLifecycle:
    def test_reset_clears_state_between_runs(self) -> None:
        """A cron job that repeats hourly must not inherit last run's count."""
        detector = LoopDetector()
        for _ in range(3):
            detector.record("t", {}, _ok())
        detector.reset()
        assert detector.record("t", {}, _ok()).verdict == LoopVerdict.OK
        assert detector.distinct_calls == 1

    def test_disabled_detector_never_fires(self) -> None:
        detector = LoopDetector(enabled=False)
        for _ in range(10):
            assert detector.record("t", {}, _ok()).verdict == LoopVerdict.OK

    def test_custom_thresholds(self) -> None:
        detector = LoopDetector(warn_at=2, block_at=2, abort_at=3)
        detector.record("t", {}, _ok())
        assert detector.record("t", {}, _ok()).verdict == LoopVerdict.BLOCK
        assert detector.record("t", {}, _ok()).verdict == LoopVerdict.ABORT

    def test_would_repeat_counts_prior_arg_matches(self) -> None:
        detector = LoopDetector()
        assert detector.would_repeat("t", {"a": 1}) == 0
        detector.record("t", {"a": 1}, _ok())
        detector.record("t", {"a": 1}, _ok("different"))
        assert detector.would_repeat("t", {"a": 1}) == 2
        assert detector.would_repeat("t", {"a": 2}) == 0

    def test_counters(self) -> None:
        detector = LoopDetector()
        detector.record("a", {}, _ok())
        detector.record("a", {}, _ok())
        detector.record("b", {}, _ok())
        assert detector.distinct_calls == 2
        assert detector.total_calls == 3
