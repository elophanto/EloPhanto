# 89 — Catalog: the raw data behind the scores

*Status: designed and built 2026-08-27. Client ask, verbatim: "game
providers, coin packages, promotions and game list, just need the raw data
and maybe some images for the promotions."*

The organ scores twelve dimensions from claims ([81](81-COMPETITIVE-INTEL.md)),
and a claim is a sentence — "Crown Coins offers over 1,000 games". What a
buyer also wants is the **inventory**: which providers, which price points,
which promotions, which games. That is not a judgement and must not be
scored; it is a list, dated and sourced. So it lives beside the evidence
register as a third class, next to voice ([87](87-VOICE-OF-CUSTOMER.md)) and
player comms ([88](88-WEEKLY-SERVICE.md) §C).

## Non-negotiables

1. The pack is unchanged when nothing is collected; catalog rows never
   enter `score_subject`.
2. Every row carries `source_url`, `observed_at`, the exit IP and the
   session state it was read in — a coin ladder seen as a signed-in
   player in Florida is a different fact from the logged-out one.
3. Items are **verified**: the name must appear on the page it was read
   from, or the row is dropped. Same rule as claims and quotes.
4. Register is canon; nothing here adds or archives brands.

## Data — `watch_catalog`

| column | meaning |
|---|---|
| `catalog_id`, `company_id`, `subject_id` | as elsewhere |
| `kind` | `provider` · `coin_package` · `promotion` · `loyalty_tier` · `game` |
| `name` | the item as printed ("Pragmatic Play", "$29.99", "Sweet Bonanza") |
| `detail` | the rest of the line — terms, category, what the package grants |
| `price_usd` | for `coin_package`, the number; else NULL |
| `coins_text` | "GC 700 + free SC 55" — verbatim, never parsed into a score |
| `sort_index` | position on the page, so a price ladder keeps its order |
| `source_url`, `image_path`, `observed_at`, `exit_ip`, `customer_state` | provenance |
| `dedupe_key` | brand + kind + normalised name — re-collection updates, never duplicates |
| `meta_json` | the kind's structured fields (below) — `gold_coins` / `sweeps_coins`, `benefit` / `how_to_claim` / `frequency`, `qualification` / `reward` |

## Collection (`core/watch_catalog.py`, `watch_catalog_collect`)

**Research first, sign in last.** Nearly all of this is public: the brands
publish their providers, ladders, promotions and lobbies, and review sites
repeat them. So the order is (1) the brand's own public pages, (2) the open
web — targeted queries per kind, the brand's own domain ranked first and
coupon farms last, filed as `third_party` — and only then (3) a signed-in
read, and only for the kinds still empty (`sign_in_if_missing`, reported as
`needs_sign_in`). A session costs proxy traffic and login attempts; those
are spent on what nothing public answers.

Reads default to **direct, no proxy**: a provider list or a game title
carries no geo claim, so the state-pinned exit is not spent on it. Pass
`geo_state` only when the state actually matters (a store's prices).


Per brand: rank its readable pages for each kind (`catalog_page_kind` —
`providers`/`store`/`promotions`/`games` by URL and title), fetch the best
few with the existing `fetch_page_best_effort` (browser escalation
included), and run one extraction contract per kind. Promotions pages are
photographed with `capture_page_screenshot`, and the shot is attached to
every promotion row from that page — the "images for the promotions" the
client asked for, already consent-dismissed.

Signed-in collection matters most here: the coin store and the real
promotions are usually behind a login, so `watch_catalog_collect` takes
`customer_state` and stamps it, exactly as `watch_analyze` now does
([88](88-WEEKLY-SERVICE.md) §F).

## Tables, the client's own layout (2026-09-01)

The client sent two reference pages — a coin-package table with *Gold
coins* and *Sweeps coins* columns, a promotions table of *Promotion ·
Benefit · How to claim · Frequency*, and a loyalty-club table of *Tier ·
Qualification · Reward* — and asked for the same: "easier to read and
more info". So each row now carries the structured fields of its kind in
`meta_json`, and the pack renders them as bordered tables, one fact per
cell:

* **Coin packages** — `parse_coins` reads the two numbers off the grant
  as printed ("120K Gold Coins + 60 SC FREE" → 120,000 / 60), and wins
  over the model's numbers when both exist; a grant it cannot read is shown
  as printed. The 55 of 60 packages already on record were filled from
  their own `coins_text`, no re-collection.
* **Promotions** — the model is asked for benefit, claim route and
  frequency; `parse_frequency` and `parse_claim` (deterministic, first
  match wins, tested on the register's own lines) fill whatever it leaves
  blank, and fill the rows collected before the columns existed. A benefit
  is never legal boilerplate when the title carries the grant ("Get 1.5M CC
  + 75 FREE SC" → "1,500,000 GC + 75 SC"). Empty stays "–".
* **Loyalty tiers** — a fifth kind, `loyalty_tier`, with `qualification`
  and `reward`; collected from the brand's VIP / loyalty page and from the
  known review of the brand.
* **Known review pages** — `known_review_urls(brand)` tries the trusted
  review's predictable URL first (`igamingfuture.com/sweepstakes-casinos/
  reviews/<slug>/`), before any search; trusted hosts outrank generic
  review sites, and the research filter refuses only genuinely legal pages
  so a `/sweepstakes-casinos/…` path is not thrown away as "sweepstakes
  rules".

Per brand, three pages in the appendix: *Coins / Promotions* (the two
tables side by side, the overflow counted into the workbook), *Loyalty
Club* (only when tiers exist), *Providers / Games* (every studio, the
titles read, "+N more in the workbook" when cut). The workbook's sheets
carry the same columns, and a *Loyalty tiers* sheet.

## In the pack

Appendix, after the method slide, only when rows exist:

* **Providers** — brand × provider matrix, ticked; counts per brand.
* **Coin packages** — the price ladder per brand, cheapest to dearest,
  with what each grants; ours highlighted.
* **Promotions** — the table (name, terms, dates) plus the captured
  images, two to a slide.
* **Games** — count per brand and the newest/most-featured titles; the
  full list belongs in the workbook, not on a slide.

The workbook gains one sheet per kind — raw data, one row per item, with
its URL and date. That is the deliverable the client actually asked for;
the slides are the readable summary of it.

## Tools

| tool | what |
|---|---|
| `watch_catalog_collect` | collect one or all kinds for one or all brands; `customer_state`, `geo_state`, `save`, `max_pages` |
| `watch_catalog` | read side: `summary` (counts per brand × kind, price ladders) or `list` (the rows) |

`watch_queue action=schedule` folds catalog collection into the weekly
refresh, after the sessions are signed in.


## Tone of voice (`core/watch_tone.py`)

Added the same day, from the same client conversation. No new collection:
the words are already in the registers — promotions and their terms
(catalog), marketing lines (evidence), and what lands in a player's inbox
(comms). The read is two layers:

* **Measured habits**, deterministic and checkable: share of words in
  CAPITALS, exclamation marks per line, urgency and reward words per 100
  words, emoji per line, second person, line length.
* **A characterisation** — register ("loud and urgent"), two or three
  traits, and a *signature line*. The signature must be one of the brand's
  own sampled lines; a line the model produced that the brand never wrote
  is dropped, and a brand with no samples is never characterised.

One slide (brand · voice · CAPS · !/line · urgency · its own words), a
report section with the traits, and `tone=false` to leave it out. The
measurements alone render when no model is available.
