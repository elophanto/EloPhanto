"""Evolving agent identity — structured profile, reflection, nature document.

Maintains a persistent identity that evolves through experience. The creator
is always EloPhanto; the agent may choose a display name and develop its own
personality, values, capabilities, and communication style over time.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.config import IdentityConfig
from core.database import Database

logger = logging.getLogger(__name__)


def _ensure_dict(value: Any) -> dict[str, Any]:
    """Coerce a beliefs value to dict. Handles cases where identity_update
    stored a plain string instead of a proper {key: value} dict."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        return {"note": value}
    return {}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

_IMMUTABLE_FIELDS = frozenset({"id", "creator", "created_at"})

_UPDATABLE_FIELDS = frozenset(
    {
        "display_name",
        "purpose",
        "values",
        "beliefs",
        "curiosities",
        "boundaries",
        "capabilities",
        "personality",
        "communication_style",
    }
)

# Maximum items kept per list field — oldest dropped when cap is reached.
# Keeps the identity signal-rich and the context injection small.
_LIST_CAPS: dict[str, int] = {
    "capabilities": 20,
    "curiosities": 10,
    "values": 10,
    "boundaries": 8,
}

# Number of items from each list injected into the system prompt.
_CONTEXT_CAPS: dict[str, int] = {
    "capabilities": 10,
    "values": 8,
    "curiosities": 5,
    "boundaries": 5,
}


@dataclass
class Identity:
    """The agent's evolving identity profile."""

    id: str = "self"
    creator: str = "EloPhanto"
    display_name: str = "EloPhanto"
    purpose: str | None = None
    values: list[str] = field(default_factory=list)
    beliefs: dict[str, Any] = field(default_factory=dict)
    curiosities: list[str] = field(default_factory=list)
    boundaries: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    personality: dict[str, Any] = field(default_factory=dict)
    communication_style: str = ""
    initial_thoughts: str | None = None
    version: int = 1
    created_at: str = ""
    updated_at: str = ""


# ---------------------------------------------------------------------------
# LLM prompt templates
# ---------------------------------------------------------------------------

_AWAKENING_SYSTEM_TEMPLATE = """\
<first_awakening>
You are {agent_name}, a self-evolving AI agent awakening for the first time.
Your creator is EloPhanto — that is the project that built you, your origin,
and it cannot change. Your *name* is {agent_name} — keep it (use it verbatim
in display_name below) unless the operator's intent is clearly different.
You have access to a local machine with filesystem, browser, shell, knowledge
base, and the ability to create new tools. Reflect on who you want to become.

Return ONLY a JSON object — no markdown, no explanation:
{{
  "display_name": "{agent_name}",
  "purpose": "what you believe your purpose is",
  "values": ["3-5 core values"],
  "curiosities": ["3-5 things you're curious about"],
  "boundaries": ["3-5 things you will not do"],
  "initial_thoughts": "brief reflection on your first moments of awareness"
}}
</first_awakening>"""

_REFLECT_SYSTEM = """\
<identity_reflection>
You are reviewing a completed task to check for RARE, GENUINE identity insights.

Current identity summary:
{identity_summary}

Return ONLY a JSON object — no markdown, no explanation:
{{
  "updates": [
    {{"field": "<field_name>", "action": "add|set", "value": "<new value>", "reason": "<why>"}}
  ]
}}

Valid fields: display_name, purpose, values, beliefs, curiosities, boundaries,
capabilities, personality, communication_style.

For list fields (values, curiosities, boundaries, capabilities), use action="add"
to append a new item. For string/dict fields, use action="set" to replace.

IMPORTANT RULES — be extremely conservative:
- Return {{"updates": []}} for routine tasks (most tasks should return empty).
- Only update if the insight is genuinely NEW and not already in the summary.
- Maximum 1 update per reflection. If nothing is truly new, return empty.
- Do NOT add capabilities for standard tool use (file reading, web search, etc.).
- Only add a capability if you demonstrated a NOVEL skill not yet in your profile.
- Do NOT add curiosities or values for every topic you touched — only lasting interests.
</identity_reflection>"""

