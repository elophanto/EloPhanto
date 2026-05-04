"""EloPhanto terminal dashboard — Textual full-screen TUI.

Multi-panel dashboard inspired by Hyperspace AGI's terminal design.
Surfaces all autonomous activity (mind cycles, swarm, scheduler,
gateway sessions, tool calls) alongside the chat REPL in real time.
"""

from __future__ import annotations

import asyncio
import re
import time as _time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

# Mouse SGR escape sequences (e.g. ``\x1b[<35;62;22M``) and other CSI
# sequences sometimes leak into the input field when the terminal
# briefly steals mouse capture (Shift-drag for native selection,
# trackpad scrolls during widget transitions, etc.). Strip them on
# arrival so they never appear as visible characters or get submitted.
_ANSI_CSI_RE = re.compile(r"\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]")
# Some terminals send the bracket without the escape byte (the ESC was
# consumed by Textual's keyboard handler before the widget got it).
# Catch every common leftover shape:
#   ``[<35;62;22M``  — SGR mouse press/release (full)
#   ``<35;62;22M``   — SGR mouse with the ``[`` also eaten
#   ``[A`` ``[B`` …  — bare cursor / function keys (mess up the input cursor)
#   ``[2~``          — bare special key codes
_BARE_CSI_RE = re.compile(r"(?:\[<?\d*(?:;\d+)*[a-zA-Z~]|<\d+;\d+;\d+[Mm])")
# Last-resort match: SGR mouse params with BOTH the ESC + `[` + `<`
# eaten by upstream consumers. Looks like ``5;55;24M`` — at least
# two numeric groups separated by semicolons, terminated by M or m
# (mouse press / release in SGR mode). Real user input never contains
# this shape (chat doesn't have ``35;54;22M`` patterns), so it's safe
# to strip aggressively. This is the regex that catches the leftover
# from a real bug observed in the field where the leading framing
# was fully consumed before the input widget saw the sequence.
_NAKED_SGR_MOUSE_RE = re.compile(r"\d+(?:;\d+)+[Mm]")
# Tightest residue catcher — matches ``;<digits>M`` or ``;<digits>m``,
# the smallest fragment of a chopped SGR sequence still recognisable
# as one. ``;2M`` in normal English chat is essentially never typed,
# whereas it's the canonical leftover after the bigger regexes have
# stripped most of the mouse stream. Restricting to the
# semicolon-prefixed form means ``price 5M users`` is left alone
# (the M follows whitespace, not a semicolon).
_SGR_MOUSE_RESIDUE_RE = re.compile(r";\d+[Mm]")
# Stand-alone control characters that shouldn't appear in a chat input.
_CTRL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _ego_qualifier(ego_data: dict) -> str:
    """Derive a one-word ego qualifier from structured ego state.

    The footer / digest needs a single short word that gives the
    operator an honest sense of where the agent stands. Earlier
    versions tried to use ``last_self_critique`` directly and got
    truncated nonsense like ``ego 1.00 · I am better at`` because
    the critique is by design unsparing prose, not a mood label.

    This function maps the *structured* ego fields onto a small
    vocabulary that maps to actual states:

      - ``stale`` — ego data hasn't been recomputed in 25+ tasks
        (the recompute trigger threshold). Coherence may be stale
        even if numerically high; flag honestly.
      - ``humbled`` — many recent humbling events (≥3). The agent
        has hit walls and recorded them.
      - ``shaken`` — coherence < 0.50. Self-image has drifted from
        evidence by the ego layer's own measure.
      - ``questioning`` — coherence 0.50-0.75 OR mean confidence
        < 0.65. Some self-doubt, no crisis.
      - ``steady`` — coherence 0.75-0.92, no recent humbling,
        confidence broadly positive.
      - ``settled`` — coherence ≥ 0.92, mean confidence ≥ 0.80.
        Genuine alignment. The default 1.00 with no recompute
        history shows as ``stale`` not ``settled``.
      - ``green`` — empty/missing data (first boot, ego layer not
        yet initialized).

    Returns a single lowercase word, never longer than ~12 chars,
    safe for the 22-col footer budget.
    """
    if not ego_data:
        return "green"
    try:
        coherence = float(ego_data.get("coherence", 0.0))
    except (TypeError, ValueError):
        coherence = 0.0
    try:
        confidence_avg = float(ego_data.get("confidence_avg", 0.0))
    except (TypeError, ValueError):
        confidence_avg = 0.0
    try:
        humbling = int(ego_data.get("humbling_count", 0))
    except (TypeError, ValueError):
        humbling = 0
    try:
        tasks_since = int(ego_data.get("tasks_since_recompute", 0))
    except (TypeError, ValueError):
        tasks_since = 0

    # First-boot / no-data path. confidence_avg of 0 means no
    # capabilities have been recorded yet — the ego layer either
    # hasn't run or just started.
    if confidence_avg <= 0.0 and humbling == 0:
        return "green"

    # Stale check fires before the optimistic "settled" so we don't
    # paint over default-1.0 ego with confident words.
    if tasks_since >= 25:
        return "stale"

    if humbling >= 3:
        return "humbled"

    if coherence < 0.50:
        return "shaken"

    if coherence < 0.75 or confidence_avg < 0.65:
        return "questioning"

    if coherence >= 0.92 and confidence_avg >= 0.80:
        return "settled"

    return "steady"


