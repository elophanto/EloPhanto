# EloPhanto — Terminal Dashboard

Inspired by [Hyperspace AGI](https://github.com/hyperspaceai/agi)'s dense multi-panel TUI, this is the full-screen terminal dashboard for EloPhanto. It surfaces all autonomous activity in real time alongside the chat REPL.

**Status: implemented** — `cli/dashboard/app.py` (Textual). Launches automatically when the terminal supports it; falls back to linear mode otherwise. Pass `--no-dashboard` to force linear mode.

---

## The Problem with the Current Terminal

EloPhanto is a genuinely autonomous agent. It runs mind cycles, heartbeat tasks, swarm sub-agents, scheduled jobs, and webhook-triggered tasks — all while the user is (or isn't) typing. None of this is visible in the current terminal. The user sees a linear chat scroll. Everything else is invisible unless it happens to print a line.

**What a user cannot see today:**
- Whether the mind is actively running, sleeping, or paused
- Which tool the agent is using right now
- Budget consumed vs. daily limit
- Active swarm agents and their progress
- Next scheduled task and its ETA
- Gateway sessions (Telegram connected? Discord alive?)
- Heartbeat cycle status
- LLM provider health (is OpenRouter responding slowly?)

A richer terminal doesn't just look good — it makes the agent legible.

---

## Design Goals

1. **Information density without clutter** — every visible element is actionable context
2. **Works at 80 cols** (minimum), looks best at 120–140 cols
3. **Chat remains primary** — panels are sidebars/headers, not replacements
4. **Zero input latency** — panels update async; input REPL is never blocked
5. **Graceful degradation** — narrow terminals fall back to the existing linear mode
6. **No new heavy dependencies** — use Textual (same ecosystem as Rich, already a dep candidate) or Rich Live

---

## Layout

```
┌─ EloPhanto ◆ ──── session: 2h14m ─── budget: $2.10/$100 ─── 3 sessions ──────────────────────────────┐
│ ● openrouter  ● zai  ○ kimi  ● ollama        cycle #14 · 09:42        mode: full_auto                 │
├────────────────────────────────────┬───────────────────────────────────────────────────────────────────┤
│  AGENT                             │  CHAT                                                             │
│  ● Researching Hacker News         │                                                                   │
│    tool: browser_navigate [12s]    │  You   Search for recent AI papers on arxiv                      │
│    goal: 1 active · 3 done         │                                                                   │
│    turns: 47 · tokens: 84k         │  EloPhanto                                                        │
│                                    │  ┌─────────────────────────────────────────────────────────────┐ │
│  MIND                              │  │ Found 12 papers from the last 48 hours. Top picks:          │ │
│  ● cycle #14 · sleeping 18m        │  │ 1. "Scaling Synthetic Data..." (DeepMind, 847 citations)    │ │
│    last: checked Commune feed      │  │ 2. "MoE Routing at Scale..." (Meta, 623 citations)          │ │
│    next wakeup: 09:59              │  └─────────────────────────────────────────────────────────────┘ │
│    budget: 18% of daily            │                                                                   │
│                                    │  You   summarise the first one                                   │
│  SWARM                             │                                                                   │
│  ● fix-auth-bug    claude    45%   │  EloPhanto  ◆ thinking...                                        │
│    ○ write-tests   claude     0%   │                                                                   │
│    ✓ update-docs   claude   100%   │                                                                   │
│                                    │                                                                   │
│  SCHEDULER                         │                                                                   │
│  ○ daily-summary   in  2h 14m      │                                                                   │
│  ○ commune-sync    in    42m       │                                                                   │
│  ✓ arxiv-check     done  09:15     │                                                                   │
│                                    │                                                                   │
│  GATEWAY                           │                                                                   │
│  ● cli (you)  ● telegram  ○ slack  │                                                                   │
│  3 sessions · 0 pending            │                                                                   │
├────────────────────────────────────┴───────────────────────────────────────────────────────────────────┤
│  EVENTS  ·  09:43 heartbeat_idle — nothing to do                                                      │
│           ·  09:42 tool: browser_navigate → github.com (234ms)                                        │
│           ·  09:41 mind cycle #14 started — budget $0.04                                              │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  ❯ _                                                                                                   │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Zones

| Zone | Content | Update rate |
|------|---------|-------------|
| **Header bar** | Logo, session duration, budget, session count, provider dots, mind cycle, mode | 5s |
| **Left sidebar** | AGENT · MIND · SWARM · SCHEDULER · GATEWAY panels | On event |
| **Chat area** | Scrollable conversation history + in-progress streaming | Streaming |
| **Event feed** | Last 3 gateway events (tool calls, heartbeat, webhooks) | On event |
| **Input line** | prompt_toolkit REPL | Always live |

---

## Panel Breakdown

### Header Bar

```
◆ EloPhanto  session: 2h14m  budget: $2.10/$100.00 [██░░░░░░░░]  3 sessions  cycle #14 · 09:42  full_auto
● openrouter (842ms)   ● zai (340ms)   ○ kimi (disabled)   ● ollama (local)
```

- Budget bar fills left-to-right; turns yellow at 80%, red at 95%
- Provider dots: green=healthy, yellow=degraded, grey=disabled
- Latency in parentheses: rolling average of last 5 calls per provider
- Mind cycle counter + wall-clock time of last wakeup

### AGENT Panel

```
AGENT ──────────────────────────
● browser_navigate           12s
  └─ goal: Research HN posts
  turns: 47  tokens: 84k  cost: $0.31
  ✓ 3 checkpoints done · 1 active
```

- Live tool spinner with elapsed time
- Current goal name + checkpoint progress
- Running totals for the session (turns, tokens, cost)
- Idle state: `◆ ready — waiting for input`

### MIND Panel

```
MIND ───────────────────────────
● sleeping · wakes in 18m
  last: checked Commune feed
  cycles today: 14 · cost: $1.20
  budget: 18% of daily
```

- States: `● running`, `● sleeping · wakes in Xm`, `○ paused`, `○ disabled`
- Last action summary (single line)
- Daily cycle count + cost attribution

### SWARM Panel

```
SWARM ──────────────────────────
● fix-auth-bug    claude  [████░]  45%
○ write-tests     claude  [░░░░░]   0%  queued
✓ update-docs     claude  [█████] done
```

- One row per active/recent swarm agent
- Progress bar driven by `done_criteria` (pr_created = 100% on PR open)
- States: `●` running, `○` queued, `✓` done, `✗` failed

### SCHEDULER Panel

```
SCHEDULER ──────────────────────
○ daily-summary   in  2h 14m   cron
○ commune-sync    in    42m    interval
✓ arxiv-check     09:15        done
```

- Next 3 upcoming tasks with ETA
- Completed tasks shown dimmed for context

### GATEWAY Panel

```
GATEWAY ────────────────────────
● cli        (you)   active
● telegram   @user1  active · 2 msgs
○ slack               not connected
3 sessions · port 18789
```

### Event Feed

Scrolling single-line stream of the last N gateway events, newest at top:

```
EVENTS
09:43  heartbeat_idle — nothing to do
09:42  tool: browser_navigate → github.com (234ms)
09:41  mind cycle #14 started — $0.04
09:38  webhook: POST /hooks/wake (telegram trigger)
09:35  tool: knowledge_search "arxiv papers" → 8 results (89ms)
```

---

## Implementation Plan

### Phase 1 — Textual App shell

Replace the current `channels/cli_adapter.py` REPL with a [Textual](https://github.com/Textualize/textual) app.

Textual is from the Textualize team (same as Rich), is async-native, and supports split-panel layouts with reactive widgets that update without re-rendering the whole screen.

**New files:**
- `cli/dashboard/app.py` — `class EloPhantoDashboard(App)`
- `cli/dashboard/widgets/` — one file per panel widget
- `cli/dashboard/state.py` — shared reactive state (current tool, budget, mind status, swarm list)

**Existing files changed:**
- `channels/cli_adapter.py` — launch `EloPhantoDashboard` instead of bare REPL when terminal supports it
- `cli/gateway_cmd.py` — detect terminal capability; fall back to current linear mode if `TERM=dumb` or `--no-dashboard` flag

### Phase 2 — State bridge

A `DashboardState` dataclass holds all panel data. Gateway events (tool calls, mind cycles, heartbeat, swarm status, scheduler ticks) update it. Textual's reactive system propagates diffs to widgets.

```python
@dataclass
class DashboardState:
    session_start: float
    budget_used: float
    budget_limit: float
    provider_health: dict[str, ProviderStatus]
    current_tool: str | None
    current_tool_elapsed: float
    mind_state: str          # running | sleeping | paused | disabled
    mind_next_wakeup: float | None
    mind_cycles_today: int
    mind_cost_today: float
    swarm_tasks: list[SwarmTask]
    scheduled_tasks: list[ScheduledTask]
    gateway_sessions: list[SessionInfo]
    events: deque[EventLine]   # maxlen=100
```

The CLI adapter subscribes to gateway events and calls `state.update(event)`. Textual's `watch_*` reactive triggers redraw.

### Phase 3 — Fallback

When `--no-dashboard` is passed or the terminal is too narrow (<80 cols) or dumb (`TERM=dumb`, CI, no TTY), the app falls back to the current linear Rich output — no dashboard, no behaviour change.

```python
def should_use_dashboard() -> bool:
    import shutil, os
    if not sys.stdout.isatty(): return False
    if os.environ.get("TERM") == "dumb": return False
    if shutil.get_terminal_size().columns < 80: return False
    return True
```

---

## Key Inspirations from Hyperspace AGI

| Hyperspace feature | EloPhanto equivalent |
|---|---|
| RESEARCH panel with ML loss + NDCG | AGENT panel with goal progress + checkpoint count |
| SWARM panel with knapsack/TSP progress bars | SWARM panel with claude-code agent progress |
| NETWORK FEED with peer connect/disconnect | EVENT FEED with gateway events, tool calls |
| DAG tree view (303 nodes, depth 7) | Goal tree view (active goal → checkpoints → tool calls) |
| Header: peers · pts · T0 · 0.6h · status | Header: sessions · budget · cycle# · time · mode |
| WARPS with config % | SCHEDULER with ETA countdowns |
| MODELS & COMPUTE (hardware info) | Provider health dots with latency |

---

## What to Build First

1. **Event feed only** (low effort, high value) — add a scrolling event log to the bottom of the current terminal, below the chat. No layout changes needed. This alone makes the agent's background activity visible.

2. **Header bar** — single line above the prompt with budget + mind status + provider dots. Printable in the existing Rich console.

3. **Full Textual app** — full layout as designed above. Opt-in behind `--dashboard` flag initially.

---

## Color Palette

The dashboard uses exact hex approximations of the web app's `web/src/globals.css` dark-mode oklch tokens:

| Token | Hex | oklch source | Role |
|-------|-----|-------------|------|
| `_BG` | `#0d0e14` | `oklch(0.095 0.005 260)` | Screen background — deep cool charcoal |
| `_SURFACE` | `#111218` | `oklch(0.12 0.006 260)` | Sidebar / cards |
| `_RAISED` | `#161820` | `oklch(0.16 0.006 260)` | Header / input bar |
| `_BORDER` | `#1e2030` | `oklch(1 0 0 / 8%)` | Dividers |
| `_BRIGHT` | `#dbd7cc` | `oklch(0.88 0.008 80)` | Text primary — warm off-white |
| `_DIM` | `#71728a` | `oklch(0.5 0.01 260)` | Text muted — cool grey |
| `_MIND` | `#8b5cf6` | brand accent | Electric purple (thinking spinner, header ◆, agent name) |
| `_ACCENT` | `#a78bfa` | brand accent hover | Violet-400 (scheduler names, channel badges) |
| `_OK` | `#22c55e` | brand success | Green (connected, done, healthy) |
| `_WARN` | `#f59e0b` | brand warning | Amber (degraded, approval needed) |

The background is intentionally **not** pure black — the `260°` hue gives it the cinematic cool-blue depth of the web app's "ex machina" dark mode.

## Thinking Indicator

When the agent is processing a message, a one-line animated spinner appears between the event feed and the input bar:

```
⠹ thinking...
```

Implementation: `_animate_thinking()` is a `@work(exclusive=True, group="thinking-anim")` Textual worker that cycles through the braille frames `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` at 100ms intervals. The `#thinking` widget is hidden (`display: none`) by default and shown via an `.active` CSS class while `_awaiting_response = True`. It auto-hides when the response arrives, times out, or the user presses Ctrl+X.

## Dependencies

| Dep | Version | Notes |
|-----|---------|-------|
| `textual` | `>=0.70` | MIT. Textualize. Async-native, Rich-compatible. `uv add textual` |
| `prompt_toolkit` | `>=3.0` | Already added in Phase 16. Textual has its own input handling — check compatibility |

Textual and prompt_toolkit both want to own stdin. In Textual mode, prompt_toolkit is not used — Textual handles the input line natively. In fallback (non-dashboard) mode, prompt_toolkit continues as-is.

---

## Open Questions

1. **Goal tree depth** — how deep should the AGENT panel show the goal/checkpoint/tool hierarchy? Probably 2 levels (goal → current checkpoint). Full DAG is overkill for a terminal sidebar.

2. **Swarm progress heuristic** — swarm agents are external processes. Progress bar today can only be 0% (running) or 100% (done). A future enhancement: stream stdout from the tmux pane to estimate progress.

3. **Dashboard state persistence** — if the user closes and reopens the terminal, should the dashboard restore last-known state from the DB? Probably yes for swarm + scheduler; not needed for current tool/mind.

4. **Wide vs. narrow layout** — at 80 cols the sidebar collapses and only the header + event feed are shown. At 120+ cols the full layout renders. Textual handles this with responsive CSS-like rules.
