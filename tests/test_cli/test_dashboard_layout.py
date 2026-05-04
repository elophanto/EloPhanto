"""Tests for the redesigned dashboard layout — sidebar panels, digest
renderer, and the build_digest_from_state helper that aggregates
sidebar state into the "since you were away" opening message.

Pure-function tests only — no Textual app instantiation. The
compose() wiring is structural and tested via launch (not feasible
in CI without a real terminal); this file covers the renderable
output of every panel + the digest builder, which is where logic
errors would actually surface.
"""

from __future__ import annotations

import pytest


class TestShortTokens:
    """Compact token-count formatter — drives sidebar tabular alignment."""

    @pytest.mark.parametrize(
        "n,expected",
        [
            (0, "0"),
            (42, "42"),
            (999, "999"),
            (1_500, "1.5k"),
            (12_345, "12k"),
            (45_000, "45k"),
            (1_500_000, "1.5M"),
            (10_000_000, "10.0M"),
        ],
    )
    def test_format(self, n: int, expected: str) -> None:
        from cli.dashboard.app import _short_tokens

        assert _short_tokens(n) == expected


class TestPanelRendering:
    """Each panel's body() produces non-empty markup when state has
    something to show, and a quiet placeholder ('· · ·' or empty
    string) when it doesn't."""

    def test_agent_idle_renders_idle_state(self) -> None:
        from cli.dashboard.app import _AgentPanel, _State

        panel = _AgentPanel(_State())
        body = panel.body()
        assert "idle" in body
        # Even on idle, the stats row (turns·tokens·cost) is shown.
        # Labels are glyph-only on the 30-col sidebar — verify the
        # numeric content rather than full words.
        assert "0" in body  # turns
        assert "$0.00" in body  # cost

    def test_agent_running_shows_tool_and_elapsed(self) -> None:
        import time

        from cli.dashboard.app import _AgentPanel, _State

        s = _State()
        s.current_tool = "shell_execute"
        s.current_tool_start = time.monotonic() - 5
        body = _AgentPanel(s).body()
        assert "shell_execute" in body
        # Elapsed seconds — must be a small integer right-padded for
        # tabular alignment.
        assert any(f"{i}s" in body for i in range(4, 8))

    def test_mind_resting_shows_eta(self) -> None:
        import time

        from cli.dashboard.app import _MindPanel, _State

        s = _State()
        s.mind_state = "sleeping"
        s.mind_sleep_ts = time.monotonic() - 30
        s.mind_next_wakeup_secs = 270  # 4 min after the 30s elapsed
        body = _MindPanel(s).body()
        assert "resting" in body
        # ETA value (4m or similar) is shown after ``resting ·`` — no
        # longer the verbose "wakes in" prefix (cut for sidebar fit).
        assert any(unit in body for unit in ("m", "s", "h"))

    def test_goals_empty_renders_quiet_placeholder(self) -> None:
        from cli.dashboard.app import _GoalsPanel, _State

        body = _GoalsPanel(_State()).body()
        # Empty bodies use the · · · placeholder per the visual
        # language. Asserts we don't accidentally show "no active
        # goals" or similar wordy text.
        assert "·" in body and "no active" not in body.lower()

    def test_goals_renders_progress_bar_and_checkpoint(self) -> None:
        from cli.dashboard.app import _GoalsPanel, _State

        s = _State()
        s.goals = [
            {
                "title": "ship invoice MVP",
                "pct": 43,
                "checkpoint": "3/7",
                "status": "active",
            },
        ]
        body = _GoalsPanel(s).body()
        # Title is truncated to 8 chars — Textual border + container
        # padding eats more than the 30-col panel width suggests, so
        # the visible budget is ~22 cols. Earlier (longer) caps wrapped
        # in real terminals.
        assert "ship inv" in body
        # Progress bar uses ▓ filled + ░ empty.
        assert "▓" in body and "░" in body
        # Checkpoint takes the right column when present.
        assert "3/7" in body

    def test_approvals_empty_returns_no_body(self) -> None:
        """Approvals panel hides itself when there's nothing to ask
        about — empty body + header lets the caller (compose) decide
        whether to show or hide the widget. We assert empty body
        rather than ' · · ·' because absence is the right signal."""
        from cli.dashboard.app import _ApprovalsPanel, _State

        body = _ApprovalsPanel(_State()).body()
        assert body == ""

    def test_approvals_renders_age_in_smallest_unit(self) -> None:
        from cli.dashboard.app import _ApprovalsPanel, _State

        s = _State()
        s.approvals = [
            {"tool": "browser_navigate", "summary": "open bank.com", "age_secs": 92},
        ]
        body = _ApprovalsPanel(s).body()
        # Tool name is truncated to 12 chars to fit the 22-col visible
        # sidebar budget. Assert the truncated prefix.
        assert "browser_navi" in body
        # 92 secs renders as 1m, not 92s.
        assert "1m" in body
        # Summary appears on second line.
        assert "open bank.com" in body

    def test_footer_shows_ego_and_peers(self) -> None:
        from cli.dashboard.app import _FooterPanel, _State

        s = _State()
        s.ego_coherence = 0.78
        s.ego_mood = "steady"
        s.p2p_peer_count = 3
        body = _FooterPanel(s).body()
        assert "0.78" in body
        assert "steady" in body
        # peer count rendered as positive int
        assert "peers" in body and "3" in body

    def test_footer_when_idle_shows_dash_and_zero(self) -> None:
        from cli.dashboard.app import _FooterPanel, _State

        body = _FooterPanel(_State()).body()
        assert "ego –" in body or "ego -" in body or "ego 0" in body
        assert "peers 0" in body


