# 88 — The weekly service: brief, alerts, player comms, regulatory, calendar, trends

*Status: designed and built 2026-08-18 (all sections). Builds on the watch organ
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

## What shipped (2026-08-18)

- **A. Brief** — `core/watch_brief.py` (`field_changes`, `offer_changes`, `build_weekly_brief`,
  `brief_facts`, `render_brief_markdown`, `render_brief_slide`, `narrate_brief`),
  `core/watch_offers.py` (offer facts moved from the tools module), `watch_weekly_brief`.
- **B. Alerts** — `watch_alerts` table, `core/watch_alerts.py` (`detect_alerts`, event /
  voice-spike / regulatory candidates), `WatchManager.record_alerts / list_alerts /
  mark_alerts_notified`, `watch_alerts` tool; a generic `watch` notification type in the
  Telegram, Discord, Slack and CLI adapters.
- **C. Player comms** — `watch_comms` table, `core/watch_comms.py` (`read_comms`,
  `summarize_comms`, inbox naming), `WatchManager.add_comms / list_comms / comms_summary`,
  `watch_comms_setup` / `watch_comms_collect` / `watch_comms`; deck slide, report section,
  workbook sheet, brief lines, snapshot section.
- **D. Regulatory** — `watch_regulatory` table, `core/watch_regulatory.py` (`regulatory_queries`,
  `extract_regulatory` with verified excerpts, `regulatory_calendar`), `WatchManager.add_regulatory /
  list_regulatory / regulatory_calendar`, `watch_regulatory_collect` / `watch_regulatory`; calendar
  slide, report section, brief lines, alerts, snapshot section.
- **E. Smalls** — `core/watch_calendar.py` (`message_category` / `message_categories`,
  `demand_calendar` — computed holidays, paydays, SSA/SSI, tax; supplied events),
  `watch_app_meta` table + `fetch_app_meta` (stored by `watch_voice_collect`) +
  `WatchManager.app_meta_latest` (brief: "shipped app vX"), `WatchManager.trend_series` +
  trends slide (≥ 3 scored cycles across days), calendar slide (`calendar=true`,
  `calendar_events=[…]` on report/deck).
- Schedules from `watch_queue action=schedule`: Friday brief, daily market pulse, 6-hourly alert
  check (direct tool), weekly comms collect (direct tool), weekly regulatory tracking, weekly voice.
- Tests: `test_watch_brief.py`, `test_watch_comms.py`, `test_watch_regulatory.py`,
  `test_watch_smalls.py` — each pins "absent, the pack is unchanged".

## F. Logged-in observation (`core/watch_login.py`, `watch_login`)

The register has always had `customer_state` (`logged_out` · `registered`
· `verified` · `purchaser` · `redeemer` · `vip`), but every collection ran
logged out because nothing logged in — and worse, `watch_observe` /
`watch_analyze` HARDCODED `logged_out`, so evidence gathered with
credentials would have claimed to be what a visitor sees. Both now take
and stamp `customer_state`; a third-party page is never stamped logged-in,
because it looks the same to everyone.

`watch_login` signs the agent's own Chrome in, per brand, with the
credentials the vault holds keyed by domain (`vault_lookup <domain>`):

1. clear the consent overlay **first** — while it is up the login control
   is not reachable and the click lands on the banner;
2. click the visible login control, the way a person does — no URL
   guessing — and when that opens a SIGN-UP panel, click its "already have
   an account" switch; `/login` is a last resort, not the first move;
3. give the form up to 12s to arrive: a login click often *navigates*;
4. complete an e-mail-first step when the password screen comes second;
5. type the credentials, click a checkbox anti-bot widget if one appears
   (a control, like consent — an image or audio puzzle is reported as
   `challenge` and never solved);
6. submit the form's OWN button — scored, because the site header's
   "Log In" link and the "Continue with Apple/Google" buttons both match
   naive text, and some brands keep the real button in a shadow root where
   only the bridge's matcher can reach it;
7. read the verdict from the page: `logged_in`, `already_logged_in`,
   `rejected` (with the site's own message — a stale password, a locked
   account and a failed anti-bot score all read alike, so a human judges),
   `challenge`, `no_form`, `unreachable`.

A page is **logged in only on an account control** — "log out", "my
account", "my profile". "Sweeps coins", "redeem" and "buy coins" are sold
to everyone (LuckyLand's logged-out homepage was once judged "already
logged in" on those words while its header read Sign Up / Login); they
make a verdict *unclear* at most, and never outweigh a Login button.

**Never twice in a row.** Every attempt is stamped and stored — merged into
`workspace/login-checks/results.json`, so a call for one brand keeps every
other brand's verdict (the agent signs in one brand per call); a brand
checked within `retry_after_hours` (default 12) is reported from that
result instead of being signed into again. Repeated failures are how
accounts lock — the cooldown is a safety rail, not an optimisation.

Sessions live in the browser profile, so collection that follows is
unattended: `watch_analyze customer_state='registered'` reads what a
signed-in player sees — coin packages, VIP tiers, real daily bonuses —
and every row says what the session was. `watch_queue action=schedule`
installs *Site sessions · weekly* so the agent refreshes them itself.
`scripts/check_site_logins.py` is a thin CLI over the same code.

## IP policy (smart routing)

The state-pinned residential exit exists to prove **what a Florida customer
sees**, and only storefront observation spends it (`watch_analyze` /
`watch_observe`, exit-verified, stamped on the row). Everything else goes
direct: voice of customer (Reddit, App Store), app meta, regulatory pages,
player-comms reading — no geo claim, no proxy. The browser honours
`proxy.bypass` in config for the same split (bypassed domains leave on the
machine's own IP); reddit.com belongs there. Reddit additionally challenges
fresh automated sessions ("prove your humanity") regardless of IP — the
check is completed once by a human in the agent's Chrome window and the
session persists in the profile copy; the collector's error says exactly
that when it happens.

## Tools added

| tool | what |
|---|---|
| `watch_weekly_brief` | build + render (md, one-slide pptx) + optional notify + snapshot |
| `watch_alerts` | check (detect + store + optional notify) · list |
| `watch_comms_setup` · `watch_comms_collect` · `watch_comms` | player comms |
| `watch_regulatory_collect` · `watch_regulatory` | regulatory register |
| `watch_queue action=schedule` | also installs weekly brief, 6-hourly alerts, daily pulse, weekly comms + regulatory (`service=false` to skip) |

## Build order

1. `core/watch_offers.py` (move) · `core/watch_brief.py` · `watch_weekly_brief` · schedule.
2. `watch_alerts` table/tool · daily pulse + 6-hourly alert schedules.
3. Player comms.
4. Regulatory.
5. Smalls (categories, app meta, calendar, trends).
Docs and capabilities at each step; tests pin "pack unchanged".
