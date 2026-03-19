"""User modeling: builds evolving profiles from conversation observation.

Observes conversations and extracts structured user signals (role, expertise,
preferences) via a lightweight LLM call after each completed task. Profiles
persist in SQLite and are injected into the system prompt as <user_context>.

Mirrors the IdentityManager pattern but models the *user*, not the agent.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_MAX_OBSERVATIONS = 20
_MAX_EXPERTISE = 15


@dataclass
class UserProfile:
    """Structured profile for a single user."""

    user_id: str
    channel: str
    display_name: str = ""
    role: str = ""  # "developer", "designer", "founder", etc.
    expertise: list[str] = field(default_factory=list)
    preferences: dict[str, str] = field(default_factory=dict)
    observations: list[str] = field(default_factory=list)
    interaction_count: int = 0
    created_at: str = ""
    updated_at: str = ""


# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

_EXTRACT_SYSTEM = """\
<user_signal_extraction>
You extract structured user signals from a completed AI agent conversation.

Given the user's message and the agent's response, identify any NEW signals about
the user. Only extract what is clearly demonstrated, not assumed.

Return ONLY a JSON object — no markdown, no explanation:
{
  "display_name": "name if mentioned or null",
  "role": "user's role if apparent or null",
  "new_expertise": ["skill1", "skill2"],
  "preferences": {"key": "value"},
  "observation": "one-sentence note about this user or null"
}

Rules:
- Return null/empty for fields with no clear signal
- new_expertise: only technical skills clearly demonstrated (not just mentioned)
- preferences: communication style, verbosity, code style, workflow preferences
- observation: notable behavioral pattern, not a task summary
- Be conservative — skip routine interactions with no user-specific signal
</user_signal_extraction>"""


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class UserProfileManager:
    """Manages per-user profiles with LLM-based signal extraction."""

    def __init__(self, db: Any, router: Any) -> None:
        self._db = db
        self._router = router

    async def get_or_create(self, channel: str, user_id: str) -> UserProfile:
        """Load existing profile or create a blank one."""
        rows = await self._db.execute(
            "SELECT * FROM user_profiles WHERE user_id = ? AND channel = ?",
            (user_id, channel),
        )
        if rows:
            return self._row_to_profile(rows[0])

        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "INSERT INTO user_profiles "
            "(user_id, channel, display_name, role, expertise_json, "
            "preferences_json, observations_json, interaction_count, "
            "created_at, updated_at) "
            "VALUES (?, ?, '', '', '[]', '{}', '[]', 0, ?, ?)",
            (user_id, channel, now, now),
        )
        return UserProfile(
            user_id=user_id, channel=channel, created_at=now, updated_at=now
        )

    async def build_user_context(self, channel: str, user_id: str) -> str:
        """Build XML context block for system prompt injection."""
        profile = await self.get_or_create(channel, user_id)

        if not profile.role and not profile.expertise and not profile.preferences:
            return ""  # No useful data yet

        parts = ["<user_context>"]
        if profile.display_name:
            parts.append(f"  <name>{profile.display_name}</name>")
        if profile.role:
            parts.append(f"  <role>{profile.role}</role>")
        if profile.expertise:
            parts.append(
                f"  <expertise>{', '.join(profile.expertise[-_MAX_EXPERTISE:])}</expertise>"
            )
        if profile.preferences:
            prefs = ", ".join(f"{k}: {v}" for k, v in profile.preferences.items())
            parts.append(f"  <preferences>{prefs}</preferences>")
        if profile.observations:
            recent = profile.observations[-5:]
            obs_str = "; ".join(recent)
            parts.append(f"  <observations>{obs_str}</observations>")
        parts.append(f"  <interactions>{profile.interaction_count}</interactions>")
        parts.append("</user_context>")

        return "\n".join(parts)

    async def observe_task(
        self,
        channel: str,
        user_id: str,
        user_message: str,
        agent_response: str,
    ) -> None:
        """Fire-and-forget: extract user signals from a completed task.

        Safe to call as asyncio.create_task() — all exceptions are caught.
        """
        try:
            await self._observe_task_inner(
                channel, user_id, user_message, agent_response
            )
        except Exception as e:
            logger.debug("User model observation failed: %s", e)

    async def _observe_task_inner(
        self,
        channel: str,
        user_id: str,
        user_message: str,
        agent_response: str,
    ) -> None:
        profile = await self.get_or_create(channel, user_id)

        # Always bump interaction count
        profile.interaction_count += 1

        # Only run LLM extraction periodically to save cost
        # First 3 interactions, then every 5th
        should_extract = (
            profile.interaction_count <= 3 or profile.interaction_count % 5 == 0
        )

        if should_extract:
            try:
                response = await self._router.complete(
                    messages=[
                        {"role": "system", "content": _EXTRACT_SYSTEM},
                        {
                            "role": "user",
                            "content": (
                                f"User message: {user_message[:500]}\n\n"
                                f"Agent response: {agent_response[:500]}"
                            ),
                        },
                    ],
                    task_type="simple",
                    temperature=0.1,
                )
                data = json.loads(response.content)
                self._merge_signals(profile, data)
            except Exception as e:
                logger.debug("User signal extraction failed: %s", e)

        await self._save_profile(profile)

    def _merge_signals(self, profile: UserProfile, data: dict[str, Any]) -> None:
        """Merge extracted signals into the profile."""
        if data.get("display_name") and not profile.display_name:
            profile.display_name = str(data["display_name"])[:100]

        if data.get("role"):
            profile.role = str(data["role"])[:100]

        for skill in data.get("new_expertise", []):
            skill = str(skill).lower().strip()[:50]
            if skill and skill not in profile.expertise:
                profile.expertise.append(skill)
                if len(profile.expertise) > _MAX_EXPERTISE:
                    profile.expertise = profile.expertise[-_MAX_EXPERTISE:]

        for k, v in data.get("preferences", {}).items():
            k, v = str(k)[:50], str(v)[:100]
            if k and v:
                profile.preferences[k] = v

        obs = data.get("observation")
        if obs and isinstance(obs, str) and obs.strip():
            # Scan for injection before persisting
            from core.injection_guard import scan_for_injection

            is_suspicious, _ = scan_for_injection(obs)
            if not is_suspicious:
                profile.observations.append(obs.strip()[:200])
                if len(profile.observations) > _MAX_OBSERVATIONS:
                    profile.observations = profile.observations[-_MAX_OBSERVATIONS:]

    async def _save_profile(self, profile: UserProfile) -> None:
        """Persist profile to SQLite."""
        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "INSERT OR REPLACE INTO user_profiles "
            "(user_id, channel, display_name, role, expertise_json, "
            "preferences_json, observations_json, interaction_count, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                profile.user_id,
                profile.channel,
                profile.display_name,
                profile.role,
                json.dumps(profile.expertise),
                json.dumps(profile.preferences),
                json.dumps(profile.observations),
                profile.interaction_count,
                profile.created_at or now,
                now,
            ),
        )

    def _row_to_profile(self, row: Any) -> UserProfile:
        """Convert a SQLite Row to a UserProfile."""
        return UserProfile(
            user_id=row["user_id"],
            channel=row["channel"],
            display_name=row["display_name"] or "",
            role=row["role"] or "",
            expertise=json.loads(row["expertise_json"] or "[]"),
            preferences=json.loads(row["preferences_json"] or "{}"),
            observations=json.loads(row["observations_json"] or "[]"),
            interaction_count=row["interaction_count"] or 0,
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )
