"""Company management tools — chat-callable CLI equivalents.

ABE (Autonomous Business Entity) is a concept originated by Petr
Royce in 2023. See ``docs/76-ABE-FRAMEWORK.md`` §Phase 8.

Six tools that wrap the same logic as the ``elophanto company …``
CLI commands so the operator can manage ABEs entirely via chat
without remembering shell syntax:

- ``company_list``     (SAFE)     — all companies + active marker
- ``company_report``   (SAFE)     — headline numbers + recent events
- ``company_create``   (MODERATE) — new company row + data dir
- ``company_use``      (MODERATE) — switch active company
- ``company_pause``    (MODERATE) — pause status
- ``company_resume``   (MODERATE) — resume status

All state-changing tools default to **session-only** contextvar
updates. Pass ``persist=true`` to write the sidecar (so future CLI
+ chat sessions inherit) — this surfaces in the MODERATE approval
prompt so the operator can refuse if they didn't intend a default
change.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult


class _CompanyToolBase(BaseTool):
    """Shared dependency injection for all company management tools."""

    def __init__(self) -> None:
        self._db: Any = None
        self._project_root: Path | None = None
        self._company_manager: Any = None

    @property
    def group(self) -> str:
        return "companies"

    def _check_ready(self) -> ToolResult | None:
        """Return a failure ToolResult when required deps are missing."""
        if self._db is None or self._company_manager is None:
            return ToolResult(
                success=False,
                error=f"{self.name} not initialized (missing db / company_manager)",
            )
        return None


# ── SAFE: reads ────────────────────────────────────────────────────────


class CompanyListTool(_CompanyToolBase):
    @property
    def name(self) -> str:
        return "company_list"

    @property
    def description(self) -> str:
        return (
            "CANONICAL list of ABE-tracked companies. Call FIRST when "
            "asked about companies; do NOT reconstruct from memory. "
            "Returns slug, name, status, active marker, has_product."
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
        from core.company import current_company_id
        from core.product import load_product

        active = current_company_id()
        companies = await self._company_manager.list()
        rows = []
        for c in companies:
            has_product = (
                self._project_root is not None
                and load_product(self._project_root, c.id) is not None
            )
            rows.append(
                {
                    "slug": c.id,
                    "name": c.name,
                    "status": c.status,
                    "active_session": c.id == active,
                    "has_product": has_product,
                }
            )
        return ToolResult(
            success=True,
            data={"companies": rows, "active_session": active, "count": len(rows)},
        )


class CompanyReportTool(_CompanyToolBase):
    @property
    def name(self) -> str:
        return "company_report"

    @property
    def description(self) -> str:
        return (
            "CANONICAL state of an ABE company: revenue, spend, net, "
            "tokens, email touches, pipeline. Reads ledger directly — "
            "call for 'how is X doing' / 'state of X'."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "Company slug. Defaults to the active company.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Recent ledger events to include (default 10, max 50).",
                },
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        gate = self._check_ready()
        if gate is not None:
            return gate
        from core.company import current_company_id
        from core.ledger import ResourceLedger
        from core.product import load_product

        target = str(params.get("slug") or current_company_id())
        limit = min(int(params.get("limit") or 10), 50)

        company = await self._company_manager.get(target)
        if company is None:
            return ToolResult(success=False, error=f"No such company: {target}")

        ledger = ResourceLedger(self._db)
        usd_in = await ledger.sum(target, type="usd", direction="in")
        usd_out = await ledger.sum(target, type="usd", direction="out")
        tokens_out = await ledger.sum(target, type="tokens", direction="out")
        emails_out = await ledger.sum(target, type="email_sent", direction="out")
        pipeline = await ledger.sum(target, type="pipeline_advance", direction="in")
        recent = await ledger.recent(target, limit=limit)

        product = None
        if self._project_root is not None:
            product = load_product(self._project_root, target)
        product_summary = (
            product.what_we_sell.strip().replace("\n", " ")[:300]
            if product is not None
            else None
        )

        # Pipeline-by-stage table
        stage_rows = await self._db.execute(
            "SELECT status, COUNT(*) AS n FROM prospects "
            "WHERE company_id = ? GROUP BY status",
            (target,),
        )
        stages = {r["status"]: int(r["n"]) for r in stage_rows}

        return ToolResult(
            success=True,
            data={
                "slug": company.id,
                "name": company.name,
                "status": company.status,
                "product": product_summary,
                "product_defined": product is not None,
                "headline": {
                    "revenue_usd": round(usd_in, 4),
                    "spend_usd": round(usd_out, 4),
                    "net_usd": round(usd_in - usd_out, 4),
                    "llm_tokens_out": int(tokens_out),
                    "email_touches_out": int(emails_out),
                    "pipeline_advances_in": int(pipeline),
                },
                "pipeline_by_stage": stages,
                "recent_events": recent,
                "data_dir": (
                    str(self._company_manager.data_dir(target))
                    if self._company_manager.data_dir(target) is not None
                    else None
                ),
            },
        )


# ── MODERATE: state changes ────────────────────────────────────────────


class CompanyCreateTool(_CompanyToolBase):
    @property
    def name(self) -> str:
        return "company_create"

    @property
    def description(self) -> str:
        return (
            "Create a new company (ABE). Operator-approved per call. "
            "Slug must be unique; name is the display name. Does NOT write "
            "the product YAML — operator hand-writes it or the agent "
            "proposes via company_set_product later."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "Stable slug (e.g. 'acme-inc'). Stored verbatim.",
                },
                "name": {
                    "type": "string",
                    "description": "Display name; defaults to the slug.",
                },
            },
            "required": ["slug"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        gate = self._check_ready()
        if gate is not None:
            return gate
        slug = str(params.get("slug", "")).strip()
        if not slug:
            return ToolResult(success=False, error="slug is required")
        try:
            company = await self._company_manager.create(
                slug=slug, name=str(params.get("name") or slug)
            )
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        return ToolResult(
            success=True,
            data={
                "slug": company.id,
                "name": company.name,
                "status": company.status,
                "data_dir": (
                    str(self._company_manager.data_dir(company.id))
                    if self._company_manager.data_dir(company.id) is not None
                    else None
                ),
                "next_step": (
                    f"Write companies/{company.id}/company.yaml (operator) or "
                    f"call company_set_product (agent) to anchor the dream phase."
                ),
            },
        )


class CompanyUseTool(_CompanyToolBase):
    @property
    def name(self) -> str:
        return "company_use"

    @property
    def description(self) -> str:
        return (
            "Switch the active company for this session. Session-only by "
            "default — the operator's CLI default is preserved. Pass "
            "persist=true to also write the sidecar so future CLI + chat "
            "sessions inherit (only when the operator explicitly asks for "
            "a default change)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "persist": {
                    "type": "boolean",
                    "description": (
                        "Default false (session-only). True writes "
                        "~/.elophanto/current_company."
                    ),
                },
            },
            "required": ["slug"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        gate = self._check_ready()
        if gate is not None:
            return gate
        from core.company import set_current_company, write_persisted_current_company

        slug = str(params.get("slug", "")).strip()
        if not slug:
            return ToolResult(success=False, error="slug is required")
        company = await self._company_manager.get(slug)
        if company is None:
            return ToolResult(success=False, error=f"No such company: {slug}")

        set_current_company(slug)
        persisted = False
        if params.get("persist") is True:
            write_persisted_current_company(slug)
            persisted = True
        return ToolResult(
            success=True,
            data={
                "active_session": slug,
                "persisted_to_sidecar": persisted,
                "scope": "session-only" if not persisted else "session+sidecar",
            },
        )


class CompanyPauseTool(_CompanyToolBase):
    @property
    def name(self) -> str:
        return "company_pause"

    @property
    def description(self) -> str:
        return (
            "Mark a company as paused. Stops the dream phase from "
            "surfacing it via from_unproductized_companies; existing rows "
            "under it keep working. Reversible via company_resume."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        gate = self._check_ready()
        if gate is not None:
            return gate
        slug = str(params.get("slug", "")).strip()
        if not slug:
            return ToolResult(success=False, error="slug is required")
        ok = await self._company_manager.set_status(slug, "paused")
        if not ok:
            return ToolResult(success=False, error=f"No such company: {slug}")
        return ToolResult(success=True, data={"slug": slug, "status": "paused"})


class CompanyResumeTool(_CompanyToolBase):
    @property
    def name(self) -> str:
        return "company_resume"

    @property
    def description(self) -> str:
        return "Flip a paused company back to active."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        gate = self._check_ready()
        if gate is not None:
            return gate
        slug = str(params.get("slug", "")).strip()
        if not slug:
            return ToolResult(success=False, error="slug is required")
        ok = await self._company_manager.set_status(slug, "active")
        if not ok:
            return ToolResult(success=False, error=f"No such company: {slug}")
        return ToolResult(success=True, data={"slug": slug, "status": "active"})


class CompanyArchiveTool(_CompanyToolBase):
    """Soft-delete a company. Sets status='archived' — hidden from
    the board view, dream phase, candidate generators, and per-cycle
    company iteration. Reversible via `company_resume` (flips back to
    active). Use when a business is shut down or paused indefinitely
    but the historical data (ledger, prospects, drafts, goals) is
    worth keeping for audit.

    For HARD DELETE that wipes the company + all its rows + all its
    files, use `company_purge` (CRITICAL permission). Archive is the
    safe default — almost always what an operator means by "delete".
    """

    @property
    def name(self) -> str:
        return "company_archive"

    @property
    def description(self) -> str:
        return (
            "Soft-delete an ABE company: status → 'archived'. Hidden "
            "from board, dream phase, and arbiter candidate sources. "
            "Reversible via company_resume. Historical data preserved. "
            "For hard delete + cascade wipe use `company_purge`."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        # DESTRUCTIVE — reversible but the operator should approve
        # explicitly. Removing a company from the board is a real
        # state change with downstream impact on autonomous behavior.
        return PermissionLevel.DESTRUCTIVE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        gate = self._check_ready()
        if gate is not None:
            return gate
        slug = str(params.get("slug", "")).strip()
        if not slug:
            return ToolResult(success=False, error="slug is required")
        # Refuse the seed company — accidentally archiving
        # `elophanto-self` would break every production schedule.
        if slug == "elophanto-self":
            return ToolResult(
                success=False,
                error=(
                    "Refusing to archive 'elophanto-self' — that's the "
                    "agent's own ABE. If you truly mean to retire it, "
                    "pause it first and confirm intent in chat."
                ),
            )
        ok = await self._company_manager.set_status(slug, "archived")
        if not ok:
            return ToolResult(success=False, error=f"No such company: {slug}")
        return ToolResult(
            success=True,
            data={
                "slug": slug,
                "status": "archived",
                "next": (
                    f"Company '{slug}' archived. Run `company_resume "
                    "{slug}` to bring it back to active, or "
                    "`company_purge` for hard delete."
                ),
            },
        )


class CompanyPurgeTool(_CompanyToolBase):
    """Hard delete a company. Drops the row from `companies` AND
    cascade-deletes every dependent row across resource_ledger /
    goals / missions / scheduled_tasks / prospects / email_log /
    outreach_log / payment_audit / payment_requests AND removes the
    on-disk artifacts at `companies/<slug>/` + `data/companies/<slug>/`.

    Irreversible. Use only when:
      - The company was a mistake (typo, test artifact).
      - You're sure no historical data is worth keeping.

    For shutting down a real business while keeping audit trail, use
    `company_archive` instead.
    """

    @property
    def name(self) -> str:
        return "company_purge"

    @property
    def description(self) -> str:
        return (
            "HARD DELETE an ABE company + cascade through every "
            "dependent table + remove on-disk artifacts. Irreversible. "
            "Use `company_archive` for the safe reversible default."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "confirm": {
                    "type": "boolean",
                    "description": (
                        "Must be exactly true. A second guard against "
                        "accidental purge — even with CRITICAL approval, "
                        "the operator's intent must include this flag."
                    ),
                },
            },
            "required": ["slug", "confirm"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.CRITICAL

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        gate = self._check_ready()
        if gate is not None:
            return gate
        if self._db is None or self._project_root is None:
            return ToolResult(
                success=False,
                error="company_purge needs db + project_root",
            )
        slug = str(params.get("slug", "")).strip()
        if not slug:
            return ToolResult(success=False, error="slug is required")
        if not bool(params.get("confirm")):
            return ToolResult(
                success=False,
                error=(
                    "company_purge: pass `confirm: true` to acknowledge "
                    "this is irreversible. (CRITICAL approval alone is "
                    "not enough — this flag is a deliberate-intent check.)"
                ),
            )
        if slug == "elophanto-self":
            return ToolResult(
                success=False,
                error=(
                    "Refusing to purge 'elophanto-self' — that's the "
                    "agent's own ABE; purging it would orphan the entire "
                    "production substrate. Archive it instead if you "
                    "really mean to retire."
                ),
            )

        company = await self._company_manager.get(slug)
        if company is None:
            return ToolResult(success=False, error=f"No such company: {slug}")

        # Cascade across every table that carries company_id.
        cascade_tables = (
            "resource_ledger",
            "goals",
            "missions",
            "scheduled_tasks",
            "prospects",
            "outreach_log",
            "email_log",
            "payment_audit",
            "payment_requests",
            "sessions",
            "llm_usage",
        )
        deleted: dict[str, int] = {}
        for table in cascade_tables:
            try:
                rows = await self._db.execute(
                    f"SELECT COUNT(*) AS n FROM {table} WHERE company_id = ?",
                    (slug,),
                )
                n = int(rows[0]["n"]) if rows else 0
                if n > 0:
                    await self._db.execute_insert(
                        f"DELETE FROM {table} WHERE company_id = ?", (slug,)
                    )
                deleted[table] = n
            except Exception:
                # Table might not exist on older schemas; skip rather
                # than abort. The companies row itself still gets deleted.
                deleted[table] = -1

        # Delete the companies row itself
        await self._db.execute_insert("DELETE FROM companies WHERE id = ?", (slug,))

        # Filesystem: companies/<slug>/ + data/companies/<slug>/
        import shutil

        fs_removed: list[str] = []
        for sub in ("companies", "data/companies"):
            target = self._project_root / sub / slug
            if target.is_dir():
                try:
                    shutil.rmtree(target)
                    fs_removed.append(str(target))
                except Exception:
                    pass

        return ToolResult(
            success=True,
            data={
                "slug": slug,
                "deleted_rows": deleted,
                "fs_removed": fs_removed,
                "next": (
                    f"Company '{slug}' purged. All rows + files gone. "
                    "If this was a mistake, restore from git or backup."
                ),
            },
        )


# Convenience timestamp for any tool that needs "now" formatting
def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# Sliding-window helper available for any future-tool that wants
# time-bounded ledger queries. Currently unused by Phase 8 tools but
# kept here so we don't duplicate the pattern when Phase 5 (board view)
# eventually lifts the same logic from cli/company_cmd.py.
def _since_iso(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()
