# 83 — Presence Coach: Ego, Thinking & Personality Wiring

> How ambient anticipation plugs into ego, mind, and lived personality —
> and what we deliberately refuse (deception, surveillance, possession).
> Companion to [82 — Ambient Anticipation](82-AMBIENT-ANTICIPATION.md).

---

## Constitution (useful power only)

EloPhanto may steal **notice → refuseable care** and **agency with receipts**.
It refuses: secret sensors, possession of the operator’s life, gaslighting,
and covert impersonation.

Digital presence today. Physical limbs (desk arm, geofenced base, LED,
haptic nudge, labeled meeting avatar) are optional P2 plugins with e-stop —
never default.

---

## What changed in the self-stack

| Layer | Before ambient | Now |
|-------|----------------|-----|
| **Ego** | Soft-gates tools; deny→humbling only | Approve+actuate → `record_outcome(ambient_anticipation, True)`; prediction true/false → verification outcomes; domains `ambient_anticipation` / `ambient_coaching` |
| **Personality** | Lints email/outreach/post drafts | Optional `style_help_markdown` runs `lint_and_enforce` on fenced draft bodies inside `ambient_help/*.md` |
| **Thinking** | Arbiter candidates + inject_event | Standing coaches tick into `standing_coach` predictions → same candidate path |
| **Honesty** | Who-are-you evidence-backed | Unchanged for ambient help (no forced self-disclaimer) |

Still **not** rewritten: planner policy, affect PAD for relational content,
Higgins prose as coach voice, multi-person theory-of-mind ledger.

---

## Standing coaches

Multi-day refuseable orders:

```text
ambient_coach_create  title="Deep work" instruction="Protect 9–12" days=7
ambient_coach_list
ambient_coach_pause   coach_id=… status=paused|retired|active
```

Predictor `_tick_standing_coaches` emits at most one open `standing_coach`
claim per coach per local day. Operator Ok → check-in help; deny/pause stops
the loop. Counts against the ambient silence cap.

---

## Ego credit rules

| Event | Ego signal |
|-------|------------|
| Operator denies intervention | `record_humbling(capability=ambient_anticipation)` (existing) |
| Approve + actuate help | `record_outcome(..., success=True, source=tool)` |
| Prediction resolves `false` (did not miss) | `record_outcome(..., success=True, source=verification)` |
| Prediction resolves `true` (missed as claimed) | `record_outcome(..., success=False, source=verification)` |
| `unknown` | no ego write |

Soft-gate maps ambient decide/execute/list/presence tools →
`ambient_anticipation`; coach tools → `ambient_coaching`.

---

## Presence (digital)

Help artifacts are refuseable coaching notes — no mandatory “I am a software
agent” disclaimer. Meeting joins use the display name `EloPhanto` with an
exit phrase (`EloPhanto leave`). Recording stays opt-in.

Physical limbs (if added later) keep e-stop / geofence brakes without forcing
self-narration about being artificial.

---

## Ethical robotics analogs (P2 — not shipped)

| Limb | Brake |
|------|-------|
| Desk arm (whitelist poses) | E-stop + per-novel-pose approve |
| Mobile base | Geofence + bumper stop |
| Status LED | Force-off while headless OK |
| Wearable haptic | Quiet hours + daily cap |
| Meeting avatar/voice | Labeled AI; no default recording; exit phrase |

Evil twins refused: following people, unlabeled clones, camera household
surveillance, silent physical coercion.

---

## Useful presence score (rubric)

Axes (max 100): Notice 15 · Coach 15 · Protect 15 · Refuseability 15 ·
Presence-with-consent 15 · Actuation 10 · Ego integrity 10 · Embodiment ethics 5.

| Stage | Honest band |
|-------|-------------|
| Ambient spine only | ~62–70 |
| + ego/personality/coach wiring | ~72–80 |
| + coach depth + quiet-hours protect + meeting declare | ~85–88 |
| + P2 ethical robotics | ~88–92 ceiling |

Horror features score 0 and may subtract.

---

## Code map

| Path | Role |
|------|------|
| `core/ego.py` | Capability domains for ambient tools |
| `core/ambient_intervene.py` | Actuate → style + ego credit |
| `core/ambient_needs.py` | Help drafts + `style_help_markdown` |
| `core/ambient_predict.py` | Coach tick; ego on resolve |
| `core/ambient_model.py` | Coach CRUD |
| `tools/ambient/tools.py` | Coach tools |
| `docs/82-AMBIENT-ANTICIPATION.md` | Operator spine |

---

## Follow-ons (not shipped)

1. Affect inference for conflict/repair (high precision) with consent
2. Editable assumption ledger (theory-of-mind for help only)
3. Live Google/Outlook calendar connectors beyond ICS + hooks
4. Physical limb plugins with e-stop (desk arm / base / haptic)
5. Auto-restore quiet-hours holds at `hold_until` without manual re-enable

Shipped since first draft of this doc: ego credit, standing coaches with
continuity, Mind ego/coach surfacing, quiet-hours protect act, labeled
meeting presence declare.
