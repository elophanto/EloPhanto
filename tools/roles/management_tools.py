"""Role management tools — chat-callable CLI equivalents.

ABE (Autonomous Business Entity) is a concept originated by Petr
Royce, May 2026. See ``docs/76-ABE-FRAMEWORK.md`` §Phase 8.

Four tools that wrap the same logic as ``elophanto role …`` so the
operator can manage role personas via chat:

- ``role_list``  (SAFE)     — all roles + active marker + last_active_at
- ``role_show``  (SAFE)     — one role's full overlay + allowlist + KPI
- ``role_use``   (MODERATE) — switch active role for this session
- ``role_sync``  (MODERATE) — re-read roles/*.yaml into DB

``role_use`` defaults to **session-only**; pass ``persist=true`` to
also write ``~/.elophanto/current_role``.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class _RoleToolBase(BaseTool):
    def __init__(self) -> None:
        self._role_manager: Any = None

    @property
    def group(self) -> str:
        return "roles"

    def _check_ready(self) -> ToolResult | None:
        if self._role_manager is None:
            return ToolResult(
                success=False,
                error=f"{self.name} not initialized (missing role_manager)",
            )
        return None


class RoleListTool(_RoleToolBase):
    @property
    def name(self) -> str:
        return "role_list"

    @property
    def description(self) -> str:
        return (
            "CANONICAL list of ABE role personas — rows in the `roles` "
            "table, synced from `roles/*.yaml`. **Call this whenever "
            "the operator asks about roles, role definitions, or what "
            "roles are available** — do NOT enumerate roles from "
            "memory or guess; this tool is the source of truth. Returns "
            "name, description, active-session marker, allowlist sizes, "
            "and last-active timestamp."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        gate = self._check_ready()
        if gate is not None:
            return gate
        from core.role_context import current_role

        active = current_role()
        roles = await self._role_manager.list_roles()
        rows = [
            {
                "name": r.name,
                "description": r.description.strip(),
                "active_session": r.name == active,
                "allowed_tools_count": len(r.allowed_tools),
                "allowed_tool_groups_count": len(r.allowed_tool_groups),
                "kpi_count": len(r.kpi),
                "last_active_at": r.last_active_at,
                "constraint_free": (not r.allowed_tools and not r.allowed_tool_groups),
            }
            for r in roles
        ]
        return ToolResult(
            success=True,
            data={
                "roles": rows,
                "active_session": active,
                "active_label": active or "(none — playing CEO)",
                "count": len(rows),
            },
        )


class RoleShowTool(_RoleToolBase):
    @property
    def name(self) -> str:
        return "role_show"

    @property
    def description(self) -> str:
        return (
            "Return the full overlay text, allowlist, and KPI map for one "
            "role. Use when the operator asks 'what does the X role do?' "
            "or to verify a YAML edit landed correctly."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        gate = self._check_ready()
        if gate is not None:
            return gate
        name = str(params.get("name", "")).strip()
        if not name:
            return ToolResult(success=False, error="name is required")
        role = await self._role_manager.get(name)
        if role is None:
            return ToolResult(success=False, error=f"No such role: {name}")
        return ToolResult(
            success=True,
            data={
                "name": role.name,
                "description": role.description.strip(),
                "prompt_overlay": role.prompt_overlay.strip(),
                "allowed_tools": role.allowed_tools,
                "allowed_tool_groups": role.allowed_tool_groups,
                "kpi": role.kpi,
                "scope": role.scope,
                "last_active_at": role.last_active_at,
                "constraint_free": (
                    not role.allowed_tools and not role.allowed_tool_groups
                ),
            },
        )


class RoleUseTool(_RoleToolBase):
    @property
    def name(self) -> str:
        return "role_use"

    @property
    def description(self) -> str:
        return (
            "Switch the active role for this session. Pass name='' or "
            "name=null to clear (back to CEO default — full tools). "
            "Session-only by default; pass persist=true to also write "
            "~/.elophanto/current_role (only when the operator "
            "explicitly asks for a default change)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Role name. Empty string or null = clear "
                        "(back to CEO default)."
                    ),
                },
                "persist": {
                    "type": "boolean",
                    "description": (
                        "Default false (session-only). True writes "
                        "~/.elophanto/current_role."
                    ),
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        gate = self._check_ready()
        if gate is not None:
            return gate
        from core.role_context import set_current_role, write_persisted_current_role

        name = params.get("name")
        if name is not None:
            name = str(name).strip() or None

        # When clearing (None / empty), skip the role-exists check.
        if name is not None:
            role = await self._role_manager.get(name)
            if role is None:
                return ToolResult(success=False, error=f"No such role: {name}")

        set_current_role(name)
        persisted = False
        if params.get("persist") is True:
            write_persisted_current_role(name)
            persisted = True
        return ToolResult(
            success=True,
            data={
                "active_session": name,
                "active_label": name or "(none — playing CEO)",
                "persisted_to_sidecar": persisted,
                "scope": "session-only" if not persisted else "session+sidecar",
            },
        )


class RoleSyncTool(_RoleToolBase):
    @property
    def name(self) -> str:
        return "role_sync"

    @property
    def description(self) -> str:
        return (
            "Re-read all roles/*.yaml files into the DB. Idempotent. Use "
            "after editing a role YAML by hand so the next role_use / "
            "role_show reflects the change."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        gate = self._check_ready()
        if gate is not None:
            return gate
        try:
            count = await self._role_manager.sync_from_disk()
        except Exception as e:
            return ToolResult(success=False, error=f"role_sync failed: {e}")
        return ToolResult(
            success=True,
            data={"synced": count, "note": "DB now matches roles/*.yaml on disk."},
        )
