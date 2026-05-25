"""``company_set_product`` — agent-writable product YAML.

ABE (Autonomous Business Entity) is a concept originated by Petr
Royce in 2023.

Closes the read-only/write-only asymmetry of Phase 4: before this
tool, the agent could *read* `companies/<slug>/company.yaml` but
the operator had to *write* every line by hand. Now the agent can
propose a product (subject to MODERATE approval) and the file
lands at `companies/<slug>/company.yaml`.

**Safety**:
- ``what_we_sell`` is required and must not be empty (navel-gazing
  guard — Phase 4's loader returns ``None`` for empty values).
- ``what_we_sell`` text is run through ``core.consumer_filter`` so
  agent-proposed descriptions can't drift back into the same
  navel-gazing patterns the dream-lens rewrite filtered out
  ("framework for documenting agent identity boundaries", etc.).
- Refuses to write for unknown company slugs — operator controls
  company creation via `elophanto company create`. Avoids the
  agent silently materializing companies the operator never asked
  about.
- ``PermissionLevel.MODERATE`` — every write requires operator
  approval. Reversible (just overwrites a file) so DESTRUCTIVE
  is wrong tier; SAFE would be too loose.

See ``docs/76-ABE-FRAMEWORK.md`` §Phase 7.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class CompanySetProductTool(BaseTool):
    """Write or update a company's ``company.yaml``."""

    def __init__(self) -> None:
        self._db: Any = None
        self._project_root: Path | None = None

    @property
    def group(self) -> str:
        return "companies"

    @property
    def name(self) -> str:
        return "company_set_product"

    @property
    def description(self) -> str:
        return (
            "Write or update a company's product config "
            "(companies/<slug>/company.yaml). Required: slug (must already "
            "exist in the companies table) and what_we_sell (non-empty, "
            "passes the consumer filter). Optional: price, fulfillment, "
            "channels, wallet, kpis. Use to bootstrap or revise what a "
            "company sells — operator approves every write."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": (
                        "Company slug (must already exist in `companies` "
                        "table — create via `elophanto company create` first)."
                    ),
                },
                "what_we_sell": {
                    "type": "string",
                    "description": (
                        "What this company actually sells, 1-3 sentences. "
                        "MUST name a real external consumer + concrete "
                        "deliverable. Banned patterns: 'framework for "
                        "documenting agent identity', 'self-perception', "
                        "any phrase the consumer-filter banlist rejects."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Display name (defaults to the slug).",
                },
                "price": {
                    "type": "object",
                    "description": (
                        "Pricing model: e.g. "
                        "{amount: 100, currency: USD, model: hourly}."
                    ),
                },
                "fulfillment": {
                    "type": "string",
                    "description": "How delivery happens after a sale.",
                },
                "channels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Channel adapters this company uses.",
                },
                "wallet": {
                    "type": "object",
                    "description": (
                        "Wallet metadata: {chain, address}. Address may be "
                        "left empty if held in the vault."
                    ),
                },
                "kpis": {
                    "type": "array",
                    "description": (
                        "List of KPIs: [{type, target_weekly}, ...]. "
                        "Types should match ledger event types "
                        "(pipeline_advance, email_sent, usd, ...) so the "
                        "arbiter's kpi_gap calculation can find them."
                    ),
                },
            },
            "required": ["slug", "what_we_sell"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._db is None or self._project_root is None:
            return ToolResult(
                success=False,
                error="company_set_product not initialized (missing db / project_root)",
            )

        slug = str(params.get("slug", "")).strip()
        what_we_sell = str(params.get("what_we_sell", "")).strip()
        if not slug:
            return ToolResult(success=False, error="slug is required")
        if not what_we_sell:
            return ToolResult(
                success=False,
                error="what_we_sell is required and must be non-empty",
            )

        # Refuse to write for slugs the operator hasn't created. Phase 7
        # deliberately doesn't auto-create companies — operator
        # controls that surface via `elophanto company create`.
        rows = await self._db.execute("SELECT id FROM companies WHERE id = ?", (slug,))
        if not rows:
            return ToolResult(
                success=False,
                error=(
                    f"company {slug!r} does not exist — operator must "
                    f"create it first via `elophanto company create {slug}`"
                ),
            )

        # Apply the shared consumer filter to what_we_sell so the
        # agent can't drift back into the navel-gazing pattern the
        # dream-lens rewrite filtered out. Empty/whitespace also
        # caught here as a belt-and-suspenders against the required
        # check above.
        from core.consumer_filter import is_consumerless_text

        rejected, reason = is_consumerless_text(what_we_sell, label="what_we_sell")
        if rejected:
            return ToolResult(
                success=False,
                error=(
                    f"what_we_sell rejected by consumer filter: {reason}. "
                    f"Propose a description that names a real external "
                    f"consumer + a concrete deliverable they receive."
                ),
            )

        # Render the YAML by hand — `yaml.safe_dump` would round-trip
        # fine, but a hand-rendered file preserves operator comments
        # in cases where someone has already hand-edited the file
        # (the tool overwrites the file, but the rendered output
        # follows the same shape as the elophanto-self seed so the
        # operator can re-edit by hand cleanly).
        import yaml

        doc: dict[str, Any] = {
            "name": str(params.get("name") or slug),
            "what_we_sell": what_we_sell,
        }
        if isinstance(params.get("price"), dict):
            doc["price"] = params["price"]
        if params.get("fulfillment"):
            doc["fulfillment"] = str(params["fulfillment"])
        if isinstance(params.get("channels"), list):
            doc["channels"] = list(params["channels"])
        if isinstance(params.get("wallet"), dict):
            doc["wallet"] = params["wallet"]
        if isinstance(params.get("kpis"), list):
            doc["kpis"] = list(params["kpis"])

        target = self._project_root / "companies" / slug / "company.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        # default_flow_style=False = block style, sort_keys=False = preserve
        # the field order we built `doc` with.
        target.write_text(
            yaml.safe_dump(doc, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

        return ToolResult(
            success=True,
            data={
                "slug": slug,
                "path": str(target),
                "what_we_sell_preview": (
                    what_we_sell[:120] + "…"
                    if len(what_we_sell) > 120
                    else what_we_sell
                ),
                "fields_written": sorted(doc.keys()),
            },
        )
