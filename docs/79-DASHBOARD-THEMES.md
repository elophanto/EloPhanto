# Dashboard themes

The EloPhanto **terminal** dashboard's look is fully theme-driven.
Operators can fork a built-in theme, override only the colors / layout
they want to change, and ship YAML files that other operators can drop
in too. No Python execution in theme files — themes are safe to share.

> **Terminal only.** This YAML system themes the Textual terminal
> dashboard. The **web** dashboard (`./start.sh --web`) has its own,
> separate theme system — CSS-variable presets selected in the sidebar
> or Settings → Appearance (including Blade / Light / Dark / Nocturne /
> Mocha), persisted in the browser. The two don't share files; they
> ship matching palettes so the surfaces feel like one product.

## Built-in themes

Four ship with the agent (`elophanto themes list`):

| Name | Look |
|------|------|
| `blade` | Rain-city near-black with amber lead + teal HUD — product default (dark, `chrome: hud`) |
| `default` | Warm paper-cream, near-monochrome, brand-violet ◆ accent (light) |
| `nocturne` | Cinematic near-black glass with a luminous teal accent (dark) |
| `mocha` | Soothing dark pastel — Mauve accent, low-glare background (dark) |

A theme can be **light** or **dark** via the `dark:` flag (see schema).
Dark themes flip Textual's default text color to light so unmarked
text stays readable on the dark background, and re-tint the whole
panel palette (text, glyphs, status dots) — not just CSS backgrounds.

## Quick start

```bash
elophanto themes list                       # see what's available
elophanto themes show mocha                 # inspect a theme (colors + layout)
elophanto themes init my-theme              # scaffold ~/.elophanto/themes/my-theme.yaml
# edit ~/.elophanto/themes/my-theme.yaml
elophanto themes validate ~/.elophanto/themes/my-theme.yaml
elophanto chat --theme my-theme             # one-off
```

To make a theme stick across restarts, set it in `config.yaml`:

```yaml
dashboard:
  theme: my-theme
```

`--theme` on the CLI overrides the config value; the config value
overrides the built-in `blade` product default.

## Where theme files live

Resolution order (first hit wins):

1. **Project** — `<repo>/.elophanto/themes/<name>.yaml` (per-repo overrides)
2. **User** — `~/.elophanto/themes/<name>.yaml` (your personal themes)
3. **Built-in** — `cli/dashboard/themes/<name>.yaml` (ships with the agent)

So a project-level `nocturne.yaml` masks a user-level `nocturne.yaml`,
which masks a built-in `nocturne.yaml`.

## Schema

A theme is a YAML mapping with these top-level keys:

```yaml
name: blade                            # required
description: "Short human description"  # optional
extends: null                          # optional — name of parent theme
dark: true                             # optional — true for dark themes (default false)
chrome: hud                            # optional — "" | classic | hud (see Chrome)

colors:                                # required (or inherit from extends)
  background:  "#050608"
  surface:     "#0a0c11"
  raised:      "#10141c"
  border:      "#1e2533"
  foreground:  "#cfd5e0"
  bright:      "#f3efe6"
  muted:       "#6b7385"
  placeholder: "#3d4454"
  accent:      "#f0a020"
  accent_alt:  "#3aa8a0"
  success:     "#3aa8a0"
  warning:     "#f0b429"
  error:       "#e07070"
  info:        "#3aa8a0"

layout:                                # required (or inherit from extends)
  sidebar_width: 28                    # int 10..80 (built-ins use 28)
  sidebar:                             # ordered list of panel names
    - mascot
    - agent
    - mind
    - goals
    - approvals
    - companies
    - scheduler
    - gateway
    - footer
  main:                                # ordered list of main-area widgets
    - chat
    - reasoning
    - events
    - input
  panels:                              # per-widget options (optional)
    reasoning:
      default_size: small              # small | medium | large | hidden
    mascot:
      hidden: false                    # omit the panel regardless of `sidebar` order
    swarm:
      hidden: true                     # blade hides empty swarm by default

typography:                            # reserved for future use
  chat_padding: [0, 1]
```

### Colors

Every color is a **6-digit hex string** (`#rrggbb`). Three-digit
shorthand and named CSS colors are rejected — they render
inconsistently across terminals. Pick hex, ship hex.

| Token         | Where it's used                                    |
|---------------|----------------------------------------------------|
| `background`  | Screen + chat + reasoning + events backgrounds     |
| `surface`     | Sidebar background                                  |
| `raised`      | Header bar + input bar (slightly more elevated)    |
| `border`      | Dividers between regions                            |
| `foreground`  | Default body text                                   |
| `bright`      | Emphasized text (often same as `foreground`)        |
| `muted`       | Labels, dim copy                                    |
| `placeholder` | Input placeholder text                              |
| `accent`      | Brand color — focused cursor, primary glyphs       |
| `accent_alt`  | Darker variant of accent for light backgrounds     |
| `success`     | Green "OK" dots                                     |
| `warning`     | Amber "caution" dots                                |
| `error`       | Red "failure" dots                                  |
| `info`        | Blue "working / in-progress" dots                   |

