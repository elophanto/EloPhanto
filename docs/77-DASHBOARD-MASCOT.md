# 77 — Dashboard mascot

**Status**: Shipped. · **Started**: 2026-05-21

## What it is

A small ASCII character at the top of the dashboard sidebar whose
face mirrors agent state at a glance. Sleep / idle / thinking /
working / happy / concerned / humbled — one face per state, with
state-coloured eyes, per-state mouth shapes, and small animations
to convey what the agent is doing right now without needing to read
log lines.

```
╭───────────╮
│           │
│  ◔     ◔  │      <-- thinking; pupils rotate
│     ·     │
│           │
╰───────────╯
  thinking
  AlphaScala
```

Lives entirely in the existing Textual dashboard, drawn into a
``_MascotPanel`` widget at the top of the sidebar. No new windows,
no GUI dependencies, no extra process. The face IS the dashboard's
identity surface.

## Why a TUI-native mascot

EloPhanto's positioning is "the agent that lives in your terminal."
A separate desktop overlay window would contradict that. The mascot
needs to feel like part of the dashboard the operator is already
running, not a parallel surface they have to manage.

Practical consequences of TUI-native:

- Character grid only. Width is fixed, motion can only happen at
  cell granularity. Continuous "breathing" motion was prototyped
  (vertical shift every ~3.5s) but read as a *hop*, not breath —
  removed. State-internal animation (pupil rotation, mouth flex,
  blink) carries the "alive" signal instead.
- Color is the only depth tool. Eye glyphs are coloured per state,
  same hue as the label below, so the at-a-glance signal stays
  legible on both dark and light terminals.
- All glyphs must be terminal-safe Unicode that renders correctly
  in iTerm2 / Terminal.app / Ghostty / Alacritty / kitty / Windows
  Terminal. ASCII box-drawing + circle glyphs (◉ ◔ ◓ ◑ ◒) all qualify.

## State priority

The mapper in ``cli/dashboard/mascot.py:decide_face`` reads a
``MascotInputs`` snapshot and returns one of seven faces. Priority
order (top wins):

```
1. concerned   recent error / preempt / stuck checkpoint / negative mood
2. happy       recent success + positive mood
3. working     current_tool set + started within 30s (live tool call)
4. thinking    mind cycle running OR recent activity (chat replies, etc.)
5. humbled     ego coherence < 0.3 (no other signal)
6. idle        mind explicitly sleeping/running and healthy
7. sleep       fallback — mind paused/disabled with no recent activity
```

Inputs come from `_State`:

- `mind_state` — `"running"` / `"sleeping"` / `"paused"` / `"disabled"` / `"unknown"`
- `current_tool` + `current_tool_start` — live tool call detection
- `ego_mood` + `ego_coherence` — affect / self-grading signals
- `events` deque — scanned for `[red]` / `✖` / `error` (concerned) and
  `✓` / `✔` / `completed` (happy)
- `last_activity_ts` — set in `_dispatch` for every gateway message
  (response, event, approval, error). Without this signal the
  mascot reads "sleeping" during chat-only sessions because chat
  replies arrive as `RESPONSE` not `EVENT` and the mind never
  transitions out of `unknown`.

The activity-fresh window is 90 seconds. After that, the mascot
falls through to sleep if nothing else is going on. Stale tool
calls (>30s with no progress) decay out of `working` and fall
through to `thinking` so a hung tool doesn't freeze the face.

## Animation

Each face is a list of frames in ``_FACES``. The panel runs a
``set_interval`` at ``FRAME_TICK_MS`` (250ms) and advances a frame
counter; ``render_face(face, frame=N)`` returns the ``N % len(frames)``
slot.

Per-state cadence:

| State       | Frames | Motion                                       |
|-------------|--------|----------------------------------------------|
| sleep       | 6      | closed-arc eyes, small mouth (currently static across frames) |
| idle        | 8      | alert eyes, one blink per cycle (~2s)        |
| thinking    | 8      | pupil rotation through 8 phases (smooth roll)|
| working     | 4      | focused eyes, mouth opens/closes             |
| happy       | 4      | squint-bounce on the eyes                    |
| concerned   | 4      | wide eyes + frown                            |
| humbled     | 1      | static — the stillness IS the affect         |

Width is pinned to 13 visible characters per line across every frame
of every state (tests enforce this via
``test_frames_within_state_have_consistent_visible_width``) so the
sidebar never reflows on a state change.

### Anticipation between state transitions

When ``decide_face`` returns a different face than the panel last
rendered, the panel injects a single ``show_closed=True`` frame
before the new state's animation starts. The closed-eye frame
(``_CLOSED_FRAME``) is the same dimensions as a normal frame so
panel height stays constant across the transition. Reads as the
mascot briefly closing its eyes to acknowledge "I'm changing state."

This is Disney's anticipation principle in TUI form. The transition
window is 2 frames (~500ms at 250ms tick).

## Config flag

```yaml
# config.yaml
dashboard:
  mascot_enabled: true   # default; flip to false to hide the panel
```

Read once at dashboard launch by ``_read_dashboard_flag`` (no full
Config loader — startup stays fast). When disabled the panel is
simply not added to the sidebar; everything else works identically.

## Files

- `cli/dashboard/mascot.py` — face data, state mapping, render
- `cli/dashboard/app.py` — `_MascotPanel` widget + sidebar wiring +
  `last_activity_ts` bump in `_dispatch`
- `tests/test_cli/test_dashboard_mascot.py` — 32 tests covering
  state priority, animation invariants, panel-side event scanning,
  config flag

## Tests

```
TestPriorityOrdering        14 tests — every branch wins when its
                                       signal dominates
TestRendering               12 tests — frame consistency, color
                                       contract, anticipation,
                                       name line, label content
TestPanelWiring              2 tests — event-deque scanning detects
                                       error / success markers
```

Width invariant test ensures the sidebar can't reflow on a state
change. Animation invariant test ensures every state has at least
one frame and animated states have multiple.

## Decisions deliberately NOT made

- **No breathing motion.** Vertical-shift breath cycle was prototyped
  and removed (operator feedback 2026-05-21: reads as a discrete hop
  in character cells, not continuous breath). State-internal
  animation carries the aliveness signal instead. The ``breathing``
  parameter is retained as a no-op for API stability.
- **No boot wave.** Considered a one-time wave-frame on dashboard
  launch (mascot greets you). Skipped because the dashboard already
  paints a digest greeting; double-greeting felt redundant.
- **No sounds.** The TUI can't emit a chime without bell-character
  abuse. Out of scope.

## Future considerations

- Sleep state could benefit from a drifting Z animation across the
  empty top row of the box (currently all 6 frames are identical).
  Trade-off: motion in sleep state attracts attention an operator
  may not want at rest. Deferred.
- Per-mission mascot variants. Could imagine the face leaning into
  the active mission's lens (e.g. more focused eyes during a
  ``capability-development`` cycle). Probably too clever for the
  current scope.
