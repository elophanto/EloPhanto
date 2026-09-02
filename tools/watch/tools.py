"""watch_* — track a market: brands, weighted dimensions, evidence, scores.

ABE organ 2 (market model). These tools turn ad-hoc competitor research into a
standing, evidence-backed model that can be refreshed and diffed month over
month. Market-agnostic: the scoring frame is data (see ``core/watch_seeds.py``
for ready-made packs), not code.

Two behaviours are deliberately strict, because the analysis is only worth
anything if they hold:

* ``watch_score`` refuses to score a dimension with no evidence. The honest
  representation of "we don't know" is a NULL score plus its coverage gap —
  never a low score, which would report an opaque brand as a weak one.
* ``watch_evidence`` is append-only. Corrections supersede, never overwrite,
  so month-over-month change is real rather than an artefact of editing.

Design: tmp/competitive-intel-organ-spec.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.watch import VALID_CUSTOMER_STATES
from tools.base import BaseTool, PermissionLevel, ToolResult


def _slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in (name or "").lower()).strip("-")


def _company(params: dict[str, Any]) -> str:
    """Resolve the owning company — explicit arg wins, else the active one."""
    from core.company import current_company_id

    return str(params.get("company_id") or current_company_id() or "elophanto-self")


class _WatchToolBase(BaseTool):
    """Shared plumbing: injected manager + company resolution."""

    def __init__(self) -> None:
        self._watch_manager: Any = None

    @property
    def group(self) -> str:
        return "watch"

    def _guard(self) -> ToolResult | None:
        if self._watch_manager is None:
            return ToolResult(success=False, error=f"{self.name} not initialized (watch_manager)")
        return None


class WatchSubjectTool(_WatchToolBase):
    """Add / list the brands being tracked."""

    @property
    def name(self) -> str:
        return "watch_subject"

    @property
    def description(self) -> str:
        return (
            "Manage the brands tracked in a competitive analysis. "
            "action='add' registers a brand (name, group, url); action='list' "
            "returns all tracked brands; action='archive' stops tracking one. "
            "Use this before recording evidence about a competitor."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "archive"],
                    "description": "What to do. Default 'list'.",
                },
                "name": {"type": "string", "description": "Brand name."},
                "group_name": {
                    "type": "string",
                    "description": "Parent group / operator (e.g. 'VGW', 'B2S').",
                },
                "url": {"type": "string", "description": "Brand homepage URL."},
                "product_offering": {"type": "string"},
                "market_share_est": {"type": "string"},
                "is_self": {
                    "type": "boolean",
                    "description": "True for our own brands (excluded from competitor rollups).",
                },
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        action = str(params.get("action") or "list").lower()
        cid = _company(params)
        wm = self._watch_manager

        if action == "list":
            subs = await wm.list_subjects(cid)
            return ToolResult(
                success=True,
                data={
                    "count": len(subs),
                    "subjects": [
                        {
                            "subject_id": s.subject_id,
                            "name": s.name,
                            "group": s.group_name,
                            "url": s.url,
                            "is_self": s.is_self,
                        }
                        for s in subs
                    ],
                },
            )

        name = str(params.get("name") or "").strip()
        if not name:
            return ToolResult(success=False, error="name is required")

        if action == "add":
            sub = await wm.add_subject(
                name=name,
                company_id=cid,
                group_name=str(params.get("group_name") or ""),
                url=str(params.get("url") or ""),
                product_offering=str(params.get("product_offering") or ""),
                market_share_est=str(params.get("market_share_est") or ""),
                is_self=bool(params.get("is_self")),
            )
            return ToolResult(success=True, data={"subject_id": sub.subject_id, "name": sub.name})

        if action == "archive":
            sub = await wm.get_subject_by_name(name, cid)
            if sub is None:
                return ToolResult(success=False, error=f"no such subject: {name!r}")
            await wm.archive_subject(sub.subject_id)
            return ToolResult(success=True, data={"archived": name})

        return ToolResult(success=False, error=f"unknown action: {action!r}")


class WatchDimensionTool(_WatchToolBase):
    """Define the weighted scoring frame, or load a ready-made pack."""

    @property
    def name(self) -> str:
        return "watch_dimension"

    @property
    def description(self) -> str:
        return (
            "Manage the scoring dimensions of a competitive analysis — the "
            "weighted parameters brands are scored on. action='seed' loads a "
            "ready-made pack (e.g. 'social_casino_t1' = the 12-dimension "
            "sweepstakes-casino frame plus its brands); action='list' shows the "
            "current frame; action='upsert' adds or edits one dimension with its "
            "weight, sub-criteria and refresh cadence."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "upsert", "seed", "packs"],
                    "description": "What to do. Default 'list'.",
                },
                "pack": {
                    "type": "string",
                    "description": "Seed pack name for action='seed'.",
                },
                "name": {"type": "string", "description": "Dimension name."},
                "description_text": {"type": "string"},
                "weight_pct": {
                    "type": "number",
                    "description": "Weight of this dimension; all should sum to 100.",
                },
                "refresh_cadence": {
                    "type": "string",
                    "enum": ["weekly", "monthly", "quarterly"],
                },
                "subcriteria": {
                    "type": "array",
                    "description": "[{name, weight_pct}] summing to 100.",
                    "items": {"type": "object"},
                },
                "view_weights": {
                    "type": "object",
                    "description": "Alternative-view weights, e.g. {'customer_proposition': 18}.",
                },
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        action = str(params.get("action") or "list").lower()
        cid = _company(params)
        wm = self._watch_manager

        if action == "packs":
            from core.watch_seeds import list_packs

            return ToolResult(success=True, data={"packs": list_packs()})

        if action == "list":
            dims = await wm.list_dimensions(cid)
            total = round(sum(d.weight_pct for d in dims), 2)
            return ToolResult(
                success=True,
                data={
                    "count": len(dims),
                    "weight_total_pct": total,
                    "weights_valid": abs(total - 100.0) < 0.01 if dims else False,
                    "dimensions": [
                        {
                            "name": d.name,
                            "weight_pct": d.weight_pct,
                            "cadence": d.refresh_cadence,
                            "subcriteria": [s.get("name") for s in d.subcriteria],
                        }
                        for d in dims
                    ],
                },
            )

        if action == "seed":
            from core.watch_seeds import get_pack

            pack_name = str(params.get("pack") or "").strip()
            pack = get_pack(pack_name)
            if pack is None:
                from core.watch_seeds import list_packs

                return ToolResult(
                    success=False,
                    error=(
                        f"unknown pack {pack_name!r}. Available: "
                        f"{[p['name'] for p in list_packs()]}"
                    ),
                )
            dims_added = 0
            for i, d in enumerate(pack["dimensions"]):
                await wm.upsert_dimension(
                    name=d["name"],
                    company_id=cid,
                    description=d.get("description", ""),
                    weight_pct=d.get("weight_pct", 0),
                    subcriteria=d.get("subcriteria", []),
                    refresh_cadence=d.get("refresh_cadence", "monthly"),
                    view_weights=d.get("view_weights", {}),
                    sort_order=i,
                )
                dims_added += 1
            subs_added = 0
            for s in pack.get("subjects", []):
                await wm.add_subject(
                    name=s["name"],
                    company_id=cid,
                    group_name=s.get("group_name", ""),
                    url=s.get("url", ""),
                    is_self=bool(s.get("is_self")),
                )
                subs_added += 1
            return ToolResult(
                success=True,
                data={
                    "pack": pack_name,
                    "dimensions_seeded": dims_added,
                    "subjects_seeded": subs_added,
                    "next": (
                        "Collect evidence with watch_evidence, then score with "
                        "watch_score. Scores without evidence are refused by design."
                    ),
                },
            )

        if action == "upsert":
            name = str(params.get("name") or "").strip()
            if not name:
                return ToolResult(success=False, error="name is required")
            try:
                dim = await wm.upsert_dimension(
                    name=name,
                    company_id=cid,
                    description=str(params.get("description_text") or ""),
                    weight_pct=float(params.get("weight_pct") or 0),
                    subcriteria=params.get("subcriteria") or [],
                    refresh_cadence=str(params.get("refresh_cadence") or "monthly"),
                    view_weights=params.get("view_weights") or {},
                )
            except ValueError as e:
                return ToolResult(success=False, error=str(e))
            return ToolResult(
                success=True,
                data={"dimension_id": dim.dimension_id, "name": dim.name},
            )

        return ToolResult(success=False, error=f"unknown action: {action!r}")


class WatchEvidenceTool(_WatchToolBase):
    """Record and query the evidence register (append-only)."""

    @property
    def name(self) -> str:
        return "watch_evidence"

    @property
    def description(self) -> str:
        return (
            "The evidence register for a competitive analysis. action='add' "
            "records ONE observed fact about a brand with full provenance "
            "(source URL, geo/state, customer state, date, confidence); "
            "action='list' queries it. Evidence is append-only — pass "
            "'supersedes' with an evidence_id to correct or refresh a prior "
            "observation instead of overwriting it. Authenticated observations "
            "(verified/purchaser/redeemer/vip) are operator-collected: pass "
            "collector='human'."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "list"]},
                "subject": {"type": "string", "description": "Brand name."},
                "dimension": {"type": "string", "description": "Dimension name."},
                "subcriterion": {
                    "type": "string",
                    "description": "Which sub-criterion this fact covers (drives coverage %).",
                },
                "claim": {
                    "type": "string",
                    "description": "The observed fact, stated plainly.",
                },
                "value_text": {"type": "string"},
                "value_num": {"type": "number"},
                "source_url": {"type": "string"},
                "source_type": {
                    "type": "string",
                    "enum": [
                        "site",
                        "terms",
                        "ad_library",
                        "trust_site",
                        "filing",
                        "shop",
                        "press",
                        "other",
                    ],
                },
                "geo_state": {
                    "type": "string",
                    "description": "US state code the observation was made from, or 'n/a'.",
                },
                "customer_state": {
                    "type": "string",
                    "enum": [
                        "logged_out",
                        "registered",
                        "verified",
                        "purchaser",
                        "redeemer",
                        "vip",
                    ],
                },
                "journey_stage": {"type": "string"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "excerpt": {
                    "type": "string",
                    "description": "Verbatim supporting quote.",
                },
                "screenshot_path": {"type": "string"},
                "collector": {"type": "string", "enum": ["agent", "human"]},
                "supersedes": {
                    "type": "string",
                    "description": "evidence_id this observation replaces.",
                },
                "include_superseded": {"type": "boolean"},
                "limit": {"type": "integer"},
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        action = str(params.get("action") or "list").lower()
        cid = _company(params)
        wm = self._watch_manager

        subject_id = None
        if params.get("subject"):
            sub = await wm.get_subject_by_name(str(params["subject"]), cid)
            if sub is None:
                return ToolResult(
                    success=False,
                    error=(
                        f"no tracked brand named {params['subject']!r} — add it "
                        "with watch_subject first"
                    ),
                )
            subject_id = sub.subject_id

        dimension_id = None
        if params.get("dimension"):
            dim = await wm.get_dimension_by_name(str(params["dimension"]), cid)
            if dim is None:
                return ToolResult(
                    success=False,
                    error=(
                        f"no dimension named {params['dimension']!r} — see "
                        "watch_dimension action='list'"
                    ),
                )
            dimension_id = dim.dimension_id

        if action == "list":
            rows = await wm.list_evidence(
                cid,
                subject_id=subject_id,
                dimension_id=dimension_id,
                include_superseded=bool(params.get("include_superseded")),
                limit=int(params.get("limit") or 50),
            )
            return ToolResult(
                success=True,
                data={
                    "count": len(rows),
                    "evidence": [
                        {
                            "evidence_id": e.evidence_id,
                            "claim": e.claim,
                            "subcriterion": e.subcriterion,
                            "source_url": e.source_url,
                            "geo_state": e.geo_state,
                            "customer_state": e.customer_state,
                            "observed_at": e.observed_at,
                            "confidence": e.confidence,
                            "collector": e.collector,
                        }
                        for e in rows
                    ],
                },
            )

        if action == "add":
            if not subject_id or not dimension_id:
                return ToolResult(success=False, error="subject and dimension are both required")
            claim = str(params.get("claim") or "").strip()
            if not claim:
                return ToolResult(success=False, error="claim is required")
            try:
                ev = await wm.add_evidence(
                    company_id=cid,
                    subject_id=subject_id,
                    dimension_id=dimension_id,
                    claim=claim,
                    subcriterion=str(params.get("subcriterion") or ""),
                    value_text=str(params.get("value_text") or ""),
                    value_num=params.get("value_num"),
                    source_url=str(params.get("source_url") or ""),
                    source_type=str(params.get("source_type") or "site"),
                    geo_state=str(params.get("geo_state") or "n/a"),
                    customer_state=str(params.get("customer_state") or "logged_out"),
                    journey_stage=str(params.get("journey_stage") or ""),
                    confidence=str(params.get("confidence") or "medium"),
                    excerpt=str(params.get("excerpt") or ""),
                    screenshot_path=str(params.get("screenshot_path") or ""),
                    collector=str(params.get("collector") or "agent"),
                    supersedes=params.get("supersedes"),
                )
            except ValueError as e:
                return ToolResult(success=False, error=str(e))
            return ToolResult(
                success=True,
                data={"evidence_id": ev.evidence_id, "observed_at": ev.observed_at},
            )

        return ToolResult(success=False, error=f"unknown action: {action!r}")


class WatchScoreTool(_WatchToolBase):
    """Score a brand on a dimension — strictly from recorded evidence."""

    @property
    def name(self) -> str:
        return "watch_score"

    @property
    def description(self) -> str:
        return (
            "Score a tracked brand on one dimension, 1-5 (1 = materially behind "
            "market, 3 = parity, 5 = market-leading). The score MUST be justified "
            "by evidence already recorded via watch_evidence — scoring a dimension "
            "with no evidence is refused. If the data genuinely isn't available, "
            "pass score=null to record the gap: coverage is reported separately so "
            "a brand is never marked down merely for being opaque."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["set", "list"]},
                "subject": {"type": "string", "description": "Brand name."},
                "dimension": {"type": "string", "description": "Dimension name."},
                "score": {
                    "type": "number",
                    "description": "1-5, or null to record an evidence gap.",
                },
                "rationale": {
                    "type": "string",
                    "description": "Why this score, referencing the evidence.",
                },
                "subcriteria_scores": {"type": "object"},
                "scored_by": {"type": "string"},
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        action = str(params.get("action") or "set").lower()
        cid = _company(params)
        wm = self._watch_manager

        if action == "list":
            scores = await wm.list_scores(cid)
            return ToolResult(
                success=True,
                data={
                    "count": len(scores),
                    "scores": [
                        {
                            "subject_id": s.subject_id,
                            "dimension_id": s.dimension_id,
                            "score": s.score,
                            "coverage_pct": s.coverage_pct,
                            "confidence": s.confidence,
                        }
                        for s in scores
                    ],
                },
            )

        subject_name = str(params.get("subject") or "").strip()
        dim_name = str(params.get("dimension") or "").strip()
        if not subject_name or not dim_name:
            return ToolResult(success=False, error="subject and dimension are both required")
        sub = await wm.get_subject_by_name(subject_name, cid)
        if sub is None:
            return ToolResult(success=False, error=f"no such brand: {subject_name!r}")
        dim = await wm.get_dimension_by_name(dim_name, cid)
        if dim is None:
            return ToolResult(success=False, error=f"no such dimension: {dim_name!r}")

        raw = params.get("score")
        score = None if raw is None else float(raw)
        try:
            result = await wm.set_score(
                company_id=cid,
                subject_id=sub.subject_id,
                dimension_id=dim.dimension_id,
                score=score,
                rationale=str(params.get("rationale") or ""),
                subcriteria_scores=params.get("subcriteria_scores") or {},
                scored_by=str(params.get("scored_by") or "agent"),
            )
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        return ToolResult(
            success=True,
            data={
                "subject": sub.name,
                "dimension": dim.name,
                "score": result.score,
                "coverage_pct": result.coverage_pct,
                "confidence": result.confidence,
                "evidence_count": len(result.evidence_ids),
            },
        )


class WatchScorecardTool(_WatchToolBase):
    """The weighted executive scorecard, plus both alternative views."""

    @property
    def name(self) -> str:
        return "watch_scorecard"

    @property
    def description(self) -> str:
        return (
            "Render the executive scorecard: every tracked brand scored across "
            "the weighted dimensions, ranked, with the alternative views "
            "(customer proposition / transition priority) and each brand's "
            "evidence coverage and confidence shown separately from its "
            "competitive score. format='xlsx' writes the client-facing workbook "
            "(scorecard + weights + full evidence register + gaps)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json", "xlsx"],
                    "description": "Output format. Default 'markdown'.",
                },
                "path": {
                    "type": "string",
                    "description": "Output file for format='xlsx'.",
                },
                "title": {"type": "string", "description": "Workbook title."},
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        cid = _company(params)
        wm = self._watch_manager
        card = await wm.scorecard(cid)
        fmt = str(params.get("format") or "markdown").lower()

        if fmt == "json":
            return ToolResult(success=True, data=card)

        if fmt == "xlsx":
            path = str(params.get("path") or "").strip()
            if not path:
                return ToolResult(success=False, error="path is required for format='xlsx'")
            try:
                from core.watch_xlsx import render_scorecard_xlsx
            except ImportError as e:  # openpyxl missing
                return ToolResult(success=False, error=f"xlsx export unavailable: {e}")
            voice_rows: list[dict[str, Any]] = []
            if str(params.get("voice") or "auto").lower() != "false":
                try:
                    voice_rows = _voice_rows_for_export(
                        await wm.list_voice(cid, limit=5000),
                        await wm.list_subjects(cid),
                        await wm.list_dimensions(cid),
                    )
                except Exception:
                    voice_rows = []
            comms_rows: list[dict[str, Any]] = []
            if str(params.get("voice") or "auto").lower() != "false":
                try:
                    comms_rows = _comms_rows_for_export(
                        await wm.list_comms(cid, limit=5000), await wm.list_subjects(cid)
                    )
                except Exception:
                    comms_rows = []
            catalog_rows: list[dict[str, Any]] = []
            if str(params.get("voice") or "auto").lower() != "false":
                try:
                    catalog_rows = _catalog_rows_for_export(
                        await wm.list_catalog(cid), await wm.list_subjects(cid)
                    )
                except Exception:
                    catalog_rows = []
            written = render_scorecard_xlsx(
                card,
                dimensions=await wm.list_dimensions(cid),
                evidence=await wm.evidence_with_names(cid),
                staleness=await wm.staleness(cid),
                path=path,
                title=str(params.get("title") or "Competitive Scorecard"),
                voice_rows=voice_rows or None,
                comms_rows=comms_rows or None,
                catalog_rows=catalog_rows or None,
                provider_universe=_provider_universe(params),
            )
            return ToolResult(
                success=True,
                data={
                    "path": written,
                    "sheets": ["Scorecard", "Weights", "Evidence", "Gaps"],
                    "rows": len(card["rows"]),
                },
            )

        lines = [
            "| # | Brand | Group | Score | Cust. prop | Transition | Coverage | Conf |",
            "|---|-------|-------|-------|-----------|------------|----------|------|",
        ]
        for r in card["rows"]:
            o = r["overall"]
            score = "—" if o["normalized_pct"] is None else f"{o['normalized_pct']:.1f}"
            # A provisional score is marked at the number itself. A footnote
            # is not enough — the figure gets quoted on its own.
            if r.get("provisional") and o["normalized_pct"] is not None:
                score += "†"
            cp = r["views"].get("customer_proposition", {}).get("normalized_pct")
            tp = r["views"].get("transition_priority", {}).get("normalized_pct")
            lines.append(
                f"| {r['rank'] or '—'} | {r['name']}{' *(us)*' if r['is_self'] else ''} "
                f"| {r['group']} | {score} | {'—' if cp is None else f'{cp:.1f}'} "
                f"| {'—' if tp is None else f'{tp:.1f}'} "
                f"| {o['coverage_pct']:.0f}% | {o['confidence']} |"
            )
        provisional = [
            r
            for r in card["rows"]
            if r.get("provisional") and r["overall"]["normalized_pct"] is not None
        ]
        if provisional:
            lines += ["", "**† Provisional — not ranked:**"]
            lines += [
                f"- {r['name']}: {r.get('provisional_reason', 'insufficient evidence')}"
                for r in provisional
            ]
        note = (
            "\nScores are normalised to the weight actually scored; '—' means no "
            "evidence yet, never a weak result. Coverage shows the evidence gap."
        )
        if not card["weights_valid"]:
            note += f"\n⚠️  Dimension weights sum to {card['weight_total_pct']}%, not 100%."
        return ToolResult(
            success=True,
            data={"markdown": "\n".join(lines) + note, "rows": len(card["rows"])},
        )


class WatchSnapshotTool(_WatchToolBase):
    """Freeze the scorecard so later months have something to compare against."""

    @property
    def name(self) -> str:
        return "watch_snapshot"

    @property
    def description(self) -> str:
        return (
            "Freeze the current scorecard as a snapshot. Snapshots are what "
            "watch_diff and the monthly board report compare against, so take "
            "one at the end of every reporting cycle. action='list' shows "
            "existing snapshots."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["take", "list"]},
                "label": {
                    "type": "string",
                    "description": "Human label, e.g. 'March board report'.",
                },
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        cid = _company(params)
        wm = self._watch_manager
        action = str(params.get("action") or "take").lower()

        if action == "list":
            snaps = await wm.list_snapshots(cid)
            return ToolResult(success=True, data={"count": len(snaps), "snapshots": snaps})

        snap_id = await wm.take_snapshot(cid, label=str(params.get("label") or ""))
        return ToolResult(success=True, data={"snapshot_id": snap_id})


class WatchDiffTool(_WatchToolBase):
    """What materially changed since a snapshot."""

    @property
    def name(self) -> str:
        return "watch_diff"

    @property
    def description(self) -> str:
        return (
            "Compare the live scorecard against a snapshot and return only "
            "MATERIAL changes: score moves of at least a full point, rank "
            "changes, dimensions newly scored or withdrawn, big coverage "
            "shifts, and brands entering or leaving. Use this to answer 'what "
            "actually changed this month?' without re-reading everything."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "snapshot_id": {
                    "type": "string",
                    "description": "Snapshot to compare against. Default: the most recent.",
                },
                "min_score_delta": {
                    "type": "number",
                    "description": "Minimum score move to count as material. Default 1.0.",
                },
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        cid = _company(params)
        diff = await self._watch_manager.diff_since_snapshot(
            cid,
            snapshot_id=params.get("snapshot_id"),
            min_score_delta=float(params.get("min_score_delta") or 1.0),
        )
        if diff is None:
            return ToolResult(
                success=False,
                error=(
                    "no snapshot to compare against — take one with "
                    "watch_snapshot first (a diff needs a prior state)"
                ),
            )
        return ToolResult(success=True, data=diff)


_BOARD_SYSTEM = """You are preparing a monthly competitor board report.

