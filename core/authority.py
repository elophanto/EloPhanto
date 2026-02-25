"""Authority tier system for multi-user access control.

Resolves who can do what based on verified platform user IDs.
Authority is enforced at the gateway level BEFORE the existing
permission system (executor) — they are layered, not competing.

Flow: Inbound message → resolve authority → filter tool list → permission check → execute

See docs/27-SECURITY-HARDENING.md (Gap 1: Stakeholder Model).
"""

from __future__ import annotations

import enum
import logging

from core.config import AuthorityConfig
from tools.base import BaseTool

logger = logging.getLogger(__name__)


class AuthorityLevel(enum.Enum):
    """User authority tiers — determines tool visibility."""

    OWNER = "owner"
    TRUSTED = "trusted"
    PUBLIC = "public"


def resolve_authority(
    channel: str,
    user_id: str,
    config: AuthorityConfig | None,
) -> AuthorityLevel:
    """Resolve a user's authority tier.

    Rules:
    - CLI channel is always OWNER (local process = trusted by default).
    - No config (None) means all users are OWNER (backward compat).
    - Empty owner.user_ids means all users are OWNER (unconfigured).
    - Match ``"channel:user_id"`` against owner → trusted → fallback to PUBLIC.
    """
    # CLI is always owner — it's a local process
    if channel in ("cli", "local", "direct"):
        return AuthorityLevel.OWNER

    # No authority config → backward compatible, everyone is owner
    if config is None:
        return AuthorityLevel.OWNER

    # No owner IDs configured → unconfigured, everyone is owner
    if not config.owner.user_ids:
        return AuthorityLevel.OWNER

    # Build the composite key: "telegram:123456"
    composite = f"{channel}:{user_id}"

    # Check owner list
    if composite in config.owner.user_ids or user_id in config.owner.user_ids:
        return AuthorityLevel.OWNER

    # Check trusted list
    if composite in config.trusted.user_ids or user_id in config.trusted.user_ids:
        return AuthorityLevel.TRUSTED

    # Everyone else is public
    return AuthorityLevel.PUBLIC


# ---------------------------------------------------------------------------
# Tool filtering by authority tier
# ---------------------------------------------------------------------------

# Read-only, safe tools that trusted users can access.
# These tools never modify state, execute code, or access sensitive data.
_TRUSTED_TOOLS: frozenset[str] = frozenset(
    {
        # File system (read-only)
        "file_read",
        "file_list",
        # Knowledge
        "knowledge_search",
        # Goals (read-only)
        "goal_status",
        # Identity (read-only)
        "identity_status",
        # Hub
        "hub_search",
        # Skills (read-only)
        "skill_list",
        "skill_read",
        # Documents (read-only)
        "document_query",
        "document_collections",
        # Scheduling (read-only)
        "schedule_list",
        # Payments (read-only)
        "payment_balance",
        "wallet_status",
        "payment_history",
        "payment_validate",
    }
)


def filter_tools_for_authority(
    tools: list[BaseTool],
    authority: AuthorityLevel,
) -> list[BaseTool]:
    """Filter the tool list based on the user's authority tier.

    - OWNER: all tools (no filtering).
    - TRUSTED: only tools in ``_TRUSTED_TOOLS``.
    - PUBLIC: empty list (chat only, no tool access).
    """
    if authority == AuthorityLevel.OWNER:
        return tools

    if authority == AuthorityLevel.TRUSTED:
        return [t for t in tools if t.name in _TRUSTED_TOOLS]

    # PUBLIC — no tools
    return []


def check_tool_authority(tool_name: str, authority: AuthorityLevel) -> bool:
    """Check if a specific tool is allowed for a given authority level.

    Used as a safety net in the executor — even if the LLM hallucinates
    a tool call that wasn't in its filtered list, this blocks execution.
    """
    if authority == AuthorityLevel.OWNER:
        return True

    if authority == AuthorityLevel.TRUSTED:
        return tool_name in _TRUSTED_TOOLS

    return False
