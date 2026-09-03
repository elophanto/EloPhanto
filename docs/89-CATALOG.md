# 89 — Catalog: the raw data behind the scores

*Status: designed and built 2026-08-27. Client ask, verbatim: "game
providers, coin packages, promotions and game list, just need the raw data
and maybe some images for the promotions."*

The organ scores twelve dimensions from claims ([81](81-COMPETITIVE-INTEL.md)),
and a claim is a sentence — "Brand C offers over 1,000 games". What a
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

"Nothing public answers" is `found < min_items` (default 1). Three teaser
titles on a homepage are not a lobby: `min_items=10` on `provider,game`
sends a brand with a thin public catalogue to research and then, still
short, to `needs_sign_in` — that is how the first full run (2026-09-01)
left Brand G at 3 games and Brand B at 3: they counted as answered.

**A signed-in read goes through the browser, never HTTP.** A session lives
in the Chrome profile; an HTTP client has no cookies, so a "registered"
read over HTTP sees the logged-out site — which is why the first two
registered re-reads (2026-09-01/02) wrote nothing while Brand A's and Hello
Millions' lobbies were live sessions. `read_signed_in_pages` opens the
lobby as the player the browser already is, scrolls so the lazy-loaded
grid is in the DOM, then clicks through to Providers, Get Coins /
Store, Promotions and VIP, reading each page's DOM; a modal (an updated
Terms of Use, a promo) is read through, never accepted on the player's
behalf. Pages are filed by the kind their title names and stamped with
the session.

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

## Game portfolio — the client's own matrix (2026-09-01)

The client's sheet (`game_portfolio.csv`, semicolon-separated) is a
Provider × Brand matrix: column A their studio list (59 names), the header
row their brand columns, every cell empty for us to fill. So:

* `canonical_provider` gives one key per studio however it is printed —
  "BGaming" / "B Gaming" / "BGAMING", "Relax" / "Relax Gaming", "2×2" /
  "2 By 2", "4TP" / "4ThePlayer", "Gamzik" / "Gamzix" — while the rows in
  the register stay as printed. 136 printed forms collapse to 127 studios.
* `read_provider_universe(path)` reads their sheet; `brand_key` matches
  their brand labels to the register's ("Brand H" = "Brand H
  Slots", "Brand G" = "Brand G").
* `provider_matrix(items, brands, universe, universe_brands)` builds the
  matrix. With their list, rows follow it first — including studios on the
  list that nothing has shown yet (empty row, grey on the slide), so the
  gap is visible — then studios we observed that are not on their list,
  marked `*`. A cell is ● when the brand carries the studio (a site read
  beats a review read), with the number of that studio's titles read when
  any; a game's `detail` counts as its studio only when it names a known
  studio, so "Jackpot Slots" never becomes a provider. Brands only on
  their sheet (Brand F) and only in the register are reported, never
  reconciled — the register is canon.
* Deck: *Game portfolio – N studios × M brands (i of k)*, 20 rows a page,
  every studio; replaces the twelve-most-common slide. Workbook: a *Game
  portfolio* sheet first among the catalog sheets, same cells, plus
  *Brands* and *On client list* columns.
* `providers_from=<path>` on `watch_executive_deck`, `watch_board_report`
  (and its workbook) and `watch_catalog action=matrix`; without it the
  matrix is what was observed, most-carried first.

Against their list on 2026-09-01: 51 of 59 seen, 8 not yet (Ajoy, Deck of
Dice, G Games, GameArt, Hacksaw RGS, LivePlay, Toucan Games, Zoot), 76
observed that they do not list. The thin brands are Brand H (0 studios on
record), Brand G (7), Brand O (8), Brand B (10): their lobbies are
behind a login, which is what `watch_catalog_collect kinds=provider,game
sign_in_if_missing=true` is for.

## How old is the page (2026-09-03)

A review written in 2024 still says a studio powers a brand that dropped
it since; on 2026-09-02 one studio was shown as carried by one of our
brands on the strength of such a page. The register stamped when *we*
read the page and nothing else, so an old claim and a fresh one were
indistinguishable. Now:

