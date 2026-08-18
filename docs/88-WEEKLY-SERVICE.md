# 88 — The weekly service: brief, alerts, player comms, regulatory, calendar, trends

*Status: designed 2026-08-18; built in order below. Builds on the watch organ
([81](81-COMPETITIVE-INTEL.md)) and voice of customer ([87](87-VOICE-OF-CUSTOMER.md)).*

The monthly pack is the product; this turns it into a **weekly service** —
what a steering committee sees every Friday, what wakes them mid-week, and
the two feeds the pack lacked (what brands send players, what regulators do).
Every piece is a reading of registers that already exist, or a new register
of the same shape (append-only, provenance on every row, third-party tagged,
verified excerpts, opinion kept apart from fact). Nothing changes the pack;
each piece adds to it and can stand alone.

## Non-negotiables (same as 87)

1. Existing tables, tool contracts and slides are untouched; a pack rendered
   with none of the new data is the pack it always was.
2. Every new row carries `source_url`, `observed_at`, an excerpt verified
   against the page/mail, and `source_type`/`third_party` where it applies.
3. Register is canon: nothing here adds or archives brands.
4. Same seams: `WatchManager` on the shared `Database`; collectors beside
   `watch_observe`/`watch_voice`; tools via `create_watch_tools()` and the
   `Agent` dependency block; schedules via `watch_queue`; snapshots carry the
   new sections only when present; deck via `watch_deck.py`.

## A. Weekly executive brief (`core/watch_brief.py`, `watch_weekly_brief`)

One page, every Friday. Read from the registers over the last 7 days:

- **Fields that changed** — for each brand × dimension × sub-criterion, the
  newest claim inside the window vs the newest before it; a change is a
  different normalised claim/value. That is the evidence-backed version of
  "the grid's fields that moved this week".
- **Offers that changed** — `offer_facts` (moved from the tools module to
  `core/watch_offers.py`) on evidence up to `since` vs now: welcome/ongoing
  before → after per brand.
- **Market events** this week (`market_events` over `evidence_since`).
- **Score movement** vs the last snapshot (`diff_since_snapshot`), if any.
- **Voice movement** (`diff_voice_since_snapshot`, 7-day summary).
- **Player comms** and **regulatory** lines once B and C exist.
- **Executive request** — a slot: `request` param (the question) and the
  agent's answer folded into the brief.

Rendered as markdown (for channels/e-mail) and a **one-slide pptx** in the
deck's style — three columns: *What changed · Market & players · Decisions*
— plus a footer of counts and sources. The narrator (router) writes one
"so what" per column when available; the computed fallback speaks in facts.
`take_snapshot` (label "weekly brief") so the next week diffs against this.
`notify=true` broadcasts the markdown as a gateway NOTIFICATION (Telegram,
Slack, Discord — whatever is connected). `watch_queue action=schedule`
installs *Weekly executive brief* (Fridays 07:00) as an agent task.

## B. Alerts (`core/watch_alerts.py`, `watch_alerts`)

Table `watch_alerts` (kind: `market_event` · `regulatory` · `voice_spike`;
subject, title, detail, source_url, detected_at, notified_at, dedupe key).
`detect_alerts` reads the last 48h of evidence for market events, the
regulatory register for items with an effective date ≤ 30 days out or newly
observed enforcement, and the 7-day voice summary for a brand-theme with
n ≥ 10, negative share ≥ 0.6 and a rise ≥ 0.2 vs the last snapshot. New
alerts are stored once (dedupe) and, with `notify=true`, broadcast. Scheduled
as a **direct-tool** cron every 6 hours — no LLM in the loop. Alerts can only
be as fresh as collection, so a **daily market pulse** schedule reads every
brand's homepage (`watch_analyze max_pages=1`) each morning: ~14 page loads
a day.

## C. Player comms (`core/watch_comms.py`, `watch_comms_*`)

What brands send players. Per brand: an AgentMail inbox created and tagged
on the subject (`inbox:<address>`), a one-time signup the agent performs in
the browser with the playbook, then a collector that reads new mail from
that inbox and files each message in `watch_comms` (received_at, sender,
subject line, category from a fixed vocabulary — `welcome` · `promo_offer`
· `daily_bonus` · `reactivation` · `vip_loyalty` · `tournament_event` ·
`product_news` · `transactional` · `other` — offer text, verified excerpt,
send weekday/hour). Reading contract like VoC. Deck: *What they send
players* (brand × category counts for the period, cadence per brand, best
offer lines); brief: comms lines; workbook sheet. Tools: `watch_comms_setup`
(inbox + signup instructions), `watch_comms_collect`, `watch_comms`.

## D. Regulatory (`core/watch_regulatory.py`, `watch_regulatory_*`)

Table `watch_regulatory` (jurisdiction, kind: `bill` · `effective_date` ·
`enforcement` · `lawsuit` · `guidance` · `operator_response`; title, status,
event_date, source_url, excerpt, subjects affected, observed_at, dedupe).
Collector: `search_web` per priority state and per brand ("<state>
sweepstakes casino bill", "cease and desist sweepstakes <state>", "<brand>
lawsuit"), `fetch_page_best_effort`, one extraction contract with verified
excerpts, `third_party` provenance. Deck: *Regulatory calendar* (dated
table, next 90 days first) and *operator responses* (who left a state when).
Alerts as in B. Tools: `watch_regulatory_collect`, `watch_regulatory`
(list | calendar). Priority states: param, default the proxy state.

## E. Smalls

- **Message categories** — `message_categories(evidence)` reads promotions
  claims into a fixed vocabulary (deterministic regexes) for the brief and
  a slide; no change to extraction.
- **App meta** — `watch_app_meta` (store, app id, version, rating, count,
  release notes, observed_at) from the iTunes lookup already used by VoC;
  brief line "new release", deck line on deep dives.
- **Demand calendar** — `core/watch_calendar.py`: computed US holidays,
  paydays (1st/15th, last business day), SSA/SSI dates, tax season, plus an
  operator-maintained events list (sports); next 8 weeks on a slide and in
  the brief. Deterministic; sports dates are supplied, not guessed.
- **Trends** — once ≥ 3 snapshots: overall score per brand over time (line
  chart), voice negative share over time; a slide in the pack and the brief.

## Tools added

| tool | what |
|---|---|
| `watch_weekly_brief` | build + render (md, one-slide pptx) + optional notify + snapshot |
| `watch_alerts` | check (detect + store + optional notify) · list |
| `watch_comms_setup` · `watch_comms_collect` · `watch_comms` | player comms |
| `watch_regulatory_collect` · `watch_regulatory` | regulatory register |
| `watch_queue action=schedule` | also installs weekly brief, 6-hourly alerts, daily pulse, weekly comms + regulatory |

## Build order

1. `core/watch_offers.py` (move) · `core/watch_brief.py` · `watch_weekly_brief` · schedule.
2. `watch_alerts` table/tool · daily pulse + 6-hourly alert schedules.
3. Player comms.
4. Regulatory.
5. Smalls (categories, app meta, calendar, trends).
Docs and capabilities at each step; tests pin "pack unchanged".
