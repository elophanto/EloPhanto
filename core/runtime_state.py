"""Runtime state builder — code-enforced self-model for the LLM.

Builds the ``<runtime_state>`` XML block that sits alongside
``<agent_identity>`` in the system prompt. Unlike the identity model
(which is the agent's evolving self-concept), runtime_state is rebuilt
from real data every turn — non-negotiable ground truth.

See docs/27-SECURITY-HARDENING.md (Gap 3: Self-Identity Model).
"""

from __future__ import annotations

from collections import Counter

from tools.base import BaseTool, PermissionLevel


def build_runtime_state(
    *,
    fingerprint: str = "",
    fingerprint_status: str = "unavailable",
    tools: list[BaseTool] | None = None,
    authority: str = "owner",
    channel: str = "cli",
    context_mode: str = "user_chat",
    storage_status: str = "",
    storage_used_mb: float = 0.0,
    storage_quota_mb: float = 0.0,
    active_processes: int = 0,
    max_processes: int = 10,
    provider_stats: dict[str, dict] | None = None,
) -> str:
    """Build the ``<runtime_state>`` XML block for the system prompt.

    Args:
        fingerprint: Agent fingerprint hex (empty if no vault).
        fingerprint_status: One of "verified", "created", "changed", "unavailable".
        tools: List of tools available to the current user (already filtered by authority).
        authority: Current user's authority tier ("owner", "trusted", "public").
        channel: Current channel name ("cli", "telegram", "discord", etc.).
        context_mode: Execution context ("user_chat", "mind", "goal").
        storage_status: Quota status ("ok", "warning", "exceeded", or empty).
        storage_used_mb: Current storage usage in MB.
        storage_quota_mb: Storage quota in MB.
        active_processes: Number of active tracked processes.
        max_processes: Maximum concurrent processes allowed.
        provider_stats: Per-provider transparency stats (Gap 5). None to omit.

    Returns:
        XML string for injection into the system prompt.
    """
    tool_list = tools or []
    total = len(tool_list)

    # Count tools by permission level
    counts: Counter[str] = Counter()
    for t in tool_list:
        counts[t.permission_level.value] += 1

    safe = counts.get(PermissionLevel.SAFE.value, 0)
    moderate = counts.get(PermissionLevel.MODERATE.value, 0)
    destructive = counts.get(PermissionLevel.DESTRUCTIVE.value, 0)
    critical = counts.get(PermissionLevel.CRITICAL.value, 0)

    # Build fingerprint line
    fp_short = fingerprint[:12] if fingerprint else ""
    fp_line = (
        f'  <fingerprint status="{fingerprint_status}">{fp_short}</fingerprint>'
        if fingerprint
        else f'  <fingerprint status="{fingerprint_status}"/>'
    )

    # Build optional storage line
    storage_line = ""
    if storage_status:
        storage_line = (
            f'  <storage status="{storage_status}" '
            f'used_mb="{storage_used_mb}" quota_mb="{storage_quota_mb}"/>\n'
        )

    # Build process line
    process_line = f'  <processes active="{active_processes}" max="{max_processes}"/>\n'

    # Build provider transparency block (Gap 5)
    providers_block = ""
    if provider_stats:
        provider_lines: list[str] = []
        for name, stats in sorted(provider_stats.items()):
            provider_lines.append(
                f'    <provider name="{name}" '
                f'calls="{stats.get("total_calls", 0)}" '
                f'failures="{stats.get("failures", 0)}" '
                f'truncations="{stats.get("truncations", 0)}" '
                f'avg_latency_ms="{stats.get("avg_latency_ms", 0)}"/>'
            )
        providers_block = (
            "  <providers>\n" + "\n".join(provider_lines) + "\n  </providers>\n"
        )

    return (
        "<runtime_state>\n"
        f"{fp_line}\n"
        f'  <tools total="{total}" safe="{safe}" moderate="{moderate}" '
        f'destructive="{destructive}" critical="{critical}"/>\n'
        f'  <authority current_user="{authority}" channel="{channel}"/>\n'
        f'  <context mode="{context_mode}"/>\n'
        f"{storage_line}"
        f"{process_line}"
        f"{providers_block}"
        "</runtime_state>"
    )
