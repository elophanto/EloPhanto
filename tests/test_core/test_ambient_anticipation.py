"""Ambient anticipation spine — golden tests for AIA-useful jobs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.ambient_intervene import InterventionManager
from core.ambient_model import AmbientModelManager
from core.ambient_predict import AmbientPredictor
from core.ambient_signals import AmbientSignalStore
from core.database import Database
from core.instinct import Instinct, InstinctStore, make_instinct_id
from core.instinct_match import format_for_prompt, match_instincts
from core.kill_switch import hard_stop, kill_open_interventions
from core.mind_arbiter import Candidate
from core.mind_candidates import CandidateContext, from_external_signals


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "ambient.db")
    await d.initialize()
    yield d
    await d.close()


@pytest.fixture
async def stores(db: Database) -> dict:
    signals = AmbientSignalStore(db)
    model = AmbientModelManager(db)
    interventions = InterventionManager(db)
    predictor = AmbientPredictor(db, model_manager=model)
    return {
        "db": db,
        "signals": signals,
        "model": model,
        "interventions": interventions,
        "predictor": predictor,
    }


class TestAmbientSignals:
    async def test_ingest_and_list_open(self, stores: dict) -> None:
        sid = await stores["signals"].ingest(
            kind="calendar",
            source="test",
            urgency=0.8,
            payload={"title": "standup"},
            dedup_key="cal:standup:1",
        )
        assert sid
        opens = await stores["signals"].list_open(min_urgency=0.5)
        assert any(s.signal_id == sid for s in opens)

    async def test_dedup_bumps_urgency(self, stores: dict) -> None:
        a = await stores["signals"].ingest(
            kind="wake",
            source="hook",
            urgency=0.4,
            dedup_key="same",
            payload={"n": 1},
        )
        b = await stores["signals"].ingest(
            kind="wake",
            source="hook",
            urgency=0.9,
            dedup_key="same",
            payload={"n": 2},
        )
        assert a == b
        sig = await stores["signals"].get(a)
        assert sig is not None
        assert sig.urgency == 0.9


class TestInstinctMatch:
    def test_match_and_format(self, tmp_path: Path) -> None:
        store = InstinctStore(tmp_path / "data", project_hash="t")
        now = datetime.now(UTC).isoformat()
        inst = Instinct(
            id=make_instinct_id("school morning still home", "nudge leave"),
            trigger="school morning still home after window",
            action="nudge leave for school",
            confidence=0.8,
            created_at=now,
            updated_at=now,
        )
        store.save(inst)
        hits = match_instincts(
            store, "school morning still home after window urgency", threshold=0.3
        )
        assert hits
        blob = format_for_prompt(hits)
        assert "matched_instincts" in blob
        assert "nudge leave" in blob


class TestFromExternalSignals:
    async def test_signal_becomes_candidate(self, stores: dict) -> None:
        await stores["signals"].ingest(
            kind="email",
            source="email_monitor",
            urgency=0.7,
            payload={"subject": "deadline Friday"},
        )
        ctx = CandidateContext(
            signal_store=stores["signals"],
            intervention_manager=stores["interventions"],
            max_external_proposals_per_day=3,
        )
        cands = await from_external_signals(ctx)
        assert cands
        assert cands[0].source == "external_signal"
        assert "intervention_id=" in cands[0].action_spec
        assert cands[0].metadata.get("intervention_id")
        # Signal consumed so it cannot flood the next wakeup.
        assert await stores["signals"].list_open() == []

    async def test_instinct_match_boosts_not_blackhole(
        self, stores: dict, tmp_path: Path
    ) -> None:
        store = InstinctStore(tmp_path / "instincts", project_hash="t")
        now = datetime.now(UTC).isoformat()
        store.save(
            Instinct(
                id=make_instinct_id("deadline email", "draft reply"),
                trigger="email deadline Friday",
                action="draft a reply",
                confidence=0.9,
                created_at=now,
                updated_at=now,
            )
        )
        await stores["signals"].ingest(
            kind="email",
            source="email_monitor",
            urgency=0.75,
            payload={"subject": "deadline Friday"},
        )
        ctx = CandidateContext(
            signal_store=stores["signals"],
            intervention_manager=stores["interventions"],
            instinct_store=store,
            max_external_proposals_per_day=3,
        )
        cands = await from_external_signals(ctx)
        assert cands, "instinct match must not crash the generator"
        assert "matched_instincts" in cands[0].action_spec

    async def test_silence_cap_across_wakeups(self, stores: dict) -> None:
        im = stores["interventions"]
        ctx = CandidateContext(
            signal_store=stores["signals"],
            intervention_manager=im,
            max_external_proposals_per_day=3,
        )
        total = 0
        for i in range(10):
            await stores["signals"].ingest(
                kind="wake",
                source="t",
                urgency=0.9,
                payload={"i": i},
                dedup_key=f"wake:{i}",
            )
            cands = await from_external_signals(ctx)
            total += len(cands)
        assert total <= 3
        assert await im.daily_proposal_count() == 3
        # Further wakeups stay silent.
        await stores["signals"].ingest(
            kind="wake", source="t", urgency=0.95, payload={"late": 1}, dedup_key="late"
        )
        assert await from_external_signals(ctx) == []

    async def test_silence_cap_seeded(self, stores: dict) -> None:
        im = stores["interventions"]
        for i in range(3):
            await im.propose(
                strength="nudge",
                channel="chat",
                proposal={"summary": f"p{i}"},
            )
        await stores["signals"].ingest(kind="wake", source="t", urgency=0.9, payload={})
        ctx = CandidateContext(
            signal_store=stores["signals"],
            intervention_manager=im,
            max_external_proposals_per_day=3,
        )
        cands = await from_external_signals(ctx)
        assert cands == []


class TestInterventions:
    async def test_propose_decide_receipt(self, stores: dict) -> None:
        im = stores["interventions"]
        prop = await im.propose(
            strength="nudge",
            channel="chat",
            proposal={"summary": "prep draft"},
        )
        assert prop.status == "proposed"
        decided = await im.decide(
            prop.intervention_id, "approved", receipt={"operator": "test"}
        )
        assert decided is not None
        assert decided.status == "approved"
        executed = await im.mark_executed(
            prop.intervention_id, receipt={"signal_ids": ["x"], "operator": "test"}
        )
        assert executed is not None
        assert executed.status == "executed"

    async def test_act_refuses_soft_execute(self, stores: dict) -> None:
        im = stores["interventions"]
        prop = await im.propose(
            strength="act",
            channel="chat",
            proposal={"summary": "send message", "requires_approval": True},
        )
        with pytest.raises(ValueError, match="prior operator approval"):
            await im.mark_executed(prop.intervention_id, receipt={})
        with pytest.raises(ValueError, match="operator or approval_id"):
            await im.decide(prop.intervention_id, "approved", receipt={})
        decided = await im.decide(
            prop.intervention_id, "approved", receipt={"operator": "ops"}
        )
        assert decided is not None
        with pytest.raises(ValueError, match="operator or approval_id"):
            await im.mark_executed(prop.intervention_id, receipt={})
        executed = await im.mark_executed(
            prop.intervention_id, receipt={"operator": "ops", "outcome": "sent"}
        )
        assert executed is not None
        assert executed.status == "executed"


class TestPredictAndLeaveBy:
    async def test_routine_window_creates_prediction(self, stores: dict) -> None:
        model = stores["model"]
        hh = await model.create_household("ops")
        person = await model.ensure_operator_person(hh.household_id, "Operator")
        now = datetime.now(UTC)
        window = (now + timedelta(minutes=20)).strftime("%H:%M")
        routine = await model.create_routine(
            household_id=hh.household_id,
            title="Morning standup prep",
            window_start=window,
            window_end=(now + timedelta(minutes=40)).strftime("%H:%M"),
            person_id=person.person_id,
        )
        preds = await stores["predictor"].tick()
        assert any(
            (p.get("routine_id") if isinstance(p, dict) else p.routine_id)
            == routine.routine_id
            for p in preds
        )
        open_preds = await stores["predictor"].list_open()
        assert open_preds
        assert open_preds[0].claim_type in ("leave_by", "chore_due")

    async def test_prediction_candidate(self, stores: dict) -> None:
        model = stores["model"]
        hh = await model.create_household("ops2")
        await model.ensure_operator_person(hh.household_id, "Operator")
        now = datetime.now(UTC)
        await model.create_routine(
            household_id=hh.household_id,
            title="Ship checkpoint",
            window_start=(now + timedelta(minutes=15)).strftime("%H:%M"),
        )
        await stores["predictor"].tick()
        ctx = CandidateContext(
            signal_store=stores["signals"],
            predictor=stores["predictor"],
            intervention_manager=stores["interventions"],
            max_external_proposals_per_day=5,
        )
        cands = await from_external_signals(ctx)
        assert any(c.source == "ambient_prediction" for c in cands)

    async def test_prediction_no_repropose_after_decide(self, stores: dict) -> None:
        model = stores["model"]
        im = stores["interventions"]
        hh = await model.create_household("ops3")
        await model.ensure_operator_person(hh.household_id, "Operator")
        now = datetime.now(UTC)
        await model.create_routine(
            household_id=hh.household_id,
            title="Leave for school",
            window_start=(now + timedelta(minutes=12)).strftime("%H:%M"),
        )
        await stores["predictor"].tick()
        ctx = CandidateContext(
            signal_store=stores["signals"],
            predictor=stores["predictor"],
            intervention_manager=im,
            max_external_proposals_per_day=5,
        )
        first = await from_external_signals(ctx)
        assert len(first) == 1
        iid = first[0].metadata["intervention_id"]
        await im.decide(iid, "approved", receipt={"operator": "test"})
        daily_after = await im.daily_proposal_count()
        second = await from_external_signals(ctx)
        assert second == []
        assert await im.daily_proposal_count() == daily_after

    async def test_local_midnight_silence_meter(
        self, stores: dict, monkeypatch
    ) -> None:
        """Proposals just before local midnight must not count on the next local day."""
        from zoneinfo import ZoneInfo

        monkeypatch.setenv("ELOPHANTO_HOUSEHOLD_TZ", "America/New_York")
        im = stores["interventions"]
        tz = ZoneInfo("America/New_York")
        # Insert a row stamped 23:30 local yesterday → should not count today.
        yesterday_local = datetime.now(tz).replace(
            hour=23, minute=30, second=0, microsecond=0
        ) - timedelta(days=1)
        yesterday_utc = yesterday_local.astimezone(UTC).isoformat()
        await stores["db"].execute_insert(
            "INSERT INTO ambient_interventions "
            "(intervention_id, company_id, household_id, prediction_id, "
            "signal_id, person_id, strength, channel, proposal_json, status, "
            "receipt_json, created_at, decided_at, executed_at) "
            "VALUES (?, ?, NULL, NULL, NULL, NULL, 'nudge', 'chat', '{}', "
            "'proposed', '{}', ?, NULL, NULL)",
            ("int_yest", "elophanto-self", yesterday_utc),
        )
        # Today's proposals should be 0 despite the yesterday row.
        assert await im.daily_proposal_count() == 0
        await im.propose(
            strength="nudge", channel="chat", proposal={"summary": "today"}
        )
        assert await im.daily_proposal_count() == 1
        # day_iso legacy path still works for explicit UTC-prefix queries.
        day = yesterday_utc[:10]
        assert await im.daily_proposal_count(day_iso=day) >= 1

    async def test_no_manager_stays_silent(self, stores: dict) -> None:
        await stores["signals"].ingest(
            kind="wake", source="t", urgency=0.9, payload={"x": 1}
        )
        ctx = CandidateContext(
            signal_store=stores["signals"],
            intervention_manager=None,
            max_external_proposals_per_day=3,
        )
        assert await from_external_signals(ctx) == []
        # Signal must remain open (nothing consumed without a ledger).
        assert len(await stores["signals"].list_open()) == 1


class TestTrackBPresenceAndHist:
    async def test_presence_leave_grades_false(self, stores: dict) -> None:
        model = stores["model"]
        hh = await model.create_household("grade-hh")
        person = await model.ensure_operator_person(hh.household_id, "Op")
        now = datetime.now(UTC)
        await model.create_routine(
            hh.household_id,
            "School leave",
            window_start=(now + timedelta(minutes=10)).strftime("%H:%M"),
            window_end=(now + timedelta(minutes=25)).strftime("%H:%M"),
            person_id=person.person_id,
        )
        preds = await stores["predictor"].tick()
        assert preds
        pid = preds[0]["prediction_id"]
        await stores["signals"].ingest(
            kind="presence",
            source="test",
            urgency=0.6,
            payload={"transition": "leave", "person_id": person.person_id},
            subject_ref=person.person_id,
            household_id=hh.household_id,
        )
        resolve_by = (now + timedelta(minutes=2)).isoformat()
        await stores["db"].execute_insert(
            "UPDATE ambient_predictions SET resolve_by = ? WHERE prediction_id = ?",
            (resolve_by, pid),
        )
        n = await stores["predictor"].resolve_due(now=now + timedelta(minutes=5))
        assert n >= 1
        pred = await stores["predictor"].get(pid)
        assert pred is not None
        assert pred.outcome == "false"
        assert pred.evidence_ids

    async def test_presence_home_only_grades_true(self, stores: dict) -> None:
        model = stores["model"]
        hh = await model.create_household("miss-hh")
        person = await model.ensure_operator_person(hh.household_id, "Op")
        now = datetime.now(UTC)
        await model.create_routine(
            hh.household_id,
            "Standup",
            window_start=(now + timedelta(minutes=8)).strftime("%H:%M"),
            person_id=person.person_id,
        )
        preds = await stores["predictor"].tick()
        assert preds
        pid = preds[0]["prediction_id"]
        await stores["signals"].ingest(
            kind="presence",
            source="test",
            urgency=0.4,
            payload={"transition": "home", "person_id": person.person_id},
            subject_ref=person.person_id,
        )
        resolve_by = (now + timedelta(minutes=2)).isoformat()
        await stores["db"].execute_insert(
            "UPDATE ambient_predictions SET resolve_by = ? WHERE prediction_id = ?",
            (resolve_by, pid),
        )
        await stores["predictor"].resolve_due(now=now + timedelta(minutes=5))
        pred = await stores["predictor"].get(pid)
        assert pred is not None
        assert pred.outcome == "true"

    async def test_no_presence_grades_unknown(self, stores: dict) -> None:
        model = stores["model"]
        hh = await model.create_household("unk-hh")
        person = await model.ensure_operator_person(hh.household_id, "Op")
        now = datetime.now(UTC)
        await model.create_routine(
            hh.household_id,
            "Solo",
            window_start=(now + timedelta(minutes=9)).strftime("%H:%M"),
            person_id=person.person_id,
        )
        preds = await stores["predictor"].tick()
        pid = preds[0]["prediction_id"]
        resolve_by = (now + timedelta(minutes=1)).isoformat()
        await stores["db"].execute_insert(
            "UPDATE ambient_predictions SET resolve_by = ? WHERE prediction_id = ?",
            (resolve_by, pid),
        )
        await stores["predictor"].resolve_due(now=now + timedelta(minutes=3))
        pred = await stores["predictor"].get(pid)
        assert pred is not None
        assert pred.outcome == "unknown"

    async def test_hist_blend_after_labeled(self, stores: dict) -> None:
        from core.ambient_predict import MODEL_HIST_V1

        model = stores["model"]
        hh = await model.create_household("hist-hh")
        person = await model.ensure_operator_person(hh.household_id, "Op")
        now = datetime.now(UTC)
        routine = await model.create_routine(
            hh.household_id,
            "Commute",
            window_start=(now + timedelta(minutes=15)).strftime("%H:%M"),
            person_id=person.person_id,
        )
        # Seed 5 labeled outcomes for this routine.
        for i, outcome in enumerate(["true", "true", "false", "true", "false"]):
            await stores["db"].execute_insert(
                "INSERT INTO ambient_predictions "
                "(prediction_id, company_id, household_id, routine_id, person_id, "
                "claim, claim_type, p_hat, model, features_json, evidence_ids_json, "
                "resolve_by, outcome, resolved_at, created_at) "
                "VALUES (?, 'elophanto-self', ?, ?, ?, 'seed', 'leave_by', 0.5, "
                "'rule:v1', '{}', '[]', ?, ?, ?, ?)",
                (
                    f"prd_seed_{i}",
                    hh.household_id,
                    routine.routine_id,
                    person.person_id,
                    now.isoformat(),
                    outcome,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        preds = await stores["predictor"].tick()
        assert preds
        assert preds[0]["model"] == MODEL_HIST_V1
        summary = await stores["predictor"].calibration_summary()
        row = next(r for r in summary if r["routine_id"] == routine.routine_id)
        assert row["hist_ready"] is True
        assert row["n_labeled"] >= 5

    async def test_cross_day_unresolved_blocks(self, stores: dict) -> None:
        model = stores["model"]
        hh = await model.create_household("block-hh")
        person = await model.ensure_operator_person(hh.household_id, "Op")
        now = datetime.now(UTC)
        routine = await model.create_routine(
            hh.household_id,
            "Blocked",
            window_start=(now + timedelta(minutes=12)).strftime("%H:%M"),
            person_id=person.person_id,
        )
        yesterday = (now - timedelta(days=1)).isoformat()
        await stores["db"].execute_insert(
            "INSERT INTO ambient_predictions "
            "(prediction_id, company_id, household_id, routine_id, person_id, "
            "claim, claim_type, p_hat, model, features_json, evidence_ids_json, "
            "resolve_by, outcome, resolved_at, created_at) "
            "VALUES (?, 'elophanto-self', ?, ?, ?, 'old', 'leave_by', 0.5, "
            "'rule:v1', '{}', '[]', ?, NULL, NULL, ?)",
            (
                "prd_old_open",
                hh.household_id,
                routine.routine_id,
                person.person_id,
                (now + timedelta(hours=2)).isoformat(),
                yesterday,
            ),
        )
        preds = await stores["predictor"].tick()
        assert not any(p.get("routine_id") == routine.routine_id for p in preds)

    async def test_household_tz_sync(self, stores: dict, monkeypatch) -> None:
        monkeypatch.setenv("ELOPHANTO_HOUSEHOLD_TZ", "America/Chicago")
        hh = await stores["model"].create_household("tz-hh", timezone="UTC")
        updated = await stores["model"].ensure_household_timezone(hh.household_id)
        assert updated is not None
        assert updated.timezone == "America/Chicago"

    async def test_presence_skipped_as_candidate(self, stores: dict) -> None:
        await stores["signals"].ingest(
            kind="presence",
            source="operator_activity.chat",
            urgency=0.9,
            payload={"transition": "home"},
            subject_ref="per_x",
        )
        ctx = CandidateContext(
            signal_store=stores["signals"],
            intervention_manager=stores["interventions"],
            max_external_proposals_per_day=3,
        )
        cands = await from_external_signals(ctx)
        assert cands == []
        # Presence stays open for grading (not consumed as a proposal).
        assert len(await stores["signals"].list_open()) == 1

    async def test_presence_tool_ingest(self, stores: dict) -> None:
        from tools.ambient.tools import AmbientPresenceReportTool

        model = stores["model"]
        hh = await model.create_household("tool-hh")
        person = await model.ensure_operator_person(hh.household_id, "Op")
        tool = AmbientPresenceReportTool()
        tool._signal_store = stores["signals"]
        tool._ambient_model = model
        result = await tool.execute(
            {"transition": "leave", "person_id": person.person_id}
        )
        assert result.success
        opens = await stores["signals"].list_open()
        assert any(s.kind == "presence" for s in opens)


class TestKillInvariant:
    async def test_killed_intervention(self, stores: dict) -> None:
        im = stores["interventions"]
        prop = await im.propose(
            strength="act",
            channel="chat",
            proposal={"summary": "send message", "requires_approval": True},
        )
        killed = await im.mark_killed(prop.intervention_id)
        assert killed is not None
        assert killed.status == "killed"

    async def test_hard_stop_kills_open(self, stores: dict, tmp_path: Path) -> None:
        im = stores["interventions"]
        await im.propose(strength="nudge", channel="chat", proposal={"summary": "open"})
        await im.propose(
            strength="act", channel="chat", proposal={"summary": "needs ops"}
        )
        n = await kill_open_interventions(stores["db"])
        assert n == 2
        assert await im.list_by_status("proposed") == []
        result = await hard_stop(
            data_dir=tmp_path / "data",
            db=stores["db"],
            kill_interventions=True,
        )
        assert result.killed_interventions == 0  # already killed


class TestCandidateFrozen:
    def test_external_candidate_shape(self) -> None:
        c = Candidate(
            source="external_signal",
            action_spec="test",
            expected_value=5.0,
            feasibility=0.8,
            dedup_key="signal:abc",
            metadata={"strength_hint": "nudge"},
        )
        assert c.stable_dedup_key() == "signal:abc"
