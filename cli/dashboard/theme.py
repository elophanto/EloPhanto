"""Dashboard theme system — YAML-declared, user-extensible.

A theme is a pure declarative file (`name.yaml`) describing colors,
layout slot ordering, and per-widget options. No Python execution
in theme files — themes are safe to download and install from
strangers.

Discovery, in resolution order (first hit wins for a given name):
1. Project themes  — `<project_root>/.elophanto/themes/<name>.yaml`
2. User themes     — `~/.elophanto/themes/<name>.yaml`
3. Built-in themes — `cli/dashboard/themes/<name>.yaml`

The built-in `default` theme is the source of truth for the current
look. Custom themes can `extends: default` and override only the
fields they want to change.

Validation:
- All required color keys present (no silent fallbacks — bad theme
  fails loudly at load).
- Colors are 6-digit hex.
- Layout slot names are in the registered panel set.
- `sidebar_width` is an int in a sensible range.
- `default_size` is one of small | medium | large | hidden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ── Registered panel + widget names ─────────────────────────────────
# Any name appearing in a theme's `layout.sidebar` or `layout.main`
# must be in one of these sets. Adding a new panel = add its name
# here + register the constructor in `cli/dashboard/app.py:_SIDEBAR_PANELS`.

SIDEBAR_PANEL_NAMES: frozenset[str] = frozenset(
    {
        "mascot",
        "agent",
        "mind",
        "goals",
        "companies",
        "swarm",
        "scheduler",
        "approvals",
        "gateway",
        "footer",
    }
)

MAIN_WIDGET_NAMES: frozenset[str] = frozenset({"chat", "reasoning", "events", "input"})

_REQUIRED_COLOR_KEYS: frozenset[str] = frozenset(
    {
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
    }
)

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_VALID_SIZES = frozenset({"small", "medium", "large", "hidden"})

_BUILTIN_DIR = Path(__file__).parent / "themes"


class ThemeError(ValueError):
    """A theme file failed to load, parse, or validate."""


@dataclass(frozen=True)
class ThemeColors:
    """Color tokens — every key is a 6-digit hex string."""

    background: str
    surface: str
    raised: str
    border: str
    foreground: str
    bright: str
    muted: str
    placeholder: str
    accent: str
    accent_alt: str
    success: str
    warning: str
    error: str
    info: str


@dataclass(frozen=True)
class PanelOptions:
    """Per-widget knobs. Future widgets can add their own fields."""

    default_size: str = "medium"  # for `reasoning`: small | medium | large | hidden
    hidden: bool = False


@dataclass(frozen=True)
class ThemeLayout:
    """Layout descriptor — slot ordering + per-panel options."""

    sidebar_width: int
    sidebar: tuple[str, ...]
    main: tuple[str, ...]
    panels: dict[str, PanelOptions] = field(default_factory=dict)


@dataclass(frozen=True)
class Theme:
    """A loaded, validated theme."""

    name: str
    description: str
    extends: str | None
    colors: ThemeColors
    layout: ThemeLayout
    source_path: Path  # Where the leaf theme file came from (post-extend resolution)
    # True for dark themes — drives Textual's App.dark so unmarked text
    # defaults to a LIGHT foreground (instead of near-black, which would
    # be invisible on a dark background). Light themes set this False.
    dark: bool = False
    typography: dict[str, Any] = field(default_factory=dict)


# ── Loading ─────────────────────────────────────────────────────────


def _user_themes_dir() -> Path:
    return Path.home() / ".elophanto" / "themes"


def _project_themes_dir(project_root: Path | None) -> Path | None:
    if project_root is None:
        return None
    return project_root / ".elophanto" / "themes"


def _search_paths(project_root: Path | None) -> list[Path]:
    """Resolution order — project, then user, then built-in."""
    out: list[Path] = []
    proj = _project_themes_dir(project_root)
    if proj is not None:
        out.append(proj)
    out.append(_user_themes_dir())
    out.append(_BUILTIN_DIR)
    return out


def _find_theme_file(name: str, project_root: Path | None) -> Path:
    """First matching <name>.yaml across the search paths."""
    for d in _search_paths(project_root):
        candidate = d / f"{name}.yaml"
        if candidate.is_file():
            return candidate
    searched = ", ".join(str(d) for d in _search_paths(project_root))
    raise ThemeError(
        f"theme {name!r} not found (searched: {searched}). "
        "Run `elophanto themes list` to see what's available."
    )


def _parse_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ThemeError(f"cannot read theme file {path}: {e}") from e
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ThemeError(f"theme {path} is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise ThemeError(
            f"theme {path} must be a YAML mapping at the top level "
            f"(got {type(data).__name__})"
        )
    return data


def _deep_merge(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    """Overlay child onto parent — dicts merge, scalars/lists replace.

    Lists REPLACE rather than concat: a child theme that wants a
    different sidebar order must spell out the whole sidebar. Keeps
    behavior predictable (no surprise prepend/append semantics).
    """
    out: dict[str, Any] = dict(parent)
    for k, v in child.items():
        # YAML `colors:` with all-commented entries parses to None.
        # Treat None as "inherit from parent" rather than overwrite —
        # the operator's intent was to leave the section unchanged.
        if v is None:
            continue
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _resolve_with_extends(
    name: str, project_root: Path | None, _seen: set[str] | None = None
) -> tuple[dict[str, Any], Path]:
    """Load a theme YAML and merge with its `extends` parent chain.

    Cycles raise ThemeError. Returns (merged_dict, leaf_source_path).
    """
    _seen = _seen or set()
    if name in _seen:
        chain = " → ".join([*_seen, name])
        raise ThemeError(f"theme extends cycle: {chain}")
    _seen = _seen | {name}

    path = _find_theme_file(name, project_root)
    raw = _parse_yaml(path)

    parent_name = raw.get("extends")
    if parent_name:
        parent_raw, _ = _resolve_with_extends(str(parent_name), project_root, _seen)
        merged = _deep_merge(parent_raw, raw)
        # Override the metadata back to the leaf — extends is a
        # composition tool, not a renaming tool.
        merged["name"] = raw.get("name", name)
        merged["extends"] = parent_name
        if "description" in raw:
            merged["description"] = raw["description"]
        return merged, path

    return raw, path


# ── Validation ──────────────────────────────────────────────────────


def _validate_hex(label: str, value: Any) -> str:
    if not isinstance(value, str) or not _HEX_RE.match(value):
        raise ThemeError(
            f"color {label!r} must be a 6-digit hex string (e.g. '#1c1a16'), "
            f"got {value!r}"
        )
    return value


def _validate_colors(raw: dict[str, Any]) -> ThemeColors:
    missing = sorted(_REQUIRED_COLOR_KEYS - set(raw))
    if missing:
        raise ThemeError(f"theme is missing required color keys: {', '.join(missing)}")
    unknown = sorted(set(raw) - _REQUIRED_COLOR_KEYS)
    if unknown:
        # Unknown keys are a warning, not an error — themes may add
        # forward-compatible keys for future widgets. Raise only if
        # required ones are absent.
        pass
    validated = {k: _validate_hex(k, raw[k]) for k in _REQUIRED_COLOR_KEYS}
    return ThemeColors(**validated)


def _validate_layout(raw: dict[str, Any]) -> ThemeLayout:
    sidebar_width = raw.get("sidebar_width", 30)
    if not isinstance(sidebar_width, int) or not 10 <= sidebar_width <= 80:
        raise ThemeError(
            f"layout.sidebar_width must be an int in [10, 80], got {sidebar_width!r}"
        )

    sidebar = raw.get("sidebar", [])
    main = raw.get("main", [])
    if not isinstance(sidebar, list) or not all(isinstance(x, str) for x in sidebar):
        raise ThemeError("layout.sidebar must be a list of strings")
    if not isinstance(main, list) or not all(isinstance(x, str) for x in main):
        raise ThemeError("layout.main must be a list of strings")

    bad_sidebar = [s for s in sidebar if s not in SIDEBAR_PANEL_NAMES]
    if bad_sidebar:
        valid = ", ".join(sorted(SIDEBAR_PANEL_NAMES))
        raise ThemeError(
            f"unknown sidebar panel(s): {bad_sidebar}. " f"Valid panels: {valid}"
        )
    bad_main = [s for s in main if s not in MAIN_WIDGET_NAMES]
    if bad_main:
        valid = ", ".join(sorted(MAIN_WIDGET_NAMES))
        raise ThemeError(
            f"unknown main widget(s): {bad_main}. " f"Valid widgets: {valid}"
        )

    # Duplicates in sidebar = layout error (a panel shown twice doesn't
    # make sense and Textual will reject duplicate IDs).
    if len(set(sidebar)) != len(sidebar):
        dupes = sorted({s for s in sidebar if sidebar.count(s) > 1})
        raise ThemeError(f"layout.sidebar has duplicates: {dupes}")
    if len(set(main)) != len(main):
        dupes = sorted({s for s in main if main.count(s) > 1})
        raise ThemeError(f"layout.main has duplicates: {dupes}")

    panel_opts_raw = raw.get("panels", {}) or {}
    if not isinstance(panel_opts_raw, dict):
        raise ThemeError("layout.panels must be a mapping")
    panels: dict[str, PanelOptions] = {}
    for pname, opts in panel_opts_raw.items():
        if pname not in SIDEBAR_PANEL_NAMES and pname not in MAIN_WIDGET_NAMES:
            raise ThemeError(
                f"layout.panels.{pname}: unknown widget name "
                f"(must be a sidebar panel or main widget)"
            )
        if not isinstance(opts, dict):
            raise ThemeError(f"layout.panels.{pname} must be a mapping")
        size = opts.get("default_size", "medium")
        if size not in _VALID_SIZES:
            raise ThemeError(
                f"layout.panels.{pname}.default_size: must be one of "
                f"{sorted(_VALID_SIZES)}, got {size!r}"
            )
        hidden = bool(opts.get("hidden", False))
        panels[pname] = PanelOptions(default_size=size, hidden=hidden)

    return ThemeLayout(
        sidebar_width=sidebar_width,
        sidebar=tuple(sidebar),
        main=tuple(main),
        panels=panels,
    )


def _build_theme(raw: dict[str, Any], source_path: Path, fallback_name: str) -> Theme:
    name = raw.get("name", fallback_name)
    if not isinstance(name, str) or not name:
        raise ThemeError("theme `name` must be a non-empty string")

    description = raw.get("description", "") or ""
    if not isinstance(description, str):
        raise ThemeError("theme `description` must be a string")

    extends = raw.get("extends")
    if extends is not None and not isinstance(extends, str):
        raise ThemeError("theme `extends` must be a string or null")

    colors_raw = raw.get("colors")
    if not isinstance(colors_raw, dict):
        raise ThemeError("theme is missing `colors:` mapping")
    colors = _validate_colors(colors_raw)

    layout_raw = raw.get("layout")
    if not isinstance(layout_raw, dict):
        raise ThemeError("theme is missing `layout:` mapping")
    layout = _validate_layout(layout_raw)

    typography = raw.get("typography", {}) or {}
    if not isinstance(typography, dict):
        raise ThemeError("theme `typography` must be a mapping")

    dark = raw.get("dark", False)
    if not isinstance(dark, bool):
        raise ThemeError("theme `dark` must be true or false")

    return Theme(
        name=name,
        description=description,
        extends=extends,
        colors=colors,
        layout=layout,
        source_path=source_path,
        dark=dark,
        typography=typography,
    )


# ── Public API ──────────────────────────────────────────────────────


def load_theme(name: str, project_root: Path | None = None) -> Theme:
    """Load a theme by name, resolving `extends` chains.

    Raises ThemeError with a precise reason on any failure (missing
    file, bad YAML, invalid color, unknown layout slot, ...).
    """
    merged, source = _resolve_with_extends(name, project_root)
    return _build_theme(merged, source, fallback_name=name)


def list_themes(project_root: Path | None = None) -> dict[str, Path]:
    """Discover all available themes across the search paths.

    Returns name → leaf path. Names found in earlier search paths
    shadow later ones (project > user > built-in).
    """
    discovered: dict[str, Path] = {}
    # Iterate in REVERSE order so the highest-priority source overwrites.
    for d in reversed(_search_paths(project_root)):
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.yaml")):
            discovered[p.stem] = p
    return discovered


def validate_theme_file(path: Path) -> Theme:
    """Parse + validate a theme file directly (without name lookup).

    Useful for `elophanto themes validate <path>` before installing.
    """
    raw = _parse_yaml(path)
    # If the file declares `extends:`, that name must resolve via the
    # normal search paths — validating a free-floating extends'd file
    # in isolation isn't possible.
    if raw.get("extends"):
        merged, _ = _resolve_with_extends(path.stem, project_root=None)
        raw = merged
    return _build_theme(raw, path, fallback_name=path.stem)


# ── CSS rendering ───────────────────────────────────────────────────


def render_css(theme: Theme) -> str:
    """Render the dashboard CSS with theme colors substituted in.

    Returns a complete Textual CSS document. The shape of the CSS
    matches what was previously hardcoded in EloPhantoDashboard.CSS
    so the visual diff against the old hardcoded version is zero.
    """
    c = theme.colors
    sidebar_w = theme.layout.sidebar_width

    # Reasoning panel default size → height.
    reasoning_opts = theme.layout.panels.get("reasoning", PanelOptions())
    reasoning_default = reasoning_opts.default_size
    reasoning_default_height = {
        "small": 5,
        "medium": 10,
        "large": 20,
        "hidden": 0,
    }[reasoning_default]

    # Shared scrollbar styling — slim (1 cell) and palette-matched.
    # Textual's default scrollbar is a chunky blue that clashes with
    # every custom theme; this makes it a quiet 1-cell track in the
    # theme's own border/muted/accent colors. Applied to each scroll
    # container individually (scrollbar properties don't inherit).
    scrollbar = f"""\
    scrollbar-size-vertical: 1;
    scrollbar-size-horizontal: 1;
    scrollbar-background: {c.surface};
    scrollbar-background-hover: {c.surface};
    scrollbar-background-active: {c.surface};
    scrollbar-color: {c.border};
    scrollbar-color-hover: {c.muted};
    scrollbar-color-active: {c.accent};
    scrollbar-corner-color: {c.surface};"""

    return f"""\
