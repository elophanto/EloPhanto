"""``gcal`` — the operator's real calendar: read, schedule, reschedule, cancel."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult
from tools.google.base import GoogleAuthMissing, google_request

logger = logging.getLogger(__name__)

_API = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarTool(BaseTool):
    """Google Calendar over the operator's OAuth grant."""

    def __init__(self) -> None:
        self._token_store: Any = None  # injected
        self._broker: Any = None
        self._scope_guard: Any = None
        self._net_policy: Any = None
        self._bindings: dict[str, str] = {}

    @property
    def name(self) -> str:
        return "gcal"

    @property
    def group(self) -> str:
        return "scheduling"

    @property
    def description(self) -> str:
        return (
            "Read and manage the operator's Google Calendar. Actions: "
            "'list' (upcoming events), 'create', 'update', 'delete', "
            "'freebusy' (find open slots), 'calendars'. Times are ISO 8601; "
            "pass a timezone or the calendar default is used. Requires "
            "`elophanto oauth login google`."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "list | create | update | delete | freebusy | calendars",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar id (default 'primary').",
                },
                "event_id": {
                    "type": "string",
                    "description": "Event id for update/delete.",
                },
                "summary": {"type": "string", "description": "Event title."},
                "description": {"type": "string", "description": "Event description."},
                "location": {"type": "string", "description": "Event location."},
                "start": {
                    "type": "string",
                    "description": "ISO 8601 start, e.g. 2026-08-14T18:00:00 or 2026-08-14 for all-day.",
                },
                "end": {"type": "string", "description": "ISO 8601 end."},
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone, e.g. Europe/Prague.",
                },
                "attendees": {
                    "type": "array",
                    "description": "Attendee email addresses.",
                    "items": {"type": "string"},
                },
                "days_ahead": {
                    "type": "integer",
                    "description": "Window for list/freebusy (default 7).",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Result cap for list (default 20).",
                },
            },
            "required": ["action"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    def dynamic_permission_level(
        self, params: dict[str, Any]
    ) -> PermissionLevel | None:
        """Deleting an event is the irreversible one, and it often has guests.

        Cancelling a meeting mails everyone invited — that is a social act as
        much as a data change, so it always confirms even in full_auto.
        """
        action = str(params.get("action", "") or "").lower()
        if action in ("list", "freebusy", "calendars"):
            return PermissionLevel.SAFE
        if action == "delete":
            return PermissionLevel.CRITICAL
        if action == "create" and params.get("attendees"):
            # Inviting other people is outbound comms, not a private note.
            return PermissionLevel.CRITICAL
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        action = str(params.get("action", "") or "").lower()
        cal_id = str(params.get("calendar_id", "") or "primary")
        try:
            if action == "list":
                return await self._list(cal_id, params)
            if action == "create":
                return await self._create(cal_id, params)
            if action == "update":
                return await self._update(cal_id, params)
            if action == "delete":
                return await self._delete(cal_id, params)
            if action == "freebusy":
                return await self._freebusy(cal_id, params)
            if action == "calendars":
                data = await google_request(
                    self._token_store, "GET", f"{_API}/users/me/calendarList"
                )
                return ToolResult(
                    success=True,
                    data={
                        "calendars": [
                            {
                                "id": c.get("id"),
                                "summary": c.get("summary"),
                                "primary": c.get("primary", False),
                                "timezone": c.get("timeZone"),
                            }
                            for c in data.get("items", [])
                        ]
                    },
                )
            return ToolResult(
                success=False,
                error=(
                    f"Unknown action {action!r}. Use list, create, update, "
                    "delete, freebusy, or calendars."
                ),
            )
        except GoogleAuthMissing as exc:
            return ToolResult(success=False, error=str(exc))
        except Exception as exc:
            logger.error("gcal %s failed: %s", action, exc)
            return ToolResult(success=False, error=f"Calendar {action} failed: {exc}")

    # ── actions ─────────────────────────────────────────────────────

    async def _list(self, cal_id: str, params: dict[str, Any]) -> ToolResult:
        days = int(params.get("days_ahead") or 7)
        now = datetime.now(UTC)
        data = await google_request(
            self._token_store,
            "GET",
            f"{_API}/calendars/{cal_id}/events",
            params={
                "timeMin": now.isoformat(),
                "timeMax": (now + timedelta(days=days)).isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": max(1, min(int(params.get("max_results") or 20), 250)),
            },
        )
        return ToolResult(
            success=True,
            data={
                "events": [_summarize(e) for e in data.get("items", [])],
                "window_days": days,
            },
        )

    async def _create(self, cal_id: str, params: dict[str, Any]) -> ToolResult:
        if not params.get("start") or not params.get("end"):
            return ToolResult(
                success=False, error="create requires both `start` and `end`."
            )
        body = _event_body(params)
        created = await google_request(
            self._token_store,
            "POST",
            f"{_API}/calendars/{cal_id}/events",
            params={"sendUpdates": "all" if params.get("attendees") else "none"},
            json_body=body,
        )
        return ToolResult(success=True, data=_summarize(created))

    async def _update(self, cal_id: str, params: dict[str, Any]) -> ToolResult:
        event_id = str(params.get("event_id", "") or "")
        if not event_id:
            return ToolResult(success=False, error="update requires `event_id`.")
        # PATCH so unspecified fields survive — a partial update must not
        # silently strip the description or the guest list.
        updated = await google_request(
            self._token_store,
            "PATCH",
            f"{_API}/calendars/{cal_id}/events/{event_id}",
            params={"sendUpdates": "all" if params.get("attendees") else "none"},
            json_body=_event_body(params, partial=True),
        )
        return ToolResult(success=True, data=_summarize(updated))

    async def _delete(self, cal_id: str, params: dict[str, Any]) -> ToolResult:
        event_id = str(params.get("event_id", "") or "")
        if not event_id:
            return ToolResult(success=False, error="delete requires `event_id`.")
        await google_request(
            self._token_store,
            "DELETE",
            f"{_API}/calendars/{cal_id}/events/{event_id}",
            params={"sendUpdates": "all"},
        )
        return ToolResult(success=True, data={"deleted": event_id})

    async def _freebusy(self, cal_id: str, params: dict[str, Any]) -> ToolResult:
        days = int(params.get("days_ahead") or 7)
        now = datetime.now(UTC)
        end = now + timedelta(days=days)
        data = await google_request(
            self._token_store,
            "POST",
            f"{_API}/freeBusy",
            json_body={
                "timeMin": now.isoformat(),
                "timeMax": end.isoformat(),
                "items": [{"id": cal_id}],
            },
        )
        busy = data.get("calendars", {}).get(cal_id, {}).get("busy", [])
        return ToolResult(
            success=True,
            data={
                "busy": busy,
                "window": {"start": now.isoformat(), "end": end.isoformat()},
            },
        )


def _event_body(params: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if params.get("summary"):
        body["summary"] = str(params["summary"])
    if params.get("description"):
        body["description"] = str(params["description"])
    if params.get("location"):
        body["location"] = str(params["location"])
    tz = params.get("timezone")
    if params.get("start"):
        body["start"] = _time_field(str(params["start"]), tz)
    if params.get("end"):
        body["end"] = _time_field(str(params["end"]), tz)
    if params.get("attendees"):
        body["attendees"] = [{"email": str(a)} for a in params["attendees"]]
    if not partial and "summary" not in body:
        body["summary"] = "(untitled)"
    return body


def _time_field(value: str, tz: Any) -> dict[str, str]:
    """Date-only values are all-day events; everything else is a dateTime."""
    if len(value) == 10 and value.count("-") == 2:
        return {"date": value}
    field: dict[str, str] = {"dateTime": value}
    if tz:
        field["timeZone"] = str(tz)
    return field


def _summarize(event: dict[str, Any]) -> dict[str, Any]:
    start = event.get("start", {}) or {}
    end = event.get("end", {}) or {}
    return {
        "id": event.get("id"),
        "summary": event.get("summary", ""),
        "start": start.get("dateTime") or start.get("date", ""),
        "end": end.get("dateTime") or end.get("date", ""),
        "location": event.get("location", ""),
        "attendees": [a.get("email") for a in event.get("attendees", []) or []],
        "link": event.get("htmlLink", ""),
        "status": event.get("status", ""),
    }
