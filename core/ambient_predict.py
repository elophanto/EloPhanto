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

            # Any unresolved pred for this routine blocks a new one (cross-day).
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
        """Per-routine calibration: n labeled, miss rate, unknown rate."""
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
        true_n = 0
        false_n = 0
        for row in rows:
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
