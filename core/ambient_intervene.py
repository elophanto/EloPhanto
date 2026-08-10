"""Ambient interventions — propose → decide → execute with receipts.

act/escalate never auto-approve; they stay proposed until an explicit
operator decision. daily_proposal_count supports the silence cap.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from core.ambient_signals import AmbientSignal
from core.company import current_company_id
from core.database import Database

logger = logging.getLogger(__name__)

STRENGTH_OBSERVE = "observe"
STRENGTH_NUDGE = "nudge"
STRENGTH_ACT = "act"
STRENGTH_ESCALATE = "escalate"
_VALID_STRENGTHS = frozenset(
    {STRENGTH_OBSERVE, STRENGTH_NUDGE, STRENGTH_ACT, STRENGTH_ESCALATE}
)
_AUTO_APPROVE_FORBIDDEN = frozenset({STRENGTH_ACT, STRENGTH_ESCALATE})

STATUS_PROPOSED = "proposed"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
STATUS_EXECUTED = "executed"
STATUS_EXPIRED = "expired"
STATUS_KILLED = "killed"
_VALID_STATUSES = frozenset(
    {
        STATUS_PROPOSED,
        STATUS_APPROVED,
        STATUS_DENIED,
        STATUS_EXECUTED,
        STATUS_EXPIRED,
        STATUS_KILLED,
    }
)
_DECISIONS = frozenset({"approved", "denied"})


@dataclass
class Intervention:
    intervention_id: str
    company_id: str
    strength: str
    channel: str
    proposal: dict[str, Any]
    status: str = STATUS_PROPOSED
    household_id: str | None = None
    prediction_id: str | None = None
    signal_id: str | None = None
    person_id: str | None = None
    receipt: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    decided_at: str | None = None
    executed_at: str | None = None


class InterventionManager:
    """Propose/decide/execute lifecycle for ambient interventions."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def propose_from_prediction(
        self,
        prediction: Any,
        *,
        strength: str = STRENGTH_NUDGE,
        channel: str = "chat",
        proposal: dict[str, Any],
    ) -> Intervention:
        strength = self._validate_strength(strength)
        pred = self._as_mapping(prediction)
        return await self._insert(
            company_id=str(pred.get("company_id") or current_company_id()),
            household_id=pred.get("household_id"),
            prediction_id=pred.get("prediction_id"),
            signal_id=None,
            person_id=pred.get("person_id"),
            strength=strength,
            channel=channel,
            proposal=proposal,
        )

    async def propose_from_signal(
        self,
        signal: AmbientSignal | Any,
        *,
        strength: str = STRENGTH_NUDGE,
        channel: str = "chat",
        proposal: dict[str, Any],
    ) -> Intervention:
        strength = self._validate_strength(strength)
        # Declared up front to match _insert's signature. Without this the
        # types are inferred from whichever branch runs first, and the
        # mapping branch — which legitimately yields None — reads as a
        # violation of a `str` that was never intended to be required.
        company_id: str
        household_id: str | None
        signal_id: str | None
        person_id: str | None
        if isinstance(signal, AmbientSignal):
            company_id = signal.company_id
            household_id = signal.household_id
            signal_id = signal.signal_id
            person_id = signal.subject_ref
        else:
            m = self._as_mapping(signal)
            company_id = str(m.get("company_id") or current_company_id())
            household_id = m.get("household_id")
            signal_id = m.get("signal_id")
            person_id = m.get("subject_ref") or m.get("person_id")
        return await self._insert(
            company_id=company_id,
            household_id=household_id,
            prediction_id=None,
            signal_id=signal_id,
            person_id=person_id,
            strength=strength,
            channel=channel,
            proposal=proposal,
        )

    async def list_by_status(
        self,
        status: str,
        limit: int = 50,
        *,
        company_id: str | None = None,
    ) -> list[Intervention]:
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"invalid intervention status {status!r}; "
                f"must be one of {sorted(_VALID_STATUSES)}"
            )
        cid = company_id or current_company_id()
        rows = await self._db.execute(
            "SELECT * FROM ambient_interventions "
            "WHERE company_id = ? AND status = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (cid, status, int(limit)),
        )
        return [self._row_to_intervention(r) for r in rows]

    async def decide(
        self,
        intervention_id: str,
        decision: str,
        receipt: dict[str, Any],
    ) -> Intervention | None:
        """Operator approve|deny. act/escalate cannot be auto-approved.

        Callers must pass an explicit operator decision; this method never
        soft-approves on timeout for act/escalate.
        """
        if decision not in _DECISIONS:
            raise ValueError(f"invalid decision {decision!r}; must be approved|denied")
        row = await self._get_row(intervention_id)
        if not row:
            return None
        strength = row["strength"]
        if decision == "approved" and strength in _AUTO_APPROVE_FORBIDDEN:
            # Explicit operator path only — still allowed when decide() is
            # called with decision='approved', but receipt must record who.
            if not receipt.get("operator") and not receipt.get("approval_id"):
                raise ValueError(
                    f"strength={strength} requires operator or approval_id "
                    "in receipt; never auto-approve"
                )

        now = datetime.now(UTC).isoformat()
        new_status = STATUS_APPROVED if decision == "approved" else STATUS_DENIED
        merged = self._merge_receipt(row["receipt_json"], receipt)
        merged["decision"] = decision
        await self._db.execute_insert(
            "UPDATE ambient_interventions SET status = ?, receipt_json = ?, "
            "decided_at = ? WHERE intervention_id = ?",
            (new_status, json.dumps(merged), now, intervention_id),
        )
        logger.info(
            "[ambient_intervene] %s decision=%s strength=%s",
            intervention_id,
            decision,
            strength,
        )
        result = await self.get(intervention_id)
        if result is None:
            return None
        if decision == "denied" and result.signal_id:
            # Suppress further noise for the same signal id.
            try:
                from core.ambient_signals import AmbientSignalStore

                store = AmbientSignalStore(self._db)
                await store.suppress(result.signal_id)
            except Exception:
                pass
        if decision == "denied":
            # Standing coach: deny pauses the order (refuseable care).
            try:
                proposal = result.proposal if isinstance(result.proposal, dict) else {}
                coach_id = None
                if proposal.get("claim_type") == "standing_coach":
                    payload = proposal.get("payload") or {}
                    if isinstance(payload, dict):
                        coach_id = payload.get("coach_id")
                    coach_id = coach_id or (proposal.get("features") or {}).get(
                        "coach_id"
                    )
                if not coach_id and result.prediction_id:
                    rows = await self._db.execute(
                        "SELECT features_json FROM ambient_predictions "
                        "WHERE prediction_id = ?",
                        (result.prediction_id,),
                    )
                    if rows:
                        feats = json.loads(rows[0]["features_json"] or "{}")
                        if isinstance(feats, dict):
                            coach_id = feats.get("coach_id")
                if coach_id:
                    from core.ambient_model import AmbientModelManager

                    model = AmbientModelManager(self._db)
                    await model.set_coach_status(str(coach_id), "paused")
                    await model.update_coach_continuity(
                        str(coach_id),
                        {
                            "last_outcome": "denied_paused",
                            "last_note": "Operator denied check-in; order paused",
                        },
                    )
            except Exception:
                pass
        return result

    async def actuate_approved(
        self,
        intervention_id: str,
        *,
        inject_event: Any | None = None,
        create_goal: Any | None = None,
        workspace_dir: Any | None = None,
        personality_manager: Any | None = None,
        ego_manager: Any | None = None,
    ) -> Intervention | None:
        """Bounded help after operator approve for observe/nudge.

        act/escalate stay approved until explicit ambient_intervention_execute.
        Nudge/observe: write a refuseable help artifact (draft/prep/resume),
        inject a mind event (and optional goal), then mark executed.
        """
        from pathlib import Path

        from core.ambient_needs import build_help_artifact, style_help_markdown

        row = await self.get(intervention_id)
        if row is None or row.status != STATUS_APPROVED:
            return row
        if row.strength in _AUTO_APPROVE_FORBIDDEN:
            return row  # wait for explicit execute
        proposal = row.proposal if isinstance(row.proposal, dict) else {}
        need = str(proposal.get("need") or proposal.get("summary") or "")[:200]
        action = str(proposal.get("action") or "")[:240]
        why = str(proposal.get("why") or "")[:240]
        claim_type = proposal.get("claim_type")
        payload: dict[str, Any] = {}
        if isinstance(proposal.get("payload"), dict):
            payload = dict(proposal["payload"])
        elif row.signal_id:
            try:
                sig_rows = await self._db.execute(
                    "SELECT payload_json FROM ambient_signals WHERE signal_id = ?",
                    (row.signal_id,),
                )
                if sig_rows:
                    payload = json.loads(sig_rows[0]["payload_json"] or "{}")
                    if not isinstance(payload, dict):
                        payload = {}
            except Exception:
                payload = {}
        if row.prediction_id and not payload:
            try:
                pred_rows = await self._db.execute(
                    "SELECT features_json, claim FROM ambient_predictions "
                    "WHERE prediction_id = ?",
                    (row.prediction_id,),
                )
                if pred_rows:
                    feats = json.loads(pred_rows[0]["features_json"] or "{}")
                    if isinstance(feats, dict):
                        payload = feats
                    if not need:
                        need = str(pred_rows[0]["claim"] or "")[:200]
            except Exception:
                pass

        artifact_md = build_help_artifact(
            need=need,
            action=action,
            why=why,
            claim_type=str(claim_type) if claim_type else None,
            payload=payload,
            intervention_id=intervention_id,
        )
        style_meta: dict[str, Any] = {}
        try:
            artifact_md, style_meta = await style_help_markdown(
                artifact_md, personality_manager=personality_manager
            )
        except Exception as e:
            logger.debug("ambient help style failed: %s", e)
            style_meta = {"styled": False, "error": str(e)[:120]}
        help_path = ""
        try:
            if workspace_dir is not None:
                base = Path(workspace_dir)
            else:
                base = Path(getattr(self._db, "_db_path", Path("."))).parent
            help_dir = base / "ambient_help"
            help_dir.mkdir(parents=True, exist_ok=True)
            path = help_dir / f"{intervention_id}.md"
            path.write_text(artifact_md, encoding="utf-8")
            help_path = str(path)
        except Exception as e:
            logger.debug("ambient help artifact write failed: %s", e)

        preview = "\n".join(line for line in artifact_md.splitlines() if line.strip())[
            :400
        ]
        # Persist preview on the proposal so UI / brief can show it.
        try:
            merged_proposal = dict(proposal)
            merged_proposal["help_preview"] = preview
            if help_path:
                merged_proposal["help_artifact"] = help_path
            if style_meta:
                merged_proposal["style"] = style_meta
            await self._db.execute_insert(
                "UPDATE ambient_interventions SET proposal_json = ? "
                "WHERE intervention_id = ?",
                (json.dumps(merged_proposal), intervention_id),
            )
        except Exception:
            pass

        event_text = (
            f"[AMBIENT APPROVED] {need} → {action} "
            f"(intervention_id={intervention_id}"
            + (f", artifact={help_path}" if help_path else "")
            + ")"
        )
        if inject_event is not None:
            try:
                inject_event(event_text)
            except Exception as e:
                logger.debug("ambient actuate inject failed: %s", e)
        goal_id = None
        if create_goal is not None and action:
            try:
                goal = await create_goal(
                    f"[ambient] {need}: {action}"[:300],
                    source="ambient_intervention",
                )
                goal_id = getattr(goal, "goal_id", None) or (
                    goal.get("goal_id") if isinstance(goal, dict) else None
                )
            except Exception as e:
                logger.debug("ambient actuate create_goal failed: %s", e)
        if ego_manager is not None:
            try:
                await ego_manager.record_outcome(
                    "ambient_anticipation",
                    True,
                    task_goal=need[:200] or "ambient help",
                    notes=f"approved+actuated {intervention_id}",
                    source="tool",
                )
            except Exception as e:
                logger.debug("ambient ego credit failed: %s", e)
        # Standing coach continuity memory
        try:
            coach_id = None
            if str(claim_type or "") == "standing_coach":
                coach_id = payload.get("coach_id")
            if coach_id:
                from core.ambient_model import AmbientModelManager

                model = AmbientModelManager(self._db)
                await model.update_coach_continuity(
                    str(coach_id),
                    {
                        "last_outcome": "helped",
                        "last_note": (need or action)[:160] or "check-in completed",
                        "last_intervention_id": intervention_id,
                    },
                )
        except Exception as e:
            logger.debug("ambient coach continuity failed: %s", e)
        # If standing coach saw conflicts, queue a separate act-strength protect.
        try:
            conflicts = payload.get("conflicts") if isinstance(payload, dict) else None
            if (
                str(claim_type or "") == "standing_coach"
                and isinstance(conflicts, list)
                and conflicts
            ):
                follow = await self.propose_quiet_hours_protect(
                    parent_intervention_id=intervention_id,
                    conflicts=[str(c) for c in conflicts],
                    coach_id=str(payload.get("coach_id") or "") or None,
                    company_id=row.company_id,
                    household_id=row.household_id,
                    person_id=row.person_id,
                )
                if follow is not None:
                    logger.info(
                        "[ambient_intervene] queued quiet-hours protect %s",
                        follow.intervention_id,
                    )
        except Exception as e:
            logger.debug("ambient protect follow-up failed: %s", e)
        return await self.mark_executed(
            intervention_id,
            {
                "bounded_help": "artifact",
                "help_artifact": help_path or None,
                "help_preview": preview,
                "style": style_meta,
                "event": event_text[:400],
                "goal_id": goal_id,
                "operator": "actuate_approved",
            },
        )

    async def propose_quiet_hours_protect(
        self,
        *,
        parent_intervention_id: str,
        conflicts: list[str],
        coach_id: str | None = None,
        company_id: str | None = None,
        household_id: str | None = None,
        person_id: str | None = None,
    ) -> Intervention | None:
        """Follow-up act proposal: pause conflicting schedules (operator must execute)."""
        if not conflicts:
            return None
        proposal = {
            "need": "Quiet-hours hold for standing coach window",
            "action": "Temporarily disable conflicting scheduled tasks",
            "risk": "medium — pauses automation until hold ends",
            "why": f"Conflicts: {', '.join(str(c)[:40] for c in conflicts[:5])}",
            "claim_type": "quiet_hours_hold",
            "protect_kind": "quiet_hours",
            "conflicts": list(conflicts)[:10],
            "coach_id": coach_id,
            "parent_intervention_id": parent_intervention_id,
            "strength": "act",
            "requires_approval": True,
            "summary": "Quiet-hours hold → pause conflicting schedules",
            "silence_exempt": True,
        }
        return await self.propose(
            strength=STRENGTH_ACT,
            channel="chat",
            proposal=proposal,
            company_id=company_id,
            household_id=household_id,
            person_id=person_id,
        )

    async def apply_quiet_hours_hold(
        self,
        intervention_id: str,
        *,
        hold_hours: float = 3.0,
    ) -> dict[str, Any]:
        """Disable enabled schedules named in proposal.conflicts; return receipt facts."""
        row = await self.get(intervention_id)
        if row is None:
            return {"ok": False, "error": "not found"}
        proposal = row.proposal if isinstance(row.proposal, dict) else {}
        if proposal.get("protect_kind") != "quiet_hours":
            return {"ok": False, "error": "not a quiet_hours protect"}
        conflicts = proposal.get("conflicts") or []
        paused: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        until = (now + timedelta(hours=max(0.5, float(hold_hours)))).isoformat()
        try:
            rows = await self._db.execute(
                "SELECT id, name, enabled FROM scheduled_tasks WHERE enabled = 1"
            )
        except Exception as e:
            return {"ok": False, "error": str(e)[:160]}
        conflict_blob = " ".join(str(c).lower() for c in conflicts)
        for sched in rows or []:
            name = str(sched["name"] or "")
            sid = str(sched["id"])
            if (
                name.lower() in conflict_blob
                or sid in conflict_blob
                or any(name.lower() in str(c).lower() for c in conflicts)
            ):
                await self._db.execute_insert(
                    "UPDATE scheduled_tasks SET enabled = 0, updated_at = ? WHERE id = ?",
                    (now.isoformat(), sid),
                )
                paused.append({"id": sid, "name": name})
        return {
            "ok": True,
            "protect_kind": "quiet_hours",
            "paused": paused,
            "hold_until": until,
            "note": "Schedules paused; re-enable manually or after hold_until",
        }

    async def mark_executed(
        self,
        intervention_id: str,
        receipt: dict[str, Any],
    ) -> Intervention | None:
        row = await self._get_row(intervention_id)
        if not row:
            return None
        strength = row["strength"]
        status = row["status"]
        if status not in (STATUS_APPROVED, STATUS_PROPOSED):
            raise ValueError(f"cannot execute intervention in status={status!r}")
        # act/escalate must be explicitly approved with operator receipt first.
        if strength in _AUTO_APPROVE_FORBIDDEN:
            if status != STATUS_APPROVED:
                raise ValueError(
                    f"strength={strength} requires prior operator approval; "
                    "never soft-execute from proposed"
                )
            if not receipt.get("operator") and not receipt.get("approval_id"):
                raise ValueError(
                    f"strength={strength} requires operator or approval_id "
                    "in execute receipt"
                )
        now = datetime.now(UTC).isoformat()
        merged = self._merge_receipt(row["receipt_json"], receipt)
        await self._db.execute_insert(
            "UPDATE ambient_interventions SET status = ?, receipt_json = ?, "
            "executed_at = ? WHERE intervention_id = ?",
            (STATUS_EXECUTED, json.dumps(merged), now, intervention_id),
        )
        return await self.get(intervention_id)

    async def mark_killed(self, intervention_id: str) -> Intervention | None:
        row = await self._get_row(intervention_id)
        if not row:
            return None
        now = datetime.now(UTC).isoformat()
        merged = self._merge_receipt(
            row["receipt_json"], {"killed_at": now, "reason": "kill_switch"}
        )
        await self._db.execute_insert(
            "UPDATE ambient_interventions SET status = ?, receipt_json = ?, "
            "decided_at = COALESCE(decided_at, ?) WHERE intervention_id = ?",
            (STATUS_KILLED, json.dumps(merged), now, intervention_id),
        )
        logger.info("[ambient_intervene] killed %s", intervention_id)
        return await self.get(intervention_id)

    async def daily_proposal_count(
        self,
        company_id: str | None = None,
        day_iso: str | None = None,
        *,
        timezone: str | None = None,
    ) -> int:
        """Count proposals for the local calendar day (silence cap).

        Uses ``ELOPHANTO_HOUSEHOLD_TZ`` / ``TZ`` / UTC when timezone is
        omitted. Compares against UTC ``created_at`` via local midnight
        bounds so US timezones don't reset the cap mid-afternoon.
        """
        import os
        from zoneinfo import ZoneInfo

        cid = company_id or current_company_id()
        if day_iso:
            # Legacy: treat day_iso as a UTC date prefix (tests may pass this).
            rows = await self._db.execute(
                "SELECT COUNT(*) AS n FROM ambient_interventions "
                "WHERE company_id = ? AND created_at LIKE ?",
                (cid, f"{day_iso[:10]}%"),
            )
        else:
            tz_name = timezone
            if not tz_name:
                try:
                    hh_rows = await self._db.execute(
                        "SELECT timezone FROM households WHERE company_id = ? "
                        "ORDER BY created_at ASC LIMIT 1",
                        (cid,),
                    )
                    if hh_rows and hh_rows[0]["timezone"]:
                        tz_name = str(hh_rows[0]["timezone"])
                except Exception:
                    tz_name = None
            tz_name = (
                tz_name
                or os.environ.get("ELOPHANTO_HOUSEHOLD_TZ")
                or os.environ.get("TZ")
                or "UTC"
            )
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                tz = ZoneInfo("UTC")
            local_now = datetime.now(tz)
            start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_local = start_local + timedelta(days=1)
            start_utc = start_local.astimezone(UTC).isoformat()
            end_utc = end_local.astimezone(UTC).isoformat()
            rows = await self._db.execute(
                "SELECT COUNT(*) AS n FROM ambient_interventions "
                "WHERE company_id = ? AND created_at >= ? AND created_at < ?",
                (cid, start_utc, end_utc),
            )
        if not rows:
            return 0
        return int(rows[0]["n"] or 0)

    async def propose(
        self,
        *,
        strength: str,
        channel: str,
        proposal: dict[str, Any],
        company_id: str | None = None,
        household_id: str | None = None,
        prediction_id: str | None = None,
        signal_id: str | None = None,
        person_id: str | None = None,
    ) -> Intervention:
        """Generic propose entry used by tests and tools."""
        strength = self._validate_strength(strength)
        return await self._insert(
            company_id=company_id or current_company_id(),
            household_id=household_id,
            prediction_id=prediction_id,
            signal_id=signal_id,
            person_id=person_id,
            strength=strength,
            channel=channel,
            proposal=proposal,
        )

    async def has_intervention_for_prediction(
        self,
        prediction_id: str,
        *,
        company_id: str | None = None,
    ) -> bool:
        """True if any ledger row already covers this prediction (any status)."""
        if not prediction_id:
            return False
        cid = company_id or current_company_id()
        rows = await self._db.execute(
            "SELECT intervention_id FROM ambient_interventions "
            "WHERE company_id = ? AND prediction_id = ? LIMIT 1",
            (cid, prediction_id),
        )
        return bool(rows)

    async def get(self, intervention_id: str) -> Intervention | None:
        row = await self._get_row(intervention_id)
        return self._row_to_intervention(row) if row else None

    def may_auto_approve(self, strength: str) -> bool:
        """False for act/escalate — callers must not soft-approve those."""
        return strength not in _AUTO_APPROVE_FORBIDDEN

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _insert(
        self,
        *,
        company_id: str,
        household_id: str | None,
        prediction_id: str | None,
        signal_id: str | None,
        person_id: str | None,
        strength: str,
        channel: str,
        proposal: dict[str, Any],
    ) -> Intervention:
        iid = f"int_{uuid.uuid4().hex[:16]}"
        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "INSERT INTO ambient_interventions "
            "(intervention_id, company_id, household_id, prediction_id, "
            "signal_id, person_id, strength, channel, proposal_json, status, "
            "receipt_json, created_at, decided_at, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, NULL, NULL)",
            (
                iid,
                company_id,
                household_id,
                prediction_id,
                signal_id,
                person_id,
                strength,
                channel,
                json.dumps(proposal or {}),
                STATUS_PROPOSED,
                now,
            ),
        )
        logger.info(
            "[ambient_intervene] proposed %s strength=%s channel=%s",
            iid,
            strength,
            channel,
        )
        return Intervention(
            intervention_id=iid,
            company_id=company_id,
            household_id=household_id,
            prediction_id=prediction_id,
            signal_id=signal_id,
            person_id=person_id,
            strength=strength,
            channel=channel,
            proposal=dict(proposal or {}),
            status=STATUS_PROPOSED,
            receipt={},
            created_at=now,
        )

    async def _get_row(self, intervention_id: str) -> Any | None:
        rows = await self._db.execute(
            "SELECT * FROM ambient_interventions WHERE intervention_id = ?",
            (intervention_id,),
        )
        return rows[0] if rows else None

    @staticmethod
    def _validate_strength(strength: str) -> str:
        if strength not in _VALID_STRENGTHS:
            raise ValueError(
                f"invalid strength {strength!r}; "
                f"must be one of {sorted(_VALID_STRENGTHS)}"
            )
        return strength

    @staticmethod
    def _as_mapping(obj: Any) -> dict[str, Any]:
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "__dataclass_fields__"):
            return {
                k: getattr(obj, k)
                for k in obj.__dataclass_fields__  # type: ignore[attr-defined]
            }
        # sqlite Row / attribute bag
        out: dict[str, Any] = {}
        for key in (
            "company_id",
            "household_id",
            "prediction_id",
            "signal_id",
            "person_id",
            "subject_ref",
        ):
            if hasattr(obj, key):
                out[key] = getattr(obj, key)
            elif hasattr(obj, "__getitem__"):
                try:
                    out[key] = obj[key]
                except (KeyError, IndexError, TypeError):
                    pass
        return out

    @staticmethod
    def _merge_receipt(existing_raw: Any, update: dict[str, Any]) -> dict[str, Any]:
        try:
            base = (
                json.loads(existing_raw or "{}")
                if isinstance(existing_raw, str)
                else dict(existing_raw or {})
            )
        except (json.JSONDecodeError, TypeError):
            base = {}
        if not isinstance(base, dict):
            base = {}
        base.update(update or {})
        return base

    @staticmethod
    def _row_to_intervention(row: Any) -> Intervention:
        try:
            proposal = json.loads(row["proposal_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            proposal = {}
        if not isinstance(proposal, dict):
            proposal = {}
        try:
            receipt = json.loads(row["receipt_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            receipt = {}
        if not isinstance(receipt, dict):
            receipt = {}
        return Intervention(
            intervention_id=row["intervention_id"],
            company_id=row["company_id"],
            household_id=row["household_id"],
            prediction_id=row["prediction_id"],
            signal_id=row["signal_id"],
            person_id=row["person_id"],
            strength=row["strength"],
            channel=row["channel"],
            proposal=proposal,
            status=row["status"] or STATUS_PROPOSED,
            receipt=receipt,
            created_at=row["created_at"] or "",
            decided_at=row["decided_at"],
            executed_at=row["executed_at"],
        )
