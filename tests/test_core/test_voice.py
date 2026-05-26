"""Voice profile + linter (ABE Phase 10 — anti-slop quality layer).

Locks in:
- load_voice() returns None when file missing / unparseable / not a mapping
- load_voice() parses persona / tone / length / hooks / banned_phrases / banned_patterns
- lint_text() catches banned phrases (case-insensitive substring)
- lint_text() catches banned regex patterns (case-insensitive)
- lint_text() enforces min/max char bounds
- lint_text() enforces allowed-hooks allowlist on the first non-empty line
- VoiceManager.lint() fail-soft when no voice.yaml exists for the company
- VoiceManager caches + reload() invalidates
"""

from __future__ import annotations

import pytest

from core.voice import (
    BannedPattern,
    LengthBounds,
    Voice,
    VoiceManager,
    lint_text,
    load_voice,
)


def _write_voice(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestLoadVoice:
    def test_missing_file_returns_none(self, tmp_path) -> None:
        assert load_voice(tmp_path, "no-such-co") is None

    def test_bad_yaml_returns_none(self, tmp_path) -> None:
        _write_voice(
            tmp_path / "data" / "companies" / "co" / "voice.yaml",
            "this: is: not: valid: yaml:",
        )
        # Malformed YAML — load_voice swallows and returns None
        assert load_voice(tmp_path, "co") is None

    def test_top_level_not_mapping_returns_none(self, tmp_path) -> None:
        _write_voice(
            tmp_path / "data" / "companies" / "co" / "voice.yaml",
            "- just\n- a\n- list\n",
        )
        assert load_voice(tmp_path, "co") is None

    def test_full_parse(self, tmp_path) -> None:
        _write_voice(
            tmp_path / "data" / "companies" / "co" / "voice.yaml",
            """
persona: founder writing on Twitter
tone: [direct, concrete]
length_target: { min_chars: 80, max_chars: 240 }
allowed_hooks:
  - "POV: <scenario>"
banned_phrases:
  - leverage
  - unlock
banned_patterns:
  - regex: "^We help"
    reason: self-focused hook
cta_style: soft — one line
""",
        )
        v = load_voice(tmp_path, "co")
        assert v is not None
        assert v.persona == "founder writing on Twitter"
        assert v.tone == ["direct", "concrete"]
        assert v.length_target.min_chars == 80
        assert v.length_target.max_chars == 240
        assert v.allowed_hooks == ["POV: <scenario>"]
        assert v.banned_phrases == ["leverage", "unlock"]
        assert len(v.banned_patterns) == 1
        assert v.banned_patterns[0].regex == "^We help"
        assert v.cta_style == "soft — one line"


class TestLintText:
    def test_empty_voice_passes_any(self) -> None:
        v = Voice()
        r = lint_text("anything goes", v)
        assert r.passed is True
        assert r.violations == []

    def test_banned_phrase_case_insensitive(self) -> None:
        v = Voice(banned_phrases=["leverage"])
        r = lint_text("We Leverage AI to deliver value", v)
        assert r.passed is False
        assert any("leverage" in vio for vio in r.violations)

    def test_banned_regex(self) -> None:
        v = Voice(
            banned_patterns=[BannedPattern(regex=r"^we help", reason="self-focused")]
        )
        r = lint_text("We help businesses unlock value", v)
        assert r.passed is False
        assert any("self-focused" in vio for vio in r.violations)

    def test_too_short(self) -> None:
        v = Voice(length_target=LengthBounds(min_chars=50, max_chars=0))
        r = lint_text("short.", v)
        assert r.passed is False
        assert any("too short" in vio for vio in r.violations)

    def test_too_long(self) -> None:
        v = Voice(length_target=LengthBounds(min_chars=0, max_chars=10))
        r = lint_text("this is definitely more than ten chars", v)
        assert r.passed is False
        assert any("too long" in vio for vio in r.violations)

    def test_hook_allowlist_matches(self) -> None:
        v = Voice(allowed_hooks=["POV: <scenario>"])
        r = lint_text("POV: you check your agent's overnight log", v)
        assert r.passed is True

    def test_hook_allowlist_rejects(self) -> None:
        v = Voice(allowed_hooks=["POV: <scenario>"])
        r = lint_text("We help businesses unlock value", v)
        assert r.passed is False
        assert any("opening line" in vio for vio in r.violations)
        # Suggestion should mention the allowed hook template
        assert any("POV:" in s for s in r.suggestions)

    def test_multiple_violations_collected(self) -> None:
        v = Voice(
            banned_phrases=["leverage"],
            length_target=LengthBounds(min_chars=200, max_chars=0),
        )
        r = lint_text("We leverage AI.", v)
        assert r.passed is False
        # Both rules fail
        assert len(r.violations) >= 2

    def test_bad_regex_does_not_crash(self) -> None:
        v = Voice(banned_patterns=[BannedPattern(regex="[unclosed")])
        # Should log warning, not raise
        r = lint_text("any text", v)
        assert r.passed is True


class TestVoiceManager:
    def test_no_project_root_always_passes(self) -> None:
        mgr = VoiceManager(None)
        r = mgr.lint("any text", company_id="co")
        assert r.passed is True

    def test_missing_voice_yaml_passes(self, tmp_path) -> None:
        mgr = VoiceManager(tmp_path)
        r = mgr.lint("any text", company_id="co")
        assert r.passed is True

    def test_lint_uses_loaded_contract(self, tmp_path) -> None:
        _write_voice(
            tmp_path / "data" / "companies" / "co" / "voice.yaml",
            "banned_phrases: [leverage]\n",
        )
        mgr = VoiceManager(tmp_path)
        r = mgr.lint("We leverage AI", company_id="co")
        assert r.passed is False

    def test_cache_then_reload(self, tmp_path) -> None:
        path = tmp_path / "data" / "companies" / "co" / "voice.yaml"
        _write_voice(path, "banned_phrases: [foo]\n")
        mgr = VoiceManager(tmp_path)
        # Prime cache
        assert mgr.lint("foo here", company_id="co").passed is False
        # Mutate file — cached read still uses old rules
        _write_voice(path, "banned_phrases: [bar]\n")
        assert mgr.lint("foo here", company_id="co").passed is False
        # reload picks up new rules
        mgr.reload("co")
        assert mgr.lint("foo here", company_id="co").passed is True
        assert mgr.lint("bar here", company_id="co").passed is False

    def test_exemplars_dir(self, tmp_path) -> None:
        mgr = VoiceManager(tmp_path)
        p = mgr.exemplars_dir("co", "twitter")
        assert p == tmp_path / "data" / "companies" / "co" / "exemplars" / "twitter"

    def test_voice_path(self, tmp_path) -> None:
        mgr = VoiceManager(tmp_path)
        assert mgr.voice_path("co") == (
            tmp_path / "data" / "companies" / "co" / "voice.yaml"
        )


@pytest.mark.asyncio
async def test_voice_module_loadable() -> None:
    # Pin the import surface — tools and agent depend on these names
    from core.voice import (  # noqa: F401
        VoiceManager,  # noqa: F401
        lint_text,
        load_voice,
    )
