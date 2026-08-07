"""A role mask must never outlive the cycle that set it.

The pin is applied while BUILDING the prompt, which happens before _think's
try/finally opens — so a failure in that window stranded the mask. Worse, the
next cycle's pin overwrote the unreleased token, and since that token was the
only handle capable of restoring the contextvar, a one-cycle leak became
permanent. With goal tools role-gated at the time, a stuck mask could deny the
mind its own goal bookkeeping.
"""

from __future__ import annotations

from core.role_context import current_role, reset_current_role, set_current_role


class _Pinner:
    """Minimal stand-in for AutonomousMind's pin lifecycle."""

    def __init__(self) -> None:
        self._role_pin_token = None

    # Mirrors AutonomousMind._release_role_pin
    def _release_role_pin(self) -> None:
        token = self._role_pin_token
        self._role_pin_token = None
        if token is None:
            return
        try:
            reset_current_role(token)
        except Exception:
            pass

    def pin(self, role: str) -> None:
        # Mirrors the fixed pin site: release before set.
        self._release_role_pin()
        self._role_pin_token = set_current_role(role)


class TestRolePinLifecycle:
    def test_pin_then_release_restores_the_previous_role(self) -> None:
        p = _Pinner()
        before = current_role()
        p.pin("marketing")
        assert current_role() == "marketing"
        p._release_role_pin()
        assert current_role() == before

    def test_repinning_does_not_strand_the_contextvar(self) -> None:
        """The permanence bug: pin, pin again without releasing, then release.

        If the second pin overwrites a live token, the original value can never
        be restored and the mask sticks forever.
        """
        p = _Pinner()
        before = current_role()
        p.pin("marketing")
        p.pin("ops")  # release-before-set happens inside
        assert current_role() == "ops"
        p._release_role_pin()
        assert current_role() == before, "role mask outlived its cycle"

    def test_release_on_entry_clears_a_leak_from_a_prior_cycle(self) -> None:
        """Simulates a crash between the pin and the try/finally: the token is
        still held, and the NEXT cycle must clear it on entry."""
        p = _Pinner()
        before = current_role()
        p.pin("sales")
        assert current_role() == "sales"
        # ...cycle dies here without reaching its finally...
        # next cycle begins:
        p._release_role_pin()
        assert current_role() == before

    def test_release_is_idempotent(self) -> None:
        p = _Pinner()
        before = current_role()
        p.pin("ops")
        p._release_role_pin()
        p._release_role_pin()
        assert current_role() == before

    def test_release_without_a_pin_is_safe(self) -> None:
        p = _Pinner()
        p._release_role_pin()
        assert p._role_pin_token is None


def test_think_releases_the_pin_on_entry_and_in_finally() -> None:
    """Source guard: both halves must exist, or a leak in the pre-try window
    persists across cycles."""
    from pathlib import Path

    src = Path("core/autonomous_mind.py").read_text()
    think = src[src.index("async def _think(") : src.index("def _dream_journal_handle")]
    assert think.count("self._release_role_pin()") >= 2, (
        "_think must release the pin on entry AND in its finally"
    )
    # And the pin site must release before overwriting a live token.
    pin_site = src[src.index("Release first:") : src.index("Release first:") + 500]
    assert "self._release_role_pin()" in pin_site