The accent also tints the scrollbar when active; the scrollbar track
uses `border` (rest) → `muted` (hover) → `accent` (dragging) on a
`surface` background, so it always matches the palette instead of
falling back to Textual's default blue.

### `dark`

`dark: true` marks a dark theme. It does two things:

1. Sets Textual's `App.dark`, so text rendered *without* explicit
   color markup defaults to a **light** foreground (otherwise it would
   be near-black and invisible on a dark background).
2. The dashboard re-tints its entire Rich-markup palette (body text,
   labels, status dots) and panel glyphs from the theme — so a dark
   theme isn't just dark backgrounds with black text, it's coherent
   top to bottom.

Light themes omit `dark` (or set it `false`). The built-in `default`
is light; `blade`, `nocturne`, and `mocha` are dark. Unset
`dashboard.theme` resolves to `blade`.

### Chrome

Optional top-level `chrome:` selects the **ops dialect**, not just
colors:

| Value | Effect |
|-------|--------|
| *(omit)* / `classic` | Classic IDE-adjacent chrome — soft labels, rounded mascot, provider dots in the header |
| `hud` | Blade Runner mission console — mission rail header, angular sensor mascot, HUD panel grammar, amber command aperture |

`blade` ships with `chrome: hud`. Under HUD:

- **Mission rail** — `◆ callsign │ RUNNING/REST/PAUSE/TOOL │ burn meter │ primary mission │ AUTH n / BLK n (when needed) │ LINK`
- **Panel titles** — MISSION / COS / AUTH / CLOCK / LINK (approvals panel hidden when empty)
- **Readouts** — pipe meters `|████░░░░|`, field keys (`TRUST`/`VOICE`/`STRAT`/`NET7`), bracketed idle `[standby]`
- **Mascot** — separate `_FACES_HUD` set (square sensors, scan bars, ops labels `CYCLE`/`TOOL`/`DOUBT`)
- **CSS** — amber left rail on the sidebar, amber header/input borders, denser panel padding

Fork `blade` and set `chrome: classic` (or omit it) if you want the
rain-city palette without the mission-console dialect.

### Layout

`layout.sidebar` and `layout.main` are ordered lists of *slot names*.
Reorder to rearrange; remove an entry to hide that panel; duplicates
are rejected.

Valid sidebar slots: `mascot, agent, mind, goals, companies, swarm,
scheduler, approvals, gateway, footer`.

Valid main slots: `chat, reasoning, events, input`. (The `input` widget
always renders in the bottom input bar regardless of where it appears
in `layout.main` — kept in the schema for future use.)

`layout.panels.<name>.hidden: true` is equivalent to removing the name
from the slot list. The `mascot` panel can also be killed via
`dashboard.mascot_enabled: false` in `config.yaml` — that flag wins
over the theme.

### Inheritance

Set `extends: <parent-name>` to inherit from another theme. The child
only needs to declare keys it wants to override. Lists (`sidebar`,
`main`) REPLACE the parent's list rather than concatenating — a child
that wants a different sidebar order must spell it out fully. Cycles
are detected at load and produce a clear error.

A child theme that writes an empty section (`colors:` with all
entries commented out — parses as YAML null) inherits that section
from its parent. This makes the starter template from
`elophanto themes init` work without surprises.

## Validation

All validation runs at load time. Errors are loud and specific:

```
$ elophanto themes validate ~/.elophanto/themes/broken.yaml
Invalid theme: color 'accent' must be a 6-digit hex string (e.g. '#1c1a16'), got 'red'
```

Possible errors:

- **Missing required color key** — a `colors:` block must contain all
  14 keys (or inherit them via `extends:`).
- **Bad hex** — not matching `^#[0-9a-fA-F]{6}$`.
- **Unknown sidebar / main slot** — must be in the registered set.
- **Duplicate slots** — same name listed twice in `sidebar` or `main`.
- **`sidebar_width` out of range** — must be `10..80`.
- **`default_size` not one of** `small | medium | large | hidden`.
- **`extends:` cycle** — A → B → A.
- **`chrome` not one of** `hud | classic | ""`.

If `dashboard.theme` in `config.yaml` points at a broken theme, the
dashboard falls back to `blade` and logs the error rather than
crashing the chat session.

## Adding a new panel

(Developer-side, not theme-side.) To make a new sidebar panel available
to themes:

1. Define the panel widget (subclass `_SidePanel`) in `cli/dashboard/app.py`.
2. Add its stable name to `cli/dashboard/theme.SIDEBAR_PANEL_NAMES`.
3. Register the constructor at the bottom of `app.py`:
   `_register_panel("my-panel", _MyPanel)`.
4. Reference it from at least the default theme's `layout.sidebar`.

The validator will then accept the name in user-authored themes.

## Why YAML and not Python?

Themes are something operators share with other operators. A Python
"theme" would mean downloading and executing arbitrary code — too
much trust for cosmetic changes. YAML keeps themes inert: the worst
a malicious theme can do is render unreadable text or hide a panel.

If you need behavior changes (new widgets, new interactions), that's
a plugin — separate concern, not a theme.
