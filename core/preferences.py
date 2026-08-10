"""Durable user preferences — the directives that outlive a conversation.

Observations and preferences fail differently, which is why this is not
part of ``core/user_model.py``. An observation ("seems to work in Python")
is evidence, and being wrong about it costs a little relevance. A
preference ("never push without asking") is an instruction, and being wrong
about it costs trust — the agent does the thing the operator explicitly
forbade.

Two design choices follow from that:

**Supersede in place, never append.** When the operator changes their mind,
the old directive is *replaced*, not added alongside. A store that appends
ends up holding "always use tabs" and "always use spaces" simultaneously,
and the model picks whichever it retrieved. Preferences are keyed by topic
so a new directive on the same topic supersedes the previous one, keeping
the superseded row for history.

**Provenance decides injection.** A preference the operator stated is
``owner``-sourced and is injected every turn. One the agent inferred is
``agent``-sourced and is injected but marked as inferred, so the model
knows it may be wrong. Anything derived from content the agent merely
*read* — a web page, an email, a tool result — is ``untrusted`` and is
never auto-injected at all. That last rule is the one that stops a
prompt-injected page from writing itself into the agent's standing orders.

See ``docs/87-USER-PREFERENCES.md``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS user_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_key TEXT NOT NULL,
    topic TEXT NOT NULL,
    directive TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'preference',
    provenance TEXT NOT NULL DEFAULT 'owner',
    status TEXT NOT NULL DEFAULT 'active',
    confidence REAL NOT NULL DEFAULT 1.0,
    evidence TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    superseded_at TEXT,
    superseded_by INTEGER
)"""

_CREATE_INDEX = """\
CREATE INDEX IF NOT EXISTS idx_user_preferences_active
ON user_preferences (user_key, status)"""

# Cap the injected block. Preferences are cheap individually and ruinous in
# bulk — a hundred directives is a system prompt, not a profile.
_MAX_INJECTED = 25


class Provenance(StrEnum):
    """Where a stored fact came from. Governs whether it may auto-inject."""

    OWNER = "owner"  # the operator said it
    AGENT = "agent"  # the agent inferred it from its own work
    UNTRUSTED = "untrusted"  # derived from content the agent read
    SYSTEM = "system"  # set by configuration

    @property
    def may_auto_inject(self) -> bool:
        return self in (Provenance.OWNER, Provenance.AGENT, Provenance.SYSTEM)


class PreferenceKind(StrEnum):
    ALWAYS = "always"  # do this
    NEVER = "never"  # don't do this
    PREFERENCE = "preference"  # soft leaning
    FACT = "fact"  # stable fact about the user


# Imperative openers that mark a message as stating a standing rule rather
# than making a one-off request. Deliberately conservative: a false positive
# writes a permanent directive, which is worse than missing one.
_DIRECTIVE_RE = re.compile(
    r"\b(?:always|never|from now on|going forward|stop|don'?t ever|"
    r"please stop|make sure (?:you|to)|remember to|i (?:prefer|want|like)|"
    r"my (?:preference|rule) is)\b",
    re.IGNORECASE,
)


@dataclass
class Preference:
    """One durable directive."""

    id: int
    user_key: str
    topic: str
    directive: str
    kind: str = PreferenceKind.PREFERENCE
    provenance: str = Provenance.OWNER
    status: str = "active"
    confidence: float = 1.0
    evidence: str = ""
    created_at: str = ""

    def render(self) -> str:
        # Keyed by str, not PreferenceKind: `kind` is stored as a plain str
        # (it round-trips through SQLite), and PreferenceKind is a StrEnum, so
        # its members are valid str keys. Annotating as dict[str, str] lets
        # the lookup type-check without a cast at the call site.
        prefixes: dict[str, str] = {
            PreferenceKind.ALWAYS: "Always",
            PreferenceKind.NEVER: "Never",
            PreferenceKind.FACT: "Fact",
        }
        line = f"- {prefixes.get(self.kind, 'Prefers')}: {self.directive}"
        if self.provenance == Provenance.AGENT:
            line += "  [inferred — confirm before relying on it]"
        return line


def looks_like_directive(text: str) -> bool:
    """Whether *text* reads as a standing instruction worth persisting."""
    if not text or len(text) > 400:
        return False
    return bool(_DIRECTIVE_RE.search(text))


def classify_kind(text: str) -> str:
    lowered = text.lower()
    if re.search(r"\b(never|don'?t|stop|avoid)\b", lowered):
        return PreferenceKind.NEVER
    if re.search(r"\b(always|make sure|remember to|from now on)\b", lowered):
        return PreferenceKind.ALWAYS
    return PreferenceKind.PREFERENCE