You are given FACTS: material changes detected between two scorecards, plus the
evidence recorded this period. Convert them into board-ready judgement.

For each material change output:
- implication: what this means for US specifically, in one sentence
- recommendation: the concrete action to take
- classification: exactly one of
    no_regret            — worth doing regardless of how strategy or rankings
                           change next month; low cost, reversible, independent
                           of major platform work
    transition_requirement — must be built as part of the platform transition
    post_transition      — optimisation to do after the transition completes
    monitor              — no action yet; watch it
- decision_required: what the board must decide, or "none"

Rules:
- Use ONLY the facts given. Never invent a competitor move, number or source.
- If a change is ambiguous, say so and classify it 'monitor'.
- Be concise and concrete. No filler, no restating the change.
- The no-regret test: "would we still be pleased we did this if the transition
  plan, competitor rankings or strategic priorities changed next month?"

Return STRICT JSON: {"items":[{"subject":str,"change":str,"implication":str,
"recommendation":str,"classification":str,"decision_required":str}]}"""


_DECK_NARRATIVE_SYSTEM = """You write the words for an executive competitor
board deck. The room is a leadership team deciding how to respond in their
market; they care about competitors and their moves, not about how the
analysis was produced. You are given FACTS only: current standings, our
position, observed facts per key brand, the material changes this period,
the judged implications, and the evidence gaps.

Return STRICT JSON:
{"headline": str,
 "bullets": [str, ...],
 "exec": {"findings": [str, ...], "threats": [str, ...], "watch": [str, ...],
          "by_dimension": [{"dimension": str, "observations": [str, ...]}],
          "recommendation": str, "actions": [str, ...]},
 "titles": {"standings": str, "versus": str, "dimensions": str, "offers": str,
            "changes": str, "coverage": str, "voice": str},
 "commentary": {"standings": str, "versus": str, "dimensions": str, "offers": str,
                "changes": str, "coverage": str, "glance": str, "voice": str},
 "slides": {"standings": {"observations": [str, ...], "implications": [str, ...]},
            "versus": {...}, "dimensions": {...}, "offers": {...},
            "exhibits": {...}, "coverage": {...}, "voice": {...} (only when voice_of_customer given)},
 "profiles": [{"brand": str, "title": str,
               "observations": [str, ...], "implications": [str, ...]}],
 "next_steps": [str, ...]}

- headline: one sentence, at most 14 words – the single thing the room must
  take away. Lead with the so-what for US, not a description of the market.
- bullets: 3 to 5, each at most 20 words, priority order.
- exec: the executive summary slide, read first and often alone –
  by_dimension: one entry per dimension in dimensions_by_weight, SAME
    order, SAME names; 2 observations each (max 16 words): who leads it and
    with what, and where WE stand on it. Name brands; cite the fact.
  recommendation: 1-2 sentences (max 40 words) – what we should do, stated
    as a decision the room can take or refuse.
  actions: 2-3 concrete next actions (max 14 words each).
  findings / threats / watch: as before – findings: 3-4 market findings;
    threats: 2-3 competitive threats to US, sharpest first; watch: 2-3
    things to watch next period. Each entry at most 18 words.
- slides: the reading panel every analytical slide carries – for each of
  standings, versus, dimensions, offers, exhibits, coverage:
  observations: 2-4 lines on what THAT slide shows (max 20 words each);
  implications: 1-3 lines on what it means for US (max 18 words each).
  "offers" reads offers_observed – who leads on welcome generosity, what
  the ongoing propositions have in common, where ours sits. "exhibits" is
  what the storefronts visibly emphasise (offer-led vs game-led vs
  trust-led). Never repeat a chart's numbers back; say what they mean.
