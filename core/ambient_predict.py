"""Ambient rule:v1 + hist:v1 predictor — falsifiable routine-window claims.

Tick creates leave_by / chore_due predictions when an active routine's
window is approaching and no recent presence-leave confirms adherence.
resolve_due grades outcomes from presence signals or unknown after resolve_by.
hist:v1 blends historical miss rate once a routine has enough labeled outcomes.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from core.ambient_model import AmbientModelManager, Routine
from core.company import current_company_id
from core.database import Database

logger = logging.getLogger(__name__)

MODEL_RULE_V1 = "rule:v1"
MODEL_HIST_V1 = "hist:v1"
CLAIM_LEAVE_BY = "leave_by"
CLAIM_CHORE_DUE = "chore_due"
CLAIM_REPLY_DUE = "reply_due"
CLAIM_PREP_SCHEDULE = "prep_before_schedule"
CLAIM_PREP_MEETING = "prep_before_meeting"  # real calendar only; not cron
CLAIM_STALE_GOAL = "stale_goal_resume"
# Legacy alias — older rows used meeting language for scheduled_tasks.
_CLAIM_PREP_ALIASES = frozenset({CLAIM_PREP_SCHEDULE, CLAIM_PREP_MEETING})

DEFAULT_LEAD_MINUTES = 30
PRESENCE_LOOKBACK_HOURS = 6
HIST_MIN_LABELED = 5
HIST_RULE_WEIGHT = 0.6
HIST_BLEND_WEIGHT = 0.4
STALE_GRACE = timedelta(hours=24)


@dataclass
class Prediction:
    prediction_id: str
    company_id: str
    claim: str
    claim_type: str
    p_hat: float
    model: str
    resolve_by: str
    household_id: str | None = None
    routine_id: str | None = None
    person_id: str | None = None
    features: dict[str, Any] = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)
    outcome: str | None = None
    resolved_at: str | None = None
    created_at: str = ""


class AmbientPredictor:
    """Rule/hist prediction engine."""

    def __init__(
        self,
        db: Database,
        model_manager: AmbientModelManager | None = None,
        *,
        lead_minutes: int = DEFAULT_LEAD_MINUTES,
    ) -> None:
        self._db = db
        self._model = model_manager or AmbientModelManager(db)
        self._lead_minutes = max(1, int(lead_minutes))

    async def tick(self, company_id: str | None = None) -> list[dict[str, Any]]:
        """Scan active routines; return newly created prediction dicts."""
        cid = company_id or current_company_id()
        now_utc = datetime.now(UTC)
        # Hygiene first so stale unresolved rows don't block forever without grade.
        try:
            await self.resolve_due(company_id=cid, now=now_utc)
            await self.expire_stale(company_id=cid, now=now_utc)
        except Exception as e:
            logger.debug("ambient predict hygiene failed: %s", e)

        created: list[dict[str, Any]] = []
        created.extend(await self._tick_routines(cid, now_utc))
        created.extend(await self._tick_reply_due(cid, now_utc))
        created.extend(await self._tick_schedule_prep(cid, now_utc))
        created.extend(await self._tick_calendar_meetings(cid, now_utc))
        created.extend(await self._tick_stale_goals(cid, now_utc))
        created.extend(await self._tick_standing_coaches(cid, now_utc))
        return created

    async def _tick_routines(self, cid: str, now_utc: datetime) -> list[dict[str, Any]]:
        routines = await self._model.list_active_routines(company_id=cid)
        created: list[dict[str, Any]] = []

        for routine in routines:
            if not routine.window_start:
                continue
            local_now = await self._local_now(routine.household_id, now_utc)
            minutes_left = self._minutes_until_window(routine.window_start, local_now)
            if minutes_left is None:
                continue
            if minutes_left < 0 or minutes_left > self._lead_minutes:
                continue

            if await self._has_unresolved_prediction(cid, routine.routine_id):
                continue

            if routine.person_id and await self._recent_presence_leave(
                cid, routine.person_id, now_utc
            ):
                continue

            claim_type = self._claim_type_for(routine)
            rule_p = round(
                max(0.15, min(0.95, 1.0 - (minutes_left / self._lead_minutes))),
                3,
            )
            p_hat, model, hist_features = await self._blend_hist(
                cid, routine.routine_id, rule_p
            )
            resolve_by = self._resolve_by_iso(
                routine.window_end or routine.window_start, local_now
            )
            claim = (
                f"Will miss routine {routine.title} window starting "
                f"{routine.window_start}"
            )
            features = {
                "minutes_left": minutes_left,
                "lead_minutes": self._lead_minutes,
                "window_start": routine.window_start,
                "window_end": routine.window_end,
                "timezone": getattr(local_now.tzinfo, "key", None)
                or str(local_now.tzinfo),
                "rule_p": rule_p,
                **hist_features,
            }
            pred = await self._insert_prediction(
                company_id=cid,
                household_id=routine.household_id,
                routine_id=routine.routine_id,
                person_id=routine.person_id,
                claim=claim,
                claim_type=claim_type,
                p_hat=p_hat,
                model=model,
                features=features,
                resolve_by=resolve_by,
            )
            created.append(pred)
            logger.info(
                "[ambient_predict] %s claim_type=%s p_hat=%.2f model=%s routine=%s",
                pred["prediction_id"],
                claim_type,
                p_hat,
                model,
                routine.routine_id,
            )

        return created

    async def _tick_reply_due(
        self, cid: str, now_utc: datetime
    ) -> list[dict[str, Any]]:
        """Open high-urgency emails without a reply_due prediction yet."""
        from core.ambient_needs import score_email_urgency

        rows = await self._db.execute(
            "SELECT * FROM ambient_signals "
            "WHERE company_id = ? AND kind = 'email' "
            "AND status IN ('open','consumed') AND urgency >= 0.55 "
            "ORDER BY urgency DESC, received_at DESC LIMIT 10",
            (cid,),
        )
        created: list[dict[str, Any]] = []
        for row in rows:
            sid = row["signal_id"]
            # One open reply_due per signal.
            existing = await self._db.execute(
                "SELECT prediction_id FROM ambient_predictions "
                "WHERE company_id = ? AND claim_type = 'reply_due' "
                "AND outcome IS NULL AND features_json LIKE ? LIMIT 1",
                (cid, f'%"{sid}"%'),
            )
            if existing:
                continue
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            u = max(float(row["urgency"] or 0.55), score_email_urgency(payload))
            subject = str(payload.get("subject") or "email")[:80]
            sender = str(payload.get("from") or payload.get("sender") or "")[:60]
            resolve_by = (now_utc + timedelta(hours=8)).isoformat()
            p_hat, model, hist_features = await self._blend_hist_claim(
                cid, CLAIM_REPLY_DUE, u
            )
            hh_id, person_id = await self._operator_scope(cid)
            pred = await self._insert_prediction(
                company_id=cid,
                household_id=hh_id or row["household_id"],
                routine_id=None,
                person_id=person_id,
                claim=f"Reply due: {subject}" + (f" ({sender})" if sender else ""),
                claim_type=CLAIM_REPLY_DUE,
                p_hat=p_hat,
                model=model,
                features={
                    "signal_id": sid,
                    "urgency": u,
                    "subject": subject,
                    "from": sender,
                    **hist_features,
                },
                resolve_by=resolve_by,
            )
            created.append(pred)
        return created

    async def _tick_schedule_prep(
        self, cid: str, now_utc: datetime
    ) -> list[dict[str, Any]]:
        """Upcoming enabled schedules → prep_before_schedule predictions."""
        try:
            rows = await self._db.execute(
                "SELECT id, name, next_run_at, description FROM scheduled_tasks "
                "WHERE enabled = 1 AND next_run_at IS NOT NULL "
                "ORDER BY next_run_at ASC LIMIT 20",
            )
        except Exception:
            return []
        created: list[dict[str, Any]] = []
        for row in rows:
            next_run = row["next_run_at"] or ""
            try:
                when = datetime.fromisoformat(str(next_run).replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=UTC)
            except ValueError:
                continue
            minutes_left = (when - now_utc).total_seconds() / 60.0
            if minutes_left < 0 or minutes_left > self._lead_minutes:
                continue
            sched_id = str(row["id"])
            existing = await self._db.execute(
                "SELECT prediction_id FROM ambient_predictions "
                "WHERE company_id = ? AND claim_type = ? "
                "AND outcome IS NULL AND features_json LIKE ? LIMIT 1",
                (cid, CLAIM_PREP_SCHEDULE, f'%"{sched_id}"%'),
            )
            if existing:
                continue
            p_hat = round(
                max(0.2, min(0.9, 1.0 - (minutes_left / self._lead_minutes))), 3
            )
            p_hat, model, hist_features = await self._blend_hist_claim(
                cid, CLAIM_PREP_SCHEDULE, p_hat
            )
            name = str(row["name"] or "schedule")[:100]
            hh_id, person_id = await self._operator_scope(cid)
            pred = await self._insert_prediction(
                company_id=cid,
                household_id=hh_id,
                routine_id=None,
                person_id=person_id,
                claim=f"Prep before scheduled task: {name}",
                claim_type=CLAIM_PREP_SCHEDULE,
                p_hat=p_hat,
                model=model,
                features={
                    "schedule_id": sched_id,
                    "minutes_left": int(minutes_left),
                    "next_run_at": next_run,
                    "title": name,
                    "description": str(row["description"] or "")[:300],
                    **hist_features,
                },
                resolve_by=when.isoformat(),
            )
            created.append(pred)
            # Also write a calendar signal for adapters/UI (scheduler source
            # so needs contract does not call this a "meeting").
            try:
                from core.ambient_signals import AmbientSignalStore

                store = AmbientSignalStore(self._db)
                await store.ingest(
                    kind="calendar",
                    source="scheduler",
                    urgency=p_hat,
                    payload={
                        "title": name,
                        "starts_at": next_run,
                        "schedule_id": sched_id,
                    },
                    dedup_key=f"calendar:sched:{sched_id}:{str(next_run)[:13]}",
                )
            except Exception:
                pass
        return created

    async def _tick_calendar_meetings(
        self, cid: str, now_utc: datetime
    ) -> list[dict[str, Any]]:
        """Real calendar events (ICS / non-scheduler calendar signals) → meetings."""
        import os
        from pathlib import Path

        from core.ambient_needs import parse_ics_events

        created: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []

        ics_path = os.environ.get("ELOPHANTO_CALENDAR_ICS", "").strip()
        paths: list[Path] = []
        if ics_path:
            paths.append(Path(ics_path).expanduser())
        try:
            base = Path(getattr(self._db, "_db_path", Path("."))).parent
            paths.append(base / "calendar.ics")
        except Exception:
            pass
        for path in paths:
            try:
                if path.is_file():
                    events.extend(parse_ics_events(path.read_text(encoding="utf-8")))
            except Exception:
                continue

        try:
            rows = await self._db.execute(
                "SELECT * FROM ambient_signals "
                "WHERE company_id = ? AND kind = 'calendar' "
                "AND source != 'scheduler' AND status IN ('open','consumed') "
                "ORDER BY urgency DESC, received_at DESC LIMIT 15",
                (cid,),
            )
        except Exception:
            rows = []
        for row in rows or []:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            if payload.get("schedule_id"):
                continue
            events.append(
                {
                    "uid": row["signal_id"],
                    "title": payload.get("title") or payload.get("name") or "meeting",
                    "starts_at": payload.get("starts_at") or payload.get("dtstart"),
                    "description": payload.get("description") or "",
                    "attendees": payload.get("attendees") or [],
                    "location": payload.get("location") or "",
                    "signal_id": row["signal_id"],
                }
            )

        hh_id, person_id = await self._operator_scope(cid)
        for ev in events:
            starts = str(ev.get("starts_at") or ev.get("dtstart") or "")
            when = self._parse_calendar_dt(starts)
            if when is None:
                continue
            minutes_left = (when - now_utc).total_seconds() / 60.0
            if minutes_left < 0 or minutes_left > self._lead_minutes:
                continue
            uid = str(ev.get("uid") or ev.get("signal_id") or starts)[:80]
            existing = await self._db.execute(
                "SELECT prediction_id FROM ambient_predictions "
                "WHERE company_id = ? AND claim_type = ? "
                "AND outcome IS NULL AND features_json LIKE ? LIMIT 1",
                (cid, CLAIM_PREP_MEETING, f'%"{uid}"%'),
            )
            if existing:
                continue
            rule_p = round(
                max(0.25, min(0.92, 1.0 - (minutes_left / self._lead_minutes))), 3
            )
            p_hat, model, hist_features = await self._blend_hist_claim(
                cid, CLAIM_PREP_MEETING, rule_p
            )
            title = str(ev.get("title") or ev.get("summary") or "meeting")[:100]
            pred = await self._insert_prediction(
                company_id=cid,
                household_id=hh_id,
                routine_id=None,
                person_id=person_id,
                claim=f"Prep before meeting: {title}",
                claim_type=CLAIM_PREP_MEETING,
                p_hat=p_hat,
                model=model,
                features={
                    "calendar_uid": uid,
                    "signal_id": ev.get("signal_id"),
                    "title": title,
                    "starts_at": starts,
                    "description": str(ev.get("description") or "")[:300],
                    "attendees": ev.get("attendees") or [],
                    "location": ev.get("location") or "",
                    "minutes_left": int(minutes_left),
                    **hist_features,
                },
                resolve_by=when.isoformat(),
            )
            created.append(pred)
            if not ev.get("signal_id"):
                try:
                    from core.ambient_signals import AmbientSignalStore

                    store = AmbientSignalStore(self._db)
                    await store.ingest(
                        kind="calendar",
                        source="calendar_ics",
                        urgency=p_hat,
                        payload={
                            "title": title,
                            "starts_at": starts,
                            "description": ev.get("description") or "",
                            "attendees": ev.get("attendees") or [],
                            "uid": uid,
                        },
                        household_id=hh_id,
                        subject_ref=person_id,
                        dedup_key=f"calendar:ics:{uid}:{starts[:13]}",
                    )
                except Exception:
                    pass
        return created

    @staticmethod
    def _parse_calendar_dt(value: str) -> datetime | None:
        import re

        text = (value or "").strip()
        if not text:
            return None
        try:
            m = re.match(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z?$", text)
            if m:
                y, mo, d, h, mi, s = (int(x) for x in m.groups())
                return datetime(y, mo, d, h, mi, s, tzinfo=UTC)
            when = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            return when
        except ValueError:
            return None

    async def _tick_stale_goals(
        self, cid: str, now_utc: datetime
    ) -> list[dict[str, Any]]:
        """Active goals untouched >48h → stale_goal_resume predictions."""
        cutoff = (now_utc - timedelta(hours=48)).isoformat()
        try:
            rows = await self._db.execute(
                "SELECT goal_id, goal, updated_at FROM goals "
                "WHERE status = 'active' AND updated_at <= ? "
                "ORDER BY updated_at ASC LIMIT 5",
                (cutoff,),
            )
        except Exception:
            return []
        created: list[dict[str, Any]] = []
        for row in rows:
            gid = row["goal_id"]
            existing = await self._db.execute(
                "SELECT prediction_id FROM ambient_predictions "
                "WHERE company_id = ? AND claim_type = 'stale_goal_resume' "
                "AND outcome IS NULL AND features_json LIKE ? LIMIT 1",
                (cid, f'%"{gid}"%'),
            )
            if existing:
                continue
            title = str(row["goal"] or gid)[:100]
            p_hat, model, hist_features = await self._blend_hist_claim(
                cid, CLAIM_STALE_GOAL, 0.7
            )
            hh_id, person_id = await self._operator_scope(cid)
            pred = await self._insert_prediction(
                company_id=cid,
                household_id=hh_id,
                routine_id=None,
                person_id=person_id,
                claim=f"Stale goal needs resume: {title}",
                claim_type=CLAIM_STALE_GOAL,
                p_hat=p_hat,
                model=model,
                features={
                    "goal_id": gid,
                    "updated_at": row["updated_at"],
                    "goal": title,
                    **hist_features,
                },
                resolve_by=(now_utc + timedelta(hours=24)).isoformat(),
            )
            created.append(pred)
        return created

    async def _tick_standing_coaches(
        self, cid: str, now_utc: datetime
    ) -> list[dict[str, Any]]:
        """Active multi-day coaches → at most one standing_coach claim / day each."""
        now_iso = now_utc.isoformat()
        day = now_iso[:10]
        try:
            rows = await self._db.execute(
                "SELECT * FROM ambient_coaches "
                "WHERE company_id = ? AND status = 'active' "
                "AND (expires_at IS NULL OR expires_at > ?) "
                "ORDER BY created_at ASC LIMIT 10",
                (cid, now_iso),
            )
        except Exception:
            return []
        created: list[dict[str, Any]] = []
        hh_id, person_id = await self._operator_scope(cid)
        for row in rows:
            last = str(row["last_proposed_at"] or "")
            if last.startswith(day):
                continue
            coach_id = row["coach_id"]
            existing = await self._db.execute(
                "SELECT prediction_id FROM ambient_predictions "
                "WHERE company_id = ? AND claim_type = 'standing_coach' "
                "AND outcome IS NULL AND features_json LIKE ? LIMIT 1",
                (cid, f'%"{coach_id}"%'),
            )
            if existing:
                continue
            title = str(row["title"] or "coach")[:100]
            instruction = str(row["instruction"] or "")[:240]
            try:
                continuity = json.loads(row["continuity_json"] or "{}")
            except (json.JSONDecodeError, TypeError, KeyError):
                continuity = {}
            if not isinstance(continuity, dict):
                continuity = {}
            # Optional: upcoming schedules as "conflicts" hints for protect plan.
            conflicts: list[str] = []
            try:
                scheds = await self._db.execute(
                    "SELECT name, next_run_at FROM scheduled_tasks "
                    "WHERE enabled = 1 AND next_run_at IS NOT NULL "
                    "ORDER BY next_run_at ASC LIMIT 5"
                )
                for s in scheds or []:
                    conflicts.append(
                        f"{s['name']} @ {str(s['next_run_at'] or '')[:16]}"
                    )
            except Exception:
                pass
            pred = await self._insert_prediction(
                company_id=cid,
                household_id=hh_id,
                routine_id=None,
                person_id=person_id,
                claim=f"Standing coach: {title}",
                claim_type="standing_coach",
                p_hat=0.65,
                model=MODEL_RULE_V1,
                features={
                    "coach_id": coach_id,
                    "title": title,
                    "instruction": instruction,
                    "continuity": continuity,
                    "conflicts": conflicts,
                },
                resolve_by=(now_utc + timedelta(hours=20)).isoformat(),
            )
            created.append(pred)
            try:
                await self._model.mark_coach_proposed(coach_id)
            except Exception:
                pass
        return created

    async def resolve_due(
        self,
        *,
        company_id: str | None = None,
        now: datetime | None = None,
    ) -> int:
        """Resolve open predictions past resolve_by. Returns count resolved."""
        cid = company_id or current_company_id()
        now = now or datetime.now(UTC)
        now_iso = now.isoformat()
        rows = await self._db.execute(
            "SELECT * FROM ambient_predictions "
            "WHERE company_id = ? AND outcome IS NULL AND resolve_by <= ?",
            (cid, now_iso),
        )
        resolved = 0
        for row in rows:
            outcome, evidence = await self._grade_outcome(row, now)
            await self._db.execute_insert(
                "UPDATE ambient_predictions SET outcome = ?, resolved_at = ?, "
                "evidence_ids_json = ? WHERE prediction_id = ?",
                (outcome, now_iso, json.dumps(evidence), row["prediction_id"]),
            )
            resolved += 1
            # Credit ego when claims falsify cleanly (did not miss) or miss.
            if outcome in ("true", "false"):
                ego = getattr(self, "_ego_manager", None)
                if ego is not None:
                    try:
                        await ego.record_outcome(
                            "ambient_anticipation",
                            success=(outcome == "false"),
                            task_goal=str(row["claim"] or row["claim_type"])[:200],
                            notes=f"prediction {row['prediction_id']} → {outcome}",
                            source="verification",
                        )
                    except Exception:
                        pass
            logger.info(
                "[ambient_predict] resolved %s outcome=%s evidence=%d",
                row["prediction_id"],
                outcome,
                len(evidence),
            )
        return resolved

    async def expire_stale(
        self,
        *,
        company_id: str | None = None,
        now: datetime | None = None,
    ) -> int:
        """Mark unresolved preds past resolve_by+24h as unknown. Returns count."""
        cid = company_id or current_company_id()
        now = now or datetime.now(UTC)
        cutoff = (now - STALE_GRACE).isoformat()
        now_iso = now.isoformat()
        rows = await self._db.execute(
            "SELECT prediction_id FROM ambient_predictions "
            "WHERE company_id = ? AND outcome IS NULL AND resolve_by <= ?",
            (cid, cutoff),
        )
        if not rows:
            return 0
        for row in rows:
            await self._db.execute_insert(
                "UPDATE ambient_predictions SET outcome = ?, resolved_at = ? "
                "WHERE prediction_id = ? AND outcome IS NULL",
                ("unknown", now_iso, row["prediction_id"]),
            )
        logger.info("[ambient_predict] expired %d stale prediction(s)", len(rows))
        return len(rows)

    async def calibration_summary(
        self, company_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Per-routine + per-claim_type calibration."""
        cid = company_id or current_company_id()
        rows = await self._db.execute(
            "SELECT routine_id, outcome, COUNT(*) AS n FROM ambient_predictions "
            "WHERE company_id = ? AND routine_id IS NOT NULL "
            "GROUP BY routine_id, outcome",
            (cid,),
        )
        by_routine: dict[str, dict[str, int]] = {}
        for row in rows:
            rid = row["routine_id"]
            bucket = by_routine.setdefault(
                rid, {"true": 0, "false": 0, "unknown": 0, "total": 0}
            )
            outcome = row["outcome"] or "unknown"
            if outcome not in ("true", "false", "unknown"):
                outcome = "unknown"
            n = int(row["n"] or 0)
            bucket[outcome] += n
            bucket["total"] += n

        out: list[dict[str, Any]] = []
        for rid, b in sorted(by_routine.items()):
            labeled = b["true"] + b["false"]
            miss_rate = (b["true"] / labeled) if labeled else None
            unknown_rate = (b["unknown"] / b["total"]) if b["total"] else None
            out.append(
                {
                    "routine_id": rid,
                    "claim_type": None,
                    "n": b["total"],
                    "n_labeled": labeled,
                    "n_true": b["true"],
                    "n_false": b["false"],
                    "n_unknown": b["unknown"],
                    "miss_rate": round(miss_rate, 3) if miss_rate is not None else None,
                    "unknown_rate": (
                        round(unknown_rate, 3) if unknown_rate is not None else None
                    ),
                    "hist_ready": labeled >= HIST_MIN_LABELED,
                }
            )

        claim_rows = await self._db.execute(
            "SELECT claim_type, outcome, COUNT(*) AS n FROM ambient_predictions "
            "WHERE company_id = ? AND routine_id IS NULL AND claim_type IS NOT NULL "
            "GROUP BY claim_type, outcome",
            (cid,),
        )
        by_claim: dict[str, dict[str, int]] = {}
        for row in claim_rows:
            ct = row["claim_type"]
            bucket = by_claim.setdefault(
                ct, {"true": 0, "false": 0, "unknown": 0, "total": 0}
            )
            outcome = row["outcome"] or "unknown"
            if outcome not in ("true", "false", "unknown"):
                outcome = "unknown"
            n = int(row["n"] or 0)
            bucket[outcome] += n
            bucket["total"] += n
        for ct, b in sorted(by_claim.items()):
            labeled = b["true"] + b["false"]
            miss_rate = (b["true"] / labeled) if labeled else None
            unknown_rate = (b["unknown"] / b["total"]) if b["total"] else None
            out.append(
                {
                    "routine_id": None,
                    "claim_type": ct,
                    "n": b["total"],
                    "n_labeled": labeled,
                    "n_true": b["true"],
                    "n_false": b["false"],
                    "n_unknown": b["unknown"],
                    "miss_rate": round(miss_rate, 3) if miss_rate is not None else None,
                    "unknown_rate": (
                        round(unknown_rate, 3) if unknown_rate is not None else None
                    ),
                    "hist_ready": labeled >= HIST_MIN_LABELED,
                }
            )
        return out

    async def get(self, prediction_id: str) -> Prediction | None:
        rows = await self._db.execute(
            "SELECT * FROM ambient_predictions WHERE prediction_id = ?",
            (prediction_id,),
        )
        return self._row_to_prediction(rows[0]) if rows else None

    async def list_open(
        self,
        company_id: str | None = None,
        limit: int = 50,
    ) -> list[Prediction]:
        cid = company_id or current_company_id()
        rows = await self._db.execute(
            "SELECT * FROM ambient_predictions "
            "WHERE company_id = ? AND outcome IS NULL "
            "ORDER BY resolve_by ASC LIMIT ?",
            (cid, int(limit)),
        )
        return [self._row_to_prediction(r) for r in rows]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _blend_hist(
        self, company_id: str, routine_id: str, rule_p: float
    ) -> tuple[float, str, dict[str, Any]]:
        rows = await self._db.execute(
            "SELECT outcome, COUNT(*) AS n FROM ambient_predictions "
            "WHERE company_id = ? AND routine_id = ? "
            "AND outcome IN ('true', 'false') GROUP BY outcome",
            (company_id, routine_id),
        )
        return self._blend_from_counts(rows, rule_p)

    async def _blend_hist_claim(
        self, company_id: str, claim_type: str, rule_p: float
    ) -> tuple[float, str, dict[str, Any]]:
        """hist:v1 for digital claim types (reply/prep/stale) without routines."""
        rows = await self._db.execute(
            "SELECT outcome, COUNT(*) AS n FROM ambient_predictions "
            "WHERE company_id = ? AND claim_type = ? AND routine_id IS NULL "
            "AND outcome IN ('true', 'false') GROUP BY outcome",
            (company_id, claim_type),
        )
        return self._blend_from_counts(rows, rule_p)

    def _blend_from_counts(
        self, rows: Any, rule_p: float
    ) -> tuple[float, str, dict[str, Any]]:
        true_n = 0
        false_n = 0
        for row in rows or []:
            if row["outcome"] == "true":
                true_n = int(row["n"] or 0)
            elif row["outcome"] == "false":
                false_n = int(row["n"] or 0)
        labeled = true_n + false_n
        if labeled < HIST_MIN_LABELED:
            return rule_p, MODEL_RULE_V1, {"hist_n": labeled}
        miss_rate = true_n / labeled
        blended = round(
            max(
                0.05,
                min(
                    0.95,
                    HIST_RULE_WEIGHT * rule_p + HIST_BLEND_WEIGHT * miss_rate,
                ),
            ),
            3,
        )
        return (
            blended,
            MODEL_HIST_V1,
            {
                "hist_n": labeled,
                "hist_miss_rate": round(miss_rate, 3),
                "hist_true": true_n,
                "hist_false": false_n,
            },
        )

    async def _operator_scope(self, company_id: str) -> tuple[str | None, str | None]:
        """Primary household + operator person when ambient consent allows."""
        from core.ambient_needs import person_allows_ambient

        try:
            hh = await self._model.get_primary_household(company_id=company_id)
        except Exception:
            hh = None
        if hh is None:
            return None, None
        try:
            person = await self._model.ensure_operator_person(
                hh.household_id, "Operator", company_id=company_id
            )
        except Exception:
            return hh.household_id, None
        if not person_allows_ambient(person.consent):
            return hh.household_id, None
        return hh.household_id, person.person_id

    @staticmethod
    def _claim_type_for(routine: Routine) -> str:
        blob = " ".join(
            [
                routine.title or "",
                " ".join(routine.signal_kinds or []),
                json.dumps(routine.attrs or {}),
            ]
        ).lower()
        if "chore" in blob:
            return CLAIM_CHORE_DUE
        return CLAIM_LEAVE_BY

    @staticmethod
    def _parse_hhmm(value: str) -> tuple[int, int] | None:
        text = (value or "").strip()
        if not text:
            return None
        parts = text.split(":")
        if len(parts) < 2:
            return None
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError:
            return None
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return hour, minute

    async def _local_now(self, household_id: str | None, now: datetime) -> datetime:
        """Wall-clock now in the household timezone (falls back to UTC)."""
        tz_name = "UTC"
        if household_id:
            try:
                hh = await self._model.get_household(household_id)
                if hh and hh.timezone:
                    tz_name = hh.timezone
            except Exception:
                pass
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(tz_name)
        except Exception:
            return now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return now.astimezone(tz)

    def _minutes_until_window(self, window_start: str, now: datetime) -> int | None:
        parsed = self._parse_hhmm(window_start)
        if parsed is None:
            return None
        hour, minute = parsed
        window_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        delta = (window_dt - now).total_seconds() / 60.0
        return int(round(delta))

    def _resolve_by_iso(self, window_end: str, now: datetime) -> str:
        parsed = self._parse_hhmm(window_end)
        if parsed is None:
            return (
                (now + timedelta(minutes=self._lead_minutes))
                .astimezone(UTC)
                .isoformat()
            )
        hour, minute = parsed
        end_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if end_dt < now:
            end_dt += timedelta(days=1)
        return end_dt.astimezone(UTC).isoformat()

    async def _has_unresolved_prediction(
        self, company_id: str, routine_id: str
    ) -> bool:
        rows = await self._db.execute(
            "SELECT prediction_id FROM ambient_predictions "
            "WHERE company_id = ? AND routine_id = ? AND outcome IS NULL LIMIT 1",
            (company_id, routine_id),
        )
        return bool(rows)

    async def _recent_presence_leave(
        self, company_id: str, person_id: str, now: datetime
    ) -> bool:
        since = (now - timedelta(hours=PRESENCE_LOOKBACK_HOURS)).isoformat()
        rows = await self._db.execute(
            "SELECT signal_id, payload_json, subject_ref FROM ambient_signals "
            "WHERE company_id = ? AND kind = ? AND received_at >= ? "
            "AND status IN ('open','consumed') "
            "ORDER BY received_at DESC LIMIT 40",
            (company_id, "presence", since),
        )
        for row in rows:
            if not self._signal_matches_person(row, person_id):
                continue
            if self._is_leave_payload(row["payload_json"]):
                return True
        return False

    async def _grade_outcome(self, row: Any, now: datetime) -> tuple[str, list[str]]:
        """true = missed as claimed; false = did not miss; else unknown."""
        claim_type = str(row["claim_type"] or "")
        try:
            features = json.loads(row["features_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            features = {}
        if not isinstance(features, dict):
            features = {}

        if claim_type == CLAIM_REPLY_DUE:
            return await self._grade_reply_due(row, features, now)
        if claim_type in _CLAIM_PREP_ALIASES:
            return await self._grade_prep_schedule(row, features, now)
        if claim_type == CLAIM_STALE_GOAL:
            return await self._grade_stale_goal(row, features, now)
        if claim_type == "standing_coach":
            # Coach day held if help was executed; otherwise miss/unknown.
            pred_id = row["prediction_id"]
            ints = await self._db.execute(
                "SELECT intervention_id FROM ambient_interventions "
                "WHERE prediction_id = ? AND status = 'executed' LIMIT 1",
                (pred_id,),
            )
            if ints:
                return "false", [ints[0]["intervention_id"]]
            denied = await self._db.execute(
                "SELECT intervention_id FROM ambient_interventions "
                "WHERE prediction_id = ? AND status = 'denied' LIMIT 1",
                (pred_id,),
            )
            if denied:
                return "false", [denied[0]["intervention_id"]]
            return "true", [str(features.get("coach_id") or pred_id)]

        # Routine presence claims (leave_by / chore_due).
        person_id = row["person_id"]
        if not person_id:
            return "unknown", []
        created_at = row["created_at"] or ""
        resolve_by = row["resolve_by"] or now.isoformat()
        signals = await self._db.execute(
            "SELECT signal_id, payload_json, subject_ref, received_at "
            "FROM ambient_signals "
            "WHERE company_id = ? AND kind = ? "
            "AND received_at >= ? AND received_at <= ? "
            "AND status IN ('open','consumed','expired') "
            "ORDER BY received_at ASC",
            (row["company_id"], "presence", created_at, resolve_by),
        )
        evidence: list[str] = []
        left = False
        presence_seen = False
        for sig in signals:
            if not self._signal_matches_person(sig, person_id):
                continue
            presence_seen = True
            evidence.append(sig["signal_id"])
            if self._is_leave_payload(sig["payload_json"]):
                left = True
                break
        if left:
            return "false", evidence  # left in time → did not miss
        if not presence_seen:
            return "unknown", []
        # Presence seen (arrive/home/etc) but never leave → miss.
        return "true", evidence

    async def _grade_reply_due(
        self, row: Any, features: dict[str, Any], now: datetime
    ) -> tuple[str, list[str]]:
        """false = outbound reply evidence; true = still unanswered; else unknown."""
        sid = str(features.get("signal_id") or "")
        subject = str(features.get("subject") or "").strip()
        created_at = row["created_at"] or ""
        resolve_by = row["resolve_by"] or now.isoformat()
        evidence: list[str] = []

        # Outbound email_log matching subject after claim created.
        if subject:
            try:
                logs = await self._db.execute(
                    "SELECT id, message_id, subject, timestamp FROM email_log "
                    "WHERE direction = 'outbound' AND timestamp >= ? "
                    "AND timestamp <= ? AND subject LIKE ? "
                    "ORDER BY timestamp ASC LIMIT 5",
                    (created_at, resolve_by, f"%{subject[:60]}%"),
                )
            except Exception:
                logs = []
            if logs:
                evidence.extend([str(r["message_id"] or r["id"]) for r in logs if r])
                return "false", evidence

        if not sid:
            return "unknown", []

        # Signal suppressed / expired after operator handled or silenced.
        sig_rows = await self._db.execute(
            "SELECT signal_id, status FROM ambient_signals WHERE signal_id = ?",
            (sid,),
        )
        if not sig_rows:
            return "unknown", []
        evidence.append(sid)
        status = str(sig_rows[0]["status"] or "")
        if status == "suppressed":
            # Deny/suppress = operator refused the claim; not a miss.
            return "false", evidence

        # Executed intervention for this signal = help delivered (coached).
        ints = await self._db.execute(
            "SELECT intervention_id, status FROM ambient_interventions "
            "WHERE signal_id = ? AND status = 'executed' LIMIT 3",
            (sid,),
        )
        if ints:
            evidence.extend(str(r["intervention_id"]) for r in ints)
            return "false", evidence

        if status in ("open", "consumed"):
            return "true", evidence
        return "unknown", evidence

    async def _grade_prep_schedule(
        self, row: Any, features: dict[str, Any], now: datetime
    ) -> tuple[str, list[str]]:
        """false = ran/prepped; true = missed prep window."""
        claim_type = str(row["claim_type"] or "")
        sched_id = str(features.get("schedule_id") or "")
        created_at = row["created_at"] or ""
        resolve_by = row["resolve_by"] or now.isoformat()
        evidence: list[str] = []
        pred_id = row["prediction_id"]

        # Shared: prep help already executed → claim falsified (operator ready).
        ints = await self._db.execute(
            "SELECT intervention_id FROM ambient_interventions "
            "WHERE prediction_id = ? AND status = 'executed' LIMIT 1",
            (pred_id,),
        )
        if ints:
            evidence.append(ints[0]["intervention_id"])
            return "false", evidence

        if claim_type == CLAIM_PREP_MEETING or (
            not sched_id and features.get("calendar_uid")
        ):
            uid = str(features.get("calendar_uid") or features.get("signal_id") or "")
            if uid:
                evidence.append(uid)
            # Meeting start passed with no prep executed → miss.
            return "true", evidence or ["meeting"]

        if not sched_id:
            return "unknown", []

        try:
            runs = await self._db.execute(
                "SELECT id, status, completed_at FROM schedule_runs "
                "WHERE schedule_id = ? AND started_at >= ? AND started_at <= ? "
                "ORDER BY started_at ASC LIMIT 5",
                (sched_id, created_at, resolve_by),
            )
        except Exception:
            runs = []
        for r in runs or []:
            evidence.append(f"run:{r['id']}")
            if str(r["status"] or "") in ("ok", "success", "completed", "done"):
                return "false", evidence
            if r["completed_at"]:
                return "false", evidence

        try:
            tasks = await self._db.execute(
                "SELECT id, last_run_at, last_status FROM scheduled_tasks "
                "WHERE id = ?",
                (sched_id,),
            )
        except Exception:
            tasks = []
        if tasks:
            evidence.append(sched_id)
            last_run = str(tasks[0]["last_run_at"] or "")
            if last_run and last_run >= created_at:
                return "false", evidence

        return "true", evidence or [sched_id]

    async def _grade_stale_goal(
        self, row: Any, features: dict[str, Any], now: datetime
    ) -> tuple[str, list[str]]:
        """false = goal touched after claim; true = still stale/active."""
        gid = str(features.get("goal_id") or "")
        created_at = row["created_at"] or ""
        baseline = str(features.get("updated_at") or created_at)
        if not gid:
            return "unknown", []
        try:
            goals = await self._db.execute(
                "SELECT goal_id, status, updated_at FROM goals WHERE goal_id = ?",
                (gid,),
            )
        except Exception:
            return "unknown", []
        if not goals:
            return "unknown", [gid]
        g = goals[0]
        evidence = [gid]
        updated = str(g["updated_at"] or "")
        status = str(g["status"] or "")
        if status in ("completed", "cancelled", "failed", "parked"):
            return "false", evidence
        if updated and updated > baseline:
            return "false", evidence
        ints = await self._db.execute(
            "SELECT intervention_id FROM ambient_interventions "
            "WHERE prediction_id = ? AND status = 'executed' LIMIT 1",
            (row["prediction_id"],),
        )
        if ints:
            evidence.append(ints[0]["intervention_id"])
            return "false", evidence
        if status == "active":
            return "true", evidence
        return "unknown", evidence

    @staticmethod
    def _signal_matches_person(row: Any, person_id: str) -> bool:
        ref = (row["subject_ref"] or "").strip()
        if not ref:
            return False
        if ref == person_id:
            return True
        if ref.endswith(f":{person_id}") or ref.endswith(f"/{person_id}"):
            return True
        if f"person:{person_id}" == ref or f"person_id:{person_id}" == ref:
            return True
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
        if isinstance(payload, dict):
            for key in ("person_id", "person_ref", "subject_ref"):
                val = str(payload.get(key) or "")
                if val == person_id or val.endswith(person_id):
                    return True
        return False

    @staticmethod
    def _is_leave_payload(raw: Any) -> bool:
        try:
            payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (json.JSONDecodeError, TypeError):
            return False
        if not isinstance(payload, dict):
            return False
        transition = str(
            payload.get("transition")
            or payload.get("event")
            or payload.get("state")
            or ""
        ).lower()
        return transition in {"leave", "left", "exit", "depart", "away"}

    @staticmethod
    def _is_arrive_payload(raw: Any) -> bool:
        try:
            payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (json.JSONDecodeError, TypeError):
            return False
        if not isinstance(payload, dict):
            return False
        transition = str(
            payload.get("transition")
            or payload.get("event")
            or payload.get("state")
            or ""
        ).lower()
        return transition in {"arrive", "arrived", "home", "enter", "present"}

    async def _insert_prediction(
        self,
        *,
        company_id: str,
        household_id: str | None,
        routine_id: str | None,
        person_id: str | None,
        claim: str,
        claim_type: str,
        p_hat: float,
        model: str,
        features: dict[str, Any],
        resolve_by: str,
    ) -> dict[str, Any]:
        pid = f"prd_{uuid.uuid4().hex[:16]}"
        now = datetime.now(UTC).isoformat()
        await self._db.execute_insert(
            "INSERT INTO ambient_predictions "
            "(prediction_id, company_id, household_id, routine_id, person_id, "
            "claim, claim_type, p_hat, model, features_json, evidence_ids_json, "
            "resolve_by, outcome, resolved_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, NULL, NULL, ?)",
            (
                pid,
                company_id,
                household_id,
                routine_id,
                person_id,
                claim,
                claim_type,
                p_hat,
                model,
                json.dumps(features),
                resolve_by,
                now,
            ),
        )
        return {
            "prediction_id": pid,
            "company_id": company_id,
            "household_id": household_id,
            "routine_id": routine_id,
            "person_id": person_id,
            "claim": claim,
            "claim_type": claim_type,
            "p_hat": p_hat,
            "model": model,
            "features": features,
            "evidence_ids": [],
            "resolve_by": resolve_by,
            "outcome": None,
            "resolved_at": None,
            "created_at": now,
        }

    @staticmethod
    def _row_to_prediction(row: Any) -> Prediction:
        try:
            features = json.loads(row["features_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            features = {}
        if not isinstance(features, dict):
            features = {}
        try:
            evidence = json.loads(row["evidence_ids_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            evidence = []
        if not isinstance(evidence, list):
            evidence = []
        return Prediction(
            prediction_id=row["prediction_id"],
            company_id=row["company_id"],
            household_id=row["household_id"],
            routine_id=row["routine_id"],
            person_id=row["person_id"],
            claim=row["claim"],
            claim_type=row["claim_type"],
            p_hat=float(row["p_hat"] or 0.0),
            model=row["model"],
            features=features,
            evidence_ids=[str(x) for x in evidence],
            resolve_by=row["resolve_by"],
            outcome=row["outcome"],
            resolved_at=row["resolved_at"],
            created_at=row["created_at"] or "",
        )
