"""Mission tools — CRUD + momentum for the missions tier.

Five tools, one file: list / create / set_status / touch / update.
All wrap ``MissionManager``; injection happens in ``Agent._inject_*_deps``.

Missions are durable drives (alphascala-launch, elophanto-growth,
elo-recovery, capability-development, social-presence). They are
NEVER auto-completed — only paused or retired by the operator. See
docs/75-AUTONOMOUS-MIND-V2.md §Phase 2.
"""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class _MissionToolBase(BaseTool):
    """Shared injection + group for all mission tools."""

    def __init__(self) -> None:
        self._mission_manager: Any = None

    @property
    def group(self) -> str:
        return "missions"


class MissionListTool(_MissionToolBase):
    @property
    def name(self) -> str:
        return "mission_list"

    @property
    def description(self) -> str:
        return (
            "List missions (durable drives the agent works toward across many "
            "goals). Returns id, title, status, priority_weight, "
            "momentum_score, last_touched_at. Defaults to active missions; "
            "pass status='all' to include paused and retired."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "paused", "retired", "all"],
                    "description": "Filter by status. Default 'active'.",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._mission_manager:
            return ToolResult(success=False, error="Mission system not initialized")
        status = params.get("status", "active")
        filter_status: str | None = None if status == "all" else status
        try:
            missions = await self._mission_manager.list_missions(status=filter_status)
            return ToolResult(
                success=True,
                data={
                    "count": len(missions),
                    "missions": [
                        {
                            "mission_id": m.mission_id,
                            "title": m.title,
                            "description": m.description,
                            "status": m.status,
                            "priority_weight": m.priority_weight,
                            "momentum_score": round(m.decayed_momentum(), 3),
                            "last_touched_at": m.last_touched_at,
                            "staleness_hours": (
                                round(m.staleness_hours(), 1)
                                if m.last_touched_at
                                else None
                            ),
                        }
                        for m in missions
                    ],
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"mission_list failed: {e}")


class MissionCreateTool(_MissionToolBase):
    @property
    def name(self) -> str:
        return "mission_create"

    @property
    def description(self) -> str:
        return (
            "Create a new mission (durable drive). Use sparingly — missions "
            "are long-running and operator-supervised, not per-task. Returns "
            "the new mission_id."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title."},
                "description": {
                    "type": "string",
                    "description": "What success looks like over the long arc.",
                },
                "priority_weight": {
                    "type": "number",
                    "description": (
                        "Higher = more attention. Default 1.0; reserve >2.0 "
                        "for the agent's top one or two missions."
                    ),
                },
                "mission_id": {
                    "type": "string",
                    "description": (
                        "Optional stable slug (e.g. 'alphascala-launch') so "
                        "config and identity can reference it by name. "
                        "Auto-generated if omitted."
                    ),
                },
            },
            "required": ["title"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._mission_manager:
            return ToolResult(success=False, error="Mission system not initialized")
        title = params.get("title", "").strip()
        if not title:
            return ToolResult(success=False, error="title is required")
        try:
            m = await self._mission_manager.create(
                title=title,
                description=params.get("description", ""),
                priority_weight=float(params.get("priority_weight", 1.0)),
                mission_id=params.get("mission_id"),
            )
            return ToolResult(
                success=True,
                data={
                    "mission_id": m.mission_id,
                    "title": m.title,
                    "status": m.status,
                    "priority_weight": m.priority_weight,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"mission_create failed: {e}")


class MissionStatusTool(_MissionToolBase):
    """Change status (active|paused|retired) OR fetch a single mission.

    Bundled into one tool because both share the same surface (a
    mission_id lookup) and splitting them inflated the tool count
    without adding clarity. Pass ``status`` to mutate; omit it to
    just read.
    """

    @property
    def name(self) -> str:
        return "mission_status"

    @property
    def description(self) -> str:
        return (
            "Get or change a mission's status. Pass mission_id alone to "
            "fetch; pass mission_id + status to set it (active|paused|"
            "retired). Missions are NEVER completed — only paused or "
            "retired."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mission_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["active", "paused", "retired"],
                    "description": "If omitted, returns current state only.",
                },
            },
            "required": ["mission_id"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._mission_manager:
            return ToolResult(success=False, error="Mission system not initialized")
        mid = params.get("mission_id", "").strip()
        if not mid:
            return ToolResult(success=False, error="mission_id is required")
        try:
            if "status" in params and params["status"]:
                ok = await self._mission_manager.set_status(mid, params["status"])
                if not ok:
                    return ToolResult(success=False, error=f"mission {mid!r} not found")
            m = await self._mission_manager.get(mid)
            if not m:
                return ToolResult(success=False, error=f"mission {mid!r} not found")
            return ToolResult(
                success=True,
                data={
                    "mission_id": m.mission_id,
                    "title": m.title,
                    "description": m.description,
                    "status": m.status,
                    "priority_weight": m.priority_weight,
                    "momentum_score": round(m.decayed_momentum(), 3),
                    "last_touched_at": m.last_touched_at,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"mission_status failed: {e}")


class MissionTouchTool(_MissionToolBase):
    """Log meaningful progress on a mission.

    Bumps momentum and refreshes last_touched_at. The mind should call
    this when it shipped a public artifact under the mission (a post,
    a new tool, a feature release) or after a goal under the mission
    completes (which the goal-completion hook also handles
    automatically; this tool exists for manual / non-goal progress).
    """

    @property
    def name(self) -> str:
        return "mission_touch"

    @property
    def description(self) -> str:
        return (
            "Log progress on a mission. Bumps momentum_score and "
            "last_touched_at. Use when you shipped something under this "
            "mission that didn't go through a goal (a post, a quick "
            "experiment, an outreach reply)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mission_id": {"type": "string"},
                "bump": {
                    "type": "number",
                    "description": (
                        "How much momentum to add. Default 1.0. Use 0.5 for "
                        "small wins (a single post), 2.0 for big ones "
                        "(launch, milestone)."
                    ),
                },
                "note": {
                    "type": "string",
                    "description": "Optional short description of what you did.",
                },
            },
            "required": ["mission_id"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._mission_manager:
            return ToolResult(success=False, error="Mission system not initialized")
        mid = params.get("mission_id", "").strip()
        if not mid:
            return ToolResult(success=False, error="mission_id is required")
        try:
            m = await self._mission_manager.touch(
                mid, bump=float(params.get("bump", 1.0))
            )
            if not m:
                return ToolResult(success=False, error=f"mission {mid!r} not found")
            return ToolResult(
                success=True,
                data={
                    "mission_id": m.mission_id,
                    "momentum_score": round(m.momentum_score, 3),
                    "last_touched_at": m.last_touched_at,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"mission_touch failed: {e}")


class MissionUpdateTool(_MissionToolBase):
    @property
    def name(self) -> str:
        return "mission_update"

    @property
    def description(self) -> str:
        return (
            "Update a mission's title, description, or priority_weight. "
            "Only fields you pass are changed. Use to refine a mission as "
            "the operator's understanding sharpens."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mission_id": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "priority_weight": {"type": "number"},
            },
            "required": ["mission_id"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._mission_manager:
            return ToolResult(success=False, error="Mission system not initialized")
        mid = params.get("mission_id", "").strip()
        if not mid:
            return ToolResult(success=False, error="mission_id is required")
        try:
            ok = await self._mission_manager.update(
                mid,
                title=params.get("title"),
                description=params.get("description"),
                priority_weight=(
                    float(params["priority_weight"])
                    if "priority_weight" in params
                    else None
                ),
            )
            if not ok:
                return ToolResult(
                    success=False,
                    error=f"mission {mid!r} not found or no fields to update",
                )
            m = await self._mission_manager.get(mid)
            return ToolResult(
                success=True,
                data={
                    "mission_id": m.mission_id,
                    "title": m.title,
                    "priority_weight": m.priority_weight,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"mission_update failed: {e}")