- voice_of_customer, when present, is what PLAYERS SAY — sentiment, not
  fact. Write titles.voice (an action title for the 'What players say'
  slide) and slides.voice {observations, implications}: which brand draws
  the most negative sentiment and on what theme, where we sit, what a
  rising complaint theme means for us. Never state a voice theme as a
  product fact ("X's redemptions are slow"); say what players say ("players
  complain about X's redemption speed, 62% of 40 mentions negative"). Never
  let it change a score claim. Shares with n; skip brands marked too_few.
- player_comms, when present, is what brands SEND players (marketing
  e-mail we receive first-hand): write titles.comms and slides.comms
  {observations, implications} — who sends most, what mix, what offers,
  where we differ. First-party fact, dated; quote offers as given.
- market_events, when present, are the most material facts in the room: a
  competitor closing, exiting a state, being acquired, rebranding, launching.
  Reflect them in the headline or recommendation, in slides.standings /
  commentary.changes, and in exec.actions where a decision follows (a rival
  closing means its players are up for grabs on a date). Never bury one.
- titles: an ACTION TITLE per slide – a sentence someone could disagree with
  ("High 5 leads a thin field"), never a label ("Standings overview").
  At most 10 words each.
- commentary: one line per slide (max 22 words) telling the room what to take
  from that slide. "glance" covers the headline-numbers slide; "dimensions"
  covers the who-leads-each-dimension breakout; "offers" the offers table.
- profiles: one per brand listed in brand_facts EXCEPT ours, in the given
  order. For each brand:
  title – an action title about THAT brand's market position, max 10 words;
  observations – 2-4 lines on what the brand actually does in the market
  (offers, promotions, payments, product, terms), drawn from its observed
  facts, each max 20 words;
  implications – 1-2 lines on what that means for US, each max 18 words.
- next_steps: 2 to 4 concrete actions, each at most 16 words.

Rules:
- Use ONLY the facts given. Never invent a number, a move, a brand, a source.
- Talk about the MARKET and the BRANDS, never about the analysis. Words like
  evidence, coverage, dimension, scored, provisional or snapshot belong only
  in titles.coverage and commentary.coverage; everywhere else say what the
  brand does, not how well we measured it.
- If our brand is provisional or unscored, say so plainly; do not rank it.
- If there is no material change, say so; do not manufacture urgency.
- NEVER mention internal bookkeeping: no hashes, SHA, file names, file paths,
  manifests, ledgers, registers, corpora, checkpoints, run IDs, snapshots or
  tool names. The room hears about the MARKET, not about the machinery.
- Punctuation: en dashes (–), never em dashes (—).
- No filler, no preamble, no restating the method."""


def _collect_exhibits(
    evidence: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    config: Any = None,
) -> dict[str, list[dict[str, str]]]:
    """brand -> up to 3 newest storefront exhibits ``{path, url, observed_at}``.

    Register-carried paths come first — the shot stands beside the claims
    from that page. Brands whose shots never landed on a row (an unreadable
    site rescued by third-party sources) fall back to the workspace exhibit
    directory, so a walled brand still shows its storefront."""
    from pathlib import Path

    from core.watch_observe import exhibit_kind

    _order = {"home": 0, "promo": 1, "other": 2}
    out: dict[str, list[dict[str, str]]] = {}
    seen: set[str] = set()
    for e in evidence:
        pth = str(e.get("screenshot_path") or "")
        if not pth or pth in seen or not Path(pth).exists():
            continue
        url = str(e.get("source_url") or "")
        kind = exhibit_kind(url) if url else ("home" if pth.endswith("-home.jpg") else "other")
        if kind == "legal":
            continue  # a privacy policy is evidence, never an exhibit
        seen.add(pth)
        out.setdefault(str(e.get("subject") or ""), []).append(
            {
                "path": pth,
                "url": url,
                "observed_at": str(e.get("observed_at") or ""),
                "kind": kind,
            }
        )
    for name in out:
        # newest-first input; stable sort keeps newest within a kind
        out[name].sort(key=lambda s: _order.get(s.get("kind", "other"), 2))
    ws = str(getattr(config, "workspace", "") or "").strip()
    if ws:
        root = Path(ws).expanduser()
        if not root.is_absolute():
            root = Path(getattr(config, "project_root", Path.cwd())) / root
        base = root / "watch-screenshots"
        for r in rows:
            name = str(r.get("name") or "")
            if not name or out.get(name):
                continue
            slug = "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-") or "brand"
            d = base / slug
            if not d.is_dir():
                continue
            files = sorted(d.glob("*.jpg"), key=lambda f: f.name, reverse=True)
            picked: list[dict[str, str]] = []
            for f in files:
                stem = f.name.split("-", 1)[-1].rsplit(".", 1)[0]  # after YYYYMMDD-
                kind = "home" if stem == "home" else exhibit_kind("/" + stem.replace("-", "/"))
                if kind == "legal":
                    continue
                picked.append({"path": str(f), "url": "", "observed_at": "", "kind": kind})
            picked.sort(key=lambda s: _order.get(s.get("kind", "other"), 2))
            if picked:
                out[name] = picked[:3]
    return {k: v[:3] for k, v in out.items() if v}


def _brand_facts(card: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Observed facts per key brand, for the narrative model: the ranked
    leader and runners-up plus our brand, newest first, at most one claim
    per dimension per brand so eight lines cover the whole product."""
    rows = card.get("rows", [])
    ranked = [r for r in rows if r.get("rank") is not None]
    if not ranked:
        # Ranks withheld (field not yet comparable) — the deep dives still
        # profile the strongest peers by score; scores are real, ranks are not.
        ranked = sorted(
            [r for r in rows if r["overall"]["normalized_pct"] is not None],
            key=lambda r: -float(r["overall"]["normalized_pct"]),
        )
    picks: list[str] = []
    for r in ranked:
        if not r.get("is_self"):
            picks.append(r["name"])
        if len(picks) >= 8:
            break
    us = next((r["name"] for r in rows if r.get("is_self")), None)
    if us:
        picks.append(us)
    facts: dict[str, list[str]] = {}
    for name in picks:
        seen_dims: set[str] = set()
        lines: list[str] = []
        for e in evidence:  # evidence_with_names is newest-first
            if str(e.get("subject") or "") != name:
                continue
            dim = str(e.get("dimension") or "")
            if dim in seen_dims:
                continue
            claim = str(e.get("claim") or "").strip()
            if not claim:
                continue
            seen_dims.add(dim)
            lines.append(f"[{dim}] {claim[:160]}")
            if len(lines) >= 8:
                break
        if lines:
            facts[name] = lines
    return facts


# Offer facts live in core/watch_offers.py (shared with the weekly brief).
from core.watch_offers import offer_facts as _offer_facts  # noqa: E402


async def _narrate_for_deck(
    router: Any,
    *,
    card: dict[str, Any],
    diff: dict[str, Any] | None,
    judged: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    evidence: list[dict[str, Any]] | None = None,
    offers: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    voice: dict[str, Any] | None = None,
    comms: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The deck's words. Model-written from facts when a router exists;
    otherwise the computed factual fallback — and the deck labels which."""
    from core.watch_deck import _slides_facts, factual_narrative

    fallback = factual_narrative(card, diff, judged, gaps, voice=voice, comms=comms)
    if offers:
        keep = {k: (fallback.get("slides") or {}).get(k) for k in ("voice", "comms")}
        fallback["slides"] = _slides_facts(card, offers)
        for k, v in keep.items():
            if v:
                fallback["slides"][k] = v
    if router is None:
        return fallback
    import json as _json

    rows = card.get("rows", [])
    facts = {
        "standings": [
            {
                "rank": r.get("rank"),
                "brand": r["name"],
                "is_us": bool(r.get("is_self")),
                "overall_normalized_pct": r["overall"]["normalized_pct"],
                "provisional": bool(r.get("provisional")),
                "coverage_pct": r["overall"]["coverage_pct"],
                "unscored_dimensions": r["overall"].get("unscored_dimensions", [])[:6],
            }
            for r in rows[:14]
        ],
        "material_changes": (
            None
            if diff is None
            else {
                "count": diff.get("material_count", 0),
                "changed": [
                    {
                        "subject": c["subject"],
                        "items": [i["detail"] for i in c["items"]],
                    }
                    for c in diff.get("changed", [])
                ],
                "added_subjects": diff.get("added_subjects", []),
                "removed_subjects": diff.get("removed_subjects", []),
            }
        ),
        "implications": judged,
        "brand_facts": _brand_facts(card, evidence or []),
        "dimensions_by_weight": [
            {
                "dimension": d["name"],
                "weight_pct": d.get("weight_pct"),
                "top_score": max(
                    [
                        float(r["dimensions"][d["name"]]["score"])
                        for r in rows
                        if r.get("dimensions", {}).get(d["name"], {}).get("score") is not None
                    ]
                    or [0]
                ),
                "leaders": [
                    r["name"]
                    for r in rows
                    if r.get("dimensions", {}).get(d["name"], {}).get("score") is not None
                    and float(r["dimensions"][d["name"]]["score"])
                    == max(
                        float(x["dimensions"][d["name"]]["score"])
                        for x in rows
                        if x.get("dimensions", {}).get(d["name"], {}).get("score") is not None
                    )
                ][:3],
                "ours": {
                    r["name"]: r.get("dimensions", {}).get(d["name"], {}).get("score")
                    for r in rows
                    if r.get("is_self")
                },
            }
            for d in sorted(
                card.get("dimensions", []), key=lambda d: -float(d.get("weight_pct") or 0)
            )[:6]
        ],
        "voice_of_customer": (
            {
                "window_days": voice.get("window_days"),
                "mentions": voice.get("mentions"),
                "sources": voice.get("sources"),
                "field_themes": voice.get("field_themes"),
                "brands": [
                    {
                        "brand": b.get("name"),
                        "is_self": b.get("is_self"),
                        "n": b.get("n"),
                        "too_few": b.get("too_few"),
                        "neg_share": b.get("neg_share"),
                        "top_complaint": b.get("top_complaint"),
                        "top_praise": b.get("top_praise"),
                        "flags": b.get("flags"),
                        "quotes": [q.get("quote") for q in (b.get("quotes") or [])[:2]],
                    }
                    for b in voice.get("brands", [])
                ],
            }
            if voice
            else None
        ),
        "player_comms": (
            {
                "window_days": comms.get("window_days"),
                "emails": comms.get("emails"),
                "brands": [
                    {
                        "brand": b.get("name"),
                        "is_self": b.get("is_self"),
                        "n": b.get("n"),
                        "per_week": b.get("per_week"),
                        "categories": b.get("categories"),
                        "latest_offers": b.get("latest_offers"),
                    }
                    for b in comms.get("brands", [])
                    if b.get("inbox")
                ],
            }
            if comms
            else None
        ),
        "market_events": [
            {"brand": ev["brand"], "claim": ev["claim"], "observed": ev.get("observed_at", "")}
            for ev in (events or [])
        ],
        "offers_observed": [
            {
                "brand": o["brand"],
                "is_us": o["is_self"],
                "welcome": o.get("welcome") or "",
                "ongoing": o.get("ongoing") or "",
            }
            for o in (offers or [])
        ],
        "gaps": {
            "never_observed_pairs": sum(1 for g in gaps if g.get("status") == "never_observed"),
            "unobserved_brands": sorted(
                {g["subject"] for g in gaps if g.get("status") == "never_observed"}
            )[:6],
            "stale": sum(1 for g in gaps if g.get("status") == "stale"),
        },
    }
    try:
        resp = await router.complete(
            messages=[
                {"role": "system", "content": _DECK_NARRATIVE_SYSTEM},
                {"role": "user", "content": _json.dumps(facts, indent=1, default=str)},
            ],
            task_type="analysis",
            temperature=0.3,
            max_tokens=4000,
        )
        text = (resp.content or "").strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            text = text[4:] if text.startswith("json") else text
        data = _json.loads(text)
        bullets = [str(b).strip() for b in data.get("bullets", []) if str(b).strip()]
        if not bullets:
            return fallback
        known = {str(r.get("name") or "") for r in rows}
        exec_zone = data.get("exec") or {}
        profiles = [
            {
                "brand": str(pr.get("brand") or "").strip(),
                "title": str(pr.get("title") or "").strip(),
                "observations": [
                    str(o).strip() for o in (pr.get("observations") or []) if str(o).strip()
                ][:4],
                "implications": [
                    str(i).strip() for i in (pr.get("implications") or []) if str(i).strip()
                ][:2],
            }
            for pr in (data.get("profiles") or [])
            if isinstance(pr, dict) and str(pr.get("brand") or "").strip() in known
        ]
        known_dims = {str(d.get("name") or "") for d in card.get("dimensions", [])}
        by_dim = [
            {
                "dimension": str(d.get("dimension") or "").strip(),
                "observations": [
                    str(o).strip() for o in (d.get("observations") or []) if str(o).strip()
                ][:3],
            }
            for d in (exec_zone.get("by_dimension") or [])
            if isinstance(d, dict) and str(d.get("dimension") or "").strip() in known_dims
        ]
        slides_raw = data.get("slides") or {}
        slides = {
            k: {
                "observations": [
                    str(o).strip() for o in (v.get("observations") or []) if str(o).strip()
                ][:4],
                "implications": [
                    str(i).strip() for i in (v.get("implications") or []) if str(i).strip()
                ][:3],
            }
            for k, v in slides_raw.items()
            if isinstance(v, dict)
            and k in ("standings", "versus", "dimensions", "offers", "exhibits", "coverage", "voice", "comms")
        }
        return {
            "headline": str(data.get("headline") or "").strip(),
            "bullets": bullets[:5],
            "exec": {
                "findings": [
                    str(x).strip() for x in (exec_zone.get("findings") or []) if str(x).strip()
                ][:4],
                "threats": [
                    str(x).strip() for x in (exec_zone.get("threats") or []) if str(x).strip()
                ][:3],
                "watch": [str(x).strip() for x in (exec_zone.get("watch") or []) if str(x).strip()][
                    :3
                ],
                "by_dimension": [d for d in by_dim if d["observations"]][:6]
                or (fallback.get("exec") or {}).get("by_dimension", []),
                "recommendation": str(exec_zone.get("recommendation") or "").strip(),
                "actions": [
                    str(a).strip() for a in (exec_zone.get("actions") or []) if str(a).strip()
                ][:3],
            },
            "slides": slides or fallback.get("slides", {}),
            "profiles": [pr for pr in profiles if pr["observations"]][:8],
            "titles": {
                k: str(v).strip() for k, v in (data.get("titles") or {}).items() if str(v).strip()
            },
            "commentary": {
                k: str(v).strip()
                for k, v in (data.get("commentary") or {}).items()
                if str(v).strip()
            },
            "next_steps": [
                str(b).strip() for b in (data.get("next_steps") or []) if str(b).strip()
            ][:4]
            or fallback["next_steps"],
            "source": "model",
        }
    except Exception as e:  # the deck still ships — as facts, and says so
        import logging

        logging.getLogger(__name__).warning("deck narrative failed: %s", e)
        return fallback


async def _voice_for_pack(
    wm: Any, cid: str, params: dict[str, Any], *, window_days: int = 30
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The voice summary and theme diff to lay on top of a pack — or
    ``(None, None)`` when voice is off or nothing was collected. 'auto'
    (default) means: present when rows exist. Never raises: voice must not
    break the pack it rides on."""
    mode = str(params.get("voice") or "auto").lower()
    if mode == "false":
        return None, None
    try:
        summary = await wm.voice_summary(cid, window_days=window_days)
    except Exception:
        return None, None
    if not summary.get("mentions") and mode != "true":
        return None, None
    try:
        vdiff = await wm.diff_voice_since_snapshot(cid)
    except Exception:
        vdiff = None
    return summary, vdiff


def _voice_rows_for_export(rows: list[Any], subjects: list[Any], dims: list[Any]) -> list[dict[str, Any]]:
    names = {s.subject_id: s.name for s in subjects}
    dnames = {d.dimension_id: d.name for d in dims}
    return [
        {
            "brand": names.get(r.subject_id, r.subject_id),
            "source": r.source,
            "posted_at": r.posted_at or r.observed_at,
            "theme": r.theme,
            "sentiment": r.sentiment,
            "rating": r.rating,
            "quote": r.quote,
            "dimension": dnames.get(r.dimension_id, ""),
            "geo_hint": r.geo_hint,
            "weight": r.weight,
            "url": r.source_url,
        }
        for r in rows
    ]


async def _comms_for_pack(wm: Any, cid: str, params: dict[str, Any], *, window_days: int = 30) -> dict[str, Any] | None:
    """Player comms summary for the pack — None when off or nothing filed.
    Rides the same voice=auto|true|false switch (they are the two evidence
    classes on top of the pack)."""
    mode = str(params.get("voice") or "auto").lower()
    if mode == "false":
        return None
    try:
        summary = await wm.comms_summary(cid, window_days=window_days)
    except Exception:
        return None
    if not summary.get("emails") and mode != "true":
        return None
    return summary


def _comms_rows_for_export(rows: list[Any], subjects: list[Any]) -> list[dict[str, Any]]:
    names = {s.subject_id: s.name for s in subjects}
    return [
        {
            "brand": names.get(r.subject_id, r.subject_id),
            "received_at": r.received_at,
            "category": r.category,
            "subject": r.subject_line,
            "offer": r.offer_text,
            "excerpt": r.excerpt,
            "sender": r.sender,
            "inbox": r.inbox,
        }
        for r in rows
    ]


def _regulatory_markdown(cal: dict[str, Any]) -> list[str]:
    lines = ["## Regulatory calendar", ""]
    lines.append(f"_{cal.get('label', '')}_ {cal.get('total', 0)} items on record.")
    lines.append("")
    if cal.get("ahead"):
        lines.append(f"**Dated items in the next {cal.get('horizon_days', 90)} days**")
        lines.append("")
        lines.append("| Date | Jurisdiction | Kind | Item | Status | Source |")
        lines.append("|---|---|---|---|---|---|")
        for i in cal["ahead"][:10]:
            lines.append(
                f"| {i['event_date']} | {i['jurisdiction']} | {i['kind'].replace('_', ' ')} | {i['title']} | "
                f"{i.get('status', '')} | {i.get('source_url', '')} |"
            )
        lines.append("")
    if cal.get("recent_actions"):
        lines.append("**Enforcement and lawsuits observed in the last 30 days**")
        lines.append("")
        for i in cal["recent_actions"][:6]:
            lines.append(f"- {i['jurisdiction']} · {i['kind']}: {i['title']}" + (f" ({', '.join(i['subjects'])})" if i.get("subjects") else ""))
        lines.append("")
    if cal.get("operator_responses"):
        lines.append("**Operator responses on record**")
        lines.append("")
        for i in cal["operator_responses"][:8]:
            lines.append(f"- {i['jurisdiction']}: {i['title']}" + (f" — {i['event_date']}" if i.get("event_date") else ""))
        lines.append("")
    return lines


def _catalog_rows_for_export(rows: list[Any], subjects: list[Any]) -> list[dict[str, Any]]:
    from core.watch_catalog import promo_fields

    names = {s.subject_id: s.name for s in subjects}
    selves = {s.subject_id for s in subjects if getattr(s, "is_self", False)}
    return [
        {
            "brand": names.get(r.subject_id, r.subject_id), "kind": r.kind, "name": r.name,
            "detail": r.detail, "price_usd": r.price_usd, "coins": r.coins_text,
            "sort_index": r.sort_index, "url": r.source_url, "image": r.image_path,
            "session": r.customer_state, "observed_at": r.observed_at,
            "source_type": r.source_type, "is_self": r.subject_id in selves, **(r.meta or {}),
            # the workbook's Benefit / How to claim / Frequency read like the deck's
            **(promo_fields(r.name, r.detail, r.meta) if r.kind == "promotion" else {}),
        }
        for r in rows
    ]


def _provider_universe(params: dict[str, Any]) -> dict[str, Any] | None:
    """The client's own studio list (``providers_from``: their game-portfolio
    sheet as CSV), when given and readable — else None and the matrix
    follows what was observed."""
    path = str(params.get("providers_from") or "").strip()
    if not path:
        return None
    from core.watch_catalog import read_provider_universe

    try:
        uni = read_provider_universe(path)
    except Exception:
        return None
    return uni if uni.get("providers") else None


async def _catalog_for_pack(wm: Any, cid: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """The raw inventory to lay in the appendix — None when off or empty.
    Rides the same voice=auto|true|false switch as the other classes."""
    if str(params.get("voice") or "auto").lower() == "false":
        return None
    try:
        cat = await wm.catalog_summary(cid, _provider_universe(params))
    except Exception:
        return None
    return cat if cat.get("items") else None


async def _tone_for_pack(wm: Any, cid: str, params: dict[str, Any], router: Any) -> dict[str, Any] | None:
    """How each brand talks, built from copy already collected — promotions,
    marketing lines and e-mails. None when off or when there is no copy."""
    if str(params.get("voice") or "auto").lower() == "false" or not params.get("tone", True):
        return None
    from core.watch_tone import copy_samples, read_tone, summarize_tone, tone_features

    try:
        subjects = await wm.list_subjects(cid)
        evidence = await wm.evidence_with_names(cid)
        catalog = await wm.list_catalog(cid)
        comms = await wm.list_comms(cid, limit=5000)
    except Exception:
        return None
    by_subject: dict[str, list[dict[str, Any]]] = {}
    for e in evidence:
        by_subject.setdefault(str(e.get("subject") or ""), []).append(e)
    brands: list[dict[str, Any]] = []
    for subj in subjects:
        samples = copy_samples(
            brand=subj.name,
            evidence=by_subject.get(subj.name, []),
            catalog=[c for c in catalog if c.subject_id == subj.subject_id],
            comms=[c for c in comms if c.subject_id == subj.subject_id],
        )
        if not samples:
            continue
        brands.append({
            "name": subj.name,
            "is_self": bool(subj.is_self),
            "samples": samples,
            "features": tone_features([s["text"] for s in samples]),
        })
    if not brands:
        return None
    return summarize_tone(brands, await read_tone(router, brands))


def _tone_markdown(tone: dict[str, Any]) -> list[str]:
    lines = ["## Tone of voice", ""]
    lines.append(f"_{tone.get('label', '')}_")
    lines.append("")
    lines.append("| Brand | Voice | CAPS | !/line | Urgency /100w | In its own words |")
    lines.append("|---|---|---:|---:|---:|---|")
    for b in tone.get("brands", []):
        f = b["features"]
        line = b.get("signature") or (b["quotes"][0]["text"] if b.get("quotes") else "")
        lines.append(
            f"| {b['name']}{' (us)' if b['is_self'] else ''} | {b.get('register') or '—'} | "
            f"{f.get('caps_pct', 0):g}% | {f.get('exclaims_per_line', 0):g} | "
            f"{f.get('urgency_per_100w', 0):g} | “{line[:110]}” |"
        )
    lines.append("")
    for b in tone.get("brands", []):
        if b.get("traits"):
            lines.append(f"- **{b['name']}** — {'; '.join(b['traits'])}"
                         + (f" Avoids: {b['avoid']}." if b.get("avoid") else ""))
    lines.append("")
    return lines


def _catalog_markdown(cat: dict[str, Any]) -> list[str]:
    t = cat.get("totals", {})
    lines = ["## Raw data: providers, packages, promotions, games", ""]
    lines.append(
        f"_{cat.get('label', '')}_ {t.get('provider', 0)} providers, "
        f"{t.get('coin_package', 0)} coin packages, {t.get('promotion', 0)} promotions and "
        f"{t.get('game', 0)} game titles read across {len(cat.get('brands', []))} brands; "
        "every item is in the workbook with its source URL."
    )
    lines.append("")
    lines.append("| Brand | Providers | Packages | Promotions | Games | Cheapest package | Read as |")
    lines.append("|---|---:|---:|---:|---:|---|---|")
    for b in cat.get("brands", []):
        c = b["counts"]
        cheapest = ""
        priced = [p for p in b["packages"] if p.get("price_usd") is not None]
        if priced:
            p0 = priced[0]
            cheapest = f"${p0['price_usd']:.2f}" + (f" — {p0['coins']}" if p0.get("coins") else "")
        lines.append(
            f"| {b['name']}{' (us)' if b['is_self'] else ''} | {c.get('provider', 0)} | "
            f"{c.get('coin_package', 0)} | {c.get('promotion', 0)} | {c.get('game', 0)} | "
            f"{cheapest} | {', '.join(b['customer_states'])} |"
        )
    lines.append("")
    return lines


def _comms_markdown(comms: dict[str, Any]) -> list[str]:
    lines = ["## What they send players", ""]
    lines.append(
        f"_{comms.get('label', '')}_ {comms.get('emails', 0)} e-mails in {comms.get('window_days', 30)} days "
        "from the brands with a linked inbox."
    )
    lines.append("")
    lines.append("| Brand | E-mails | /week | Mix | Latest offer |")
    lines.append("|---|---:|---:|---|---|")
    for b in comms.get("brands", []):
        if not b.get("inbox"):
            continue
        mix = ", ".join(f"{c.replace('_', ' ')} {n}" for c, n in sorted((b.get("categories") or {}).items(), key=lambda kv: -kv[1])[:3])
        latest = (b.get("latest_offers") or [{}])[0].get("offer", "") if b.get("latest_offers") else ""
        lines.append(f"| {b['name']}{' (us)' if b.get('is_self') else ''} | {b.get('n', 0)} | {b.get('per_week', 0):g} | {mix} | {latest} |")
    lines.append("")
    return lines


def _voice_markdown(voice: dict[str, Any], vdiff: dict[str, Any] | None) -> list[str]:
    """The 'What players say' section of the board report."""
    lines = ["## What players say", ""]
    lines.append(
        f"_{voice.get('label', '')}_ {voice.get('mentions', 0)} public mentions in "
        f"{voice.get('window_days', 30)} days from {', '.join(voice.get('sources') or []) or 'no source'}; "
        f"brands under {voice.get('min_mentions', 15)} mentions are not read."
    )
    lines.append("")
    lines.append("| Brand | n | Negative | Top complaint | Top praise | Players flag |")
    lines.append("|---|---:|---:|---|---|---|")
    for b in voice.get("brands", []):
        if b.get("too_few"):
            lines.append(f"| {b['name']}{' (us)' if b.get('is_self') else ''} | {b.get('n', 0)} | — | too few mentions to read | | |")
            continue
        lines.append(
            f"| {b['name']}{' (us)' if b.get('is_self') else ''} | {b.get('n', 0)} | "
            f"{int(round(b.get('neg_share', 0) * 100))}% | "
            f"{(b.get('top_complaint') or '').replace('_', ' ')} | "
            f"{(b.get('top_praise') or '').replace('_', ' ')} | {', '.join(b.get('flags') or [])} |"
        )
    lines.append("")
    for b in voice.get("brands", []):
        if b.get("too_few") or not b.get("quotes"):
            continue
        q = b["quotes"][0]
        lines.append(f"- **{b['name']}** — “{q['quote']}” ({q['source']}, {q['posted_at']})")
    lines.append("")
    if vdiff and not vdiff.get("baseline") and vdiff.get("changed"):
        lines.append("**Rising and falling since the last cycle:**")
        for c in vdiff["changed"][:6]:
            arrow = "▲" if c["direction"] == "rising" else "▼"
            lines.append(
                f"- {arrow} {c['brand']} · {c['theme'].replace('_', ' ')}: "
                f"{int(round(c['share_from'] * 100))}% → {int(round(c['share_to'] * 100))}% of mentions, "
                f"{int(round(c['neg_from'] * 100))}% → {int(round(c['neg_to'] * 100))}% negative"
            )
        lines.append("")
    elif vdiff and vdiff.get("baseline"):
        lines.append("_First cycle with voice collected — movement appears next cycle._")
        lines.append("")
    return lines


class WatchBoardReportTool(_WatchToolBase):
    """Turn the month's material changes into implications and decisions."""

    def __init__(self) -> None:
        super().__init__()
        self._router: Any = None
        self._config: Any = None  # workspace root, for storefront exhibits

    @property
    def name(self) -> str:
        return "watch_board_report"

    @property
    def description(self) -> str:
        return (
            "Produce the monthly competitor board report: material changes "
            "since the last snapshot, each turned into an implication, a "
            "recommendation classified as no-regret / transition-requirement / "
            "post-transition / monitor, and the decision the board must make — "
            "plus current standings and outstanding evidence gaps. When written "
            "to a path, the executive deck (.pptx) is written beside it."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "snapshot_id": {
                    "type": "string",
                    "description": "Compare against this snapshot. Default: most recent.",
                },
                "path": {
                    "type": "string",
                    "description": "Optional file to write the markdown report to.",
                },
                "take_snapshot": {
                    "type": "boolean",
                    "description": "Snapshot the current state after reporting. Default true.",
                },
                "baseline": {
                    "type": "boolean",
                    "description": (
                        "This pack ESTABLISHES a baseline — a from-scratch or "
                        "first analysis. No comparison against any prior "
                        "snapshot; the report and deck say 'baseline', not "
                        "'N material changes'. Use for 'fresh', 'from scratch' "
                        "or first-run analyses. Default false."
                    ),
                },
                "voice": {
                    "type": "string",
                    "enum": ["auto", "true", "false"],
                    "description": (
                        "Voice of customer on top of the pack: 'auto' (default) "
                        "adds the 'What players say' section/slides when voice "
                        "rows exist for this company; 'false' leaves them out; "
                        "'true' insists (empty section if nothing collected). The "
                        "same switch governs player comms and the regulatory calendar."
                    ),
                },
                "providers_from": {
                    "type": "string",
                    "description": "Path to the client's own game-portfolio sheet (CSV; column A = "
                                   "studios, header row = their brands). The Provider × Brand matrix "
                                   "then follows their list and marks what is not on it.",
                },
                "tone": {
                    "type": "boolean",
                    "description": (
                        "Tone-of-voice slide and section — how each brand talks to players, "
                        "measured from copy already collected (promotions, site lines, "
                        "e-mails). Default true."
                    ),
                },
                "trends": {
                    "type": "boolean",
                    "description": "Trend slide once ≥3 scored snapshots exist. Default true.",
                },
                "calendar": {
                    "type": "boolean",
                    "description": "Add the 8-week demand calendar slide (holidays, paydays, benefit and tax dates). Default false.",
                },
                "calendar_events": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Operator-supplied events for the calendar: [{date: YYYY-MM-DD, label, kind}]. Sports dates go here — never guessed.",
                },
                "deck": {
                    "type": "boolean",
                    "description": (
                        "Also write the executive deck (.pptx) — the same facts "
                        "and judgement as ~10 board slides. Default true whenever "
                        "`path` is set; the deck lands beside the report."
                    ),
                },
                "deck_path": {
                    "type": "string",
                    "description": (
                        "Where to write the deck. Default: `path` with a .pptx suffix."
                    ),
                },
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def _judge(self, diff: dict[str, Any]) -> list[dict[str, Any]]:
        """Ask the router to turn facts into implications. Optional by design:
        with no router the report still ships the facts, clearly marked."""
        if self._router is None:
            return []
        import json as _json

        facts = [
            {"subject": c["subject"], "changes": [i["detail"] for i in c["items"]]}
            for c in diff.get("changed", [])
        ]
        if diff.get("added_subjects"):
            facts.append({"subject": "(new entrants)", "changes": diff["added_subjects"]})
        if not facts:
            return []
        try:
            resp = await self._router.complete(
                messages=[
                    {"role": "system", "content": _BOARD_SYSTEM},
                    {"role": "user", "content": _json.dumps(facts, indent=1)},
                ],
                task_type="analysis",
                temperature=0.2,
                max_tokens=1800,
            )
            text = (resp.content or "").strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                text = text[4:] if text.startswith("json") else text
            data = _json.loads(text)
            items = data.get("items", []) if isinstance(data, dict) else []
            return [i for i in items if isinstance(i, dict)]
        except Exception as e:  # judgement is best-effort; facts are not
            import logging

            logging.getLogger(__name__).warning("board report judgement failed: %s", e)
            return []

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        cid = _company(params)
        wm = self._watch_manager

        # A from-scratch analysis has nothing to move FROM. Diffing it against
        # a snapshot taken earlier the same day (or by a previous run of the
        # same baseline) manufactures "141 material changes" out of the
        # collection itself. baseline=true declares intent: no diff, and the
        # pack says so.
        diff = (
            None
            if params.get("baseline")
            else await wm.diff_since_snapshot(cid, snapshot_id=params.get("snapshot_id"))
        )
        card = await wm.scorecard(cid)
        gaps = await wm.staleness(cid)

        lines: list[str] = ["# Competitor board report", ""]
        if diff is None:
            lines += [
                "**First reporting cycle** — no prior snapshot, so there is "
                "nothing to compare against yet. This report establishes the "
                "baseline; next cycle will show material change.",
                "",
            ]
        else:
            lines += [
                f"Period: {diff.get('from_generated_at', '?')} → "
                f"{diff.get('to_generated_at', '?')}",
                f"Material changes: **{diff.get('material_count', 0)}**",
                "",
            ]

        # ── Standings ──
        lines += ["## Standings", ""]
        if card.get("comparability_note"):
            lines += [
                "> **Not yet a league table.** " + card["comparability_note"] + ".",
                "> Scores are shown; ranks are withheld until the field is "
                "measured to comparable depth.",
                "",
            ]
        lines += [
            "| # | Brand | Overall | Cust. prop | Transition | Coverage |",
            "|---|-------|---------|-----------|------------|----------|",
        ]
        for r in card["rows"][:15]:
            o = r["overall"]
            cp = r["views"].get("customer_proposition", {}).get("normalized_pct")
            tp = r["views"].get("transition_priority", {}).get("normalized_pct")
            fmt = lambda v: "—" if v is None else f"{v:.1f}"  # noqa: E731
            overall_txt = fmt(o["normalized_pct"])
            if r.get("provisional") and o["normalized_pct"] is not None:
                overall_txt += "†"
            lines.append(
                f"| {r['rank'] or '—'} | {r['name']}{' *(us)*' if r['is_self'] else ''} "
                f"| {overall_txt} | {fmt(cp)} | {fmt(tp)} "
                f"| {o['coverage_pct']:.0f}% |"
            )
        board_provisional = [
            r
            for r in card["rows"][:15]
            if r.get("provisional") and r["overall"]["normalized_pct"] is not None
        ]
        if board_provisional:
            lines += [
                "",
                "† Provisional: scored on too little of the model to hold a rank. "
                "The figure is real; the standing is not yet earned.",
            ]
            lines += [
                f"- **{r['name']}** — {r.get('provisional_reason', '')}" for r in board_provisional
            ]
        lines.append("")

        # ── Material changes + judgement ──
        judged: list[dict[str, Any]] = []
        if diff and diff.get("material_count"):
            lines += ["## Material changes", ""]
            for c in diff.get("changed", []):
                lines.append(f"**{c['subject']}**")
                for item in c["items"]:
                    lines.append(f"- {item['detail']}")
                lines.append("")
            if diff.get("added_subjects"):
                lines.append(f"**New in the analysis:** {', '.join(diff['added_subjects'])}")
                lines.append("")
            if diff.get("removed_subjects"):
                lines.append(f"**Removed:** {', '.join(diff['removed_subjects'])}")
                lines.append("")

            judged = await self._judge(diff)
            if judged:
                lines += ["## Implications and recommendations", ""]
                lines += [
                    "| Subject | Change | Implication | Recommendation | Class | Decision required |",
                    "|---------|--------|-------------|----------------|-------|-------------------|",
                ]
                for j in judged:
                    lines.append(
                        f"| {j.get('subject', '')} | {j.get('change', '')} "
                        f"| {j.get('implication', '')} | {j.get('recommendation', '')} "
                        f"| `{j.get('classification', 'monitor')}` "
                        f"| {j.get('decision_required', 'none')} |"
                    )
                lines.append("")
            else:
                lines += [
                    "> Implications not generated (no model available). The "
                    "material changes above are the factual record; judgement "
                    "still needs to be applied.",
                    "",
                ]
        elif diff is not None:
            lines += [
                "## Material changes",
                "",
                "None this period above the materiality threshold "
                f"(score move ≥ {diff['thresholds']['min_score_delta']}, "
                f"coverage shift ≥ {diff['thresholds']['min_coverage_delta']}%).",
                "",
            ]

        trends = None
        try:
            trends = await wm.trend_series(cid)
            if int(trends.get("cycles", 0)) < 3 or not params.get("trends", True):
                trends = None
        except Exception:
            trends = None
        calendar = None
        if params.get("calendar"):
            from core.watch_calendar import demand_calendar

            calendar = demand_calendar(weeks=8, events=params.get("calendar_events") or [])

        # ── Tone of voice ──
        tone = await _tone_for_pack(wm, cid, params, self._router)
        if tone:
            lines += _tone_markdown(tone)

        # ── Raw data appendix (docs/89) ──
        catalog = await _catalog_for_pack(wm, cid, params)
        if catalog:
            lines += _catalog_markdown(catalog)

        # ── Regulatory calendar (docs/88 §D) ──
        regulatory = None
        if str(params.get("voice") or "auto").lower() != "false":
            try:
                regulatory = await wm.regulatory_calendar(cid)
                if not regulatory.get("total"):
                    regulatory = None
            except Exception:
                regulatory = None
        if regulatory:
            lines += _regulatory_markdown(regulatory)

        # ── What they send players (comms, on top; docs/88) ──
        comms = await _comms_for_pack(wm, cid, params)
        if comms is not None and comms.get("emails"):
            lines += _comms_markdown(comms)

        # ── What players say (voice of customer, on top; docs/87) ──
        voice, voice_diff = await _voice_for_pack(wm, cid, params)
        if voice is not None:
            lines += _voice_markdown(voice, voice_diff)

        # ── Evidence gaps ──
        never = [g for g in gaps if g["status"] == "never_observed"]
        stale = [g for g in gaps if g["status"] == "stale"]
        lines += ["## Evidence gaps", ""]
        lines.append(
            f"- **{len(never)}** brand × dimension pairs never observed"
            + (f" (e.g. {never[0]['subject']} / {never[0]['dimension']})" if never else "")
        )
        lines.append(f"- **{len(stale)}** overdue a refresh against their cadence")
        lines.append("")
        lines.append(
            "> Gaps are absences of evidence, not weaknesses. No brand is "
            "scored down for being opaque."
        )

        report = "\n".join(lines)
        written = None
        if params.get("path"):
            from pathlib import Path

            p = Path(str(params["path"])).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(report, encoding="utf-8")
            written = str(p)

        # The deck is the same facts and the same judgement, before the
        # snapshot below — so both deliverables describe one period. It is
        # part of the pack, not an extra: whenever the report goes to disk,
        # the deck goes beside it unless deck=false.
        deck_written = None
        deck_error = None
        deck_target = str(params.get("deck_path") or "").strip()
        if not deck_target and written:
            from pathlib import Path as _P

            deck_target = str(_P(written).with_suffix(".pptx"))
        if not params.get("deck", True):
            deck_target = ""
        if deck_target:
            try:
                from core.watch_deck import render_executive_deck

                ev_rows = await wm.evidence_with_names(cid)
                from core.watch_deck import market_events

                exhibits = _collect_exhibits(ev_rows, card.get("rows", []), self._config)
                offers = _offer_facts(card, ev_rows, exhibits)
                events = market_events(ev_rows)
                summary = await _narrate_for_deck(
                    self._router,
                    card=card,
                    diff=diff,
                    judged=judged,
                    gaps=gaps,
                    evidence=ev_rows,
                    offers=offers,
                    events=events,
                    voice=voice,
                    comms=comms,
                )
                deck_written = render_executive_deck(
                    card,
                    diff=diff,
                    judged=judged,
                    summary=summary,
                    gaps=gaps,
                    evidence_count=len(ev_rows),
                    screenshots=exhibits,
                    offers=offers,
                    events=events,
                    voice=voice,
                    voice_diff=voice_diff,
                    comms=comms,
                    regulatory=regulatory,
                    catalog=catalog,
                    tone=tone,
                    trends=trends,
                    calendar=calendar,
                    path=deck_target,
                )
            except Exception as e:
                deck_error = str(e)

        snap_id = None
        if params.get("take_snapshot", True):
            snap_id = await wm.take_snapshot(cid, label="board report")

        data: dict[str, Any] = {
            "markdown": report,
            "material_count": (diff or {}).get("material_count", 0),
            "judged_items": len(judged),
            "gaps_never_observed": len(never),
            "gaps_stale": len(stale),
            "path": written,
            "snapshot_id": snap_id,
        }
        if deck_target:
            data["deck_path"] = deck_written
            if deck_error:
                data["deck_error"] = deck_error
        return ToolResult(success=True, data=data)


class WatchExecutiveDeckTool(_WatchToolBase):
    """The board pack as slides: standings, our position, what moved, what to
    do, what to decide, and how much of it is actually measured."""

    def __init__(self) -> None:
        super().__init__()
        self._router: Any = None
        self._config: Any = None  # workspace root, for storefront exhibits

    @property
    def name(self) -> str:
        return "watch_executive_deck"

    @property
    def description(self) -> str:
        return (
            "Produce the executive presentation (.pptx, ~16 slides) of the "
            "competitor analysis: executive summary (findings / threats / "
            "watch next), standings chart, our brand vs the leader, a deep-"
            "dive slide per key competitor (observations → implications), "
            "storefront screenshot exhibits, market moves, implications and "
            "recommendations, decisions required, and appendix (coverage, "
            "heatmap, method). Same stored evidence as the workbook and board "
            "report — use when asked for a presentation, deck, slides or "
            "board pack. Does not snapshot; run watch_board_report to close "
            "the cycle."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Where to write the .pptx. Default ~/Desktop/competitor-deck.pptx",
                },
                "snapshot_id": {
                    "type": "string",
                    "description": "Compare against this snapshot. Default: most recent.",
                },
                "title": {
                    "type": "string",
                    "description": "Deck title. Default 'Competitive Intelligence — Executive Briefing'.",
                },
                "market_label": {
                    "type": "string",
                    "description": "Subtitle on the cover, e.g. the market or client name.",
                },
                "baseline": {
                    "type": "boolean",
                    "description": (
                        "This deck establishes a baseline (from-scratch / first "
                        "analysis): no comparison against a prior snapshot. "
                        "Default false."
                    ),
                },
                "voice": {
                    "type": "string",
                    "enum": ["auto", "true", "false"],
                    "description": (
                        "Voice of customer on top of the pack: 'auto' (default) "
                        "adds the 'What players say' section/slides when voice "
                        "rows exist for this company; 'false' leaves them out; "
                        "'true' insists (empty section if nothing collected). The "
                        "same switch governs player comms and the regulatory calendar."
                    ),
                },
                "providers_from": {
                    "type": "string",
                    "description": "Path to the client's own game-portfolio sheet (CSV; column A = "
                                   "studios, header row = their brands). The Provider × Brand matrix "
                                   "then follows their list and marks what is not on it.",
                },
                "tone": {
                    "type": "boolean",
                    "description": (
                        "Tone-of-voice slide and section — how each brand talks to players, "
                        "measured from copy already collected (promotions, site lines, "
                        "e-mails). Default true."
                    ),
                },
                "trends": {
                    "type": "boolean",
                    "description": "Trend slide once ≥3 scored snapshots exist. Default true.",
                },
                "calendar": {
                    "type": "boolean",
                    "description": "Add the 8-week demand calendar slide (holidays, paydays, benefit and tax dates). Default false.",
                },
                "calendar_events": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Operator-supplied events for the calendar: [{date: YYYY-MM-DD, label, kind}]. Sports dates go here — never guessed.",
                },
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        cid = _company(params)
        wm = self._watch_manager
        from pathlib import Path

        path = Path(str(params.get("path") or "~/Desktop/competitor-deck.pptx")).expanduser()
        if path.suffix.lower() != ".pptx":
            path = path.with_suffix(".pptx")

        # A from-scratch analysis has nothing to move FROM. Diffing it against
        # a snapshot taken earlier the same day (or by a previous run of the
        # same baseline) manufactures "141 material changes" out of the
        # collection itself. baseline=true declares intent: no diff, and the
        # pack says so.
        diff = (
            None
            if params.get("baseline")
            else await wm.diff_since_snapshot(cid, snapshot_id=params.get("snapshot_id"))
        )
        card = await wm.scorecard(cid)
        gaps = await wm.staleness(cid)
        evidence = await wm.evidence_with_names(cid)

        # Reuse the report's judgement so both artefacts say the same thing.
        judge = WatchBoardReportTool()
        judge._router = self._router
        judged = await judge._judge(diff) if diff else []
        exhibits = _collect_exhibits(evidence, card.get("rows", []), self._config)
        from core.watch_deck import market_events

        offers = _offer_facts(card, evidence, exhibits)
        events = market_events(evidence)
        voice, voice_diff = await _voice_for_pack(wm, cid, params)
        comms = await _comms_for_pack(wm, cid, params)
        regulatory = None
        if str(params.get("voice") or "auto").lower() != "false":
            try:
                regulatory = await wm.regulatory_calendar(cid)
                if not regulatory.get("total"):
                    regulatory = None
            except Exception:
                regulatory = None
        catalog = await _catalog_for_pack(wm, cid, params)
        tone = await _tone_for_pack(wm, cid, params, self._router)
        trends = None
        try:
            trends = await wm.trend_series(cid)
            if int(trends.get("cycles", 0)) < 3 or not params.get("trends", True):
                trends = None
        except Exception:
            trends = None
        calendar = None
        if params.get("calendar"):
            from core.watch_calendar import demand_calendar

            calendar = demand_calendar(weeks=8, events=params.get("calendar_events") or [])
        summary = await _narrate_for_deck(
            self._router,
            card=card,
            diff=diff,
            judged=judged,
            gaps=gaps,
            evidence=evidence,
            offers=offers,
            events=events,
            voice=voice,
            comms=comms,
        )
        try:
            from core.watch_deck import render_executive_deck

            written = render_executive_deck(
                card,
                diff=diff,
                judged=judged,
                summary=summary,
                gaps=gaps,
                evidence_count=len(evidence),
                screenshots=exhibits,
                offers=offers,
                events=events,
                voice=voice,
                voice_diff=voice_diff,
                comms=comms,
                regulatory=regulatory,
                catalog=catalog,
                tone=tone,
                trends=trends,
                calendar=calendar,
                path=path,
                title=str(params.get("title") or "Competitive Intelligence — Executive Briefing"),
                market_label=str(params.get("market_label") or ""),
            )
        except Exception as e:
            return ToolResult(success=False, error=f"deck export failed: {e}")

        ranked = [r for r in card["rows"] if r.get("rank") is not None]
        return ToolResult(
            success=True,
            data={
                "path": written,
                "brands": len(card["rows"]),
                "ranked": len(ranked),
                "material_count": (diff or {}).get("material_count", 0),
                "judged_items": len(judged),
                "summary_source": summary.get("source", "facts"),
                "note": (
                    "Summary and implications are model-written from the factual "
                    "record and labelled as such on the slides; standings, scores "
                    "and gaps are computed. Unscored dimensions are blank, never "
                    "zero, and provisional brands are listed, not ranked."
                    if summary.get("source") == "model"
                    else "No model available: the summary slide is factual only "
                    "and says so. Standings, scores and gaps are computed."
                ),
            },
        )


def _exit_not_verified(geo_state: str, detail: dict[str, Any]) -> ToolResult:
    """Refuse when the exit cannot be *proven* to be in the claimed state.

    Two distinct failures share this gate: the provider routed the request
    somewhere else (targeting is best-effort — observed `_state-texas`
    exiting in Virginia), or the geolocation echoes were unreachable so
    nothing could be proven either way. Both end the same: no proof, no
    stamp. "Could not verify" must never soften into "verified".
    """
    landed = [
        f"{g.get('state_code')} ({g.get('ip')})"
        for g in detail.get("landed", [])
        if isinstance(g, dict) and g.get("state_code")
    ]
    unreachable = any(isinstance(g, dict) and g.get("error") for g in detail.get("landed", []))
    if landed:
        why = f"the exit landed in {', '.join(landed)} instead"
    elif unreachable:
        why = "the geolocation services could not be reached, so nothing was proven"
    else:
        why = "the exit could not be verified"
    return ToolResult(
        success=False,
        error=(
            f"Exit verification failed for geo_state={geo_state}: {why}. "
            "State targeting is best-effort at the provider, so retrying may "
            "land correctly (each attempt re-rolls the exit). Evidence is only "
            "stamped with a state its exit provably came from."
        ),
    )


def _no_exit_for_state(geo_state: str) -> ToolResult:
    """Refuse rather than collect from the wrong place and stamp it right.

    `geo_state` on an evidence row is a provenance claim — "this is what a
    customer in Nevada sees". If no exit actually comes out in that state,
    the honest options are to route there or to say so. Fetching from the
    host's own location (or from a different state's exit) and writing "NV"
    on it is neither, so it is not offered.
    """
    return ToolResult(
        success=False,
        error=(
            f"No network exit for geo_state={geo_state}. Add a proxy.pool entry "
            f"for {geo_state}, or — if the single proxy is pinned to that state "
            f"(e.g. an IPRoyal password ending _state-…) — declare it with "
            f"`proxy.state: {geo_state}` in config.yaml. Refusing to collect from "
            "the host's own location and stamp the evidence with a state it was "
            "not observed from. Omit geo_state to observe without a state claim."
        ),
    )


class WatchObserveTool(_WatchToolBase):
    """Collect evidence from public pages — every claim proof-checked."""

    def __init__(self) -> None:
        super().__init__()
        self._router: Any = None
        self._config: Any = None
        self._browser_manager: Any = None

    @property
    def name(self) -> str:
        return "watch_observe"

    @property
    def description(self) -> str:
        return (
            "Collect evidence about a tracked brand automatically: fetches the "
            "brand's public pages, extracts facts for the given dimension, and "
            "files them in the evidence register. Every claim must quote the "
            "source verbatim and the quote is CHECKED against the fetched page "
            "— unverifiable claims are discarded, not saved. Falls back to the real "
            "browser when a site is a JS app or blocks plain requests. "
            "Public/logged-out pages only; anything behind an account is "
            "operator-collected."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Brand name."},
                "dimension": {"type": "string", "description": "Dimension name."},
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Pages to read. Defaults to the brand's homepage.",
                },
                "geo_state": {
                    "type": "string",
                    "description": (
                        "US state to observe as. Uses the matching proxy exit "
                        "from proxy.pool when configured."
                    ),
                },
                "customer_state": {
                    "type": "string",
                    "enum": ["logged_out", "registered", "verified", "purchaser", "redeemer", "vip"],
                    "description": (
                        "What the browser session actually IS while reading — "
                        "'logged_out' (default) or the account state you are "
                        "logged in as. Stamped on every row: never claim a "
                        "logged-in state you are not in. Site credentials live "
                        "in the vault (vault_lookup <domain>)."
                    ),
                },
                "max_claims": {
                    "type": "integer",
                    "description": "Per page. Default 8.",
                },
                "company_id": {"type": "string"},
            },
            "required": ["subject", "dimension"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        if self._router is None:
            return ToolResult(
                success=False,
                error="watch_observe needs a model to read pages (router not injected)",
            )
        from core.watch_observe import (
            extract_claims,
            fetch_page_best_effort,
            filter_verified_claims,
        )

        cid = _company(params)
        wm = self._watch_manager
        subj = await wm.get_subject_by_name(str(params.get("subject") or ""), cid)
        if subj is None:
            return ToolResult(success=False, error=f"no such brand: {params.get('subject')!r}")
        dim = await wm.get_dimension_by_name(str(params.get("dimension") or ""), cid)
        if dim is None:
            return ToolResult(
                success=False, error=f"no such dimension: {params.get('dimension')!r}"
            )

        urls = [str(u) for u in (params.get("urls") or []) if str(u).strip()]
        if not urls:
            if not subj.url:
                return ToolResult(
                    success=False,
                    error=f"{subj.name} has no URL — pass urls, or set one via watch_subject",
                )
            urls = [subj.url]

        geo_state = str(params.get("geo_state") or "n/a")
        customer_state = str(params.get("customer_state") or "logged_out")
        if customer_state not in VALID_CUSTOMER_STATES:
            return ToolResult(
                success=False,
                error=(
                    f"invalid customer_state {customer_state!r} — one of "
                    f"{', '.join(VALID_CUSTOMER_STATES)}"
                ),
            )
        proxy_url = None
        if self._config is not None and getattr(self._config, "proxy", None):
            proxy_url = self._config.proxy.request_proxy_url(geo_state) or None
        if geo_state != "n/a" and not proxy_url:
            return _no_exit_for_state(geo_state)

        # A state stamp is proven, not assumed: pin one exit and check its
        # geolocation before anything is fetched, then fetch through the
        # pinned session so the proof binds the pages it covers.
        exit_info: dict[str, Any] = {}
        if geo_state != "n/a" and proxy_url:
            from core.watch_observe import verify_exit_state

            ok, proxy_url, exit_info = await verify_exit_state(proxy_url, geo_state)
            if not ok:
                return _exit_not_verified(geo_state, exit_info)
        http_exit_ip = str(exit_info.get("ip") or "")

        subcriteria = [str(s.get("name", "")) for s in dim.subcriteria if s.get("name")]
        max_claims = int(params.get("max_claims") or 8)

        written = 0
        rejected_total = 0
        page_reports: list[dict[str, Any]] = []
        # Browser-escalated pages exit through Chrome's own credentials, not
        # the verified session — a different address. Checked once, lazily,
        # the first time a page actually escalates; None = not yet checked.
        browser_exit: dict[str, Any] | None = None

        for url in urls[:5]:
            text, fetch_err, method = await fetch_page_best_effort(
                url, browser_manager=self._browser_manager, proxy_url=proxy_url
            )
            if fetch_err or not text:
                page_reports.append({"url": url, "error": fetch_err or "no readable text"})
                continue
            page_exit_ip = http_exit_ip
            if geo_state != "n/a" and method == "browser":
                if browser_exit is None:
                    from core.watch_observe import verify_browser_exit

                    b_ok, b_detail = await verify_browser_exit(self._browser_manager, geo_state)
                    browser_exit = {"ok": b_ok, **b_detail}
                if not browser_exit.get("ok"):
                    page_reports.append(
                        {
                            "url": url,
                            "method": method,
                            "error": (
                                f"page needed the browser, but Chrome's exit is "
                                f"not verified in {geo_state} "
                                f"({browser_exit.get('state_code') or browser_exit.get('error', 'unknown')}) "
                                "— page skipped so the state stamp stays true"
                            ),
                        }
                    )
                    continue
                page_exit_ip = str(browser_exit.get("ip") or "")
            claims = await extract_claims(
                self._router,
                page_text=text,
                dimension_name=dim.name,
                subcriteria=subcriteria,
                max_claims=max_claims,
            )
            verified, rejected = filter_verified_claims(claims, text)
            rejected_total += len(rejected)
            for c in verified:
                await wm.add_evidence(
                    company_id=cid,
                    subject_id=subj.subject_id,
                    dimension_id=dim.dimension_id,
                    subcriterion=str(c.get("subcriterion") or ""),
                    claim=str(c.get("claim") or "")[:1000],
                    value_text=str(c.get("value_text") or "")[:300],
                    source_url=url,
                    source_type="site",
                    geo_state=geo_state,
                    customer_state=customer_state,
                    # Quoted from a live page and substring-verified: solid on
                    # provenance, but a marketing page is still the brand
                    # talking about itself — hence medium, not high.
                    confidence="medium",
                    excerpt=str(c.get("excerpt") or "")[:1000],
                    collector="agent",
                    exit_ip=page_exit_ip,
                )
                written += 1
            page_reports.append(
                {
                    "url": url,
                    "method": method,
                    "chars": len(text),
                    "proposed": len(claims),
                    "verified": len(verified),
                    "rejected": len(rejected),
                    "rejections": [r["reason"] for r in rejected[:3]],
                }
            )

        return ToolResult(
            success=True,
            data={
                "subject": subj.name,
                "dimension": dim.name,
                "geo_state": geo_state,
                "proxied": bool(proxy_url),
                "exit": exit_info or None,
                "evidence_written": written,
                "claims_rejected": rejected_total,
                "pages": page_reports,
                "note": (
                    "Claims are only saved when their verbatim excerpt is found "
                    "in the fetched page. Score with watch_score once coverage "
                    "is adequate."
                ),
            },
        )


class WatchAnalyzeTool(_WatchToolBase):
    """One command: read a brand, score every dimension, save the deliverables."""

    def __init__(self) -> None:
        super().__init__()
        self._router: Any = None
        self._vault: Any = None  # for search-driven source expansion
        self._config: Any = None
        self._browser_manager: Any = None

    @property
    def group(self) -> str:
        return "watch"

    @property
    def name(self) -> str:
        return "watch_analyze"

    @property
    def description(self) -> str:
        return (
            "Run a FULL competitor analysis on one brand end to end: reads its "
            "site (landing page plus terms / promotions / payments pages, using "
            "the real browser when a site is a JS app or blocks requests), files "
            "every verifiable fact into the evidence register, scores each "
            "dimension it has evidence for, and saves the pack: scorecard "
            "workbook, board report and executive deck (.pptx). Use this when "
            "asked to 'do a competitor analysis on "
            "X' or 'analyse X and save the results'. Dimensions with no evidence "
            "are left unscored rather than guessed."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Brand to analyse (must be tracked, or pass url).",
                },
                "url": {
                    "type": "string",
                    "description": "Homepage — needed only if the brand isn't tracked yet.",
                },
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Explicit pages to read instead of auto-discovering.",
                },
                "dimensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Limit to these dimensions. Default: all.",
                },
                "out_dir": {
                    "type": "string",
                    "description": "Where to save the workbook, report and deck. Default ~/Desktop.",
                },
                "geo_state": {
                    "type": "string",
                    "description": "Observe as this US state.",
                },
                "customer_state": {
                    "type": "string",
                    "enum": ["logged_out", "registered", "verified", "purchaser", "redeemer", "vip"],
                    "description": (
                        "What the browser session actually IS while reading — "
                        "'logged_out' (default) or the account state you are "
                        "logged in as. Stamped on every row: never claim a "
                        "logged-in state you are not in. Site credentials live "
                        "in the vault (vault_lookup <domain>)."
                    ),
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Pages to read. Default 4.",
                },
                "save": {
                    "type": "boolean",
                    "description": "Write the deliverables to disk. Default true.",
                },
                "deck": {
                    "type": "boolean",
                    "description": (
                        "Also write the executive presentation (.pptx). Default "
                        "true — it is part of the pack. Set false to skip it."
                    ),
                },
                "expand_sources": {
                    "type": "boolean",
                    "description": (
                        "When the brand's own site leaves dimensions without "
                        "evidence, search the web for third-party sources "
                        "(reviews, help centers) and read those too. Default "
                        "true; needs the search_sh_api_key vault entry."
                    ),
                },
                "baseline": {
                    "type": "boolean",
                    "description": (
                        "The saved pack establishes a baseline (from-scratch "
                        "analysis) — no diff against prior snapshots. Default false."
                    ),
                },
                "company_id": {"type": "string"},
            },
            "required": ["subject"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    def _exhibit_dir(self, brand: str) -> Any:
        """``<workspace>/watch-screenshots/<brand-slug>/`` — None when no
        workspace is configured (exhibits then simply are not filed)."""
        from pathlib import Path

        ws = str(getattr(self._config, "workspace", "") or "").strip()
        if not ws:
            return None
        root = Path(ws).expanduser()
        if not root.is_absolute():
            root = Path(getattr(self._config, "project_root", Path.cwd())) / root
        slug = "".join(ch if ch.isalnum() else "-" for ch in brand.lower()).strip("-") or "brand"
        d = root / "watch-screenshots" / slug
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        if self._router is None:
            return ToolResult(
                success=False, error="watch_analyze needs a model (router not injected)"
            )
        from core.watch_observe import (
            collect_pages,
            extract_claims_multi,
            filter_verified_claims,
            score_dimension,
        )

        cid = _company(params)
        wm = self._watch_manager
        name = str(params.get("subject") or "").strip()

        subj = await wm.get_subject_by_name(name, cid)
        if subj is None:
            url = str(params.get("url") or "").strip()
            if not url:
                known = [s.name for s in await wm.list_subjects(cid)]
                return ToolResult(
                    success=False,
                    error=(
                        f"{name!r} is not tracked. Pass url= to add it, or pick "
                        f"one of: {known[:14]}"
                    ),
                )
            # Auto-add is an OPERATOR convenience. In autonomous contexts
            # (goal, mind, scheduled) the register is read-only canon: it is
            # a customer deliverable, and a plan that quietly grows it
            # changes every ranking in the pack. 2026-08-15: a goal executor
            # "completing the canon" invented two brands the customer never
            # asked to track. Prompt rules discourage it; this refuses it.
            from core.execution_context import current_context

            if not current_context().is_user_input:
                known = [s.name for s in await wm.list_subjects(cid)]
                return ToolResult(
                    success=False,
                    error=(
                        f"{name!r} is not in the register, and autonomous "
                        "runs may not add brands — the register is canon. "
                        f"Analyze one of: {known[:14]}. Only the operator "
                        "adds brands (watch_subject)."
                    ),
                )
            subj = await wm.add_subject(name=name, company_id=cid, url=url)

        dimensions = await wm.list_dimensions(cid)
        if not dimensions:
            return ToolResult(
                success=False,
                error=(
                    "no scoring dimensions defined — seed a frame first, e.g. "
                    "watch_dimension action='seed' pack='social_casino_t1'"
                ),
            )
        wanted = {d.lower() for d in (params.get("dimensions") or [])}
        if wanted:
            dimensions = [d for d in dimensions if d.name.lower() in wanted]
            if not dimensions:
                return ToolResult(success=False, error="no matching dimensions")

        geo_state = str(params.get("geo_state") or "n/a")
        customer_state = str(params.get("customer_state") or "logged_out")
        if customer_state not in VALID_CUSTOMER_STATES:
            return ToolResult(
                success=False,
                error=(
                    f"invalid customer_state {customer_state!r} — one of "
                    f"{', '.join(VALID_CUSTOMER_STATES)}"
                ),
            )
        proxy_url = None
        if self._config is not None and getattr(self._config, "proxy", None):
            proxy_url = self._config.proxy.request_proxy_url(geo_state) or None
        if geo_state != "n/a" and not proxy_url:
            return _no_exit_for_state(geo_state)

        # Prove the exit before reading anything; fetch through the session
        # that passed. See watch_observe — same rule, same reasons.
        exit_info: dict[str, Any] = {}
        if geo_state != "n/a" and proxy_url:
            from core.watch_observe import verify_exit_state

            ok, proxy_url, exit_info = await verify_exit_state(proxy_url, geo_state)
            if not ok:
                return _exit_not_verified(geo_state, exit_info)
        http_exit_ip = str(exit_info.get("ip") or "")

        # ── 1. Read the site ──
        explicit = [str(u) for u in (params.get("urls") or []) if str(u).strip()]
        max_pages = int(params.get("max_pages") or 4)
        if explicit:
            pages = []
            from core.watch_observe import fetch_page_best_effort

            for u in explicit[:max_pages]:
                t, e, m = await fetch_page_best_effort(
                    u, browser_manager=self._browser_manager, proxy_url=proxy_url
                )
                pages.append({"url": u, "text": t, "error": e, "method": m})
        else:
            if not subj.url:
                return ToolResult(success=False, error=f"{subj.name} has no URL — pass url or urls")
            pages = await collect_pages(
                subj.url,
                browser_manager=self._browser_manager,
                proxy_url=proxy_url,
                max_pages=max_pages,
            )

        # Browser-escalated pages exit through Chrome's credentials, not the
        # verified session. One check covers them all; failing it drops those
        # pages from a state-stamped run rather than stamping them falsely.
        browser_exit: dict[str, Any] = {}
        if geo_state != "n/a" and any(
            str(p.get("method") or "").startswith("browser") for p in pages
        ):
            from core.watch_observe import verify_browser_exit

            b_ok, b_detail = await verify_browser_exit(self._browser_manager, geo_state)
            browser_exit = {"ok": b_ok, **b_detail}
            if not b_ok:
                dropped = [p for p in pages if str(p.get("method") or "").startswith("browser")]
                pages = [p for p in pages if not str(p.get("method") or "").startswith("browser")]
                for p_ in dropped:
                    pages.append(
                        {
                            "url": p_.get("url"),
                            "text": "",
                            "method": p_.get("method"),
                            "error": (
                                f"browser exit not verified in {geo_state} "
                                f"({b_detail.get('state_code') or b_detail.get('error', 'unknown')}) "
                                "— page dropped so the state stamp stays true"
                            ),
                        }
                    )

        readable = [p for p in pages if p.get("text")]
        # An unreadable site is not the end of the brand — it is the case
        # source expansion exists for. The early return here used to run
        # BEFORE expansion, so the brands that most needed third-party
        # sources (bot-walled, browser exit unverifiable) were exactly the
        # ones that never got them. Now the run continues into expansion
        # with every dimension missing, and only fails if that finds
        # nothing either.
        site_unreadable = not readable
        site_error = (
            f"could not read any page for {subj.name}: "
            f"{[p.get('error') for p in pages]}. The site may need the "
            "browser (is Chrome available?) or an explicit urls list."
        )

        # ── 1c. Storefront exhibits ──
        # A clean screenshot of what a visitor actually sees, filed beside
        # the claims it supports. Captured only through a browser whose exit
        # is verified in the claimed state — an out-of-state storefront is a
        # different product, not an exhibit.
        shots: dict[str, str] = {}
        shots_note = ""
        # ``screenshots`` is deliberately NOT in the input schema. It existed
        # there for one evening — and the first goal-driven run under time
        # pressure turned it off ("do only the remainder") and shipped a pack
        # with no exhibits. Exhibits are part of collection, not an option
        # the model weighs against the clock; the kwarg survives for
        # programmatic callers and tests only.
        if self._browser_manager is None:
            shots_note = "skipped — no browser available"
        elif not params.get("screenshots", True):
            shots_note = "disabled by caller"
        if params.get("screenshots", True) and self._browser_manager is not None:
            from core.watch_observe import rank_exhibit_pages

            # Home, then the promotions page, then one more product page —
            # never a privacy policy or terms page as the brand's exhibit.
            targets: list[str] = rank_exhibit_pages(
                [{"url": p_.get("url"), "title": p_.get("title")} for p_ in readable],
                home_url=str(subj.url or ""),
                limit=3,
            )
            if targets:
                allowed = True
                if geo_state != "n/a":
                    if not browser_exit:
                        from core.watch_observe import verify_browser_exit

                        b_ok, b_detail = await verify_browser_exit(self._browser_manager, geo_state)
                        browser_exit = {"ok": b_ok, **b_detail}
                    allowed = bool(browser_exit.get("ok"))
                    if not allowed:
                        shots_note = f"skipped — browser exit not verified in {geo_state}"
                shot_dir = self._exhibit_dir(subj.name) if allowed else None
                if allowed and shot_dir is None:
                    allowed = False
                    shots_note = "skipped — no workspace configured"
                if allowed and shot_dir is not None:
                    from core.watch_observe import (
                        capture_page_screenshot,
                        screenshot_filename,
                    )

                    for u in targets:
                        out = shot_dir / screenshot_filename(u)
                        got = await capture_page_screenshot(self._browser_manager, u, str(out))
                        if got:
                            shots[u] = got
                    if not shots and not shots_note:
                        shots_note = "capture failed on every page"
        import logging

        logging.getLogger(__name__).info(
            "watch exhibits for %s: %s",
            subj.name,
            shots_note or f"{len(shots)} captured",
        )

        # ── 2. Extract + verify, one model call per page across all dimensions ──
        dim_specs = [
            {
                "name": d.name,
                "subcriteria": [str(s.get("name", "")) for s in d.subcriteria if s.get("name")],
            }
            for d in dimensions
        ]
        by_name = {d.name: d for d in dimensions}
        written = 0
        rejected_total = 0
        site_covered: set[str] = set()
        page_reports: list[dict[str, Any]] = []

        for page in readable:
            page_text = page.get("text")
            if not isinstance(page_text, str) or not page_text:
                continue
            claims = await extract_claims_multi(
                self._router, page_text=page_text, dimensions=dim_specs
            )
            verified, rejected = filter_verified_claims(claims, page_text)
            rejected_total += len(rejected)
            for c in verified:
                dim = by_name.get(str(c.get("dimension")))
                if dim is None:
                    continue
                site_covered.add(dim.dimension_id)
                await wm.add_evidence(
                    company_id=cid,
                    subject_id=subj.subject_id,
                    dimension_id=dim.dimension_id,
                    subcriterion=str(c.get("subcriterion") or ""),
                    claim=str(c.get("claim") or "")[:1000],
                    value_text=str(c.get("value_text") or "")[:300],
                    source_url=page["url"],
                    source_type="site",
                    geo_state=geo_state,
                    customer_state=customer_state,
                    confidence="medium",
                    excerpt=str(c.get("excerpt") or "")[:1000],
                    screenshot_path=shots.get(str(page.get("url") or ""), ""),
                    collector="agent",
                    exit_ip=(
                        str(browser_exit.get("ip") or "")
                        if str(page.get("method") or "").startswith("browser")
                        else http_exit_ip
                    ),
                )
                written += 1
            page_reports.append(
                {
                    "url": page["url"],
                    "method": page.get("method"),
                    "chars": len(page_text),
                    "verified": len(verified),
                    "rejected": len(rejected),
                }
            )

        # ── 2b. Expand sources where the brand's own site said nothing ──
        # The site is the primary source; for dimensions it left silent, look
        # where the facts actually live — reviews, help centers, app stores —
        # found by search, fetched through the SAME verified session, held to
        # the same verbatim-excerpt gate. A brand that hides its terms is not
        # a brand we score blind; it is a brand we read about elsewhere.
        expansion_report: dict[str, Any] = {}
        if params.get("expand_sources", True):
            covered = site_covered
            evidenced = {
                e.dimension_id for e in await wm.list_evidence(cid, subject_id=subj.subject_id)
            }
            missing = [d.name for d in dimensions if d.dimension_id not in (covered | evidenced)]
            api_key = None
            if self._vault is not None:
                try:
                    api_key = self._vault.get("search_sh_api_key")
                except Exception:
                    api_key = None
            if missing and not api_key:
                expansion_report = {
                    "attempted": False,
                    "missing_dimensions": missing,
                    "note": "no search_sh_api_key in vault — expansion skipped",
                }
            elif missing:
                from core.watch_observe import (
                    expansion_queries,
                    fetch_page_best_effort,
                    pick_expansion_urls,
                    search_web,
                )

                fetched = {str(pr.get("url") or "") for pr in pages}
                results: list[dict[str, str]] = []
                queries = expansion_queries(subj.name, missing)
                search_key = str(api_key)
                for q in queries:
                    results.extend(await search_web(q, api_key=search_key))
                extra_urls = pick_expansion_urls(results, already_fetched=fetched, limit=4)
                exp_written = 0
                exp_pages: list[dict[str, Any]] = []
                for url in extra_urls:
                    text, fetch_err, method = await fetch_page_best_effort(
                        url,
                        browser_manager=self._browser_manager,
                        proxy_url=proxy_url,
                    )
                    if fetch_err or not text:
                        exp_pages.append({"url": url, "error": fetch_err})
                        continue
                    claims = await extract_claims_multi(
                        self._router,
                        page_text=text,
                        dimensions=[d for d in dim_specs if d["name"] in missing],
                    )
                    verified, _rej = filter_verified_claims(claims, text)
                    for c in verified:
                        dim = by_name.get(str(c.get("dimension")))
                        if dim is None:
                            continue
                        await wm.add_evidence(
                            company_id=cid,
                            subject_id=subj.subject_id,
                            dimension_id=dim.dimension_id,
                            subcriterion=str(c.get("subcriterion") or ""),
                            claim=str(c.get("claim") or "")[:1000],
                            value_text=str(c.get("value_text") or "")[:300],
                            source_url=url,
                            # Third-party pages: real provenance, lower
                            # authority than the brand's own words.
                            source_type="third_party",
                            geo_state=geo_state,
                            # A third-party page is the same for everyone —
                            # the session state of OUR browser says nothing
                            # about it, so it is never stamped logged-in.
                            customer_state="logged_out",
                            confidence="low",
                            excerpt=str(c.get("excerpt") or "")[:1000],
                            collector="agent",
                            exit_ip=(
                                str(browser_exit.get("ip") or "")
                                if method == "browser"
                                else http_exit_ip
                            ),
                        )
                        exp_written += 1
                    exp_pages.append({"url": url, "method": method, "verified": len(verified)})
                written += exp_written
                expansion_report = {
                    "attempted": True,
                    "missing_dimensions": missing,
                    "queries": queries,
                    "pages": exp_pages,
                    "evidence_written": exp_written,
                }

        if site_unreadable and written == 0:
            exp_note = ""
            if expansion_report.get("attempted"):
                exp_note = (
                    " Source expansion searched "
                    f"{len(expansion_report.get('queries', []))} queries and "
                    "found no verifiable third-party claims either."
                )
            elif expansion_report.get("note"):
                exp_note = f" Source expansion: {expansion_report['note']}."
            return ToolResult(
                success=False,
                data={"source_expansion": expansion_report or None},
                error=site_error + exp_note,
            )

        # ── 3. Score what the evidence supports ──
        scored: list[dict[str, Any]] = []
        unscored: list[str] = []
        for dim in dimensions:
            own = await wm.list_evidence(
                cid, subject_id=subj.subject_id, dimension_id=dim.dimension_id
            )
            if not own:
                unscored.append(dim.name)
                continue
            # Peer evidence makes the 1-5 judgement comparative instead of a
            # guess in isolation; absent peers, the model is told to say so.
            peers: dict[str, list[str]] = {}
            for other in await wm.list_subjects(cid):
                if other.subject_id == subj.subject_id:
                    continue
                rows = await wm.list_evidence(
                    cid, subject_id=other.subject_id, dimension_id=dim.dimension_id
                )
                if rows:
                    peers[other.name] = [r.claim for r in rows[:10]]
            judged = await score_dimension(
                self._router,
                dimension_name=dim.name,
                subcriteria=[str(s.get("name", "")) for s in dim.subcriteria if s.get("name")],
                own_claims=[r.claim for r in own],
                peer_claims=peers,
            )
            if judged is None or judged.get("score") is None:
                await wm.set_score(
                    company_id=cid,
                    subject_id=subj.subject_id,
                    dimension_id=dim.dimension_id,
                    score=None,
                    rationale=(judged or {}).get("rationale", "evidence too thin"),
                    scored_by="agent",
                )
                unscored.append(dim.name)
                continue
            res = await wm.set_score(
                company_id=cid,
                subject_id=subj.subject_id,
                dimension_id=dim.dimension_id,
                score=judged["score"],
                rationale=judged.get("rationale", ""),
                scored_by="agent",
            )
            scored.append(
                {
                    "dimension": dim.name,
                    "score": res.score,
                    "coverage_pct": res.coverage_pct,
                    "provisional": judged.get("provisional", False),
                    "rationale": judged.get("rationale", ""),
                }
            )

        # ── 4. Save the deliverables ──
        saved: dict[str, str] = {}
        if params.get("save", True):
            from pathlib import Path

            out_dir = Path(str(params.get("out_dir") or "~/Desktop")).expanduser()
            out_dir.mkdir(parents=True, exist_ok=True)
            slug = "".join(ch if ch.isalnum() else "-" for ch in subj.name.lower()).strip("-")
            try:
                from core.watch_xlsx import render_scorecard_xlsx

                saved["scorecard"] = render_scorecard_xlsx(
                    await wm.scorecard(cid),
                    dimensions=await wm.list_dimensions(cid),
                    evidence=await wm.evidence_with_names(cid),
                    staleness=await wm.staleness(cid),
                    path=out_dir / f"competitor-scorecard-{slug}.xlsx",
                    title=f"Competitive Scorecard — {subj.name}",
                )
            except Exception as e:
                saved["scorecard_error"] = str(e)

            report_tool = WatchBoardReportTool()
            report_tool._watch_manager = wm
            report_tool._router = self._router
            report_tool._config = self._config
            rep_params: dict[str, Any] = {
                "company_id": cid,
                "path": str(out_dir / f"competitor-report-{slug}.md"),
                "take_snapshot": True,
                "baseline": bool(params.get("baseline", False)),
            }
            want_deck = bool(params.get("deck", True))
            rep_params["deck"] = want_deck
            if want_deck:
                rep_params["deck_path"] = str(out_dir / f"competitor-deck-{slug}.pptx")
            rep = await report_tool.execute(rep_params)
            if rep.success:
                saved["report"] = rep.data.get("path") or ""
                if want_deck:
                    if rep.data.get("deck_path"):
                        saved["deck"] = rep.data["deck_path"]
                    if rep.data.get("deck_error"):
                        saved["deck_error"] = rep.data["deck_error"]

        return ToolResult(
            success=True,
            data={
                "subject": subj.name,
                "pages_read": len(readable),
                "exit": exit_info or None,
                "source_expansion": expansion_report or None,
                "pages": page_reports,
                "evidence_written": written,
                "claims_rejected": rejected_total,
                "dimensions_scored": len(scored),
                "dimensions_unscored": len(unscored),
                "scores": scored,
                "unscored": unscored,
                "screenshots": (
                    {
                        "captured": len(shots),
                        "paths": sorted(shots.values()),
                        **({"note": shots_note} if shots_note else {}),
                    }
                    if (shots or shots_note)
                    else None
                ),
                "saved": saved,
                "note": (
                    "Every saved fact quotes its source and was checked against "
                    "the live page. Unscored dimensions had no supporting "
                    "evidence on the pages read — that is a coverage gap, not a "
                    "weakness of the brand."
                ),
            },
        )


class WatchQueueTool(_WatchToolBase):
    """What needs re-observing, and the schedules that drive it."""

    def __init__(self) -> None:
        super().__init__()
        self._scheduler: Any = None

    @property
    def name(self) -> str:
        return "watch_queue"

    @property
    def description(self) -> str:
        return (
            "The competitive-intelligence refresh queue: which brand × "
            "dimension pairs have never been observed or are overdue against "
            "their cadence (promotional weekly, operational monthly, financial "
            "quarterly), most urgent first. action='schedule' installs the "
            "recurring weekly/monthly/quarterly refresh jobs."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "schedule"]},
                "voice": {
                    "type": "boolean",
                    "description": "schedule: also install the weekly voice-of-customer collection. Default true.",
                },
                "service": {
                    "type": "boolean",
                    "description": (
                        "schedule: also install the weekly service — Friday brief, daily "
                        "market pulse, 6-hourly alert check. Default true."
                    ),
                },
                "cadence": {
                    "type": "string",
                    "enum": ["weekly", "monthly", "quarterly"],
                    "description": "Only show pairs on this cadence.",
                },
                "limit": {"type": "integer", "description": "Default 25."},
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        cid = _company(params)
        action = str(params.get("action") or "list").lower()

        if action == "schedule":
            if self._scheduler is None:
                return ToolResult(
                    success=False, error="scheduler unavailable — cannot install jobs"
                )
            crons = {
                "weekly": "0 9 * * 1",
                "monthly": "0 9 1 * *",
                "quarterly": "0 9 1 1,4,7,10 *",
            }
            existing = {s.name: s.id for s in await self._scheduler.list_schedules()}
            created: list[str] = []
            for cadence, cron in crons.items():
                name = f"Competitive refresh · {cadence}"
                if name in existing:
                    await self._scheduler.delete_schedule(existing[name])
                await self._scheduler.create_schedule(
                    name=name,
                    task_goal=(
                        f"Refresh the {cadence} competitive-intelligence "
                        f"dimensions for {cid}. Call watch_queue with "
                        f"cadence={cadence} to see what is due, then "
                        f"watch_observe each pair, then watch_score the ones "
                        f"that now have enough evidence. Do not invent facts."
                    ),
                    cron_expression=cron,
                    description="Auto-created by watch_queue action=schedule",
                    company_id=cid,
                )
                created.append(f"{name} ({cron})")
            # Voice of customer rides its own weekly cadence (docs/87): a
            # week of posts is a readable batch, and the monthly pack then
            # has four weeks behind its 30-day window.
            if bool(params.get("voice", True)):
                name = "Voice of customer · weekly"
                if name in existing:
                    await self._scheduler.delete_schedule(existing[name])
                await self._scheduler.create_schedule(
                    name=name,
                    task_goal=(
                        f"Collect voice of customer for every active brand of {cid}: "
                        "call watch_voice_collect (all subjects, sources reddit + "
                        "app_store, window_days=14). Do not add or archive brands; do "
                        "not score anything — this is what players say, filed apart."
                    ),
                    cron_expression="0 8 * * 3",
                    description="Auto-created by watch_queue action=schedule",
                    company_id=cid,
                )
                created.append(f"{name} (0 8 * * 3)")
            if bool(params.get("service", True)):
                # Sessions expire; the agent refreshes them itself. The
                # 12h cooldown inside watch_login means a brand that is
                # already signed in costs nothing here.
                name = "Site sessions · weekly"
                if name in existing:
                    await self._scheduler.delete_schedule(existing[name])
                try:
                    await self._scheduler.create_schedule(
                        name=name,
                        task_goal=(
                            f"Refresh the signed-in sessions for {cid}: call watch_login "
                            "(all brands). Report the verdicts; do NOT retry a brand the "
                            "tool reports from cache, and do not attempt a brand twice in "
                            "one run — repeated failures lock accounts. Brands that come "
                            "back 'rejected' need their stored credentials checked by the "
                            "operator; 'challenge' means an anti-bot puzzle, leave it."
                        ),
                        cron_expression="0 5 * * 1",
                        description="Auto-created by watch_queue action=schedule",
                        company_id=cid,
                    )
                    created.append(f"{name} (0 5 * * 1)")
                except Exception as e:
                    created.append(f"{name} FAILED: {e}")
                name = "Raw catalog · weekly"
                if name in existing:
                    await self._scheduler.delete_schedule(existing[name])
                try:
                    await self._scheduler.create_schedule(
                        name=name,
                        task_goal=(
                            f"Refresh the raw inventory for {cid}: call watch_catalog_collect "
                            "for every brand (research=true, sign_in_if_missing=true). It "
                            "reads the brands' own public pages and the open web first — no "
                            "session, no metered exit. Only if the receipt lists "
                            "needs_sign_in entries, run watch_login for those brands and "
                            "re-run watch_catalog_collect for them with the matching "
                            "customer_state. Do not add or archive brands; do not score."
                        ),
                        cron_expression="30 5 * * 1",
                        description="Auto-created by watch_queue action=schedule",
                        company_id=cid,
                    )
                    created.append(f"{name} (30 5 * * 1)")
                except Exception as e:
                    created.append(f"{name} FAILED: {e}")
                name = "Regulatory tracking · weekly"
                if name in existing:
                    await self._scheduler.delete_schedule(existing[name])
                await self._scheduler.create_schedule(
                    name=name,
                    task_goal=(
                        f"Weekly regulatory tracking for {cid}: call watch_regulatory_collect "
                        "for the priority states, then watch_alerts action=check. Do not add "
                        "or archive brands; this is third-party regulatory news, not legal advice."
                    ),
                    cron_expression="0 6 * * 2",
                    description="Auto-created by watch_queue action=schedule",
                    company_id=cid,
                )
                created.append(f"{name} (0 6 * * 2)")
            if bool(params.get("service", True)):
                # Agent task, not direct_tool: the scheduler refuses the
                # direct path for non-SAFE tools (watch_comms_collect is
                # MODERATE), and on 2026-08-20 that refusal aborted the whole
                # schedule call before the brief/pulse/alert schedules were
                # created. Every creation below is also independent now.
                name = "Player comms · weekly"
                if name in existing:
                    await self._scheduler.delete_schedule(existing[name])
                try:
                    await self._scheduler.create_schedule(
                        name=name,
                        task_goal=(
                            f"Collect this week's player comms for {cid}: call "
                            "watch_comms_collect for all brands with a linked inbox. "
                            "Do not add or archive brands; do not score anything."
                        ),
                        cron_expression="0 7 * * 4",
                        description="Auto-created by watch_queue action=schedule",
                        company_id=cid,
                    )
                    created.append(f"{name} (0 7 * * 4)")
                except Exception as e:
                    created.append(f"{name} FAILED: {e}")
            # The weekly service (docs/88): the Friday brief, the daily market
            # pulse that keeps alerts fresh, and the 6-hourly alert check —
            # the last one a direct tool call, no LLM in the loop.
            if bool(params.get("service", True)):
                for name, cron, goal, direct in (
                    (
                        "Weekly executive brief",
                        "0 7 * * 5",
                        (
                            f"Write this week's competitive brief for {cid}: call "
                            "watch_weekly_brief with a path under the workspace "
                            "(weekly-brief-<date>/brief.md) and notify=true. If an "
                            "executive request was received this week, research it "
                            "with the watch tools and pass request/answer. Do not add "
                            "or archive brands."
                        ),
                        None,
                    ),
                    (
                        "Daily market pulse",
                        "0 6 * * *",
                        (
                            f"Daily market pulse for {cid}: for every active brand in "
                            "the register call watch_analyze with max_pages=1, "
                            "expand_sources=false, deck=false, save=false (homepage "
                            "only — market events and offer changes surface here). "
                            "Do not add or archive brands."
                        ),
                        None,
                    ),
                    (
                        "Competitive alerts check",
                        "30 */6 * * *",
                        "Check competitive alerts and push new ones.",
                        ("watch_alerts", {"action": "check", "notify": True, "company_id": cid}),
                    ),
                ):
                    if name in existing:
                        await self._scheduler.delete_schedule(existing[name])
                    try:
                        await self._scheduler.create_schedule(
                            name=name,
                            task_goal=goal,
                            cron_expression=cron,
                            description="Auto-created by watch_queue action=schedule",
                            company_id=cid,
                            direct_tool=direct[0] if direct else None,
                            direct_params=direct[1] if direct else None,
                        )
                        created.append(f"{name} ({cron})")
                    except Exception as e:
                        created.append(f"{name} FAILED: {e}")
            return ToolResult(success=True, data={"schedules": created})

        gaps = await self._watch_manager.staleness(cid)
        cadence = str(params.get("cadence") or "").lower()
        if cadence:
            gaps = [g for g in gaps if g.get("cadence") == cadence]
        # Never-observed first, then the most overdue.
        gaps.sort(
            key=lambda g: (
                g["status"] != "never_observed",
                -(g.get("age_days") or 0),
            )
        )
        limit = int(params.get("limit") or 25)
        return ToolResult(
            success=True,
            data={
                "due_count": len(gaps),
                "never_observed": sum(1 for g in gaps if g["status"] == "never_observed"),
                "stale": sum(1 for g in gaps if g["status"] == "stale"),
                "queue": gaps[:limit],
            },
        )