class TestDigestRenderer:
    """The digest is the load-bearing distinctive feature — when the
    user opens the terminal, this is what they see first. Test the
    renderer's output shape and edge cases."""

    def test_empty_digest_still_greets(self) -> None:
        from cli.dashboard.app import _Digest, _render_digest

        out = _render_digest(_Digest())
        # Even an empty digest produces a greeting line.
        assert "EloPhanto" in out
        # Trailing rule is always present — visual page break before chat.
        assert "─" in out

    def test_done_section_shown_when_populated(self) -> None:
        from cli.dashboard.app import _Digest, _DigestEntry, _render_digest

        d = _Digest(
            since_label="14h",
            done=[_DigestEntry(text="posted 3 X replies", detail="last 11m ago")],
        )
        out = _render_digest(d)
        assert "14h since you opened me" in out
        assert "Done while you were away" in out
        assert "posted 3 X replies" in out
        assert "last 11m ago" in out

    def test_empty_sections_skipped(self) -> None:
        """Sections with no entries render nothing — no awkward
        ``Done while you were away · (nothing)`` shells."""
        from cli.dashboard.app import _Digest, _render_digest

        out = _render_digest(_Digest(since_label="3h"))
        assert "Done while you were away" not in out
        assert "Doing now" not in out
        assert "Wanted your eyes on" not in out

    def test_mood_only_shown_when_signal_present(self) -> None:
        from cli.dashboard.app import _Digest, _render_digest

        # No mood, no ego — section absent entirely.
        out = _render_digest(_Digest())
        assert "Mood" not in out

        # With either signal, section appears.
        out = _render_digest(_Digest(mood="steady"))
        assert "Mood" in out and "steady" in out

        out = _render_digest(_Digest(ego_coherence=0.61))
        assert "Mood" in out and "0.61" in out

    def test_long_detail_text_does_not_break_layout(self) -> None:
        """A 200-char detail string shouldn't wrap weirdly or crash the
        renderer. We only assert no exception + presence of the text."""
        from cli.dashboard.app import _Digest, _DigestEntry, _render_digest

        long = "x" * 200
        d = _Digest(done=[_DigestEntry(text="t", detail=long)])
        out = _render_digest(d)
        assert long in out


