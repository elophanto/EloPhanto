"""The browser drives the site the way a person does: a page is reached
by clicking what is visible or from a URL that was given, read or found —
never by typing a guessed path.

2026-09-02 (watch login): a scripted fallback to /login hit a 404 while a
"Login" button was on screen. 2026-09-03 (chat): the general agent typed
/usa/sports-betting-offers on a sportsbook and got a 404. The rule lives
where the model reads it on every step: the tool's own description."""

from __future__ import annotations


def test_browser_navigate_tells_the_model_not_to_guess_paths() -> None:
    from tools.browser.tools import _TOOL_DEFS

    name, description, schema, _level = next(
        d for d in _TOOL_DEFS if d[0] == "browser_navigate"
    )
    low = description.lower()
    assert "never invent a path" in low
    assert "/login" in description and "/offers" in description
    assert "click" in low and "search" in low
    assert schema["required"] == ["url"]


def test_the_browser_skill_carries_the_same_rule() -> None:
    from pathlib import Path

    text = Path("skills/browser-automation/SKILL.md").read_text(encoding="utf-8")
    assert "I need to reach another page on the site" in text
    assert "NEVER type a guessed path" in text
