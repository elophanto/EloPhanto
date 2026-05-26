"""Capability audit — read-only synthesis of agent inventory (Phase 11).

ABE (Autonomous Business Entity) is a concept originated by Petr
Royce in 2023. See ``docs/76-ABE-FRAMEWORK.md`` §Phase 11.

Reads three sources and synthesizes them into a ``CapabilityMap``:

1. **Vault** — present credential keys via ``Vault.list_keys()``
   (no plaintext exposed; just the key names). Skipped when vault is
   locked, with a clear note in the rendered markdown.
2. **Tool registry** — all registered tools grouped by their ``group``
   attribute. Lets the audit answer "what channels can the agent
   actually act on?" — email, social, prospecting, etc.
3. **Skills** — filesystem walk of ``skills/<slug>/SKILL.md``.

The audit is **pure / read-only**. No side effects beyond writing
``data/companies/<slug>/capabilities.md`` when the caller asks for
the markdown render. Used by ``company_capabilities`` (Phase 11
tool) and by ``company_plan_apply``'s blocker detection step.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CapabilityMap:
    """Snapshot of what the agent has access to at audit time."""

    vault_keys: list[str] = field(default_factory=list)
    vault_locked: bool = False
    tools_by_group: dict[str, list[str]] = field(default_factory=dict)
    skills: list[str] = field(default_factory=list)

    def has_vault_key(self, key: str) -> bool:
        return key in self.vault_keys

    def has_tool(self, tool_name: str) -> bool:
        return any(tool_name in names for names in self.tools_by_group.values())

    def has_skill(self, skill_name: str) -> bool:
        return skill_name in self.skills

    def as_dict(self) -> dict[str, Any]:
        return {
            "vault_keys": list(self.vault_keys),
            "vault_locked": self.vault_locked,
            "tools_by_group": {k: list(v) for k, v in self.tools_by_group.items()},
            "skills": list(self.skills),
        }


def collect_capabilities(
    *,
    registry: Any = None,
    vault: Any = None,
    project_root: Path | None = None,
) -> CapabilityMap:
    """Build a CapabilityMap from the live agent state.

    All arguments optional — missing sources degrade gracefully so a
    partial audit still returns something useful. The caller (the
    ``company_capabilities`` tool) injects what it has.
    """
    cap = CapabilityMap()

    # 1. Vault
    if vault is not None:
        try:
            cap.vault_keys = sorted(vault.list_keys())
            cap.vault_locked = False
        except Exception as e:
            # Locked vault, missing master, IO error — treat all as
            # "locked / unreadable" so the planner knows credentials
            # introspection is unavailable rather than empty.
            logger.debug("capability_audit: vault read failed: %s", e)
            cap.vault_locked = True
    else:
        cap.vault_locked = True

    # 2. Tools — bucket by group
    if registry is not None:
        try:
            for tool in registry.all_tools():
                group = getattr(tool, "group", "") or "ungrouped"
                cap.tools_by_group.setdefault(group, []).append(tool.name)
            for group, names in cap.tools_by_group.items():
                cap.tools_by_group[group] = sorted(set(names))
        except Exception as e:
            logger.warning("capability_audit: registry read failed: %s", e)

    # 3. Skills — filesystem walk
    if project_root is not None:
        skills_root = project_root / "skills"
        if skills_root.is_dir():
            for entry in sorted(skills_root.iterdir()):
                if not entry.is_dir():
                    continue
                if (entry / "SKILL.md").is_file():
                    cap.skills.append(entry.name)

    return cap


def render_capabilities_md(cap: CapabilityMap, *, company_id: str = "") -> str:
    """Render a CapabilityMap as a human-readable markdown summary.
    Pure function — no IO."""
    parts: list[str] = []
    header = "# Capabilities"
    if company_id:
        header += f" — {company_id}"
    parts.append(header + "\n")

    # Vault
    parts.append("## Credentials (vault)\n")
    if cap.vault_locked:
        parts.append(
            "_Vault is locked or unavailable — credential introspection skipped. "
            "Unlock via `elophanto vault unlock` to enable._\n"
        )
    elif not cap.vault_keys:
        parts.append("_No credentials stored. Add via `elophanto vault add`._\n")
    else:
        for key in cap.vault_keys:
            parts.append(f"- `{key}`")
        parts.append("")

    # Tools
    parts.append("## Registered tools (by group)\n")
    if not cap.tools_by_group:
        parts.append("_No tools registered (initialization not complete?)._\n")
    else:
        for group in sorted(cap.tools_by_group):
            parts.append(f"### {group}")
            for name in cap.tools_by_group[group]:
                parts.append(f"- `{name}`")
            parts.append("")

    # Skills
    parts.append("## Installed skills\n")
    if not cap.skills:
        parts.append("_No skills installed under `skills/`._\n")
    else:
        for skill in cap.skills:
            parts.append(f"- `{skill}`")
        parts.append("")

    parts.append(
        "_This is a snapshot of agent inventory, not what's needed for "
        "any particular strategy. Cross-reference against `blockers.md` "
        "(via `company_plan_apply`) to see gaps the strategy actually requires._\n"
    )

    return "\n".join(parts)


def write_capabilities_md(
    cap: CapabilityMap, project_root: Path, company_id: str
) -> Path:
    """Write the rendered markdown to data/companies/<slug>/capabilities.md."""
    path = project_root / "data" / "companies" / company_id / "capabilities.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_capabilities_md(cap, company_id=company_id), encoding="utf-8"
    )
    return path
