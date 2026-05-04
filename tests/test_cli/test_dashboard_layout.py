"""Tests for the redesigned terminal dashboard layout.

Covers the two new surfaces:

- ``_StatusBar`` — the one-row glance-able strip at the bottom of the
  screen that replaced the 30-column sidebar. Verifies state-to-text
  mapping for each segment (gateway, budget, mode, counts, mind), and
  that empty/zero values stay visually quiet (dim) rather than shouting.
- ``_render_digest()`` — the home-view "since you were away" digest
  rendered into the transcript on first connect. Verifies that the
  appropriate bands appear when their state is populated and stay
  silent when there's nothing to show.

We don't run the full Textual app loop here — too heavy for a unit
test and not what we're testing. Instead we instantiate the widgets
directly with a controlled `_State` and assert on the produced markup.
"""

from __future__ import annotations

import pytest

from cli.dashboard.app import _State, _StatusBar

# ---------------------------------------------------------------------------
# _StatusBar — state-to-text rendering
# ---------------------------------------------------------------------------


class _CapturingStatusBar(_StatusBar):
    """Subclass that captures the rendered line instead of pushing it
    into Textual's rendering pipeline. Lets us assert on the full
    formatted string the user would see, including Rich markup tokens."""

    def __init__(self, state: _State) -> None:
        super().__init__(state)
        self.rendered: str = ""

    def update(self, content: object = "", *args: object, **kwargs: object) -> None:  # type: ignore[override]
        # Textual's Static.update takes a renderable. Stringify so the
        # assertions can check substrings regardless of input type.
        self.rendered = str(content)


class TestStatusBar:
    def test_idle_state_is_quiet(self) -> None:
        """Fresh state, nothing happening. Status bar should show
        gateway as 'idle', zero counts as dim, no shouting accents."""
        bar = _CapturingStatusBar(_State())
        bar.repaint()
        out = bar.rendered
        assert "○ idle" in out  # gateway dot when no sessions
        assert "0" in out  # zero counts present
        assert "sched" in out and "goal" in out and "swarm" in out
        # The brand glyph is always there; mind state shows idle/dash.
        assert "◆" in out

    def test_active_session_shows_count(self) -> None:
        """An active session bumps the gateway segment from `○ idle`
        to `●N sess` so the user can see at a glance the gateway is up."""
        s = _State()
        s.sessions = [{"channel": "cli", "user": "0xroyce", "active": True}]
        bar = _CapturingStatusBar(s)
        bar.repaint()
        # Green dot + count of 1 + sess label.
        assert "●" in bar.rendered
        assert "1" in bar.rendered
        assert "sess" in bar.rendered

    def test_budget_color_shifts_above_threshold(self) -> None:
        """80%/95% are the visual gates — color of the budget number
        changes so the user can spot a runaway spend without reading
        the digits. Test all three bands (under, warn, over)."""
        for used, expected_token in [
            (10.0, "16a34a"),  # green at 10% of $100 default
            (85.0, "d97706"),  # amber at 85%
            (98.0, "red"),  # red at 98%
        ]:
            s = _State()
            s.budget_used = used
            bar = _CapturingStatusBar(s)
            bar.repaint()
            assert (
                expected_token in bar.rendered
            ), f"budget={used} expected color token {expected_token!r} in: {bar.rendered}"

    def test_zero_counts_render_dim_nonzero_render_accent(self) -> None:
        """Zero counts MUST stay dim — the bar shouldn't shout when
        nothing is happening. Non-zero counts get accent color so the
        eye is drawn."""
        s = _State()
        # Zero everything.
        bar0 = _CapturingStatusBar(s)
        bar0.repaint()
        # The dim color token must appear (it's used for the labels too,
        # so this is a sanity check the formatting didn't drop entirely).
        assert "78746e" in bar0.rendered  # _DIM color hex

        # Now bump scheduled_tasks count.
        s.scheduled_tasks = [{"name": "x", "eta_secs": 60}]
        bar1 = _CapturingStatusBar(s)
        bar1.repaint()
        # Accent color (#6d28d9) should appear in the rendered output
        # for the now-non-zero count.
        assert "6d28d9" in bar1.rendered

    def test_mind_state_indicator_reflects_phase(self) -> None:
        """The mind glyph color/text shifts: thinking, sleeping (with
        eta), or unknown/idle. Lets the user see at a glance whether
        the autonomous loop is actively burning compute."""
        for state, expected in [
            ("running", "thinking"),
            ("unknown", "◆ -"),
        ]:
            s = _State()
            s.mind_state = state
            bar = _CapturingStatusBar(s)
            bar.repaint()
            assert (
                expected in bar.rendered
            ), f"mind_state={state} expected {expected!r}: {bar.rendered}"


# ---------------------------------------------------------------------------
# _render_digest — home-view bands appear/hide based on state
# ---------------------------------------------------------------------------