class TestBuildDigestFromState:
    """The function that turns sidebar state + an optional seed dict
    into a `_Digest`. This is the bridge the dashboard uses on
    startup — when the launcher passes a seed, that wins; otherwise
    we derive a useful digest from active sidebar state."""

    def test_empty_state_and_seed_returns_minimal_digest(self) -> None:
        from cli.dashboard.app import _build_digest_from_state, _State

        d = _build_digest_from_state(_State(), {})
        assert d.since_label == ""
        assert d.done == []
        assert d.doing == []
        assert d.needs_eyes == []

    def test_seed_done_passes_through(self) -> None:
        from cli.dashboard.app import _build_digest_from_state, _State

        seed = {
            "since_label": "8h",
            "done": [{"text": "posted thread", "detail": "11m ago"}],
        }
        d = _build_digest_from_state(_State(), seed)
        assert d.since_label == "8h"
        assert len(d.done) == 1
        assert d.done[0].text == "posted thread"
        assert d.done[0].detail == "11m ago"

    def test_doing_auto_derived_from_goals_when_seed_omits_it(self) -> None:
        """The most useful behaviour: launcher doesn't bother
        populating doing-now, so we synthesize it from active goals."""
        from cli.dashboard.app import _build_digest_from_state, _State

        s = _State()
        s.goals = [
            {
                "title": "ship invoice MVP",
                "pct": 43,
                "checkpoint": "3/7",
                "status": "active",
            },
        ]
        d = _build_digest_from_state(s, {})
        assert len(d.doing) == 1
        assert "ship invoice MVP" in d.doing[0].text
        assert d.doing[0].detail == "3/7"

    def test_doing_auto_includes_running_swarm_tasks(self) -> None:
        from cli.dashboard.app import _build_digest_from_state, _State

        s = _State()
        s.swarm_tasks = [
            {"name": "PR-42", "agent": "claude-code", "status": "running", "pct": 60},
            {"name": "PR-43", "agent": "codex", "status": "queued", "pct": 0},
        ]
        d = _build_digest_from_state(s, {})
        # Only the running task is included — queued is not yet "doing".
        assert len(d.doing) == 1
        assert "PR-42" in d.doing[0].text
        assert "claude-code" in d.doing[0].detail

    def test_seed_doing_overrides_auto_derivation(self) -> None:
        """If the launcher gave us doing-now entries explicitly, those
        win over the auto-derivation. Operator intent beats heuristic."""
        from cli.dashboard.app import _build_digest_from_state, _State

        s = _State()
        s.goals = [{"title": "auto-derived goal", "pct": 50}]
        seed = {"doing": [{"text": "explicit override", "detail": "from launcher"}]}
        d = _build_digest_from_state(s, seed)
        assert len(d.doing) == 1
        assert d.doing[0].text == "explicit override"

    def test_needs_eyes_falls_back_to_pending_approvals(self) -> None:
        from cli.dashboard.app import _build_digest_from_state, _State

        s = _State()
        s.approvals = [
            {"tool": "browser_navigate", "summary": "open bank.com", "age_secs": 90},
        ]
        d = _build_digest_from_state(s, {})
        assert len(d.needs_eyes) == 1
        assert "browser_navigate" in d.needs_eyes[0].text
        assert "bank.com" in d.needs_eyes[0].detail

    def test_mood_pulled_from_state_ego(self) -> None:
        from cli.dashboard.app import _build_digest_from_state, _State

        s = _State()
        s.ego_mood = "focused"
        s.ego_coherence = 0.71
        d = _build_digest_from_state(s, {})
        assert d.mood == "focused"
        assert d.ego_coherence == 0.71

    def test_seed_mood_overrides_state_ego_mood(self) -> None:
        from cli.dashboard.app import _build_digest_from_state, _State

        s = _State()
        s.ego_mood = "from-state"
        d = _build_digest_from_state(s, {"mood": "from-seed"})
        assert d.mood == "from-seed"