Screen {{
    layout: vertical;
    background: {c.background};
    /* Belt-and-suspenders for terminals that override Textual's
     * default-foreground heuristic — text without explicit colour
     * markup must still render on the background, never invisible. */
    color: {c.foreground};
}}
#body {{
    layout: horizontal;
    height: 1fr;
}}
#sidebar {{
    width: {sidebar_w};
    min-width: {sidebar_w};
    border-right: solid {c.border};
    background: {c.surface};
    color: {c.foreground};
    overflow-y: auto;
{scrollbar}
}}
#main-area {{
    layout: vertical;
    width: 1fr;
}}
#chat {{
    height: 1fr;
    width: 1fr;
    padding: 0 1;
    background: {c.background};
    color: {c.foreground};
    overflow-x: hidden;
    scrollbar-gutter: stable;
{scrollbar}
}}
#feed-header {{
    height: 1;
    width: 1fr;
    padding: 0 1;
    background: {c.background};
    border-top: solid {c.border};
    color: {c.muted};
}}
#reasoning-header {{
    height: 1;
    width: 1fr;
    padding: 0 1;
    background: {c.background};
    border-top: solid {c.border};
    color: {c.muted};
}}
/* Default height: {reasoning_default}. Cycled by Ctrl+R via
   _reasoning_height_idx. The .reasoning-* classes are toggled on
   BOTH #reasoning and #reasoning-header. */
