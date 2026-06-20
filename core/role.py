"""Role personas — system-prompt overlays + tool subsets.

ABE (Autonomous Business Entity) is a concept originated by Petr
Royce in 2023.

A role is config, not code. Each role lives as a ~20-line YAML file
under ``roles/<name>.yaml`` and is mirrored into the ``roles`` table
on boot for query efficiency.

EloPhanto plays the **CEO role by default** (no overlay, no tool
restriction). When the arbiter or operator switches the active role,
the executor gates tool calls against the role's allowlist BEFORE the
generic permission check, and ``IdentityManager.build_identity_context()``
appends the role's prompt_overlay to the system prompt.

See ``docs/76-ABE-FRAMEWORK.md`` §Phase 2 for the design contract.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.database import Database

logger = logging.getLogger(__name__)


# Meta / introspection / mind-internal tools that are NEVER role-gated.
#
# Background: a narrow role allowlist (e.g. OPS) would otherwise block
# the autonomous mind from its own bookkeeping (scratchpad, wakeup),
# from listing/switching out of the active role (paralysing recovery),
# and from read-only introspection (skill_list/read, company_list/
# report). Observed in production: one OPS cycle racked up 240
# denials in a single 18-hour log, including 14 denied ``role_use``
# calls — the mind literally could not exit the role.
#
# Inclusion bar: the tool must be (a) read-only OR mind-internal AND
# (b) something no operator would ever want a role to lack. Write
# tools that genuinely belong to a function (e.g. ``company_set_*``,
# ``company_plan_apply``) stay gated — denying those in OPS is the
# correct behaviour.
_ROLE_GATE_EXEMPT: frozenset[str] = frozenset(
    {
        # Mind-internal bookkeeping
        "update_scratchpad",
        "set_next_wakeup",
        "affect_record_event",
        # Role meta — the agent must always be able to see and switch roles
        "role_list",
        "role_show",
        "role_use",
        # Read-only knowledge/skill lookup
        "skill_list",
        "skill_read",
        # Read-only company introspection
        "company_list",
        "company_report",
        # Generic file IO — every role needs to write scratchpads,
        # research notes, drafts, run logs. Observed in production: a
        # narrow SUPPORT role allowlist denied file_write, blocking
        # the agent from saving the cycle's own audit trail. The
        # role gate is for semantic actions (send email, post tweet,
        # mutate company config), not for the mechanical act of
        # writing a file. Path-level safety (workspace boundaries,
        # protected files) is enforced separately.
        "file_write",
        "file_read",
    }
)


@dataclass(slots=True)
class Role:
    name: str
    description: str = ""
    prompt_overlay: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    allowed_tool_groups: list[str] = field(default_factory=list)
    kpi: dict[str, float] = field(default_factory=dict)
    scope: str = "global"  # 'global' | 'company'
    # Display identity (user-facing). emoji is a single glyph; titles is a
    # seniority ladder keyed to business reality: {"ic","lead","chief"}.
    # core/role_display.py picks the tier from the company's metabolism so a
    # pre-revenue org shows "Founder"/"Marketing", not "CEO"/"CMO".
    emoji: str = ""
    titles: dict[str, str] = field(default_factory=dict)
    last_active_at: str | None = None
    created_at: str = ""
    updated_at: str = ""


def _row_get(r: Any, key: str, default: Any = None) -> Any:
    """sqlite3.Row has no .get() — tolerate columns absent from a SELECT."""
    try:
        return r[key]
    except (IndexError, KeyError):
        return default


def _row_to_role(r: Any) -> Role:
    return Role(
        name=r["role_name"],
        description=r["description"] or "",
        prompt_overlay=r["prompt_overlay"] or "",
        allowed_tools=json.loads(r["allowed_tools"] or "[]"),
        allowed_tool_groups=json.loads(r["allowed_tool_groups"] or "[]"),
        kpi=json.loads(r["kpi_json"] or "{}"),
        scope=r["scope"] or "global",
        emoji=_row_get(r, "emoji", "") or "",
        titles=json.loads(_row_get(r, "titles_json", "{}") or "{}"),
        last_active_at=r["last_active_at"],
        created_at=r["created_at"] or "",
        updated_at=r["updated_at"] or "",
    )


class RoleManager:
    """CRUD over the ``roles`` table, plus YAML sync from ``roles/``."""

    def __init__(self, db: Database, roles_dir: Path | None = None) -> None:
        self._db = db
        self._roles_dir = roles_dir

    # ── Reads ──────────────────────────────────────────────────────

    async def list_roles(self) -> list[Role]:
        rows = await self._db.execute(
            "SELECT role_name, description, prompt_overlay, allowed_tools, "
            "allowed_tool_groups, kpi_json, scope, emoji, titles_json, "
            "last_active_at, created_at, updated_at FROM roles ORDER BY role_name"
        )
        return [_row_to_role(r) for r in rows]

    async def get(self, name: str) -> Role | None:
        rows = await self._db.execute(
            "SELECT role_name, description, prompt_overlay, allowed_tools, "
            "allowed_tool_groups, kpi_json, scope, emoji, titles_json, "
            "last_active_at, created_at, updated_at FROM roles WHERE role_name = ?",
            (name,),
        )
        return _row_to_role(rows[0]) if rows else None

    # ── Writes ─────────────────────────────────────────────────────

    async def upsert(
        self,
        *,
        name: str,
        description: str = "",
        prompt_overlay: str = "",
        allowed_tools: list[str] | None = None,
        allowed_tool_groups: list[str] | None = None,
        kpi: dict[str, float] | None = None,
        scope: str = "global",
        emoji: str = "",
        titles: dict[str, str] | None = None,
    ) -> Role:
        """Insert or replace a role row. Returns the persisted Role."""
        if scope not in ("global", "company"):
            raise ValueError(f"invalid scope: {scope!r}")
        now_iso = datetime.now(UTC).isoformat()
        existing = await self.get(name)
        created_at = existing.created_at if existing else now_iso
        await self._db.execute_insert(
            "INSERT OR REPLACE INTO roles "
            "(role_name, description, prompt_overlay, allowed_tools, "
            "allowed_tool_groups, kpi_json, scope, emoji, titles_json, "
            "last_active_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                description,
                prompt_overlay,
                json.dumps(allowed_tools or []),
                json.dumps(allowed_tool_groups or []),
                json.dumps(kpi or {}),
                scope,
                emoji,
                json.dumps(titles or {}),
                existing.last_active_at if existing else None,
                created_at,
                now_iso,
            ),
        )
        role = await self.get(name)
        assert role is not None
        return role

    async def touch(self, name: str) -> None:
        """Mark a role as active right now — bumps ``last_active_at``."""
        await self._db.execute(
            "UPDATE roles SET last_active_at = ?, updated_at = ? "
            "WHERE role_name = ?",
            (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat(), name),
        )

    # ── YAML sync ──────────────────────────────────────────────────

    async def sync_from_disk(self, roles_dir: Path | None = None) -> int:
        """Walk ``roles/*.yaml`` and upsert each. Idempotent. Returns count."""
        target = roles_dir or self._roles_dir
        if target is None or not target.is_dir():
            return 0
        count = 0
        for path in sorted(target.glob("*.yaml")):
            try:
                role = await self.upsert_from_yaml(path)
                if role is not None:
                    count += 1
            except Exception as e:
                logger.warning("role sync: %s failed: %s", path.name, e)
        return count

    async def upsert_from_yaml(self, path: Path) -> Role | None:
        """Load a single ``roles/<name>.yaml`` and upsert it."""
        import yaml

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("role yaml %s parse failed: %s", path, e)
            return None
        if not isinstance(data, dict):
            logger.warning("role yaml %s: top-level must be a mapping", path)
            return None
        name = str(data.get("name") or path.stem).strip()
        if not name:
            return None
        return await self.upsert(
            name=name,
            description=str(data.get("description") or ""),
            prompt_overlay=str(data.get("prompt_overlay") or ""),
            allowed_tools=list(data.get("allowed_tools") or []),
            allowed_tool_groups=list(data.get("allowed_tool_groups") or []),
            kpi=dict(data.get("kpi") or {}),
            scope=str(data.get("scope") or "global"),
            emoji=str(data.get("emoji") or ""),
            titles={str(k): str(v) for k, v in (data.get("titles") or {}).items()},
        )

    # ── Neglect ranking ────────────────────────────────────────────

    async def list_by_neglect(self, *, limit: int = 5) -> list[Role]:
        """Return roles ranked by neglect.

        Never-touched (``last_active_at IS NULL``) sorts first, then
        oldest ``last_active_at`` ascending. The arbiter uses this to
        bias the role rotation toward roles the agent hasn't worked
        from recently.
        """
        rows = await self._db.execute(
            "SELECT role_name, description, prompt_overlay, allowed_tools, "
            "allowed_tool_groups, kpi_json, scope, emoji, titles_json, "
            "last_active_at, created_at, updated_at FROM roles "
            "ORDER BY last_active_at IS NULL DESC, last_active_at ASC "
            "LIMIT ?",
            (limit,),
        )
        return [_row_to_role(r) for r in rows]

    # ── Permission gate (pure function — no DB) ────────────────────

    @staticmethod
    def is_tool_allowed(
        role: Role,
        tool_name: str,
        tool_group: str | None = None,
    ) -> bool:
        """Whether a tool is allowed under a role.

        Rule (from the doc): empty ``allowed_tools`` AND empty
        ``allowed_tool_groups`` → no constraint, every tool allowed
        (this is what makes the default CEO role unrestricted).
        Otherwise, tool name OR group must match.

        Meta/introspection/mind-internal tools in ``_ROLE_GATE_EXEMPT``
        always pass — see the comment on that set for the rationale.
        """
        if tool_name in _ROLE_GATE_EXEMPT:
            return True
        if not role.allowed_tools and not role.allowed_tool_groups:
            return True
        if tool_name in role.allowed_tools:
            return True
        if tool_group is not None and tool_group in role.allowed_tool_groups:
            return True
        return False