# ── Voice of customer (docs/87): what players say, beside the pack ─────


class WatchVoiceCollectTool(_WatchToolBase):
    """Collect what players say about tracked brands — Reddit, App Store —
    into the organ's second evidence class. Never touches scores."""

    def __init__(self) -> None:
        super().__init__()
        self._router: Any = None
        self._config: Any = None
        self._vault: Any = None  # optional reddit_client_id / reddit_client_secret
        self._browser_manager: Any = None  # Reddit's public JSON via real Chrome

    @property
    def name(self) -> str:
        return "watch_voice_collect"

    @property
    def description(self) -> str:
        return (
            "Voice of customer: collect what PLAYERS say about one tracked brand "
            "(or all active brands) from public sources — Reddit posts/comments "
            "and App Store reviews — read each post for theme and sentiment, and "
            "file short verbatim quotes in watch_voice. Opinion, kept apart from "
            "the evidence register: nothing here changes a score or the pack; "
            "the deck and report pick it up as 'What players say' when present. "
            "Usernames/links are stripped, affiliate posts dropped, cross-posts "
            "counted once. Register is canon: collects only for existing subjects."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Brand name from the register. Omit for all active brands.",
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["reddit", "app_store"]},
                    "description": "Default: reddit + app_store.",
                },
                "window_days": {"type": "integer", "description": "Default 30."},
                "max_posts": {"type": "integer", "description": "Per brand per source. Default 200."},
                "save": {"type": "boolean", "description": "Default true; false = dry run."},
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        from core.watch_voice import (
            brand_aliases,
            collect_app_store,
            collect_reddit,
            find_app_store_id,
            read_posts,
        )

        cid = _company(params)
        wm = self._watch_manager
        sources = [str(x) for x in (params.get("sources") or ["reddit", "app_store"])]
        window_days = int(params.get("window_days") or 30)
        max_posts = int(params.get("max_posts") or 200)
        save = bool(params.get("save", True))
        # Always direct — smart IP policy (docs/88): opinions and app-store
        # reviews carry no geo claim; the state-pinned exit is spent only on
        # storefront observation. (2026-08-20: geo_state=FL was passed here
        # and routed even iTunes through the metered exit.)
        proxy_url = None

        subjects = await wm.list_subjects(cid)
        if params.get("subject"):
            subj = await wm.get_subject_by_name(str(params["subject"]), cid)
            if subj is None:
                return ToolResult(
                    success=False,
                    error=f"subject {params['subject']!r} is not in the register — the register is canon",
                )
            subjects = [subj]
        dims = [d.name for d in await wm.list_dimensions(cid)]
        if self._router is None:
            return ToolResult(success=False, error="no router — voice reading needs the model")

        reddit_token = ""
        reddit_note = ""
        if "reddit" in sources:
            from core.watch_voice import reddit_app_token

            cid_ = str(self._vault.get("reddit_client_id") or "") if self._vault is not None else ""
            sec_ = str(self._vault.get("reddit_client_secret") or "") if self._vault is not None else ""
            if cid_ and sec_:
                reddit_token, tok_err = await reddit_app_token(cid_, sec_, proxy_url=proxy_url)
                if tok_err:
                    reddit_note = f"Reddit OAuth token failed: {tok_err}"
            if not reddit_token and self._browser_manager is None:
                reddit_note = reddit_note or (
                    "Reddit skipped: no browser and no reddit_client_id / "
                    "reddit_client_secret in the vault"
                )
        report: list[dict[str, Any]] = []
        total_kept = 0
        for subj in subjects:
            aliases = brand_aliases(subj.name, subj.url)
            per: dict[str, Any] = {"subject": subj.name, "sources": {}}
            posts_all: list[Any] = []
            if "reddit" in sources and not reddit_token and self._browser_manager is None:
                per["sources"]["reddit"] = {"fetched": 0, "note": reddit_note}
            elif "reddit" in sources:
                posts, errs = await collect_reddit(
                    subj.name, aliases, window_days=window_days, proxy_url=proxy_url,
                    max_posts=max_posts, token=reddit_token,
                    browser_manager=None if reddit_token else self._browser_manager,
                )
                per["sources"]["reddit"] = {"fetched": len(posts), "errors": errs[:3]}
                posts_all.extend(posts)
            if "app_store" in sources:
                app_id = next(
                    (t.split(":", 1)[1] for t in (subj.tags or []) if str(t).startswith("app_store:")),
                    None,
                )
                if app_id is None:
                    app_id = await find_app_store_id(subj.name, aliases, proxy_url=proxy_url)
                    if app_id and save:
                        await wm.tag_subject(subj.subject_id, f"app_store:{app_id}")
                if app_id:
                    posts, errs = await collect_app_store(
                        app_id, window_days=window_days, proxy_url=proxy_url
                    )
                    per["sources"]["app_store"] = {
                        "app_id": app_id, "fetched": len(posts), "errors": errs[:3]
                    }
                    posts_all.extend(posts)
                    # The listing itself — version, rating, release notes —
                    # from the same endpoints; release cadence over time.
                    try:
                        from core.watch_voice import fetch_app_meta

                        meta = await fetch_app_meta(app_id, proxy_url=proxy_url)
                        if meta and save:
                            await wm.add_app_meta(
                                company_id=cid, subject_id=subj.subject_id, store="app_store",
                                app_id=app_id, version=meta["version"], rating=meta["rating"],
                                rating_count=meta["rating_count"], release_notes=meta["release_notes"],
                                released_at=meta["released_at"],
                            )
                        if meta:
                            per["sources"]["app_store"]["version"] = meta["version"]
                            per["sources"]["app_store"]["rating"] = meta["rating"]
                    except Exception:
                        pass
                else:
                    per["sources"]["app_store"] = {"fetched": 0, "note": "no iOS app found"}
            items, dropped = await read_posts(
                self._router, brand=subj.name, posts=posts_all, dimension_names=dims
            )
            kept = 0
            dup = 0
            dim_ids = {d.name: d.dimension_id for d in await wm.list_dimensions(cid)}
            for it in items:
                if not save:
                    kept += 1
                    continue
                row = await wm.add_voice(
                    company_id=cid,
                    subject_id=subj.subject_id,
                    source=it["post"].source,
                    theme=it["theme"],
                    sentiment=it["sentiment"],
                    quote=it["quote"],
                    source_url=it["post"].url,
                    posted_at=it["post"].posted_at,
                    rating=it["post"].rating,
                    dimension_id=dim_ids.get(it["dimension"], ""),
                    geo_hint=it["geo_hint"],
                    weight=it["post"].weight,
                )
                if row is None:
                    dup += 1
                else:
                    kept += 1
            per.update({"posts": len(posts_all), "kept": kept, "duplicates": dup, "dropped": dropped})
            total_kept += kept
            report.append(per)
        return ToolResult(
            success=True,
            data={
                "company_id": cid,
                "window_days": window_days,
                "saved": save,
                "kept_total": total_kept,
                "brands": report,
                "reddit": (
                    "oauth"
                    if reddit_token
                    else (
                        "browser"
                        if "reddit" in sources and self._browser_manager is not None
                        else (reddit_note or "not requested")
                    )
                ),
                "note": "opinion filed in watch_voice; scores and the evidence register untouched",
            },
        )