def _short_tokens(n: int) -> str:
    """Compact token-count display for fixed-width sidebar columns.

    Renders 1234567 → 1.2M, 12345 → 12k, 999 → 999. Picked over
    Python's locale formatting because we want the result to fit in
    5 chars max no matter how busy the session got — the panel's
    tabular alignment depends on it."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n // 1000}k"
    if n >= 1_000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences, bare CSI leftovers, and stray
    control characters that can leak into the Input widget when the
    terminal handles mouse/keys outside Textual.

    Order matters: strip the framed shapes first, then the naked
    SGR-mouse params. Run the naked-mouse pass repeatedly because
    a stream of mouse events concatenates into garbage like
    ``5;55;24M35;54;22;27M5;65;27M`` — once the first match is
    stripped, the next leftover is now adjacent to the next, and a
    second pass picks up patterns the first missed."""
    text = _ANSI_CSI_RE.sub("", text)
    text = _BARE_CSI_RE.sub("", text)
    # Repeated passes — bounded by len(text) // 4 because each match
    # consumes ≥4 chars (smallest is `1;2M`), so we can't loop more
    # times than that.
    for _ in range(max(1, len(text) // 4)):
        new_text = _NAKED_SGR_MOUSE_RE.sub("", text)
        if new_text == text:
            break
        text = new_text
    # Final residue pass: `;<digits>M` fragments left after the
    # multi-group regex chewed through the bulk of a mouse stream.
    text = _SGR_MOUSE_RESIDUE_RE.sub("", text)
    text = _CTRL_CHARS_RE.sub("", text)
    return text


from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Input, RichLog, Static

from core.protocol import (
    GatewayMessage,
    MessageType,
    approval_response_message,
    chat_message,
    command_message,
)

# ── Palette — matches web/src/globals.css LIGHT mode ─────────────────────
# Light: warm paper white, near-monochrome — same champagne feel as elophanto.com
# oklch(0.98 0.003 80) → warm paper white background
# oklch(0.12 0.01  60) → near-black warm foreground
_OK = "#16a34a"  # success green   (darker for light bg)
_WARN = "#d97706"  # warning amber   (darker for light bg)
_DIM = "#78746e"  # muted text      (oklch 0.5 0.01 60 — warm mid-grey)
_ACCENT = "#6d28d9"  # violet accent   (darker for light bg)
_BRIGHT = "#1c1a16"  # near-black text (oklch 0.12 0.01 60 — warm)
_MIND = "#7c3aed"  # brand purple    (EloPhanto ◆ logo colour)

# Layout background tokens — LIGHT, warm paper tones (oklch hue 80 = yellow-warm)
_BG = "#f9f8f4"  # screen background — warm paper white  (oklch 0.98 0.003 80)
_SURFACE = "#f2f0ea"  # sidebar / cards    — slightly tinted  (oklch 0.97 0.004 80)
_RAISED = "#e8e4dc"  # header / input bar — elevated          (oklch 0.94 0.005 80)
_BORDER = "#d4cfc5"  # dividers           — warm separator    (oklch 0.88 0.005 80)


# ── Internal Textual message ─────────────────────────────────────────────
class _GwMsg(Message):
    """Posted when a gateway WebSocket message arrives."""

    def __init__(self, gw_msg: GatewayMessage) -> None:
        super().__init__()
        self.gw_msg = gw_msg


class _GwConnected(Message):
    """Posted when the gateway WS connection is established."""

    def __init__(self, client_id: str) -> None:
        super().__init__()
        self.client_id = client_id


class _GwDisconnected(Message):
    """Posted when the gateway WS connection drops."""


class _Tick(Message):
    """Internal timer tick for refreshing elapsed-time displays."""


# ── Dashboard state ───────────────────────────────────────────────────────
@dataclass
class _State:
    session_start: float = field(default_factory=_time.monotonic)

    # Budget
    budget_used: float = 0.0
    budget_limit: float = 100.0

    # Mind summary for header
    mind_cycle: int = 0
    mind_ts: str = "--:--"
    mode: str = "full_auto"
    gateway_port: int = 18789

    # Provider health: name → ("ok" | "warn" | "off", latency_ms)
    providers: dict[str, tuple[str, int]] = field(default_factory=dict)

    # AGENT panel
    current_tool: str = ""
    current_tool_start: float = 0.0
    current_goal: str = ""
    checkpoints_done: int = 0
    session_turns: int = 0
    session_tokens: int = 0
    session_cost: float = 0.0
    last_provider: str = ""
    last_model: str = ""

    # MIND panel
    mind_state: str = "unknown"  # running | sleeping | paused | disabled
    mind_next_wakeup_secs: int = 0
    mind_sleep_ts: float = 0.0  # monotonic when sleep started
    mind_last_action: str = ""
    mind_cycles_today: int = 0
    mind_cost_today: float = 0.0
    mind_budget_pct: int = 0

    # SWARM panel: list of {name, agent, pct, status}
    swarm_tasks: list[dict] = field(default_factory=list)

    # SCHEDULER panel: list of {name, eta_secs, status, ts_str}
    scheduled_tasks: list[dict] = field(default_factory=list)

    # GATEWAY panel: list of {channel, user, active}
    sessions: list[dict] = field(default_factory=list)

    # GOALS panel: list of {title, pct, checkpoint, status}
    # `status` is one of: active | paused | done | blocked.
    # `pct` is integer 0-100 derived from completed/total checkpoints.
    goals: list[dict] = field(default_factory=list)

    # APPROVALS panel: list of {tool, summary, age_secs}
    # Pending owner-approval requests. Drives the "wanted your eyes
    # on" line in the digest as well as the always-visible APPROVALS
    # sidebar panel.
    approvals: list[dict] = field(default_factory=list)

    # Ego footer — coherence + mood are read from the agent's ego
    # layer. Shown in the sidebar's permanent footer + the digest.
    ego_coherence: float = 0.0
    ego_mood: str = ""

    # P2P footer — peers connected via libp2p (if peers.enabled). 0
    # is the no-op default; positive number means decentralized
    # transport is up and someone's connected.
    p2p_peer_count: int = 0

    # Event feed (newest last, rendered newest-first)
    events: deque = field(default_factory=lambda: deque(maxlen=50))

    # ── Helpers ──────────────────────────────────────────────────────────

    def session_elapsed(self) -> str:
        secs = int(_time.monotonic() - self.session_start)
        h, r = divmod(secs, 3600)
        m, _ = divmod(r, 60)
        return f"{h}h{m:02d}m" if h else f"{m}m"

    def budget_bar(self, width: int = 10) -> str:
        pct = min(100, int(self.budget_used / max(self.budget_limit, 0.01) * 100))
        filled = int(pct / 100 * width)
        bar = "█" * filled + "░" * (width - filled)
        color = _OK if pct < 80 else (_WARN if pct < 95 else "red")
        return f"[{color}]{bar}[/]"

    def mind_eta(self) -> str:
        if self.mind_state != "sleeping" or not self.mind_sleep_ts:
            return ""
        elapsed = int(_time.monotonic() - self.mind_sleep_ts)
        remaining = max(0, self.mind_next_wakeup_secs - elapsed)
        if remaining >= 3600:
            return f"{remaining // 3600}h{(remaining % 3600) // 60}m"
        if remaining >= 60:
            return f"{remaining // 60}m{remaining % 60}s"
        return f"{remaining}s"


# ── Sidebar panels ────────────────────────────────────────────────────────


class _SidePanel(Static):
    """Base sidebar panel — single-glyph header + Rich markup body.

    Visual language (revised): each panel is a glyph + uppercase name
    on one line, then 1-3 body rows. No box-drawing rules around the
    content — whitespace + glyph carry the structure. Sections are
    separated by a single blank row in the parent container, not by
    rules inside each panel. Reads as denser-but-cleaner than the
    prior box-everywhere style.
    """

    DEFAULT_CSS = """
    _SidePanel {
        height: auto;
        padding: 0 1 1 1;
        color: #78746e;
    }
    """

    # Single-character glyph that visually identifies the panel. Each
    # subclass overrides. Convention: ◆ for primary state, ◇ for
    # ambient state, ⚡ for activity, ⏱ for scheduled, ! for needs-
    # attention. Picked to read as quiet typography rather than emoji.
    GLYPH = "◆"
    GLYPH_COLOR = "#7c3aed"  # _MIND violet by default

    def __init__(self, title: str, state: _State, **kwargs: Any) -> None:
        super().__init__(markup=True, **kwargs)
        self._title = title
        self._st = state

    def _hdr(self) -> str:
        return f"[{self.GLYPH_COLOR}]{self.GLYPH}[/] " f"[{_BRIGHT}]{self._title}[/]"

    def body(self) -> str:  # noqa: D102
        return ""

    def repaint(self) -> None:
        body = self.body()
        if body:
            self.update(f"{self._hdr()}\n{body}")
        else:
            self.update(self._hdr())


class _AgentPanel(_SidePanel):
    GLYPH = "◆"
    GLYPH_COLOR = "#7c3aed"

    def __init__(self, state: _State) -> None:
        super().__init__("AGENT", state, id="panel-agent")

    def body(self) -> str:
        s = self._st
        # Row 1: live activity. When running a tool, show the tool +
        # elapsed seconds; otherwise "idle". This is the panel's
        # signature line — what the agent is actually doing right now.
        if s.current_tool:
            elapsed = int(_time.monotonic() - s.current_tool_start)
            line1 = (
                f"  [{_OK}]●[/] [{_BRIGHT}]{s.current_tool[:14]}[/]"
                f" [{_DIM}]{elapsed:>3d}s[/]"
            )
        else:
            line1 = f"  [{_DIM}]◇ idle[/]"

        # Row 2: model — quiet, contextual; only shown when we have
        # one. Provider+slash dropped from the visible label; the
        # model name alone is enough. Truncated to 22 chars to keep
        # the row inside the 30-col sidebar without wrapping.
        if s.last_model:
            model_short = s.last_model.split("/")[-1][:22]
            line2 = f"  [{_DIM}]via[/] [{_BRIGHT}]{model_short}[/]"
        else:
            line2 = ""

        # Row 3: stats. Tabular alignment via fixed-width labels so
        # the numbers hover at the same x-positions on every repaint.
        # turns·tokens·cost — the operator's "is this expensive" check.
        tkn = _short_tokens(s.session_tokens)
        # Glyph-only labels keep this row inside ~24 visible cols so it
        # doesn't wrap on a 30-col sidebar. ⊘ turns, ◇ tokens, $ cost —
        # the visual context is enough; the verbose ``turns/tok/cost``
        # labels were eating ~10 cols of width for no real signal gain.
        line3 = (
            f"  [{_BRIGHT}]{s.session_turns}[/][{_DIM}]t[/]"
            f"  [{_BRIGHT}]{tkn}[/]"
            f"  [{_BRIGHT}]${s.session_cost:.2f}[/]"
        )

        return "\n".join(line for line in (line1, line2, line3) if line)


class _MindPanel(_SidePanel):
    GLYPH = "◇"
    GLYPH_COLOR = "#7c3aed"

    def __init__(self, state: _State) -> None:
        super().__init__("MIND", state, id="panel-mind")

    def body(self) -> str:
        s = self._st
        # Mood is the panel's signature line — the autonomous mind's
        # current state in one phrase. Each state gets a verb ("running",
        # "pondering", "resting") and a colour that hints at energy
        # level. "sleeping" reads as restful + ETA-aware, not blocked.
        if s.mind_state == "running":
            line1 = f"  [{_OK}]●[/] [{_OK}]running[/]"
        elif s.mind_state == "sleeping":
            eta = s.mind_eta() or "?"
            # "resting · 4m" — dropped "wakes in" because the colon-
            # space-eta reads obvious enough. Saves 9 cols on a tight
            # sidebar.
            line1 = f"  [{_ACCENT}]●[/] [{_DIM}]resting ·[/] [{_BRIGHT}]{eta}[/]"
        elif s.mind_state == "paused":
            line1 = f"  [{_DIM}]◇[/] [{_DIM}]paused[/]"
        elif s.mind_state == "disabled":
            line1 = f"  [{_DIM}]○[/] [{_DIM}]off[/]"
        else:
            line1 = f"  [{_DIM}]?[/] [{_DIM}]{s.mind_state}[/]"

        # Last action — what the autonomous mind last did. Truncated
        # to 18 chars without a "last·" prefix; readers infer "this is
        # what it just did" from context (it's row 2 of the MIND
        # panel). Saves 6 cols of label.
        if s.mind_last_action:
            line2 = f"  [{_DIM}]›[/] [{_BRIGHT}]{s.mind_last_action[:18]}[/]"
        else:
            line2 = ""

        # Glyph-only labels (matching AGENT row 3): c for cycles, $ for
        # cost, % for daily budget. Fits inside ~22 visible cols so the
        # 30-col sidebar doesn't wrap.
        line3 = (
            f"  [{_BRIGHT}]{s.mind_cycles_today}[/][{_DIM}]c[/]"
            f"  [{_BRIGHT}]${s.mind_cost_today:.2f}[/]"
            f"  [{_DIM}]{s.mind_budget_pct}%[/]"
        )

        return "\n".join(line for line in (line1, line2, line3) if line)


class _SwarmPanel(_SidePanel):
    GLYPH = "⚡"
    GLYPH_COLOR = "#d97706"  # amber — the "energy" colour for activity

    def __init__(self, state: _State) -> None:
        super().__init__("SWARM", state, id="panel-swarm")

    def body(self) -> str:
        s = self._st
        if not s.swarm_tasks:
            return f"  [{_DIM}]· · ·[/]"

        # State -> dot. Dot is the leading glyph; running/queued/done/
        # failed are the four states the orchestrator emits.
        icons = {
            "running": f"[{_OK}]●[/]",
            "queued": f"[{_DIM}]○[/]",
            "done": f"[{_OK}]✓[/]",
            "failed": "[red]✗[/]",
        }
        lines = []
        # Show the last 4 — limited to keep the sidebar from running
        # off the bottom of the screen on a busy session.
        for task in s.swarm_tasks[-4:]:
            icon = icons.get(task.get("status", ""), f"[{_DIM}]?[/]")
            # 8-char name cap matches GOALS panel; visual rhyme.
            name = task.get("name", "?")[:8]
            pct = int(task.get("pct", 0))
            filled = min(4, max(0, int(pct / 25)))
            bar = f"[{_OK}]{'▓' * filled}[/][{_DIM}]{'░' * (4 - filled)}[/]"
            lines.append(
                f"  {icon} [{_BRIGHT}]{name:<8}[/] {bar} [{_DIM}]{pct:>3d}%[/]"
            )
        return "\n".join(lines)


class _SchedulerPanel(_SidePanel):
    GLYPH = "⏱"
    GLYPH_COLOR = "#6d28d9"  # violet — kindred with MIND

    def __init__(self, state: _State) -> None:
        super().__init__("SCHEDULED", state, id="panel-scheduler")

    def body(self) -> str:
        s = self._st
        if not s.scheduled_tasks:
            return f"  [{_DIM}]· · ·[/]"

        icons = {
            "pending": f"[{_DIM}]○[/]",
            "done": f"[{_OK}]✓[/]",
            "running": f"[{_OK}]●[/]",
            "failed": "[red]✗[/]",
        }
        lines = []
        for task in s.scheduled_tasks[-4:]:
            icon = icons.get(task.get("status", "pending"), f"[{_DIM}]○[/]")
            # 12-char name + 6-char right column fits 22:
            # 2 indent + 2 icon + 12 name + 1 + 5 right = 22.
            # The 16-char cap from the prior version wrapped because
            # the visible budget on a 30-col sidebar with Textual's
            # border + container padding is closer to 22 than 28.
            name = task.get("name", "?")[:12]
            eta = task.get("eta_str", "")
            ts = task.get("ts_str", "")
            # Compact "5m" / "1h" preferred over "in 5m" — saves 3 cols.
            right = eta if eta else ts
            lines.append(f"  {icon} [{_BRIGHT}]{name:<12}[/] [{_DIM}]{right}[/]")
        return "\n".join(lines)


class _GatewayPanel(_SidePanel):
    GLYPH = "⌁"
    GLYPH_COLOR = "#16a34a"  # green — the "connections live" colour

    def __init__(self, state: _State) -> None:
        super().__init__("GATEWAY", state, id="panel-gateway")

    def body(self) -> str:
        s = self._st
        # Channels row: dot per channel + name. Dedupe by channel name
        # so two sessions on the same channel collapse to one pill.
        if not s.sessions:
            line1 = f"  [{_DIM}]· · ·[/]"
        else:
            seen: dict[str, bool] = {}
            for sess in s.sessions:
                ch = sess.get("channel", "?")
                seen[ch] = seen.get(ch, False) or sess.get("active", False)
            parts = []
            for ch, active in seen.items():
                dot = f"[{_OK}]●[/]" if active else f"[{_DIM}]○[/]"
                parts.append(f"{dot} [{_BRIGHT}]{ch}[/]")
            line1 = "  " + "  ".join(parts)

        # Footer row: count + port, tabular-aligned with other panels.
        count = len(s.sessions)
        line2 = (
            f"  [{_DIM}]sess[/] [{_BRIGHT}]{count:<3d}[/]"
            f"  [{_DIM}]port[/] [{_BRIGHT}]{s.gateway_port}[/]"
        )
        return f"{line1}\n{line2}"


class _GoalsPanel(_SidePanel):
    """Active multi-step goals — title + checkpoint progress.

    Was previously a single line buried in AGENT (`goal: <title>`).
    Promoted to its own panel because:
      1. Goals run for days; they belong in ambient state, not the
         AGENT panel which shows the current LLM call.
      2. Multiple goals can be active concurrently (a research goal
         and a build goal in parallel) — single line couldn't show
         both.
      3. Checkpoint progress (3/7) is the operator's main "is this
         making progress" signal; deserves visual prominence.
    """

    GLYPH = "◆"
    GLYPH_COLOR = "#16a34a"  # green — the "in motion" colour

    def __init__(self, state: _State) -> None:
        super().__init__("GOALS", state, id="panel-goals")

    def body(self) -> str:
        s = self._st
        if not s.goals:
            return f"  [{_DIM}]· · ·[/]"

        icons = {
            "active": f"[{_OK}]●[/]",
            "paused": f"[{_DIM}]◇[/]",
            "blocked": f"[{_WARN}]●[/]",
            "done": f"[{_OK}]✓[/]",
        }
        lines = []
        # Show top 3 — too many goals at once usually means the
        # operator hasn't pruned, and the panel shouldn't compensate
        # for that by growing taller and squashing other panels.
        for goal in s.goals[:3]:
            icon = icons.get(goal.get("status", "active"), f"[{_DIM}]?[/]")
            # 8-char title cap. Sidebar visual budget after Textual
            # border + padding is ~22 cols on a 30-col panel:
            # 2 indent + 2 icon+space + 8 title + 1 + 4 bar + 1 + 4 tail = 22.
            # Earlier 14-char cap wrapped on real terminals.
            title = goal.get("title", "?")[:8]
            pct = int(goal.get("pct", 0))
            checkpoint = goal.get("checkpoint", "")
            filled = min(4, max(0, int(pct / 25)))
            bar = f"[{_OK}]{'▓' * filled}[/][{_DIM}]{'░' * (4 - filled)}[/]"
            tail = (
                f"[{_DIM}]{checkpoint}[/]" if checkpoint else f"[{_DIM}]{pct:>3d}%[/]"
            )
            lines.append(f"  {icon} [{_BRIGHT}]{title:<8}[/] {bar} {tail}")
        return "\n".join(lines)


class _ApprovalsPanel(_SidePanel):
    """Pending owner-approval requests.

    The "wanted your eyes on" surface. Hidden when empty (zero
    visual weight when the agent has nothing to ask) but loud when
    there's something pending — coloured amber, age in seconds so
    the operator can see whether a request has been sitting for
    minutes vs. seconds.
    """

    GLYPH = "!"
    GLYPH_COLOR = "#d97706"  # amber — needs-attention

    def __init__(self, state: _State) -> None:
        super().__init__("APPROVALS", state, id="panel-approvals")

    def body(self) -> str:
        s = self._st
        if not s.approvals:
            # When there are no approvals, return empty body — the
            # parent paints just the header. Even better would be to
            # hide the whole widget; the wiring for that lives in
            # compose() / repaint_panels.
            return ""

        lines = []
        for req in s.approvals[:3]:
            tool = req.get("tool", "?")[:12]
            summary = req.get("summary", "")[:28]
            age_secs = int(req.get("age_secs", 0))
            # Age displayed in the smallest unit that keeps the text
            # 4 chars or fewer: 9s, 12s, 1m, 4h.
            if age_secs < 60:
                age = f"{age_secs}s"
            elif age_secs < 3600:
                age = f"{age_secs // 60}m"
            else:
                age = f"{age_secs // 3600}h"
            lines.append(
                f"  [{_WARN}]●[/] [{_BRIGHT}]{tool:<12}[/] [{_DIM}]{age:>4}[/]"
            )
            if summary:
                lines.append(f"    [{_DIM}]{summary}[/]")
        return "\n".join(lines)


class _FooterPanel(_SidePanel):
    """Permanent sidebar footer — ego coherence + peer count.

    Sits at the bottom of the sidebar regardless of how many other
    panels are mounted above. Two single-line slots that always
    have a value (ego coherence is bounded [0.05, 0.95]; peer count
    is 0 when libp2p is off). Reads as a quiet status line, not a
    panel, so the ── separator is omitted.
    """

    GLYPH = "·"
    GLYPH_COLOR = "#78746e"  # dim — footer is ambient state

    def __init__(self, state: _State) -> None:
        super().__init__("", state, id="panel-footer")

    def _hdr(self) -> str:
        # Override: the footer doesn't render a header, just the body.
        # Empty title would still render a leading glyph; suppress it
        # entirely so the footer reads as a statusline.
        return ""

    def body(self) -> str:
        s = self._st
        ego_str = (
            f"[{_DIM}]ego[/] [{_BRIGHT}]{s.ego_coherence:.2f}[/]"
            if s.ego_coherence > 0
            else f"[{_DIM}]ego –[/]"
        )
        if s.ego_mood:
            ego_str += f" [{_DIM}]· {s.ego_mood[:14]}[/]"

        peers_str = (
            f"[{_DIM}]peers[/] [{_BRIGHT}]{s.p2p_peer_count}[/]"
            if s.p2p_peer_count > 0
            else f"[{_DIM}]peers 0[/]"
        )
        return f"  {ego_str}\n  {peers_str}"


# ── Digest — "since you were away" opening message ────────────────────────


@dataclass
class _DigestEntry:
    """One row in the digest. Free-form structure — the renderer
    decides which sections to include based on which lists have
    content. Intentionally lightweight; no rich types so callers
    can populate from arbitrary backend queries without heavy mapping.
    """

    text: str
    detail: str = ""
    glyph: str = "→"
    color: str = ""  # hex, defaults to bright when empty


@dataclass
class _Digest:
    """Aggregate of agent activity since the last terminal open.

    Populated by the dashboard from existing data sources (session
    history, goal store, approval queue, ego layer). All fields
    optional — empty digest is a valid state, the renderer simply
    skips empty sections.
    """

    since_label: str = ""  # "14h" | "yesterday" | "" if first ever open
    done: list[_DigestEntry] = field(default_factory=list)
    doing: list[_DigestEntry] = field(default_factory=list)
    needs_eyes: list[_DigestEntry] = field(default_factory=list)
    mood: str = ""
    ego_coherence: float = 0.0


def _render_digest(d: _Digest) -> str:
    """Render the digest as Rich markup for the chat RichLog.

    Sections are skipped when empty so a fresh install (no goals,
    no history, no approvals) renders as a single greeting line
    rather than an awkward shell of empty headers.

    Reads cold to a new operator: it tells them what the agent did
    while they were away, what's running, what needs them, and the
    mood — in one scrollable block they can read once and forget.
    """
    rows: list[str] = []

    # Greeting line — sets the tone. Never absent.
    if d.since_label:
        rows.append(
            f"[{_MIND}]◆[/] [{_BRIGHT}]EloPhanto[/]"
            f"  [{_DIM}]· {d.since_label} since you opened me[/]"
        )
    else:
        rows.append(f"[{_MIND}]◆[/] [{_BRIGHT}]EloPhanto[/]")
    rows.append("")  # breathing room before sections

    def _section(label: str, entries: list[_DigestEntry], glyph_color: str) -> None:
        if not entries:
            return
        rows.append(f"  [{_DIM}]{label}[/]")
        for e in entries:
            color = e.color or _BRIGHT
            glyph_c = glyph_color or _DIM
            line = f"    [{glyph_c}]{e.glyph}[/] [{color}]{e.text}[/]"
            if e.detail:
                line += f"   [{_DIM}]{e.detail}[/]"
            rows.append(line)
        rows.append("")

    _section("Done while you were away", d.done, _OK)
    _section("Doing now", d.doing, _ACCENT)
    _section("Wanted your eyes on", d.needs_eyes, _WARN)

    # Mood footer — quiet, single line. Skipped when no signal.
    if d.mood or d.ego_coherence > 0:
        bits = []
        if d.mood:
            bits.append(f"[{_BRIGHT}]{d.mood}[/]")
        if d.ego_coherence > 0:
            bits.append(f"[{_DIM}]ego coherence[/] [{_BRIGHT}]{d.ego_coherence:.2f}[/]")
        rows.append(f"  [{_DIM}]Mood ·[/]  " + "  ".join(bits))
        rows.append("")

    # Trailing rule — the digest ends so chat can begin. Reads as
    # "the page break" between the digest and live conversation.
    rows.append(f"  [{_DIM}]{'─' * 64}[/]")
    return "\n".join(rows)


def _build_digest_from_state(state: _State, seed: dict) -> _Digest:
    """Build a `_Digest` from current sidebar state + caller-supplied
    seed dict. Pure function — no I/O, no time-of-day side-effects.

    `seed` shape (all fields optional):
        {
          "since_label": "14h",
          "done": [{"text": "...", "detail": "...", "glyph": "→"}, ...],
          "doing": [{"text": "...", "detail": "...", "glyph": "◆"}, ...],
          "needs_eyes": [{"text": "...", "detail": "...", "glyph": "!"}, ...],
          "mood": "steady, productive",
        }

    The launcher (start.sh path) populates `seed` by querying the
    agent's existing systems (session history, goal store, approval
    queue, ego layer) before spawning the dashboard. The dashboard
    itself is data-pure — it doesn't directly query these systems
    so we don't tangle UI lifecycle with agent state lifecycle.

    When `seed` is empty, the digest derives "doing now" from the
    current sidebar state (active goals, running swarm tasks,
    pending approvals) so even without a launcher digest the user
    sees a useful summary on session start.
    """
    digest = _Digest(
        since_label=seed.get("since_label", ""),
        mood=seed.get("mood", "") or state.ego_mood,
        ego_coherence=state.ego_coherence,
    )

    # Seed-supplied entries take priority. Pass through with light
    # default-fill so callers can pass minimal dicts without specifying
    # the glyph/color on every entry.
    def _coerce(items: list, default_glyph: str) -> list[_DigestEntry]:
        out = []
        for it in items or []:
            if isinstance(it, _DigestEntry):
                out.append(it)
                continue
            out.append(
                _DigestEntry(
                    text=str(it.get("text", "")),
                    detail=str(it.get("detail", "")),
                    glyph=str(it.get("glyph", default_glyph)),
                    color=str(it.get("color", "")),
                )
            )
        return out

    digest.done = _coerce(seed.get("done", []), "→")
    digest.needs_eyes = _coerce(seed.get("needs_eyes", []), "!")

    # Doing-now: prefer caller's explicit list; otherwise auto-derive
    # from sidebar state. Goals + active swarm tasks make natural
    # "doing now" entries because they're already structured.
    if seed.get("doing"):
        digest.doing = _coerce(seed["doing"], "◆")
    else:
        derived: list[_DigestEntry] = []
        for goal in (state.goals or [])[:3]:
            title = goal.get("title", "")
            if not title:
                continue
            checkpoint = goal.get("checkpoint", "")
            pct = int(goal.get("pct", 0))
            detail = checkpoint if checkpoint else f"{pct}%"
            derived.append(
                _DigestEntry(
                    text=f"goal · {title}",
                    detail=detail,
                    glyph="◆",
                )
            )
        for task in (state.swarm_tasks or [])[:2]:
            if task.get("status") != "running":
                continue
            name = task.get("name", "")
            if not name:
                continue
            agent = task.get("agent", "")
            derived.append(
                _DigestEntry(
                    text=f"swarm · {name}",
                    detail=f"on {agent}" if agent else "",
                    glyph="⚡",
                )
            )
        digest.doing = derived

    # If no needs-eyes were seeded, derive from active approval queue.
    if not digest.needs_eyes and state.approvals:
        for req in state.approvals[:2]:
            digest.needs_eyes.append(
                _DigestEntry(
                    text=f"{req.get('tool', 'tool')} approval pending",
                    detail=str(req.get("summary", "")),
                    glyph="!",
                )
            )

    return digest


# ── Header widget ──────────────────────────────────────────────────────────


class _Header(Static):
    """1-row header — brand · session · budget · mode · providers.

    Was 2 rows (general + providers). Compressed to 1 by:
      - dropping the verbose ``budget:`` label and showing just the
        bar + ``$used/$limit``
      - condensing providers to a row of dots + names (no per-provider
        latency by default — the doctor command is the right place
        for that detail)
      - moving cycle info into the MIND sidebar panel where it belongs

    Reclaims a row of vertical real estate that the chat transcript
    can use instead.
    """

    DEFAULT_CSS = """
    _Header {
        height: 1;
        padding: 0 1;
        background: #e8e4dc;
        color: #78746e;
    }
    """

    def __init__(self, state: _State) -> None:
        super().__init__(markup=True, id="header")
        self._st = state

    def repaint(self) -> None:
        s = self._st
        elapsed = s.session_elapsed()
        budget_bar = s.budget_bar(8)
        budget_str = f"${s.budget_used:.2f}/${s.budget_limit:.0f}"

        # Compact provider summary: dot per provider, no labels except
        # name. A red/amber/green dot conveys most of what an operator
        # needs at a glance; precise latency lives in `elophanto doctor`.
        if s.providers:
            prov_parts = []
            for name, (status, _lat) in s.providers.items():
                if status == "ok":
                    dot = f"[{_OK}]●[/]"
                elif status == "warn":
                    dot = f"[{_WARN}]●[/]"
                else:
                    dot = f"[{_DIM}]○[/]"
                prov_parts.append(f"{dot} [{_DIM}]{name}[/]")
            providers = "  ".join(prov_parts)
        else:
            providers = f"[{_DIM}]providers ·[/]"

        row = (
            f"[{_MIND}]◆[/] [{_BRIGHT}]EloPhanto[/]   "
            f"[{_DIM}]{elapsed}[/]   "
            f"{budget_bar} [{_DIM}]{budget_str}[/]   "
            f"[{_DIM}]{s.mode}[/]   "
            f"{providers}"
        )
        self.update(row)


# ── Main app ───────────────────────────────────────────────────────────────


class EloPhantoDashboard(App):
    """Full-screen terminal dashboard for EloPhanto."""

    CSS = """
    Screen {
        layout: vertical;
        background: #f9f8f4;
    }
    #body {
        layout: horizontal;
        height: 1fr;
    }
    #sidebar {
        width: 30;
        min-width: 30;
        border-right: solid #d4cfc5;
        background: #f2f0ea;
        overflow-y: auto;
    }
    #main-area {
        layout: vertical;
        width: 1fr;
    }
    #chat {
        height: 1fr;
        padding: 0 1;
        background: #f9f8f4;
    }
    #feed-header {
        height: 1;
        padding: 0 1;
        background: #f9f8f4;
        border-top: solid #d4cfc5;
        color: #78746e;
    }
    #events {
        height: 5;
        background: #f9f8f4;
        padding: 0 1;
    }
#input-bar {
        height: 3;
        background: #e8e4dc;
        border-top: solid #d4cfc5;
        padding: 0 1;
    }
    #input-bar Input {
        background: #e8e4dc;
        border: none;
        color: #1c1a16;
        padding: 0 0;
    }
    #input-bar Input:focus {
        border: none;
    }
    #input-bar Input > .input--cursor {
        background: #7c3aed;
        color: #f9f8f4;
    }
    #input-bar Input > .input--placeholder {
        color: #b8b2a8;
    }
    _SidePanel {
        height: auto;
        padding: 0 1 1 1;
        color: #78746e;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit_app", "Quit", show=False),
        Binding("ctrl+x", "cancel_request", "Cancel", show=False),
        Binding("ctrl+y", "copy_last", "Copy", show=False),
        Binding("f1", "toggle_sidebar", "Sidebar", show=False),
    ]

    _connected: reactive[bool] = reactive(False)

    def __init__(
        self,
        gateway_url: str = "ws://127.0.0.1:18789",
        *,
        digest_seed: dict | None = None,
    ) -> None:
        super().__init__()
        self._gw_url = gateway_url
        self._ws: Any = None
        self._session_id = ""
        self._user_id = "cli-user"
        self._pending: dict[str, asyncio.Future[GatewayMessage]] = {}
        self._state = _State()
        self._awaiting_response = False
        self._current_msg_id = ""
        self._approval_pending: GatewayMessage | None = None
        self._last_response: str = ""
        self._sidebar_visible = True
        # Optional digest input from the launcher (start.sh / the CLI
        # entry point) — pre-populated facts the dashboard renders as
        # the "since you were away" opening message. None / empty dict
        # = no digest, just a one-line greeting in the digest's place.
        self._digest_seed: dict = digest_seed or {}

    # ── Compose ──────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield _Header(self._state)
        with Horizontal(id="body"):
            with VerticalScroll(id="sidebar"):
                # Order matters — primary state first, ambient state
                # second, activity third, infra/gateway last. The
                # Footer panel anchors the bottom regardless of how
                # tall the panels above it grow.
                yield _AgentPanel(self._state)
                yield _MindPanel(self._state)
                yield _GoalsPanel(self._state)
                yield _SwarmPanel(self._state)
                yield _SchedulerPanel(self._state)
                yield _ApprovalsPanel(self._state)
                yield _GatewayPanel(self._state)
                yield _FooterPanel(self._state)
            with Vertical(id="main-area"):
                chat_log = RichLog(id="chat", highlight=True, markup=True, wrap=True)
                chat_log.can_focus = False  # let terminal handle mouse/selection
                yield chat_log
                yield Static("", id="feed-header", markup=True)
                yield RichLog(
                    id="events", highlight=True, markup=True, wrap=False, max_lines=50
                )
        with Vertical(id="input-bar"):
            yield Input(
                placeholder="❯ type a message, /help, or exit  ·  Shift+drag to select text",
                id="input",
            )

    # ── Lifecycle ────────────────────────────────────────────────────────

    def _suppress_mouse_tracking(self) -> None:
        """Send the full set of "disable mouse tracking" CSI sequences
        directly to the terminal. Idempotent. Called on mount AND
        every 500ms after, because Textual re-enables tracking on
        mount, refocus, paste, etc. — and once tracking is on, every
        mouse move dumps a chunk of SGR codes that get partially
        consumed by Textual's renderer and partially leak into the
        Input widget as visible text (the "5;55;24M..." garbage).

        We can't ask Textual nicely to stop because there's no public
        API for it; brute-forcing via stdout works because Textual's
        renderer treats raw escape writes as opaque pass-through."""
        try:
            import sys as _sys

            _sys.stdout.write(
                "\x1b[?1000l"  # X10 mouse tracking off
                "\x1b[?1002l"  # button-event tracking off
                "\x1b[?1003l"  # any-event tracking off
                "\x1b[?1006l"  # SGR extended mode off
                "\x1b[?1015l"  # urxvt extended mode off
            )
            _sys.stdout.flush()
        except Exception:
            pass

    def on_mount(self) -> None:
        self._connect_gateway(self._gw_url)
        self._start_tick()
        self.query_one("#feed-header", Static).update(
            f"[{_DIM}]─── LIVE FEED {'─' * 60}[/]"
        )
        # Paint the digest as the FIRST scrollable item in chat. It
        # scrolls up and out of view as soon as the operator sends
        # their first message, so it doesn't compete for permanent
        # screen real estate. _build_digest reads from existing
        # systems (state + caller-supplied digest_seed) and falls
        # back to a minimal greeting when there's nothing yet.
        try:
            digest = _build_digest_from_state(self._state, self._digest_seed)
            self.query_one("#chat", RichLog).write(_render_digest(digest))
        except Exception:
            # Digest is best-effort eye-candy — never block startup
            # because of a render glitch. Fall through to chat.
            pass
        # Focus input immediately
        self.query_one("#input", Input).focus()
        # Disable terminal mouse tracking — we don't react to mouse here
        # and Textual's default tracking dumps SGR codes into the Input
        # whenever the cursor passes over the window or a trackpad
        # twitch fires while focus is elsewhere. Send the disable
        # sequences directly to the terminal; Textual's renderer leaves
        # them alone.
        self._suppress_mouse_tracking()
        # Textual re-enables mouse tracking whenever certain widgets
        # mount, refocus, or handle a paste — so a one-shot disable on
        # mount is not enough. Re-send the disable sequences every
        # 500ms. Cheap (a few stdout bytes), and bounded — Textual's
        # tick scheduler stops with the app. This is the load-bearing
        # fix for "mouse moves keep leaking SGR codes into the input"
        # that survived multiple reported attempts before this one.
        self.set_interval(0.5, self._suppress_mouse_tracking)

    @work(exclusive=True)
    async def _connect_gateway(self, url: str) -> None:
        """Background worker: connect to gateway WS and listen for messages."""
        import websockets  # type: ignore[import]

        try:
            async with websockets.connect(url) as ws:
                self._ws = ws
                # Read initial status / connected message
                raw = await ws.recv()
                msg = GatewayMessage.from_json(str(raw))
                if msg.type == MessageType.STATUS:
                    client_id = msg.data.get("client_id", "")
                    self.post_message(_GwConnected(client_id))

                # Drain incoming messages and post to app
                async for raw in ws:
                    try:
                        gw_msg = GatewayMessage.from_json(str(raw))
                        self.post_message(_GwMsg(gw_msg))
                    except Exception:
                        pass
        except Exception as exc:
            self._add_event(f"[red]Gateway disconnected:[/] {exc}", tag="GW")
            self.post_message(_GwDisconnected())

    @work(exclusive=False)
    async def _start_tick(self) -> None:
        """Post a _Tick every 5 seconds so elapsed-time panels refresh."""
        while True:
            await asyncio.sleep(5)
            self.post_message(_Tick())

    # ── Gateway message handlers ─────────────────────────────────────────

    def on__gw_connected(self, message: _GwConnected) -> None:
        self._connected = True
        self._add_event(
            f"[{_OK}]Connected to gateway[/] · {message.client_id[:8]}", tag="GW"
        )
        self._repaint_all()
        # Ask for initial status to populate provider health + scheduler
        self.run_worker(self._request_status(), exclusive=False)

    def on__gw_disconnected(self, message: _GwDisconnected) -> None:
        self._connected = False
        self._add_event("[red]Gateway disconnected[/]", tag="GW")

    def on__gw_msg(self, message: _GwMsg) -> None:
        self._dispatch(message.gw_msg)

    def on__tick(self, message: _Tick) -> None:
        # Refresh panels that show elapsed time
        self._repaint_panel("panel-agent")
        self._repaint_panel("panel-mind")
        self._repaint_header()
        # Refresh scheduler/providers every 30s (6 ticks × 5s)
        self._tick_count = getattr(self, "_tick_count", 0) + 1
        if (
            self._tick_count % 6 == 0
            and self._connected
            and not self._awaiting_response
        ):
            self.run_worker(self._request_status(), exclusive=False)

    def _dispatch(self, msg: GatewayMessage) -> None:
        if msg.type == MessageType.RESPONSE:
            reply_to = msg.data.get("reply_to", "")
            future = self._pending.get(reply_to)
            if future and not future.done():
                future.set_result(msg)
            else:
                self._on_response(msg)

        elif msg.type == MessageType.APPROVAL_REQUEST:
            self._on_approval_request(msg)

        elif msg.type == MessageType.EVENT:
            self._on_event(msg)

        elif msg.type == MessageType.ERROR:
            reply_to = msg.data.get("reply_to", "")
            future = self._pending.get(reply_to)
            if future and not future.done():
                future.set_exception(RuntimeError(msg.data.get("detail", "error")))
            else:
                detail = msg.data.get("detail", "unknown error")
                chat = self.query_one("#chat", RichLog)
                chat.write(f"[red]Error:[/] {detail}")

    def _on_response(self, msg: GatewayMessage) -> None:
        if msg.session_id:
            self._session_id = msg.session_id
        content = msg.data.get("content", "")

        # Check if this is a dashboard command response — has a "dashboard" key
        # directly in data, or content is JSON with a "dashboard" key.
        dashboard_data = msg.data.get("dashboard")
        if dashboard_data is None and content:
            import json

            try:
                parsed = json.loads(content)
                dashboard_data = parsed.get("dashboard")
            except (json.JSONDecodeError, AttributeError):
                pass

        if dashboard_data is not None:
            # Silently consume dashboard responses — don't print to chat
            self._parse_status_data(dashboard_data)
            self._awaiting_response = False
            self._repaint_all()
            return

        # Extract provider/model from response metadata
        _resp_provider = msg.data.get("provider", "")
        _resp_model = msg.data.get("model", "")
        if _resp_provider:
            self._state.last_provider = _resp_provider
        if _resp_model:
            self._state.last_model = _resp_model

        if content:
            self._last_response = content
            chat = self.query_one("#chat", RichLog)
            chat.write("")
            # Show provider/model in response header
            _model_tag = ""
            if _resp_provider and _resp_model:
                _m_short = _resp_model.split("/")[-1][:20]
                _model_tag = f"  [{_DIM}]{_resp_provider}/{_m_short}[/]"
            chat.write(f"[#b8b2a8]─[/] [bold {_MIND}]EloPhanto[/]{_model_tag}")
            chat.write(content)
            chat.write("")

        # Clear thinking indicator
        self._awaiting_response = False
        self.query_one("#input", Input).placeholder = (
            "❯ type a message, /help, or exit  ·  Ctrl+Y to copy last response"
        )

        # Update session stats from response metadata
        usage = msg.data.get("usage", {})
        if usage:
            self._state.session_tokens += usage.get("total_tokens", 0)
            cost = usage.get("cost_usd", 0.0)
            self._state.session_cost += cost
            self._state.budget_used += cost
        self._state.session_turns += 1

        self._repaint_all()

    def _on_approval_request(self, msg: GatewayMessage) -> None:
        self._approval_pending = msg
        tool_name = msg.data.get("tool_name", "?")
        description = msg.data.get("description", "")
        chat = self.query_one("#chat", RichLog)
        chat.write("")
        chat.write(f"[{_WARN}]⚠ Approval needed[/]  [{_BRIGHT}]{tool_name}[/]")
        chat.write(f"  [{_DIM}]{description}[/]")
        chat.write(
            f"  [{_DIM}]Type [/][{_BRIGHT}]y[/][{_DIM}] to approve or [/][{_BRIGHT}]n[/][{_DIM}] to deny[/]"
        )
        chat.write("")
        self.query_one("#input", Input).placeholder = "❯ y / n"

    def _on_event(self, msg: GatewayMessage) -> None:
        event = msg.data.get("event", "")

        if event == "step_progress":
            tool_name = msg.data.get("tool_name", "")
            if tool_name:
                if not self._state.current_tool:
                    self._state.current_tool_start = _time.monotonic()
                self._state.current_tool = tool_name
                self.query_one("#input", Input).placeholder = (
                    f"❯ running {tool_name}..."
                )
                self._add_event(f"[{_ACCENT}]{tool_name}[/]", tag="AGT")
                self._repaint_panel("panel-agent")

        elif event == "task_complete":
            self._state.current_tool = ""
            self._state.current_goal = ""
            goal = msg.data.get("goal", "")
            self._add_event(
                f"[{_OK}]✓[/] task complete: [{_DIM}]{goal[:50]}[/]", tag="AGT"
            )
            self.query_one("#input", Input).placeholder = (
                "❯ type a message, /help, or exit"
            )
            self._repaint_all()

        elif event == "goal_started":
            goal = msg.data.get("goal", "")
            self._state.current_goal = goal[:40]
            self._add_event(
                f"[white on blue] ▶ GOAL [/] [{_DIM}]{goal[:50]}[/]", tag="AGT"
            )
            chat = self.query_one("#chat", RichLog)
            chat.write(f"\n[white on blue] ▶ GOAL [/] [{_DIM}]{goal[:60]}[/]")
            self._repaint_panel("panel-agent")

        elif event == "goal_checkpoint_complete":
            title = msg.data.get("checkpoint_title", "")
            order = msg.data.get("checkpoint_order", "")
            self._state.checkpoints_done = max(
                self._state.checkpoints_done, int(order or 0)
            )
            self._add_event(
                f"[black on {_OK}] ✓ CP {order} [/] [{_DIM}]{title[:40]}[/]", tag="AGT"
            )
            self._repaint_panel("panel-agent")

        elif event == "goal_completed":
            goal = msg.data.get("goal", "")
            self._state.current_goal = ""
            self._state.checkpoints_done = 0
            chat = self.query_one("#chat", RichLog)
            chat.write(f"[black on {_OK}] ✔ COMPLETED [/] [{_DIM}]{goal[:60]}[/]\n")
            self._add_event(f"[{_OK}]✔[/] goal completed", tag="AGT")
            self._repaint_panel("panel-agent")

        elif event == "goal_failed":
            error = msg.data.get("error", "")
            self._state.current_goal = ""
            chat = self.query_one("#chat", RichLog)
            chat.write(f"[white on red] ✖ FAILED [/] [{_DIM}]{error[:80]}[/]\n")
            self._add_event("[red]✖[/] goal failed", tag="AGT")
            self._repaint_panel("panel-agent")

        elif event == "user_message":
            ch = msg.data.get("channel", "?")
            content = msg.data.get("content", "")
            if ch != "cli" and content:
                chat = self.query_one("#chat", RichLog)
                chat.write(f"  [{_DIM}]({ch})[/] [{_BRIGHT}]{content[:200]}[/]")
            self._state.sessions = self._ensure_session(self._state.sessions, ch, True)
            self._repaint_panel("panel-gateway")

        elif event == "notification":
            ntype = msg.data.get("notification_type", "")
            if ntype == "scheduled_result":
                task_name = msg.data.get("task_name", "")
                status = msg.data.get("status", "")
                icon = "✅" if status == "completed" else "⚠️"
                self._add_event(f"{icon} scheduled: [{_DIM}]{task_name}[/]", tag="SCH")
                # Update scheduler panel
                self._update_scheduled_task(
                    task_name, "done" if status == "completed" else "failed"
                )
                self._repaint_panel("panel-scheduler")

        elif event.startswith("mind_"):
            self._handle_mind_event(event, msg.data)

        elif event in (
            "agent_spawned",
            "agent_completed",
            "agent_failed",
            "agent_stopped",
        ):
            self._handle_swarm_event(event, msg.data)

        elif event in ("heartbeat_check", "heartbeat_action", "heartbeat_idle"):
            label = event.replace("heartbeat_", "hb:")
            self._add_event(f"[{_DIM}]{label}[/]", tag="HB")

        elif event in ("webhook_received", "webhook_task_started"):
            endpoint = msg.data.get("endpoint", "")
            self._add_event(f"[{_ACCENT}]webhook:[/] [{_DIM}]{endpoint}[/]", tag="WH")

    def _handle_mind_event(self, event: str, data: dict) -> None:
        s = self._state

        if event == "mind_wakeup":
            s.mind_state = "running"
            s.mind_cycle = data.get("cycle", s.mind_cycle)
            s.mind_ts = _time.strftime("%H:%M")
            s.mind_cycles_today = data.get("total_cycles_today", s.mind_cycles_today)
            last = data.get("last_action", "")
            if last and last != "(not started)":
                s.mind_last_action = last[:30]

            # Parse budget
            try:
                b_rem = float(
                    str(data.get("budget_remaining", "")).replace("$", "") or 0
                )
                b_tot = float(
                    str(data.get("budget_total", "")).replace("$", "") or s.budget_limit
                )
                if b_tot > 0:
                    s.budget_limit = b_tot
                    s.budget_used = b_tot - b_rem
                    s.mind_budget_pct = min(100, int((b_tot - b_rem) / b_tot * 100))
            except (ValueError, TypeError):
                pass

            self._add_event(f"[{_MIND}]mind[/] cycle #{s.mind_cycle} wakeup", tag="MND")

        elif event == "mind_tool_use":
            tool = data.get("tool", "")
            if tool:
                if not s.current_tool:
                    s.current_tool_start = _time.monotonic()
                s.current_tool = tool
            self._add_event(f"[{_DIM}]tool:[/] [{_ACCENT}]{tool[:30]}[/]", tag="MND")

        elif event == "mind_action":
            summary = data.get("summary", "")
            cost_str = data.get("cost", "")
            try:
                s.mind_cost_today += float(cost_str.replace("$", "") or 0)
            except (ValueError, AttributeError):
                pass
            if summary:
                s.mind_last_action = summary[:30]
            s.current_tool = ""

        elif event == "mind_sleep":
            s.mind_state = "sleeping"
            s.mind_next_wakeup_secs = int(data.get("next_wakeup_seconds", 300))
            s.mind_sleep_ts = _time.monotonic()
            try:
                cost = float(str(data.get("cycle_cost", "")).replace("$", "") or 0)
                s.mind_cost_today += cost
            except (ValueError, TypeError):
                pass
            s.current_tool = ""
            wakeup_str = _fmt_secs(s.mind_next_wakeup_secs)
            self._add_event(
                f"[{_DIM}]mind sleeping · next in {wakeup_str}[/]", tag="MND"
            )

        elif event == "mind_paused":
            s.mind_state = "paused"
            self._add_event(f"[{_DIM}]mind paused[/]", tag="MND")

        elif event == "mind_resumed":
            s.mind_state = "running"
            self._add_event(f"[{_MIND}]mind resumed[/]", tag="MND")

        elif event == "mind_error":
            error = data.get("error", "")
            self._add_event(f"[red]mind error:[/] [{_DIM}]{error[:50]}[/]", tag="MND")

        self._repaint_panel("panel-mind")
        self._repaint_header()

    def _handle_swarm_event(self, event: str, data: dict) -> None:
        s = self._state
        agent_id = data.get("agent_id", data.get("swarm_id", "?"))
        task = data.get("task", data.get("goal", agent_id))[:20]
        agent_type = data.get("profile", data.get("agent_type", "agent"))

        if event == "agent_spawned":
            s.swarm_tasks.append(
                {"name": task, "agent": agent_type, "pct": 0, "status": "running"}
            )
            self._add_event(f"[{_OK}]swarm:[/] spawned [{_DIM}]{task}[/]", tag="SW")

        elif event == "agent_completed":
            self._set_swarm_status(task, "done", 100)
            self._add_event(f"[{_OK}]swarm:[/] completed [{_DIM}]{task}[/]", tag="SW")

        elif event in ("agent_failed", "agent_stopped"):
            self._set_swarm_status(task, "failed", 0)
            self._add_event(
                f"[red]swarm:[/] {event.replace('agent_', '')} [{_DIM}]{task}[/]",
                tag="SW",
            )

        self._repaint_panel("panel-swarm")

    # ── Input handler ─────────────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        """Strip leaked mouse-tracking / ANSI bytes as the user types.

        Without this, Shift-drag for terminal selection (or any moment
        the terminal briefly handles mouse outside Textual) can dump
        sequences like ``[<35;62;22M`` into the input field.
        """
        cleaned = _strip_ansi(event.value)
        if cleaned != event.value:
            event.input.value = cleaned

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = _strip_ansi(event.value).strip()
        event.input.clear()
        if not text:
            return

        # Handle pending approval
        if self._approval_pending:
            approved = text.lower() in ("y", "yes", "approve", "ok", "1")
            denied = text.lower() in ("n", "no", "deny", "0")
            if approved or denied:
                await self._send_ws(
                    approval_response_message(self._approval_pending.id, approved)
                )
                self._approval_pending = None
                verdict = f"[{_OK}]approved[/]" if approved else "[red]denied[/]"
                chat = self.query_one("#chat", RichLog)
                chat.write(f"  {verdict}")
                self.query_one("#input", Input).placeholder = (
                    "❯ type a message, /help, or exit"
                )
                return
            # Not a yes/no — clear the approval and send as chat
            self._approval_pending = None

        low = text.lower()

        # Local commands
        if low in ("exit", "quit", "q"):
            self.exit()
            return

        # Slash commands
        if low.startswith("/") and "/" not in low[1:]:
            parts = low[1:].split(None, 1)
            cmd = parts[0]
            args = parts[1] if len(parts) > 1 else ""

            chat = self.query_one("#chat", RichLog)
            if cmd == "clear":
                await self._send_ws(
                    command_message(
                        "clear",
                        channel="cli",
                        user_id=self._user_id,
                        session_id=self._session_id,
                    )
                )
                self._session_id = ""
                chat.clear()
                chat.write(f"[{_OK}]Session cleared.[/]")
                return
            if cmd == "stop":
                await self._send_ws(
                    command_message(
                        "cancel",
                        channel="cli",
                        user_id=self._user_id,
                        session_id=self._session_id,
                    )
                )
                chat.write(f"[{_WARN}]Cancel requested.[/]")
                return
            if cmd == "help":
                chat.write(
                    f"\n[{_ACCENT}]Commands[/]\n"
                    "/clear       Reset session\n"
                    "/stop        Cancel running request\n"
                    "/status      Gateway status\n"
                    "/mind        Mind status\n"
                    "/mind stop   Stop mind\n"
                    "/mind start  Start mind\n"
                    "/health      Provider health\n"
                    "/config      Read/update config\n"
                    "exit         Quit dashboard\n"
                )
                return
            # Send other slash commands to gateway
            await self._send_ws(
                command_message(
                    cmd,
                    args={"subcommand": args} if args else None,
                    channel="cli",
                    user_id=self._user_id,
                    session_id=self._session_id,
                )
            )
            return

        # Regular chat message
        chat = self.query_one("#chat", RichLog)
        chat.write(f"[#b8b2a8]─[/] [bold {_BRIGHT}]You[/]")
        chat.write(text)
        chat.write("")

        if not self._ws:
            chat.write(f"[{_WARN}]Not connected to gateway.[/]")
            return

        msg = chat_message(
            text, channel="cli", user_id=self._user_id, session_id=self._session_id
        )
        future: asyncio.Future[GatewayMessage] = (
            asyncio.get_event_loop().create_future()
        )
        self._pending[msg.id] = future

        self._awaiting_response = True
        self.query_one("#input", Input).placeholder = "❯ thinking..."

        await self._send_ws(msg)

        # Wait for response in a worker so the UI stays responsive
        self._wait_response(msg.id, future)

    @work(exclusive=False)
    async def _wait_response(
        self, msg_id: str, future: asyncio.Future[GatewayMessage]
    ) -> None:
        try:
            response = await future
            self.post_message(_GwMsg(response))
        except asyncio.CancelledError:
            pass
        finally:
            self._pending.pop(msg_id, None)

    # ── Key routing ───────────────────────────────────────────────────────

    def on_key(self, event: events.Key) -> None:
        """Route printable keys (except space) to the input widget."""
        if event.key == "space":
            return  # handled by key_space below
        inp = self.query_one("#input", Input)
        if inp.has_focus:
            return
        if event.is_printable and event.character:
            inp.focus()
            inp.insert_text_at_cursor(event.character)
            event.stop()

    def key_space(self) -> None:
        """Insert a space character — needed because Kitty keyboard protocol sends
        space with character=None, making event.is_printable=False so Input ignores it.
        """
        inp = self.query_one("#input", Input)
        inp.focus()
        inp.insert_text_at_cursor(" ")

    # ── Bindings ──────────────────────────────────────────────────────────

    async def action_quit_app(self) -> None:
        self.exit()

    async def action_cancel_request(self) -> None:
        if self._awaiting_response and self._ws:
            await self._send_ws(
                command_message(
                    "cancel",
                    channel="cli",
                    user_id=self._user_id,
                    session_id=self._session_id,
                )
            )
            self._awaiting_response = False
            self.query_one("#input", Input).placeholder = (
                "❯ type a message, /help, or exit"
            )

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar")
        self._sidebar_visible = not self._sidebar_visible
        sidebar.display = self._sidebar_visible

    def action_copy_last(self) -> None:
        """Copy last agent response to system clipboard."""
        import subprocess

        if not self._last_response:
            self._add_event("Nothing to copy", tag="CPY")
            return
        try:
            subprocess.run(
                ["pbcopy"],
                input=self._last_response.encode(),
                check=True,
                timeout=2,
            )
            # Show truncated preview in event feed
            preview = self._last_response[:60].replace("\n", " ")
            self._add_event(f"Copied to clipboard: {preview}...", tag="CPY")
        except FileNotFoundError:
            # Linux fallback
            try:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=self._last_response.encode(),
                    check=True,
                    timeout=2,
                )
                self._add_event("Copied to clipboard", tag="CPY")
            except Exception:
                self._add_event("[red]No clipboard tool found[/]", tag="CPY")
        except Exception as exc:
            self._add_event(f"[red]Copy failed:[/] {exc}", tag="CPY")

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _send_ws(self, msg: GatewayMessage) -> None:
        if self._ws:
            try:
                await self._ws.send(msg.to_json())
            except Exception as exc:
                self._add_event(f"[red]Send error:[/] {exc}", tag="GW")

    async def _request_status(self) -> None:
        """Send dashboard command to populate initial provider/scheduler state."""
        await asyncio.sleep(0.5)  # let connection settle
        await self._send_ws(
            command_message("dashboard", channel="cli", user_id=self._user_id)
        )

    def _parse_status_data(self, data: dict) -> None:
        """Parse /status response to populate provider health, scheduler, etc."""
        s = self._state

        providers = data.get("providers", {})
        for name, info in providers.items():
            if isinstance(info, dict):
                healthy = info.get("healthy", True)
                enabled = info.get("enabled", True)
                lat = int(info.get("latency_ms", 0))
                if not enabled:
                    status = "off"
                elif healthy:
                    status = "ok"
                else:
                    status = "warn"
                s.providers[name] = (status, lat)

        scheduled = data.get("scheduled_tasks", [])
        if scheduled:
            import datetime

            now = datetime.datetime.now(datetime.UTC)
            parsed = []
            for t in scheduled[:6]:
                name = t.get("name", "?")
                last_status = t.get("last_status", "pending") or "pending"
                # Compute ETA from next_run_at (ISO string or None)
                eta_str = ""
                ts_str = ""
                next_run = t.get("next_run_at")
                if next_run:
                    try:
                        if isinstance(next_run, str):
                            next_dt = datetime.datetime.fromisoformat(next_run)
                        else:
                            next_dt = next_run
                        if next_dt.tzinfo is None:
                            next_dt = next_dt.replace(tzinfo=datetime.UTC)
                        delta = int((next_dt - now).total_seconds())
                        eta_str = _fmt_secs(max(0, delta))
                    except Exception:
                        eta_str = str(next_run)[:12]
                last_run = t.get("last_run_at")
                if last_run and not eta_str:
                    try:
                        if isinstance(last_run, str):
                            ts_str = last_run[11:16]  # HH:MM from ISO
                        else:
                            ts_str = str(last_run)[:5]
                    except Exception:
                        ts_str = ""
                parsed.append(
                    {
                        "name": name,
                        "eta_str": eta_str,
                        "ts_str": ts_str,
                        "status": last_status,
                    }
                )
            s.scheduled_tasks = parsed

        budget = data.get("budget", {})
        if budget:
            s.budget_used = budget.get("used_today", s.budget_used)
            s.budget_limit = budget.get("daily_limit", s.budget_limit)

        mode = data.get("permission_mode", "")
        if mode:
            s.mode = mode

        port = data.get("gateway_port", 0)
        if port:
            s.gateway_port = port

        # Ego (footer + digest mood). Populated when the agent's
        # identity layer is initialized; absent on first boot before
        # the ego subsystem has computed an initial coherence score.
        # The qualifier ("steady" / "shaken" / etc.) is *derived* from
        # structured numbers, not from prose — earlier the gateway
        # sent last_self_critique here and the footer rendered
        # "ego 1.00 · I am better at" which is unsparing critique
        # truncated to 14 chars, NOT a mood. See _ego_qualifier docs.
        ego = data.get("ego", {})
        if ego:
            try:
                s.ego_coherence = float(ego.get("coherence", 0.0))
            except (TypeError, ValueError):
                pass
            s.ego_mood = _ego_qualifier(ego)

        # Goals (sidebar GOALS panel + digest "doing now" auto-derive).
        # Each entry: {title, pct, checkpoint, status}.
        goals = data.get("goals", [])
        if isinstance(goals, list):
            s.goals = [g for g in goals if isinstance(g, dict) and g.get("title")]

        # Approvals — pending owner-confirmation requests. Each entry:
        # {tool, summary, age_secs}.
        approvals = data.get("approvals", [])
        if isinstance(approvals, list):
            s.approvals = [
                a for a in approvals if isinstance(a, dict) and a.get("tool")
            ]

        # libp2p peer count for the footer. 0 = decentralized peers
        # disabled or no peers connected.
        try:
            s.p2p_peer_count = int(data.get("p2p_peer_count", 0))
        except (TypeError, ValueError):
            pass

        self._repaint_all()

    def _add_event(self, line: str, tag: str = "   ") -> None:
        ts = _time.strftime("%H:%M:%S")
        entry = f"[{_DIM}]{ts}[/]  [{_ACCENT}]{tag:<3}[/]  {line}"
        self._state.events.appendleft(entry)
        try:
            feed = self.query_one("#events", RichLog)
            feed.write(entry)
        except Exception:
            pass

    def _repaint_panel(self, panel_id: str) -> None:
        try:
            panel = self.query_one(f"#{panel_id}", _SidePanel)
            panel.repaint()
        except Exception:
            pass

    def _repaint_header(self) -> None:
        try:
            self.query_one("#header", _Header).repaint()
        except Exception:
            pass

    def _repaint_all(self) -> None:
        self._repaint_header()
        for pid in (
            "panel-agent",
            "panel-mind",
            "panel-goals",
            "panel-swarm",
            "panel-scheduler",
            "panel-approvals",
            "panel-gateway",
            "panel-footer",
        ):
            self._repaint_panel(pid)

    def _set_swarm_status(self, name: str, status: str, pct: int) -> None:
        for task in self._state.swarm_tasks:
            if task.get("name", "").startswith(name[:10]):
                task["status"] = status
                task["pct"] = pct
                return

    def _update_scheduled_task(self, name: str, status: str) -> None:
        for task in self._state.scheduled_tasks:
            if task.get("name") == name:
                task["status"] = status
                return

    @staticmethod
    def _ensure_session(sessions: list[dict], channel: str, active: bool) -> list[dict]:
        for s in sessions:
            if s.get("channel") == channel:
                s["active"] = active
                return sessions
        sessions.append({"channel": channel, "active": active})
        return sessions


# ── Utility ───────────────────────────────────────────────────────────────


def _fmt_secs(secs: int) -> str:
    if secs >= 3600:
        return f"{secs // 3600}h{(secs % 3600) // 60}m"
    if secs >= 60:
        return f"{secs // 60}m{secs % 60}s"
    return f"{secs}s"


# ── Launch helpers ────────────────────────────────────────────────────────


def should_use_dashboard() -> bool:
    """Return True if the terminal supports the full-screen dashboard."""
    import os
    import shutil
    import sys

    if not sys.stdout.isatty():
        return False
    if os.environ.get("TERM") in ("dumb", ""):
        return False
    if os.environ.get("NO_DASHBOARD"):
        return False
    if shutil.get_terminal_size(fallback=(0, 0)).columns < 80:
        return False
    # Check textual is importable
    try:
        import textual  # noqa: F401
    except ImportError:
        return False
    return True


async def run_dashboard(gateway_url: str) -> None:
    """Run the Textual dashboard app (async entry point)."""
    app = EloPhantoDashboard(gateway_url=gateway_url)
    await app.run_async()
