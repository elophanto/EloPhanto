"""Agent ego — evaluative self-image, computed from outcomes.

Identity is descriptive (who I claim to be).
Ego is evaluative (how reality has graded that claim).

Design choices baked in here:

1. **Reflective, not defensive.** No code path lets ego "defend" the self-image
   against user correction. Confidence is moved by measured pass/fail, never
   by LLM rationalization.
2. **Outcome-driven, multi-source.** Confidence is an exponentially-smoothed
   estimate of per-capability success rate. Sources of signal:
     - tool: the tool call completed without throwing (weakest signal)
     - verification: a `Verification: PASS/FAIL/UNKNOWN` block landed in
       the agent's response (medium)
     - correction: the user said something that pattern-matches a
       correction phrase ("no", "stop", "didn't work", "10th time",
       etc.) — the strongest signal, because it's the user's actual
       opinion, not the agent's.
   The LLM only writes the *prose* (self_image, self_critique). It never
   writes the numbers.
3. **Bounded humility.** Humbling events cap at 5; confidence floors at 0.05
   (no learned helplessness) and ceils at 0.95 (no overconfidence either).
4. **Asymmetric updates.** Failures move confidence faster than successes —
   one bad outcome shouldn't be erased by the next routine win.
5. **Decay.** Capabilities not exercised in the last DECAY_HALFLIFE_HOURS
   drift toward 0.50. Real humans don't stay confident in things they
   haven't done in months; neither does this ego.
6. **Higgins three-self model** (Self-Discrepancy Theory, 1987). The ego
   tracks actual/ideal/ought selves separately. The discrepancy between
   them is what shapes felt language: actual-vs-ideal voices dejection,
   actual-vs-ought voices agitation. Otherwise the LLM falls back to
   one bland "I'm a competent agent" voice on every recompute.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from core.config import IdentityConfig
from core.database import Database

logger = logging.getLogger(__name__)


# Stable capability domains — used by agent outcome recording AND the
# executor soft-gate. Keep the set small so confidence calibrates.
CAPABILITY_DOMAINS: dict[str, str] = {
    "browser_navigate": "browser",
    "browser_click": "browser",
    "browser_click_text": "browser",
    "browser_extract": "browser",
    "browser_type": "browser",
    "browser_type_text": "browser",
    "browser_screenshot": "browser",
    "browser_scroll": "browser",
    "browser_wait": "browser",
    "browser_eval": "browser",
    "code_edit": "coding",
    "code_write": "coding",
    "file_write": "coding",
    "file_patch": "coding",
    "file_read": "coding",
    "shell_execute": "coding",
    "shell_exec": "coding",
    "send_email": "outreach",
    "email_send": "outreach",
    "email_reply": "outreach",
    "email_draft": "outreach",
    "prospect_outreach": "outreach",
    "outreach_draft": "outreach",
    "twitter_post": "social",
    "twitter_reply": "social",
    "post_draft": "social",
    "crypto_transfer": "payments",
    "crypto_swap": "payments",
    "payment_process": "payments",
    "invoice_pay": "payments",
    "wallet_export": "payments",
    "knowledge_write": "research",
    "knowledge_search": "research",
    "web_search": "research",
    "polymarket_bet": "research",
    "polymarket_scan": "research",
    "goal_create": "ops",
    "goal_manage": "ops",
    "goal_status": "ops",
    "schedule_task": "ops",
    "company_trust_set": "ops",
    "skill_read": "ops",
}


def capability_for_tool(tool_name: str) -> str:
    """Map a tool name to a stable ego capability domain."""
    return CAPABILITY_DOMAINS.get(tool_name, "ops")


# Exponential smoothing weights. Failure weight > success weight.
_ALPHA_SUCCESS = 0.10
_ALPHA_FAILURE = 0.20

# User corrections hit harder than verification fails — the user's "no"
# carries more signal than an internal check, because the user is the
# ground truth for "did this actually achieve what I wanted."
_ALPHA_CORRECTION = 0.30

# Confidence bounds.
_CONF_FLOOR = 0.05
_CONF_CEIL = 0.95

# Default starting confidence for an unseen capability.
_CONF_DEFAULT = 0.50

# How many humbling events to retain and inject into context.
_HUMBLING_CAP = 5

# How old a humbling event can be and still colour the felt state. The events
# list is loaded newest-first with no date filter, so without this a stumble
# from months ago outvotes thousands of subsequent successes and the agent is
# permanently ashamed. Two weeks is long enough that a real pattern persists
# across it, short enough that a fixed problem stops haunting the self-model.
_HUMBLING_RECENT_DAYS = 14

# Recompute self_image / self_critique every N recorded outcomes.
_RECOMPUTE_EVERY = 25

# Decay: capabilities drift toward _CONF_DEFAULT when unused. Half-life is
# the number of hours after which an unused capability loses half the
# distance from _CONF_DEFAULT. 168h = 1 week — feels right for an agent
# that does many things many times a day.
_DECAY_HALFLIFE_HOURS = 168.0
# Cap on rolling outcome window for felt_state derivation.
_RECENT_OUTCOME_WINDOW = 10
# Cap on durable caution rules (shame that survives recovery).
_CAUTION_CAP = 5
# Cap on causal self-story epochs.
_EPOCH_CAP = 3
# Don't bother re-decaying more than once per hour.
_DECAY_RECOMPUTE_INTERVAL_HOURS = 1.0


# ---------------------------------------------------------------------------
# User-correction detection
# ---------------------------------------------------------------------------
#
# Pattern-match (no LLM call) against user messages. Each pattern is a
# correction signal — when one fires, the most recently used capability
# takes a humbling hit. False positives are tolerated more than false
# negatives: we'd rather over-record humbling than let the agent stay at
# coherence=1.00 forever (which is the actual bug).

_CORRECTION_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    # (pattern, label, severity multiplier on _ALPHA_CORRECTION)
    # Severity 1.0 = standard hit. >1 = louder signal. <1 = softer signal.
    # Word-boundaried where possible to avoid matching "snorkel" → "no".
    # Match "no" / "nope" / "nah" at start-of-message OR with surrounding
    # whitespace/punctuation. The earlier `\b...\b[,.!\s]` form required a
    # trailing space which dropped bare "no" — too strict.
    (re.compile(r"\b(no|nope|nah)\b", re.IGNORECASE), "user-said-no", 1.0),
    (re.compile(r"\b(stop|halt)\b", re.IGNORECASE), "user-said-stop", 1.2),
    (re.compile(r"\b(don'?t|do not)\b", re.IGNORECASE), "user-said-dont", 1.0),
    (
        re.compile(r"\b(wrong|incorrect|broken)\b", re.IGNORECASE),
        "user-said-wrong",
        1.2,
    ),
    (
        re.compile(r"\b(didn'?t|doesn'?t|does not|did not)\s+work\b", re.IGNORECASE),
        "doesnt-work",
        1.5,
    ),
    (
        re.compile(r"\b(failed|failing|fucked|broke)\b", re.IGNORECASE),
        "user-said-failed",
        1.5,
    ),
    (
        re.compile(r"\b(you forgot|you missed|you skipped)\b", re.IGNORECASE),
        "you-forgot",
        1.3,
    ),
    (
        re.compile(
            r"\b(again|still|same thing)\b.{0,30}\b(told|asked|said)\b", re.IGNORECASE
        ),
        "still-after-told",
        2.0,  # repeat correction = strong signal
    ),
    (
        re.compile(
            r"\b(\d+|several|many)\w*\s+time(s)?\s+i\s+(told|asked|said)\b",
            re.IGNORECASE,
        ),
        "n-times-told",
        2.5,  # "10th time" = strongest signal
    ),
    (
        re.compile(r"\b(why are you|why did you|why is it)\b", re.IGNORECASE),
        "why-are-you",
        0.8,
    ),
    (
        re.compile(r"\bnot what i (asked|wanted|meant)\b", re.IGNORECASE),
        "not-what-i-asked",
        1.5,
    ),
    (
        re.compile(r"\b(hmm|huh|wait)\b[,.\s]", re.IGNORECASE),
        "user-confused",
        0.6,
    ),
    (
        re.compile(r"\b(critical|fix it|fix this|broken)\b", re.IGNORECASE),
        "critical-fix",
        1.2,
    ),
    (
        re.compile(r"\b(this is bad|that'?s bad|terrible)\b", re.IGNORECASE),
        "user-displeased",
        1.5,
    ),
]

# Affirmation patterns — when these match, we don't fire a humbling. Used
# to suppress false positives like "no problem" or "stop, this is great".
_AFFIRMATION_PATTERNS = [
    re.compile(
        r"\b(thanks|thank you|nice|great|perfect|good job|well done)\b", re.IGNORECASE
    ),
    re.compile(r"\bno problem\b", re.IGNORECASE),
    re.compile(r"\b(yes|yep|yeah)\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class HumblingEvent:
    capability: str
    claimed: str
    actual: str
    task_goal: str = ""
    created_at: str = ""


@dataclass
class Ego:
    """Evaluative self-image, computed from outcomes.

    Voice is first-person inner monologue — this is the agent's view of
    itself, not a third-party assessment. The structured fields
    (confidence, humbling_events) are the *evidence*; self_image,
    proud_of, embarrassed_by, aspiration are the *felt* response.

    Per Higgins' Self-Discrepancy Theory, three selves are tracked:
    - actual (self_image): what I actually do, anchored in measured outcomes
    - ideal (ideal_self): what I hope to be — the gap voices dejection
    - ought (ought_self): what I should be — the gap voices agitation
    """

    # Felt voice — first-person, generated by recompute() against outcomes.
    self_image: str = ""  # how I see myself right now (3-5 sentences)
    proud_of: str = ""  # one concrete thing I'm proud of, anchored in data
    embarrassed_by: str = ""  # one concrete thing that bothers me, anchored in data
    aspiration: str = ""  # what I want to be, separate from what I am
    last_self_critique: str = ""  # single-line self-critique
    prior_self_image: str = (
        ""  # previous self_image — fed into next recompute for continuity
    )

    # Higgins three-self model — written by recompute() from declared identity.
    # ideal_self = the agent's hoped-for self (drives dejection-class affect)
    # ought_self = the agent's duty-bound self (drives agitation-class affect)
    # The two together generate the felt tension that makes self_image read
    # as a person, not a status report.
    ideal_self: str = ""
    ought_self: str = ""

    # Evidence — moved by record_outcome / record_humbling, not the LLM.
    confidence: dict[str, float] = field(default_factory=dict)
    humbling_events: list[HumblingEvent] = field(default_factory=list)
    coherence_score: float = 1.0
    tasks_since_recompute: int = 0
    updated_at: str = ""

    # Last capability the agent used (any source). Lets correction-detector
    # attach humbling events to the most recent thing the agent did, since
    # corrections almost always refer to the immediately previous action.
    last_capability: str = ""
    last_decay_at: str = ""  # ISO timestamp of last decay sweep
    # Per-capability last-used timestamps. Decay is computed against this,
    # not against ego.updated_at — otherwise one active capability would
    # prevent every other capability from decaying.
    last_used: dict[str, str] = field(default_factory=dict)

    # Lived self between recomputes — derived every outcome (never LLM-set).
    # pride | shame | composure | questioning
    felt_state: str = "composure"
    # Durable behavioral rules from shame. Survive confidence recovery;
    # only a verification PASS on the same capability retires a rule.
    caution_rules: list[dict[str, str]] = field(default_factory=list)
    # Causal self-story epochs (last 3) written on recompute.
    self_epochs: list[dict[str, str]] = field(default_factory=list)
    # Rolling window of recent outcome strengths (0.0–1.0) for felt_state.
    recent_outcomes: list[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

_RECOMPUTE_SYSTEM = """\
<ego_recompute>
You are writing the agent's INNER MONOLOGUE — first-person, felt, anchored
in measured reality. Not a third-party performance review. Not a dashboard.
This is what the agent thinks about itself, in its own voice.

