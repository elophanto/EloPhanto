# 87 — Voice of Customer (watch organ, second evidence class)

*Status: designed and built 2026-08-17 (steps 1–5). Google Play, Trustpilot/BBB and X
collectors are the remaining step 6.*

The competitive-intelligence organ ([81](81-COMPETITIVE-INTEL.md)) records **what a
brand says and does** — its pages, read and photographed, scored against the
customer's model. Voice of customer (VoC) records **what players say about the
brand** — on Reddit, in app-store reviews, on complaint boards. It is opinion,
not fact, and the design keeps it that way: a second evidence class beside the
first, with its own collector, its own reading, its own slides, that can ship
on top of the pack or entirely on its own — and never changes a scorecard number.

## Non-negotiables

1. **The current pack is untouched.** No existing table changes shape, no
   existing tool changes contract, no existing slide moves. VoC adds tables,
   tools and slides; with nothing collected the pack renders exactly as today.
2. **On top or alone.** `watch_board_report` / `watch_executive_deck` gain an
   optional `voice=true|false|auto` (auto = include when VoC evidence exists);
   a new `watch_voice_report` ships a VoC-only pack for a company.
3. **Opinion never becomes fact.** VoC rows live in `watch_voice` (not
   `watch_evidence`), never enter `score_subject`, and every VoC slide carries
   the label *"What players say — sentiment from public posts, not observed
   product fact."* A VoC theme can *flag* a dimension (a "watch this" note on
   the deep dive), never move its score.
4. **Same architecture as everything else.** Manager on the shared `Database`
   handle (`core/watch.py` → `WatchManager` grows `add_voice`, `list_voice`,
   `voice_summary`); collectors in `core/watch_voice.py` beside
   `core/watch_observe.py`; tools in `tools/watch/tools.py` registered through
   `create_watch_tools()` and wired in `Agent` with the same dependency block;
   schedules through `watch_queue`; snapshots carry a `voice` section so
   `diff_since_snapshot` reports theme deltas the same way it reports score
   moves; the deck renders through `core/watch_deck.py`.
5. **Register is canon here too.** VoC collects for the brands in
   `watch_subjects`; it never adds or archives one.

## Data

New table `watch_voice` (in `core/database.py` beside the watch tables):

| column | meaning |
|---|---|
| `voice_id`, `company_id`, `subject_id` | as in evidence |
| `source` | `reddit` · `app_store` · `google_play` · `trustpilot` · `bbb` · `x` · `web` |
| `source_url`, `posted_at`, `observed_at`, `exit_ip` | provenance; `posted_at` is the post's own date |
| `rating` | 1–5 when the source has one, else NULL |
| `theme` | one of a fixed vocabulary (below) |
| `sentiment` | `negative` · `neutral` · `positive` |
| `quote` | ≤ 240 chars verbatim, **no usernames, no PII** |
| `dimension_id` | optional — the dimension this theme speaks to (flag, not score) |
| `geo_hint` | state/country if the post says so, else `''` |
| `weight` | 0–1 credibility (account age/karma where visible; affiliate-link posts → 0) |
| `dedupe_key` | hash of normalised quote — cross-posts count once |
| `created_at` | |

**Theme vocabulary** (fixed, so cycles are comparable): `redemption_speed`,
`kyc_friction`, `support`, `fairness_rtp`, `promo_value`, `app_stability`,
`account_bans`, `vip_treatment`, `game_selection`, `payments`, `other`.

Snapshots (`watch_snapshots.payload_json`) gain `voice: {subject: {theme:
{n, neg_share, avg_rating}}, window_days, mentions}` so the diff can say
*"redemption complaints at Crown Coins 12 → 27 mentions, neg share up 18
points"* next cycle. `diff_scorecards` is not touched; a sibling
`diff_voice(prev, curr)` returns theme deltas.

## Collection (`core/watch_voice.py`)

One collector per source, all the same shape `async def collect_<source>(brand,
*, since, proxy_url, browser_manager, router) -> list[VoiceRow]`, run by
`collect_voice(subject, sources, window_days)`. Order of build:

1. **Reddit** — public JSON (`/search.json`, `/r/<sub>/search.json`) via
   `fetch_page_best_effort` with the existing proxy plumbing; subs
   `sweepstakescasinos`, `SweepstakesCasinos`, brand subs when they exist;
   query = brand name + aliases (from `watch_subjects.url` host and name).
2. **App Store** — iTunes customer-reviews RSS (`/us/rss/customerreviews/id=…`);
   app id discovered once per subject and cached as the subject tag `app_store:<id>`.
3. **Google Play** — reviews page via the browser (JS app); same extraction.
4. **Trustpilot / BBB** — later; grey-area scraping, cite-and-quote only.
5. **X** — later; the browser session already exists.

