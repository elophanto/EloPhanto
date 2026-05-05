"""``job_record`` — dedup + status tracking for paid jobs.

The companion to ``job_verify``. After verifying an envelope, the
agent calls this to either:
  - mark a job ``seen`` (returns ``already_seen=true`` if it's a
    duplicate the agent has already accepted/processed)
  - mark it ``accepted`` (we're committing to do the work)
  - mark it ``completed`` with a result string
  - mark it ``failed`` with a reason

Status is monotonic: seen → accepted → completed/failed. The tool
refuses backwards transitions so an honest mistake in the skill
ritual can't accidentally re-open a completed job.

SAFE permission level (writes only to a local SQLite table the
agent owns; no side effects beyond persistence).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

_VALID_STATUSES = ("seen", "accepted", "completed", "failed")


class JobRecordTool(BaseTool):
    """Record / update a job's local status. Used for dedup + audit."""

    @property
    def group(self) -> str:
        return "jobs"

    def __init__(self) -> None:
        # Database handle injected at agent startup (same pattern as
        # other DB-touching tools — see PaymentRequestTool, etc.).
        self._db: Any = None

    @property
    def name(self) -> str:
        return "job_record"

    @property
    def description(self) -> str:
        return (
            "Record a paid-job's status in the local jobs table. Used "
            "for dedup (mark `seen` after every job_verify; if the "
            "result includes `already_seen: true`, skip the job — "
            "we've handled it before) and for audit (mark `accepted` "
            "before execution, then `completed` with the deliverable "
            "or `failed` with a reason). Status moves forward only — "
            "the tool refuses to roll a `completed` job back to `seen`."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Job ULID from the verified envelope.",
                },
                "status": {
                    "type": "string",
                    "enum": list(_VALID_STATUSES),
                    "description": (
                        "Target status. Use `seen` right after "
                        "verification (dedup check), `accepted` "
                        "before starting work, `completed` when "
                        "delivering the result, `failed` if you "
                        "cannot or will not perform the task."
                    ),
                },
                "task": {
                    "type": "string",
                    "description": (
                        "The task text from the verified envelope. "
                        "Required when first marking `seen` so the "
                        "row has a complete record; ignored on "
                        "subsequent updates."
                    ),
                },
                "requester_email": {
                    "type": "string",
                    "description": (
                        "Requester's email from the envelope. Stored "
                        "alongside `task` on first `seen` so the "
                        "completion path doesn't need to re-parse "
                        "the envelope to know who to reply to."
                    ),
                },
                "requester_wallet": {
                    "type": "string",
                    "description": "Requester's Solana wallet (optional).",
                },
                "result": {
                    "type": "string",
                    "description": (
                        "Result text — what got delivered (for "
                        "`completed`) or the rejection reason (for "
                        "`failed`). Stored verbatim; the website "
                        "may render it via /api/jobs/:id/result."
                    ),
                },
                "expires_at": {
                    "type": "string",
                    "description": "ISO-8601 expiry from envelope (stored on `seen`).",
                },
                "issued_at": {
                    "type": "string",
                    "description": "ISO-8601 issued-at from envelope (stored on `seen`).",
                },
            },
            "required": ["job_id", "status"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._db is None:
            return ToolResult(
                success=False,
                data={},
                error="job_record: database handle not injected",
            )

        job_id = (params.get("job_id") or "").strip()
        status = (params.get("status") or "").strip()
        if not job_id:
            return ToolResult(success=False, data={}, error="job_id is required")
        if status not in _VALID_STATUSES:
            return ToolResult(
                success=False,
                data={},
                error=f"status must be one of {_VALID_STATUSES}",
            )

        now = datetime.now(UTC).isoformat()

        # Read existing row (if any) to enforce monotonic status.
        rows = await self._db.execute(
            "SELECT status FROM jobs WHERE job_id = ?", (job_id,)
        )
        existing_status = rows[0]["status"] if rows else None

        # Dedup signal — if this is a `seen` call and we've moved
        # past `seen` already, surface `already_seen` so the skill
        # ritual can short-circuit. A repeat `seen` on a row that's
        # also still at `seen` is a no-op (no duplicate work yet).
        if status == "seen" and existing_status is not None:
            return ToolResult(
                success=True,
                data={
                    "job_id": job_id,
                    "already_seen": True,
                    "current_status": existing_status,
                },
            )

        # Forward-only transition rule. seen < accepted < completed = failed.
        order = {"seen": 0, "accepted": 1, "completed": 2, "failed": 2}
        if existing_status is not None:
            cur = order.get(existing_status, -1)
            new = order.get(status, -1)
            if new < cur:
                return ToolResult(
                    success=False,
                    data={
                        "job_id": job_id,
                        "current_status": existing_status,
                        "rejected_status": status,
                    },
                    error=(
                        f"refusing backwards status transition "
                        f"{existing_status!r} -> {status!r}"
                    ),
                )
            # Same-or-forward — proceed.

        if existing_status is None:
            # First write — insert a new row. Caller should provide
            # task + email at this point so the audit row is complete.
            await self._db.execute(
                """
                INSERT INTO jobs (
                    job_id, task, requester_email, requester_wallet,
                    status, result, issued_at, expires_at,
                    seen_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    str(params.get("task", "")),
                    str(params.get("requester_email", "")),
                    str(params.get("requester_wallet", "")),
                    status,
                    str(params.get("result", "")),
                    str(params.get("issued_at", "")),
                    str(params.get("expires_at", "")),
                    now,
                    now if status in ("completed", "failed") else "",
                ),
            )
        else:
            # Update existing row — bump status + result, set
            # completed_at on terminal transitions.
            completed_at = now if status in ("completed", "failed") else ""
            await self._db.execute(
                """
                UPDATE jobs
                   SET status = ?,
                       result = COALESCE(NULLIF(?, ''), result),
                       completed_at = CASE
                           WHEN ? <> '' THEN ?
                           ELSE completed_at
                       END
                 WHERE job_id = ?
                """,
                (
                    status,
                    str(params.get("result", "")),
                    completed_at,
                    completed_at,
                    job_id,
                ),
            )

        return ToolResult(
            success=True,
            data={
                "job_id": job_id,
                "status": status,
                "already_seen": False,
            },
        )
