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
            "Onboard a new ABE company. Bundles company_create + "
            "persist sidecar + company_set_product + optional seed goal "
            "into one call. Research the URL first (browser_navigate + "
            "browser_extract) so what_we_sell is grounded. See "
            "drive-business skill PATH A."
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
                "payment_rail": {
                    "type": "string",
                    "enum": ["fiat", "crypto"],
                    "description": (
                        "How this business gets paid — ONE rail per "
                        "business: 'fiat' (Stripe — cards/bank) or 'crypto' "
                        "(wallet). Fiat starts in TEST mode (no real money "
                        "or KYC until the operator finishes KYC and goes "
                        "live). Ask the operator which they want. Optional "
                        "— can be set later."
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

        # Step 1.5: payment rail (ABE finance rail). One rail per business,
        # chosen here. Non-fatal on a bad value — the company still onboards
        # and the operator can set it later via company_set_product/edit.
        payment_rail = str(params.get("payment_rail") or "").strip().lower() or None
        if payment_rail:
            try:
                await self._company_manager.set_payment_rail(slug, payment_rail)
            except ValueError as e:
                logger.warning(
                    "company_onboard: invalid payment_rail %r (%s); left unset",
                    payment_rail,
                    e,
                )
                payment_rail = None

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

        # Step 3.5 (ABE Phase 10): seed the voice exemplars directory
        # so the operator has an obvious place to drop reference
        # posts/emails. Without this, the workflow ("paste exemplars
        # then run voice_extract") is discoverable only via docs. Two
        # default channel subdirs (twitter, email) cover the common
        # cases; operator can add more. README in the root explains
        # the flow. All idempotent.
        try:
            exemplars_root = (
                self._project_root / "data" / "companies" / slug / "exemplars"
            )
            for channel in ("twitter", "email"):
                (exemplars_root / channel).mkdir(parents=True, exist_ok=True)
            readme = exemplars_root / "README.md"
            if not readme.is_file():
                readme.write_text(
                    f"# Voice exemplars for {name}\n\n"
                    "Drop reference posts / emails here (one per `.md` "
                    "file, raw body is fine) under the channel subdir "
                    f"that matches: `twitter/`, `email/`, or any new "
                    "channel you add (`linkedin/`, etc).\n\n"
                    "Two or more files per channel are enough. Then "
                    f"ask EloPhanto to run `voice_extract` for `{slug}` "
                    "— it will distill the recurring patterns and "
                    "propose a `voice.yaml` for review. Once you "
                    f"approve it (`elophanto voice approve {slug}`), "
                    "every draft for this company is lint-gated "
                    "against your voice — no more AI slop.\n",
                    encoding="utf-8",
                )
        except Exception as e:
            # Non-fatal — the operator can mkdir the path manually.
            logger.warning(
                "company_onboard: exemplars dir seed failed (%s); "
                "operator can mkdir data/companies/%s/exemplars/ "
                "manually",
                e,
                slug,
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
                "payment_rail": payment_rail,
                "fiat_setup": (
                    (
                        "Fiat rail selected. To accept payments: (1) enable "
                        "Stripe + paste a free sk_test_ key (wizard or "
                        "`elophanto vault set stripe_secret_key sk_test_...`) "
                        "— this works in TEST mode with no KYC; (2) when "
                        "ready for real money, finish KYC (existing entity or "
                        "Stripe Atlas) and call company_set_entity_state to "
                        "advance to 'verified', then flip payments.fiat.mode "
                        "to live. fiat_payment_link creates checkout links; "
                        "fiat_reconcile (auto-scheduled every 30m) records "
                        "payments."
                    )
                    if payment_rail == "fiat"
                    else None
                ),
                "next_step": (
                    "Phase 11 canonical post-onboard sequence: "
                    "1) `company_capabilities` to audit available "
                    "tools/credentials/skills; "
                    "2) ask the operator about target audience, "
                    "competitors, budget, risk tolerance, primary "
                    "goals, then call `company_set_strategy_inputs`; "
                    "3) `company_plan` to generate a strategy proposal; "
                    "4) `company_plan_apply` to materialize the "
                    "mission + goals + schedules + voice seed; "
                    "5) `company_plan_approve` after operator reviews "
                    "blockers + voice. The autonomous mind will then "
                    "pick up the tactics on its next wakeup."
                ),
            },
        )
