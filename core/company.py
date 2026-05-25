"""Company scope — the single isolation key for the ABE framework.

ABE (Autonomous Business Entity) is a concept originated by Petr
Royce, May 2026. See ``docs/76-ABE-FRAMEWORK.md`` for the full design. Companies are
slugs (``elophanto-self``, ``acme-inc``, ...) threaded as ``company_id``
through every multi-tenant table. The active company for the current
async task is tracked via a ``contextvars.ContextVar`` so callers don't
have to plumb it through every signature. Default is ``elophanto-self``
so any code path that forgets to set it gets safe behavior, not a crash.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.database import Database


DEFAULT_COMPANY_ID = "elophanto-self"

# Module-level context var. The default exists so unit tests and any
# legacy code path that doesn't yet thread company context still get a
# valid company_id at write time. The mind loop and the CLI flip this
# explicitly per cycle / per command.
_current_company: contextvars.ContextVar[str] = contextvars.ContextVar(
    "elophanto_company_id", default=DEFAULT_COMPANY_ID
)


def current_company_id() -> str:
    """Return the currently active company id for this async context."""
    return _current_company.get()


def set_current_company(company_id: str) -> contextvars.Token[str]:
    """Set the active company. Returns a token usable with reset()."""
    return _current_company.set(company_id)


def reset_current_company(token: contextvars.Token[str]) -> None:
    _current_company.reset(token)


@dataclass(slots=True)
class Company:
    id: str
    name: str
    status: str  # 'active' | 'paused' | 'archived'
    product_yaml: str | None
    created_at: str
    updated_at: str


# Where the CLI persists the operator's selected company between
# invocations. Process-wide contextvar reads this on startup.
_CURRENT_COMPANY_FILE = Path.home() / ".elophanto" / "current_company"


def read_persisted_current_company() -> str | None:
    """Read the operator's selected company from the persistence file.

    Returns ``None`` if the file is missing, empty, or unreadable.
    Never raises — a corrupt sidecar file falls back to the default.
    """
    try:
        if not _CURRENT_COMPANY_FILE.exists():
            return None
        slug = _CURRENT_COMPANY_FILE.read_text(encoding="utf-8").strip()
        return slug or None
    except OSError:
        return None


def write_persisted_current_company(company_id: str) -> None:
    _CURRENT_COMPANY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CURRENT_COMPANY_FILE.write_text(company_id, encoding="utf-8")


class CompanyManager:
    """CRUD over the ``companies`` table.

    Deliberately thin — companies are slugs + a name + a status. The
    interesting state (revenue, pipeline, role activity) lives in
    ``resource_ledger`` and per-company-scoped rows on other tables.

    ABE Phase 6: when ``project_root`` is supplied, ``create()`` also
    materializes the per-company data directory at
    ``<project_root>/data/companies/<slug>/`` so tools that want per-
    company file state have a stable location to write into.
    """

    def __init__(self, db: Database, *, project_root: Path | None = None) -> None:
        self._db = db
        self._project_root = project_root

    def data_dir(self, company_id: str) -> Path | None:
        """Path to a company's per-company data directory, or None
        when no project_root was supplied (e.g. test setups)."""
        if self._project_root is None:
            return None
        return self._project_root / "data" / "companies" / company_id

    def ensure_data_dir(self, company_id: str) -> Path | None:
        """Idempotently create the per-company data dir. Returns the
        path (or None when project_root unset). Safe to call repeatedly.
        """
        target = self.data_dir(company_id)
        if target is None:
            return None
        target.mkdir(parents=True, exist_ok=True)
        return target

    async def list(self) -> list[Company]:
        rows = await self._db.execute(
            "SELECT id, name, status, product_yaml, created_at, updated_at "
            "FROM companies ORDER BY created_at"
        )
        return [
            Company(
                id=r["id"],
                name=r["name"],
                status=r["status"],
                product_yaml=r["product_yaml"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    async def get(self, company_id: str) -> Company | None:
        rows = await self._db.execute(
            "SELECT id, name, status, product_yaml, created_at, updated_at "
            "FROM companies WHERE id = ?",
            (company_id,),
        )
        if not rows:
            return None
        r = rows[0]
        return Company(
            id=r["id"],
            name=r["name"],
            status=r["status"],
            product_yaml=r["product_yaml"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )

    async def create(
        self,
        slug: str,
        name: str,
        *,
        product_yaml: str | None = None,
    ) -> Company:
        """Create a new company row.

        Raises ``ValueError`` if the slug is empty or already exists.
        Slug is stored verbatim — the CLI does no normalization, so the
        operator picks their own convention.
        """
        slug = slug.strip()
        if not slug:
            raise ValueError("company slug cannot be empty")

        existing = await self.get(slug)
        if existing is not None:
            raise ValueError(f"company {slug!r} already exists")

        now_iso = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "INSERT INTO companies (id, name, status, product_yaml, created_at, updated_at) "
            "VALUES (?, ?, 'active', ?, ?, ?)",
            (slug, name, product_yaml, now_iso, now_iso),
        )
        created = await self.get(slug)
        assert created is not None, "company should exist immediately after insert"
        # ABE Phase 6: materialize the per-company data directory so
        # tools that opt into per-company file state have a stable
        # location waiting. Idempotent; safe if project_root is unset.
        self.ensure_data_dir(slug)
        return created

    async def set_status(self, company_id: str, status: str) -> bool:
        if status not in ("active", "paused", "archived"):
            raise ValueError(f"invalid status: {status!r}")
        now_iso = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE companies SET status = ?, updated_at = ? WHERE id = ?",
            (status, now_iso, company_id),
        )
        return (await self.get(company_id)) is not None