Every post goes through one extraction contract (`VOICE_EXTRACT_SYSTEM`, same
verified-excerpt discipline as `EXTRACT_SYSTEM`): the model returns
`{theme, sentiment, quote, dimension, geo_hint}` and the quote must appear
verbatim in the post text or the row is dropped. Usernames are stripped
before the model sees the text. Affiliate/referral posts (`ref=`, "use my
code") are dropped. Cross-posts are deduped on `dedupe_key`.

Volume asymmetry is handled in the reading, not the collection: every number
shown is a *share* with its `n`, and brands under a minimum `n` (config, default
15 in the window) are shown as *"too few mentions to read"* rather than
charted.

## Reading (`WatchManager.voice_summary`)

Per company, window: per brand — mentions, sources, avg rating, sentiment
split, theme shares, top praise theme, top complaint theme, three quotes
(one negative, one positive, one about the theme with the biggest change);
plus field-level theme shares. Pure computation, deterministic, no model.

## Deck and report

- **"What players say"** — brands × themes heatmap (cell = share of that
  brand's mentions, colour by negative share), `n` per brand, window in the
  eyebrow, the opinion label in the footer.
- **"Rising and falling"** (cycles ≥ 2) — theme deltas per brand from
  `diff_voice`; first cycle says "baseline".
- **Deep dives** — a three-quote strip under the existing facts + a *"players
  flag"* line when a negative theme maps to a dimension.
- **Executive summary** — the narrator gets `voice_summary` and is told the
  same thing the slide says: sentiment, not fact; a rising complaint theme is
  worth a line in *Where we stand* / *Decisions*, never a score claim.
- Standalone: `watch_voice_report` renders title, what-players-say, rising/
  falling, one slide per brand, method, closing — the same components.

Board report (markdown) and scorecard (xlsx) each gain one optional section /
sheet, `voice`, present only when there is data.

## Tools

| tool | what |
|---|---|
| `watch_voice_collect` | run collectors for one subject or all active subjects; params `subject`, `sources`, `window_days`, `save`; returns rows found/kept/dropped per source |
| `watch_voice` | list / summarise VoC rows (`action=list|summary`, filters) |
| `watch_voice_report` | the standalone pack |
| `watch_board_report`, `watch_executive_deck` | new optional `voice` param (default `auto`) |
| `watch_queue` | `action=schedule` also installs *Voice of customer · weekly* (`voice=false` to skip) |
| `watch_analyze` | **unchanged** — VoC is not part of a page analysis |

## Defaults

No config section: the knobs are tool parameters, so a run can be
narrowed without editing config — `watch_voice_collect(sources, window_days=30,
max_posts=200, geo_state)`; `min_mentions=15` (`VOICE_MIN_MENTIONS`); Reddit
subs `sweepstakescasinos`, `SweepstakesCasinos` (`DEFAULT_REDDIT_SUBS`). The
weekly schedule installed by `watch_queue` uses `window_days=14`.

## Costs and limits

Text only — proxy cost is negligible; the model reads one post at a time
through the same router. Reddit's public JSON is rate-limited (~1 req/s with a
UA); the collector sleeps between calls and stops at `max_posts` (default 200
per brand per run). App-store RSS returns the latest 500 reviews per app.
Trustpilot/BBB terms restrict wholesale reuse: quotes are ≤ 240 chars, cited
by URL, no bulk republication.

## What shipped (2026-08-17)

- `watch_voice` table (`core/database.py`), `WatchVoice` record, `WatchManager.add_voice /
  list_voice / voice_summary / tag_subject / diff_voice_since_snapshot`; `summarize_voice`,
  `diff_voice`, `voice_dedupe_key` in `core/watch.py`. Snapshots carry `voice` only when
  there is one.
- `core/watch_voice.py`: `collect_reddit` (search JSON field-wide + per sub, top-level
  comments of brand threads), `collect_app_store` (+ `find_app_store_id`, cached as the
  subject tag `app_store:<id>`), `read_posts` with `VOICE_READ_SYSTEM` (verbatim-quote
  verification, vocabulary validation, dimension flag with a deterministic fallback),
  `strip_pii`, `is_affiliate`, `brand_aliases`.
- Tools: `watch_voice_collect`, `watch_voice` (summary | list | diff), `watch_voice_report`
  (standalone md + pptx + xlsx); `voice=auto|true|false` on `watch_board_report`,
  `watch_executive_deck` and the xlsx export; `watch_queue action=schedule` also installs
  *Voice of customer · weekly* (Wednesdays 08:00, `window_days=14`).
- Deck (`core/watch_deck.py`): `_slide_voice` (brands × themes heatmap + reading panel),
  `_slide_voice_changes` (rising / falling), a quote strip on deep dives
  (`_slide_profile(voice_brand=)`), `render_voice_deck` standalone; `factual_narrative(voice=)`
  and the narrator's `voice_of_customer` facts + rules (`titles.voice`, `slides.voice`).
- Workbook (`core/watch_xlsx.py`): `write_voice_sheet` (the *Voice* sheet, only when rows
  exist), `render_voice_xlsx` (Summary + Voice).
- Tests: `tests/test_core/test_watch_voice*.py` — including the guarantee that a deck /
  report / workbook with no voice rows is byte-for-byte the pack it always was.

## Build order (each step ships green with the pack unchanged)

1. Schema + `WatchManager.add_voice/list_voice/voice_summary` + tests.
2. `core/watch_voice.py`: extraction contract, dedupe, Reddit collector +
   App Store collector, `watch_voice_collect` + `watch_voice` tools.
3. Snapshot `voice` section + `diff_voice`.
4. Deck slides + report/xlsx sections behind `voice=auto`; standalone
   `watch_voice_report`.
5. `watch_queue` cadence; docs; capabilities entry.
6. Later: Google Play (browser), Trustpilot/BBB, X.
