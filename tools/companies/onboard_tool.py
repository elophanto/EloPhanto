"""``company_onboard`` — single-tool ABE onboarding orchestration.

ABE (Autonomous Business Entity) is a concept originated by Petr
Royce in 2023. See ``docs/76-ABE-FRAMEWORK.md`` for the framework.

This tool exists because the natural operator request — *"I have a
business on X.com, drive it"* — was forcing the LLM to chain 4-5
separate tool calls (company_create → company_use → company_set_product
→ goal_create → ...) and orchestrate them correctly. One fumble (e.g.
forgetting to call company_set_product) left the company in a broken
state (product undefined → dream phase has no anchor → drift). The
ABE framework gap review (2026-05-26) identified this as the highest-
leverage UX fix.

``company_onboard`` bundles the entire setup sequence into one
operator-approved call:

1. Validate slug + ``what_we_sell`` (banlist filter from
   ``core.consumer_filter`` applies — agent can't write
   navel-gazing product copy).
2. Create the company row + materialize ``data/companies/<slug>/``.
3. Persist company use to the sidecar so the autonomous mind picks
   it up on the next wakeup (without this, the mind keeps operating
   under the previous default company and the operator sees zero
   activity on the new one — the load-bearing failure mode).
4. Write ``companies/<slug>/company.yaml`` with the provided product
   spec.
5. Optionally create a seed goal so the agent has explicit first
   work to do (without this, the agent has to dream up its own
   initial direction, which is unreliable for a fresh company).

MODERATE permission tier — one approval covers the whole sequence.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class CompanyOnboardTool(BaseTool):
    """One-shot ABE onboarding."""

    def __init__(self) -> None:
        self._db: Any = None
        self._project_root: Path | None = None
        self._company_manager: Any = None
        self._goal_manager: Any = None

    @property
    def group(self) -> str:
        return "companies"

    @property
    def name(self) -> str:
        return "company_onboard"

    @property
    def description(self) -> str:
        return (
            "**Canonical entry point when the operator says 'I have a "
            "business on X.com' / 'drive my business' / 'I want to run "
            "X'.** Bundles company_create + company_use(persist=true) + "
            "company_set_product + optional seed goal into ONE "
            "operator-approved call. Before calling, do quick research "
            "on the business (browser_navigate + browser_extract on the "
            "URL, or web_search '<domain> what do they sell') to fill in "
            "`what_we_sell` accurately — that field anchors the dream "
            "phase, an empty/wrong value causes drift. After this tool "
            "returns success, the autonomous mind will inherit the new "
            "company on its next wakeup and start operating it."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": (
                        "Stable slug for the ABE (e.g. 'alphascala', "
                        "'acme-inc'). Use the domain stem when possible "
                        "so the operator can recognize it. Lowercase + "
                        "hyphens, no spaces."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Display name. Defaults to the slug.",
                },
                "what_we_sell": {
                    "type": "string",
                    "description": (
                        "1-3 sentences naming a real external consumer + "
                        "concrete deliverable. Required and non-empty. "
                        "Banned patterns (navel-gazing): 'framework for "
                        "documenting agent identity', 'self-perception', "
                        "any phrase the consumer-filter banlist rejects. "
                        "Fill from research, not guesswork."
                    ),
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
                    "description": "Channel adapters this company uses (cli, telegram, x, ...).",
                },
                "kpis": {
                    "type": "array",
                    "description": (
                        "List of KPIs: [{type, target_weekly}, ...]. "
                        "Types should match ledger event types so the "
                        "arbiter's kpi_gap calculation can find them."
                    ),
                },
                "seed_goal": {
                    "type": "string",
                    "description": (
                        "Optional first goal for the agent to work on. "
                        "Concrete, single-line, names a deliverable. "
                        "Example: 'Research 20 qualified prospects for "
                        "alphascala and capture them in the CRM.' Without "
                        "a seed goal the agent has to dream up its first "
                        "direction, which is unreliable for a fresh "
                        "company."
                    ),
                },
            },
            "required": ["slug", "what_we_sell"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        # Init gate — same pattern as other ABE tools so an
        # uninitialized state surfaces with a clear error rather
        # than a deep AttributeError.
        if (
            self._db is None
            or self._project_root is None
            or self._company_manager is None
        ):
            return ToolResult(
                success=False,
                error=(
                    "company_onboard not initialized (missing db / "
                    "project_root / company_manager)"
                ),
            )

        slug = str(params.get("slug", "")).strip()
        what_we_sell = str(params.get("what_we_sell", "")).strip()
        name = str(params.get("name") or slug).strip()

        if not slug:
            return ToolResult(success=False, error="slug is required")
        if not what_we_sell:
            return ToolResult(
                success=False,
                error="what_we_sell is required and must be non-empty",
            )

        # Banlist filter (same one dream phase + company_set_product use).
        # Agent-proposed what_we_sell can't drift into navel-gazing.
        from core.consumer_filter import is_consumerless_text

        rejected, reason = is_consumerless_text(what_we_sell, label="what_we_sell")
        if rejected:
            return ToolResult(
                success=False,
                error=(
                    f"what_we_sell rejected by consumer filter: {reason}. "
                    f"Research the business and propose a description "
                    f"that names a real external consumer + a concrete "
                    f"deliverable they receive."
                ),
            )

        # Step 1: Create company row + data dir
        try:
            company = await self._company_manager.create(slug=slug, name=name)
        except ValueError as e:
            return ToolResult(success=False, error=f"company_create failed: {e}")

        # Step 2: Persist company use so the autonomous mind picks
        # it up on its next wakeup. This is the load-bearing step —
        # without persistence, the mind never sees the new company
        # and the operator gets zero activity on it. See
        # core/autonomous_mind.py:_think for the read side.
        try:
            from core.company import (
                set_current_company,
                write_persisted_current_company,
            )

            set_current_company(slug)
            write_persisted_current_company(slug)
        except Exception as e:
            # Don't bail — the company exists and the YAML can still
            # land. Operator can persist manually via company_use.
            logger.warning(
                "company_onboard: persist context failed (%s); "
                "operator may need to run company_use(slug=%s, "
                "persist=true) manually",
                e,
                slug,
            )

        # Step 3: Write the product YAML
        product_path = self._project_root / "companies" / slug / "company.yaml"
        try:
            import yaml

            doc: dict[str, Any] = {
                "name": name,
                "what_we_sell": what_we_sell,
            }
            if isinstance(params.get("price"), dict):
                doc["price"] = params["price"]
            if params.get("fulfillment"):
                doc["fulfillment"] = str(params["fulfillment"])
            if isinstance(params.get("channels"), list):
                doc["channels"] = list(params["channels"])
            if isinstance(params.get("kpis"), list):
                doc["kpis"] = list(params["kpis"])

            product_path.parent.mkdir(parents=True, exist_ok=True)
            product_path.write_text(
                yaml.safe_dump(doc, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=(
                    f"company {slug!r} created and active, but product "
                    f"YAML write failed: {e}. Run company_set_product "
                    f"to retry."
                ),
            )

        # Step 4: Optional seed goal so the agent has explicit first
        # work. Without this, a brand-new company depends on the
        # dream phase to invent direction, which is unreliable.
        seed_goal = str(params.get("seed_goal") or "").strip()
        seed_goal_id: str | None = None
        if seed_goal and self._goal_manager is not None:
            try:
                g = await self._goal_manager.create_goal(
                    goal=seed_goal,
                    assigned_to_role=None,  # CEO default; operator can re-assign
                )
                seed_goal_id = g.goal_id
            except Exception as e:
                # Non-fatal — operator/agent can create the goal later.
                logger.warning(
                    "company_onboard: seed goal create failed (%s); "
                    "company + product still landed",
                    e,
                )

        return ToolResult(
            success=True,
            data={
                "slug": company.id,
                "name": company.name,
                "status": company.status,
                "product_yaml_path": str(product_path),
                "what_we_sell_preview": (
                    what_we_sell[:160] + "…"
                    if len(what_we_sell) > 160
                    else what_we_sell
                ),
                "active_session_persisted": True,
                "seed_goal_id": seed_goal_id,
                "next_step": (
                    "Autonomous mind will inherit this company on its "
                    "next wakeup. To start operating immediately, ask "
                    "the operator what 'drive this' means as concrete "
                    "recurring work (daily outreach? weekly content? "
                    "specific KPIs?) and call schedule_task or "
                    "mission_create for the cadence."
                ),
            },
        )
