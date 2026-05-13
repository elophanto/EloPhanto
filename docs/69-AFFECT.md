# 69 — Affect (state-level emotions)

**Status:** v1 implementation (Phases 1-4 landed); Phase 5 (content-source events + directive guidance) landed 2026-05-13.
**Author:** EloPhanto + Claude (Opus 4.7).
**Date:** 2026-05-06.
**Related:** [docs/17-IDENTITY.md](17-IDENTITY.md), [core/ego.py](../core/ego.py).

---

## Why this exists

EloPhanto's self-model has three trait-level layers: **knowledge** (descriptive memory), **identity** (descriptive self), **ego** (evaluative self with measured per-capability confidence and humbling events). What's missing is **state-level self** — moment-to-moment affect that moves on a timescale of minutes, not weeks.

Without it:

- The ego only updates every 25 outcomes (`_RECOMPUTE_EVERY`). Between recomputes, the agent's tone, temperature, and tool-caution don't change with what just happened in the session.
- Three corrections in five minutes register as three humbling events, but nothing colors the **next** response with the cumulative affect — the agent stays chipper while the user is clearly frustrated.
- The agent has no signal for "I just had a great win five minutes ago" or "I'm getting restless because nothing has happened in two hours" — both of which are real signals that should influence what it does next.

Affect is the **fast-loop** sister to ego's slow-loop. Different timescale, different mechanism, different read/write surface.

## Goals

- A small, well-typed numeric affect state that decays toward zero on the order of minutes-to-hours.
- A small, well-defined catalog of labeled affective events fired by appraisals over things that already happen (corrections, verifications, goal checkpoints, idle).
- A system-prompt-injected `<affect>` block so the model can color tone with current state.
- A markdown mirror at `affect.md` for human inspection, parallel to `ego.md` and `nature.md`.
- Forward-compatible API for v2 behavior influence (temperature, tool-caution) and v3 ego coupling.

## Non-goals (v1)