class WatchVoiceTool(_WatchToolBase):
    """Read the voice-of-customer register: rows, the per-brand summary, or
    the theme diff against the last snapshot."""

    @property
    def name(self) -> str:
        return "watch_voice"

    @property
    def description(self) -> str:
        return (
            "Voice of customer, read side. action='summary' (default) — per "
            "brand: mentions, sentiment split, theme shares with n, top complaint "
            "and praise, three quotes, dimensions flagged; brands under the "
            "minimum are 'too few mentions to read'. action='list' — the rows "
            "(filter by subject/source/theme). action='diff' — rising and falling "
            "themes since the last snapshot. All of it is what players SAY, not "
            "observed fact."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["summary", "list", "diff"]},
                "subject": {"type": "string"},
                "source": {"type": "string"},
                "theme": {"type": "string"},
                "window_days": {"type": "integer", "description": "Default 30."},
                "limit": {"type": "integer", "description": "list: default 50."},
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        cid = _company(params)
        wm = self._watch_manager
        action = str(params.get("action") or "summary").lower()
        if action == "diff":
            d = await wm.diff_voice_since_snapshot(cid)
            if d is None:
                return ToolResult(success=True, data={"baseline": True, "note": "no snapshot yet"})
            return ToolResult(success=True, data=d)
        if action == "list":
            subject_id = None
            if params.get("subject"):
                subj = await wm.get_subject_by_name(str(params["subject"]), cid)
                if subj is None:
                    return ToolResult(success=False, error="unknown subject")
                subject_id = subj.subject_id
            rows = await wm.list_voice(
                cid,
                subject_id=subject_id,
                source=params.get("source") or None,
                theme=params.get("theme") or None,
                limit=int(params.get("limit") or 50),
            )
            names = {s.subject_id: s.name for s in await wm.list_subjects(cid)}
            return ToolResult(
                success=True,
                data={
                    "count": len(rows),
                    "rows": [
                        {
                            "brand": names.get(r.subject_id, r.subject_id),
                            "source": r.source,
                            "posted_at": r.posted_at[:10],
                            "theme": r.theme,
                            "sentiment": r.sentiment,
                            "rating": r.rating,
                            "quote": r.quote,
                            "url": r.source_url,
                            "weight": r.weight,
                        }
                        for r in rows
                    ],
                },
            )
        summary = await wm.voice_summary(cid, window_days=int(params.get("window_days") or 30))
        return ToolResult(success=True, data=summary)


