"""company_plan — LLM-driven strategy generation (Phase 11).

Reads ``companies/<slug>/company.yaml`` for product + strategy_inputs,
calls the LLM with the ported ``tmp/strategy.js`` prompts (system +
user), writes the parsed strategy JSON to
``data/companies/<slug>/strategy/proposed/<ISO_timestamp>.yaml``.

Pure artifact generation — no goals/missions/schedules created here.
That's ``company_plan_apply``'s job.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult
from tools.strategy._prompts import build_system_prompt, build_user_prompt

logger = logging.getLogger(__name__)


def _load_company_yaml(project_root: Path, company_id: str) -> dict[str, Any]:
    path = project_root / "companies" / company_id / "company.yaml"
    if not path.is_file():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("company_plan: company.yaml parse failed (%s): %s", path, e)
        return {}
    return data if isinstance(data, dict) else {}


def _strategy_inputs_from_company(
    company_yaml: dict[str, Any],
) -> dict[str, Any]:
    """Pull the strategy_inputs section + relevant product fields
    into the param shape that build_user_prompt expects."""
    si = company_yaml.get("strategy_inputs") or {}
    if not isinstance(si, dict):
        si = {}
    budget = si.get("budget") or {}
    if not isinstance(budget, dict):
        budget = {}
    return {
        "businessName": company_yaml.get("name") or "",
        "productDescription": company_yaml.get("what_we_sell") or "",
        "industry": si.get("industry") or "",
        "targetAudience": si.get("target_audience") or "",
        "uniqueSellingPoints": si.get("unique_selling_points") or "",
        "competitors": si.get("competitors") or "",
        "currentChallenges": si.get("current_challenges") or "",
        "budget": budget.get("amount") or 0,
        "budgetPeriod": budget.get("period") or "monthly",
        "budgetType": budget.get("type") or "mixed",
        "strategyMode": si.get("strategy_mode") or "standard",
        "focus": si.get("focus") or "full",
        "goals": si.get("primary_goals") or [],
        "riskTolerance": si.get("risk_tolerance") or 50,
        "channels": company_yaml.get("channels") or [],
        "timeline": si.get("timeline_hint") or "",
        "context": si.get("context") or "",
    }


async def _build_operational_context(db: Any, company_id: str) -> str:
    """Render existing per-company operational state into a context
    string the LLM strategy generator can ground on.

    The 2026-05-26 live test exposed that the strategy generator,
    given only ``company.yaml.what_we_sell``, focused narrowly on
    that one surface and ignored everything else the agent was
    actually doing for the company (X growth schedules, livestream
    cadence, polymarket monitor, prospect funnel state, ledger
    activity). Result: a strategy that addressed 1 of 5 surfaces
    and called it done. Operator feedback: *"the review part is
    not good enough"*.

    This function answers "what is this company actually doing
    right now?" — enabled schedules, recent ledger sums by type,
    prospect status distribution, active missions. The LLM
    receives this context BEFORE the planning call so the
    resulting strategy is a plan for the WHOLE business surface,
    not just ``what_we_sell``.

    Pure read-only. Best-effort: any query that fails returns its
    section empty rather than crashing the plan call.
    """
    parts: list[str] = []

    # 1. Enabled schedules (cadence + deadline) — these reveal what
    # operational surfaces the agent is currently maintaining.
    try:
        rows = await db.execute(
            "SELECT name, cron_expression, task_goal, direct_tool "
            "FROM scheduled_tasks WHERE enabled = 1 AND company_id = ? "
            "ORDER BY name",
            (company_id,),
        )
        if rows:
            parts.append(
                f"ACTIVE SCHEDULES ({len(rows)}) — surfaces the agent "
                "already operates for this company. The strategy should "
                "respect / extend these, not ignore them:"
            )
            for r in rows[:20]:
                goal_snip = (r["task_goal"] or "").splitlines()[0][:80]
                tool_hint = f" → {r['direct_tool']}" if r["direct_tool"] else ""
                parts.append(
                    f"  - [{r['cron_expression']}] {r['name']}{tool_hint}: {goal_snip}"
                )
            if len(rows) > 20:
                parts.append(f"  - …and {len(rows) - 20} more.")
            parts.append("")
    except Exception:
        pass

    # 2. Recent ledger activity (last 7 days) — honest progress signal
    # per type. Strategy generator should plan around revenue gaps,
    # spend ratios, and existing channels with momentum.
    try:
        rows = await db.execute(
            "SELECT type, direction, SUM(amount) AS total, COUNT(*) AS n "
            "FROM resource_ledger "
            "WHERE company_id = ? "
            "AND date(ts) >= date('now', '-7 days') "
            "GROUP BY type, direction "
            "ORDER BY total DESC",
            (company_id,),
        )
        if rows:
            parts.append("LEDGER SUMS (last 7 days) — what's actually moving:")
            for r in rows:
                parts.append(
                    f"  - {r['type']} ({r['direction']}): "
                    f"{r['total']:.2f} ({r['n']} events)"
                )
            parts.append("")
    except Exception:
        pass

    # 3. Prospect status distribution — funnel health snapshot.
    try:
        rows = await db.execute(
            "SELECT status, COUNT(*) AS n FROM prospects "
            "WHERE company_id = ? GROUP BY status ORDER BY n DESC",
            (company_id,),
        )
        if rows:
            parts.append("PROSPECT FUNNEL:")
            for r in rows:
                parts.append(f"  - {r['status']}: {r['n']}")
            parts.append("")
    except Exception:
        pass

    # 4. Active missions — multiple in-flight initiatives the
    # strategy should acknowledge rather than overwrite.
    try:
        rows = await db.execute(
            "SELECT title, momentum_score FROM missions "
            "WHERE company_id = ? AND status = 'active' "
            "ORDER BY momentum_score DESC LIMIT 10",
            (company_id,),
        )
        if rows:
            parts.append("ACTIVE MISSIONS:")
            for r in rows:
                parts.append(f"  - {r['title']} (momentum={r['momentum_score']:.2f})")
            parts.append("")
    except Exception:
        pass

    if not parts:
        return ""
    return (
        "OPERATIONAL CONTEXT (deterministic snapshot of current state — "
        "the strategy must address ALL these surfaces, not just "
        "what_we_sell):\n\n" + "\n".join(parts)
    )


class CompanyPlanTool(BaseTool):
    def __init__(self) -> None:
        self._project_root: Any = None
        self._router: Any = None
        self._strategy_manager: Any = None
        self._db: Any = None
        # Live tool registry — injected so the strategy LLM can be
        # told what capabilities ALREADY exist instead of inventing
        # `tool_requirements` for them. Without this every strategy
        # shipped with hallucinated "missing" tools that became
        # blockers the autonomous mind then tried to `self_create_plugin`
        # for (see production cycle that proposed building
        # `x_post_and_reply` when twitter_post + twitter_reply already
        # ship). Optional — when None, the legacy prompt shape applies.
        self._registry: Any = None

    @property
    def name(self) -> str:
        return "company_plan"

    @property
    def group(self) -> str:
        return "companies"

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def description(self) -> str:
        return (
            "Generate strategy proposal for a company via LLM. Reads "
            "product + strategy_inputs from company.yaml. Writes "
            "data/companies/<slug>/strategy/proposed/<ts>.yaml. Pure "
            "artifact — no side effects until apply. See "
            "strategy-pipeline skill."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "context": {
                    "type": "string",
                    "description": (
                        "Optional prior research / capability audit "
                        "summary the LLM should ground the strategy in."
                    ),
                },
                "override_strategy_mode": {"type": "string"},
                "override_focus": {"type": "string"},
            },
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._project_root is None or self._router is None:
            return ToolResult(
                success=False,
                error="company_plan not initialized (project_root + router)",
            )
        if self._strategy_manager is None:
            return ToolResult(
                success=False,
                error="company_plan not initialized (missing strategy_manager)",
            )
        from core.company import current_company_id

        company_id = str(params.get("company_id") or current_company_id())
        company_yaml = _load_company_yaml(self._project_root, company_id)
        if not company_yaml:
            return ToolResult(
                success=False,
                error=(
                    f"company.yaml missing or empty for {company_id} — "
                    "run company_onboard first."
                ),
            )

        prompt_inputs = _strategy_inputs_from_company(company_yaml)

        # Build deterministic operational context (active schedules +
        # ledger sums + prospect funnel + missions) so the LLM plans
        # for the WHOLE business surface, not just what_we_sell. Live
        # test 2026-05-26 showed strategies narrowing to one surface
        # when this context wasn't injected — operator feedback:
        # "the review part is not good enough".
        operational_block = ""
        if self._db is not None:
            try:
                operational_block = await _build_operational_context(
                    self._db, company_id
                )
            except Exception as e:
                logger.warning("operational context build failed: %s", e)
                operational_block = ""

        agent_context = str(params.get("context") or "")
        merged_context_parts: list[str] = []
        if operational_block:
            merged_context_parts.append(operational_block)
        if agent_context:
            merged_context_parts.append(
                "AGENT-PROVIDED CONTEXT (from prior research):\n" + agent_context
            )
        if merged_context_parts:
            prompt_inputs["context"] = "\n\n".join(merged_context_parts)
        mode = str(
            params.get("override_strategy_mode")
            or prompt_inputs.get("strategyMode")
            or "standard"
        )
        focus = str(
            params.get("override_focus") or prompt_inputs.get("focus") or "full"
        )
        budget = float(prompt_inputs.get("budget") or 0)
        risk = int(prompt_inputs.get("riskTolerance") or 50)

        # Collect the live registry (name + 1-line description) so the
        # strategy LLM stops inventing capability names. Best-effort:
        # any registry failure falls through to the legacy prompt
        # shape rather than blocking strategy generation.
        available_tools: list[tuple[str, str]] | None = None
        if self._registry is not None:
            try:
                available_tools = sorted(
                    (t.name, (t.description or "").strip())
                    for t in self._registry.all_tools()
                )
            except Exception as e:
                logger.debug("company_plan: registry enumeration failed: %s", e)

        system_prompt = build_system_prompt(
            strategy_mode=mode,
            focus=focus,
            budget_type=str(prompt_inputs.get("budgetType") or "mixed"),
            budget=budget,
            budget_period=str(prompt_inputs.get("budgetPeriod") or "monthly"),
            risk_tolerance=risk,
            context=str(prompt_inputs.get("context") or ""),
            available_tools=available_tools,
        )
        user_prompt = build_user_prompt(inputs=prompt_inputs)

        # One retry on JSONDecodeError — strategy output is large (~5x
        # dream output); a single trailing-comma shouldn't waste the
        # whole call. We re-call with a JSON-mode reminder appended.
        last_err: str = ""
        for attempt in range(2):
            try:
                response = await self._router.complete(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    task_type="planning",
                    temperature=0.7,
                )
            except Exception as e:
                return ToolResult(success=False, error=f"strategy LLM call failed: {e}")
            content = (response.content or "").strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            try:
                parsed = json.loads(content)
                break
            except json.JSONDecodeError as e:
                last_err = str(e)
                if attempt == 0:
                    user_prompt += (
                        "\n\nREMINDER: Output ONLY the JSON object. No "
                        "code fences, no commentary. Begin with { and end "
                        "with }."
                    )
                    continue
                return ToolResult(
                    success=False,
                    error=(
                        f"strategy JSON parse failed after retry: {last_err}; "
                        f"first 200 chars: {content[:200]!r}"
                    ),
                )

        if not isinstance(parsed, dict):
            return ToolResult(
                success=False, error="strategy LLM output JSON was not a mapping"
            )

        try:
            proposal_path = self._strategy_manager.write_proposal(company_id, parsed)
        except Exception as e:
            return ToolResult(
                success=False, error=f"strategy proposal write failed: {e}"
            )

        return ToolResult(
            success=True,
            data={
                "company_id": company_id,
                "proposal_path": str(proposal_path),
                "strategy_name": parsed.get("strategyName") or "",
                "tactic_count": len(parsed.get("tactics") or []),
                "vault_requirement_count": len(parsed.get("vault_requirements") or []),
                "tool_requirement_count": len(parsed.get("tool_requirements") or []),
                "execution_priority": parsed.get("execution_priority") or "staged",
                "next": (
                    "Operator reviews the proposal at "
                    f"{proposal_path}. To activate (creates mission + "
                    "goals + schedules + voice seed + blockers), call "
                    "company_plan_apply with this proposal_path. The "
                    "proposal sits in /proposed/ until applied."
                ),
            },
        )
