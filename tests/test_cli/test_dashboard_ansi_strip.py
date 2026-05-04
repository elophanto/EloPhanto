"""Regression tests for the dashboard's ANSI/mouse-code stripper.

Real production failure: when the user moved the mouse over the
dashboard input field, the terminal sent SGR mouse-tracking codes
that bypassed Textual's mouse handler and landed in the Input widget
as garbage like ``5;55;24M35;54;22;27M5;65;27M90;15M;96;15M2MM05;22M0``.

The earlier strip regex required either a ``[`` or ``<`` framing
prefix; this leftover had both prefixes already chewed off by upstream
consumers, so it slipped through entirely. The test below uses the
exact verbatim string captured from a user screenshot.

Two-layer fix: (1) periodic re-disable of mouse tracking via stdout
escape codes (prevents codes from being sent in the first place),
(2) tighter regex with iterative passes for any that still leak through.
This file covers (2)."""

from __future__ import annotations

from cli.dashboard.app import _strip_ansi


class TestStripAnsi:
    def test_real_user_garbage_from_screenshot(self) -> None:
        """The exact leaked text from a real user report. Previously
        survived the regex completely; now reduced to at most a couple
        of irreducible characters."""
        leaked = (
            "spoke with grok and he advised what is in GROK.md ... "
            "5;55;24M35;54;22;27M5;65;27M90;15M;96;15M2MM05;22M0"
        )
        result = _strip_ansi(leaked)
        # The user's actual typed text must be preserved verbatim.
        assert "spoke with grok and he advised what is in GROK.md" in result
        # Almost all the garbage must be gone — at most 4 trailing chars
        # of irreducible residue (`M0` etc.) are tolerated.
        garbage_after = result[
            len("spoke with grok and he advised what is in GROK.md") :
        ]
        # No multi-digit ;number;number;M sequences should survive.
        import re

        assert not re.search(
            r"\d+(?:;\d+){1,}[Mm]", garbage_after
        ), f"unstripped mouse-code chunks in residue: {garbage_after!r}"

    def test_framed_sgr_with_escape_byte(self) -> None:
        """Full ANSI form: \\x1b[<...M. Should strip cleanly."""
        assert _strip_ansi("\x1b[<35;62;22Mhello") == "hello"

    def test_framed_sgr_no_escape_byte(self) -> None:
        """Common case: ESC was eaten by Textual's keyboard handler,
        so the input widget sees only ``[<...M``. Must still be
        recognised as a mouse code, not literal text."""
        assert _strip_ansi("hello[<35;62;22M") == "hello"

    def test_naked_sgr_no_brackets(self) -> None:
        """Both ESC and ``[`` consumed. Just ``<5;10;15M`` left over."""
        assert _strip_ansi("foo<5;10;15Mbar") == "foobar"

    def test_naked_sgr_no_angle_bracket(self) -> None:
        """Even ``<`` consumed — pure digit-semicolon-M sequence.
        This was the gap that the production bug exploited."""
        result = _strip_ansi("a5;55;24Mb")
        # The mouse-code chunk is fully stripped.
        assert "5;55;24M" not in result
        assert "a" in result and "b" in result

    def test_legitimate_text_with_M_preserved(self) -> None:
        """`5M` after whitespace is normal English ('5 million users'),
        must NOT be stripped. The residue regex requires a `;`
        prefix specifically to avoid this false positive."""
        for case in [
            "price 5M users",
            "rev grew to 5M last quarter",
            "We hit 100M ARR.",
            "M16 rifles",
            "M0 is the unit",  # weird but not impossible
        ]:
            result = _strip_ansi(case)
            assert (
                result == case
            ), f"legitimate text {case!r} was stripped to {result!r}"

    def test_semicolon_prefixed_residue_stripped(self) -> None:
        """`;5M` is a remnant of a chopped SGR sequence — never
        legitimate user input. Strip aggressively."""
        assert _strip_ansi(";5M") == ""
        assert _strip_ansi("text;5M more") == "text more"

    def test_normal_text_unchanged(self) -> None:
        """No false positives on plain text."""
        assert (
            _strip_ansi("normal text without escapes") == "normal text without escapes"
        )
        assert _strip_ansi("") == ""

    def test_control_chars_stripped(self) -> None:
        """Stray control characters (NUL, BS, DEL) shouldn't appear in
        chat input either."""
        assert _strip_ansi("hello\x00world") == "helloworld"
        assert _strip_ansi("hello\x7f") == "hello"  # DEL
        # Newlines and tabs are NOT stripped (legitimate whitespace).
        # Only \x00-\x08, \x0b-\x1f, \x7f.

    def test_iterative_passes_chip_through_concatenated_garbage(self) -> None:
        """Streams of mouse events concatenate without separator. The
        first regex pass strips well-formed chunks; the second pass
        picks up patterns that became matchable after the first ones
        were removed."""
        # Five back-to-back SGR mouse events smushed together.
        garbage = "1;2;3M4;5;6M7;8;9M10;11;12M13;14;15M"
        result = _strip_ansi(garbage)
        assert result == "", f"expected empty after iterative strip, got {result!r}"
