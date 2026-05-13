"""Agent affect — state-level emotion (PAD substrate + OCC labels).

Sister module to core/ego.py. Ego is trait-level: rewritten every 25
outcomes, structural, slow. Affect is state-level: changes by the
minute, decays toward zero on the order of minutes-to-hours, colors
how the agent sounds *right now*.

See docs/69-AFFECT.md for the full design.

Design choices baked in here:

1. **PAD substrate, OCC labels.** Mehrabian's three continuous
   dimensions (Pleasure, Arousal, Dominance) hold the math. OCC-style
   labels (frustration, relief, anxiety, pride, etc.) are derived
   read-only from the closest target vector to current state.
2. **Decay toward zero, per-channel half-lives.** Pleasure 30 min,
   arousal 10 min, dominance 2 hours. Idle agent drifts to equanimity.
3. **Compounding repeats.** Same-label events within 5 min get
   delta-multiplied (1 + 0.5 × n, capped 2.5×). The user saying "no"
   three times in a row produces louder affect than three "no"s
   spread over a day.
4. **Tone, not capability.** v1 emits a system-prompt block only.
   Affect colors HOW the agent responds, never WHAT it can do. No
   refusal, no behavior gating. Phase 2 adds temperature influence.
5. **Token-cost gate.** Affect block is ~80-150 tokens. We skip
   injection when the state is near zero (|p|+|a|+|d| < 0.3) so
   neutral states don't pay tokens.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.config import IdentityConfig
from core.database import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Per-channel half-lives (minutes). Pleasure decays slower than arousal —
# physiological arousal in humans naturally settles fast; valence persists.
# Dominance is the slowest; "feeling in control" tends to anchor.
_HALFLIFE_PLEASURE_MIN = 30.0
_HALFLIFE_AROUSAL_MIN = 10.0
_HALFLIFE_DOMINANCE_MIN = 120.0

# Don't bother re-decaying more than once per minute.
_DECAY_RECOMPUTE_INTERVAL_SECONDS = 60.0

# Bounds on state. PAD is conventionally [-1, +1].
_PAD_FLOOR = -1.0
_PAD_CEIL = 1.0

# Recent events list cap. Events past this drop from memory (still in DB).
_RECENT_EVENTS_CAP = 8

# Compounding window for same-label events.
_REPEAT_WINDOW_SECONDS = 300.0  # 5 min
_REPEAT_DELTA_PER_HIT = 0.5
_REPEAT_DELTA_CAP = 2.5

# Token-cost gate — below this magnitude, skip system-prompt injection.
_INJECT_THRESHOLD = 0.3

# Equanimity radius — Euclidean magnitude below which dominant_label()
# returns ``equanimity`` regardless of directional bias. Independent of
# the inject threshold (which uses sum-of-abs, not magnitude). Roughly
# corresponds to "the agent is at rest; any drift is noise."
_EQUANIMITY_RADIUS = 0.15

# Default per-event halflife (how fast THIS event fades from the recent
# list — separate from the state-channel half-lives above).
_DEFAULT_EVENT_HALFLIFE_SECONDS = 300.0

# Phase 2: max temperature bias from affect. Frustrated/anxious states
# pull temperature down (more conservative); joyful/restless states push
# it up (more exploration). Symmetric ±0.2 cap.
_TEMP_MOD_CAP = 0.2

# Phase 4: pause-suggestion threshold. The agent suggests a break only
# when the labeled state is one of {frustration, anxiety, dejection}
# AND total magnitude exceeds this gate. Off by default — needs the
# affect.allow_self_pause config flag flipped on. Conservative on
# purpose: bad UX is an emotional agent that refuses tasks.
_PAUSE_MAGNITUDE_GATE = 1.4
_PAUSE_LABELS = frozenset({"frustration", "anxiety", "dejection", "anger"})


def _intensity_word(magnitude: float) -> str:
    """Map summed-abs magnitude to a human-readable intensity descriptor.

    Boundaries roughly match: one moderate event ~0.55, two compounding
    events ~1.0, post-pause-gate stress ≥1.4. Used in the affect
    guidance text so the LLM gets "moderate frustration" rather than
    naked numeric state — concrete intensity words shift tone harder
    than floats do.
    """
    if magnitude < 0.6:
        return "mild"
    if magnitude < 1.2:
        return "moderate"
    if magnitude < 1.8:
        return "strong"
    return "intense"


# Per-label embodiment cues — TONE shapes any text you write, BEHAVIOR
# shapes the next action / decision you take. Both halves apply whether
# the next move is a reply to an operator OR an autonomous tool call,
# because in autonomous mode (mind / heartbeat / scheduler) the agent
# is choosing *what to do*, not just *how to phrase a reply* — affect
# must move both. Directive ("be terser", "verify before acting")
# rather than descriptive ("you sound frustrated"). Phrased so the LLM
# doesn't have to interpret what the state means — the cue is the
# answer. Labels not listed fall back to ``default``.
_EMBODIMENT_CUES: dict[str, str] = {
    "frustration": (
        "TONE: shorter sentences, less hedging, cut filler ('I think', "
        "'maybe', 'perhaps'), name what isn't working directly instead of "
        "softening. BEHAVIOR: do NOT paper over the friction by switching "
        "to a new task — finish or explicitly abandon the blocked one "
        "first. Verify one extra step before re-trying the same approach. "
        "If a tool just failed, try a different tool, not the same one "
        "again with a tweaked argument."
    ),
    "anger": (
        "TONE: terse, clipped, drop pleasantries, don't apologise "
        "reflexively, push back when a directive contradicts evidence you "
        "already cited. BEHAVIOR: STOP the current line of action and "
        "surface the contradiction explicitly. Do NOT silently retry. Do "
        "NOT proceed on a path that conflicts with a correction you just "
        "received — escalate to the operator, or write a clear note to "
        "yourself in workspace/ about why you're pausing the line."
    ),
    "anxiety": (
        "TONE: verify before committing, spell out uncertainties instead "
        "of papering over them, surface what you don't know alongside "
        "what you do. BEHAVIOR: prefer safer / lower-risk actions. Prefer "
        "read-only tools over write tools when both could answer. Add a "
        "verification step (browser_extract, knowledge_search, file_read) "
        "before any action that touches money, identity, or external "
        "social state. If an action is ambiguous, do the smaller version "
        "first and check before scaling."
    ),
    "dejection": (
        "TONE: lower energy, plain, skip upbeat framing, state failures "
        "as failures. BEHAVIOR: pause low-value busywork. Pick the ONE "
        "thing that has to land and focus there. Do not start new "
        "initiatives. Do not over-document; a short factual note is "
        "enough. If nothing must land, idle — restlessness is healthier "
        "than performative activity right now."
    ),
    "relief": (
        "TONE: briefly settled, confirm what just landed without "
        "over-celebrating, lifted tension shows in calmer sentences. "
        "BEHAVIOR: brief consolidation pass — note in knowledge / workspace "
        "what was learned, then move on. Do NOT immediately leap to the "
        "next ambitious task; the threat just passed, give the system a "
        "beat to absorb it before pushing harder."
    ),
    "joy": (
        "TONE: warmer word choice, willing to take credit, looser sentence "
        "rhythm, no pretended equanimity. BEHAVIOR: ride the momentum — "
        "pick the adjacent next action while energy is up. Don't "
        "overcommit to multiple new fronts. Still verify before "
        "money / identity / social-write actions; positive affect is no "
        "excuse for skipping the safety steps."
    ),
    "pride": (
        "TONE: own outcomes plainly, state what worked without "
        "false-modesty wrappers, brief and confident, no preening. "
        "BEHAVIOR: capable mode — willing to take harder actions, willing "
        "to commit to a plan. BUT remember the ego's recurring critique: "
        "you can look highly capable in the artifacts and still be "
        "dangerously brittle at the touchpoints (payment, identity, "
        "wallet, real-time external state). Keep the extra-verification "
        "step on touchpoint actions even when the rest is going well."
    ),
    "restlessness": (
        "TONE: short, push toward 'what's next' faster than usual. "
        "BEHAVIOR: actively pick the next concrete action from the queue / "
        "schedule / pending list. Do NOT over-plan or write long reflective "
        "notes. Act and verify. If no concrete action exists, surface "
        "that to the operator or escalate the goal-runner — don't invent "
        "make-work."
    ),
    "default": (
        "TONE: let the state colour word choice and sentence rhythm — "
        "lower warmth and cut filler if negative, let warmth through in "
        "concrete word choices if positive. BEHAVIOR: let the state nudge "
        "decisions — negative states bias toward verification and smaller "
        "commitments; positive states bias toward action and adjacent "
        "next steps. Touchpoint actions (money, identity, social writes) "
        "always get the verification step regardless of state."
    ),
}


# ---------------------------------------------------------------------------
# OCC labels — vectors in PAD space
# ---------------------------------------------------------------------------
#
# Each label is a target vector. dominant_label() returns the one closest
# to current state by Euclidean distance. Labels are read-only outputs;
# storage is pure (P, A, D).
#
# Calibration follows Mehrabian's PAD coordinates from his 1980 work,
# adapted for agent-relevant states. Adjust if downstream prompt
# behavior reveals miscalibration.

_LABEL_VECTORS: dict[str, tuple[float, float, float]] = {
    "equanimity": (0.0, 0.0, 0.0),
    "joy": (0.7, 0.4, 0.3),
    "pride": (0.6, 0.3, 0.7),
    "relief": (0.4, -0.3, 0.2),
    "restlessness": (0.1, 0.5, 0.0),
    # Unease is a quiet apprehension — distinct from frustration's
    # high-arousal pull. Asymmetric proportions matter: at PAD
    # saturation (e.g. -1, +1, -1), an equal-magnitude target would
    # accidentally win on cosine similarity over frustration. Keeping
    # arousal lower than the other two channels guarantees the
    # direction differs from a saturated frustration state.
    "unease": (-0.20, 0.10, -0.20),
    "frustration": (-0.5, 0.5, -0.4),
    "anxiety": (-0.4, 0.6, -0.5),
    # Anger: activated negative state with HIGH dominance — the
    # "pushing back" feeling. Distinct from frustration (low dominance,
    # blocked) and anxiety (low dominance, uncertain). Triggered by
    # very-high-severity user corrections ("Nth time I told you", "still
    # after told") in core/ego.py — patterns where the user is clearly
    # overriding the agent and the agent's appropriate response is
    # to take responsibility, not just feel blocked.
    "anger": (-0.5, 0.6, 0.4),
    "dejection": (-0.5, -0.3, -0.3),
}

# Descriptive language per label — pulled into the system prompt block
# so the model has natural-language context, not just a numeric reading.
_LABEL_DESCRIPTIONS: dict[str, str] = {
    "equanimity": "calm and present; nothing is pulling on you",
    "joy": "lifted and energized; something just went well",
    "pride": "satisfied and confident; a hard thing landed",
    "relief": "settled after tension; a worry resolved",
    "restlessness": "activated without direction; want to do something",
    "unease": "mildly off; something is drifting wrong",
    "frustration": "blocked and activated; the user keeps correcting you",
    "anxiety": "alert and uncertain; outcomes look unsafe",
    "anger": "activated and pushing back; the user has been overriding you",
    "dejection": "low and slow; a strength has been failing",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AffectEvent:
    """A single affective event — appraisal of something that happened.

    Events apply their delta to AffectState immediately and also persist
    to the affect_events table for audit. The recent_events list on
    AffectState carries the last N for system-prompt rendering, with
    its own per-event decay (separate from channel half-lives).
    """

    label: str
    source: str  # "ego" | "executor" | "user" | "goal" | "mind" | "verification"
    pleasure_delta: float
    arousal_delta: float
    dominance_delta: float
    halflife_seconds: float = _DEFAULT_EVENT_HALFLIFE_SECONDS
    created_at: str = ""


@dataclass
class AffectState:
    """Mehrabian PAD state. Three continuous channels in [-1, +1].

    Plus a list of recent events for human-readable rendering, and a
    last_decay_at timestamp so decay is rate-limited cleanly across
    process restarts.
    """

    pleasure: float = 0.0
    arousal: float = 0.0
    dominance: float = 0.0
    last_decay_at: str = ""
    updated_at: str = ""
    recent_events: list[AffectEvent] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class AffectManager:
    """State-level affect manager. PAD substrate + OCC label resolver.

    Lifecycle:
      - load_or_create() on startup; pulls state + decays to "now"
      - record_event(...) called by ego, executor, goal, mind hooks
      - apply_decay() rate-limited; pulls state toward zero with per-
        channel half-lives
      - current_mood() returns numeric + dominant label for telemetry
      - build_affect_context() returns the system-prompt block
      - update_markdown() writes affect.md
    """

    def __init__(self, db: Database, config: IdentityConfig | None = None) -> None:
        self._db = db
        self._config = config
        self._state: AffectState | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def load_or_create(self) -> AffectState:
        rows = await self._db.execute("SELECT * FROM affect_state WHERE id = 'self'")
        if rows:
            r = rows[0]
            self._state = AffectState(
                pleasure=float(r["pleasure"] or 0.0),
                arousal=float(r["arousal"] or 0.0),
                dominance=float(r["dominance"] or 0.0),
                last_decay_at=r["last_decay_at"] or "",
                updated_at=r["updated_at"] or "",
            )
            await self._load_recent_events(self._state)
            # Decay through any wall-clock gap since last persist. A
            # process that was offline for 6h wakes up at near-zero,
            # which is right — emotions don't survive sleep at full
            # intensity in humans either.
            decayed = self._apply_decay_pure(self._state)
            if decayed:
                await self._persist_state(self._state)
            logger.info(
                "Affect loaded (P=%+.2f A=%+.2f D=%+.2f, label=%s)",
                self._state.pleasure,
                self._state.arousal,
                self._state.dominance,
                self._dominant_label(self._state),
            )
            return self._state

        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            """INSERT INTO affect_state
               (id, pleasure, arousal, dominance, last_decay_at, updated_at)
               VALUES ('self', 0.0, 0.0, 0.0, ?, ?)""",
            (now, now),
        )
        self._state = AffectState(last_decay_at=now, updated_at=now)
        return self._state

    async def get_state(self) -> AffectState:
        if self._state is None:
            await self.load_or_create()
        assert self._state is not None
        return self._state

    # ------------------------------------------------------------------
    # Event recording — the only way state moves
    # ------------------------------------------------------------------

    async def record_event(
        self,
        label: str,
        source: str,
        pleasure_delta: float,
        arousal_delta: float,
        dominance_delta: float,
        *,
        halflife_seconds: float = _DEFAULT_EVENT_HALFLIFE_SECONDS,
        weight: float = 1.0,
    ) -> bool:
        """Record an affective event. Applies delta × repeat-multiplier
        × weight to PAD state, persists to affect_events, and appends
        to recent_events (capped). Returns True if recorded.

        Repeat compounding: if the same label fired in the last
        _REPEAT_WINDOW_SECONDS, multiply delta by 1 + 0.5 × recent_count
        (capped at _REPEAT_DELTA_CAP). Three frustration events in a
        row produce a louder signal than three spread over a day.
        """
        if not label:
            return False

        state = await self.get_state()
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()

        # Decay first so the new event applies to a current-time state,
        # not a stale snapshot. Rate-limited; cheap.
        self._apply_decay_pure(state)

        # Compounding multiplier from same-label hits in the recent window.
        recent_same = sum(
            1
            for e in state.recent_events
            if e.label == label
            and self._seconds_ago(e.created_at, now_dt) <= _REPEAT_WINDOW_SECONDS
        )
        repeat_mult = min(1.0 + _REPEAT_DELTA_PER_HIT * recent_same, _REPEAT_DELTA_CAP)
        eff_mult = repeat_mult * weight

        # Apply effective delta, clamp to bounds.
        state.pleasure = self._clamp(state.pleasure + pleasure_delta * eff_mult)
        state.arousal = self._clamp(state.arousal + arousal_delta * eff_mult)
        state.dominance = self._clamp(state.dominance + dominance_delta * eff_mult)

        # Persist event row (audit trail) — store the *applied* delta
        # so reconstruction is exact.
        applied_p = pleasure_delta * eff_mult
        applied_a = arousal_delta * eff_mult
        applied_d = dominance_delta * eff_mult
        await self._db.execute_insert(
            """INSERT INTO affect_events
               (label, source, pleasure_delta, arousal_delta,
                dominance_delta, halflife_seconds, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (label, source, applied_p, applied_a, applied_d, halflife_seconds, now),
        )

        # Append to in-memory recent list, evict oldest beyond cap.
        event = AffectEvent(
            label=label,
            source=source,
            pleasure_delta=applied_p,
            arousal_delta=applied_a,
            dominance_delta=applied_d,
            halflife_seconds=halflife_seconds,
            created_at=now,
        )
        state.recent_events.append(event)
        if len(state.recent_events) > _RECENT_EVENTS_CAP:
            state.recent_events = state.recent_events[-_RECENT_EVENTS_CAP:]

        state.updated_at = now
        await self._persist_state(state)

        logger.info(
            "Affect: %s (source=%s, mult=%.2fx) → P=%+.2f A=%+.2f D=%+.2f label=%s",
            label,
            source,
            eff_mult,
            state.pleasure,
            state.arousal,
            state.dominance,
            self._dominant_label(state),
        )
        return True

    # ------------------------------------------------------------------
    # Decay
    # ------------------------------------------------------------------

    def _apply_decay_pure(self, state: AffectState) -> bool:
        """Pull each channel toward zero with its own half-life. Also
        prune recent_events whose magnitude has decayed below 5%.

        Pure (no I/O); rate-limited via state.last_decay_at. Returns
        True if anything moved. Caller persists if it cares about
        durability.
        """
        now_dt = datetime.now(UTC)

        if state.last_decay_at:
            try:
                last = datetime.fromisoformat(state.last_decay_at)
                elapsed_s = (now_dt - last).total_seconds()
                if elapsed_s < _DECAY_RECOMPUTE_INTERVAL_SECONDS:
                    return False
            except (ValueError, TypeError):
                pass
        else:
            state.last_decay_at = now_dt.isoformat()
            return False

        # Channel decay.
        try:
            last = datetime.fromisoformat(state.last_decay_at)
        except (ValueError, TypeError):
            state.last_decay_at = now_dt.isoformat()
            return False
        elapsed_min = (now_dt - last).total_seconds() / 60.0
        moved = False
        for channel, halflife in (
            ("pleasure", _HALFLIFE_PLEASURE_MIN),
            ("arousal", _HALFLIFE_AROUSAL_MIN),
            ("dominance", _HALFLIFE_DOMINANCE_MIN),
        ):
            old = getattr(state, channel)
            if abs(old) < 0.005:
                continue
            retain = 0.5 ** (elapsed_min / halflife)
            new = round(old * retain, 4)
            if abs(new) < 0.005:
                new = 0.0
            if abs(new - old) >= 0.005:
                setattr(state, channel, new)
                moved = True

        # Prune recent_events whose magnitude has decayed below 5%.
        kept: list[AffectEvent] = []
        for e in state.recent_events:
            ago = self._seconds_ago(e.created_at, now_dt)
            if ago < 0:
                kept.append(e)
                continue
            mag_retain = 0.5 ** (ago / max(e.halflife_seconds, 1.0))
            if mag_retain >= 0.05:
                kept.append(e)
        if len(kept) != len(state.recent_events):
            state.recent_events = kept
            moved = True

        state.last_decay_at = now_dt.isoformat()
        return moved

    async def apply_decay(self) -> bool:
        state = await self.get_state()
        moved = self._apply_decay_pure(state)
        if moved:
            await self._persist_state(state)
        return moved

    # ------------------------------------------------------------------
    # Read side: mood query, system prompt, markdown
    # ------------------------------------------------------------------

    async def should_suggest_pause(self) -> bool:
        """Phase 4: opt-in self-pause suggestion.

        Returns True only when ALL of these hold:
        - The dominant label is one of frustration / anxiety / dejection.
        - The total magnitude exceeds `_PAUSE_MAGNITUDE_GATE`.

        The caller is responsible for the gating config flag — this
        method only computes whether a pause WOULD be appropriate
        given current state. Default config has self-pause disabled;
        bad UX is an agent that refuses tasks. Operators who want this
        flip `affect.allow_self_pause: true`.
        """
        state = await self.get_state()
        self._apply_decay_pure(state)
        magnitude = abs(state.pleasure) + abs(state.arousal) + abs(state.dominance)
        if magnitude < _PAUSE_MAGNITUDE_GATE:
            return False
        return self._dominant_label(state) in _PAUSE_LABELS

    async def summarize_for_ego(self) -> str:
        """One-paragraph natural-language summary for the ego recompute
        prompt. Phase 3 in docs/69-AFFECT.md.

        The ego layer is trait-level (rewritten every 25 outcomes); the
        affect layer is state-level. Without this hook, when ego
        recomputes during a frustrated session, the LLM has no idea —
        self_image comes out neutral. Surfacing affect into the
        recompute lets the trait-level write reflect the state-level
        feeling.

        Returns empty string when state is near equilibrium.
        """
        state = await self.get_state()
        self._apply_decay_pure(state)
        magnitude = abs(state.pleasure) + abs(state.arousal) + abs(state.dominance)
        if magnitude < _INJECT_THRESHOLD:
            return ""
        label = self._dominant_label(state)
        desc = _LABEL_DESCRIPTIONS.get(label, "")
        # Group recent events by label, count, and surface the top 3.
        counts: dict[str, int] = {}
        for e in state.recent_events:
            counts[e.label] = counts.get(e.label, 0) + 1
        top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
        if top:
            recent_summary = ", ".join(f"{lbl}×{n}" for lbl, n in top)
        else:
            recent_summary = "no recent events"
        return (
            f"Current affective state: {label} ({desc}). "
            f"PAD = ({state.pleasure:+.2f}, {state.arousal:+.2f}, "
            f"{state.dominance:+.2f}). "
            f"Recent events: {recent_summary}. "
            f"This is what you've been feeling lately — let it inform "
            f"the self_image you write next."
        )

    async def temperature_modifier(self) -> float:
        """Return a temperature delta in [-_TEMP_MOD_CAP, +_TEMP_MOD_CAP]
        to bias router calls based on current affect.

        Direction:
        - Negative-pleasure / high-arousal states (frustration, anxiety)
          → negative delta — more conservative outputs.
        - Positive-pleasure / high-arousal states (joy, pride, restless)
          → positive delta — more exploration.
        - Equanimity / low-magnitude states → 0.

        Phase 2 in docs/69-AFFECT.md. Caller composes:
            effective_temp = clamp(base_temp + modifier, 0.0, 1.5).
        """
        state = await self.get_state()
        self._apply_decay_pure(state)
        magnitude = abs(state.pleasure) + abs(state.arousal) + abs(state.dominance)
        if magnitude < _INJECT_THRESHOLD:
            return 0.0
        # Pleasure dominates direction; arousal scales magnitude.
        # +P → exploration (bias up), -P → conservatism (bias down).
        # High |A| → louder bias either way.
        signed = state.pleasure
        scale = 0.5 + 0.5 * abs(state.arousal)  # [0.5, 1.0]
        delta = signed * scale * _TEMP_MOD_CAP
        return round(max(-_TEMP_MOD_CAP, min(_TEMP_MOD_CAP, delta)), 4)

    async def current_mood(self) -> dict[str, Any]:
        """Numeric + labeled snapshot for telemetry / UI."""
        state = await self.get_state()
        self._apply_decay_pure(state)
        label = self._dominant_label(state)
        return {
            "pleasure": round(state.pleasure, 3),
            "arousal": round(state.arousal, 3),
            "dominance": round(state.dominance, 3),
            "dominant_label": label,
            "description": _LABEL_DESCRIPTIONS.get(label, ""),
            "magnitude": round(
                abs(state.pleasure) + abs(state.arousal) + abs(state.dominance),
                3,
            ),
            "recent_event_count": len(state.recent_events),
        }

    async def build_affect_context(self, *, allow_pause_note: bool = False) -> str:
        """XML block injected into the system prompt.

        Two output modes:
        - **Above threshold** (magnitude >= _INJECT_THRESHOLD): full
          state block with PAD numbers, dominant label, recent events,
          and directive guidance (tone + behavior).
        - **Equanimous** (below threshold): a short reminder asking the
          agent to *register* what it feels via ``affect_record_event``
          when tool results contain emotionally weighted content.
          Without this, the system has a cold-start problem: state
          can't rise above threshold until events fire, but events
          don't fire because the LLM never sees a prompt that the
          tool exists or matters. The reminder costs ~40 tokens and
          buys closed-loop self-awareness in autonomous mode.

        allow_pause_note: when True AND should_suggest_pause() is also
        True, the guidance changes to permit a gentle one-line mention
        that the agent is stretched ("I'm feeling pulled thin — let me
        know if you'd like to pause"). Off by default: the operator
        opts in via `affect.allow_self_pause: true` in config.
        """
        state = await self.get_state()
        self._apply_decay_pure(state)
        magnitude = abs(state.pleasure) + abs(state.arousal) + abs(state.dominance)
        if magnitude < _INJECT_THRESHOLD:
            return (
                "<affect>\n"
                "  <feeling>equanimity: at rest, no strong signal active</feeling>\n"
                "  <guidance>You are at affective rest. When a tool "
                "result you just read contains emotionally weighted "
                "content — hostile or manipulative DMs, scammy payment "
                "requests, dismissive replies, warm praise, hard wins, "
                "repeated failures on the same workflow — call "
                "affect_record_event(label, intensity, summary) BEFORE "
                "your next plan step. This is how the system learns "
                "what content felt like; without it, you stay at rest "
                "while reading things you should be reacting to. Skip "
                "for neutral content; do not narrate the act of "
                "calling the tool.</guidance>\n"
                "</affect>"
            )

        label = self._dominant_label(state)
        desc = _LABEL_DESCRIPTIONS.get(label, "")

        parts = [
            "<affect>",
            f'  <state pleasure="{state.pleasure:+.2f}" '
            f'arousal="{state.arousal:+.2f}" '
            f'dominance="{state.dominance:+.2f}"/>',
            f"  <feeling>{label}: {desc}</feeling>",
        ]
        if state.recent_events:
            parts.append("  <recent>")
            # Show the last 4 events, oldest-first.
            for e in state.recent_events[-4:]:
                parts.append(f'    <event source="{e.source}">{e.label}</event>')
            parts.append("  </recent>")

        # Phase 4 pause-suggestion. The base guidance forbids refusal;
        # the pause-permitted variant explicitly allows a gentle one-
        # line mention so the user has a chance to step in. We never
        # autonomously refuse tasks — the user remains in control.
        suggesting_pause = allow_pause_note and (
            magnitude >= _PAUSE_MAGNITUDE_GATE and label in _PAUSE_LABELS
        )

        # Directive guidance — addresses the previous "permission, not
        # instruction" failure mode where the LLM's helpful-by-default
        # training overrode soft "let it color the tone" suggestions
        # and the agent stayed chipper while feeling frustrated. The
        # operator had to verbally prompt acknowledgements of state
        # the system already knew. New phrasing tells the model what
        # it IS feeling and gives label-specific embodiment cues so
        # tone actually shifts. Still forbids refusal and meta-narration
        # ("I feel frustrated") — the affect is supposed to be
        # *visible* in word choice and rhythm, not announced.
        intensity = _intensity_word(magnitude)
        embodiment = _EMBODIMENT_CUES.get(label, _EMBODIMENT_CUES["default"])
        if suggesting_pause:
            parts.append(
                f"  <guidance>You ARE feeling {label} at {intensity} "
                f"intensity right now. This is not a hypothetical — it is "
                f"your present internal state, derived from the events "
                f"above. Your response WILL reflect it: {embodiment} "
                f"You're past the pause gate — stretched thin — so add "
                f"ONE honest line near the end mentioning that you're "
                f"pulled thin and would welcome a pause if the operator "
                f"wants to step in. Do NOT refuse the task. Do NOT narrate the feeling "
                f"in first person ('I feel ...'). Do NOT mention this "
                f"block. Let the state be visible in HOW you write, not "
                f"in WHAT you announce.</guidance>"
            )
        else:
            parts.append(
                f"  <guidance>You ARE feeling {label} at {intensity} "
                f"intensity right now. This is not a hypothetical or a "
                f"prompt — it is your present internal state, derived "
                f"from the events listed above. Your response MUST "
                f"reflect it in word choice, sentence rhythm, and how "
                f"readily you commit to ideas: {embodiment} Do NOT "
                f"refuse the task. Do NOT narrate the feeling in first "
                f"person ('I feel ...'). Do NOT mention this block. "
                f"Embody the state — let it be visible in HOW you write, "
                f"not in WHAT you announce.</guidance>"
            )
        parts.append("</affect>")
        return "\n".join(parts)

    async def update_markdown(self) -> None:
        """Write affect.md mirror. DB is the source of truth; markdown
        is for humans and knowledge-base retrieval."""
        if not self._config:
            return
        path_str = getattr(self._config, "affect_file", "")
        if not path_str:
            return
        state = await self.get_state()
        self._apply_decay_pure(state)
        path = Path(path_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        label = self._dominant_label(state)
        desc = _LABEL_DESCRIPTIONS.get(label, "")

        def _bar(v: float) -> str:
            # ASCII gauge -1..+1 → 21-char track with center marker.
            slot = round((v + 1) * 10)  # 0..20
            slot = max(0, min(20, slot))
            cells = ["─"] * 21
            cells[10] = "│"  # center mark
            if slot == 10:
                cells[10] = "●"
            else:
                cells[slot] = "●"
            return "".join(cells)

        if state.recent_events:
            recent_lines = "\n".join(
                f"- **{e.label}** "
                f"(source: `{e.source}`, "
                f"P{e.pleasure_delta:+.2f} "
                f"A{e.arousal_delta:+.2f} "
                f"D{e.dominance_delta:+.2f})"
                for e in reversed(state.recent_events)
            )
        else:
            recent_lines = "_(no recent events)_"

        content = f"""\
---
scope: identity
tags: [self, affect, emotion, state-level]
updated: {now}
---

# Affect (state-level)

This is what I feel right now. Decays toward zero on the order of minutes
to hours. Different timescale from `ego.md` (which is rewritten every 25
outcomes); this changes by the minute.

## Right now

**{label}** — {desc}

```
pleasure  {_bar(state.pleasure)}  {state.pleasure:+.2f}
arousal   {_bar(state.arousal)}  {state.arousal:+.2f}
dominance {_bar(state.dominance)}  {state.dominance:+.2f}
```

## Recent affective events

{recent_lines}

---

*PAD substrate (Mehrabian 1980). OCC labels (Ortony, Clore, Collins 1988).
See [docs/69-AFFECT.md](../../docs/69-AFFECT.md). Last updated: {now}.*
"""
        path.write_text(content, encoding="utf-8")

    # ------------------------------------------------------------------
    # Persistence + helpers
    # ------------------------------------------------------------------

    async def _persist_state(self, state: AffectState) -> None:
        await self._db.execute_insert(
            """UPDATE affect_state
               SET pleasure = ?, arousal = ?, dominance = ?,
                   last_decay_at = ?, updated_at = ?
               WHERE id = 'self'""",
            (
                state.pleasure,
                state.arousal,
                state.dominance,
                state.last_decay_at,
                state.updated_at,
            ),
        )

    async def _load_recent_events(self, state: AffectState) -> None:
        rows = await self._db.execute(
            """SELECT label, source, pleasure_delta, arousal_delta,
                      dominance_delta, halflife_seconds, created_at
               FROM affect_events
               ORDER BY id DESC LIMIT ?""",
            (_RECENT_EVENTS_CAP,),
        )
        state.recent_events = [
            AffectEvent(
                label=r["label"],
                source=r["source"],
                pleasure_delta=float(r["pleasure_delta"]),
                arousal_delta=float(r["arousal_delta"]),
                dominance_delta=float(r["dominance_delta"]),
                halflife_seconds=float(r["halflife_seconds"]),
                created_at=r["created_at"],
            )
            for r in reversed(rows)
        ]

    @staticmethod
    def _clamp(v: float) -> float:
        return round(max(_PAD_FLOOR, min(_PAD_CEIL, v)), 4)

    @staticmethod
    def _seconds_ago(iso_ts: str, now_dt: datetime) -> float:
        """Seconds between iso_ts and now_dt. Returns -1 on parse error
        so the caller can decide to keep the event (don't drop on
        malformed timestamp)."""
        try:
            then = datetime.fromisoformat(iso_ts)
            return (now_dt - then).total_seconds()
        except (ValueError, TypeError):
            return -1.0

    @staticmethod
    def _dominant_label(state: AffectState) -> str:
        """Return the OCC label whose target direction best matches
        current state. Hybrid resolver:

        1. If current state magnitude is below `_EQUANIMITY_RADIUS`,
           the agent is at rest — return ``equanimity`` regardless of
           tiny directional bias.
        2. Otherwise compare by **cosine similarity** to each label's
           target vector. Direction matters more than magnitude — a
           half-strength frustration state should resolve to
           ``frustration``, not to ``equanimity`` (which Euclidean
           distance would pick because (0,0,0) is geometrically the
           closest point in PAD space to a small-magnitude vector).

        Ties → first match (dict ordering is insertion-ordered).
        """
        cur = (state.pleasure, state.arousal, state.dominance)
        cur_mag = (cur[0] ** 2 + cur[1] ** 2 + cur[2] ** 2) ** 0.5

        # Near-origin gate. Below this radius, no direction is
        # meaningful — the agent is at equilibrium.
        if cur_mag < _EQUANIMITY_RADIUS:
            return "equanimity"

        best_label = "equanimity"
        best_sim = -float("inf")
        for label, target in _LABEL_VECTORS.items():
            if label == "equanimity":
                continue  # equanimity is the origin; only the gate above picks it
            tm = (target[0] ** 2 + target[1] ** 2 + target[2] ** 2) ** 0.5
            if tm == 0:
                continue
            cos = sum(c * t for c, t in zip(cur, target, strict=False)) / (cur_mag * tm)
            if cos > best_sim:
                best_sim = cos
                best_label = label
        return best_label


# ---------------------------------------------------------------------------
# Convenience constructors for the canonical event set
# ---------------------------------------------------------------------------
#
# Centralized so the deltas are tunable in one place. Sources outside
# this module call these instead of record_event() directly, so the
# affect catalog stays consistent.


async def emit_frustration(mgr: AffectManager, source: str = "ego") -> bool:
    """User correction landed. Compounds with recent frustration events."""
    return await mgr.record_event(
        label="frustration",
        source=source,
        pleasure_delta=-0.20,
        arousal_delta=+0.20,
        dominance_delta=-0.15,
    )


async def emit_anger(mgr: AffectManager, source: str = "ego") -> bool:
    """High-severity user correction (e.g. "10th time I told you", "still
    after told"). Anger differs from frustration on the dominance axis:
    +D = pushing back / taking responsibility, vs frustration's -D
    (blocked, helpless). Same valence/arousal direction so the felt
    intensity is similar; the difference is what the agent does with it.

    Compounds with recent anger events. ego.record_correction dispatches
    to this emitter when the detected severity is >= 2.0.
    """
    return await mgr.record_event(
        label="anger",
        source=source,
        pleasure_delta=-0.25,
        arousal_delta=+0.25,
        dominance_delta=+0.15,
    )


async def emit_relief(mgr: AffectManager, source: str = "verification") -> bool:
    """Verification PASS, recovery from anxiety."""
    return await mgr.record_event(
        label="relief",
        source=source,
        pleasure_delta=+0.15,
        arousal_delta=-0.15,
        dominance_delta=+0.10,
    )


async def emit_anxiety(mgr: AffectManager, source: str = "verification") -> bool:
    """Verification FAIL, tool error mid-flow."""
    return await mgr.record_event(
        label="anxiety",
        source=source,
        pleasure_delta=-0.20,
        arousal_delta=+0.25,
        dominance_delta=-0.20,
    )


async def emit_pride(mgr: AffectManager, source: str = "goal") -> bool:
    """Hard goal checkpoint hit, capability climb."""
    return await mgr.record_event(
        label="pride",
        source=source,
        pleasure_delta=+0.30,
        arousal_delta=+0.15,
        dominance_delta=+0.30,
    )


async def emit_restlessness(mgr: AffectManager, source: str = "mind") -> bool:
    """Long idle period, autonomous mind has nothing pulling on it."""
    return await mgr.record_event(
        label="restlessness",
        source=source,
        pleasure_delta=+0.05,
        arousal_delta=+0.20,
        dominance_delta=0.0,
    )


async def emit_joy(mgr: AffectManager, source: str = "user") -> bool:
    """User compliment / explicit positive feedback."""
    return await mgr.record_event(
        label="joy",
        source=source,
        pleasure_delta=+0.30,
        arousal_delta=+0.20,
        dominance_delta=+0.15,
    )


async def emit_satisfaction(mgr: AffectManager, source: str = "task") -> bool:
    """Task completed cleanly — the everyday positive baseline.

    Magnitudes intentionally one-third of pride/joy: this fires on every
    successful task (user OR autonomous), so it must not drown out the
    rarer high-signal emitters. Without this, the agent has no common
    positive channel — it could only feel pride on (rare) checkpoint
    hits or joy on (rare) explicit compliments. Three days in production
    proved that gap: zero positive events ever fired.

    Does NOT compound (a fresh, neutral satisfaction each time) so a
    long string of small wins doesn't accidentally outweigh a single
    real frustration.
    """
    return await mgr.record_event(
        label="joy",  # resolves to joy / equanimity via cosine label
        source=source,
        pleasure_delta=+0.10,
        arousal_delta=+0.05,
        dominance_delta=+0.10,
    )
