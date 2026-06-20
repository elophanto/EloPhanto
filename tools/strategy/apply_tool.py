"""company_plan_apply — promote a proposed strategy to active and
fan it out into mission + goals + schedules + voice seed + blockers
(ABE Phase 11).

The single operator-approved tool that turns the LLM's artifact into
actual scheduled work. MODERATE permission so the operator sees
exactly what's about to be created before it commits.

Steps (sequential best-effort; partial success is reported):

1. Read the proposal YAML (defaults to the newest in proposed/).
2. Audit current capabilities (vault + registered tools + skills).
3. Detect blockers — cross-reference strategy.vault_requirements,
   tool_requirements, voice conflicts, budget constraints against
   the live capability map.
4. Write blockers.yaml + blockers.md.
5. Pre-seed voice_proposed.yaml from strategy.creative_directions /
   voice_seed.
6. Create one mission per applied strategy ("<Company> strategy
   execution — <strategy_name>").
7. For each tactic: create one goal with tactic_metadata packed in
   the new column and (when role hints exist) assigned_to_role
   pre-populated.
8. For each timeline entry: create one recurring schedule with a
   cron expression derived from the execution_priority.
9. Promote the proposal: copy to active/strategy.yaml, archive any
   prior active.

Failures are caught per-step and reported in the result data; the
operator can re-run after fixing the issue.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.capability_audit import CapabilityMap, collect_capabilities
from core.strategy import Blocker, save_blockers
from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────


def _tactic_id(t: dict[str, Any]) -> str:
    explicit = t.get("id")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    return f"t{t.get('priority', '?')}"


def _channel_to_role(channel: str) -> str | None:
    """Best-effort hint from channel name to role. Advisory only —
    `assigned_to_role` can still be overridden by agent_role_assignments
    or by the arbiter at cycle time."""
    ch = (channel or "").lower()
    if any(k in ch for k in ("email", "outreach", "cold")):
        return "sales"
    if any(k in ch for k in ("blog", "content", "podcast", "newsletter", "seo", "geo")):
        return "content"
    if any(
        k in ch for k in ("twitter", "x", "linkedin", "social", "instagram", "tiktok")
    ):
        return "marketing"
    if any(k in ch for k in ("paid", "ads", "ppc")):
        return "marketing"
    return None


def _detect_blockers(
    proposal: dict[str, Any], cap: CapabilityMap, voice_yaml: dict[str, Any] | None
) -> list[Blocker]:
    out: list[Blocker] = []
    counter = 1

    # 1. Vault requirements vs vault.list_keys()
    for req in proposal.get("vault_requirements") or []:
        if not isinstance(req, dict):
            continue
        key = str(req.get("key") or "").strip()
        if not key:
            continue
        if cap.vault_locked:
            out.append(
                Blocker(
                    id=f"b{counter:03d}",
                    type="missing_vault_credential",
                    description=(
                        f"Strategy needs vault key `{key}` but vault is "
                        "locked — cannot verify."
                    ),
                    affected_tactics=list(req.get("needed_for_tactics") or []),
                    resolution_proposal="ask",
                    build_hint=str(req.get("note") or ""),
                )
            )
            counter += 1
        elif not cap.has_vault_key(key):
            out.append(
                Blocker(
                    id=f"b{counter:03d}",
                    type="missing_vault_credential",
                    description=(
                        f"Strategy needs vault key `{key}` — not present in vault."
                    ),
                    affected_tactics=list(req.get("needed_for_tactics") or []),
                    resolution_proposal="ask",
                    build_hint=str(req.get("note") or ""),
                )
            )
            counter += 1

    # 2. Tool requirements vs registry
    for req in proposal.get("tool_requirements") or []:
        if not isinstance(req, dict):
            continue
        tool_name = str(req.get("tool_name") or "").strip()
        if not tool_name:
            continue
        if cap.has_tool(tool_name):
            continue
        proposed = str(req.get("resolution_proposal") or "build")
        if proposed not in ("ask", "build", "defer"):
            proposed = "build"
        out.append(
            Blocker(
                id=f"b{counter:03d}",
                type="missing_tool",
                description=(f"Strategy needs tool `{tool_name}` — not registered."),
                affected_tactics=list(req.get("needed_for_tactics") or []),
                resolution_proposal=proposed,
                build_method=(
                    str(req.get("build_method") or "self_create_plugin")
                    if proposed == "build"
                    else None
                ),
                build_hint=str(req.get("build_hint") or ""),
            )
        )
        counter += 1

    # 3. Voice conflict — strategy hookTemplates triggering current
    # voice.yaml banned_phrases. Soft check; voice_yaml may be None.
    if voice_yaml:
        banned = [str(p).lower() for p in (voice_yaml.get("banned_phrases") or [])]
        if banned:
            for cd in (
                proposal.get("creative_directions")
                or proposal.get("creativeDirections")
                or []
            ):
                if not isinstance(cd, dict):
                    continue
                hooks = cd.get("hookTemplates") or cd.get("hook_templates") or []
                for h in hooks:
                    hl = str(h).lower()
                    hit = next((b for b in banned if b in hl), None)
                    if hit:
                        out.append(
                            Blocker(
                                id=f"b{counter:03d}",
                                type="voice_conflict",
                                description=(
                                    f"Strategy hook `{h}` contains banned "
                                    f"phrase `{hit}` per current voice.yaml."
                                ),
                                affected_tactics=[],
                                resolution_proposal="ask",
                                build_hint=(
                                    "Operator decides: revise strategy hook, "
                                    "remove the banned phrase, or accept the "
                                    "exception."
                                ),
                            )
                        )
                        counter += 1
                        break

    # 4. Budget constraint — coarse: if budget > 0 and runway is
    # unknown, no automatic detection. Strategies that opt-in by
    # listing a budget_constraint blocker explicitly are surfaced.
    for risk in proposal.get("risks") or []:
        if isinstance(risk, dict) and "budget" in str(risk.get("risk") or "").lower():
            out.append(
                Blocker(
                    id=f"b{counter:03d}",
                    type="budget_constraint",
                    description=str(risk.get("risk") or ""),
                    affected_tactics=[],
                    resolution_proposal="ask",
                    build_hint=str(risk.get("mitigation") or ""),
                )
            )
            counter += 1

    return out


def _render_blockers_md(blockers: list[Blocker], company_id: str) -> str:
    parts = [f"# Blockers — {company_id}\n"]
    if not blockers:
        parts.append(
            "_No blockers — strategy is fully resolvable with current "
            "capabilities._\n"
        )
        return "\n".join(parts)
    by_type: dict[str, list[Blocker]] = {}
    for b in blockers:
        by_type.setdefault(b.type, []).append(b)
    for btype in sorted(by_type):
        parts.append(f"## {btype}\n")
        for b in by_type[btype]:
            mark = "✅" if b.is_resolved() else "⬜"
            parts.append(f"- {mark} **{b.id}** — {b.description}")
            parts.append(f"  - resolution: **{b.resolution_proposal}**")
            if b.affected_tactics:
                parts.append(f"  - affects tactics: {', '.join(b.affected_tactics)}")
            if b.build_method:
                parts.append(f"  - build method: `{b.build_method}`")
            if b.build_hint:
                parts.append(f"  - hint: {b.build_hint}")
        parts.append("")
    parts.append(
        "_Resolve via `elophanto company blockers resolve <id> "
        "<method>` once an item is unblocked. The autonomous mind "
        "may pick up `resolution=build` items via "
        "`from_buildable_blockers` and invoke self_create_plugin "
        "/ skill_promote (operator approves per call)._\n"
    )
    return "\n".join(parts)


def _seed_voice_proposed(
    proposal: dict[str, Any], project_root: Path, company_id: str
) -> Path | None:
    """Write voice_proposed.yaml from strategy.voice_seed (preferred)
    or aggregated creativeDirections.hookTemplates (fallback). Skips
    when the active voice.yaml already exists — operator-approved
    voice wins."""
    import yaml

    voice_active = project_root / "data" / "companies" / company_id / "voice.yaml"
    if voice_active.is_file():
        return None

    seed = proposal.get("voice_seed") or {}
    if not isinstance(seed, dict):
        seed = {}
    hooks = list(seed.get("hookTemplates") or seed.get("hook_templates") or [])
    banned = list(seed.get("banned_phrases") or [])
    tone = list(seed.get("tone") or [])
    cta = str(seed.get("cta_style") or "")

    if not (hooks or banned or tone or cta):
        # Fall back to creative_directions aggregation
        for cd in (
            proposal.get("creativeDirections")
            or proposal.get("creative_directions")
            or []
        ):
            if isinstance(cd, dict):
                hooks.extend(cd.get("hookTemplates") or cd.get("hook_templates") or [])

    if not hooks and not banned:
        return None

    voice_doc: dict[str, Any] = {}
    if seed.get("persona"):
        voice_doc["persona"] = str(seed["persona"])
    if tone:
        voice_doc["tone"] = [str(t) for t in tone]
    if hooks:
        voice_doc["allowed_hooks"] = [str(h) for h in dict.fromkeys(hooks)]
    if banned:
        voice_doc["banned_phrases"] = [str(p) for p in dict.fromkeys(banned)]
    if cta:
        voice_doc["cta_style"] = cta

    voice_proposed = (
        project_root / "data" / "companies" / company_id / "voice_proposed.yaml"
    )
    voice_proposed.parent.mkdir(parents=True, exist_ok=True)
    voice_proposed.write_text(
        yaml.safe_dump(voice_doc, sort_keys=False), encoding="utf-8"
    )
    return voice_proposed


def _load_active_voice(project_root: Path, company_id: str) -> dict[str, Any] | None:
    import yaml

    path = project_root / "data" / "companies" / company_id / "voice.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _cron_for_timeline(month_key: str, execution_priority: str) -> str:
    """Map a timeline bucket + execution_priority to a cron string.

    Conservative defaults — operator can edit the schedule rows
    afterwards. Different month buckets get different days to
    avoid all schedules firing the same morning.
    """
    if execution_priority == "immediate":
        # Daily at 09:00 for everything
        return "0 9 * * *"
    if execution_priority == "experimental":
        # Weekly review, Mondays 10:00
        return "0 10 * * 1"
    # staged (default) — month1 daily, month2 every-3-days, month3 weekly
    return {
        "month1": "0 9 * * *",
        "month2": "0 9 */3 * *",
        "month3": "0 10 * * 1",
    }.get(month_key, "0 10 * * 1")


# ── Tool ────────────────────────────────────────────────────────────


class CompanyPlanApplyTool(BaseTool):
    def __init__(self) -> None:
        self._project_root: Any = None
        self._registry: Any = None
        self._vault: Any = None
        self._strategy_manager: Any = None
        self._mission_manager: Any = None
        self._goal_manager: Any = None
        self._scheduler: Any = None

    @property
    def name(self) -> str:
        return "company_plan_apply"

    @property
    def group(self) -> str:
        return "companies"

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE

    @property
    def description(self) -> str:
        return (
            "Promote a proposed strategy to active. Atomically creates "
            "mission + goals (with tactic_meta) + schedules + "
            "voice_proposed.yaml + blockers.yaml. Archives prior "
            "active. MODERATE — operator approves the fan-out. See "
            "strategy-pipeline skill."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "proposal_path": {
                    "type": "string",
                    "description": (
                        "Optional — defaults to the newest YAML in "
                        "data/companies/<slug>/strategy/proposed/."
                    ),
                },
            },
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if (
            self._project_root is None
            or self._registry is None
            or self._strategy_manager is None
            or self._mission_manager is None
            or self._goal_manager is None
        ):
            return ToolResult(
                success=False,
                error=(
                    "company_plan_apply not initialized — missing "
                    "project_root / registry / strategy_manager / "
                    "mission_manager / goal_manager."
                ),
            )
        from core.company import current_company_id

        company_id = str(params.get("company_id") or current_company_id())
        proposal_path_raw = params.get("proposal_path")
        proposals = self._strategy_manager.list_proposed(company_id)
        if proposal_path_raw:
            proposal_path = Path(proposal_path_raw)
            if not proposal_path.is_file():
                return ToolResult(
                    success=False, error=f"proposal not found: {proposal_path}"
                )
        else:
            if not proposals:
                return ToolResult(
                    success=False,
                    error=(
                        f"No proposals in data/companies/{company_id}/"
                        "strategy/proposed/. Call company_plan first."
                    ),
                )
            proposal_path = proposals[-1]  # newest by ISO-timestamp sort

        # Load proposal
        try:
            import yaml

            proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
        except Exception as e:
            return ToolResult(success=False, error=f"proposal parse failed: {e}")
        if not isinstance(proposal, dict):
            return ToolResult(
                success=False,
                error="proposal YAML must be a top-level mapping",
            )

        # Capability audit
        cap = collect_capabilities(
            registry=self._registry,
            vault=self._vault,
            project_root=self._project_root,
        )

        # Blocker detection
        voice_active = _load_active_voice(self._project_root, company_id)
        blockers = _detect_blockers(proposal, cap, voice_active)

        # Persist blockers
        try:
            save_blockers(self._project_root, company_id, blockers)
            blockers_md = (
                self._project_root / "data" / "companies" / company_id / "blockers.md"
            )
            blockers_md.parent.mkdir(parents=True, exist_ok=True)
            blockers_md.write_text(
                _render_blockers_md(blockers, company_id), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("blockers persistence failed: %s", e)

        # Voice seed
        voice_proposed_path: Path | None = None
        try:
            voice_proposed_path = _seed_voice_proposed(
                proposal, self._project_root, company_id
            )
        except Exception as e:
            logger.warning("voice_proposed seed failed: %s", e)

        # Mission
        strategy_name = str(proposal.get("strategyName") or "strategy")
        strategy_id = proposal_path.stem
        mission = await self._mission_manager.create(
            title=f"{company_id} — {strategy_name}",
            description=str(proposal.get("overview") or "")[:500],
            priority_weight=1.0,
            owner_role=None,
        )

        # Goals from tactics
        execution_priority = str(proposal.get("execution_priority") or "staged")
        role_assignments_raw = proposal.get("agent_role_assignments") or {}
        if not isinstance(role_assignments_raw, dict):
            role_assignments_raw = {}
        # Invert: tactic_id -> role
        tactic_to_role: dict[str, str] = {}
        for role, ids in role_assignments_raw.items():
            if isinstance(ids, list):
                for tid in ids:
                    tactic_to_role[str(tid)] = str(role)

        created_goal_ids: list[str] = []
        tactics = proposal.get("tactics") or []
        for t in tactics:
            if not isinstance(t, dict):
                continue
            tid = _tactic_id(t)
            channel = str(t.get("channel") or "")
            role = tactic_to_role.get(tid) or _channel_to_role(channel)
            tactic_meta = {
                "strategy_id": strategy_id,
                "tactic_id": tid,
                "priority": t.get("priority"),
                "channel": channel,
                "budget": t.get("budget"),
                "timeline": t.get("timeline"),
                "expectedImpact": t.get("expectedImpact"),
                "riskLevel": t.get("riskLevel"),
                "timeToImpact": t.get("timeToImpact"),
                "dependencies": list(t.get("dependencies") or []),
                "successMetrics": t.get("successMetrics"),
                "inspiredBy": t.get("inspiredBy"),
                "execution_priority": execution_priority,
            }
            goal_text = (str(t.get("description") or t.get("name") or f"tactic {tid}"))[
                :2000
            ]
            try:
                g = await self._goal_manager.create_goal(
                    goal_text,
                    mission_id=mission.mission_id,
                    assigned_to_role=role,
                    tactic_metadata=tactic_meta,
                )
                created_goal_ids.append(g.goal_id)
            except Exception as e:
                logger.warning("tactic %s goal creation failed: %s", tid, e)

        # Schedules from timeline.month1/2/3
        created_schedule_ids: list[str] = []
        timeline = proposal.get("timeline") or {}
        if isinstance(timeline, dict) and self._scheduler is not None:
            # Re-applying a strategy should REFRESH its cadence, not pile up
            # duplicates. The schedule name is stable per (strategy, month), so
            # map existing names → id and drop the prior one before re-creating.
            try:
                _existing_by_name = {
                    s.name: s.id for s in await self._scheduler.list_schedules()
                }
            except Exception:
                _existing_by_name = {}
            for month_key in ("month1", "month2", "month3"):
                entries = timeline.get(month_key) or []
                if not entries:
                    continue
                cron = _cron_for_timeline(month_key, execution_priority)
                # Soft label for the schedule's task_goal
                joined = "; ".join(str(e) for e in entries[:5])
                # Human, month-FIRST name. The old "{company}-{timestamp}-monthN"
                # led with a timestamp, so a truncated sidebar showed all three
                # as "elophanto-20…" — the monthN that differs was past the
                # cutoff. Lead with the month so the phases stay distinguishable
                # at any width.
                _month_n = month_key.removeprefix("month")
                sched_name = f"Month {_month_n} · {(strategy_name or company_id)[:48]}"
                try:
                    # Dedupe: replace a same-named schedule from a prior apply.
                    if sched_name in _existing_by_name:
                        await self._scheduler.delete_schedule(
                            _existing_by_name[sched_name]
                        )
                    sched = await self._scheduler.create_schedule(
                        name=sched_name,
                        task_goal=(
                            f"[{company_id} / {strategy_name}] "
                            f"{month_key} cadence: {joined[:200]}"
                        ),
                        cron_expression=cron,
                        description=(
                            f"Auto-created by company_plan_apply "
                            f"(execution_priority={execution_priority})"
                        ),
                        company_id=company_id,
                    )
                    created_schedule_ids.append(sched.id)
                except Exception as e:
                    logger.warning("schedule create failed for %s: %s", month_key, e)

        # Promote proposal → active (archive prior)
        archived_path: Path | None = None
        try:
            active_path, archived_path = self._strategy_manager.promote_proposal(
                company_id, proposal_path
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=(
                    f"strategy promotion failed AFTER mission+goals "
                    f"were created (mission={mission.mission_id}, "
                    f"goals={len(created_goal_ids)}): {e}. The strategy "
                    "stayed in /proposed/; rerun apply or move manually."
                ),
            )

        unresolved = sum(1 for b in blockers if not b.is_resolved())
        return ToolResult(
            success=True,
            data={
                "company_id": company_id,
                "strategy_id": strategy_id,
                "strategy_name": strategy_name,
                "mission_id": mission.mission_id,
                "goals_created": len(created_goal_ids),
                "goal_ids": created_goal_ids,
                "schedules_created": len(created_schedule_ids),
                "schedule_ids": created_schedule_ids,
                "blockers_total": len(blockers),
                "blockers_unresolved": unresolved,
                "voice_proposed_path": (
                    str(voice_proposed_path) if voice_proposed_path else None
                ),
                "active_path": str(active_path),
                "archived_prior_path": (str(archived_path) if archived_path else None),
                "next": (
                    f"Operator reviews blockers via "
                    f"`elophanto company blockers {company_id}`, "
                    f"resolves them, then runs `company_plan_approve` "
                    f"to mark the strategy as ready for autonomous "
                    f"execution. Voice proposal at "
                    f"{voice_proposed_path or '(none — skipped)'} can be "
                    f"approved via `elophanto voice approve {company_id}`."
                ),
            },
        )


# Local helper for tests / tools that want a count
def detect_blockers(
    proposal: dict[str, Any],
    cap: CapabilityMap,
    voice_yaml: dict[str, Any] | None = None,
) -> list[Blocker]:
    return _detect_blockers(proposal, cap, voice_yaml)


def render_blockers_md(blockers: list[Blocker], company_id: str) -> str:
    return _render_blockers_md(blockers, company_id)


__all__ = [
    "CompanyPlanApplyTool",
    "detect_blockers",
    "render_blockers_md",
]


# Ensure json import is used (touched at the top for any future
# direct dump need; the tool itself currently uses yaml exclusively).
_ = json