class WatchVoiceReportTool(_WatchToolBase):
    """The standalone voice-of-customer pack — report, deck, workbook — for
    when only what players say is wanted."""

    def __init__(self) -> None:
        super().__init__()
        self._router: Any = None

    @property
    def name(self) -> str:
        return "watch_voice_report"

    @property
    def description(self) -> str:
        return (
            "Voice of customer as its own pack: a markdown report, an executive "
            "deck (.pptx: field heatmap of brands × themes, rising/falling since "
            "last cycle, one slide per brand with quotes and flags, method) and a "
            "workbook (summary + every quote), from watch_voice only. Use when the "
            "customer wants what players say on its own; the competitor pack picks "
            "the same material up automatically when present. Opinion, labelled."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Where to write the report (.md); deck and workbook land beside it.",
                },
                "window_days": {"type": "integer", "description": "Default 30."},
                "title": {"type": "string"},
                "market_label": {"type": "string"},
                "take_snapshot": {
                    "type": "boolean",
                    "description": "Snapshot after reporting so the next cycle can diff. Default true.",
                },
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        cid = _company(params)
        wm = self._watch_manager
        window_days = int(params.get("window_days") or 30)
        voice = await wm.voice_summary(cid, window_days=window_days)
        if not voice.get("mentions"):
            return ToolResult(
                success=False,
                error="nothing collected yet — run watch_voice_collect first",
            )
        vdiff = await wm.diff_voice_since_snapshot(cid)
        title = str(params.get("title") or "Voice of Customer — What Players Say")
        lines = [f"# {title}", ""] + _voice_markdown(voice, vdiff)
        lines += [
            "## Method",
            "",
            "Public posts and reviews, read for one theme (fixed vocabulary) and a sentiment; a short "
            "verbatim quote is kept with URL and date. Shares of a brand's own mentions, always with n; "
            f"brands under {voice.get('min_mentions', 15)} mentions are not read. Usernames stripped, "
            "affiliate posts dropped, cross-posts once. What players SAY — never a scorecard number.",
        ]
        report = "\n".join(lines)
        written: dict[str, str] = {}
        errors: dict[str, str] = {}
        if params.get("path"):
            from pathlib import Path

            p = Path(str(params["path"])).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(report, encoding="utf-8")
            written["report"] = str(p)
            narrative: dict[str, Any] = {}
            try:
                if self._router is not None:
                    from core.watch_deck import factual_narrative

                    # The pack's narrator wants a scorecard; standalone we take
                    # the computed reading — the slides carry it verbatim.
                    narrative = factual_narrative({"rows": [], "dimensions": []}, None, [], [], voice=voice)
                    narrative["next_steps"] = [
                        "Collect again next cycle; the movement slide fills in",
                        "Check every flagged dimension on the brand's own pages",
                    ]
            except Exception:
                narrative = {}
            try:
                from core.watch_deck import render_voice_deck

                written["deck"] = render_voice_deck(
                    voice,
                    voice_diff=vdiff,
                    narrative=narrative,
                    path=p.with_suffix(".pptx"),
                    title=title,
                    market_label=str(params.get("market_label") or ""),
                )
            except Exception as e:
                errors["deck"] = str(e)
            try:
                from core.watch_xlsx import render_voice_xlsx

                rows = _voice_rows_for_export(
                    await wm.list_voice(cid, limit=5000),
                    await wm.list_subjects(cid),
                    await wm.list_dimensions(cid),
                )
                written["workbook"] = render_voice_xlsx(rows, path=p.with_suffix(".xlsx"), summary=voice)
            except Exception as e:
                errors["workbook"] = str(e)
        snap_id = None
        if params.get("take_snapshot", True):
            snap_id = await wm.take_snapshot(cid, label="voice report")
        return ToolResult(
            success=True,
            data={
                "markdown": report,
                "written": written,
                "errors": errors,
                "snapshot_id": snap_id,
                "mentions": voice.get("mentions"),
                "brands_readable": len([b for b in voice.get("brands", []) if not b.get("too_few")]),
            },
        )


