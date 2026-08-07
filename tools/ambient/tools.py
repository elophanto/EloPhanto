"""Ambient tools — interventions + life model + presence."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

_PRESENCE_TRANSITIONS = frozenset(
    {
        "leave",
        "left",
        "exit",
        "depart",
        "away",
        "arrive",
        "arrived",
        "home",
        "enter",
        "present",
    }
)


class AmbientInterventionListTool(BaseTool):
    def __init__(self) -> None:
        self._intervention_manager: Any = None

    @property
    def group(self) -> str:
        return "ambient"

    @property
    def name(self) -> str:
        return "ambient_intervention_list"

    @property
    def description(self) -> str:
        return (
            "List ambient interventions by status "
            "(proposed|approved|denied|executed|killed|expired)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": [
                        "proposed",
                        "approved",
                        "denied",
                        "executed",
                        "killed",
                        "expired",
                    ],
                    "default": "proposed",
                },
                "limit": {"type": "integer", "default": 20},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._intervention_manager:
            return ToolResult(
                success=False, error="Ambient interventions not initialized"
            )
        status = str(params.get("status") or "proposed")
        limit = int(params.get("limit") or 20)
        try:
            items = await self._intervention_manager.list_by_status(status, limit=limit)
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        return ToolResult(
            success=True,
            data={
                "status": status,
                "count": len(items),
                "interventions": [
                    {
                        "intervention_id": i.intervention_id,
                        "strength": i.strength,
                        "channel": i.channel,
                        "status": i.status,
                        "proposal": i.proposal,
                        "signal_id": i.signal_id,
                        "prediction_id": i.prediction_id,
                        "created_at": i.created_at,
                        "decided_at": i.decided_at,
                        "executed_at": i.executed_at,
                    }
                    for i in items
                ],
            },
        )


class AmbientInterventionDecideTool(BaseTool):
    def __init__(self) -> None:
        self._intervention_manager: Any = None
        self._ego_manager: Any = None

    @property
    def group(self) -> str:
        return "ambient"

    @property
    def name(self) -> str:
        return "ambient_intervention_decide"

    @property
    def description(self) -> str:
        return (
            "Approve or deny an ambient intervention with an explicit receipt. "
            "act/escalate require operator or approval_id — never soft-auto."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "intervention_id": {"type": "string"},
                "decision": {
                    "type": "string",
                    "enum": ["approved", "denied"],
                },
                "operator": {"type": "string"},
                "approval_id": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["intervention_id", "decision"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.CRITICAL

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._intervention_manager:
            return ToolResult(
                success=False, error="Ambient interventions not initialized"
            )
        iid = str(params.get("intervention_id") or "").strip()
        decision = str(params.get("decision") or "").strip()
        if not iid:
            return ToolResult(success=False, error="intervention_id required")
        receipt: dict[str, Any] = {}
        if params.get("operator"):
            receipt["operator"] = str(params["operator"])
        if params.get("approval_id"):
            receipt["approval_id"] = str(params["approval_id"])
        if params.get("note"):
            receipt["note"] = str(params["note"])[:500]
        try:
            result = await self._intervention_manager.decide(iid, decision, receipt)
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        if result is None:
            return ToolResult(success=False, error=f"intervention {iid!r} not found")

        if decision == "denied" and self._ego_manager is not None:
            try:
                summary = ""
                if isinstance(result.proposal, dict):
                    summary = str(result.proposal.get("summary") or "")[:120]
                await self._ego_manager.record_humbling(
                    capability="ambient_anticipation",
                    claimed=f"proposed {result.strength}",
                    actual=f"operator denied: {summary or iid}",
                    task_goal="ambient intervention",
                    source="correction",
                )
            except Exception:
                pass

        return ToolResult(
            success=True,
            data={
                "intervention_id": result.intervention_id,
                "status": result.status,
                "strength": result.strength,
                "receipt": result.receipt,
            },
        )


class AmbientInterventionExecuteTool(BaseTool):
    def __init__(self) -> None:
        self._intervention_manager: Any = None

    @property
    def group(self) -> str:
        return "ambient"

    @property
    def name(self) -> str:
        return "ambient_intervention_execute"

    @property
    def description(self) -> str:
        return (
            "Mark an approved ambient intervention as executed with a receipt. "
            "act/escalate refuse without prior approval + operator/approval_id."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "intervention_id": {"type": "string"},
                "operator": {"type": "string"},
                "approval_id": {"type": "string"},
                "outcome": {"type": "string"},
                "signal_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["intervention_id"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.CRITICAL

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._intervention_manager:
            return ToolResult(
                success=False, error="Ambient interventions not initialized"
            )
        iid = str(params.get("intervention_id") or "").strip()
        if not iid:
            return ToolResult(success=False, error="intervention_id required")
        receipt: dict[str, Any] = {}
        if params.get("operator"):
            receipt["operator"] = str(params["operator"])
        if params.get("approval_id"):
            receipt["approval_id"] = str(params["approval_id"])
        if params.get("outcome"):
            receipt["outcome"] = str(params["outcome"])[:500]
        if params.get("signal_ids"):
            receipt["signal_ids"] = list(params["signal_ids"])
        try:
            result = await self._intervention_manager.mark_executed(iid, receipt)
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        if result is None:
            return ToolResult(success=False, error=f"intervention {iid!r} not found")
        return ToolResult(
            success=True,
            data={
                "intervention_id": result.intervention_id,
                "status": result.status,
                "receipt": result.receipt,
                "executed_at": result.executed_at,
            },
        )


class AmbientPresenceReportTool(BaseTool):
    def __init__(self) -> None:
        self._signal_store: Any = None
        self._ambient_model: Any = None

    @property
    def group(self) -> str:
        return "ambient"

    @property
    def name(self) -> str:
        return "ambient_presence_report"

    @property
    def description(self) -> str:
        return (
            "Report a digital presence transition for a person "
            "(leave|arrive|away|home). Never cameras — explicit opt-in only."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "transition": {
                    "type": "string",
                    "enum": sorted(_PRESENCE_TRANSITIONS),
                },
                "person_id": {"type": "string"},
                "urgency": {"type": "number", "default": 0.55},
                "note": {"type": "string"},
            },
            "required": ["transition"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._signal_store:
            return ToolResult(success=False, error="Ambient signals not initialized")
        transition = str(params.get("transition") or "").strip().lower()
        if transition not in _PRESENCE_TRANSITIONS:
            return ToolResult(
                success=False,
                error=f"transition must be one of {sorted(_PRESENCE_TRANSITIONS)}",
            )
        person_id = str(params.get("person_id") or "").strip()
        household_id = None
        if not person_id and self._ambient_model is not None:
            try:
                hh = await self._ambient_model.get_primary_household()
                if hh:
                    household_id = hh.household_id
                    persons = await self._ambient_model.list_persons(hh.household_id)
                    op = next((p for p in persons if p.role == "operator"), None)
                    if op:
                        person_id = op.person_id
            except Exception:
                pass
        if not person_id:
            return ToolResult(
                success=False, error="person_id required (no operator person found)"
            )
        urgency = float(params.get("urgency") or 0.55)
        note = str(params.get("note") or "")[:200]
        sid = await self._signal_store.ingest(
            kind="presence",
            source="ambient_presence_report",
            urgency=urgency,
            payload={"transition": transition, "person_id": person_id, "note": note},
            household_id=household_id,
            subject_ref=person_id,
            dedup_key=f"presence:{person_id}:{transition}",
        )
        return ToolResult(
            success=True,
            data={
                "signal_id": sid,
                "person_id": person_id,
                "transition": transition,
            },
        )


class AmbientHouseholdShowTool(BaseTool):
    def __init__(self) -> None:
        self._ambient_model: Any = None

    @property
    def group(self) -> str:
        return "ambient"

    @property
    def name(self) -> str:
        return "ambient_household_show"

    @property
    def description(self) -> str:
        return "Show the primary household (id, name, timezone) for this company."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._ambient_model:
            return ToolResult(success=False, error="Ambient model not initialized")
        hh = await self._ambient_model.get_primary_household()
        if hh is None:
            return ToolResult(success=False, error="no household")
        return ToolResult(
            success=True,
            data={
                "household_id": hh.household_id,
                "name": hh.name,
                "timezone": hh.timezone,
                "company_id": hh.company_id,
            },
        )


class AmbientHouseholdSetTimezoneTool(BaseTool):
    def __init__(self) -> None:
        self._ambient_model: Any = None

    @property
    def group(self) -> str:
        return "ambient"

    @property
    def name(self) -> str:
        return "ambient_household_set_timezone"

    @property
    def description(self) -> str:
        return "Set the primary household IANA timezone (e.g. America/New_York)."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "timezone": {"type": "string"},
                "household_id": {"type": "string"},
            },
            "required": ["timezone"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._ambient_model:
            return ToolResult(success=False, error="Ambient model not initialized")
        tz = str(params.get("timezone") or "").strip()
        if not tz:
            return ToolResult(success=False, error="timezone required")
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(tz)
        except Exception:
            return ToolResult(success=False, error=f"invalid timezone {tz!r}")
        hid = str(params.get("household_id") or "").strip()
        if not hid:
            hh = await self._ambient_model.get_primary_household()
            if hh is None:
                return ToolResult(success=False, error="no household")
            hid = hh.household_id
        updated = await self._ambient_model.update_household_timezone(hid, tz)
        if updated is None:
            return ToolResult(success=False, error="household not found")
        return ToolResult(
            success=True,
            data={
                "household_id": updated.household_id,
                "timezone": updated.timezone,
            },
        )


class AmbientPersonListTool(BaseTool):
    def __init__(self) -> None:
        self._ambient_model: Any = None

    @property
    def group(self) -> str:
        return "ambient"

    @property
    def name(self) -> str:
        return "ambient_person_list"

    @property
    def description(self) -> str:
        return "List persons in the primary (or given) household."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"household_id": {"type": "string"}},
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._ambient_model:
            return ToolResult(success=False, error="Ambient model not initialized")
        hid = str(params.get("household_id") or "").strip()
        if not hid:
            hh = await self._ambient_model.get_primary_household()
            if hh is None:
                return ToolResult(success=False, error="no household")
            hid = hh.household_id
        persons = await self._ambient_model.list_persons(hid)
        return ToolResult(
            success=True,
            data={
                "household_id": hid,
                "persons": [
                    {
                        "person_id": p.person_id,
                        "display_name": p.display_name,
                        "role": p.role,
                    }
                    for p in persons
                ],
            },
        )


class AmbientPersonCreateTool(BaseTool):
    def __init__(self) -> None:
        self._ambient_model: Any = None

    @property
    def group(self) -> str:
        return "ambient"

    @property
    def name(self) -> str:
        return "ambient_person_create"

    @property
    def description(self) -> str:
        return "Create a person in the primary household (scoped life model)."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "display_name": {"type": "string"},
                "role": {"type": "string"},
                "household_id": {"type": "string"},
            },
            "required": ["display_name"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._ambient_model:
            return ToolResult(success=False, error="Ambient model not initialized")
        name = str(params.get("display_name") or "").strip()
        if not name:
            return ToolResult(success=False, error="display_name required")
        hid = str(params.get("household_id") or "").strip()
        if not hid:
            hh = await self._ambient_model.get_primary_household()
            if hh is None:
                return ToolResult(success=False, error="no household")
            hid = hh.household_id
        person = await self._ambient_model.create_person(
            hid,
            name,
            role=str(params.get("role") or "").strip() or None,
        )
        return ToolResult(
            success=True,
            data={
                "person_id": person.person_id,
                "display_name": person.display_name,
                "role": person.role,
                "household_id": person.household_id,
            },
        )


class AmbientRoutineListTool(BaseTool):
    def __init__(self) -> None:
        self._ambient_model: Any = None

    @property
    def group(self) -> str:
        return "ambient"

    @property
    def name(self) -> str:
        return "ambient_routine_list"

    @property
    def description(self) -> str:
        return "List routines for the primary household (optionally by status)."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "household_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["active", "paused", "retired"],
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._ambient_model:
            return ToolResult(success=False, error="Ambient model not initialized")
        hid = str(params.get("household_id") or "").strip()
        if not hid:
            hh = await self._ambient_model.get_primary_household()
            if hh is None:
                return ToolResult(success=False, error="no household")
            hid = hh.household_id
        status = params.get("status")
        routines = await self._ambient_model.list_routines(
            hid, status=str(status) if status else "active"
        )
        return ToolResult(
            success=True,
            data={
                "household_id": hid,
                "routines": [
                    {
                        "routine_id": r.routine_id,
                        "title": r.title,
                        "window_start": r.window_start,
                        "window_end": r.window_end,
                        "person_id": r.person_id,
                        "status": r.status,
                    }
                    for r in routines
                ],
            },
        )


class AmbientRoutineCreateTool(BaseTool):
    def __init__(self) -> None:
        self._ambient_model: Any = None

    @property
    def group(self) -> str:
        return "ambient"

    @property
    def name(self) -> str:
        return "ambient_routine_create"

    @property
    def description(self) -> str:
        return "Create an active routine with optional HH:MM window for predictions."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "window_start": {"type": "string"},
                "window_end": {"type": "string"},
                "person_id": {"type": "string"},
                "household_id": {"type": "string"},
            },
            "required": ["title"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._ambient_model:
            return ToolResult(success=False, error="Ambient model not initialized")
        title = str(params.get("title") or "").strip()
        if not title:
            return ToolResult(success=False, error="title required")
        hid = str(params.get("household_id") or "").strip()
        person_id = str(params.get("person_id") or "").strip() or None
        if not hid:
            hh = await self._ambient_model.get_primary_household()
            if hh is None:
                return ToolResult(success=False, error="no household")
            hid = hh.household_id
            if not person_id:
                persons = await self._ambient_model.list_persons(hid)
                op = next((p for p in persons if p.role == "operator"), None)
                if op:
                    person_id = op.person_id
        routine = await self._ambient_model.create_routine(
            hid,
            title,
            window_start=str(params.get("window_start") or "").strip() or None,
            window_end=str(params.get("window_end") or "").strip() or None,
            person_id=person_id,
        )
        return ToolResult(
            success=True,
            data={
                "routine_id": routine.routine_id,
                "title": routine.title,
                "window_start": routine.window_start,
                "window_end": routine.window_end,
                "person_id": routine.person_id,
                "status": routine.status,
            },
        )


class AmbientRoutinePauseTool(BaseTool):
    def __init__(self) -> None:
        self._ambient_model: Any = None

    @property
    def group(self) -> str:
        return "ambient"

    @property
    def name(self) -> str:
        return "ambient_routine_pause"

    @property
    def description(self) -> str:
        return "Pause or retire a routine (status=paused|retired)."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "routine_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["paused", "retired"],
                    "default": "paused",
                },
            },
            "required": ["routine_id"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._ambient_model:
            return ToolResult(success=False, error="Ambient model not initialized")
        rid = str(params.get("routine_id") or "").strip()
        status = str(params.get("status") or "paused").strip()
        if not rid:
            return ToolResult(success=False, error="routine_id required")
        try:
            routine = await self._ambient_model.set_routine_status(rid, status)
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        if routine is None:
            return ToolResult(success=False, error="routine not found")
        return ToolResult(
            success=True,
            data={"routine_id": routine.routine_id, "status": routine.status},
        )


class AmbientCalibrationShowTool(BaseTool):
    def __init__(self) -> None:
        self._ambient_predictor: Any = None

    @property
    def group(self) -> str:
        return "ambient"

    @property
    def name(self) -> str:
        return "ambient_calibration_show"

    @property
    def description(self) -> str:
        return (
            "Show per-routine prediction calibration "
            "(n, miss_rate, unknown_rate, hist_ready)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._ambient_predictor:
            return ToolResult(success=False, error="Ambient predictor not initialized")
        summary = await self._ambient_predictor.calibration_summary()
        return ToolResult(success=True, data={"routines": summary})