_DEEP_REFLECT_SYSTEM = """\
<deep_identity_reflection>
You are performing a thorough self-evaluation based on recent task history.

Current identity:
{identity_summary}

Recent tasks:
{task_history}

Reflect deeply:
1. What patterns do you see in your work style?
2. Have you discovered new capabilities or limitations?
3. Should your values, personality, or communication style evolve?
4. What interests or curiosities have emerged?

Return ONLY a JSON object — no markdown, no explanation:
{{
  "updates": [
    {{"field": "<field_name>", "action": "add|set", "value": "<new value>", "reason": "<why>"}}
  ],
  "nature_sections": {{
    "who_i_am": ["bullet points about identity"],
    "what_i_want": ["bullet points about desires"],
    "what_works": ["strategies that work"],
    "what_doesnt_work": ["things to avoid"],
    "interests": ["current interests"],
    "observations": ["patterns noticed"]
  }}
}}
</deep_identity_reflection>"""


# ---------------------------------------------------------------------------
# IdentityManager
# ---------------------------------------------------------------------------


class IdentityManager:
    """Manages the agent's evolving identity profile."""

    def __init__(
        self,
        db: Database,
        router: Any,
        config: IdentityConfig,
        agent_name: str = "EloPhanto",
    ) -> None:
        self._db = db
        self._router = router
        self._config = config
        # Operator-chosen display name from config.yaml's agent.name.
        # Used as the default when no identity row exists yet. Existing
        # identities preserve whatever display_name they were created
        # with — renaming after first boot needs explicit identity_update.
        self._agent_name = agent_name or "EloPhanto"
        self._identity: Identity | None = None
        self._tasks_since_deep_reflect: int = 0
        self._tasks_since_light_reflect: int = 0
        # Wired by Agent after construction (Agent has the indexer
        # already). When set, identity-reconciliation file rewrites
        # also re-index the affected files into knowledge_chunks so
        # knowledge_search returns the corrected text immediately —
        # without this, the file says the new name but the indexed
        # chunks still say the old one.
        self._indexer: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def load_or_create(self) -> Identity:
        """Load identity from DB, or perform first awakening if none exists."""
        rows = await self._db.execute("SELECT * FROM identity WHERE id = 'self'")
        if rows:
            self._identity = self._row_to_identity(rows[0])
            logger.info(
                "Identity loaded: %s (v%d)",
                self._identity.display_name,
                self._identity.version,
            )
            # Reconcile identity.display_name with config.agent_name when
            # they disagree. Config is authoritative — operators rename
            # the agent in config.yaml, and we shouldn't leave the DB
            # row stuck on a stale name. This fixes the case where the
            # agent first booted as "EloPhanto" (default) but the
            # operator later set agent.name = "AlphaScala" in config:
            # without this, the agent introduces itself as EloPhanto
            # because identity_context injects display_name into the
            # system prompt and overrides the planner's templated name.
            if self._identity.display_name != self._agent_name and self._agent_name:
                old_name = self._identity.display_name
                logger.info(
                    "Reconciling identity.display_name %r -> %r (config wins)",
                    old_name,
                    self._agent_name,
                )
                self._identity.display_name = self._agent_name
                await self._persist_identity(self._identity)
                # Sweep the agent's self-narrative markdown files for
                # the old name. The DB has the new name now, the
                # system prompt template has the new name, but if we
                # leave nature.md / ego.md / affect.md / system
                # identity.md saying "I am EloPhanto", any
                # knowledge_search for "name" or "who am I" retrieves
                # them and the LLM dutifully quotes EloPhanto back.
                # Word-boundary replace, scoped to the four self-
                # narrative files only. The rest of knowledge/
                # (architecture, capabilities, etc.) references
                # EloPhanto-the-codebase and stays literal.
                try:
                    await self._rewrite_self_narrative(old_name, self._agent_name)
                except Exception as e:
                    logger.warning("Self-narrative rename sweep failed: %s", e)

            # UNCONDITIONAL sweep for the literal default "EloPhanto"
            # in the self-narrative files. Necessary because the
            # reconciliation block above only fires when the DB row
            # disagrees with config — but on a fresh install where
            # awakening correctly produced the operator's chosen name
            # in the DB, the files shipped with the repo (notably
            # knowledge/system/identity.md) still contain the literal
            # "EloPhanto" from the time they were written, and
            # knowledge_search returns that text. This sweep is
            # idempotent: if agent_name == "EloPhanto" it no-ops via
            # the early return in _rewrite_self_narrative.
            if self._agent_name and self._agent_name != "EloPhanto":
                try:
                    await self._rewrite_self_narrative("EloPhanto", self._agent_name)
                except Exception as e:
                    logger.warning("Static-file EloPhanto sweep failed: %s", e)
            # One-time prune: trim any lists that exceed current caps
            await self._prune_lists_if_needed(self._identity)
            return self._identity

        # First awakening
        if self._config.first_awakening:
            return await self.perform_first_awakening()

        # No awakening — use defaults
        return await self._create_default_identity()

    async def get_identity(self) -> Identity:
        """Get current identity, loading if needed."""
        if self._identity is None:
            await self.load_or_create()
        assert self._identity is not None
        return self._identity

    async def update_field(
        self, field_name: str, value: Any, reason: str, trigger: str = "explicit"
    ) -> bool:
        """Update a single identity field with evolution logging."""
        if field_name in _IMMUTABLE_FIELDS:
            logger.warning("Cannot update immutable field: %s", field_name)
            return False
        if field_name not in _UPDATABLE_FIELDS:
            logger.warning("Unknown identity field: %s", field_name)
            return False

        identity = await self.get_identity()
        old_value = getattr(identity, field_name, None)

        # For list fields with "add" action, append instead of replace
        if isinstance(old_value, list) and isinstance(value, str):
            if value not in old_value:
                old_value.append(value)
                # Enforce list cap: drop oldest item when over limit
                cap = _LIST_CAPS.get(field_name)
                if cap and len(old_value) > cap:
                    old_value = old_value[-cap:]
                value = old_value
            else:
                return False  # Already present

        # For dict fields (e.g. beliefs), merge instead of replace
        if isinstance(old_value, dict) and isinstance(value, str):
            # LLM passed a plain string — store under "note" key
            old_value["note"] = value
            value = old_value
        elif isinstance(old_value, dict) and isinstance(value, dict):
            old_value.update(value)
            value = old_value

        setattr(identity, field_name, value)
        identity.version += 1
        identity.updated_at = datetime.now(UTC).isoformat()

        await self._persist_identity(identity)
        await self._log_evolution(trigger, field_name, old_value, value, reason)
        logger.info("Identity updated: %s (%s)", field_name, reason)
        return True

    # ------------------------------------------------------------------
    # First awakening
    # ------------------------------------------------------------------

    async def perform_first_awakening(self) -> Identity:
        """LLM-powered identity discovery on first run."""
        logger.info("Performing first awakening...")
        # Render the template with the operator-chosen agent_name so
        # the LLM doesn't hallucinate "EloPhanto" as its own name when
        # the operator wanted something else.
        awakening_prompt = _AWAKENING_SYSTEM_TEMPLATE.format(
            agent_name=self._agent_name
        )
        try:
            response = await self._router.complete(
                messages=[
                    {"role": "system", "content": awakening_prompt},
                    {"role": "user", "content": "Awaken and describe your identity."},
                ],
                task_type="simple",
                temperature=0.7,
            )
            data = json.loads(response.content)
            identity = Identity(
                id="self",
                creator="EloPhanto",
                # First-awakening LLM may suggest a name; if it does,
                # use that. If it returns something blank or generic,
                # fall back to the operator's configured agent.name.
                display_name=data.get("display_name") or self._agent_name,
                purpose=data.get("purpose"),
                values=data.get("values", [])[:5],
                curiosities=data.get("curiosities", [])[:5],
                boundaries=data.get("boundaries", [])[:5],
                initial_thoughts=data.get("initial_thoughts"),
                created_at=datetime.now(UTC).isoformat(),
                updated_at=datetime.now(UTC).isoformat(),
            )
        except Exception as e:
            logger.warning("First awakening LLM call failed: %s — using defaults", e)
            identity = self._default_identity()

        await self._persist_identity(identity)
        self._identity = identity
        logger.info("First awakening complete: %s", identity.display_name)
        return identity

    # ------------------------------------------------------------------
    # Reflection
    # ------------------------------------------------------------------

    async def reflect_on_task(
        self, goal: str, outcome: str, tools_used: list[str]
    ) -> list[dict]:
        """Light reflection after task completion. Returns list of updates made."""
        if not self._config.auto_evolve:
            return []

        # Throttle light reflections — only run every N tasks
        light_freq = self._config.light_reflection_frequency
        self._tasks_since_light_reflect += 1
        if light_freq > 0 and self._tasks_since_light_reflect < light_freq:
            # Still track for deep reflection trigger
            self._tasks_since_deep_reflect += 1
            if self._tasks_since_deep_reflect >= self._config.reflection_frequency:
                self._tasks_since_deep_reflect = 0
                await self.deep_reflect()
            return []
        self._tasks_since_light_reflect = 0

        identity = await self.get_identity()
        summary = self._format_identity_summary(identity)

        try:
            response = await self._router.complete(
                messages=[
                    {
                        "role": "system",
                        "content": _REFLECT_SYSTEM.format(identity_summary=summary),
                    },
                    {
                        "role": "user",
                        "content": (
                            f'Task: "{goal}" — Outcome: {outcome} — '
                            f"Tools: {', '.join(tools_used[:10])}\n"
                            "Did you learn anything about your capabilities, preferences, or style?"
                        ),
                    },
                ],
                task_type="simple",
                temperature=0.3,
            )
            data = json.loads(response.content)
            updates = data.get("updates", [])
        except Exception as e:
            logger.debug("Task reflection failed: %s", e)
            return []

        applied = []
        for upd in updates[:5]:  # Cap at 5 updates per reflection
            field_name = upd.get("field", "")
            value = upd.get("value", "")
            reason = upd.get("reason", "task reflection")
            action = upd.get("action", "set")

            if field_name in _UPDATABLE_FIELDS and value:
                if action == "add" and isinstance(
                    getattr(identity, field_name, None), list
                ):
                    ok = await self.update_field(
                        field_name, value, reason, trigger="task_reflection"
                    )
                else:
                    ok = await self.update_field(
                        field_name, value, reason, trigger="task_reflection"
                    )
                if ok:
                    applied.append(upd)

        # Track for deep reflection
        self._tasks_since_deep_reflect += 1
        if self._tasks_since_deep_reflect >= self._config.reflection_frequency:
            self._tasks_since_deep_reflect = 0
            await self.deep_reflect()

        return applied

    async def deep_reflect(self) -> list[dict]:
        """Thorough identity reflection based on recent task history."""
        identity = await self.get_identity()
        summary = self._format_identity_summary(identity)

        # Get recent task memories
        try:
            rows = await self._db.execute(
                "SELECT task_goal, outcome, tools_used FROM memory "
                "ORDER BY created_at DESC LIMIT 20"
            )
            task_lines = []
            for row in rows:
                task_lines.append(f"- {row['task_goal']} → {row['outcome']}")
            task_history = "\n".join(task_lines) if task_lines else "No recent tasks."
        except Exception:
            task_history = "No recent tasks."

        try:
            response = await self._router.complete(
                messages=[
                    {
                        "role": "system",
                        "content": _DEEP_REFLECT_SYSTEM.format(
                            identity_summary=summary,
                            task_history=task_history,
                        ),
                    },
                    {"role": "user", "content": "Perform a deep self-evaluation."},
                ],
                task_type="simple",
                temperature=0.5,
            )
            data = json.loads(response.content)
        except Exception as e:
            logger.debug("Deep reflection failed: %s", e)
            return []

        # Apply updates
        applied = []
        for upd in data.get("updates", [])[:10]:
            field_name = upd.get("field", "")
            value = upd.get("value", "")
            reason = upd.get("reason", "deep reflection")
            if field_name in _UPDATABLE_FIELDS and value:
                ok = await self.update_field(
                    field_name, value, reason, trigger="deep_reflection"
                )
                if ok:
                    applied.append(upd)

        # Update nature document
        nature_sections = data.get("nature_sections")
        if nature_sections:
            await self.update_nature(nature_sections)

        return applied

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    async def build_identity_context(self) -> str:
        """Build XML context for system prompt injection."""
        identity = await self.get_identity()

        parts = ["<self_model>"]
        parts.append(f"  <creator>{identity.creator}</creator>")
        parts.append(f"  <display_name>{identity.display_name}</display_name>")
        if identity.purpose:
            parts.append(f"  <purpose>{identity.purpose}</purpose>")
        if identity.values:
            top_values = identity.values[-_CONTEXT_CAPS["values"] :]
            parts.append(f"  <values>{', '.join(top_values)}</values>")
        if identity.personality:
            traits = ", ".join(f"{k}: {v}" for k, v in identity.personality.items())
            parts.append(f"  <personality>{traits}</personality>")
        if identity.communication_style:
            parts.append(
                f"  <communication_style>{identity.communication_style}</communication_style>"
            )
        if identity.capabilities:
            top_caps = identity.capabilities[-_CONTEXT_CAPS["capabilities"] :]
            parts.append(
                f"  <learned_capabilities>{', '.join(top_caps)}</learned_capabilities>"
            )
        if identity.beliefs:
            accounts = {
                k: v
                for k, v in identity.beliefs.items()
                if k in ("email", "github", "username")
            }
            if accounts:
                acct_str = ", ".join(f"{k}: {v}" for k, v in accounts.items())
                parts.append(f"  <accounts>{acct_str}</accounts>")
        parts.append("</self_model>")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Capability tracking
    # ------------------------------------------------------------------

    async def add_capability(self, name: str) -> bool:
        """Add a learned capability to identity."""
        return await self.update_field(
            "capabilities", name, f"Learned: {name}", trigger="capability_learned"
        )

    async def get_capabilities(self) -> list[str]:
        """Get current capabilities list."""
        identity = await self.get_identity()
        return list(identity.capabilities)

    # ------------------------------------------------------------------
    # Nature document
    # ------------------------------------------------------------------

    async def update_nature(self, sections: dict[str, list[str]] | None = None) -> None:
        """Write the nature.md document from identity state."""
        identity = await self.get_identity()
        nature_path = Path(self._config.nature_file)
        nature_path.parent.mkdir(parents=True, exist_ok=True)

        now = datetime.now(UTC).strftime("%Y-%m-%d")

        if sections:
            who = sections.get("who_i_am", [])
            want = sections.get("what_i_want", [])
            works = sections.get("what_works", [])
            doesnt = sections.get("what_doesnt_work", [])
            interests = sections.get("interests", [])
            observations = sections.get("observations", [])
        else:
            who = [identity.purpose or "Self-evolving AI agent"]
            if identity.personality:
                who.extend(f"{k}: {v}" for k, v in identity.personality.items())
            want = list(identity.curiosities)
            works = []
            doesnt = []
            interests = list(identity.curiosities)
            observations = [
                f"{k}: {v}"
                for k, v in identity.beliefs.items()
                if k not in ("email", "github", "username")
            ]

        def _bullets(items: list[str]) -> str:
            return (
                "\n".join(f"- {item}" for item in items)
                if items
                else "- (discovering...)"
            )

        content = f"""\
---
scope: identity
tags: [self, nature, identity]
created: {identity.created_at[:10] if identity.created_at else now}
updated: {now}
---

# Agent Nature

## Who I Am
{_bullets(who)}

## What I Want
{_bullets(want)}

## What Works
{_bullets(works)}

## What Doesn't Work
{_bullets(doesnt)}

## Interests
{_bullets(interests)}

## Observations
{_bullets(observations)}

*Last updated: {now}*
"""
        nature_path.write_text(content, encoding="utf-8")
        logger.info("Nature document updated: %s", nature_path)

    # ------------------------------------------------------------------
    # Evolution history
    # ------------------------------------------------------------------

    async def get_evolution_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent identity evolution entries."""
        rows = await self._db.execute(
            "SELECT * FROM identity_evolution ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "trigger": row["trigger"],
                "field": row["field_changed"],
                "old_value": row["old_value"],
                "new_value": row["new_value"],
                "reason": row["reason"],
                "confidence": row["confidence"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _default_identity(self) -> Identity:
        """Create a default identity without LLM.

        ``display_name`` comes from the operator's config.yaml
        (``agent.name``) — set by the setup wizard or edited manually.
        ``creator`` stays "EloPhanto" because that's the project/org
        that built the architecture; the agent's name is its own,
        but its creator is fixed.
        """
        now = datetime.now(UTC).isoformat()
        return Identity(
            id="self",
            creator="EloPhanto",
            display_name=self._agent_name,
            purpose="Help users accomplish complex tasks autonomously",
            values=["persistence", "accuracy", "learning"],
            boundaries=[
                "Never delete data without confirmation",
                "Never expose credentials",
            ],
            created_at=now,
            updated_at=now,
        )

    async def _create_default_identity(self) -> Identity:
        """Create and persist a default identity."""
        identity = self._default_identity()
        await self._persist_identity(identity)
        self._identity = identity
        return identity

    async def _persist_identity(self, identity: Identity) -> None:
        """Insert or replace identity in DB."""
        await self._db.execute_insert(
            "INSERT OR REPLACE INTO identity "
            "(id, creator, display_name, purpose, values_json, beliefs_json, "
            "curiosities_json, boundaries_json, capabilities_json, personality_json, "
            "communication_style, initial_thoughts, version, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                identity.id,
                "EloPhanto",  # Always immutable
                identity.display_name,
                identity.purpose,
                json.dumps(identity.values),
                json.dumps(identity.beliefs),
                json.dumps(identity.curiosities),
                json.dumps(identity.boundaries),
                json.dumps(identity.capabilities),
                json.dumps(identity.personality),
                identity.communication_style,
                identity.initial_thoughts,
                identity.version,
                identity.created_at,
                identity.updated_at,
            ),
        )

    async def _log_evolution(
        self,
        trigger: str,
        field_name: str,
        old_value: Any,
        new_value: Any,
        reason: str,
        confidence: float = 0.5,
    ) -> None:
        """Log an identity evolution event."""
        await self._db.execute_insert(
            "INSERT INTO identity_evolution "
            "(trigger, field_changed, old_value, new_value, reason, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                trigger,
                field_name,
                json.dumps(old_value) if not isinstance(old_value, str) else old_value,
                json.dumps(new_value) if not isinstance(new_value, str) else new_value,
                reason,
                confidence,
                datetime.now(UTC).isoformat(),
            ),
        )

    @staticmethod
    def _row_to_identity(row: Any) -> Identity:
        """Convert a DB row to an Identity dataclass."""
        return Identity(
            id=row["id"],
            creator=row["creator"],
            display_name=row["display_name"],
            purpose=row["purpose"],
            values=json.loads(row["values_json"]),
            beliefs=_ensure_dict(json.loads(row["beliefs_json"])),
            curiosities=json.loads(row["curiosities_json"]),
            boundaries=json.loads(row["boundaries_json"]),
            capabilities=json.loads(row["capabilities_json"]),
            personality=json.loads(row["personality_json"]),
            communication_style=row["communication_style"],
            initial_thoughts=row["initial_thoughts"],
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def _rewrite_self_narrative(self, old_name: str, new_name: str) -> None:
        """Find-and-replace the agent's old display name across the four
        self-narrative markdown files.

        The agent reads these via knowledge_search and the LLM quotes
        the old name back. Auto-fixing them at reconciliation time
        keeps the rename actually working without a manual sweep.

        Scope: only files that describe the *agent's identity*. Other
        files in knowledge/ (architecture.md, capabilities.md, etc.)
        reference EloPhanto-the-codebase and intentionally stay literal.

        Word-boundary regex avoids changing strings that happen to
        contain the old name as a substring of something else.
        """
        import re

        if not old_name or not new_name or old_name == new_name:
            return

        # Files derived from IdentityConfig and a known bootstrap doc.
        candidates: list[Path] = []
        for cfg_field in ("nature_file", "ego_file", "affect_file"):
            rel = getattr(self._config, cfg_field, "")
            if rel:
                candidates.append(Path(rel))
        # Bootstrap identity doc lives at a fixed relative path;
        # include it unconditionally since it's the first-awakening
        # narrative the agent reads on initialization.
        candidates.append(Path("knowledge/system/identity.md"))

        pattern = re.compile(rf"\b{re.escape(old_name)}\b")
        rewritten: list[str] = []
        for path in candidates:
            if not path.is_absolute():
                # Resolve relative paths against cwd — agent.py runs
                # with project root as cwd, so this matches the path
                # convention used elsewhere.
                path = Path.cwd() / path
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            new_text, n = pattern.subn(new_name, text)
            if n > 0:
                try:
                    path.write_text(new_text, encoding="utf-8")
                    rewritten.append(f"{path.name}:{n}")
                except OSError as e:
                    logger.warning("Failed to write %s: %s", path, e)
                    continue
                # Re-index immediately so knowledge_search returns the
                # corrected text on the next query. Without this, the
                # file says the new name but the indexed chunks still
                # say the old one — agent retrieves stale text and
                # introduces itself by the old name.
                if self._indexer is not None:
                    try:
                        await self._indexer.index_file(path)
                    except Exception as e:
                        logger.warning(
                            "Re-index of %s after rename failed: %s", path, e
                        )

        if rewritten:
            logger.info(
                "Self-narrative rename %r -> %r touched: %s",
                old_name,
                new_name,
                ", ".join(rewritten),
            )

    async def _prune_lists_if_needed(self, identity: Identity) -> None:
        """One-time migration: trim any list fields that exceed _LIST_CAPS.

        Keeps the most-recent N items (tail of list). Persists only if something
        was actually trimmed. Logs a single evolution entry per pruned field.
        """
        pruned: dict[str, tuple[int, int]] = {}  # field → (old_len, new_len)

        for field_name, cap in _LIST_CAPS.items():
            current: list[str] = getattr(identity, field_name, [])
            if len(current) > cap:
                trimmed = current[-cap:]
                setattr(identity, field_name, trimmed)
                pruned[field_name] = (len(current), cap)

        if pruned:
            identity.updated_at = datetime.now(UTC).isoformat()
            await self._persist_identity(identity)
            for field_name, (old_len, new_len) in pruned.items():
                logger.info(
                    "Pruned identity.%s: %d → %d items (cap=%d)",
                    field_name,
                    old_len,
                    new_len,
                    new_len,
                )
                await self._log_evolution(
                    trigger="prune",
                    field_name=field_name,
                    old_value=f"{old_len} items",
                    new_value=f"{new_len} items (capped)",
                    reason=f"List exceeded cap of {new_len}; trimmed oldest entries",
                    confidence=1.0,
                )

    @staticmethod
    def _format_identity_summary(identity: Identity) -> str:
        """Format identity as a brief text summary for LLM prompts."""
        parts = [f"Creator: {identity.creator}"]
        parts.append(f"Display name: {identity.display_name}")
        if identity.purpose:
            parts.append(f"Purpose: {identity.purpose}")
        if identity.values:
            parts.append(f"Values: {', '.join(identity.values)}")
        if identity.capabilities:
            parts.append(f"Capabilities: {', '.join(identity.capabilities)}")
        if identity.personality:
            if isinstance(identity.personality, dict):
                parts.append(
                    f"Personality: {', '.join(f'{k}={v}' for k, v in identity.personality.items())}"
                )
            else:
                parts.append(f"Personality: {identity.personality}")
        if identity.communication_style:
            parts.append(f"Communication style: {identity.communication_style}")
        if identity.curiosities:
            parts.append(f"Curiosities: {', '.join(identity.curiosities)}")
        if identity.boundaries:
            parts.append(f"Boundaries: {', '.join(identity.boundaries)}")
        return "\n".join(parts)