# ── The weekly service (docs/88): brief and alerts ─────────────────────


async def _broadcast_watch(gateway: Any, *, title: str, text: str) -> bool:
    """Push a 'watch' notification to every connected channel. False when
    there is no gateway (direct mode) — the caller reports that honestly."""
    if gateway is None:
        return False
    try:
        from core.protocol import EventType, event_message

        await gateway.broadcast(
            event_message("", EventType.NOTIFICATION, {"notification_type": "watch", "title": title, "text": text}),
            session_id=None,
        )
        return True
    except Exception:
        return False


class WatchWeeklyBriefTool(_WatchToolBase):
    """The Friday one-pager: what changed this week, market and players,
    decisions — from the registers, with sources."""

    def __init__(self) -> None:
        super().__init__()
        self._router: Any = None
        self._gateway: Any = None

    @property
    def name(self) -> str:
        return "watch_weekly_brief"

    @property
    def description(self) -> str:
        return (
            "The weekly executive brief (one page): fields that changed per brand "
            "this week (newest claim vs the one before), offers that changed, "
            "market events, score and player-sentiment movement, and the week's "
            "executive request with its answer. Writes markdown and a one-slide "
            "deck; notify=true pushes it to the connected channels; takes a "
            "'weekly brief' snapshot so next week diffs against this one. Every "
            "line traces to a register row."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Where to write the .md; the .pptx lands beside it."},
                "days": {"type": "integer", "description": "Window. Default 7."},
                "request": {"type": "string", "description": "This week's executive question, if any."},
                "answer": {"type": "string", "description": "Your answer to it (already researched)."},
                "notify": {"type": "boolean", "description": "Push to connected channels. Default false."},
                "take_snapshot": {"type": "boolean", "description": "Default true."},
                "title": {"type": "string"},
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        from core.watch_brief import (
            build_weekly_brief,
            narrate_brief,
            render_brief_markdown,
            render_brief_slide,
        )

        cid = _company(params)
        wm = self._watch_manager
        brief = await build_weekly_brief(
            wm,
            cid,
            days=int(params.get("days") or 7),
            request=str(params.get("request") or ""),
            answer=str(params.get("answer") or ""),
        )
        narrative = await narrate_brief(self._router, brief)
        md = render_brief_markdown(brief, narrative)
        written: dict[str, str] = {}
        if params.get("path"):
            from pathlib import Path

            p = Path(str(params["path"])).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(md, encoding="utf-8")
            written["markdown"] = str(p)
            try:
                written["slide"] = render_brief_slide(
                    brief, narrative, path=p.with_suffix(".pptx"),
                    title=str(params.get("title") or "Weekly Competitive Brief"),
                )
            except Exception as e:
                written["slide_error"] = str(e)
        notified = False
        if params.get("notify"):
            head = f"Weekly competitive brief · {brief['period']['since']} → {brief['period']['until']}"
            notified = await _broadcast_watch(self._gateway, title=head, text=md)
        snap_id = None
        if params.get("take_snapshot", True):
            snap_id = await wm.take_snapshot(cid, label="weekly brief")
        return ToolResult(
            success=True,
            data={
                "markdown": md,
                "brief": {k: v for k, v in brief.items() if k not in ("facts_per_brand",)},
                "narrative_source": "model" if narrative else "facts",
                "written": written,
                "notified": notified,
                "snapshot_id": snap_id,
            },
        )


class WatchAlertsTool(_WatchToolBase):
    """Mid-week wake-ups: detect, store once, push."""

    def __init__(self) -> None:
        super().__init__()
        self._gateway: Any = None

    @property
    def name(self) -> str:
        return "watch_alerts"

    @property
    def description(self) -> str:
        return (
            "Competitive alerts. action='check' (default) reads the registers "
            "for market events observed in the last 48h, regulatory items with an "
            "effective date inside 30 days or fresh enforcement, and player-"
            "sentiment spikes; stores each once and, with notify=true, pushes the "
            "new ones to the connected channels. action='list' shows recent "
            "alerts. Runs unattended on a schedule; alerts are only as fresh as "
            "collection, so keep the daily market pulse running."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["check", "list"]},
                "notify": {"type": "boolean", "description": "check: push new alerts. Default true."},
                "hours": {"type": "integer", "description": "check: evidence lookback. Default 48."},
                "limit": {"type": "integer", "description": "list: default 30."},
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        from core.watch_alerts import detect_alerts, format_alert

        cid = _company(params)
        wm = self._watch_manager
        if str(params.get("action") or "check").lower() == "list":
            rows = await wm.list_alerts(cid, limit=int(params.get("limit") or 30))
            return ToolResult(success=True, data={"count": len(rows), "alerts": rows})
        cands = await detect_alerts(wm, cid, hours=int(params.get("hours") or 48))
        new = await wm.record_alerts(cid, cands)
        notified = False
        if new and bool(params.get("notify", True)):
            text = "\n".join(format_alert(a) for a in new[:8])
            notified = await _broadcast_watch(
                self._gateway,
                title=f"{len(new)} competitive alert{'s' if len(new) != 1 else ''}",
                text=text,
            )
            if notified:
                await wm.mark_alerts_notified([a["alert_id"] for a in new])
        return ToolResult(
            success=True,
            data={
                "candidates": len(cands),
                "new": [{k: v for k, v in a.items() if k != "dedupe_key"} for a in new],
                "notified": notified,
            },
        )


# ── Player comms (docs/88 §C): what brands send players ────────────────


def _agentmail_client(vault: Any, config: Any) -> tuple[Any, str | None]:
    """The AgentMail client from the vault key the e-mail tools use."""
    if vault is None:
        return None, "vault unavailable"
    ref = getattr(getattr(config, "email", None), "api_key_ref", None) or "agentmail_api_key"
    key = vault.get(ref)
    if not key:
        return None, f"no {ref} in the vault"
    try:
        from agentmail import AgentMail

        return AgentMail(api_key=key), None
    except Exception as e:
        return None, f"agentmail unavailable: {e}"


def _subject_inbox(subj: Any) -> str:
    return next((str(t).split(":", 1)[1] for t in (subj.tags or []) if str(t).startswith("inbox:")), "")


class WatchCommsSetupTool(_WatchToolBase):
    """Give a tracked brand an inbox of our own and the signup instructions."""

    def __init__(self) -> None:
        super().__init__()
        self._vault: Any = None
        self._config: Any = None

    @property
    def name(self) -> str:
        return "watch_comms_setup"

    @property
    def description(self) -> str:
        return (
            "Player comms, step 1: create an AgentMail inbox for a tracked brand "
            "(tagged inbox:<address> on the subject), store a signup password in "
            "the vault, and return the signup instructions — then sign the brand "
            "up in the browser with that address so its marketing e-mails start "
            "landing in the inbox. Register is canon: existing subjects only. "
            "Idempotent: an inbox already linked is returned as is."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Brand name from the register."},
                "company_id": {"type": "string"},
            },
            "required": ["subject"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        from core.watch_comms import inbox_username, signup_password

        cid = _company(params)
        wm = self._watch_manager
        subj = await wm.get_subject_by_name(str(params.get("subject") or ""), cid)
        if subj is None:
            return ToolResult(success=False, error="subject not in the register — the register is canon")
        inbox = _subject_inbox(subj)
        vault_key = f"watch_comms:{subj.subject_id}"
        if not inbox:
            client, cerr = _agentmail_client(self._vault, self._config)
            if client is None:
                return ToolResult(success=False, error=cerr)
            try:
                from agentmail.inboxes.types import CreateInboxRequest

                created = client.inboxes.create(
                    request=CreateInboxRequest(username=inbox_username(subj.name), display_name="Player")
                )
                inbox = str(getattr(created, "inbox_id", "") or "")
            except Exception as e:
                return ToolResult(success=False, error=f"inbox creation failed: {e}")
            if not inbox:
                return ToolResult(success=False, error="inbox creation returned no address")
            await wm.tag_subject(subj.subject_id, f"inbox:{inbox}")
        creds = self._vault.get(vault_key) if self._vault is not None else None
        if not creds:
            creds = {"email": inbox, "password": signup_password()}
            if self._vault is not None:
                self._vault.set(vault_key, creds)
        pw = creds.get("password") if isinstance(creds, dict) else ""
        return ToolResult(
            success=True,
            data={
                "subject": subj.name,
                "inbox": inbox,
                "vault_key": vault_key,
                "next": (
                    f"In the browser, open {subj.url or 'the brand site'} and sign up (or subscribe to "
                    f"the newsletter) with e-mail {inbox} and the password stored under vault key "
                    f"{vault_key}. Accept marketing e-mails. Do NOT make a purchase or verify identity. "
                    f"Then run watch_comms_collect weekly."
                ),
                "password_hint": (pw[:2] + "…") if pw else "",
            },
        )


class WatchCommsCollectTool(_WatchToolBase):
    """Read new marketing e-mails from each brand's inbox into watch_comms."""

    def __init__(self) -> None:
        super().__init__()
        self._vault: Any = None
        self._config: Any = None
        self._router: Any = None

    @property
    def name(self) -> str:
        return "watch_comms_collect"

    @property
    def description(self) -> str:
        return (
            "Player comms, step 2: for every brand with a linked inbox (or one "
            "subject), fetch its new e-mails, read each for category (welcome, "
            "promo offer, daily bonus, reactivation, VIP, tournament, product "
            "news, transactional) and the offer it carries with a verified "
            "excerpt, and file them in watch_comms. Message ids dedupe. Nothing "
            "here changes a score; the deck's 'What they send players' slide, the "
            "weekly brief and the report pick it up when present."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "One brand; default all linked."},
                "max_messages": {"type": "integer", "description": "Per inbox per run. Default 100."},
                "save": {"type": "boolean", "description": "Default true."},
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        from core.watch_comms import message_text, message_time, read_comms

        cid = _company(params)
        wm = self._watch_manager
        client, cerr = _agentmail_client(self._vault, self._config)
        if client is None:
            return ToolResult(success=False, error=cerr)
        if self._router is None:
            return ToolResult(success=False, error="no router — comms reading needs the model")
        subjects = await wm.list_subjects(cid)
        if params.get("subject"):
            subj = await wm.get_subject_by_name(str(params["subject"]), cid)
            if subj is None:
                return ToolResult(success=False, error="subject not in the register — the register is canon")
            subjects = [subj]
        save = bool(params.get("save", True))
        max_messages = int(params.get("max_messages") or 100)
        report: list[dict[str, Any]] = []
        kept_total = 0
        for subj in subjects:
            inbox = _subject_inbox(subj)
            if not inbox:
                continue
            per: dict[str, Any] = {"subject": subj.name, "inbox": inbox}
            try:
                listing = client.inboxes.messages.list(inbox_id=inbox)
                raw = getattr(listing, "messages", None) or listing
                raw = list(raw) if not isinstance(raw, list) else raw
            except Exception as e:
                per["error"] = f"list failed: {e}"
                report.append(per)
                continue
            known = {c.message_id for c in await wm.list_comms(cid, subject_id=subj.subject_id, limit=5000)}
            fresh = [m for m in raw if str(getattr(m, "message_id", "") or "") not in known][:max_messages]
            messages: list[dict[str, Any]] = []
            for m in fresh:
                mid = str(getattr(m, "message_id", "") or "")
                try:
                    full = client.inboxes.messages.get(inbox_id=inbox, message_id=mid)
                except Exception:
                    full = m
                messages.append(
                    {
                        "id": mid,
                        "subject": str(getattr(m, "subject", "") or ""),
                        "text": message_text(full)[:6000],
                        "sender": str(getattr(m, "from_", "") or ""),
                        "received_at": message_time(m),
                    }
                )
            items, dropped = await read_comms(self._router, brand=subj.name, messages=messages)
            kept = 0
            for it in items:
                if not save:
                    kept += 1
                    continue
                row = await wm.add_comms(
                    company_id=cid,
                    subject_id=subj.subject_id,
                    message_id=it["message"]["id"],
                    received_at=it["message"]["received_at"],
                    category=it["category"],
                    inbox=inbox,
                    sender=it["message"]["sender"],
                    subject_line=it["message"]["subject"],
                    offer_text=it["offer"],
                    excerpt=it["excerpt"],
                )
                if row is not None:
                    kept += 1
            per.update({"fetched": len(raw), "new": len(fresh), "kept": kept, "dropped": dropped})
            kept_total += kept
            report.append(per)
        return ToolResult(
            success=True,
            data={
                "company_id": cid,
                "saved": save,
                "kept_total": kept_total,
                "brands": report,
                "note": (
                    "linked inboxes only — run watch_comms_setup for a brand first; "
                    "filed in watch_comms; scores and the evidence register untouched"
                ),
            },
        )


class WatchCommsTool(_WatchToolBase):
    """Read side of player comms."""

    @property
    def name(self) -> str:
        return "watch_comms"

    @property
    def description(self) -> str:
        return (
            "Player comms, read side. action='summary' (default): per brand — "
            "e-mails in the window, per-week cadence, category mix, peak send hour, "
            "latest offers and subject lines. action='list': the rows."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["summary", "list"]},
                "subject": {"type": "string"},
                "window_days": {"type": "integer", "description": "Default 30."},
                "limit": {"type": "integer", "description": "list: default 50."},
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        cid = _company(params)
        wm = self._watch_manager
        if str(params.get("action") or "summary").lower() == "list":
            subject_id = None
            if params.get("subject"):
                subj = await wm.get_subject_by_name(str(params["subject"]), cid)
                if subj is None:
                    return ToolResult(success=False, error="unknown subject")
                subject_id = subj.subject_id
            rows = await wm.list_comms(cid, subject_id=subject_id, limit=int(params.get("limit") or 50))
            names = {s.subject_id: s.name for s in await wm.list_subjects(cid)}
            return ToolResult(
                success=True,
                data={
                    "count": len(rows),
                    "rows": [
                        {
                            "brand": names.get(r.subject_id, r.subject_id),
                            "received_at": r.received_at[:16],
                            "category": r.category,
                            "subject": r.subject_line,
                            "offer": r.offer_text,
                            "excerpt": r.excerpt,
                            "sender": r.sender,
                        }
                        for r in rows
                    ],
                },
            )
        return ToolResult(
            success=True, data=await wm.comms_summary(cid, window_days=int(params.get("window_days") or 30))
        )


# ── Regulatory register (docs/88 §D) ───────────────────────────────────


class WatchRegulatoryCollectTool(_WatchToolBase):
    """Search, fetch, extract with verified excerpts, file — per priority
    state and per tracked brand."""

    def __init__(self) -> None:
        super().__init__()
        self._router: Any = None
        self._config: Any = None
        self._vault: Any = None
        self._browser_manager: Any = None

    @property
    def name(self) -> str:
        return "watch_regulatory_collect"

    @property
    def description(self) -> str:
        return (
            "Regulatory tracking: for the priority states and every tracked brand, "
            "search the web, read the pages, and file bills, effective dates, "
            "enforcement actions, lawsuits, guidance and operator responses (who "
            "left a state when) in watch_regulatory — each with a verified excerpt, "
            "URL and date, third-party provenance, deduped. Needs the "
            "search_sh_api_key vault entry and the model. Not legal advice: the "
            "register says what was published and where."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "states": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Priority states (codes or names). Default: the proxy state.",
                },
                "max_pages": {"type": "integer", "description": "Pages to read per run. Default 24."},
                "save": {"type": "boolean", "description": "Default true."},
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        from core.watch_observe import fetch_page_best_effort, search_web
        from core.watch_regulatory import extract_regulatory, regulatory_queries, state_name

        cid = _company(params)
        wm = self._watch_manager
        if self._router is None:
            return ToolResult(success=False, error="no router — regulatory reading needs the model")
        api_key = self._vault.get("search_sh_api_key") if self._vault is not None else None
        if not api_key:
            return ToolResult(success=False, error="no search_sh_api_key in vault — cannot search")
        states = [str(x) for x in (params.get("states") or [])]
        if not states:
            st = getattr(getattr(self._config, "proxy", None), "state", "") if self._config else ""
            states = [st] if st else ["FL"]
        from datetime import UTC, datetime

        subjects = await wm.list_subjects(cid)
        brands = [s_.name for s_ in subjects]
        year = datetime.now(UTC).year
        queries = regulatory_queries(states, brands[:15], year=year)
        results: list[dict[str, str]] = []
        for q in queries:
            results.extend(await search_web(q, api_key=str(api_key), max_results=6))
        seen: set[str] = set()
        urls: list[str] = []
        for r in results:
            u = str(r.get("url") or "")
            if u and u not in seen and not any(b in u for b in ("facebook.com", "twitter.com", "x.com/", "youtube.com")):
                seen.add(u)
                urls.append(u)
        urls = urls[: int(params.get("max_pages") or 24)]
        # Direct, no proxy — smart IP policy (docs/88): the state-pinned exit
        # exists to prove what a Florida CUSTOMER sees and is spent only on
        # storefront observation. News, legislatures and court reports carry
        # no geo claim, cost proxy gigabytes for nothing, and some sites
        # treat datacenter-ish exits worse than a plain connection.
        proxy_url = None
        save = bool(params.get("save", True))
        filed: list[dict[str, Any]] = []
        dup = 0
        read = 0
        errors: list[str] = []
        for u in urls:
            text, ferr, _method = await fetch_page_best_effort(
                u, browser_manager=self._browser_manager, proxy_url=proxy_url
            )
            if ferr or not text:
                errors.append(f"{u}: {ferr or 'empty'}")
                continue
            read += 1
            items = await extract_regulatory(self._router, page_text=text, brands=brands, states=states)
            for it in items:
                if not save:
                    filed.append({**it, "source_url": u})
                    continue
                row = await wm.add_regulatory(
                    company_id=cid,
                    jurisdiction=it["jurisdiction"],
                    kind=it["kind"],
                    title=it["title"],
                    status=it["status"],
                    event_date=it["event_date"],
                    subjects=it["subjects"],
                    source_url=u,
                    excerpt=it["excerpt"],
                )
                if row is None:
                    dup += 1
                else:
                    filed.append(row)
        return ToolResult(
            success=True,
            data={
                "company_id": cid,
                "states": [state_name(x) for x in states],
                "queries": len(queries),
                "urls": len(urls),
                "pages_read": read,
                "filed": len(filed),
                "duplicates": dup,
                "items": filed[:20],
                "errors": errors[:5],
                "saved": save,
                "note": "third-party items with verified excerpts; not legal advice",
            },
        )


class WatchRegulatoryTool(_WatchToolBase):
    """Read side: the calendar and the rows."""

    @property
    def name(self) -> str:
        return "watch_regulatory"

    @property
    def description(self) -> str:
        return (
            "Regulatory register, read side. action='calendar' (default): dated "
            "items ahead (next 90 days, soonest first), recent enforcement and "
            "lawsuits, operator responses, counts per jurisdiction. action='list': "
            "the rows (filter by jurisdiction/kind)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["calendar", "list"]},
                "jurisdiction": {"type": "string"},
                "kind": {"type": "string"},
                "horizon_days": {"type": "integer", "description": "calendar: default 90."},
                "limit": {"type": "integer", "description": "list: default 50."},
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        cid = _company(params)
        wm = self._watch_manager
        if str(params.get("action") or "calendar").lower() == "list":
            rows = await wm.list_regulatory(
                cid,
                jurisdiction=params.get("jurisdiction") or None,
                kind=params.get("kind") or None,
                limit=int(params.get("limit") or 50),
            )
            return ToolResult(success=True, data={"count": len(rows), "items": rows})
        return ToolResult(
            success=True,
            data=await wm.regulatory_calendar(cid, horizon_days=int(params.get("horizon_days") or 90)),
        )


# ── Logged-in observation (docs/88): the agent signs in itself ─────────


def _merge_login_results(results_file: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Write ``rows`` into the results file, replacing that brand's previous
    entry and keeping every other brand's — so a per-brand call does not
    erase the history the cooldown reads."""
    existing: list[dict[str, Any]] = []
    try:
        loaded = json.loads(results_file.read_text(encoding="utf-8"))
        existing = [r for r in loaded if isinstance(r, dict)] if isinstance(loaded, list) else []
    except Exception:
        existing = []
    fresh = {str(r.get("brand") or ""): r for r in rows if not r.get("from_cache")}
    merged = [r for r in existing if str(r.get("brand") or "") not in fresh] + list(fresh.values())
    results_file.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged


def _vault_creds_for(vault: Any, url: str) -> tuple[str, dict[str, Any] | None]:
    """The stored credentials for a brand's site, resolved the way
    vault_lookup resolves them (exact key, else a domain match)."""
    if vault is None or not url:
        return "", None
    domain = (
        url.lower()
        .removeprefix("https://")
        .removeprefix("http://")
        .removeprefix("www.")
        .split("/")[0]
    )
    got = vault.get(domain)
    if not got:
        for key in vault.list_keys():
            if key and ("." in key) and (key in domain or domain in key):
                got = vault.get(key)
                domain = key
                break
    if isinstance(got, str):
        try:
            got = json.loads(got)
        except Exception:
            return domain, None
    return domain, got if isinstance(got, dict) and got.get("password") else None


class WatchLoginTool(_WatchToolBase):
    """Sign the agent's browser into tracked brands, so collection can read
    what a registered player sees."""

    def __init__(self) -> None:
        super().__init__()
        self._vault: Any = None
        self._browser_manager: Any = None
        self._config: Any = None

    @property
    def name(self) -> str:
        return "watch_login"

    @property
    def description(self) -> str:
        return (
            "Log the agent's real browser into tracked brands using the site "
            "credentials in the vault, so watch_analyze / watch_observe can then "
            "collect with customer_state='registered' — what a signed-in player "
            "sees (coin packages, VIP tiers, real daily bonuses), which no "
            "logged-out read can show. Opens the brand's login page, handles the "
            "consent overlay, types the credentials, clicks a checkbox anti-bot "
            "widget if one appears, and reports the session state READ FROM THE "
            "PAGE. It never solves an image/audio challenge — that is reported as "
            "'challenge'. action='status' checks the current session without "
            "typing anything. Register is canon: tracked subjects only."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["login", "status"]},
                "subject": {
                    "type": "string",
                    "description": "Brand name from the register. Omit for every brand with stored credentials.",
                },
                "geo_state": {
                    "type": "string",
                    "description": (
                        "Force every brand through this state's exit (e.g. TX). By "
                        "default each brand uses the state stored with its credentials "
                        "(these accounts are geo-bound — a login from the wrong state "
                        "can be refused with the right password), falling back to the "
                        "configured exit. The exit is proven before any sign-in."
                    ),
                },
                "retry_after_hours": {
                    "type": "number",
                    "description": (
                        "Do not sign in again if this brand was checked within this "
                        "many hours — report the stored verdict instead. Default 12. "
                        "Repeated failed attempts are how accounts get locked; 0 forces "
                        "a fresh attempt."
                    ),
                },
                "assist_seconds": {
                    "type": "integer",
                    "description": (
                        "If a brand shows an image/audio anti-bot puzzle, pause this "
                        "many seconds so the operator can clear it in the visible "
                        "Chrome window; the session then persists and later runs need "
                        "no human. 0 (default) reports 'challenge' and moves on."
                    ),
                },
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        if self._browser_manager is None:
            return ToolResult(success=False, error="no browser — watch_login needs the real browser")
        from core.watch_login import (
            login_to_site,
            recent_attempt,
            session_state,
            switch_browser_exit,
        )

        cid = _company(params)
        wm = self._watch_manager
        subjects = await wm.list_subjects(cid)
        if params.get("subject"):
            subj = await wm.get_subject_by_name(str(params["subject"]), cid)
            if subj is None:
                return ToolResult(
                    success=False,
                    error=f"subject {params['subject']!r} is not in the register — the register is canon",
                )
            subjects = [subj]

        if str(params.get("action") or "login").lower() == "status":
            state, hits_in, hits_out = await session_state(self._browser_manager)
            return ToolResult(
                success=True,
                data={"session": state, "signals_in": hits_in, "signals_out": hits_out},
            )

        shots = Path(
            str(getattr(self._config, "workspace", "") or ".")
        ) / "login-checks"
        proxy_cfg = getattr(self._config, "proxy", None)
        default_state = str(
            params.get("geo_state") or getattr(proxy_cfg, "state", "") or ""
        ).upper()

        def _wanted_state(creds: dict[str, Any]) -> str:
            """Where this account lives: the call's state, else the one stored
            with the credentials, else the configured exit."""
            return str(
                params.get("geo_state") or creds.get("geo") or default_state or ""
            ).upper()

        rows: list[dict[str, Any]] = []
        results_file = shots / "results.json"
        # Every failed attempt counts against the brand's own limiter, so a
        # brand checked recently is reported from the last result instead of
        # being signed into again (retry_after_hours=0 forces a fresh try).
        cooldown = float(params.get("retry_after_hours", 12) or 0)
        # Group by state so one browser restart serves every brand on that
        # exit, instead of thrashing Chrome between brands.
        todo: list[tuple[Any, str, dict[str, Any]]] = []
        for subj in subjects:
            domain, creds = _vault_creds_for(self._vault, subj.url)
            if creds is not None:
                todo.append((subj, domain, creds))
        todo.sort(key=lambda t: (_wanted_state(t[2]), t[0].name))
        current_state = ""
        for subj, domain, creds in todo:
            if cooldown > 0:
                cached = recent_attempt(str(results_file), subj.name, within_hours=cooldown)
                if cached is not None:
                    rows.append({**cached, "from_cache": True})
                    continue
            creds = {**creds, "brand": subj.name, "url": creds.get("url") or subj.url}
            shots.mkdir(parents=True, exist_ok=True)
            want_state = _wanted_state(creds)
            if want_state and want_state != current_state:
                ok, detail = await switch_browser_exit(
                    self._browser_manager, proxy_cfg, want_state
                )
                if not ok:
                    rows.append({
                        "brand": subj.name, "domain": domain, "verdict": "no_exit",
                        "note": f"cannot reach a verified {want_state} exit: "
                                f"{detail.get('error') or detail}",
                        "exit_state": want_state,
                    })
                    continue
                current_state = want_state
            res = await login_to_site(
                self._browser_manager,
                creds,
                screenshot_path=str(shots / f"{domain.replace('.', '-')}.jpg"),
                assist_seconds=int(params.get("assist_seconds") or 0),
                exit_state=want_state,
            )
            res["domain"] = domain
            rows.append(res)
            try:  # keep the cache current as we go — merged, never overwritten:
                # the agent signs in one brand per call, and the 12h cooldown
                # only holds if the previous call's verdicts survive this one.
                shots.mkdir(parents=True, exist_ok=True)
                _merge_login_results(results_file, rows)
            except Exception:
                pass
        if not rows:
            return ToolResult(
                success=False,
                error=(
                    "no stored credentials for any tracked brand — put them in the "
                    "vault keyed by domain (vault_set <domain>)"
                ),
            )
        ok = [r for r in rows if r["verdict"] in ("logged_in", "already_logged_in")]
        return ToolResult(
            success=True,
            data={
                "company_id": cid,
                "logged_in": len(ok),
                "attempted": len(rows),
                "results": rows,
                "note": (
                    "sessions live in the browser profile; collect now with "
                    "watch_analyze customer_state='registered' so the rows say what "
                    "they really are. Verdicts: 'challenge' = an image/audio anti-bot "
                    "puzzle, not solved here by design (an operator clears it once via "
                    "assist_seconds); 'rejected' = the site refused the attempt and its "
                    "own message is in `message` — a stale password, an account state "
                    "and a failed anti-bot score all read the same, so a human decides; "
                    "'no_form' = no login form found."
                ),
            },
        )


# ── Catalog: the raw inventory behind the scores (docs/89) ─────────────


class WatchCatalogCollectTool(_WatchToolBase):
    """Read each brand's providers, coin packages, promotions and games as
    printed, with a picture of the promotions page."""

    def __init__(self) -> None:
        super().__init__()
        self._router: Any = None
        self._config: Any = None
        self._browser_manager: Any = None
        self._vault: Any = None  # search_sh_api_key, for open-web research

    @property
    def name(self) -> str:
        return "watch_catalog_collect"

    @property
    def description(self) -> str:
        return (
            "Collect the RAW INVENTORY behind the scores: game providers, coin "
            "packages (the price ladder, with what each grants), promotions (with "
            "a screenshot of the promotions page) and the game list — as printed "
            "on each brand's own pages, verified to be on the page, never scored. "
            "This is what a client means by 'just the raw data'. Runs logged out "
            "by default; pass customer_state='registered' after watch_login so the "
            "store and the real promotions are visible, and every row is stamped "
            "with the session it was read in. Register is canon."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Brand name; omit for all active brands."},
                "kinds": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["provider", "coin_package", "promotion", "loyalty_tier", "game"]},
                    "description": "Default: all five.",
                },
                "customer_state": {
                    "type": "string",
                    "enum": ["logged_out", "registered", "verified", "purchaser", "redeemer", "vip"],
                    "description": (
                        "What the browser session IS while reading — stamped on every row. "
                        "Only set this when you have actually signed in (watch_login)."
                    ),
                },
                "research": {
                    "type": "boolean",
                    "description": (
                        "Search the open web for what the brand's own pages did not answer "
                        "(providers, price ladders, promotions, game lists are widely "
                        "published). Default true — it is free and needs no session."
                    ),
                },
                "min_items": {
                    "type": "integer",
                    "description": "A kind counts as answered once it has this many items (default 1: "
                                   "only an empty kind goes to research and then to sign-in). Use e.g. 10 "
                                   "for provider,game so a brand whose public pages show three teaser "
                                   "titles still gets its lobby read.",
                },
                "sign_in_if_missing": {
                    "type": "boolean",
                    "description": (
                        "Last resort: after public pages AND web research still leave a kind "
                        "empty, sign in (watch_login) and read the brand's own store/promotions "
                        "again. Default false — a session costs proxy traffic and login attempts."
                    ),
                },
                "geo_state": {
                    "type": "string",
                    "description": (
                        "Read as this US state (e.g. FL). Default 'n/a' — direct, no proxy: "
                        "providers, packages and game lists carry no geo claim, so the "
                        "state-pinned exit is not spent on them."
                    ),
                },
                "max_pages": {"type": "integer", "description": "Brand pages read per brand. Default 8."},
                "save": {"type": "boolean", "description": "Default true; false = dry run."},
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        if self._router is None:
            return ToolResult(success=False, error="no router — catalog reading needs the model")
        from core.watch_catalog import (
            CATALOG_KINDS,
            extract_catalog,
            known_review_urls,
            rank_catalog_pages,
            rank_research_urls,
            research_page_ok,
            research_queries,
        )
        from core.watch_observe import (
            capture_page_screenshot,
            collect_pages,
            fetch_page_best_effort,
            screenshot_filename,
            search_web,
        )
        from core.watch_voice import brand_aliases

        cid = _company(params)
        wm = self._watch_manager
        kinds = [k for k in (params.get("kinds") or CATALOG_KINDS) if k in CATALOG_KINDS]
        customer_state = str(params.get("customer_state") or "logged_out")
        if customer_state not in VALID_CUSTOMER_STATES:
            return ToolResult(
                success=False,
                error=f"invalid customer_state {customer_state!r} — one of {', '.join(VALID_CUSTOMER_STATES)}",
            )
        geo_state = str(params.get("geo_state") or "n/a")
        proxy_url = None
        if self._config is not None and getattr(self._config, "proxy", None):
            proxy_url = self._config.proxy.request_proxy_url(geo_state) or None
        if geo_state != "n/a" and not proxy_url:
            return _no_exit_for_state(geo_state)
        save = bool(params.get("save", True))

        subjects = await wm.list_subjects(cid)
        if params.get("subject"):
            subj = await wm.get_subject_by_name(str(params["subject"]), cid)
            if subj is None:
                return ToolResult(
                    success=False,
                    error=f"subject {params['subject']!r} is not in the register — the register is canon",
                )
            subjects = [subj]

        from datetime import UTC, datetime

        research = bool(params.get("research", True))
        sign_in_if_missing = bool(params.get("sign_in_if_missing", False))
        min_items = max(1, int(params.get("min_items") or 1))
        search_key = self._vault.get("search_sh_api_key") if self._vault is not None else None
        shots_root = Path(str(getattr(self._config, "workspace", "") or ".")) / "catalog-shots"
        report: list[dict[str, Any]] = []
        total_new = 0
        year = datetime.now(UTC).year

        async def _file(kind: str, items: list[dict[str, Any]], *, subj: Any, url: str,
                        source_type: str, shot: str, session: str) -> int:
            """Store what a page yielded; returns how many rows were new."""
            new_rows = 0
            for item in items:
                if not save:
                    continue
                _row, is_new = await wm.add_catalog_item(
                    company_id=cid, subject_id=subj.subject_id, kind=kind,
                    brand_name=subj.name, source_url=url, source_type=source_type,
                    image_path=shot if kind == "promotion" else "",
                    customer_state=session, geo_state=geo_state, **item,
                )
                new_rows += 1 if is_new else 0
            return new_rows
        for subj in subjects:
            if not subj.url:
                continue
            pages = await collect_pages(
                subj.url,
                browser_manager=self._browser_manager,
                proxy_url=proxy_url,
                max_pages=int(params.get("max_pages") or 8),
            )
            readable = [p for p in pages if not p.get("error") and p.get("text")]
            by_kind = rank_catalog_pages(readable)
            per: dict[str, Any] = {"subject": subj.name, "pages_read": len(readable), "kinds": {}}
            for kind in kinds:
                found = 0
                new = 0
                shot = ""
                for page in by_kind.get(kind, []):
                    items = await extract_catalog(
                        self._router, kind=kind, brand=subj.name, page_text=str(page.get("text") or "")
                    )
                    if not items:
                        continue
                    if kind == "promotion" and save and not shot and self._browser_manager is not None:
                        # "maybe some images for the promotions" — the page the
                        # offers were read from, consent already dismissed.
                        target = shots_root / _slug(subj.name) / screenshot_filename(str(page.get("url") or ""))
                        shot = await capture_page_screenshot(
                            self._browser_manager, str(page.get("url") or ""), str(target)
                        )
                    for item in items:
                        found += 1
                        if not save:
                            continue
                        _row, is_new = await wm.add_catalog_item(
                            company_id=cid,
                            subject_id=subj.subject_id,
                            kind=kind,
                            brand_name=subj.name,
                            source_url=str(page.get("url") or ""),
                            image_path=shot if kind == "promotion" else "",
                            customer_state=customer_state,
                            geo_state=geo_state,
                            **item,
                        )
                        new += 1 if is_new else 0
                per["kinds"][kind] = {
                    "found": found, "new": new, "pages": len(by_kind.get(kind, [])),
                    "from": "brand site" if found else "", "new_site": new,
                }
                if kind == "promotion" and shot:
                    per["kinds"][kind]["image"] = shot
                total_new += new

                # Public research: whatever the brand's own pages did not
                # answer is usually published elsewhere, and reading it costs
                # no session and no metered exit. "Did not answer" is fewer
                # than min_items — three teaser titles are not a lobby.
                site_found = found
                if found >= min_items or not research or not search_key:
                    if sign_in_if_missing and found < min_items:
                        per["kinds"][kind]["needs_sign_in"] = True
                    continue
                brand_host = (subj.url or "").split("//")[-1].split("/")[0].removeprefix("www.")
                # A review site with a predictable per-brand page comes before
                # any search: written per brand, so attribution is not in doubt.
                urls: list[str] = list(known_review_urls(subj.name))
                for _kind, query in research_queries(subj.name, [kind], year=year):
                    hits = await search_web(query, api_key=str(search_key), max_results=6)
                    urls.extend(rank_research_urls(hits, brand_host=brand_host, limit=2))
                seen_urls: set[str] = set()
                for u in urls[:4]:
                    if u in seen_urls:
                        continue
                    seen_urls.add(u)
                    text, ferr, _m = await fetch_page_best_effort(
                        u, browser_manager=self._browser_manager, proxy_url=proxy_url
                    )
                    if ferr or not text:
                        continue
                    if not research_page_ok(u, text, subj.name, brand_aliases(subj.name, subj.url)):
                        per["kinds"][kind].setdefault("skipped_pages", []).append(u[:70])
                        continue
                    items = await extract_catalog(
                        self._router, kind=kind, brand=subj.name, page_text=text
                    )
                    if not items:
                        continue
                    found += len(items)
                    new += await _file(
                        kind, items, subj=subj, url=u,
                        source_type="third_party", shot="", session=customer_state,
                    )
                if found > site_found:
                    per["kinds"][kind].update({
                        "found": found, "new": new,
                        "from": "brand site + public research" if site_found else "public research",
                    })
                    total_new += new - per["kinds"][kind].get("new_site", 0)
                if sign_in_if_missing and found < min_items:
                    # Only now is a session worth its cost.
                    per["kinds"][kind]["needs_sign_in"] = True
            report.append(per)
        return ToolResult(
            success=True,
            data={
                "company_id": cid,
                "customer_state": customer_state,
                "geo_state": geo_state,
                "saved": save,
                "new_items": total_new,
                "brands": report,
                "saved_to": (
                    "the register (table watch_catalog in the agent database) — not a file. "
                    "To see it: watch_catalog action=summary|list|matrix; to deliver it: "
                    "watch_executive_deck (Game portfolio, Coins / Promotions and Providers / "
                    "Games pages per brand) and watch_board_report format=xlsx (one sheet per "
                    "kind plus the Game portfolio matrix), both with providers_from=<client "
                    "sheet> to follow the client's studio list. Tell the operator this."
                ),
                "note": (
                    "raw inventory in watch_catalog — appendix slides and one workbook "
                    "sheet per kind; never scored. Public pages and open-web research "
                    "first; kinds marked needs_sign_in found nothing public and are the "
                    "only ones worth a watch_login + re-run with customer_state set."
                ),
                "needs_sign_in": sorted({
                    f"{b['subject']}:{k}"
                    for b in report for k, v in b["kinds"].items() if v.get("needs_sign_in")
                }),
            },
        )


class WatchCatalogTool(_WatchToolBase):
    """Read side of the catalog."""

    @property
    def name(self) -> str:
        return "watch_catalog"

    @property
    def description(self) -> str:
        return (
            "The raw inventory, read side. action='summary' (default): per brand — "
            "counts by kind, the provider list, the coin-package price ladder, the "
            "promotions with their images, a sample of games. action='list': the "
            "rows themselves (filter by subject/kind). action='matrix': the game "
            "portfolio as Provider × Brand (the client's own layout), following "
            "their studio list when providers_from is given."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["summary", "list", "matrix"]},
                "subject": {"type": "string"},
                "kind": {"type": "string", "enum": ["provider", "coin_package", "promotion", "loyalty_tier", "game"]},
                "limit": {"type": "integer", "description": "list: default 200."},
                "providers_from": {
                    "type": "string",
                    "description": "matrix: path to the client's game-portfolio CSV (column A = studios).",
                },
                "company_id": {"type": "string"},
            },
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (err := self._guard()) is not None:
            return err
        cid = _company(params)
        wm = self._watch_manager
        action = str(params.get("action") or "summary").lower()
        if action == "matrix":
            uni = _provider_universe(params)
            if params.get("providers_from") and uni is None:
                return ToolResult(
                    success=False, error=f"could not read a studio list from {params['providers_from']}",
                )
            cat = await wm.catalog_summary(cid, uni)
            matrix = cat.get("matrix")
            if not matrix:
                return ToolResult(success=True, data={"providers": [], "brands": [], "note": "no providers on record"})
            return ToolResult(
                success=True,
                data={
                    "brands": matrix["brands"],
                    "counts": matrix["counts"],
                    "brands_only_on_client_list": matrix["brands_only_on_client_list"],
                    "brands_only_in_register": matrix["brands_only_in_register"],
                    "providers": [
                        {"provider": r["name"], "on_client_list": r["on_client_list"],
                         "brands": [b for b, c in r["brands"].items() if c["carried"]],
                         "games": {b: c["games"] for b, c in r["brands"].items() if c["games"]}}
                        for r in matrix["providers"]
                    ],
                },
            )
        if action == "list":
            subject_id = None
            if params.get("subject"):
                subj = await wm.get_subject_by_name(str(params["subject"]), cid)
                if subj is None:
                    return ToolResult(success=False, error="unknown subject")
                subject_id = subj.subject_id
            rows = await wm.list_catalog(
                cid, subject_id=subject_id, kind=params.get("kind") or None,
                limit=int(params.get("limit") or 200),
            )
            names = {s.subject_id: s.name for s in await wm.list_subjects(cid)}
            return ToolResult(
                success=True,
                data={
                    "count": len(rows),
                    "items": [
                        {
                            "brand": names.get(r.subject_id, r.subject_id), "kind": r.kind,
                            "name": r.name, "detail": r.detail, "price_usd": r.price_usd,
                            "coins": r.coins_text, "url": r.source_url, "image": r.image_path,
                            "session": r.customer_state, "observed_at": r.observed_at[:10],
                        }
                        for r in rows
                    ],
                },
            )
        return ToolResult(success=True, data=await wm.catalog_summary(cid))


def create_watch_tools() -> list[BaseTool]:
    """All competitive-intelligence tools."""
    return [
        WatchSubjectTool(),
        WatchDimensionTool(),
        WatchEvidenceTool(),
        WatchScoreTool(),
        WatchScorecardTool(),
        WatchSnapshotTool(),
        WatchDiffTool(),
        WatchBoardReportTool(),
        WatchExecutiveDeckTool(),
        WatchObserveTool(),
        WatchQueueTool(),
        WatchAnalyzeTool(),
        WatchVoiceCollectTool(),
        WatchVoiceTool(),
        WatchVoiceReportTool(),
        WatchWeeklyBriefTool(),
        WatchAlertsTool(),
        WatchCommsSetupTool(),
        WatchCommsCollectTool(),
        WatchCommsTool(),
        WatchRegulatoryCollectTool(),
        WatchRegulatoryTool(),
        WatchLoginTool(),
        WatchCatalogCollectTool(),
        WatchCatalogTool(),
    ]
