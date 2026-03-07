"""Tool profile system: context-aware tool selection for LLM calls.

Selects which tools to send based on task type and provider limits,
instead of sending all 140+ tools on every request.
"""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool

logger = logging.getLogger(__name__)

# Default profile definitions: profile_name -> set of groups
DEFAULT_PROFILES: dict[str, set[str]] = {
    "minimal": {"system", "knowledge", "data", "skills"},
    "coding": {"system", "knowledge", "data", "skills", "selfdev", "goals"},
    "browsing": {"system", "knowledge", "data", "skills", "browser"},
    "desktop_profile": {"system", "knowledge", "data", "skills", "desktop"},
    "comms": {"system", "knowledge", "data", "skills", "comms", "identity"},
    "devops": {"system", "knowledge", "data", "skills", "infra", "swarm"},
    "full": {
        "system",
        "knowledge",
        "data",
        "skills",
        "selfdev",
        "goals",
        "browser",
        "desktop",
        "documents",
        "comms",
        "payments",
        "identity",
        "media",
        "social",
        "infra",
        "org",
        "swarm",
        "mcp",
        "scheduling",
        "mind",
        "hub",
    },
}

# Task type -> default profile
TASK_TYPE_PROFILES: dict[str, str] = {
    "planning": "full",
    "coding": "coding",
    "analysis": "minimal",
    "simple": "minimal",
}

# Low-priority groups dropped first when trimming for provider limits
LOW_PRIORITY_GROUPS = ("mcp", "social", "media", "infra", "org", "identity")


def resolve_profiles(
    config_profiles: dict[str, list[str]] | None,
) -> dict[str, set[str]]:
    """Merge user-configured profiles with defaults."""
    profiles = {k: set(v) for k, v in DEFAULT_PROFILES.items()}
    if config_profiles:
        for name, groups in config_profiles.items():
            profiles[name] = set(groups)
    return profiles


def select_profile(
    task_type: str,
    routing_profile: str | None = None,
) -> str:
    """Determine which profile to use for a given task type."""
    if routing_profile:
        return routing_profile
    return TASK_TYPE_PROFILES.get(task_type, "full")


def filter_tools_by_profile(
    tools: list[BaseTool],
    profile_name: str,
    profiles: dict[str, set[str]] | None = None,
    deny_groups: list[str] | None = None,
) -> list[BaseTool]:
    """Filter tools to only those in the active profile's groups.

    Args:
        tools: All registered tool instances.
        profile_name: Which profile to apply (e.g. "coding", "full").
        profiles: Profile definitions (defaults used if None).
        deny_groups: Additional groups to exclude (provider-level deny).
    """
    all_profiles = profiles or DEFAULT_PROFILES
    allowed_groups = all_profiles.get(profile_name)
    if allowed_groups is None:
        # Unknown profile — fall back to full
        logger.warning(
            "Unknown tool profile '%s', falling back to 'full'", profile_name
        )
        allowed_groups = all_profiles.get("full", set())

    # Apply deny list
    if deny_groups:
        allowed_groups = allowed_groups - set(deny_groups)

    return [t for t in tools if t.group in allowed_groups]


def trim_tools_for_limit(
    tools: list[dict[str, Any]],
    limit: int,
    recently_used: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Drop lowest-priority tool schemas to fit a provider's tool limit.

    This is the last-resort fallback after profile filtering. If the
    profile-filtered set still exceeds the limit (e.g. browser alone has
    46 tools), drop tools from low-priority groups first.

    Tools in ``recently_used`` are never dropped — they are pinned to
    prevent the agent from losing access to tools mid-conversation.
    """
    if limit <= 0 or len(tools) <= limit:
        return tools

    low_priority_prefixes = (
        "mcp_",
        "commune_",
        "replicate_",
        "deploy_",
        "deployment_",
        "create_database",
        "desktop_",
        "organization_",
        "totp_",
    )

    # If any tool from a low-priority group was recently used, pin the
    # entire group so sibling tools (e.g. commune_comment when
    # commune_home was used) remain available.
    pinned_prefixes: set[str] = set()
    if recently_used:
        for used_name in recently_used:
            for prefix in low_priority_prefixes:
                if used_name.startswith(prefix):
                    pinned_prefixes.add(prefix)
                    break

    core: list[dict[str, Any]] = []
    low: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("function", {}).get("name", "")
        if any(name.startswith(p) for p in pinned_prefixes):
            core.append(tool)
        elif any(name.startswith(p) for p in low_priority_prefixes):
            low.append(tool)
        else:
            core.append(tool)

    remaining = limit - len(core)
    if remaining > 0:
        return core + low[:remaining]
    return core[:limit]