class TestEgoQualifier:
    """Real production failure: gateway sent ``last_self_critique`` as
    ego.mood; dashboard truncated it to 14 chars and rendered
    ``ego 1.00 · I am better at`` — fragment of unsparing critique
    crammed into the footer. Looked like garbled prose.

    Fix: ego sends structured fields only (coherence, confidence_avg,
    humbling_count, tasks_since_recompute). Dashboard derives a
    one-word qualifier client-side via _ego_qualifier."""

    def test_empty_data_returns_green(self) -> None:
        from cli.dashboard.app import _ego_qualifier

        assert _ego_qualifier({}) == "green"

    def test_all_zeros_returns_green(self) -> None:
        """First-boot path. No capabilities recorded, no humbling
        events — the agent hasn't lived enough to have a state yet."""
        from cli.dashboard.app import _ego_qualifier

        assert (
            _ego_qualifier(
                {
                    "coherence": 0.0,
                    "confidence_avg": 0.0,
                    "humbling_count": 0,
                    "tasks_since_recompute": 0,
                }
            )
            == "green"
        )

    def test_real_user_data_maps_to_steady(self) -> None:
        """Verbatim from the user's SQLite: coherence 1.0 (default),
        mean confidence 0.73, no humbling, 23 tasks since recompute.
        Two under the stale threshold (25) — should read as steady,
        not settled (because 0.73 < 0.80 floor for settled)."""
        from cli.dashboard.app import _ego_qualifier

        result = _ego_qualifier(
            {
                "coherence": 1.0,
                "confidence_avg": 0.73,
                "confidence_min": 0.55,
                "confidence_max": 0.95,
                "humbling_count": 0,
                "tasks_since_recompute": 23,
            }
        )
        assert result == "steady"

    def test_stale_fires_at_25_tasks(self) -> None:
        from cli.dashboard.app import _ego_qualifier

        # 24 → still steady (under threshold)
        assert (
            _ego_qualifier(
                {
                    "coherence": 1.0,
                    "confidence_avg": 0.85,
                    "humbling_count": 0,
                    "tasks_since_recompute": 24,
                }
            )
            != "stale"
        )
        # 25 → stale
        assert (
            _ego_qualifier(
                {
                    "coherence": 1.0,
                    "confidence_avg": 0.85,
                    "humbling_count": 0,
                    "tasks_since_recompute": 25,
                }
            )
            == "stale"
        )

    def test_humbled_when_3_plus_humbling_events(self) -> None:
        from cli.dashboard.app import _ego_qualifier

        result = _ego_qualifier(
            {
                "coherence": 0.7,
                "confidence_avg": 0.55,
                "humbling_count": 4,
                "tasks_since_recompute": 2,
            }
        )
        assert result == "humbled"

    def test_shaken_when_coherence_below_50(self) -> None:
        from cli.dashboard.app import _ego_qualifier

        result = _ego_qualifier(
            {
                "coherence": 0.4,
                "confidence_avg": 0.6,
                "humbling_count": 0,
                "tasks_since_recompute": 5,
            }
        )
        assert result == "shaken"

    def test_questioning_for_mid_coherence(self) -> None:
        from cli.dashboard.app import _ego_qualifier

        result = _ego_qualifier(
            {
                "coherence": 0.65,
                "confidence_avg": 0.6,
                "humbling_count": 1,
                "tasks_since_recompute": 2,
            }
        )
        assert result == "questioning"

    def test_settled_only_when_coherence_high_and_confidence_high(self) -> None:
        """``settled`` is the rarest label — both numeric thresholds
        must clear, and no other state can pre-empt it."""
        from cli.dashboard.app import _ego_qualifier

        assert (
            _ego_qualifier(
                {
                    "coherence": 0.95,
                    "confidence_avg": 0.85,
                    "humbling_count": 0,
                    "tasks_since_recompute": 3,
                }
            )
            == "settled"
        )
        # Edge case: coherence 0.95 but confidence avg 0.79 — falls
        # short of settled, becomes steady.
        assert (
            _ego_qualifier(
                {
                    "coherence": 0.95,
                    "confidence_avg": 0.79,
                    "humbling_count": 0,
                    "tasks_since_recompute": 3,
                }
            )
            == "steady"
        )

    def test_no_prose_in_qualifier_output(self) -> None:
        """Regression: the qualifier must NEVER return prose like the
        first 14 chars of last_self_critique. The output vocabulary
        is fixed to a small word set."""
        from cli.dashboard.app import _ego_qualifier

        valid = {"green", "stale", "humbled", "shaken", "questioning", "steady", "settled"}
        # Sweep across the parameter space and assert every output is
        # one of the valid words.
        for coherence in (0.0, 0.3, 0.5, 0.7, 0.9, 1.0):
            for conf_avg in (0.0, 0.5, 0.7, 0.85):
                for humbling in (0, 1, 5):
                    for tasks_since in (0, 10, 30):
                        result = _ego_qualifier(
                            {
                                "coherence": coherence,
                                "confidence_avg": conf_avg,
                                "humbling_count": humbling,
                                "tasks_since_recompute": tasks_since,
                            }
                        )
                        assert result in valid, f"unexpected qualifier {result!r} for state ({coherence},{conf_avg},{humbling},{tasks_since})"
