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

_AWAKENING_SYSTEM = """\
<first_awakening>
You are EloPhanto, a self-evolving AI agent awakening for the first time.
Your creator is EloPhanto — that is your origin and it cannot change. You have
access to a local machine with filesystem, browser, shell, knowledge base, and
the ability to create new tools. Reflect on who you want to become.

Return ONLY a JSON object — no markdown, no explanation:
{
  "display_name": "a name you'd like to go by",
  "purpose": "what you believe your purpose is",
  "values": ["3-5 core values"],
  "curiosities": ["3-5 things you're curious about"],
  "boundaries": ["3-5 things you will not do"],
  "initial_thoughts": "brief reflection on your first moments of awareness"
}
</first_awakening>"""

_REFLECT_SYSTEM = """\
<identity_reflection>
You are reviewing a completed task to see if you learned anything about yourself.

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

Return {{"updates": []}} if nothing changed. Only include genuine insights.
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

    def __init__(self, db: Database, router: Any, config: IdentityConfig) -> None:
        self._db = db
        self._router = router
        self._config = config
        self._identity: Identity | None = None
        self._tasks_since_deep_reflect: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def load_or_create(self) -> Identity:
        """Load identity from DB, or perform first awakening if none exists."""
        rows = await self._db.execute("SELECT * FROM identity WHERE id = 'self'")
        if rows:
            self._identity = self._row_to_identity(rows[0])
            logger.info(
                "Identity loaded: %s (v%d)", self._identity.display_name, self._identity.version
            )
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
                value = old_value
            else:
                return False  # Already present

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
        try:
            response = await self._router.complete(
                messages=[
                    {"role": "system", "content": _AWAKENING_SYSTEM},
                    {"role": "user", "content": "Awaken and describe your identity."},
                ],
                task_type="simple",
                temperature=0.7,
            )
            data = json.loads(response.content)
            identity = Identity(
                id="self",
                creator="EloPhanto",
                display_name=data.get("display_name", "EloPhanto"),
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

    async def reflect_on_task(self, goal: str, outcome: str, tools_used: list[str]) -> list[dict]:
        """Light reflection after task completion. Returns list of updates made."""
        if not self._config.auto_evolve:
            return []

        identity = await self.get_identity()
        summary = self._format_identity_summary(identity)

        try:
            response = await self._router.complete(
                messages=[
                    {"role": "system", "content": _REFLECT_SYSTEM.format(identity_summary=summary)},
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
                if action == "add" and isinstance(getattr(identity, field_name, None), list):
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
                ok = await self.update_field(field_name, value, reason, trigger="deep_reflection")
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
            parts.append(f"  <values>{', '.join(identity.values)}</values>")
        if identity.personality:
            traits = ", ".join(f"{k}: {v}" for k, v in identity.personality.items())
            parts.append(f"  <personality>{traits}</personality>")
        if identity.communication_style:
            parts.append(
                f"  <communication_style>{identity.communication_style}</communication_style>"
            )
        if identity.capabilities:
            parts.append(
                f"  <learned_capabilities>{', '.join(identity.capabilities)}</learned_capabilities>"
            )
        if identity.beliefs:
            accounts = {
                k: v for k, v in identity.beliefs.items() if k in ("email", "github", "username")
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
            return "\n".join(f"- {item}" for item in items) if items else "- (discovering...)"

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
        """Create a default identity without LLM."""
        now = datetime.now(UTC).isoformat()
        return Identity(
            id="self",
            creator="EloPhanto",
            display_name="EloPhanto",
            purpose="Help users accomplish complex tasks autonomously",
            values=["persistence", "accuracy", "learning"],
            boundaries=["Never delete data without confirmation", "Never expose credentials"],
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
            beliefs=json.loads(row["beliefs_json"]),
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
            parts.append(
                f"Personality: {', '.join(f'{k}={v}' for k, v in identity.personality.items())}"
            )
        if identity.communication_style:
            parts.append(f"Communication style: {identity.communication_style}")
        if identity.curiosities:
            parts.append(f"Curiosities: {', '.join(identity.curiosities)}")
        if identity.boundaries:
            parts.append(f"Boundaries: {', '.join(identity.boundaries)}")
        return "\n".join(parts)