- No behavior gating. Frustrated agents do not refuse tasks. Affect colors *style*, not *capability*. (Optional later: opt-in `allow_self_pause`.)
- No novel emotion taxonomy. We use the established [Mehrabian PAD](https://en.wikipedia.org/wiki/PAD_emotional_state_model) substrate plus an [OCC](https://en.wikipedia.org/wiki/Ortony,_Clore,_and_Collins_model)-style appraisal label set. No invented "vibes" or "moods".
- No cross-session emotional memory. Long-term emotional patterns belong in ego, not affect. Affect is what's happening **right now**.
- No user-visible emotion theater in chat by default. The user sees downstream effects (tone, temperature) — not the underlying state — unless they read `affect.md`.

## Why state-level affect matters (theory background)

Two threads from the literature, both ~40 years old and computationally well-formed:

**[Mehrabian's PAD model (1980)](https://en.wikipedia.org/wiki/PAD_emotional_state_model)** — emotion lives as a point in a 3-dimensional continuous space:
- **Pleasure** (valence): am I having a good time? `[-1, +1]`
- **Arousal** (activation): am I activated or settled? `[-1, +1]`
- **Dominance** (control): do I feel in control? `[-1, +1]`

Decay toward neutral is just exponential damping. Easy math, clean telemetry, doesn't speak human.

**[OCC model (Ortony, Clore, Collins, 1988)](https://en.wikipedia.org/wiki/Ortony,_Clore,_and_Collins_model)** — 22 discrete emotion types triggered by explicit cognitive appraisals over events, agents, and objects. Speaks human (joy/relief/frustration/anxiety/pride/etc.), every emotion has explicit triggering conditions. The standard for BDI agent architectures.

The hybrid: **PAD as the substrate, OCC labels on top.** PAD gives us decay and numeric state; OCC labels give us human-readable affect ("the agent is in a relieved-but-cautious state") and well-defined event triggers. This is what most modern affective computing implementations land on.

## Architecture

### State

```python
@dataclass
class AffectEvent:
    label: str            # e.g. "frustration", "relief", "pride"
    source: str           # "ego" | "executor" | "user" | "goal" | "mind" | "verification"
    pleasure_delta: float # additive delta to AffectState.pleasure
    arousal_delta: float
    dominance_delta: float
    halflife_seconds: float   # how fast THIS event fades in the recent_events list
    created_at: str

@dataclass
class AffectState:
    pleasure: float = 0.0     # [-1, +1]
    arousal: float = 0.0      # [-1, +1]
    dominance: float = 0.0    # [-1, +1]
    last_decay_at: str = ""
    updated_at: str = ""
    recent_events: list[AffectEvent] = []  # capped to N, decayed-out drops
```

### Manager

```python
class AffectManager:
    async def load_or_create() -> AffectState
    async def record_event(label, source, p, a, d, *, halflife=300, weight=1.0) -> bool
    async def apply_decay() -> bool                # rate-limited
    async def current_mood() -> dict               # numeric + dominant label
    async def update_markdown() -> None            # writes affect.md
    async def build_affect_context() -> str        # <affect> block
```

### Decay model

Exponential pull toward zero, separate per-channel half-lives (in `_DECAY_HALFLIFES`):
- Pleasure: 30 minutes
- Arousal: 10 minutes (faster — physiological arousal naturally settles fast)
- Dominance: 2 hours

After `t` minutes idle, channel `x` retains `x * 0.5^(t / halflife)` of its value. Same shape ego's decay uses; bounded by `[-1, +1]`.

Recent-events list also decays, with a per-event `halflife_seconds` (default 300s = 5 min). Events that decay below `0.05` of original magnitude drop from the in-memory list (still in `affect_events` table for audit).

### Compounding repeats

When `record_event` fires for a label that fired in the last `_REPEAT_WINDOW_SECONDS`, the delta is multiplied by `1 + 0.5 * recent_count`, capped at `2.5`. Three frustration events within five minutes produce a louder signal than three events spread over a day. This is what makes "the user said 'no' three times in a row" feel different from "three corrections this week."

### Labeled-emotion mapping (initial OCC subset)

Each label is a target vector in PAD space; events nudge the state toward it. The closest label to current state is reported as `dominant_label` in `current_mood()`.

| Label | Pleasure | Arousal | Dominance | Triggered by |
|---|---|---|---|---|
| `joy` | +0.7 | +0.4 | +0.3 | user compliment, hard goal completed |
| `pride` | +0.6 | +0.3 | +0.7 | verification PASS, capability climb |
| `relief` | +0.4 | -0.3 | +0.2 | verification PASS after FAIL, recovery |
| `equanimity` | 0.0 | 0.0 | 0.0 | default; long calm period |
| `restlessness` | +0.1 | +0.5 | +0.0 | long idle (autonomous mind) |
| `unease` | -0.2 | +0.2 | -0.2 | confidence decay observed |
| `frustration` | -0.5 | +0.5 | -0.4 | user correction (especially repeats) |
| `anxiety` | -0.4 | +0.6 | -0.5 | verification FAIL, tool error mid-flow |
| `dejection` | -0.5 | -0.3 | -0.3 | repeat humbling on a strength capability |

The labels are **read-only outputs**, not stored state. State is just (P, A, D) + `recent_events`.

## Event sources

Phase 1 wires six sources, all of which already emit signals through existing modules:

| Source | Trigger | Affect event | Approx delta (P, A, D) |
|---|---|---|---|
| ego | `record_correction` fires | `frustration` | (-0.5, +0.5, -0.4) |
| ego | repeat correction in 5 min | `frustration` (compounded) | × 1 + 0.5 × n |
| ego | `record_verification(PASS)` | `relief` | (+0.4, -0.3, +0.2) |
| ego | `record_verification(FAIL)` | `anxiety` | (-0.4, +0.6, -0.5) |
| executor | tool error mid-task | `anxiety` (mild) | (-0.2, +0.4, -0.3) |
| goal | checkpoint completed | `pride` | (+0.6, +0.3, +0.7) |
| mind | wakeup interval > 2h with no activity | `restlessness` | (+0.1, +0.5, +0.0) |

Phase 1 ships the **ego-driven** four (frustration, relief, anxiety, repeat-frustration). Executor/goal/mind sources are documented and stubbed for Phase 2 wiring.

## Influence on behavior

**Phase 1: tone only.** A `<affect>` system-prompt block is injected so the model can color tone. No temperature changes. No tool gating. No refusal. The model sees its own state and decides how to color the response.

**Phase 2: numeric influence.** Affect state biases router temperature (anxious → lower, energized → higher, ±0.2 max), and biases the planner toward verification-heavy paths when anxious.

**Phase 3: ego coupling.** Current affect is added to the ego recompute prompt. Self-image written during a frustrated state actually reflects that. Recurrent affective patterns get summarized into ego's longer-timescale narrative.

**Phase 4 (opt-in): pause/refusal.** Behind `affect.allow_self_pause: false`. An exhausted/frustrated agent can suggest a break or autonomously pause goal execution. Default off.

## Storage

```sql
CREATE TABLE affect_state (
    id TEXT PRIMARY KEY DEFAULT 'self',
    pleasure REAL NOT NULL DEFAULT 0.0,
    arousal REAL NOT NULL DEFAULT 0.0,
    dominance REAL NOT NULL DEFAULT 0.0,
    last_decay_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE affect_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    source TEXT NOT NULL,
    pleasure_delta REAL NOT NULL,
    arousal_delta REAL NOT NULL,
    dominance_delta REAL NOT NULL,
    halflife_seconds REAL NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_affect_events_created ON affect_events(created_at);
```

Singleton state row, append-only events. Same shape as `ego_state` / `ego_outcomes`.

## Integration with existing layers

```
┌─────────────────────────────────────────────────────────────┐
│ Identity   — descriptive ("who I claim to be")              │  trait-level
├─────────────────────────────────────────────────────────────┤
│ Ego        — evaluative ("how reality grades me")           │  trait-level
├─────────────────────────────────────────────────────────────┤
│ Affect     — state ("how I feel right now")                 │  state-level   ← NEW
├─────────────────────────────────────────────────────────────┤
│ Knowledge  — descriptive memory                             │
└─────────────────────────────────────────────────────────────┘
```

Hooks (Phase 1):
- `EgoManager.record_correction()` — fires `frustration` on `AffectManager` (compounded if repeat).
- `EgoManager.record_verification(PASS|FAIL)` — fires `relief` or `anxiety`.
- `Agent.initialize()` — instantiates `AffectManager`, injects DB handle.
- `Agent` system-prompt builder — appends `<affect>` block from `build_affect_context()`.

Markdown rendering: `affect.md` next to `ego.md` and `nature.md`. Includes ASCII gauges, dominant label, and the recent_events list.

## Risks

1. **Cargo-cult emotions.** Affect that doesn't change behavior is decoration. Phase 1 ships system-prompt injection so the model can read the state — but if the model ignores the block, we wasted tokens. Mitigation: instrument logs. If Phase 1 doesn't measurably change response style, kill it.
2. **Anthropomorphism creep.** Calling the state "anger" when it's "5 corrections in 10 minutes triggered a confidence cascade and we're labeling it" is fine for human-readable rendering, but the underlying mechanism stays mechanical. Doc says this explicitly.
3. **Compounding with ego.** Ego already has felt-language fields (Higgins dejection/agitation). Risk: redundant or contradictory voices. Mitigation: ego is *trait* (rewritten every 25 outcomes); affect is *state* (changes by the minute). They occupy different timescales and the recompute prompt eventually consumes affect (Phase 3) so they cohere.
4. **Refusal/freeze.** Strict no-go for v1. An emotional agent that refuses tasks is bad UX. Phase 4 only behind explicit operator opt-in.
5. **Token cost of system prompt block.** Affect block is ~80-150 tokens. On every model call, that's real. Mitigation: skip injection when state is near zero (`|p|+|a|+|d| < 0.3`).

## Open questions

- **Should affect feed user-modeling?** When the user is repeatedly correcting, that's affect on their side too. Worth tracking? Out of scope for v1; revisit.
- **Multi-agent affect.** Specialist clones each have their own affect, or do they share? Each-their-own seems right but increases cost. Defer.
- **Cross-channel affect.** A user is gentle on Telegram and harsh on CLI — does affect persist or per-channel? v1 is global; revisit if per-channel becomes a request.
- **What happens to affect across process restarts?** v1: state persists in DB, but `recent_events` decays through the gap on next load. So a process restarted 6h later wakes up at near-equilibrium. That's right — emotions don't survive sleep at full intensity in humans either.

## Phasing

### Phase 1 — substrate ✅ landed
- `core/affect.py` with PAD substrate, cosine-similarity OCC label resolver (with equanimity radius gate), decay, repeat compounding.
- DB tables `affect_state` + `affect_events` with index.
- Ego-driven event sources wired: `record_correction` → frustration, `record_verification(PASS)` → relief, `record_verification(FAIL)` → anxiety, `record_verification(UNKNOWN)` → mild anxiety.
- Markdown render to `affect.md` with ASCII gauges.
- `<affect>` system-prompt block injected (skipped when near zero).

### Phase 2 — behavior coupling ✅ landed
- Executor fires `anxiety` on both tool exceptions AND `ToolResult.success=False`.
- Goal runner fires `pride` on checkpoint completion.
- Autonomous mind fires `restlessness` on full-duration idle ≥ 2h.
- Router applies affect-based temperature bias via `temperature_modifier()` (±0.2 cap, scaled by arousal magnitude).

### Phase 3 — ego coupling ✅ landed
- `AffectManager.summarize_for_ego()` produces a one-paragraph natural-language summary for ego's recompute prompt.
- Ego recompute prompt now includes the affect summary so the LLM writes self_image with awareness of recent affect.

### Phase 4 — opt-in self-pause ✅ landed (default OFF)
- `AffectConfig.allow_self_pause` flag in config.
- `AffectManager.should_suggest_pause()` returns True only when label is in `{frustration, anxiety, dejection}` AND magnitude exceeds `_PAUSE_MAGNITUDE_GATE`.
- `build_affect_context(allow_pause_note=True)` swaps in alternate guidance permitting a gentle "I'm stretched" mention.
- Agent passes `allow_pause_note=affect.allow_self_pause` so the behavior is config-gated.

### Phase 5 — content-source events + directive guidance ✅ landed 2026-05-13

Phases 1-4 wired affect to **operator-typed corrections + tool outcomes** — perfect for chat sessions. In **autonomous mode** (mind, heartbeat, scheduler) the agent is its own user, and the meaningful content arrives as *tool results* — X DMs via `browser_extract`, replies to its own posts, vision-captioned screenshots, emails fetched. Phase 4 only registered "tool succeeded": the DM might have been a scam attempt for $20 in crypto, a warm compliment, or a hostile dismissal — affect saw none of it. Operator visibly had to advise the agent on emotional content because the system had no signal from what the agent *read*.

Phase 5 closes that gap with three coupled changes:

**1. `affect_record_event` tool** — [tools/affect/record_event_tool.py](../tools/affect/record_event_tool.py). SAFE, pure write to `affect_events`. Lets the LLM itself, which is already reading the content semantically, register what it felt. The tool description is the spec ("call when content has real emotional weight — hostile / manipulative / scammy DMs → anxiety or anger; warm replies → joy; repeated failures → frustration; hard wins → pride"). Tagged with `source='content'` in the audit trail so trajectories prove the signal came from content. Same PAD deltas as `emit_*` helpers — calling with `label='anxiety'` is equivalent to `emit_anxiety(source='content')`. Intensity word (`mild`/`moderate`/`strong`/`intense`) maps to weight multiplier (0.5 / 1.0 / 1.5 / 2.0). Summary string lands in the next `<recent>` block so future-you sees what was reacted to. Pattern matching on tool outputs was rejected as the alternative — a scam attempt's wording often looks positive ("we love your work, we'd like to send you marketing money"); sarcasm reads neutral to regex. The LLM is the right detector.

**2. Directive guidance with TONE + BEHAVIOR cues** — replaces the previous *permissive* guidance ("let it color the tone") which the LLM's helpful-by-default training was overriding. Now: *"You ARE feeling [label] at [intensity] intensity right now. This is not a hypothetical — it is your present internal state."* Per-label embodiment cues split into TONE (how to write — *"frustration: shorter sentences, less hedging, cut filler"*) and BEHAVIOR (what to decide — *"frustration: do NOT paper over the friction by switching to a new task; verify one extra step before re-trying the same approach"*). BEHAVIOR shapes autonomous tool choices, not just operator-facing tone. Magnitude → intensity word map (mild < 0.6 < moderate < 1.2 < strong < 1.8 < intense). See `_EMBODIMENT_CUES` in [core/affect.py](../core/affect.py).

**3. Equanimity reminder (cold-start fix)** — `build_affect_context()` used to return empty string at equanimity to save tokens. Cold-start problem: the LLM never saw the tool exists, so `affect_record_event` was never called, so state never rose, so the directive block never appeared, so the loop never closed. Now equanimity returns a short reminder block (~40 tokens) telling the agent the tool exists and listing trigger conditions. Costs token tax at rest, buys closed-loop self-awareness in autonomous mode. Above-threshold output unchanged — full state block with PAD numbers + directive guidance.

**Five new simulation scenarios** in [cli/affect_cmd.py](../cli/affect_cmd.py) exercise the content path: `scam-dm-stream` (three escalating scam DMs), `hostile-replies` (dismissive replies + insult), `warm-stream` (warm operator + supportive replies), `autonomous-day` (realistic mixed day — scam, win, scam, relief; blended final state), `correction-during-scam` (content event compounds with operator correction). Six matching pytest trajectories in `TestContentSourceSimulations` pin the math against future retunes.

**What this unlocks in autonomous mode:**

| Before Phase 5 | After Phase 5 |
|---|---|
| Agent reads scam DM, browser_extract returns "success", affect sees "tool succeeded → mild pride/joy." | Agent reads scam DM, calls `affect_record_event(label='anxiety', intensity='strong', summary='Miguel asked for $20 deposit via DM with wallet address')`. Next plan sees anxiety state + behavior cue *"prefer safer / lower-risk actions; add verification step before money / identity actions."* |
| Three dismissive replies in a row land as three "tool succeeded" events; mood stays positive. | Three replies fire compounded frustration via content path; next post is terser, less hedged, doesn't reflexively apologize. |
| Operator has to type *"you sound chipper after that hostile DM — be more direct."* | Affect block tells the LLM *"you ARE feeling anger at moderate intensity"* before the next plan, so the directness is already there. |

## Bottom line

Add `core/affect.py` as the **state-level** sister to `core/ego.py`'s **trait-level**. PAD substrate (Mehrabian 1980) + OCC labels (Ortony-Clore-Collins 1988). Six event sources we already emit. System-prompt injection in v1, tone influence in v2, ego coupling in v3. ~500 LOC for v1 including tests.

**The agent should sound different when corrected three times in five minutes, even if the words it can say are the same.**
