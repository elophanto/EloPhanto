"""Dashboard mascot — ASCII/Unicode character whose face mirrors agent state.

EloPhanto is TUI-first, so the mascot lives in the dashboard sidebar
(not a separate OS window — that's openhuman's path, see notes in the
2026-05-21 design discussion). The face is a small ASCII/Unicode block
rendered into a Textual `Static` widget.

State priority (highest wins, top to bottom):

  1. ``concerned``   recent error / preempt / stuck checkpoint / shame
  2. ``happy``       recent success + positive affect
  3. ``working``     current_tool is set + started in the last N seconds
  4. ``thinking``    mind cycle running, no tool yet
  5. ``humbled``     ego coherence low
  6. ``idle``        mind sleeping but available
  7. ``sleep``       mind paused / disabled, nothing in flight

The face is read-only from the operator's perspective — it's status,
not interaction. Hover/click doesn't change the agent.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass
from typing import Literal

MascotFace = Literal[
    "sleep",
    "idle",
    "thinking",
    "working",
    "happy",
    "concerned",
    "humbled",
]


# ---------------------------------------------------------------------------
# Faces — single source of truth for the visual identity
# ---------------------------------------------------------------------------
#
# Design notes (2026-05-21 second redesign — "Jony Ive pass" from
# transcript). Reverses the no-border first attempt. Operator was
# correct that bare face fragments read as floating debris rather
# than a character.
#
# Principles applied:
#
#   1. **Restored container.** Soft rounded ╭─╮ border. The box IS the
#      head. Without a container the elements have no relationship to
#      each other.
#
#   2. **Proportion + negative space.** Box is 13 cols × 6 rows
#      (top border, blank, eyes, mouth, blank, bottom border). Two
#      blank rows give the face room to breathe inside its container
#      — Apple's "padding is design" principle.
#
#   3. **Centered.** The panel uses ``text-align: center`` so the
#      box sits in the middle of the sidebar, with the label and
#      name lines centered beneath. No more left-aligned fragments.
#
#   4. **Refined glyphs.** Closed eyes use ``‿`` (closed-arc) instead
#      of ``_`` (underscore), which reads as "asleep" rather than
#      "ASCII art accident". Eyes use ``◉`` consistently for "open
#      and aware" states.
#
#   5. **Animation.** Pupil rotation, mouth flex, eye blinks, Z drift
#      across the empty top row in sleep. Breath cycle handled by
#      ``render_face``; transition anticipation by the panel.
#
# Each frame is 6 lines tall, 13 visible chars wide (including border).
# The ``{e}`` placeholder is replaced with the state's eye color at
# render time.

# Visible width of each frame line, including the box border chars.
_FACE_WIDTH = 13
# Number of lines per frame (top border, blank, eyes, mouth, blank,
# bottom border).
_FACE_HEIGHT = 6

# Closed-eye anticipation frame, rendered by the panel during state
# transitions. Same dimensions as a normal frame so panel height
# stays constant across the blink.
_CLOSED_FRAME = (
    "╭───────────╮\n"
    "│           │\n"
    "│  -     -  │\n"
    "│     ·     │\n"
    "│           │\n"
    "╰───────────╯"
)


_BLANK_ROW = "           "  # 11 spaces — empty inner row


def _f(
    eyes: str, mouth: str, *, top: str = _BLANK_ROW, bottom: str = _BLANK_ROW
) -> str:
    """Compose a 6-line face frame from inner-row templates.

    Inputs are the INNER 11-char content of each row (between the
    side borders). Function wraps each with ``│ … │`` borders and
    adds the top/bottom box borders.

    Top + bottom rows default to blank but accept content so floating
    elements (Z drift in sleep, thought dots in thinking) can live
    in the space above/below the face proper.

    The ``{e}`` placeholder is preserved in the eye row so
    ``render_face`` can interpolate the state color at draw time.
    """
    for label, content in (
        ("top", top),
        ("eyes", eyes),
        ("mouth", mouth),
        ("bottom", bottom),
    ):
        assert _visible_len(content) == 11, (
            f"{label} inner content must be 11 visible chars, "
            f"got {_visible_len(content)}: {content!r}"
        )
    return (
        "╭───────────╮\n"
        f"│{top}│\n"
        f"│{eyes}│\n"
        f"│{mouth}│\n"
        f"│{bottom}│\n"
        "╰───────────╯"
    )


def _visible_len(s: str) -> int:
    """Count visible chars in a string, treating ``[{e}]…[/]`` (or any
    bracketed markup) as zero-width markup. Used during frame
    construction to validate alignment."""
    import re as _re

    return len(_re.sub(r"\[/?[^\]]*\]", "", s))


# Inner-row templates (11 visible chars each). Centered glyphs sit at
# specific columns: left eye at col 2, right eye at col 8, mouth at
# col 5 (zero-indexed within the inner row).
#
#   012345678901
#   "  E     E  "   <- eyes at col 2 and col 8
#   "     M     "   <- mouth at col 5

_FACES: dict[MascotFace, list[str]] = {
    # sleep — closed eyes (gentle arc), small mouth dash, Z drifts
    # diagonally upward across the empty top row (right→left, then
    # repeats). Eyes always closed, mouth a small line.
    # 8 frames @ 250ms = 2s cycle.
    "sleep": [
        _f("  ‿     ‿  ", "     —     ", top="         z "),
        _f("  ‿     ‿  ", "     —     ", top="        z  "),
        _f("  ‿     ‿  ", "     —     ", top="       Z   "),
        _f("  ‿     ‿  ", "     —     ", top="      Z    "),
        _f("  ‿     ‿  ", "     —     ", top="     z     "),
        _f("  ‿     ‿  ", "     —     ", top="    z      "),
        _f("  ‿     ‿  ", "     —     ", top=_BLANK_ROW),
        _f("  ‿     ‿  ", "     —     ", top=_BLANK_ROW),
    ],
    # idle — alert eyes that occasionally look around, blink, and
    # twitch the mouth between neutral and a tiny smile. 12 frames
    # @ 250ms = 3s cycle, feels properly alive.
    "idle": [
        # forward gaze, soft smile
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     ‿     "),
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     ‿     "),
        # quick blink
        _f("  -     -  ", "     ‿     "),
        # back to forward gaze
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     ‿     "),
        # glance left (both pupils shift left within the eye)
        _f("  [{e}]◐[/]     [{e}]◐[/]  ", "     ‿     "),
        _f("  [{e}]◐[/]     [{e}]◐[/]  ", "     ‿     "),
        # back to forward
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     ‿     "),
        # mouth shifts to neutral briefly
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     -     "),
        # glance right
        _f("  [{e}]◑[/]     [{e}]◑[/]  ", "     -     "),
        _f("  [{e}]◑[/]     [{e}]◑[/]  ", "     ‿     "),
        # back to forward, soft smile
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     ‿     "),
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     ‿     "),
    ],
    # thinking — pupils rotate through 8 phases AND thought dots
    # accumulate in the bottom row (· → ·· → ··· → cycle). Reads as
    # a smooth roll plus ambient "ideas streaming". 12 frames @ 250ms
    # = 3s cycle.
    "thinking": [
        _f("  [{e}]◔[/]     [{e}]◔[/]  ", "     ·     ", bottom=_BLANK_ROW),
        _f("  [{e}]◓[/]     [{e}]◓[/]  ", "     ·     ", bottom="     ·     "),
        _f("  [{e}]◑[/]     [{e}]◑[/]  ", "     ·     ", bottom="    · ·    "),
        _f("  [{e}]◒[/]     [{e}]◒[/]  ", "     ·     ", bottom="   · · ·   "),
        _f("  [{e}]◔[/]     [{e}]◔[/]  ", "     ·     ", bottom="    · ·    "),
        _f("  [{e}]◓[/]     [{e}]◓[/]  ", "     ·     ", bottom="     ·     "),
        _f("  [{e}]◑[/]     [{e}]◑[/]  ", "     ·     ", bottom=_BLANK_ROW),
        _f("  [{e}]◒[/]     [{e}]◒[/]  ", "     ·     ", bottom=_BLANK_ROW),
        _f("  [{e}]◔[/]     [{e}]◔[/]  ", "     ·     ", bottom="     ·     "),
        _f("  [{e}]◓[/]     [{e}]◓[/]  ", "     ·     ", bottom="    · ·    "),
        _f("  [{e}]◑[/]     [{e}]◑[/]  ", "     ·     ", bottom="   · · ·   "),
        _f("  [{e}]◒[/]     [{e}]◒[/]  ", "     ·     ", bottom="    · ·    "),
    ],
    # working — focused stare, mouth opens/closes like the agent is
    # speaking through tools. Eyes occasionally look down ("at the
    # work") then back up. 8 frames @ 250ms = 2s cycle.
    "working": [
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     o     "),
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     O     "),
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     o     "),
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     ◍     "),
        # eyes look down briefly — focus shifts
        _f("  [{e}]◒[/]     [{e}]◒[/]  ", "     o     "),
        _f("  [{e}]◒[/]     [{e}]◒[/]  ", "     O     "),
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     o     "),
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     ·     "),
    ],
    # happy — squint, full smile, a tiny laugh (mouth opens briefly),
    # then occasional wink. 10 frames @ 250ms = 2.5s cycle.
    "happy": [
        _f("  [{e}]^[/]     [{e}]^[/]  ", "     ◡     "),
        _f("  [{e}]⌒[/]     [{e}]⌒[/]  ", "     ◡     "),
        # mouth opens — laugh moment
        _f("  [{e}]^[/]     [{e}]^[/]  ", "     ◯     "),
        _f("  [{e}]⌒[/]     [{e}]⌒[/]  ", "     ◡     "),
        _f("  [{e}]^[/]     [{e}]^[/]  ", "     ◡     "),
        _f("  [{e}]^[/]     [{e}]^[/]  ", "     ◡     "),
        # wink (left eye closes briefly)
        _f("  -     [{e}]^[/]  ", "     ◡     "),
        _f("  [{e}]^[/]     [{e}]^[/]  ", "     ◡     "),
        _f("  [{e}]⌒[/]     [{e}]⌒[/]  ", "     ◡     "),
        _f("  [{e}]^[/]     [{e}]^[/]  ", "     ◡     "),
    ],
    # concerned — wide alert eyes that DART nervously left/right,
    # mouth quivers between frown and a thin worried line. 8 frames
    # @ 250ms = 2s cycle.
    "concerned": [
        # forward, frown
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     ◠     "),
        # dart left
        _f("  [{e}]◐[/]     [{e}]◐[/]  ", "     ◠     "),
        # back to center, mouth thins
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     -     "),
        # dart right
        _f("  [{e}]◑[/]     [{e}]◑[/]  ", "     ◠     "),
        # forward, frown deepens
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     ◠     "),
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     ◠     "),
        # small blink (stress)
        _f("  -     -  ", "     ◠     "),
        _f("  [{e}]◉[/]     [{e}]◉[/]  ", "     ◠     "),
    ],
    # humbled — eyes downcast. Mostly still, but with a single
    # occasional micro-blink so it doesn't read as frozen / dead.
    # 12 frames, only one varies, blink visible roughly every 3s.
    "humbled": [
        _f("  [{e}]╮[/]     [{e}]╭[/]  ", "     ⌣     "),
        _f("  [{e}]╮[/]     [{e}]╭[/]  ", "     ⌣     "),
        _f("  [{e}]╮[/]     [{e}]╭[/]  ", "     ⌣     "),
        _f("  [{e}]╮[/]     [{e}]╭[/]  ", "     ⌣     "),
        _f("  [{e}]╮[/]     [{e}]╭[/]  ", "     ⌣     "),
        _f("  [{e}]╮[/]     [{e}]╭[/]  ", "     ⌣     "),
        _f("  [{e}]╮[/]     [{e}]╭[/]  ", "     ⌣     "),
        _f("  [{e}]╮[/]     [{e}]╭[/]  ", "     ⌣     "),
        _f("  [{e}]╮[/]     [{e}]╭[/]  ", "     ⌣     "),
        _f("  [{e}]╮[/]     [{e}]╭[/]  ", "     ⌣     "),
        _f("  [{e}]╮[/]     [{e}]╭[/]  ", "     ⌣     "),
        # slow blink — the only motion
        _f("  -     -  ", "     ⌣     "),
    ],
}


# Labels rendered below the face. Short, single-word state names so the
# sidebar stays narrow.
_LABELS: dict[MascotFace, str] = {
    "sleep": "sleeping",
    "idle": "idle",
    "thinking": "thinking",
    "working": "working",
    "happy": "happy",
    "concerned": "concerned",
    "humbled": "humbled",
}


# Theme colors. Label color + eye color are the same per state so the
# tinted eyes and tinted label read as one design. Sleep keeps colorless
# eyes (default foreground) since the eyes are closed dashes anyway.
_STATE_COLORS: dict[MascotFace, str] = {
    "sleep": "#9a948a",
    "idle": "#78746e",
    "thinking": "#7c3aed",
    "working": "#0ea5e9",
    "happy": "#16a34a",
    "concerned": "#ef4444",
    "humbled": "#a16207",
}


# Default animation tick — every N milliseconds the panel advances
# its frame counter and repaints. 250ms is the natural eye-blink-ish
# cadence; slower than that feels laggy, faster wastes redraws.
# Per-state cadence can be derived by giving slower states more
# identical frames in their list (see `idle` — mostly identical
# frames means the animation is mostly a no-op repaint).
FRAME_TICK_MS = 250


def frame_count(face: MascotFace) -> int:
    """Number of distinct frames for ``face``. Useful for tests +
    debug rendering."""
    return len(_FACES[face])


# Breath cycle was removed after the 2026-05-21 review. In a fixed-
# character terminal grid we can't do sub-cell motion, so a "breath"
# implemented as periodic vertical shift reads as a discrete hop
# rather than continuous breathing. The state animations
# (Z-drift in sleep, pupil rotation in thinking, mouth flex in
# working, blink in idle) already convey aliveness without the
# distracting position jump. Apple's ambient-motion principle works
# at sub-pixel scale on retina displays; it doesn't translate here.
# ``breathing`` parameter retained as a no-op for backwards-compat
# with existing callers.


def render_face(
    face: MascotFace,
    *,
    agent_name: str = "",
    frame: int = 0,
    breathing: bool = False,  # noqa: ARG001 — retained for API stability
    show_closed: bool = False,
) -> str:
    """Return Rich-markup for the mascot face + optional name line.

    Arguments:
      ``face``:        the state to render.
      ``agent_name``:  optional dim line below the label.
      ``frame``:       monotonic frame counter; mod'd internally.
      ``breathing``:   accepted but ignored. See module doc for why a
                       vertical-shift breath cycle doesn't work in a
                       fixed-character terminal grid.
      ``show_closed``: when True, override the per-state animation and
                       render the closed-eye frame. Used by the panel
                       for anticipation between state changes (Disney's
                       brief eyes-close-before-new-expression).
    """
    frames = _FACES[face]
    if show_closed:
        art_raw = _CLOSED_FRAME
    else:
        art_raw = frames[frame % len(frames)]

    # Interpolate eye color.
    color = _STATE_COLORS[face]
    art = art_raw.replace("{e}", color)

    bits: list[str] = [art]
    label = _LABELS[face]
    bits.append(f"  [{color}]{label}[/{color}]")
    if agent_name:
        bits.append(f"  [dim]{agent_name}[/dim]")
    return "\n".join(bits)


# ---------------------------------------------------------------------------
# State → face mapping
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MascotInputs:
    """Plain-data snapshot of everything the mapper needs to decide a face.

    Frozen so callers can compute it once per repaint and pass it around.
    No reactivity here — that's the panel widget's job.
    """

    # MIND state — from _State.mind_state ("running" | "sleeping" |
    # "paused" | "disabled" | "unknown").
    mind_state: str = "unknown"

    # Whether a tool is currently mid-call (current_tool != "").
    has_current_tool: bool = False
    # When the current tool started (monotonic clock). 0 = never.
    current_tool_start: float = 0.0

    # Last broadcast affect mood string (e.g. "pride", "anger", "humbled").
    # Empty if no affect has fired in this session.
    ego_mood: str = ""

    # Coherence ∈ [0, 1]. < 0.3 → humbled fallback.
    ego_coherence: float = 1.0

    # Whether the most-recent dashboard event was an error / preempt /
    # mind error / stuck-checkpoint warning. The panel sets this by
    # scanning the last few events on repaint.
    recent_error: bool = False

    # Whether the most-recent dashboard event was a posting / publishing
    # / mission-touch success. Used to time-limit the "happy" face so
    # success states don't stick forever.
    recent_success: bool = False

    # Monotonic timestamp of the last sign of agent life — any tool
    # call, any agent_thought chunk, any mind/scheduled event. 0 means
    # never. Critical for the case where ``mind_state`` is still
    # ``unknown`` (boot, before the gateway sends the first mind
    # event) but the agent is clearly reasoning in the chat panel.
    # Without this signal the mascot says "sleeping" while the
    # operator watches it think (observed 2026-05-21).
    last_activity_ts: float = 0.0


# Window in seconds for considering a tool call "active" vs stale.
# A tool can stay listed in current_tool after the agent stalled; without
# this window the mascot would freeze on `working` indefinitely.
_WORKING_FRESH_SECONDS = 30.0

# Window for "agent recently did SOMETHING" — any thought, tool, or
# mind event. Bigger than _WORKING_FRESH_SECONDS because reasoning
# bursts can come in gaps of 10-20s between chunks. Used to keep the
# mascot showing `thinking` while a chat / cycle is genuinely active
# but no fresh tool call is in flight.
_ACTIVITY_FRESH_SECONDS = 90.0


def decide_face(inputs: MascotInputs, *, now: float | None = None) -> MascotFace:
    """Map dashboard state to a single mascot face.

    Priority order is documented at module top. Pure function — no I/O,
    no clock reads beyond ``now`` (which defaults to ``time.monotonic()``
    for the tool-staleness check).
    """
    if now is None:
        now = _time.monotonic()

    mood = (inputs.ego_mood or "").lower()

    # 1. concerned — the strongest negative signal. Recent errors take
    #    priority over ego state because errors are immediate and
    #    actionable, mood is ambient.
    if inputs.recent_error:
        return "concerned"
    if mood in {"shame", "anger", "frustration", "anxiety", "fear"}:
        return "concerned"

    # 2. happy — recent success + non-negative affect. Both conditions
    #    required so a success buried under recent rage doesn't read
    #    as celebration.
    if inputs.recent_success and mood in {"pride", "joy", "satisfaction"}:
        return "happy"

    # Compute "tool is genuinely live" once so downstream branches
    # treat a stale current_tool the same as no tool at all. Otherwise
    # a hung tool would block `thinking` from firing and the mascot
    # would skip straight to `idle` even while the mind is running.
    tool_is_fresh = False
    if inputs.has_current_tool and inputs.current_tool_start > 0:
        age = now - inputs.current_tool_start
        tool_is_fresh = 0 <= age <= _WORKING_FRESH_SECONDS

    # "Agent is alive" signal — any tool/thought/mind event in the
    # last _ACTIVITY_FRESH_SECONDS. Computed once because it gates
    # multiple branches below.
    has_recent_activity = (
        inputs.last_activity_ts > 0
        and (now - inputs.last_activity_ts) <= _ACTIVITY_FRESH_SECONDS
    )

    # 3. working — currently executing a tool, and the call started
    #    recently enough to still count as live activity.
    if tool_is_fresh:
        return "working"

    # 4. thinking — explicit mind cycle running, OR there's been any
    #    other sign of life (thought chunks streaming, recent tool
    #    call) even when mind_state is still 'unknown' / 'sleeping'.
    #    The second branch is the fix for the boot-time case where
    #    the dashboard hasn't received a mind event yet but the
    #    agent is clearly reasoning.
    if inputs.mind_state == "running":
        return "thinking"
    if has_recent_activity:
        return "thinking"

    # 5. humbled — coherence low, no other signal pulling us elsewhere.
    #    Operators who've watched the affect manager will know what
    #    this means; new operators just see a quieter face.
    if inputs.ego_coherence < 0.3:
        return "humbled"

    # 6. idle — mind is up but resting between cycles. The
    #    chat-only / unknown-mind case is already handled in priority 4
    #    above ("thinking" on recent activity), so this branch only
    #    fires when mind_state is explicitly running/sleeping AND
    #    there's no other signal active.
    if inputs.mind_state in {"sleeping", "running"}:
        return "idle"

    # 7. sleep — fallback. Mind paused / disabled / no recent activity.
    return "sleep"