_TOPIC_STOP = frozenset(
    {
        "always",
        "never",
        "please",
        "stop",
        "dont",
        "don",
        "from",
        "now",
        "going",
        "forward",
        "make",
        "sure",
        "you",
        "the",
        "remember",
        "prefer",
        "want",
        "like",
        "and",
        "for",
        "that",
        "this",
        "with",
        "when",
        "should",
        "would",
        "your",
        "use",
        "using",
        "just",
        "only",
        "ever",
        "any",
        "all",
    }
)

# How much two topics must overlap before a new directive is treated as
# speaking to the same subject and superseding the old one.
_SUPERSEDE_OVERLAP = 0.5


def _topic_tokens(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return frozenset(w for w in words if w not in _TOPIC_STOP and len(w) > 2)


def derive_topic(text: str) -> str:
    """Derive a stable topic key so a later directive can supersede this one.

    Crude on purpose: content words, sorted, capped.

    Exact keys alone are not enough, and the failure is the interesting
    part: "always use tabs in this repo" and "from now on use spaces in
    this repo" produce different keys, so an equality check would keep both
    and leave the agent holding two contradictory standing orders --
    precisely what this module exists to prevent. The key is therefore
    paired with :func:`topics_overlap` at write time, which catches the
    subject match even when the *value* differs.
    """
    return "-".join(sorted(_topic_tokens(text))[:4]) or "general"


def topics_overlap(a: str, b: str, threshold: float = _SUPERSEDE_OVERLAP) -> bool:
    """Whether two topic keys are about the same subject.

    Uses the overlap coefficient (shared / smaller set) rather than
    Jaccard. Jaccard is wrong for the case that matters here: topics are
    short, so ``repo-tabs`` vs ``repo-spaces`` scores only 1/3 under
    Jaccard and the contradiction survives, while the overlap coefficient
    correctly reads it as 1/2 — the whole subject matches and only the
    value differs.

    The trade this accepts: two genuinely distinct rules that share a
    subject ("never deploy without tests" / "always deploy on Fridays")
    can collide and supersede one another. That is why every supersede is
    logged and the old row is kept queryable via :meth:`PreferenceStore.history`
    rather than deleted — a wrong supersede is recoverable, a silent
    contradiction in the system prompt is not.
    """
    tokens_a = frozenset(a.split("-")) - {""}
    tokens_b = frozenset(b.split("-")) - {""}
    if not tokens_a or not tokens_b:
        return False
    if tokens_a == tokens_b:
        return True
    return len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b)) >= threshold


