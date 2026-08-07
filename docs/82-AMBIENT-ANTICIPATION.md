# 82 — Ambient Anticipation

> Notice → know → refuseable help. Digital signals and falsifiable predictions
> become capped proposals the operator can approve, deny, or kill — before
> anything irreversible happens.

---

## Overview

Ambient anticipation is the spine that lets EloPhanto **notice** stress in the
operator’s digital life (email, calendar, schedules, stale goals, routines),
**state a need** in plain language, and after explicit approval **hand over
bounded help** (a draft reply, a meeting prep pack, a resume checkpoint) with a
receipt.

It plugs into the autonomous mind as an arbiter candidate source and into the
Mind UI as the **Anticipation** panel. It does **not** replace the planner,
ego, affect, or personality systems — see
[Boundaries](#boundaries-what-this-does-and-does-not-change).

Related:

- [46 — Proactive Engine](46-PROACTIVE-ENGINE.md) — heartbeat + `/hooks/wake`
- [26 — Autonomous Mind](26-AUTONOMOUS-MIND.md) / [75 — Mind v2](75-AUTONOMOUS-MIND-V2.md) — wakeup + arbiter
- [58 — Instinct Learning](58-INSTINCT-LEARNING.md) — optional boost on matched instincts
- [17 — Identity / Ego](17-IDENTITY.md) — deny records a humbling; no deeper ego rewrite yet
- [18 — Agent Email](18-EMAIL.md) — email monitor can ingest ambient signals

---

## Jobs

| Job | Meaning |
|-----|---------|
| **Notice** | Ingest typed signals (`email`, `calendar`, `wake`, `schedule_fail`, `presence`, …) and tick predictors |
| **Know** | Emit a need contract: `need` → `action` → `risk` → `why` (+ `p_hat`, `claim_type`) |
| **Help** | On approve (observe/nudge): write a refuseable help artifact, inject a mind event, optional goal, mark executed |
| **Brake** | Deny suppresses the signal; `elophanto stop` / hard stop kills open interventions; `consent.ambient=false` silences proposals; daily cap (default 3) |

Irreversible strengths (`act`, `escalate`) stay approved until an explicit
`ambient_intervention_execute` with an operator receipt — never soft-auto.

---

## Boundaries (what this does and does not change)

### What shipped

- Signal store + intervention ledger + life model (household / person / routine)
- Falsifiable predictions (`leave_by`, `chore_due`, `reply_due`,
  `prep_before_schedule`, `prep_before_meeting`, `stale_goal_resume`,
  `standing_coach`) with grading + `hist:v1` calibration where labeled
- Arbiter candidates via `from_external_signals` (silence-capped)
- Mind UI Anticipation + life-model (coaches, ego felt/ambient caution)
- Tools under the `ambient` group (incl. standing coaches)
- Ego: approve→credit, deny→humbling (+ pause coach), prediction true/false→verification
- Personality: optional lint of help drafts / coach narratives
- Standing coaches with continuity; quiet-hours protect; meeting presence declare

### What this does **not** change (yet)

| System | Status |
|--------|--------|
| **Planner core policy** | Ambient is candidates + tools, not a new planning dialect |
| **Affect PAD for relational content** | Still browser/email regex — not conflict/repair coach |
| **Live calendar connectors** | ICS + hooks; not Google/Outlook OAuth |
| **Physical limbs** | Ethical contract in [83](83-PRESENCE-COACH-EGO.md); not shipped |

---

## Architecture

```
Adapters (/hooks/wake, email_monitor, scheduler fail, ICS, presence tool)
        │
        ▼
 ambient_signals ──► from_external_signals ──► intervention ledger (proposed)
        │                      │
        │                      ▼
        │              arbiter candidate (capped)
        │
        ▼
 ambient_predict.tick() ──► ambient_predictions ──► same candidate path
        │
        ▼
 resolve_due / expire_stale ──► outcomes ──► hist:v1 / calibration_summary

Operator Ok (Mind UI / ambient_intervention_decide)
        │
        ▼
 actuate_approved → ambient_help/*.md + mind inject + receipt (executed)
```

### Core modules

| Module | Role |
|--------|------|
| `core/ambient_signals.py` | Ingest / list / consume / suppress / expire |
| `core/ambient_needs.py` | Need contract, email urgency, filled help drafts, ICS parse, consent helper |
| `core/ambient_intervene.py` | Propose → decide → actuate / execute / kill; daily proposal count |
| `core/ambient_predict.py` | Rule + hist predictors; digital + routine claims; grading |
| `core/ambient_model.py` | Households, persons, places, routines |
| `core/mind_candidates.py` | `from_external_signals` |
| `tools/ambient/tools.py` | Operator/agent tools |
| Mind UI | `web/src/components/mind/MindPage.tsx` Anticipation + life-model cards |

### Data (SQLite)

Tables (created with the rest of the schema): `ambient_signals`,
`ambient_predictions`, `ambient_interventions`, `households`, `persons`,
`places`, `routines`. Interventions unique on `prediction_id` so one claim
cannot flood the ledger.

---

## Need contract

Every proposal carries:

```text
NEED:   what the operator is about to miss or must face
ACTION: bounded help (draft / prep / diagnose) — not silent send
RISK:   why this strength is safe or gated
WHY:    evidence + source + urgency / p_hat
KILL:   deny or /stop
```

Built in `core/ambient_needs.py` (`proposal_from_signal`,
`proposal_from_prediction`, `build_help_artifact`).

---

## Prediction claim types

| Claim | Source | Grades on |
|-------|--------|-----------|
| `leave_by` / `chore_due` | Active routines + presence | Presence leave vs home-only |
| `reply_due` | High-urgency email signals | Outbound `email_log`, suppress, or executed help |
| `prep_before_schedule` | Enabled `scheduled_tasks` in lead window | Schedule run / `last_run_at` / executed prep |
| `prep_before_meeting` | ICS file or non-scheduler calendar signals | Prep executed → false; else miss after resolve |
| `stale_goal_resume` | Active goals untouched >48h | Goal touch / status / executed help |

Cron and meetings are **not** the same claim. Scheduler rows use
`prep_before_schedule` and “scheduled task” language. Real meetings use
`prep_before_meeting`.

After enough labeled outcomes (`hist_n ≥ 5`), digital claims blend
`rule:v1` with `hist:v1` via `_blend_hist_claim`. `ambient_calibration_show`
lists per-routine and per-`claim_type` buckets.

---

## Prep before meeting

This is the highest-value coaching surface for calendar stress.

### Inputs

1. **ICS file** — `ELOPHANTO_CALENDAR_ICS=/path/to.ics`, or `calendar.ics`
   next to the agent DB directory
2. **Calendar signals** — `kind=calendar`, `source` ≠ `scheduler`, no
   `schedule_id` in payload (via `/hooks/wake` or tools)

Predictor: `AmbientPredictor._tick_calendar_meetings` (same lead window as
routines, default 30 minutes).

### On approve

`build_help_artifact` writes a **filled meeting prep pack**:

- Title + start time
- Attendees when present
- Goal / open threads / decisions / artifacts / first five minutes — filled
  from description and title, not blank checklist placeholders

File: `{workspace_or_db_parent}/ambient_help/{intervention_id}.md`  
Mind UI shows `help_preview` on Done rows.

### Example ICS

```ics
BEGIN:VCALENDAR
BEGIN:VEVENT
UID:design-review-1
SUMMARY:Design review
DTSTART:20260807T180000Z
DESCRIPTION:Ship checklist + open PRs
ATTENDEE:mailto:alex@example.com
END:VEVENT
END:VCALENDAR
```

### Example wake ingest

```bash
curl -sS -X POST http://127.0.0.1:18789/hooks/wake \
  -H "Content-Type: application/json" \
  -d '{
    "event": "Upcoming design review",
    "kind": "calendar",
    "source": "calendar_hook",
    "urgency": 0.85,
    "payload": {
      "title": "Design review",
      "starts_at": "2026-08-07T18:00:00+00:00",
      "description": "Ship checklist + open PRs",
      "attendees": ["alex@example.com"]
    },
    "dedup_key": "cal:design-review:2026-08-07"
  }'
```

(Add `Authorization: Bearer …` when webhooks auth is configured.)

---

## Silence, consent, kill

| Control | Behavior |
|---------|----------|
| Daily cap | `autonomous_mind.arbiter.max_external_proposals_per_day` (default **3**), counted in household TZ when set |
| Deny | Intervention `denied`; linked signal **suppressed**; optional ego humbling |
| `consent.ambient=false` on operator person | `from_external_signals` returns no proposals |
| `elophanto stop` / gateway hard stop | All `proposed`/`approved` interventions → `killed` |
| Presence signals | Evidence for routine grading only — never burn the silence cap as candidates |

---

## Operator surfaces

### Mind UI — Anticipation

Buckets: **Proposed** | **Waiting** (approved, waiting execute) | **Done** |
**Ignored** (denied/killed/expired).

Each brief shows need, action, strength, `p_hat`, `claim_type`, why, and after
actuation a help preview.

Life-model cards show household timezone, persons, routines, and calibration.

### Tools (`ambient` group)

| Tool | Purpose |
|------|---------|
| `ambient_intervention_list` | Filter by status |
| `ambient_intervention_decide` | `approved` \| `denied` (+ actuate for observe/nudge) |
| `ambient_intervention_execute` | Receipt for act/escalate |
| `ambient_presence_report` | Digital presence evidence (`leave` / `home` / …) |
| `ambient_household_show` / `ambient_household_set_timezone` | Household |
| `ambient_person_list` / `ambient_person_create` | Persons |
| `ambient_routine_list` / `ambient_routine_create` / `ambient_routine_pause` | Routines |
| `ambient_calibration_show` | Miss / unknown rates |

### Webhooks

`POST /hooks/wake` accepts ambient fields: `kind`, `source`, `urgency`,
`payload`, `dedup_key`, `household_id`, `subject_ref`, `expires_at`. Heartbeat
must be running or the hook returns 503.

---

## How to verify

### Automated

```bash
.venv/bin/python -m pytest tests/test_core/test_ambient_anticipation.py -q
```

### Live dogfood (email → Ok → artifact)

1. Gateway + heartbeat + autonomous mind running; Mind page open
2. Ingest a high-urgency email via `/hooks/wake` (`kind=email`, deadline/VIP language in subject)
3. Wait for a mind wakeup → Anticipation **Proposed**
4. Click **Ok** → **Done** + `ambient_help/int_….md` with **Draft reply (do not send)**
5. `elophanto stop` while something is proposed → status `killed`

### Live dogfood (prep before meeting)

1. Place `calendar.ics` beside the DB (or set `ELOPHANTO_CALENDAR_ICS`) with a
   `VEVENT` starting inside the lead window (~30 minutes)
2. Mind wakeup → claim `prep_before_meeting`
3. **Ok** → filled meeting prep pack on disk + preview in UI

---

## Configuration

```yaml
autonomous_mind:
  arbiter:
    max_external_proposals_per_day: 3   # silence cap
```

Environment:

| Variable | Purpose |
|----------|---------|
| `ELOPHANTO_CALENDAR_ICS` | Path to ICS for meeting prep ticks |
| `ELOPHANTO_HOUSEHOLD_TZ` / `TZ` | Fallback when household timezone unset |

Predictor lead window defaults to 30 minutes (`AmbientPredictor(lead_minutes=…)`).

---

## Follow-ons (not shipped)

Honest gap list for anyone wiring this into “how it thinks”:

1. Feed ambient outcomes into ego caution / felt_state (not only deny humbling)
2. Personality-styled help drafts (voice.yaml / lived personality) instead of
   template fill only
3. Standing multi-day coaching orders distinct from HEARTBEAT.md
4. Live calendar connectors (Google / Outlook) beyond ICS + hooks
5. Multi-person ACL beyond operator `consent.ambient`

---

## Code map

| Path | Notes |
|------|-------|
| `core/ambient_*.py` | Spine |
| `core/mind_candidates.py` | `from_external_signals` |
| `core/kill_switch.py` | `kill_open_interventions` |
| `cli/stop_cmd.py` | Always sweeps ambient on stop |
| `core/gateway.py` | Wake ingest + Mind ambient status + decide actuate |
| `tools/ambient/tools.py` | Tool surface |
| `tests/test_core/test_ambient_anticipation.py` | Goldens |
