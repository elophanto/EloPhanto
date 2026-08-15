"""A goal's checkpoints advance the goal — they don't audit the plumbing.

Asked for a social-casino competitor analysis, the decomposer made
checkpoint 1 "Verify Nevada proxy exit — at least 2 of 3 independent checks
report Nevada". The operator had since switched the exit to Florida, so the
criterion became unsatisfiable and the agent spent three hours reloading
ipwho.is / ipinfo.io / ipapi.co and collected nothing:

    13:05  Task verification round 1: incomplete (ipwho.is reporting Lake Wales, Florida…)
    14:56  Task verification round 1: incomplete (ipwho.is reporting Clearwater, Florida…)
    15:47  …still checking

Preconditions are the tools' job: `watch_observe` verifies its own exit and
refuses when it cannot prove the state. A plumbing checkpoint adds a way to
fail without adding a way to succeed.
"""

from __future__ import annotations

import re

from core.goal_manager import _DECOMPOSE_SYSTEM


class TestDecomposePromptForbidsPlumbing:
    def test_the_rule_is_stated(self) -> None:
        assert "NO PLUMBING CHECKPOINTS" in _DECOMPOSE_SYSTEM

    def test_it_names_the_things_not_to_check(self) -> None:
        text = _DECOMPOSE_SYSTEM.lower()
        for term in ("proxy exit", "geolocation", "credentials", "api key"):
            assert term in text, f"prompt should name {term!r} as not-a-checkpoint"

    def test_it_says_tools_enforce_their_own_preconditions(self) -> None:
        text = _DECOMPOSE_SYSTEM.lower()
        assert "fails and says so" in text
        assert "preconditions" in text

    def test_it_offers_the_alternative_rather_than_only_forbidding(self) -> None:
        """A rule with no escape hatch gets worked around."""
        flat = re.sub(r"\s+", " ", _DECOMPOSE_SYSTEM).lower()
        assert "fold it into the first real checkpoint's success criteria" in flat

    def test_it_carries_the_incident_that_motivated_it(self) -> None:
        assert "2026-08-15" in _DECOMPOSE_SYSTEM
        assert "three hours" in _DECOMPOSE_SYSTEM

    def test_the_rule_survives_prompt_reflow(self) -> None:
        """Matched on collapsed whitespace so re-wrapping cannot silently
        break the guidance into something the model reads differently."""
        flat = re.sub(r"\s+", " ", _DECOMPOSE_SYSTEM)
        assert "Every checkpoint must advance the user's goal, not confirm" in flat