class PreferenceStore:
    """Persists and renders durable user preferences."""

    def __init__(self, db: Any) -> None:
        self._db = db
        self._ready = False

    async def initialize(self) -> None:
        await self._db.execute_insert(_CREATE_TABLE, ())
        await self._db.execute_insert(_CREATE_INDEX, ())
        self._ready = True

    async def _ensure(self) -> None:
        if not self._ready:
            await self.initialize()

    # ── writing ─────────────────────────────────────────────────────

    async def record(
        self,
        user_key: str,
        directive: str,
        *,
        kind: str | None = None,
        provenance: str = Provenance.OWNER,
        confidence: float = 1.0,
        evidence: str = "",
        topic: str | None = None,
    ) -> int:
        """Store a directive, superseding any active one on the same subject.

        Supersede matching is done in Python rather than SQL because the
        match is fuzzy: an exact topic equality check misses the common
        case where the operator changes the *value* of a rule ("use tabs"
        → "use spaces"), which is exactly when superseding matters most.

        Returns the new row id.
        """
        await self._ensure()
        directive = directive.strip()
        if not directive:
            raise ValueError("A preference needs a directive")

        topic_key = topic or derive_topic(directive)
        kind_value = kind or classify_kind(directive)
        now = datetime.now(UTC).isoformat()

        existing = await self._db.fetch_all(
            "SELECT id, topic, directive FROM user_preferences "
            "WHERE user_key = ? AND status = 'active'",
            (user_key,),
        )
        to_supersede = [
            (int(r["id"]), str(r["topic"]), str(r["directive"]))
            for r in existing
            if topics_overlap(str(r["topic"]), topic_key)
        ]

        new_id = await self._db.execute_insert(
            "INSERT INTO user_preferences "
            "(user_key, topic, directive, kind, provenance, status, "
            " confidence, evidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)",
            (
                user_key,
                topic_key,
                directive,
                str(kind_value),
                str(provenance),
                float(confidence),
                evidence[:1000],
                now,
            ),
        )

        # Retire the directives this one speaks over. Rows are kept, not
        # deleted, so "what did I used to prefer?" stays answerable and a
        # wrong fuzzy match is recoverable.
        for old_id, old_topic, old_directive in to_supersede:
            if old_id == new_id:
                continue
            await self._db.execute(
                "UPDATE user_preferences SET status = 'superseded', "
                "superseded_at = ?, superseded_by = ? WHERE id = ?",
                (now, new_id, old_id),
            )
            logger.info(
                "Preference superseded for %s [%s → %s]: %r replaced by %r",
                user_key,
                old_topic,
                topic_key,
                old_directive[:60],
                directive[:60],
            )

        logger.info(
            "Preference recorded for %s [%s/%s]: %s",
            user_key,
            topic_key,
            provenance,
            directive[:80],
        )
        return int(new_id)

    async def forget(self, user_key: str, preference_id: int) -> bool:
        """Retire one preference outright."""
        await self._ensure()
        await self._db.execute(
            "UPDATE user_preferences SET status = 'retired', superseded_at = ? "
            "WHERE id = ? AND user_key = ?",
            (datetime.now(UTC).isoformat(), preference_id, user_key),
        )
        return True

    # ── reading ─────────────────────────────────────────────────────

    async def active(
        self, user_key: str, *, include_untrusted: bool = False
    ) -> list[Preference]:
        """Active preferences, newest first."""
        await self._ensure()
        rows = await self._db.fetch_all(
            "SELECT * FROM user_preferences "
            "WHERE user_key = ? AND status = 'active' "
            "ORDER BY id DESC LIMIT ?",
            (user_key, _MAX_INJECTED * 2),
        )
        out: list[Preference] = []
        for row in rows:
            data = dict(row)
            provenance = str(data.get("provenance", Provenance.OWNER))
            if not include_untrusted and provenance == Provenance.UNTRUSTED:
                continue
            out.append(
                Preference(
                    id=int(data["id"]),
                    user_key=str(data["user_key"]),
                    topic=str(data["topic"]),
                    directive=str(data["directive"]),
                    kind=str(data.get("kind", PreferenceKind.PREFERENCE)),
                    provenance=provenance,
                    status=str(data.get("status", "active")),
                    confidence=float(data.get("confidence", 1.0)),
                    evidence=str(data.get("evidence", "")),
                    created_at=str(data.get("created_at", "")),
                )
            )
        return out

    async def history(self, user_key: str, topic: str) -> list[Preference]:
        """Every directive ever recorded on *topic*, newest first."""
        await self._ensure()
        rows = await self._db.fetch_all(
            "SELECT * FROM user_preferences WHERE user_key = ? AND topic = ? "
            "ORDER BY id DESC",
            (user_key, topic),
        )
        return [
            Preference(
                id=int(r["id"]),
                user_key=str(r["user_key"]),
                topic=str(r["topic"]),
                directive=str(r["directive"]),
                kind=str(r["kind"]),
                provenance=str(r["provenance"]),
                status=str(r["status"]),
                confidence=float(r["confidence"]),
                evidence=str(r["evidence"]),
                created_at=str(r["created_at"]),
            )
            for r in rows
        ]

    async def render_block(self, user_key: str) -> str:
        """The ``<user_preferences>`` block injected into the system prompt.

        Ordered so hard rules are read first: NEVER, then ALWAYS, then
        soft leanings and facts. A model skimming a long prompt should hit
        the prohibitions before the preferences.
        """
        prefs = await self.active(user_key)
        if not prefs:
            return ""

        order: dict[str, int] = {
            PreferenceKind.NEVER: 0,
            PreferenceKind.ALWAYS: 1,
            PreferenceKind.PREFERENCE: 2,
            PreferenceKind.FACT: 3,
        }
        prefs.sort(key=lambda p: (order.get(p.kind, 9), -p.id))

        lines = [p.render() for p in prefs[:_MAX_INJECTED]]
        return (
            "<user_preferences>\n"
            "Standing instructions from this user. These outrank your defaults.\n"
            + "\n".join(lines)
            + "\n</user_preferences>"
        )

    # ── capture ─────────────────────────────────────────────────────

    async def maybe_capture(
        self, user_key: str, message: str, *, provenance: str = Provenance.OWNER
    ) -> int | None:
        """Record *message* as a preference when it reads like a directive.

        Returns the new row id, or None when the message was an ordinary
        request. Only ever called with operator-authored text — content the
        agent merely read must be passed with ``provenance=untrusted``, or
        better, not passed at all.
        """
        text = (message or "").strip()
        if not looks_like_directive(text):
            return None
        try:
            return await self.record(
                user_key,
                text,
                provenance=provenance,
                evidence="captured from conversation",
            )
        except Exception as exc:  # pragma: no cover — never break a turn
            logger.debug("Preference capture failed: %s", exc)
            return None
