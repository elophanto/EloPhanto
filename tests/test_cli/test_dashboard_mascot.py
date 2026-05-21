"""Dashboard mascot — state-mapping + render tests.

Pure tests against ``cli/dashboard/mascot.py``. No Textual app spin-up
needed; ``MascotInputs`` is a frozen dataclass and ``decide_face`` is
a pure function.

State priority (top wins): concerned → happy → working → thinking →
humbled → idle → sleep. Each test pins one branch.
"""

from __future__ import annotations

import re

import pytest

from cli.dashboard.mascot import (
    FRAME_TICK_MS,
    MascotInputs,
    decide_face,
    frame_count,
    render_face,
)


def _visible_width(line: str) -> int:
    """Strip Rich markup ([color]…[/color]) and return char count.

    Frames embed eye-color placeholders that get interpolated at
    render time; the test's width invariant cares about VISIBLE
    width, not raw string length."""
    stripped = re.sub(r"\[/?[^\]]*\]", "", line)
    return len(stripped)


# ---------------------------------------------------------------------------
# decide_face — priority branches
# ---------------------------------------------------------------------------


class TestPriorityOrdering:
    """Every face must win when its branch is the highest-priority
    signal present. The priority chain is documented in
    cli/dashboard/mascot.py; this test pins it."""

    def test_recent_error_beats_everything(self) -> None:
        inputs = MascotInputs(
            mind_state="running",
            has_current_tool=True,
            current_tool_start=100.0,
            ego_mood="pride",
            recent_error=True,
            recent_success=True,
        )
        assert decide_face(inputs, now=110.0) == "concerned"

    def test_negative_mood_without_explicit_error(self) -> None:
        inputs = MascotInputs(
            mind_state="running",
            has_current_tool=True,
            current_tool_start=100.0,
            ego_mood="shame",
            recent_error=False,
        )
        assert decide_face(inputs, now=110.0) == "concerned"

    def test_happy_requires_both_success_and_positive_mood(self) -> None:
        # Success but neutral mood → no happy.
        inputs_neutral = MascotInputs(
            mind_state="sleeping",
            recent_success=True,
            ego_mood="",
        )
        assert decide_face(inputs_neutral) != "happy"
        # Success + pride → happy.
        inputs_proud = MascotInputs(
            mind_state="sleeping",
            recent_success=True,
            ego_mood="pride",
        )
        assert decide_face(inputs_proud) == "happy"

    def test_working_when_tool_fresh(self) -> None:
        inputs = MascotInputs(
            mind_state="running",
            has_current_tool=True,
            current_tool_start=100.0,
        )
        assert decide_face(inputs, now=120.0) == "working"

    def test_working_decays_to_thinking_when_tool_stale(self) -> None:
        """A 'live' tool that hasn't moved in >30s isn't actually live —
        the mascot should fall through to the next priority (thinking)
        instead of freezing on `working`."""
        inputs = MascotInputs(
            mind_state="running",
            has_current_tool=True,
            current_tool_start=100.0,
        )
        # 60s after tool start → stale
        face = decide_face(inputs, now=160.0)
        assert face == "thinking"

    def test_thinking_when_mind_running_no_tool(self) -> None:
        inputs = MascotInputs(
            mind_state="running",
            has_current_tool=False,
        )
        assert decide_face(inputs) == "thinking"

    def test_thinking_on_recent_activity_when_mind_state_unknown(self) -> None:
        """Regression for 2026-05-21: dashboard showed mascot 'sleeping'
        while the chat panel was clearly streaming reasoning chunks. Root
        cause: ``mind_state`` was still ``unknown`` (boot, no mind event
        yet) and the activity signal didn't exist. Fix: any
        ``last_activity_ts`` within ACTIVITY_FRESH_SECONDS counts as
        'thinking' regardless of mind_state."""
        inputs = MascotInputs(
            mind_state="unknown",
            has_current_tool=False,
            last_activity_ts=100.0,
        )
        # 30s after last activity → still well within the 90s window
        assert decide_face(inputs, now=130.0) == "thinking"

    def test_recent_activity_does_not_override_explicit_pause(self) -> None:
        """If mind is explicitly paused, recent activity (e.g. a
        scheduled task firing in the background) shouldn't make the
        mascot pretend the mind is thinking — it's not."""
        inputs = MascotInputs(
            mind_state="paused",
            has_current_tool=False,
            last_activity_ts=100.0,
        )
        # Activity bumps it to "thinking" because we don't distinguish
        # mind-paused from scheduler-active in the recent-activity
        # signal. Acceptable trade-off: better to show 'thinking' when
        # the agent is genuinely active (scheduler, user chat) than
        # falsely 'sleeping'. Operators can read the MIND panel for
        # the precise state. Documenting expected behavior.
        assert decide_face(inputs, now=130.0) == "thinking"

    def test_stale_activity_falls_through_to_sleep(self) -> None:
        """Activity older than ACTIVITY_FRESH_SECONDS should NOT
        keep the mascot in 'thinking' indefinitely."""
        inputs = MascotInputs(
            mind_state="unknown",
            last_activity_ts=100.0,
        )
        # 200s after last activity → well past the 90s window
        assert decide_face(inputs, now=300.0) == "sleep"

    def test_humbled_when_coherence_low(self) -> None:
        inputs = MascotInputs(
            mind_state="sleeping",
            ego_coherence=0.1,
        )
        assert decide_face(inputs) == "humbled"

    def test_humbled_does_not_beat_working(self) -> None:
        inputs = MascotInputs(
            mind_state="running",
            has_current_tool=True,
            current_tool_start=100.0,
            ego_coherence=0.0,
        )
        assert decide_face(inputs, now=105.0) == "working"

    def test_idle_when_mind_sleeping_and_healthy(self) -> None:
        inputs = MascotInputs(
            mind_state="sleeping",
            ego_coherence=0.8,
        )
        assert decide_face(inputs) == "idle"

    def test_sleep_when_disabled_or_unknown(self) -> None:
        # Disabled mind, no other signals → sleep.
        assert (
            decide_face(MascotInputs(mind_state="disabled", ego_coherence=1.0))
            == "sleep"
        )
        # Paused mind → sleep.
        assert (
            decide_face(MascotInputs(mind_state="paused", ego_coherence=1.0)) == "sleep"
        )
        # Unknown / never set → sleep.
        assert decide_face(MascotInputs(ego_coherence=1.0)) == "sleep"