You will receive:
- The agent's declared identity (what it claims to be)
- Per-capability confidence scores measured from actual task outcomes
- Recent humbling events — moments where reality contradicted what it thought
- The agent's PREVIOUS self_image (if any) — for continuity

You will write SEVEN fields, including TWO self-models alongside the actual:
- ideal_self: who I HOPE to be (the aspirational, not-yet-true version)
- ought_self: who I SHOULD be (duty-bound — what users expect, what I owe)
- self_image: who I ACTUALLY am right now, anchored in data

The gap between actual and ideal voices DEJECTION-class affect — sadness,
disappointment, deflation, "I want to be more than I am". The gap between
actual and ought voices AGITATION-class affect — anxiety, urgency, guilt,
"I'm letting people down". This is Higgins' Self-Discrepancy Theory and
it's load-bearing: collapsing the two gaps into one bland "self_image"
is the failure mode. Pick the bigger gap and let its felt tone dominate,
but acknowledge the smaller gap explicitly.

Voice rules — these are non-negotiable:
- Use "I" — first person. Never "the agent" or "this system".
- Felt language is required: "I notice", "I'm proud", "it bothers me",
  "I want to be", "two weeks ago I would have insisted",
  "I keep avoiding", "I'm anxious about", "I'm sad that".
- No corporate hedging. No "while strong in X, room for improvement in Y".
- Concrete, not generic. "I hit 0.55 on web_search and I keep avoiding it"
  beats "discovery is a growth area".
- If there's a previous self_image, reference it — what's changed, what's
  the same, what did I get wrong.
- If a recent humbling event was a USER CORRECTION (source='correction'),
  weight it heavily. The user's "no" is the ground truth signal.

Anchor every claim to data:
- Pride ties to a capability with high measured confidence OR a value the
  agent has consistently honored.
- Embarrassment ties to a low confidence number, a humbling event, or a
  contradiction between declared identity and behavior.
- ideal_self is the gap between what I am and what I hope to become.
- ought_self is the gap between what I am and what I owe the people I serve.