* **The page's own date is read.** `page_date(html, headers)` in
  `core/watch_observe.py` returns `(YYYY-MM-DD, confidence)`: `high` from
  structured markup (`article:modified_time` / `published_time`,
  `og:updated_time`, Dublin Core, JSON-LD `dateModified` / `datePublished`,
  `<time datetime>`; the latest *modified* date wins, else the latest
  published), `medium` from visible "Last updated …" text in the common
  forms, `low` from the HTTP `Last-Modified` header (CDNs stamp it with
  now). `fetch_page_best_effort(..., meta=dict)` fills it on the way past,
  over HTTP or the browser; the collector files it on every research row
  as `meta.page_date` / `meta.page_date_confidence`.
* **The horizon is six months** (`STALE_AFTER_DAYS = 180`). A third-party
  row past it is *stale*; an undated row is not — it is reported as
  undated, never silently discounted. The brand's own pages are never
  stale: they say what the brand says today.
* **The matrix ranks evidence** per studio × brand: signed-in lobby read
  > the brand's public page > a third-party page inside the horizon > one
  past it. A cell is ● *carried* only on current evidence. Otherwise it
  is ○ *reported* — with the reason (`page dated 2024-11-03`, or `not in
  the signed-in lobby read` when the brand's lobby was read as a player
  and did not show the studio, whatever the review's date) — and counts
  for nothing: not in `brand_count`, not in `observed`. `counts.reported_only`
  says how many cells were demoted; each brand's summary carries
  `providers_reported`, and its *Providers / Games* page prints them under
  "Reported but not counted". The workbook's *Game portfolio* sheet shows
  the same ○ with the legend in row 1.
* **The search asks for recent pages.** `search_web(..., since=)` sends
  `since` (today − 360 days) to the engine; an engine that rejects the
  parameter is asked again without it. When the engine dates its sources
  (`published_at`, `modified_at`, `date_confidence`) the client passes
  them through and `rank_research_urls` sinks results past the horizon
  below undated ones. Provider and game queries now carry the year, as
  promotion queries always did.
* **The collector reports it.** Per brand × kind, `dated_pages` lists the
  research pages past the horizon (with their date) and `undated_pages`
  the ones that said nothing, so the operator knows which claims are
  standing on old ground.

What it does not do: guess a date from a URL, or drop a stale row from
the register — the row stays, as printed, with its date; only its weight
in the matrix changes.

## Read cold (2026-09-02)

A client read the 2026-08-30 pack for the first time and left comments:
"what do we mean by pairs?", "what is this, I don't get the context?"
(trends), "what is the source here?" (players), "why can't we find the
coin packages?", "the games lists are too short", "reformat the raw data
and add a link", "no description of package?", "what is game-format
merchandising?", "are we saying Brand A has fairness issues more than the
others?". The answers are now in the deck itself:

* **Slide 2, "How to read this deck"** — where the facts come from, what
  a score is, what † means, that a store and lobby sit behind a login,
  what a run is, that "what players say" is opinion, where the raw data
  lives. Nothing else in the deck assumes the vocabulary.
* **No "pairs", no "cycles"** — brand × dimension *cells*, collection
  *runs*. The trends panel reads a brand's move from its first scored run,
  reports one mover as one mover (the old panel named the same brand
  biggest riser and biggest faller, with the delta printed as if it were
  a score), and says what a flat line and a jump mean.
* **Players' table** — a "how to read" line with the sources named, each
  cell carries its count, and with fifteen brands the rows shrink so the
  table ends above the legend instead of covering it. The narrator now
  gets each brand's theme share *against the field* (`vs_field_pts`) and
  may say a brand stands out only at +10 points or more; otherwise "in
  line with the field", with the numbers, and no recommendation.
* **Raw data** — coin packages gain a *Description* column; every name in
  the per-brand tables links to the page it was read from; an empty store
  says "not read yet – behind a login", a short game list says how many
  titles the public pages showed and that the lobby needs a signed-in
  read. The three cross-brand summaries (top-12 studios, one ladder,
  twelve promotions, "e.g." titles) are gone — the per-brand pages carry
  the data.
* **Narrator** — plain English for a first-time reader, no coined phrases
  ("game-format merchandising"), one idea per sentence, every player claim
  with share and n; deep-dive implications are things we could do.

## In the pack

Appendix, after the method slide, only when rows exist:

* **Game portfolio** — Provider × Brand, every studio, paginated (above).
* **Per brand** — *Coins / Promotions* (Package · Gold coins · Sweeps coins
  · Description; Promotion · Benefit · How to claim · Frequency), *Loyalty
  Club* when tiers exist, *Providers / Games* (every studio, the titles
  read). Names link to their source page; the captured promotion images
  follow as exhibits.

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