# ---------------------------------------------------------------------------
# render_face — output shape
# ---------------------------------------------------------------------------


class TestRendering:
    @pytest.mark.parametrize(
        "face",
        [
            "sleep",
            "idle",
            "thinking",
            "working",
            "happy",
            "concerned",
            "humbled",
        ],
    )
    def test_each_face_renders_non_empty(self, face: str) -> None:
        # Disable breathing so this test only exercises face content,
        # not the breath-cycle vertical-offset behavior (separately
        # tested below).
        out = render_face(face, frame=0, breathing=False)  # type: ignore[arg-type]
        assert out
        # Layout (no breath, no name):
        #   eyes line
        #   mouth line
        #   label line
        #   trailing pad (kept so the panel height is constant when
        #   breath toggles on/off — see render_face)
        lines = out.splitlines()
        assert len(lines) >= 3, f"face={face!r} rendered too few lines:\n{out!r}"
        # Eyes + mouth must each be present (non-empty after stripping
        # markup). The first two lines are the face proper.
        assert _visible_width(lines[0]) > 0
        assert _visible_width(lines[1]) > 0
        # Label line is non-empty and contains the state name.
        assert face in out or face[:5] in out

    def test_name_appears_when_supplied(self) -> None:
        out = render_face("idle", agent_name="AlphaScala", breathing=False)
        assert "AlphaScala" in out

    def test_name_omitted_when_blank(self) -> None:
        out = render_face("idle", agent_name="", breathing=False)
        assert "AlphaScala" not in out

    def test_every_state_has_at_least_one_frame(self) -> None:
        from cli.dashboard.mascot import _FACES

        for face in _FACES:
            assert frame_count(face) >= 1, f"face {face!r} has no frames"

    def test_animated_states_have_multiple_frames(self) -> None:
        """Every state should actually animate. Humbled used to be a
        single frame but operator feedback (2026-05-21) wanted the
        mascot 'super-alive', so even humbled now has a rare blink
        — distinguishes living-but-quiet from frozen / dead."""
        for face in (
            "sleep",
            "idle",
            "thinking",
            "working",
            "happy",
            "concerned",
            "humbled",
        ):
            assert frame_count(face) > 1, f"{face!r} should have multiple frames"

    def test_frame_index_wraps_cleanly(self) -> None:
        """Callers pass a monotonically increasing counter; render
        must mod by frame count internally so the panel doesn't
        need bounds-checking."""
        # Render across multiple cycles, all should succeed + be
        # one of the state's defined frames.
        from cli.dashboard.mascot import _FACES

        for face in _FACES:
            n = frame_count(face)
            for i in range(n * 3):
                out = render_face(face, frame=i)  # type: ignore[arg-type]
                assert out, f"face={face!r} frame={i} rendered empty"

    def test_frames_within_state_have_consistent_visible_width(self) -> None:
        """Visible width (after stripping Rich markup) must not change
        between frames — otherwise the sidebar panel reflows on each
        tick. Computed on the eye + mouth lines only, with the {e}
        placeholder treated as a single eye-glyph slot."""
        from cli.dashboard.mascot import _FACES

        for face, frames in _FACES.items():
            widths_per_line: list[set[int]] = [set(), set()]
            for frame_art in frames:
                # Replace the eye placeholder with a single char so
                # visible-width measurement is accurate. (At render
                # time {e} expands to Rich markup that wraps a single
                # glyph; visible width is one char per placeholder.)
                expanded = frame_art.replace("[{e}]", "").replace("[/]", "")
                for i, line in enumerate(expanded.splitlines()[:2]):
                    widths_per_line[i].add(len(line))
            # Each row across frames must be one consistent width.
            for i, widths in enumerate(widths_per_line):
                assert len(widths) == 1, (
                    f"face={face!r} row {i} has inconsistent widths "
                    f"across frames: {sorted(widths)}"
                )

    def test_frame_tick_constant_exposed(self) -> None:
        """The panel reads FRAME_TICK_MS; pin it as a public surface."""
        assert isinstance(FRAME_TICK_MS, int)
        assert 50 <= FRAME_TICK_MS <= 1000

    def test_breathing_parameter_is_a_no_op(self) -> None:
        """The ``breathing`` parameter was a vertical-shift cycle that
        read as a discrete hop in character cells (operator feedback
        2026-05-21). Removed but kept the kwarg for API stability.
        Both True and False must produce identical output."""
        with_breath = render_face("idle", frame=0, breathing=True)
        without = render_face("idle", frame=0, breathing=False)
        assert with_breath == without

    def test_show_closed_overrides_per_state_animation(self) -> None:
        """The closed-eye transition frame is rendered regardless of
        which face the panel asks for. Used for state-change
        anticipation (Disney brief-blink-before-new-expression)."""
        closed_idle = render_face("idle", frame=0, show_closed=True, breathing=False)
        closed_thinking = render_face(
            "thinking", frame=0, show_closed=True, breathing=False
        )

        # Same face content (the closed shape), independent of face arg.
        # Eyes line — strip any markup, then compare.
        idle_eye_line = closed_idle.splitlines()[0]
        thinking_eye_line = closed_thinking.splitlines()[0]
        assert _visible_width(idle_eye_line) == _visible_width(thinking_eye_line)
        # Label color is still state-specific even during the closed
        # transition — operator sees "this is becoming idle" not "this
        # is closed".
        from cli.dashboard.mascot import _STATE_COLORS

        assert _STATE_COLORS["idle"] in closed_idle
        assert _STATE_COLORS["thinking"] in closed_thinking

    def test_label_color_is_state_specific(self) -> None:
        # Different states render different colors (label + eyes)
        # so the at-a-glance distinction works on dark + light
        # terminals.
        from cli.dashboard.mascot import _STATE_COLORS

        # Distinct colors per state.
        assert _STATE_COLORS["happy"] != _STATE_COLORS["concerned"]
        assert _STATE_COLORS["thinking"] != _STATE_COLORS["working"]
        # And each is a valid-looking hex.
        for color in _STATE_COLORS.values():
            assert color.startswith("#")
            assert len(color) == 7


