"""Tests for the dashboard theme system."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from cli.dashboard.theme import (
    _BUILTIN_DIR,
    ThemeError,
    list_themes,
    load_theme,
    render_css,
    validate_theme_file,
)

# ── Every shipped built-in theme must load + validate ──────────────


def _builtin_theme_names() -> list[str]:
    return sorted(p.stem for p in _BUILTIN_DIR.glob("*.yaml"))


@pytest.mark.parametrize("name", _builtin_theme_names())
def test_builtin_theme_loads_and_renders(name: str) -> None:
    """Guards against shipping a malformed built-in theme."""
    t = load_theme(name)
    assert t.name  # non-empty
    css = render_css(t)
    assert "Screen {" in css
    # Cursor contrast: input cursor uses accent bg + background fg.
    assert t.colors.accent in css
    assert t.colors.background in css


# ── Default theme loads + renders ──────────────────────────────────


def test_default_theme_loads() -> None:
    t = load_theme("default")
    assert t.name == "default"
    assert t.colors.accent == "#7c3aed"
    assert t.colors.background == "#f9f8f4"
    assert t.layout.sidebar_width == 28
    assert "mascot" in t.layout.sidebar
    assert "chat" in t.layout.main


def test_default_render_css_includes_all_colors() -> None:
    t = load_theme("default")
    css = render_css(t)
    # Every color token must appear somewhere in the rendered CSS.
    for color in (
        t.colors.background,
        t.colors.surface,
        t.colors.raised,
        t.colors.border,
        t.colors.foreground,
        t.colors.muted,
        t.colors.accent,
        t.colors.placeholder,
    ):
        assert color in css, f"missing {color} in rendered CSS"


def test_default_render_css_no_legacy_hardcoded_colors() -> None:
    """If someone re-hardcodes a hex in the template, the test catches it."""
    t = load_theme("default")
    css = render_css(t)
    # The CSS should only contain hexes that came from the theme.
    # Belt-and-suspenders: every hex in the rendered CSS must equal
    # one of the theme's color values.
    import re

    theme_hexes = {
        getattr(t.colors, f)
        for f in (
            "background",
            "surface",
            "raised",
            "border",
            "foreground",
            "bright",
            "muted",
            "placeholder",
            "accent",
            "accent_alt",
            "success",
            "warning",
            "error",
            "info",
        )
    }
    rendered_hexes = set(re.findall(r"#[0-9a-fA-F]{6}", css))
    leak = rendered_hexes - theme_hexes
    assert not leak, f"non-theme hex literals in CSS: {leak}"


# ── Validation ──────────────────────────────────────────────────────


def _full_color_block() -> dict[str, str]:
    """A complete, valid colors dict (all keys present, all hex)."""
    return {
        k: "#000000"
        for k in (
            "background",
            "surface",
            "raised",
            "border",
            "foreground",
            "bright",
            "muted",
            "placeholder",
            "accent",
            "accent_alt",
            "success",
            "warning",
            "error",
            "info",
        )
    }


def test_missing_color_key_rejected(tmp_path: Path) -> None:
    colors = _full_color_block()
    del colors["accent"]
    yaml_text = textwrap.dedent(
        f"""\
        name: bad
        colors: {colors!r}
        layout:
          sidebar_width: 30
          sidebar: []
          main: []
    """
    )
    f = tmp_path / "bad.yaml"
    f.write_text(yaml_text)
    with pytest.raises(ThemeError, match="missing required color keys"):
        validate_theme_file(f)


def test_bad_hex_rejected(tmp_path: Path) -> None:
    colors = _full_color_block()
    colors["accent"] = "red"  # not hex
    yaml_text = textwrap.dedent(
        f"""\
        name: bad
        colors: {colors!r}
        layout:
          sidebar_width: 30
          sidebar: []
          main: []
    """
    )
    f = tmp_path / "bad.yaml"
    f.write_text(yaml_text)
    with pytest.raises(ThemeError, match="6-digit hex"):
        validate_theme_file(f)


def test_unknown_sidebar_panel_rejected(tmp_path: Path) -> None:
    yaml_text = textwrap.dedent(
        f"""\
        name: bad
        colors: {_full_color_block()!r}
        layout:
          sidebar_width: 30
          sidebar: [mascot, BOGUS]
          main: [chat]
    """
    )
    f = tmp_path / "bad.yaml"
    f.write_text(yaml_text)
    with pytest.raises(ThemeError, match="unknown sidebar panel"):
        validate_theme_file(f)


def test_sidebar_duplicate_rejected(tmp_path: Path) -> None:
    yaml_text = textwrap.dedent(
        f"""\
        name: bad
        colors: {_full_color_block()!r}
        layout:
          sidebar_width: 30
          sidebar: [mascot, agent, mascot]
          main: [chat]
    """
    )
    f = tmp_path / "bad.yaml"
    f.write_text(yaml_text)
    with pytest.raises(ThemeError, match="duplicates"):
        validate_theme_file(f)


def test_invalid_default_size_rejected(tmp_path: Path) -> None:
    yaml_text = textwrap.dedent(
        f"""\
        name: bad
        colors: {_full_color_block()!r}
        layout:
          sidebar_width: 30
          sidebar: []
          main: [reasoning]
          panels:
            reasoning:
              default_size: enormous
    """
    )
    f = tmp_path / "bad.yaml"
    f.write_text(yaml_text)
    with pytest.raises(ThemeError, match="default_size"):
        validate_theme_file(f)


def test_sidebar_width_out_of_range(tmp_path: Path) -> None:
    yaml_text = textwrap.dedent(
        f"""\
        name: bad
        colors: {_full_color_block()!r}
        layout:
          sidebar_width: 5
          sidebar: []
          main: []
    """
    )
    f = tmp_path / "bad.yaml"
    f.write_text(yaml_text)
    with pytest.raises(ThemeError, match="sidebar_width"):
        validate_theme_file(f)


# ── Discovery + extends ─────────────────────────────────────────────


def test_extends_chain_resolves(tmp_path: Path, monkeypatch) -> None:
    """A user theme that extends `default` inherits its colors."""
    user_dir = tmp_path / ".elophanto" / "themes"
    user_dir.mkdir(parents=True)
    (user_dir / "child.yaml").write_text(
        textwrap.dedent(
            """\
        name: child
        extends: default
        colors:
          accent: "#ff0000"
    """
        )
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    # _user_themes_dir() reads Path.home() which respects $HOME on POSIX.
    t = load_theme("child")
    assert t.colors.accent == "#ff0000"
    # Inherited from default — proves extends merging worked.
    assert t.colors.background == "#f9f8f4"


def test_extends_cycle_detected(tmp_path: Path, monkeypatch) -> None:
    user_dir = tmp_path / ".elophanto" / "themes"
    user_dir.mkdir(parents=True)
    colors = _full_color_block()
    (user_dir / "a.yaml").write_text(
        textwrap.dedent(
            f"""\
        name: a
        extends: b
        colors: {colors!r}
        layout: {{sidebar_width: 30, sidebar: [], main: []}}
    """
        )
    )
    (user_dir / "b.yaml").write_text(
        textwrap.dedent(
            f"""\
        name: b
        extends: a
        colors: {colors!r}
        layout: {{sidebar_width: 30, sidebar: [], main: []}}
    """
        )
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ThemeError, match="cycle"):
        load_theme("a")


def test_unknown_theme_raises(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ThemeError, match="not found"):
        load_theme("does-not-exist")


def test_list_themes_includes_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    themes = list_themes()
    assert "default" in themes
    assert "blade" in themes
    assert "nocturne" in themes


def test_yaml_none_in_child_inherits(tmp_path: Path, monkeypatch) -> None:
    """A child that writes `colors:` with no entries inherits the parent's colors.

    Catches the bug where an empty mapping (all entries commented out)
    parses to None and used to overwrite the parent value.
    """
    user_dir = tmp_path / ".elophanto" / "themes"
    user_dir.mkdir(parents=True)
    (user_dir / "minimal.yaml").write_text(
        textwrap.dedent(
            """\
        name: minimal
        extends: default
        colors:
        layout:
    """
        )
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    t = load_theme("minimal")
    # Colors fully inherited from default — none of them are nil.
    assert t.colors.accent == "#7c3aed"
    assert t.layout.sidebar_width == 28


# ── Dashboard construction (smoke) ──────────────────────────────────


def test_dashboard_constructs_with_blade_theme_by_default() -> None:
    """Constructing EloPhantoDashboard without args picks up blade."""
    from cli.dashboard.app import EloPhantoDashboard

    app = EloPhantoDashboard()
    assert app._theme.name == "blade"
    css = type(app).CSS
    assert "#050608" in css and "#f0a020" in css
    # Restore cream so later tests that assume default aren't polluted.
    EloPhantoDashboard(theme=load_theme("default"))


def test_dashboard_panel_registry_matches_theme_names() -> None:
    """Every name in SIDEBAR_PANEL_NAMES must have a registered ctor."""
    from cli.dashboard.app import _SIDEBAR_PANELS
    from cli.dashboard.theme import SIDEBAR_PANEL_NAMES

    missing = SIDEBAR_PANEL_NAMES - set(_SIDEBAR_PANELS)
    assert not missing, f"unregistered panels: {missing}"
    extra = set(_SIDEBAR_PANELS) - SIDEBAR_PANEL_NAMES
    assert not extra, f"panels registered but not declared in theme set: {extra}"


# ── Built-in nocturne (dark) theme ──────────────────────────────────


def test_nocturne_loads_and_is_dark() -> None:
    t = load_theme("nocturne")
    assert t.dark is True
    assert t.colors.background == "#0b0e14"
    assert t.colors.accent == "#5eead4"


# ── Built-in blade (product default, dark) theme ────────────────────


def test_blade_loads_and_is_dark() -> None:
    t = load_theme("blade")
    assert t.dark is True
    assert t.chrome == "hud"
    assert t.colors.background == "#050608"
    assert t.colors.accent == "#f0a020"
    assert t.colors.accent_alt == "#3aa8a0"


def test_blade_theme_sets_amber_glyphs_and_mascot() -> None:
    import cli.dashboard.app as app_mod
    from cli.dashboard import mascot as mascot_mod
    from cli.dashboard.app import EloPhantoDashboard, _Header, _MindPanel

    try:
        app = EloPhantoDashboard(theme=load_theme("blade"))
        assert app.dark is True
        assert app_mod._MIND == "#f0a020"
        assert app_mod._BG == "#050608"
        assert app_mod._is_hud() is True
        assert mascot_mod._CHROME_HUD is True
        assert _MindPanel.GLYPH_COLOR == "#f0a020"
        assert mascot_mod._STATE_COLORS["thinking"] == "#f0a020"
        assert "#f0a020" in type(app).CSS
        h = _Header(app._state)
        app._state.mind_state = "running"
        app._state.goals = [{"title": "Ship blade HUD", "checkpoint": "1/3"}]
        h.repaint()
        rail = str(h.render())
        assert "RUNNING" in rail
        assert "Ship blade" in rail
        # HUD face set — square sensors, no plush wink/laugh glyphs.
        face = mascot_mod.render_face("happy", frame=0)
        assert "■" in face
        assert "◡" not in face and "◯" not in face
        # HUD panel readout grammar (bodies, not just titles).
        from cli.dashboard.app import _CompaniesPanel, _GoalsPanel

        app._state.goals = [
            {
                "title": "Reframe hire",
                "pct": 50,
                "checkpoint": "2/4",
                "status": "active",
            }
        ]
        goals = _GoalsPanel(app._state).body()
        assert "|█" in goals or "|░░" in goals or "█" in goals
        assert "▶" in goals
        app._state.companies = [
            {
                "slug": "elophanto",
                "active": True,
                "trust": "operating",
                "voice": "yes",
                "strategy": "active",
                "blockers": 0,
                "net_7d": 0.0,
            }
        ]
        board = _CompaniesPanel(app._state).body()
        # Compact one-glance grammar: full TRUST/VOICE/STRAT labels wrapped in
        # the narrow HUD sidebar, so each is a single keyed letter plus net.
        assert "elophanto" in board
        assert "]T[" in board and "]O[" in board  # trust: operating
        assert "]V[" in board and "]S[" in board  # voice / strategy keys
        assert "$0" in board  # 7-day net
        assert "▶" in board  # active-company marker
        css = type(app).CSS
        assert "border-left: tall #f0a020" in css
        # Attention chips on the mission rail.
        app._state.approvals = [{"tool": "shell", "summary": "rm", "age_secs": 3}]
        app._state.companies[0]["blockers"] = 2
        h.repaint()
        rail2 = str(h.render())
        assert "AUTH 1" in rail2
        assert "BLK 2" in rail2
    finally:
        EloPhantoDashboard(theme=load_theme("default"))
        assert mascot_mod._STATE_COLORS["thinking"] == "#7c3aed"
        assert app_mod._is_hud() is False
        assert mascot_mod._CHROME_HUD is False


def test_hud_mascot_faces_have_no_plush_glyphs() -> None:
    from cli.dashboard import mascot as mascot_mod
    from cli.dashboard.mascot import frame_count

    soft = ("◡", "◯", "^", "⌒", "‿", "z", "Z")
    try:
        mascot_mod.set_chrome_hud(True)
        for face in mascot_mod._FACES_HUD:
            blob = "\n".join(mascot_mod._FACES_HUD[face])
            for g in soft:
                assert g not in blob, f"HUD {face} still has soft glyph {g!r}"
            assert frame_count(face) > 1
    finally:
        mascot_mod.set_chrome_hud(False)


def test_dark_theme_sets_app_dark_and_light_text() -> None:
    """A dark theme must flip App.dark and re-tint text to light.

    Without this the panels' near-black markup would be invisible
    on the dark background.
    """
    import cli.dashboard.app as app_mod
    from cli.dashboard.app import EloPhantoDashboard

    try:
        app = EloPhantoDashboard(theme=load_theme("nocturne"))
        assert app.dark is True
        # _BRIGHT (emphasized text) must now be light, not near-black.
        assert app_mod._BRIGHT == "#f2f6fc"
        assert app_mod._BG == "#0b0e14"
        assert app_mod._MIND == "#5eead4"
        css = type(app).CSS
        assert "#0b0e14" in css and "#5eead4" in css
    finally:
        # Restore the module palette so theme order can't pollute
        # other tests in the session.
        EloPhantoDashboard(theme=load_theme("default"))


def test_theme_switch_restores_default_palette() -> None:
    """Switching dark→light must fully restore glyph + text colors."""
    import cli.dashboard.app as app_mod
    from cli.dashboard.app import EloPhantoDashboard, _MindPanel

    EloPhantoDashboard(theme=load_theme("nocturne"))
    assert _MindPanel.GLYPH_COLOR == "#5eead4"  # teal under nocturne
    EloPhantoDashboard(theme=load_theme("default"))
    assert _MindPanel.GLYPH_COLOR == "#7c3aed"  # brand violet restored
    assert app_mod._BRIGHT == "#1c1a16"  # near-black text restored
