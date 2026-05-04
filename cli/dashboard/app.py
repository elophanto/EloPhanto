"""EloPhanto terminal dashboard — Textual full-screen TUI.

Single-surface design: a unified scrollable transcript carries chat,
tool calls, scheduled-task firings, and notifications, with a 1-row
glance-able status bar pinned at the bottom for high-frequency state
(gateway sessions, budget, permission mode, scheduled/goal/swarm
counts, autonomous-mind phase). The transcript leads with a digest
of "what's happening / what wants your attention" so opening the
dashboard feels like checking in on a creature that's been doing
things, not starting a new chat from zero.
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
from textual.containers import Vertical
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
    """Base sidebar panel — title rule + Rich markup body."""

    DEFAULT_CSS = """
    _SidePanel {
        height: auto;
        padding: 0 1 1 1;
        color: #78746e;
    }
    """

    def __init__(self, title: str, state: _State, **kwargs: Any) -> None:
        super().__init__(markup=True, **kwargs)
        self._title = title
        self._st = state

    def _hdr(self) -> str:
        pad = max(0, 28 - len(self._title))
        return f"[#b8b2a8]──[/] [{_DIM}]{self._title}[/] [#b8b2a8]{'─' * pad}[/]"

    def body(self) -> str:  # noqa: D102
        return ""

    def repaint(self) -> None:
        self.update(f"{self._hdr()}\n{self.body()}")


class _AgentPanel(_SidePanel):
    def __init__(self, state: _State) -> None:
        super().__init__("AGENT", state, id="panel-agent")

    def body(self) -> str:
        s = self._st
        if s.current_tool:
            elapsed = int(_time.monotonic() - s.current_tool_start)
            tool = (
                f"[{_OK}]●[/] [{_MIND}]{s.current_tool[:22]}[/] [{_DIM}]{elapsed}s[/]"
            )
        else:
            tool = f"[{_DIM}]◆ idle[/]"

        goal = f"  [{_DIM}]goal: {s.current_goal[:26]}[/]" if s.current_goal else ""
        chk = (
            f"  [{_DIM}]✓ {s.checkpoints_done} checkpoints[/]"
            if s.checkpoints_done
            else ""
        )
        tkn = (
            f"{s.session_tokens // 1000}k"
            if s.session_tokens >= 1000
            else str(s.session_tokens)
        )
        # Provider/model line
        if s.last_provider and s.last_model:
            model_short = s.last_model.split("/")[-1][:20]
            provider_model = (
                f"  [{_DIM}]via[/] [{_BRIGHT}]{s.last_provider}/{model_short}[/]"
            )
        else:
            provider_model = ""

        stats = (
            f"  [{_DIM}]turns:[/][{_BRIGHT}]{s.session_turns}[/] "
            f"[{_DIM}]tokens:[/][{_BRIGHT}]{tkn}[/] "
            f"[{_DIM}]cost:[/][{_BRIGHT}]${s.session_cost:.2f}[/]"
        )
        lines = [f"  {tool}"]
        if provider_model:
            lines.append(provider_model)
        if goal:
            lines.append(goal)
        if chk:
            lines.append(chk)
        lines.append(stats)
        return "\n".join(lines)


class _MindPanel(_SidePanel):
    def __init__(self, state: _State) -> None:
        super().__init__("MIND", state, id="panel-mind")

    def body(self) -> str:
        s = self._st
        state_icons = {
            "running": f"[{_OK}]●[/]",
            "sleeping": f"[{_ACCENT}]●[/]",
            "paused": f"[{_DIM}]◇[/]",
            "disabled": f"[{_DIM}]○[/]",
            "unknown": f"[{_DIM}]?[/]",
        }
        icon = state_icons.get(s.mind_state, f"[{_DIM}]?[/]")
        if s.mind_state == "sleeping":
            eta = s.mind_eta()
            state_str = f"{icon} [{_DIM}]sleeping · wakes {eta}[/]"
        elif s.mind_state == "running":
            state_str = f"{icon} [{_OK}]running[/]"
        elif s.mind_state == "paused":
            state_str = f"{icon} [{_DIM}]paused[/]"
        elif s.mind_state == "disabled":
            state_str = f"{icon} [{_DIM}]disabled[/]"
        else:
            state_str = f"{icon} [{_DIM}]{s.mind_state}[/]"

        last = (
            f"  [{_DIM}]last: {s.mind_last_action[:26]}[/]"
            if s.mind_last_action
            else ""
        )
        usage = (
            f"  [{_DIM}]cycles:[/][{_BRIGHT}]{s.mind_cycles_today}[/] "
            f"[{_DIM}]cost:[/][{_BRIGHT}]${s.mind_cost_today:.2f}[/] "
            f"[{_DIM}]{s.mind_budget_pct}% daily[/]"
        )
        lines = [f"  {state_str}"]
        if last:
            lines.append(last)
        lines.append(usage)
        return "\n".join(lines)


class _SwarmPanel(_SidePanel):
    def __init__(self, state: _State) -> None:
        super().__init__("SWARM", state, id="panel-swarm")

    def body(self) -> str:
        s = self._st
        if not s.swarm_tasks:
            return f"  [{_DIM}]no active agents[/]"

        icons = {
            "running": f"[{_OK}]●[/]",
            "queued": f"[{_DIM}]○[/]",
            "done": f"[{_OK}]✓[/]",
            "failed": "[red]✗[/]",
        }
        lines = []
        for task in s.swarm_tasks[-4:]:  # show last 4
            icon = icons.get(task.get("status", ""), f"[{_DIM}]?[/]")
            name = task.get("name", "?")[:12]
            agent = task.get("agent", "")[:8]
            pct = task.get("pct", 0)
            filled = int(pct / 100 * 5)
            bar = f"[{_OK}]{'█' * filled}[/][{_DIM}]{'░' * (5 - filled)}[/]"
            lines.append(
                f"  {icon} [{_BRIGHT}]{name:<12}[/] [{_DIM}]{agent:<8}[/] {bar} [{_DIM}]{pct:3d}%[/]"
            )
        return "\n".join(lines)


class _SchedulerPanel(_SidePanel):
    def __init__(self, state: _State) -> None:
        super().__init__("SCHEDULER", state, id="panel-scheduler")

    def body(self) -> str:
        s = self._st
        if not s.scheduled_tasks:
            return f"  [{_DIM}]no scheduled tasks[/]"

        icons = {
            "pending": f"[{_DIM}]○[/]",
            "done": f"[{_OK}]✓[/]",
            "running": f"[{_OK}]●[/]",
            "failed": "[red]✗[/]",
        }
        lines = []
        for task in s.scheduled_tasks[-4:]:
            icon = icons.get(task.get("status", "pending"), f"[{_DIM}]○[/]")
            name = task.get("name", "?")[:18]
            eta = task.get("eta_str", "")
            ts = task.get("ts_str", "")
            right = f"in {eta}" if eta else ts
            lines.append(f"  {icon} [{_ACCENT}]{name:<18}[/] [{_DIM}]{right}[/]")
        return "\n".join(lines)


class _GatewayPanel(_SidePanel):
    def __init__(self, state: _State) -> None:
        super().__init__("GATEWAY", state, id="panel-gateway")

    def body(self) -> str:
        s = self._st
        if not s.sessions:
            channels_str = f"  [{_DIM}]no sessions[/]"
        else:
            seen: dict[str, bool] = {}
            for sess in s.sessions:
                ch = sess.get("channel", "?")
                seen[ch] = seen.get(ch, False) or sess.get("active", False)
            parts = []
            for ch, active in seen.items():
                dot = f"[{_OK}]●[/]" if active else f"[{_DIM}]○[/]"
                parts.append(f"{dot} [{_ACCENT}]{ch}[/]")
            channels_str = "  " + "  ".join(parts)

        count = len(s.sessions)
        port_str = f"  [{_DIM}]{count} sessions · port {s.gateway_port}[/]"
        return f"{channels_str}\n{port_str}"


# ── Header widget ──────────────────────────────────────────────────────────


class _Header(Static):
    """2-row header bar with budget, mind cycle, providers."""

    DEFAULT_CSS = """
    _Header {
        height: 2;
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
        budget_bar = s.budget_bar(10)
        budget_str = f"${s.budget_used:.2f}/${s.budget_limit:.0f}"
        cycle_str = (
            f"cycle #{s.mind_cycle} · {s.mind_ts}" if s.mind_cycle else "cycle –"
        )

        row1 = (
            f"[{_MIND}]◆[/] [{_BRIGHT}]EloPhanto[/]  "
            f"[{_DIM}]{elapsed}[/]  "
            f"[{_DIM}]budget:[/] {budget_bar} [{_DIM}]{budget_str}[/]  "
            f"[{_DIM}]{cycle_str}[/]  "
            f"[{_DIM}]{s.mode}[/]"
        )

        # Provider row
        if s.providers:
            prov_parts = []
            for name, (status, lat) in s.providers.items():
                dot = (
                    f"[{_OK}]●[/]"
                    if status == "ok"
                    else f"[{_WARN}]●[/]" if status == "warn" else f"[{_DIM}]○[/]"
                )
                lat_str = f"({lat}ms)" if lat and status != "off" else ""
                prov_parts.append(f"{dot} [{_DIM}]{name}[/] [{_DIM}]{lat_str}[/]")
            row2 = "  ".join(prov_parts)
        else:
            row2 = f"[{_DIM}]providers: connecting...[/]"

        self.update(f"{row1}\n{row2}")


# ── Status bar ────────────────────────────────────────────────────────────


class _StatusBar(Static):
    """One-row status strip at the very bottom of the screen.

    Replaces the old 30-column sidebar. Packs the high-frequency state
    that used to live in vertical panels — gateway sessions, budget,
    permission mode, schedule + goal counts — into a single horizontal
    row of glance-able tokens.

    The visual grammar:
      gw●N sess  $X/$Y  mode  N sched  N goals  N swarm   <Tab> menu
       ↑                                                       ↑
      gateway dot + session count           hint about deeper views

    Colour signals state without taking extra columns: the gateway dot
    is green when connected, dim when not; the budget number turns
    amber past 80% and red past 95%; running swarm/goal counts go
    accent-coloured when non-zero. Anything zero falls to dim text so
    it doesn't distract.
    """

    DEFAULT_CSS = """
    _StatusBar {
        height: 1;
        padding: 0 2;
        background: #f2f0ea;
    }
    """

    def __init__(self, state: _State) -> None:
        super().__init__(markup=True, id="status-bar")
        self._st = state

    def repaint(self) -> None:
        s = self._st
        # Gateway: green dot + session count when connected, dim ring
        # when disconnected. Compressed to 6-8 chars from the old
        # 4-row gateway panel.
        if s.sessions:
            active = sum(1 for x in s.sessions if x.get("active"))
            gw = f"[{_OK}]●[/][{_BRIGHT}]{active}[/][{_DIM}]sess[/]"
        else:
            gw = f"[{_DIM}]○ idle[/]"

        # Budget: numeric ratio with the limit, color shifts past 80/95%.
        used = s.budget_used
        lim = max(s.budget_limit, 0.01)
        pct = used / lim * 100
        budget_color = _OK if pct < 80 else (_WARN if pct < 95 else "red")
        budget = f"[{_DIM}]$[/][{budget_color}]{used:.2f}[/][{_DIM}]/${lim:.0f}[/]"

        # Mode: the permission gate. ask_always | smart_auto | full_auto.
        mode = f"[{_DIM}]{s.mode}[/]"

        # Counts — accent only when non-zero. Zero stays dim so the
        # bar doesn't shout when nothing's happening.
        sched_n = len(s.scheduled_tasks)
        goal_active = 1 if s.current_goal else 0
        swarm_n = sum(1 for t in s.swarm_tasks if t.get("status") == "running")

        def _count(n: int, label: str) -> str:
            color = _ACCENT if n else _DIM
            num_color = _BRIGHT if n else _DIM
            return f"[{num_color}]{n}[/] [{color}]{label}[/]"

        sched = _count(sched_n, "sched")
        goals = _count(goal_active, "goal")
        swarm = _count(swarm_n, "swarm")

        # Mind cycle indicator — pulses subtly when the autonomous loop
        # is doing something. Using ◆ as the brand glyph; dimmed when
        # idle, accent when active.
        if s.mind_state == "running":
            mind = f"[{_MIND}]◆[/] [{_DIM}]thinking[/]"
        elif s.mind_state == "sleeping":
            mind = f"[{_DIM}]◆ {s.mind_eta() or 'idle'}[/]"
        else:
            mind = f"[{_DIM}]◆ -[/]"

        # Right-side hint for the deeper menu — mirrors what the user
        # types to access more state. Non-essential, dim, easy to ignore.
        hint = f"[{_DIM}]<Tab> menu[/]"

        # Compose with two-space separators between tokens. Tabular
        # density matters here — extra padding between would make the
        # status bar feel padded-out instead of dense.
        line = (
            f"{gw}  {budget}  {mode}  {sched}  {goals}  {swarm}  {mind}"
            f"        {hint}"
        )
        self.update(line)


# ── Main app ───────────────────────────────────────────────────────────────


class EloPhantoDashboard(App):
    """Full-screen terminal dashboard for EloPhanto."""

    # New layout — full-width transcript with a 1-row status bar at
    # the very bottom, composer above it. Sidebar/feed split was
    # replaced by inline events in the transcript, with the high-
    # frequency state compressed into the status bar. The transcript
    # is the single source of truth for the user's read; the status
    # bar is a glance-able summary they can ignore until they need it.
    CSS = """
    Screen {
        layout: vertical;
        background: #f9f8f4;
    }
    #transcript {
        height: 1fr;
        padding: 1 2 0 2;
        background: #f9f8f4;
    }
    #composer {
        height: 3;
        background: #e8e4dc;
        border-top: solid #d4cfc5;
        padding: 0 2;
    }
    #composer Input {
        background: #e8e4dc;
        border: none;
        color: #1c1a16;
        padding: 0 0;
    }
    #composer Input:focus {
        border: none;
    }
    #composer Input > .input--cursor {
        background: #7c3aed;
        color: #f9f8f4;
    }
    #composer Input > .input--placeholder {
        color: #b8b2a8;
    }
    #status-bar {
        height: 1;
        background: #f2f0ea;
        color: #78746e;
        padding: 0 2;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit_app", "Quit", show=False),
        Binding("ctrl+x", "cancel_request", "Cancel", show=False),
        Binding("ctrl+y", "copy_last", "Copy", show=False),
        Binding("f1", "toggle_sidebar", "Sidebar", show=False),
    ]

    _connected: reactive[bool] = reactive(False)

    def __init__(self, gateway_url: str = "ws://127.0.0.1:18789") -> None:
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

    # ── Compose ──────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        # Transcript is full-width — chat messages, tool calls, scheduled
        # events, system notes all share this single scrollable surface.
        # Tool calls render inline under the user-message that triggered
        # them, so the read flow follows the agent's actual sequence
        # instead of requiring the user to glance between panes.
        transcript = RichLog(
            id="transcript", highlight=True, markup=True, wrap=True, max_lines=2000
        )
        transcript.can_focus = False  # let terminal handle mouse/selection
        yield transcript

        with Vertical(id="composer"):
            yield Input(
                placeholder="❯ type a message, /help, or exit  ·  Shift+drag to select text",
                id="input",
            )

        # Status bar lives at the bottom edge — one row, always visible,
        # color-coded glance-able state. Replaces 30 columns of vertical
        # sidebar with 1 row of horizontal density. Repaints on each
        # tick so it stays current without the user looking elsewhere.
        yield _StatusBar(self._state)

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
        self._render_digest()
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
                chat = self.query_one("#transcript", RichLog)
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
            chat = self.query_one("#transcript", RichLog)
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
        chat = self.query_one("#transcript", RichLog)
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
            chat = self.query_one("#transcript", RichLog)
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
            chat = self.query_one("#transcript", RichLog)
            chat.write(f"[black on {_OK}] ✔ COMPLETED [/] [{_DIM}]{goal[:60]}[/]\n")
            self._add_event(f"[{_OK}]✔[/] goal completed", tag="AGT")
            self._repaint_panel("panel-agent")

        elif event == "goal_failed":
            error = msg.data.get("error", "")
            self._state.current_goal = ""
            chat = self.query_one("#transcript", RichLog)
            chat.write(f"[white on red] ✖ FAILED [/] [{_DIM}]{error[:80]}[/]\n")
            self._add_event("[red]✖[/] goal failed", tag="AGT")
            self._repaint_panel("panel-agent")

        elif event == "user_message":
            ch = msg.data.get("channel", "?")
            content = msg.data.get("content", "")
            if ch != "cli" and content:
                chat = self.query_one("#transcript", RichLog)
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
                chat = self.query_one("#transcript", RichLog)
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

            chat = self.query_one("#transcript", RichLog)
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
        chat = self.query_one("#transcript", RichLog)
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

        self._repaint_all()

    def _add_event(self, line: str, tag: str = "   ") -> None:
        """Push an inline event to the transcript.

        Old behaviour: wrote to a separate '#events' RichLog pane that
        showed a small ticker independently of the chat. Created a
        cognitive break — when the agent ran a tool, the user had to
        glance to a different pane to see what happened.

        New behaviour: events flow into the same '#transcript' as
        normal chat, with a small grey timestamp + tag prefix so the
        eye can still skip them. Tool calls and results render as
        indented rows under the user message that triggered them; the
        transcript becomes a single readable story instead of a
        chat-on-the-left, ticker-on-the-right split."""
        ts = _time.strftime("%H:%M:%S")
        entry = f"[{_DIM}]{ts}[/]  [{_ACCENT}]{tag:<3}[/]  {line}"
        # Keep the deque so any future view that wants the recent-event
        # history (a /events overlay, a digest "since you were away"
        # block) can grab it cheaply.
        self._state.events.appendleft(entry)
        try:
            self.query_one("#transcript", RichLog).write(entry)
        except Exception:
            pass

    def _render_digest(self) -> None:
        """Render the home-view digest as the first thing the user sees.

        Designed to make EloPhanto feel like a creature you're checking
        in on rather than a chat client you're starting fresh. The
        digest has four bands (any of which can be empty and will
        gracefully drop):

          1. Doing now — current goal, running swarm tasks, scheduled
             tasks counts. Pulled from `_State` directly.
          2. Pending attention — approval requests, stalled questions.
          3. Recent activity — last few events from `_State.events`,
             which are populated by the gateway's event stream as
             the dashboard runs. Empty on first connect (we haven't
             seen any events yet) and that's fine.
          4. Hints — what to type to dig deeper.

        Re-rendered on `_repaint_all` so the digest stays current as
        long as the user hasn't scrolled past it. Once they start
        chatting, new transcript items push it up and out of view.
        """
        s = self._state
        try:
            transcript = self.query_one("#transcript", RichLog)
        except Exception:
            return

        # ── Header line — brand + session uptime ─────────────────────
        elapsed = s.session_elapsed()
        transcript.write(
            f"[{_MIND}]◆[/] [{_BRIGHT}]EloPhanto[/]  "
            f"[{_DIM}]up {elapsed}[/]  "
            f"[{_DIM}]port {s.gateway_port}[/]"
        )
        transcript.write("")

        # ── Doing now ────────────────────────────────────────────────
        doing_lines: list[str] = []
        if s.current_goal:
            chk = s.checkpoints_done
            doing_lines.append(
                f"  [{_ACCENT}]◆[/] goal · [{_BRIGHT}]{s.current_goal[:50]}[/]"
                + (f"  [{_DIM}]· {chk} checkpoints[/]" if chk else "")
            )
        for task in s.swarm_tasks:
            if task.get("status") == "running":
                name = task.get("name", "")[:35]
                agent = task.get("agent", "")
                doing_lines.append(
                    f"  [{_ACCENT}]⚡[/] swarm · [{_BRIGHT}]{name}[/]  [{_DIM}]({agent})[/]"
                )
        if s.scheduled_tasks:
            n = len(s.scheduled_tasks)
            next_eta = min(
                (t.get("eta_secs", 99999) for t in s.scheduled_tasks),
                default=0,
            )
            eta_str = (
                f"{next_eta // 60}m" if next_eta < 3600 else f"{next_eta // 3600}h"
            )
            doing_lines.append(
                f"  [{_ACCENT}]⏱[/] [{_BRIGHT}]{n}[/] [{_DIM}]scheduled · next in {eta_str}[/]"
            )
        if doing_lines:
            transcript.write(f"[{_DIM}]Doing now[/]")
            for line in doing_lines:
                transcript.write(line)
            transcript.write("")

        # ── Pending attention ────────────────────────────────────────
        # The dashboard tracks a single live approval via
        # `_approval_pending`; richer pending-state collation would
        # need a gateway-side query, deferred to a follow-up.
        if self._approval_pending is not None:
            tool_name = (self._approval_pending.data.get("tool") or "")[:30]
            transcript.write(f"[{_DIM}]Wanted your eyes on[/]")
            transcript.write(
                f"  [{_WARN}]![/] approval pending · "
                f"[{_BRIGHT}]{tool_name}[/]  [{_DIM}](type 'a' to approve, 'd' to deny)[/]"
            )
            transcript.write("")

        # ── Recent activity ──────────────────────────────────────────
        # Populated by the event stream after connect. On a fresh boot
        # this is empty; on an in-session reconnect (dashboard restart
        # while gateway keeps running) we'll have real history.
        if s.events:
            transcript.write(f"[{_DIM}]Recent activity[/]")
            for entry in list(s.events)[:5]:
                transcript.write(f"  {entry}")
            transcript.write("")

        # ── Idle hint when nothing else surfaced ─────────────────────
        if not doing_lines and not s.events and self._approval_pending is None:
            transcript.write(
                f"[{_DIM}]Idle. Tell me what you want to work on, or just say hi.[/]"
            )
            transcript.write("")

        # Visual separator before the chat begins.
        transcript.write(f"[{_DIM}]{'─' * 60}[/]")
        transcript.write("")

    def _repaint_panel(self, panel_id: str) -> None:
        """Legacy entry point — used to repaint a sidebar panel by id.
        The new layout has no sidebar; status-bar refresh is centralised
        in `_repaint_all`. Kept as a no-op so existing call sites
        (event handlers across this file) don't need a sweeping
        refactor for what's effectively a panel rename."""
        # Most call sites are followed by other state mutations whose
        # effects show up via the status-bar repaint anyway, so the
        # no-op is safe.
        del panel_id

    def _repaint_header(self) -> None:
        """Legacy entry point — header used to be a 2-row banner at the
        top of the screen. Now lives compressed in the status bar at
        the bottom. Routes to _repaint_all so any caller that still
        wants 'refresh chrome' gets the right thing."""
        self._repaint_all()

    def _repaint_all(self) -> None:
        """Refresh the status bar. Called from event handlers whenever
        state changes that the bar should reflect (budget tick, mode
        change, session join/leave, schedule fire, etc.)."""
        try:
            self.query_one("#status-bar", _StatusBar).repaint()
        except Exception:
            pass

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