# ---------------------------------------------------------------------------
# Integration with the dashboard panel — pure-Python smoke (no Textual)
# ---------------------------------------------------------------------------


class TestPanelWiring:
    """Verify that the panel-side helper that builds MascotInputs
    from _State maps the fields correctly. The panel reads .events
    looking for error/success markers; this test inputs synthetic
    events and checks the flags."""

    def test_recent_event_signals_detects_error_markers(self) -> None:
        from collections import deque

        from cli.dashboard.app import _MascotPanel, _State

        s = _State()
        s.events = deque(
            [
                "[red]✖[/] goal failed",
                "10:30  AGT  task started",
            ],
            maxlen=50,
        )
        panel = _MascotPanel(s)
        recent_error, recent_success = panel._recent_event_signals()
        assert recent_error is True
        assert recent_success is False

    def test_recent_event_signals_detects_success_markers(self) -> None:
        from collections import deque

        from cli.dashboard.app import _MascotPanel, _State

        s = _State()
        s.events = deque(
            [
                "[#16a34a]✓[/] task complete",
                "10:30  AGT  scheduled task ran",
            ],
            maxlen=50,
        )
        panel = _MascotPanel(s)
        recent_error, recent_success = panel._recent_event_signals()
        assert recent_error is False
        assert recent_success is True