class _CapturingTranscript:
    """Stand-in for a RichLog that records every line written. Used to
    introspect what the digest would have rendered without booting a
    full Textual app."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, content: object) -> None:
        self.lines.append(str(content))


@pytest.fixture
def fake_app(monkeypatch):
    """Build a minimal stand-in for EloPhantoDashboard exposing just
    the surface `_render_digest` touches: `_state`, `_approval_pending`,
    and a `query_one` that returns our capturing transcript."""
    from cli.dashboard.app import EloPhantoDashboard

    class FakeApp:
        def __init__(self) -> None:
            self._state = _State()
            self._approval_pending = None
            self._transcript = _CapturingTranscript()

        def query_one(self, selector: str, _kind: object = None):
            assert selector == "#transcript"
            return self._transcript

    # Bind the unbound method so it acts like a regular method on FakeApp.
    FakeApp._render_digest = EloPhantoDashboard._render_digest  # type: ignore[attr-defined]
    return FakeApp()


class TestRenderDigest:
    def test_header_always_rendered(self, fake_app) -> None:
        """Brand line + uptime + port appear regardless of state.
        Anchors the digest at the top of the transcript."""
        fake_app._render_digest()
        joined = "\n".join(fake_app._transcript.lines)
        assert "EloPhanto" in joined
        assert "port" in joined  # gateway port label
        assert "up" in joined  # uptime prefix

    def test_idle_state_shows_idle_hint_not_empty_bands(self, fake_app) -> None:
        """When nothing is happening, the digest shows a friendly
        idle hint instead of empty headers like 'Doing now' followed
        by nothing — that would look broken."""
        fake_app._render_digest()
        joined = "\n".join(fake_app._transcript.lines)
        assert "Idle." in joined
        assert "Doing now" not in joined  # no empty band header

    def test_active_goal_renders_doing_now_band(self, fake_app) -> None:
        """A live goal surfaces in the 'Doing now' band with the
        accent goal-glyph and the goal text."""
        fake_app._state.current_goal = "ship invoice MVP"
        fake_app._state.checkpoints_done = 3
        fake_app._render_digest()
        joined = "\n".join(fake_app._transcript.lines)
        assert "Doing now" in joined
        assert "ship invoice MVP" in joined
        assert "checkpoints" in joined
        assert "Idle." not in joined  # band content displaces idle hint

    def test_running_swarm_renders_in_doing_now(self, fake_app) -> None:
        fake_app._state.swarm_tasks = [
            {"name": "fix-billing-bug", "agent": "claude-code", "status": "running"},
            {"name": "old-task", "agent": "x", "status": "done"},
        ]
        fake_app._render_digest()
        joined = "\n".join(fake_app._transcript.lines)
        assert "Doing now" in joined
        assert "fix-billing-bug" in joined
        # Done tasks don't appear — only running ones surface.
        assert "old-task" not in joined

    def test_scheduled_tasks_show_count_and_next_eta(self, fake_app) -> None:
        fake_app._state.scheduled_tasks = [
            {"name": "Email Inbox Check", "eta_secs": 600},
            {"name": "X Post", "eta_secs": 1800},
        ]
        fake_app._render_digest()
        joined = "\n".join(fake_app._transcript.lines)
        assert "scheduled" in joined
        assert "2" in joined  # count of scheduled tasks
        # Next ETA is 600s = 10m; either string is acceptable.
        assert "10m" in joined or "next in" in joined

    def test_pending_approval_surfaces_in_attention_band(self, fake_app) -> None:
        # Simulate an approval-pending GatewayMessage shape — only
        # accesses .data.get for our purposes so a minimal stub works.
        class FakeMsg:
            data = {"tool": "browser_navigate"}

        fake_app._approval_pending = FakeMsg()
        fake_app._render_digest()
        joined = "\n".join(fake_app._transcript.lines)
        assert "Wanted your eyes on" in joined
        assert "browser_navigate" in joined
        assert "approve" in joined  # the (a/d) hint

    def test_recent_activity_band_when_events_present(self, fake_app) -> None:
        # Push a few entries into the events deque (matches what
        # _add_event would do).
        from collections import deque

        fake_app._state.events = deque(
            [
                "10:01  AGT  ▸ shell_execute",
                "10:02  SCH  ✅ scheduled: Email Inbox Check",
                "10:03  MIN  cycle 7 woke",
            ]
        )
        fake_app._render_digest()
        joined = "\n".join(fake_app._transcript.lines)
        assert "Recent activity" in joined
        # All three event entries should be visible (under the cap of 5).
        assert "shell_execute" in joined
        assert "Email Inbox Check" in joined
        assert "cycle 7" in joined

    def test_separator_anchors_digest_above_chat(self, fake_app) -> None:
        """A horizontal-rule line of dashes ends the digest. Visual
        anchor so the user can scroll up later and find 'where the
        digest ended and the chat began'."""
        fake_app._render_digest()
        joined = "\n".join(fake_app._transcript.lines)
        # 60 dashes is the rule we render. Substring match is robust
        # to surrounding markup tags.
        assert "─" * 60 in joined