#reasoning {{
    height: {reasoning_default_height};
    width: 1fr;
    background: {c.background};
    color: {c.foreground};
    padding: 0 1;
    overflow-x: hidden;
    scrollbar-gutter: stable;
{scrollbar}
}}
#reasoning.reasoning-hidden,
#reasoning-header.reasoning-hidden {{
    display: none;
}}
#reasoning.reasoning-small {{ height: 5; }}
#reasoning.reasoning-medium {{ height: 10; }}
#reasoning.reasoning-large {{ height: 20; }}
#events {{
    height: 5;
    width: 1fr;
    background: {c.background};
    color: {c.foreground};
    padding: 0 1;
    overflow-x: hidden;
    scrollbar-gutter: stable;
{scrollbar}
}}
#input-bar {{
    height: 3;
    background: {c.raised};
    border-top: solid {c.border};
    padding: 0 1;
}}
#input-bar Input {{
    background: {c.raised};
    border: none;
    color: {c.foreground};
    padding: 0 0;
}}
#input-bar Input:focus {{
    border: none;
}}
#input-bar Input > .input--cursor {{
    background: {c.accent};
    color: {c.background};
}}
#input-bar Input > .input--placeholder {{
    color: {c.placeholder};
}}
_SidePanel {{
    height: auto;
    padding: 0 1 1 1;
    color: {c.muted};
}}
#panel-mascot {{
    /* The mascot is the sidebar's identity — center it horizontally
     * within the panel so the face sits in the middle of the
     * sidebar, with the label + agent name lines balanced below.
     * Padding gives breathing room above/below the box. */
    content-align-horizontal: center;
    text-align: center;
    padding: 1 0 1 0;
}}
_Header {{
    height: 1;
    padding: 0 1;
    background: {c.raised};
    color: {c.muted};
}}
"""