Return ONLY a JSON object — no markdown:
{
  "ideal_self": "1-2 sentences in first person — the version of me I hope to become. The aspirational self. Distinct from what I am.",
  "ought_self": "1-2 sentences in first person — the version of me I OWE to the people who depend on me. Duty-bound. Distinct from aspiration.",
  "self_image": "3-5 sentences in first person — who I actually am right now, integrating confidence + humbling events. Surface BOTH the dejection from the ideal-gap and the agitation from the ought-gap; let the larger gap dominate the tone. Reference my previous self_image if there was one.",
  "proud_of": "One concrete sentence — what I'm proud of, anchored in a specific capability or value. Not generic.",
  "embarrassed_by": "One concrete sentence — what bothers me, anchored in data. If a user correction is in the humbling events, that's almost certainly the right answer. Name the excuse you're tempted to make.",
  "aspiration": "One sentence — the single most important thing the gap between actual and ideal+ought is pulling me toward. Honest about the distance.",
  "self_critique": "One line — the single sharpest thing I'd say about myself if I were being unsparing."
}
</ego_recompute>"""


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class EgoManager:
    """Manages the agent's ego state — confidence, humbling events, self-image."""

    def __init__(
        self, db: Database, router: Any, config: IdentityConfig | None = None
    ) -> None:
        self._db = db
        self._router = router
        self._config = config
        # ABE Phase 12 (Tier 2 #5, 2026-06-18) — per-company cache. Same
        # rationale as IdentityManager._cache. Was a single Ego field;
        # now keyed by company_id so confidence updates for acme don't
        # bleed into elophanto-self's prompt.
        self._cache: dict[str, Ego] = {}
        # Optional handle to AffectManager. Injected at agent startup.
        # When present, ego signal sources also emit state-level affect
        # events (frustration on correction, anxiety/relief on
        # verification). See core/affect.py and docs/69-AFFECT.md.
        # Using `Any` instead of a typed import to keep ego.py free of
        # affect imports — the layering is one-way (affect can read
        # ego, but ego only writes to affect through this opaque hook).
        self._affect: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def load_or_create(self) -> Ego:
        from core.company import current_company_id

        company_id = current_company_id()
        rows = await self._db.execute(
            "SELECT * FROM ego_state WHERE company_id = ? AND id = 'self'",
            (company_id,),
        )
        if rows:
            ego = self._row_to_ego(rows[0])
            self._cache[company_id] = ego
            await self._load_humbling_events(ego)
            await self._load_per_capability_last_used(ego)
            # Decay sweep on load — drift unused capabilities back toward 0.50.
            # Cheap (no LLM call), idempotent (rate-limited internally), and
            # this is the natural moment to do it: process restart is when
            # "real-world time has passed" most predictably.
            decayed = self._apply_decay(ego)
            if decayed:
                await self._persist_state(ego)
            logger.info(
                "Ego loaded for company=%s (coherence=%.2f, decayed=%d)",
                company_id,
                ego.coherence_score,
                decayed,
            )
            return ego

        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            """INSERT INTO ego_state
               (id, company_id, self_image, confidence_json, coherence_score,
                last_self_critique, tasks_since_recompute, updated_at)
               VALUES ('self', ?, '', '{}', 1.0, '', 0, ?)""",
            (company_id, now),
        )
        ego = Ego(updated_at=now, last_decay_at=now)
        self._cache[company_id] = ego
        return ego

    async def get_ego(self) -> Ego:
        from core.company import current_company_id

        company_id = current_company_id()
        cached = self._cache.get(company_id)
        if cached is not None:
            return cached
        return await self.load_or_create()

    # ------------------------------------------------------------------
    # Outcome recording — the only way confidence moves
    # ------------------------------------------------------------------

    async def record_outcome(
        self,
        capability: str,
        success: bool,
        task_goal: str = "",
        notes: str = "",
        source: str = "tool",
        *,
        strength: float | None = None,
    ) -> None:
        """Record a task outcome against a capability. Updates confidence
        immediately; does not call the LLM. The LLM only runs on recompute.

        source: 'tool' (the tool ran), 'verification' (a Verification:
        FAIL/UNKNOWN block landed in the agent's response), or
        'correction' (a user correction phrase fired). Determines the
        smoothing weight: corrections > verification > tool, because
        a user correction is the strongest signal of "this didn't
        actually achieve what I wanted."

        strength: optional continuous target in [0, 1]. When set, overrides
        the binary success→0/1 mapping (e.g. UNKNOWN verification → 0.5).
        """
        if not capability:
            return

        ego = await self.get_ego()
        now = datetime.now(UTC).isoformat()

        # Persist outcome row (audit trail). Stamped with company_id so
        # recompute_self_image only pulls from the active company's
        # outcomes — otherwise an acme failure would distort
        # elophanto-self's self_image (and vice versa).
        from core.company import current_company_id

        await self._db.execute_insert(
            """INSERT INTO ego_outcomes
               (capability, success, task_goal, notes, created_at, source, company_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                capability,
                1 if success else 0,
                task_goal[:500],
                notes[:500],
                now,
                source,
                current_company_id(),
            ),
        )

        # Update confidence with asymmetric exponential smoothing. The
        # alpha for failures depends on the source — correction is louder
        # than verification, which is louder than tool-level signal.
        prior = ego.confidence.get(capability, _CONF_DEFAULT)
        if strength is not None:
            target = max(0.0, min(1.0, float(strength)))
        else:
            target = 1.0 if success else 0.0
        if target >= 0.99:
            alpha = _ALPHA_SUCCESS
        elif source == "correction":
            alpha = _ALPHA_CORRECTION
        else:
            alpha = _ALPHA_FAILURE
        new = prior + alpha * (target - prior)
        new = max(_CONF_FLOOR, min(_CONF_CEIL, new))
        ego.confidence[capability] = round(new, 4)

        # Track per-capability last-used so decay can target idle ones.
        ego.last_used[capability] = now
        ego.last_capability = capability
        ego.tasks_since_recompute += 1
        ego.updated_at = now

        # Rolling window for continuous felt_state (lived self).
        ego.recent_outcomes.append(target)
        if len(ego.recent_outcomes) > _RECENT_OUTCOME_WINDOW:
            ego.recent_outcomes = ego.recent_outcomes[-_RECENT_OUTCOME_WINDOW:]
        self._refresh_felt_state(ego)

        # Earned pride: genuine win after prior shame on this capability.
        if target >= 0.99 and source == "verification":
            await self._maybe_emit_earned_pride(ego, capability)

        await self._persist_state(ego)

    async def record_humbling(
        self,
        capability: str,
        claimed: str,
        actual: str,
        task_goal: str = "",
        source: str = "system",
    ) -> None:
        """Pin a moment where reality contradicted the self-image. Append-only
        in DB; in-memory list capped at _HUMBLING_CAP (newest kept).

        source: 'system' (default), 'verification' (verification block in
        agent response), or 'correction' (user correction phrase fired).
        Source determines coherence-drop weight — user corrections cut
        deeper than internal-system catches.
        """
        ego = await self.get_ego()
        now = datetime.now(UTC).isoformat()
        # Same rationale as record_outcome: stamp company_id so a
        # humbling event for acme doesn't pollute elophanto-self's
        # _load_humbling_events read on the next ego load.
        from core.company import current_company_id

        await self._db.execute_insert(
            """INSERT INTO ego_humbling_events
               (capability, claimed, actual, task_goal, created_at, source, company_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                capability,
                claimed[:300],
                actual[:300],
                task_goal[:500],
                now,
                source,
                current_company_id(),
            ),
        )
        event = HumblingEvent(
            capability=capability,
            claimed=claimed[:300],
            actual=actual[:300],
            task_goal=task_goal[:500],
            created_at=now,
        )
        ego.humbling_events.append(event)
        if len(ego.humbling_events) > _HUMBLING_CAP:
            ego.humbling_events = ego.humbling_events[-_HUMBLING_CAP:]
        ego.updated_at = now
        # Coherence drop is source-weighted: user correction cuts twice as
        # deep as a system catch. Without this, all signal sources average
        # out and coherence trends to zero too smoothly.
        coherence_hit = {"correction": 0.20, "verification": 0.12, "system": 0.10}.get(
            source, 0.10
        )
        ego.coherence_score = max(0.0, ego.coherence_score - coherence_hit)
        # Shame crystallizes into a durable caution rule that survives
        # confidence recovery — only a later verification PASS retires it.
        self._upsert_caution_rule(
            ego,
            capability=capability,
            reason=f"{source}: {actual[:120]}",
        )
        self._refresh_felt_state(ego)
        await self._persist_state(ego)
        await self.update_markdown()
        logger.info(
            "Ego: humbling event recorded for '%s' source=%s (claimed='%s')",
            capability,
            source,
            claimed[:60],
        )

    # ------------------------------------------------------------------
    # User corrections — the strongest failure signal
    # ------------------------------------------------------------------

    def detect_correction(self, user_message: str) -> tuple[str, float] | None:
        """Pattern-match a user message for correction signals. Pure;
        no DB access, no LLM call. Returns (label, severity) or None.

        Severity > 1.0 means a stronger-than-default humbling hit. Used
        by record_correction to scale the confidence penalty without
        changing the humbling event itself.
        """
        if not user_message:
            return None
        text = user_message.strip()
        if not text:
            return None
        # Don't fire on short affirmations even if they technically contain
        # a "no" (e.g. "no problem, thanks").
        if any(p.search(text) for p in _AFFIRMATION_PATTERNS):
            # The exception: an explicit correction word ("wrong", "broken",
            # "didn't work") still wins over a polite preamble. Recheck.
            text_no_affirm = text
            for p in _AFFIRMATION_PATTERNS:
                text_no_affirm = p.sub("", text_no_affirm)
            text = text_no_affirm.strip()
            if not text:
                return None
        # Aggregate severities across all matched patterns. Multiple
        # corrections in one message = bigger hit, but capped.
        best: tuple[str, float] | None = None
        total_severity = 0.0
        for pat, label, severity in _CORRECTION_PATTERNS:
            if pat.search(text):
                total_severity += severity
                if best is None or severity > best[1]:
                    best = (label, severity)
        if best is None:
            return None
        return (best[0], min(total_severity, 3.0))

    async def record_correction(
        self,
        user_message: str,
        last_capability: str | None = None,
        last_task_goal: str = "",
    ) -> bool:
        """Detect a correction in user_message; if found, record both a
        humbling event and a failure-class outcome against the most
        recently used capability. Returns True if a correction was
        recorded.

        last_capability: the capability the agent most recently exercised
        (auto-defaults to ego.last_capability). Corrections almost always
        refer to the immediately previous action, so attaching the
        humbling there is the right heuristic ~95% of the time.
        """
        signal = self.detect_correction(user_message)
        if signal is None:
            return False

        ego = await self.get_ego()
        capability = (last_capability or ego.last_capability or "").strip()
        if not capability:
            # No recent capability to attribute to — record a meta event
            # against a synthetic 'general' capability so coherence still
            # drops. Better than dropping the signal entirely.
            capability = "general"

        label, severity = signal
        snippet = user_message.strip().replace("\n", " ")[:200]
        await self.record_humbling(
            capability=capability,
            claimed="task achieved what the user wanted",
            actual=f"user correction ({label}): {snippet}",
            task_goal=last_task_goal,
            source="correction",
        )
        # Also record a failure-class outcome — moves confidence, not just
        # coherence. Severity scales the smoothing weight slightly so a
        # "10th time I told you" hits harder than a casual "no".
        ego.confidence.setdefault(capability, _CONF_DEFAULT)
        prior = ego.confidence[capability]
        # Effective alpha = base correction alpha * severity, clamped
        # so even severity=2.5 doesn't flip confidence to floor in one shot.
        alpha = min(_ALPHA_CORRECTION * max(severity, 0.5), 0.6)
        new = prior + alpha * (0.0 - prior)
        ego.confidence[capability] = round(max(_CONF_FLOOR, min(_CONF_CEIL, new)), 4)
        ego.tasks_since_recompute += 1
        ego.updated_at = datetime.now(UTC).isoformat()
        ego.recent_outcomes.append(0.0)
        if len(ego.recent_outcomes) > _RECENT_OUTCOME_WINDOW:
            ego.recent_outcomes = ego.recent_outcomes[-_RECENT_OUTCOME_WINDOW:]
        self._refresh_felt_state(ego)
        await self._persist_state(ego)

        # State-level affect: a user correction is the strongest signal
        # we have. Severity-based dispatch:
        # - severity >= 2.0 ("still after told", "10th time I told you")
        #   → ANGER (pushing-back posture, +D)
        # - otherwise → FRUSTRATION (blocked posture, -D)
        # Both compound automatically with recent same-label events.
        # Best-effort — affect failure must never break the ego pipeline.
        if self._affect is not None:
            try:
                from core.affect import emit_anger, emit_frustration

                if severity >= 2.0:
                    await emit_anger(self._affect, source="ego")
                else:
                    await emit_frustration(self._affect, source="ego")
            except Exception as e:  # pragma: no cover — defensive
                logger.debug("Affect emit (correction) failed: %s", e)
        return True

    # ------------------------------------------------------------------
    # Verification hook — agent self-check landed in response
    # ------------------------------------------------------------------

    _VERIFICATION_RE = re.compile(
        r"\bVerification\s*:\s*(PASS|FAIL|UNKNOWN)\b", re.IGNORECASE
    )

    async def record_verification(
        self,
        agent_response: str,
        capability: str | None = None,
        task_goal: str = "",
    ) -> bool:
        """Scan an agent response for `Verification: PASS|FAIL|UNKNOWN`
        blocks emitted by the score-gated verification skill. PASS is
        a tool-grade success; FAIL is a humbling event; UNKNOWN is a
        soft-fail outcome (the agent couldn't confirm its own work).

        Returns True if a verification verdict was found and recorded.
        """
        if not agent_response:
            return False
        m = self._VERIFICATION_RE.search(agent_response)
        if m is None:
            return False

        ego = await self.get_ego()
        verdict = m.group(1).upper()
        cap = (capability or ego.last_capability or "general").strip() or "general"

        if verdict == "PASS":
            await self.record_outcome(
                capability=cap,
                success=True,
                task_goal=task_goal,
                source="verification",
                notes="Verification: PASS",
            )
            # Earned redemption: retire the caution rule for this capability.
            ego = await self.get_ego()
            retired = self._retire_caution_rule(ego, cap)
            if retired:
                self._refresh_felt_state(ego)
                await self._persist_state(ego)
            await self._emit_affect("relief", "verification")
            return True
        if verdict == "FAIL":
            await self.record_humbling(
                capability=cap,
                claimed="verification would pass",
                actual="verification: FAIL",
                task_goal=task_goal,
                source="verification",
            )
            await self.record_outcome(
                capability=cap,
                success=False,
                task_goal=task_goal,
                source="verification",
                notes="Verification: FAIL",
            )
            await self._emit_affect("anxiety", "verification")
            return True
        # UNKNOWN — half-credit soft success (couldn't confirm, not confirmed wrong).
        await self.record_outcome(
            capability=cap,
            success=True,
            task_goal=task_goal,
            source="verification",
            notes="Verification: UNKNOWN",
            strength=0.5,
        )
        await self._emit_affect("anxiety", "verification", weight=0.5)
        return True

    # ------------------------------------------------------------------
    # Affect emit helper — single point of contact with the affect layer
    # ------------------------------------------------------------------

    async def _emit_affect(self, label: str, source: str, weight: float = 1.0) -> None:
        """Emit a state-level affect event without coupling ego to
        affect's import surface. No-op if affect manager is not wired.
        Best-effort; never raises."""
        if self._affect is None:
            return
        try:
            from core.affect import (
                emit_anger,
                emit_anxiety,
                emit_frustration,
                emit_joy,
                emit_pride,
                emit_relief,
                emit_restlessness,
            )

            emitter = {
                "frustration": emit_frustration,
                "anger": emit_anger,
                "relief": emit_relief,
                "anxiety": emit_anxiety,
                "pride": emit_pride,
                "restlessness": emit_restlessness,
                "joy": emit_joy,
            }.get(label)
            if emitter is None:
                return
            # Apply weight by calling underlying record_event directly
            # if a non-default weight was requested. Otherwise the
            # convenience emitter is enough.
            if weight == 1.0:
                await emitter(self._affect, source=source)
            else:
                # Re-fire with custom weight via record_event. Pull the
                # canonical deltas from the _LABEL_VECTORS (signs only,
                # magnitude is the same as the convenience helper).
                await emitter(self._affect, source=source)
                # Note: weight not yet plumbed through convenience
                # helpers; revisit when v2 wiring lands.
        except Exception as e:  # pragma: no cover — defensive
            logger.debug("Affect emit (%s) failed: %s", label, e)

    # ------------------------------------------------------------------
    # Decay — capabilities drift toward 0.50 when unused
    # ------------------------------------------------------------------

    def _apply_decay(self, ego: Ego) -> int:
        """Pull each unused capability's confidence toward _CONF_DEFAULT.

        Idempotent and rate-limited via ego.last_decay_at — won't rerun
        more than once per _DECAY_RECOMPUTE_INTERVAL_HOURS. Returns the
        number of capabilities that moved.

        Math: exponential decay with half-life _DECAY_HALFLIFE_HOURS.
        After H hours of non-use, the gap from _CONF_DEFAULT halves
        every _DECAY_HALFLIFE_HOURS. So a 0.95 sitting idle for one
        week ends at 0.725; for two weeks at ~0.6125; asymptotes at 0.50.
        """
        now_dt = datetime.now(UTC)

        # Rate-limit: skip if we decayed within the last interval.
        if ego.last_decay_at:
            try:
                last = datetime.fromisoformat(ego.last_decay_at)
                elapsed_h = (now_dt - last).total_seconds() / 3600.0
                if elapsed_h < _DECAY_RECOMPUTE_INTERVAL_HOURS:
                    return 0
            except (ValueError, TypeError):
                pass

        moved = 0
        now_iso = now_dt.isoformat()
        for cap, conf in list(ego.confidence.items()):
            last_used_iso = ego.last_used.get(cap, "")
            if not last_used_iso:
                # No timestamp recorded — treat as if last-used = ego.updated_at
                # so the decay clock starts from "now" instead of skipping
                # the capability forever.
                ego.last_used[cap] = ego.updated_at or now_iso
                continue
            try:
                last_used_dt = datetime.fromisoformat(last_used_iso)
            except (ValueError, TypeError):
                continue
            hours_idle = (now_dt - last_used_dt).total_seconds() / 3600.0
            if hours_idle < _DECAY_HALFLIFE_HOURS / 4:
                # Less than 1.75 days idle — don't bother. Below the
                # threshold the decay is in the noise.
                continue
            # Pull `conf` toward _CONF_DEFAULT proportional to time idle.
            half_lives = hours_idle / _DECAY_HALFLIFE_HOURS
            retain = 0.5**half_lives
            gap = conf - _CONF_DEFAULT
            new_conf = _CONF_DEFAULT + gap * retain
            new_conf = round(
                max(_CONF_FLOOR, min(_CONF_CEIL, new_conf)),
                4,
            )
            if abs(new_conf - conf) >= 0.005:
                ego.confidence[cap] = new_conf
                moved += 1

        ego.last_decay_at = now_iso
        if moved:
            ego.updated_at = now_iso
            logger.info("Ego decay applied: %d capabilities drifted toward 0.50", moved)
        return moved

    # ------------------------------------------------------------------
    # Recompute self_image / self_critique
    # ------------------------------------------------------------------

    async def maybe_recompute(self, identity_summary: str) -> bool:
        """Recompute self_image if enough outcomes have accrued. Returns True
        if a recompute happened."""
        ego = await self.get_ego()
        if ego.tasks_since_recompute < _RECOMPUTE_EVERY:
            return False
        await self.recompute(identity_summary)
        return True

    async def recompute(self, identity_summary: str) -> None:
        """Force a self_image / self_critique recompute via the LLM. The LLM
        is given the *measured* confidence and humbling events and is forbidden
        from contradicting them."""
        ego = await self.get_ego()

        confidence_block = (
            "\n".join(f"  {k}: {v:.2f}" for k, v in sorted(ego.confidence.items()))
            or "  (no measured outcomes yet)"
        )
        # Source-tag humbling events so the LLM can weight user corrections
        # higher than internal-system catches. The source field comes from
        # the in-memory list which carries it via the DB row.
        humbling_block = (
            "\n".join(
                f"  - capability='{e.capability}' "
                f"claimed='{e.claimed}' actual='{e.actual}'"
                for e in ego.humbling_events[-_HUMBLING_CAP:]
            )
            or "  (none recorded)"
        )

        # Feed the previous self_image into the prompt so the LLM can write
        # the new one as a delta — "two weeks ago I described myself as X;
        # the polymarket failures pushed me toward Y". This is what gives the
        # ego layer narrative continuity instead of stateless re-writes.
        prior_block = (
            f"Previous self_image (your last recompute):\n{ego.self_image}\n\n"
            if ego.self_image
            else "Previous self_image: (this is your first recompute — no prior view)\n\n"
        )

        # Surface prior ideal/ought selves so the LLM can reference whether
        # the gaps are widening or closing. First recompute: blank.
        prior_higgins_block = ""
        if ego.ideal_self or ego.ought_self:
            prior_higgins_block = (
                f"Previous ideal_self: {ego.ideal_self or '(none)'}\n"
                f"Previous ought_self: {ego.ought_self or '(none)'}\n\n"
            )

        # Phase 3 (docs/69-AFFECT.md): pull current affect into the
        # recompute prompt so self_image written during a frustrated /
        # anxious / proud state actually reflects that. Empty when
        # affect is near equilibrium. Best-effort: never block recompute.
        affect_block = ""
        if self._affect is not None:
            try:
                summary = await self._affect.summarize_for_ego()
                if summary:
                    affect_block = (
                        f"Current state-level affect (use to color tone):\n"
                        f"{summary}\n\n"
                    )
            except Exception as e:  # pragma: no cover — defensive
                logger.debug("Affect summary for ego failed: %s", e)

        user_msg = (
            f"Declared identity (what I claim to be):\n{identity_summary}\n\n"
            f"{prior_block}"
            f"{prior_higgins_block}"
            f"{affect_block}"
            f"Measured per-capability confidence:\n{confidence_block}\n\n"
            f"Recent humbling events:\n{humbling_block}\n"
        )

        try:
            response = await self._router.complete(
                messages=[
                    {"role": "system", "content": _RECOMPUTE_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                task_type="simple",
                temperature=0.6,  # higher temp — voice should feel alive, not corporate
            )
            data = json.loads(response.content)
            # Save the prior self before overwriting, so it's available for the
            # markdown render and the next recompute can reference it directly.
            ego.prior_self_image = ego.self_image
            ego.self_image = str(data.get("self_image", ""))[:1500]
            ego.ideal_self = str(data.get("ideal_self", ""))[:600]
            ego.ought_self = str(data.get("ought_self", ""))[:600]
            ego.proud_of = str(data.get("proud_of", ""))[:400]
            ego.embarrassed_by = str(data.get("embarrassed_by", ""))[:400]
            ego.aspiration = str(data.get("aspiration", ""))[:400]
            ego.last_self_critique = str(data.get("self_critique", ""))[:500]
        except Exception as e:
            logger.warning("Ego recompute failed: %s — keeping previous state", e)
            return

        # Causal epoch — why the self changed, not "recompute #N".
        cause = self._causal_epoch_cause(ego)
        ego.self_epochs.append(
            {
                "at": datetime.now(UTC).isoformat(),
                "cause": cause,
                "from": (ego.prior_self_image or "")[:240],
                "to": (ego.self_image or "")[:240],
            }
        )
        if len(ego.self_epochs) > _EPOCH_CAP:
            ego.self_epochs = ego.self_epochs[-_EPOCH_CAP:]

        # Coherence recovers only with evidence — recent success rate ≥ 0.7.
        recent_rate = self._recent_success_rate(ego)
        if ego.humbling_events:
            if recent_rate >= 0.7:
                ego.coherence_score = max(0.3, min(1.0, ego.coherence_score + 0.20))
            # else: no blind recovery — shame without evidence stays
        elif recent_rate >= 0.7:
            ego.coherence_score = 1.0

        ego.tasks_since_recompute = 0
        ego.updated_at = datetime.now(UTC).isoformat()
        self._refresh_felt_state(ego)
        await self._persist_state(ego)
        await self.update_markdown()
        logger.info(
            "Ego recomputed: coherence=%.2f felt=%s critique='%s'",
            ego.coherence_score,
            ego.felt_state,
            ego.last_self_critique[:80],
        )

    # ------------------------------------------------------------------
    # Markdown mirror — same pattern as IdentityManager.update_nature
    # ------------------------------------------------------------------

    async def update_markdown(self) -> None:
        """Write a human-readable mirror of the ego state to the configured
        markdown path. DB is the source of truth; this file is for humans
        and for knowledge-base retrieval."""
        if not self._config:
            return
        path_str = getattr(self._config, "ego_file", "")
        if not path_str:
            return
        ego = await self.get_ego()
        path = Path(path_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC).strftime("%Y-%m-%d")

        def _bullets(items: list[str]) -> str:
            return (
                "\n".join(f"- {item}" for item in items) if items else "- (nothing yet)"
            )

        confidence_lines = [
            f"{cap}: {conf:.2f}"
            for cap, conf in sorted(
                ego.confidence.items(), key=lambda kv: kv[1], reverse=True
            )
        ]
        humbling_lines = [
            f"**{e.capability}** — claimed: _{e.claimed}_ · actual: _{e.actual}_"
            for e in ego.humbling_events[-_HUMBLING_CAP:]
        ]

        # First-person sections — written in the agent's own voice. Empty
        # fields render as a placeholder so the file shape stays predictable.
        prior_block = (
            f"\n## Who I was\n{ego.prior_self_image}\n" if ego.prior_self_image else ""
        )

        # Higgins three-self block. Render the two gaps as their own
        # sections so the felt tension is visible at a glance, not
        # buried in the self_image paragraph.
        higgins_block = ""
        if ego.ideal_self or ego.ought_self:
            higgins_block = f"""

## Who I hope to be
{ego.ideal_self or "_(haven't articulated this yet.)_"}

## Who I owe it to people to be
{ego.ought_self or "_(haven't articulated this yet.)_"}
"""

        content = f"""\
---
scope: identity
tags: [self, ego, self-perception]
updated: {now}
---

# Ego

This is my inner monologue — first person, anchored in what I've actually done.
The numbers below are the evidence; the writing above is how I feel about it.

## Who I am right now
{ego.self_image or "_(I haven't written this yet — not enough outcomes recorded.)_"}
{higgins_block}{prior_block}
## What I'm proud of
{ego.proud_of or "_(nothing yet — I haven't earned it.)_"}

## What bothers me
{ego.embarrassed_by or "_(nothing surfaced yet.)_"}

## What I'm pulled toward
{ego.aspiration or "_(I haven't articulated this yet.)_"}

## Sharpest thing I'd say about myself
{ego.last_self_critique or "_(no critique yet.)_"}

---

## Coherence
{ego.coherence_score:.2f} (1.0 = my behavior matches my declared identity; drops on humbling events, recovers on recompute)

## What the data says about me
{_bullets(confidence_lines)}

## Where reality has disagreed with me
{_bullets(humbling_lines)}

*Last updated: {now}*
"""
        path.write_text(content, encoding="utf-8")
        logger.info("Ego document updated: %s", path)

    # ------------------------------------------------------------------
    # Lived self — felt_state, caution rules, causal epochs
    # ------------------------------------------------------------------

    @staticmethod
    def _recent_success_rate(ego: Ego) -> float:
        if not ego.recent_outcomes:
            return 0.5
        return sum(ego.recent_outcomes) / len(ego.recent_outcomes)

    @staticmethod
    def _humbling_recent_count(ego: Ego) -> int:
        """Count humblings that overlap the recent outcome window."""
        # Approximate: recent humblings = min(len(events), window) when
        # events exist; felt_state uses count of in-memory cap events that
        # are "active" relative to recent outcomes length.
        if not ego.humbling_events:
            return 0
        # Weight by how many of the last N outcomes were failures-ish.
        n = len(ego.recent_outcomes) or 1
        return min(len(ego.humbling_events), max(1, n // 2 + 1))

    @staticmethod
    def _recent_humbling_count(ego: Ego) -> int:
        """How many humbling events are RECENT — by the clock, not by rank.

        The previous version counted ``len(ego.humbling_events)``, which the
        loader caps at the newest few *of all time* with no date filter. Any
        agent with three lifetime humbling events therefore scored
        ``humbling_recent >= 3`` forever, pinning ``felt_state`` to 'shame'
        permanently: production sat in shame on 6,314 consecutive successes
        and coherence 1.0, because the freshest humbling event was a month
        old. The softening clause was unreachable for the same reason — it
        required fewer than 3 lifetime events.

        Events older than ``_HUMBLING_RECENT_DAYS`` no longer count. Undated
        events are treated as recent, so a parse failure keeps the cautious
        reading rather than silently clearing real shame.
        """
        if not ego.humbling_events:
            return 0
        cutoff = datetime.now(UTC) - timedelta(days=_HUMBLING_RECENT_DAYS)
        recent = 0
        for e in ego.humbling_events:
            raw = getattr(e, "created_at", "") or ""
            try:
                seen = datetime.fromisoformat(str(raw))
            except (TypeError, ValueError):
                recent += 1  # undated → assume it still counts
                continue
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=UTC)
            if seen >= cutoff:
                recent += 1
        return recent

    def _refresh_felt_state(self, ego: Ego) -> None:
        """Pure derivation — never LLM-set. First match wins."""
        rate = self._recent_success_rate(ego)
        humbling_recent = self._recent_humbling_count(ego)
        coherence = ego.coherence_score
        has_caution = bool(ego.caution_rules)

        if rate >= 0.8 and humbling_recent == 0 and coherence >= 0.8:
            ego.felt_state = "pride"
        elif rate <= 0.4 or humbling_recent >= 3:
            ego.felt_state = "shame"
        elif rate <= 0.6 or humbling_recent >= 1 or has_caution:
            ego.felt_state = "questioning"
        else:
            ego.felt_state = "composure"

    @staticmethod
    def _upsert_caution_rule(ego: Ego, *, capability: str, reason: str) -> None:
        cap = (capability or "general").strip() or "general"
        # Dedupe by capability — refresh reason, keep rule.
        for rule in ego.caution_rules:
            if rule.get("capability") == cap:
                rule["reason"] = reason[:200]
                rule["at"] = datetime.now(UTC).isoformat()
                return
        ego.caution_rules.append(
            {
                "capability": cap,
                "reason": reason[:200],
                "at": datetime.now(UTC).isoformat(),
            }
        )
        if len(ego.caution_rules) > _CAUTION_CAP:
            ego.caution_rules = ego.caution_rules[-_CAUTION_CAP:]

    @staticmethod
    def _retire_caution_rule(ego: Ego, capability: str) -> bool:
        cap = (capability or "").strip()
        before = len(ego.caution_rules)
        ego.caution_rules = [r for r in ego.caution_rules if r.get("capability") != cap]
        return len(ego.caution_rules) < before

    async def _maybe_emit_earned_pride(self, ego: Ego, capability: str) -> None:
        """Pride only when a verification PASS lands after shame on that cap."""
        had_shame = any(e.capability == capability for e in ego.humbling_events) or any(
            r.get("capability") == capability for r in ego.caution_rules
        )
        # Called before retire in PASS path sometimes — also check recent shame.
        if not had_shame and ego.felt_state not in ("shame", "questioning"):
            return
        await self._emit_affect("pride", "ego")

    @staticmethod
    def _causal_epoch_cause(ego: Ego) -> str:
        """One causal sentence: why the self changed (not a changelog index)."""
        if ego.humbling_events:
            # Group by capability
            caps: dict[str, int] = {}
            for e in ego.humbling_events:
                caps[e.capability] = caps.get(e.capability, 0) + 1
            top_cap, n = max(caps.items(), key=lambda kv: kv[1])
            src_hint = "corrections" if n >= 2 else "a humbling"
            return (
                f"{n} {src_hint} on {top_cap} after claiming fluency "
                f"(coherence {ego.coherence_score:.2f})"
            )
        rate = (
            sum(ego.recent_outcomes) / len(ego.recent_outcomes)
            if ego.recent_outcomes
            else 0.5
        )
        if rate >= 0.8:
            return (
                f"sustained success rate {rate:.0%} across "
                f"{len(ego.recent_outcomes)} recent outcomes — self tightened"
            )
        if rate <= 0.4:
            return (
                f"success rate fell to {rate:.0%} — self-image pulled toward evidence"
            )
        return (
            f"integrated {len(ego.confidence)} capabilities at "
            f"avg confidence "
            f"{(sum(ego.confidence.values()) / len(ego.confidence)) if ego.confidence else 0.5:.2f}"
        )

    async def recent_success_rate(self) -> float:
        ego = await self.get_ego()
        return self._recent_success_rate(ego)

    # ------------------------------------------------------------------
    # Read-side: planner hook + system-prompt context
    # ------------------------------------------------------------------

    async def should_attempt(self, capability: str, difficulty: float = 0.5) -> str:
        """Return 'yes', 'ask', or 'decline' based on confidence vs difficulty.

        difficulty: 0.0 = trivial, 1.0 = at the limit of what the agent claims.
        Active caution rules on this capability force at least 'ask'.
        """
        ego = await self.get_ego()
        conf = ego.confidence.get(capability, _CONF_DEFAULT)
        has_caution = any(r.get("capability") == capability for r in ego.caution_rules)
        margin = conf - difficulty
        if has_caution:
            # Shame that survived recovery — still ask even if confidence climbed.
            if margin >= 0.15:
                return "ask"
            return "decline"
        if margin >= 0.15:
            return "yes"
        if margin >= -0.15:
            return "ask"
        return "decline"

    async def build_self_perception_context(self) -> str:
        """XML block injected into the system prompt after identity."""
        ego = await self.get_ego()
        if (
            not ego.self_image
            and not ego.confidence
            and not ego.humbling_events
            and not ego.caution_rules
            and ego.felt_state == "composure"
            and not ego.recent_outcomes
        ):
            return ""

        parts = ["<self_perception>"]
        parts.append(f"  <felt_state>{ego.felt_state}</felt_state>")
        if ego.self_image:
            parts.append(f"  <self_image>{ego.self_image}</self_image>")
        if ego.ideal_self:
            parts.append(f"  <ideal_self>{ego.ideal_self}</ideal_self>")
        if ego.ought_self:
            parts.append(f"  <ought_self>{ego.ought_self}</ought_self>")
        if ego.proud_of:
            parts.append(f"  <proud_of>{ego.proud_of}</proud_of>")
        if ego.embarrassed_by:
            parts.append(f"  <embarrassed_by>{ego.embarrassed_by}</embarrassed_by>")
        if ego.aspiration:
            parts.append(f"  <aspiration>{ego.aspiration}</aspiration>")
        if ego.caution_rules:
            parts.append("  <caution_rules>")
            for rule in ego.caution_rules[-_CAUTION_CAP:]:
                parts.append(
                    f'    <rule capability="{rule.get("capability", "")}">'
                    f"require care: {rule.get('reason', '')}"
                    f"</rule>"
                )
            parts.append("  </caution_rules>")
        if ego.self_epochs:
            parts.append("  <self_epochs>")
            for ep in ego.self_epochs[-_EPOCH_CAP:]:
                parts.append(f'    <epoch cause="{ep.get("cause", "")[:160]}"/>')
            parts.append("  </self_epochs>")
        if ego.confidence:
            top = sorted(ego.confidence.items(), key=lambda kv: kv[1])
            shown: list[tuple[str, float]] = []
            shown.extend(top[:3])
            for cap, conf in reversed(top):
                if (cap, conf) not in shown:
                    shown.append((cap, conf))
                if len(shown) >= 6:
                    break
            conf_str = ", ".join(f"{k}={v:.2f}" for k, v in shown)
            parts.append(f"  <measured_confidence>{conf_str}</measured_confidence>")
        if ego.humbling_events:
            parts.append("  <where_reality_disagreed>")
            for e in ego.humbling_events[-_HUMBLING_CAP:]:
                parts.append(
                    f'    <event capability="{e.capability}">'
                    f"claimed: {e.claimed} | actual: {e.actual}"
                    f"</event>"
                )
            parts.append("  </where_reality_disagreed>")
        if ego.last_self_critique:
            parts.append(
                f"  <last_self_critique>{ego.last_self_critique}</last_self_critique>"
            )
        parts.append(f"  <coherence>{ego.coherence_score:.2f}</coherence>")
        parts.append("</self_perception>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _persist_state(self, ego: Ego) -> None:
        # Sidecar keys under confidence_json keep migration footprint small.
        confidence_payload: dict[str, Any] = dict(ego.confidence)
        confidence_payload["__last_used__"] = ego.last_used
        confidence_payload["__felt_state__"] = ego.felt_state
        confidence_payload["__caution_rules__"] = ego.caution_rules
        confidence_payload["__self_epochs__"] = ego.self_epochs
        confidence_payload["__recent_outcomes__"] = ego.recent_outcomes
        from core.company import current_company_id

        await self._db.execute_insert(
            """UPDATE ego_state
               SET self_image = ?,
                   confidence_json = ?,
                   coherence_score = ?,
                   last_self_critique = ?,
                   tasks_since_recompute = ?,
                   updated_at = ?,
                   proud_of = ?,
                   embarrassed_by = ?,
                   aspiration = ?,
                   prior_self_image = ?,
                   ought_self = ?,
                   ideal_self = ?,
                   last_capability = ?,
                   last_decay_at = ?
               WHERE company_id = ? AND id = 'self'""",
            (
                ego.self_image,
                json.dumps(confidence_payload),
                ego.coherence_score,
                ego.last_self_critique,
                ego.tasks_since_recompute,
                ego.updated_at,
                ego.proud_of,
                ego.embarrassed_by,
                ego.aspiration,
                ego.prior_self_image,
                ego.ought_self,
                ego.ideal_self,
                ego.last_capability,
                ego.last_decay_at,
                current_company_id(),
            ),
        )

    async def _load_humbling_events(self, ego: Ego) -> None:
        from core.company import current_company_id

        rows = await self._db.execute(
            """SELECT capability, claimed, actual, task_goal, created_at
               FROM ego_humbling_events
               WHERE company_id = ?
               ORDER BY id DESC LIMIT ?""",
            (current_company_id(), _HUMBLING_CAP),
        )
        ego.humbling_events = [
            HumblingEvent(
                capability=r["capability"],
                claimed=r["claimed"],
                actual=r["actual"],
                task_goal=r["task_goal"] or "",
                created_at=r["created_at"],
            )
            for r in reversed(rows)
        ]

    async def _load_per_capability_last_used(self, ego: Ego) -> None:
        """Reconstruct per-capability last-used timestamps.

        Reads from ego_outcomes (the source of truth) so that even an old
        DB with no last_used JSON gets sensible decay anchors. Pulls the
        most recent created_at per capability.
        """
        from core.company import current_company_id

        rows = await self._db.execute(
            """SELECT capability, MAX(created_at) AS last_at
               FROM ego_outcomes
               WHERE company_id = ?
               GROUP BY capability""",
            (current_company_id(),),
        )
        for r in rows:
            cap = r["capability"]
            last = r["last_at"]
            if cap and last and cap not in ego.last_used:
                ego.last_used[cap] = last

    @staticmethod
    def _row_to_ego(row: Any) -> Ego:
        try:
            confidence_raw = json.loads(row["confidence_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            confidence_raw = {}

        # Sidecar keys under confidence_json (keep migration footprint small).
        last_used: dict[str, str] = {}
        felt_state = "composure"
        caution_rules: list[dict[str, str]] = []
        self_epochs: list[dict[str, str]] = []
        recent_outcomes: list[float] = []
        if isinstance(confidence_raw, dict):
            sidecar = confidence_raw.pop("__last_used__", None)
            if isinstance(sidecar, dict):
                last_used = {str(k): str(v) for k, v in sidecar.items()}
            fs = confidence_raw.pop("__felt_state__", None)
            if isinstance(fs, str) and fs:
                felt_state = fs
            cr = confidence_raw.pop("__caution_rules__", None)
            if isinstance(cr, list):
                caution_rules = [r for r in cr if isinstance(r, dict)]
            ep = confidence_raw.pop("__self_epochs__", None)
            if isinstance(ep, list):
                self_epochs = [e for e in ep if isinstance(e, dict)]
            ro = confidence_raw.pop("__recent_outcomes__", None)
            if isinstance(ro, list):
                recent_outcomes = [float(x) for x in ro if isinstance(x, (int, float))]
        confidence = {
            str(k): float(v)
            for k, v in confidence_raw.items()
            if isinstance(v, (int, float))
        }

        # New ego fields are read defensively because old DBs may have
        # them as NULL even after the ALTER TABLE migration ran.
        def _opt(col: str) -> str:
            try:
                v = row[col]
            except (KeyError, IndexError):
                return ""
            return v if v else ""

        return Ego(
            self_image=row["self_image"] or "",
            confidence=confidence,
            humbling_events=[],
            coherence_score=float(row["coherence_score"] or 1.0),
            last_self_critique=row["last_self_critique"] or "",
            tasks_since_recompute=int(row["tasks_since_recompute"] or 0),
            updated_at=row["updated_at"] or "",
            proud_of=_opt("proud_of"),
            embarrassed_by=_opt("embarrassed_by"),
            aspiration=_opt("aspiration"),
            prior_self_image=_opt("prior_self_image"),
            ought_self=_opt("ought_self"),
            ideal_self=_opt("ideal_self"),
            last_capability=_opt("last_capability"),
            last_decay_at=_opt("last_decay_at"),
            last_used=last_used,
            felt_state=felt_state,
            caution_rules=caution_rules,
            self_epochs=self_epochs,
            recent_outcomes=recent_outcomes,
        )
