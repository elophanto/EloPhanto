"""Tests for browser execution state tracking."""

from __future__ import annotations

from core.browser_executor import (
    OBSERVATION_TOOLS,
    STATE_CHANGING_TOOLS,
    BrowserExecutionState,
)


class TestBrowserExecutionState:
    def test_initial_state(self) -> None:
        state = BrowserExecutionState()
        assert state.needs_observation is False
        assert state.unobserved_changes == 0

    def test_state_changing_tool_sets_needs_observation(self) -> None:
        state = BrowserExecutionState()
        state.after_tool("browser_click")
        assert state.needs_observation is True
        assert state.unobserved_changes == 1

    def test_observation_tool_clears_needs_observation(self) -> None:
        state = BrowserExecutionState()
        state.after_tool("browser_click")
        assert state.needs_observation is True
        state.after_tool("browser_extract", {"text": "Hello"})
        assert state.needs_observation is False
        assert state.unobserved_changes == 0

    def test_multiple_actions_without_observation(self) -> None:
        state = BrowserExecutionState()
        state.after_tool("browser_click")
        state.after_tool("browser_type")
        state.after_tool("browser_navigate")
        assert state.unobserved_changes == 3

    def test_evidence_notice_none_when_no_observation_needed(self) -> None:
        state = BrowserExecutionState()
        assert state.get_evidence_notice() is None

    def test_evidence_notice_after_one_action(self) -> None:
        state = BrowserExecutionState()
        state.after_tool("browser_click")
        notice = state.get_evidence_notice()
        assert notice is not None
        assert "observe" in notice.lower()

    def test_evidence_notice_warning_after_multiple_actions(self) -> None:
        state = BrowserExecutionState()
        state.after_tool("browser_click")
        state.after_tool("browser_type")
        notice = state.get_evidence_notice()
        assert notice is not None
        assert "WARNING" in notice

    def test_stagnation_detection(self) -> None:
        state = BrowserExecutionState()
        # Simulate same action repeated
        for _ in range(3):
            state.after_tool("browser_click")
        notice = state.check_stagnation("browser_click")
        assert notice is not None
        assert "STAGNATION" in notice

    def test_no_stagnation_with_varied_actions(self) -> None:
        state = BrowserExecutionState()
        state.after_tool("browser_click")
        state.after_tool("browser_extract")
        state.after_tool("browser_type")
        assert state.check_stagnation("browser_navigate") is None

    def test_reset(self) -> None:
        state = BrowserExecutionState()
        state.after_tool("browser_click")
        state.after_tool("browser_type")
        state.reset()
        assert state.needs_observation is False
        assert state.unobserved_changes == 0
        assert state.get_evidence_notice() is None


class TestToolSets:
    def test_state_changing_and_observation_dont_overlap(self) -> None:
        overlap = STATE_CHANGING_TOOLS & OBSERVATION_TOOLS
        assert len(overlap) == 0, f"Overlap: {overlap}"

    def test_key_state_changing_tools_present(self) -> None:
        for name in [
            "browser_click",
            "browser_type",
            "browser_navigate",
            "browser_press_key",
        ]:
            assert name in STATE_CHANGING_TOOLS

    def test_key_observation_tools_present(self) -> None:
        for name in ["browser_extract", "browser_get_elements", "browser_screenshot"]:
            assert name in OBSERVATION_TOOLS
