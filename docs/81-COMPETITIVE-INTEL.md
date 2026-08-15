# EloPhanto — Competitive Intelligence (Market Model)

> **Status: built (P1–P3).** A market is modelled as tracked brands, weighted
> dimensions, an evidence register with full provenance, and 1–5 scores that
> are **refused unless evidence backs them**. All four deliverables generate
> from stored evidence: the executive scorecard (markdown or a four-sheet XLSX
> workbook), month-over-month material-change detection, the board report, and
> the executive deck (~10 board slides, .pptx).
> Collection is autonomous for public pages — with every claim's quote checked
> against the live source before it is saved — driven by a cadence-based
> refresh queue and recurring schedules.
>
> ABE (Autonomous Business Entity) is a concept originated by Petr Royce in
> 2023. This is **organ 2 — the market model** from
> [76-ABE-FRAMEWORK.md](76-ABE-FRAMEWORK.md).

## Why this exists

An agent that can only research produces essays. An autonomous business needs a
*standing model* of its market: what each competitor does, how good it is, on
what evidence, and **what changed since last month**. That is the difference
between a one-off report and an operating capability — and it is what a
recurring competitor-analysis engagement actually buys.

## The three rules

All three are enforced in code, not prompt, because the analysis is worthless
if they can be talked around.

**1. A missing datapoint is never a bad score.** `watch_score` refuses to score
a dimension that has no evidence. The honest representation of "we don't know"
is a `NULL` score plus its coverage gap. A brand that is merely opaque must
never be reported as a weak competitor. Coverage and confidence sit *beside*
the score and never fold into it.

**2. Evidence is append-only.** A correction or re-observation writes a new row
and supersedes the old one. Nothing is overwritten, so a month-over-month diff
reflects what genuinely changed rather than what got edited.

**3. Thin evidence cannot hold a rank.** `normalized_pct` rescales to the
weight actually scored — the right comparable figure, with a sharp edge: a
brand with one 4%-weight dimension scored 5/5 normalizes to **100.0** and
would otherwise sit top of the board pack above a rival measured on all
twelve. That reads as "market leader" when the truth is "we looked at one
thing". So a subject earns a rank only once its scored weight reaches
`rank_threshold_pct` (default **50%** of total weight); below that it is
`provisional`, sorted after every ranked brand and carrying `rank: None`,
exactly like a subject with no evidence at all.

The score is never suppressed — a provisional row still shows its normalized
figure, its `evidence_weight_pct`, and which dimensions are missing. Only the
*claim to a position* is withheld, because the rank is the number a reader
trusts without checking the footnote. It is marked at the number itself
(`100.0†`) in the scorecard and board report, and as a `Status` column in the
client workbook — a caveat that lives only in a notes row travels nowhere once
a client sorts the sheet or copies a row out.

Set `rank_threshold_pct` per call when a market is deliberately scored on a
narrow slice.

## Data model

| Table | Holds |
|---|---|
| `watch_subjects` | Tracked brands — name, group, URL, `is_self` for our own |
| `watch_dimensions` | The scoring frame — weight, sub-criteria, refresh cadence, alternative-view weights |
| `watch_evidence` | **The evidence register.** One observed fact + source URL, source type, geo/state, customer state, journey stage, date, confidence, excerpt, screenshot, collector, supersession |
| `watch_scores` | subject × dimension: 1–5 (nullable), rationale, evidence IDs, coverage %, confidence |
| `watch_snapshots` | Frozen scorecards, for diffing (P2) |

All `company_id`-scoped like the rest of ABE, so several engagements can run
side by side without leaking into each other.

## Scoring

```
weighted points = (score / 5) × dimension weight
```

A 4/5 on a dimension weighted 10% yields 8 points. Two totals are always
reported together:

- `raw_points` — out of `scored_weight_pct`, **not** out of 100
- `normalized_pct` — raw rescaled to the weight actually scored; the only
  figure comparable between brands with different coverage

Reporting both makes thin evidence impossible to mistake for strength — and
rule 3 stops it claiming a rank while nobody is reading the second number.

**Alternative views** re-weight the *same* scores to answer different
questions — `customer_proposition` (games, promos, loyalty, packages, RTP,
payments) versus `transition_priority` (KYC, payments, loyalty capability,
state variation, portfolio tooling). The strongest competitor is not
automatically the best transition benchmark; the two rankings are meant to
disagree.

## Tools

| Tool | Perm | Does |
|---|---|---|
| `watch_subject` | MODERATE | add / list / archive tracked brands |
| `watch_dimension` | MODERATE | list / upsert dimensions, or `seed` a ready-made pack |
| `watch_evidence` | SAFE | add / query the evidence register (append-only; `supersedes` to correct) |
| `watch_score` | MODERATE | score a brand on a dimension **from its evidence** |
| `watch_scorecard` | SAFE | ranked scorecard + both alternative views; `format=xlsx` writes the client workbook |
| `watch_snapshot` | MODERATE | freeze the scorecard so later cycles have a baseline to diff |
| `watch_diff` | SAFE | material changes since a snapshot |
| `watch_board_report` | MODERATE | the monthly report: changes → implications → recommendations → decisions; written to a `path`, the executive deck (.pptx) lands beside it |
| `watch_executive_deck` | MODERATE | the executive presentation on its own (.pptx): summary, standings chart, us vs the leader, changes, implications, decisions, evidence coverage |
| `watch_observe` | MODERATE | collect evidence from public pages, every quote verified against the source |
| `watch_queue` | MODERATE | what is due for refresh; `action=schedule` installs the recurring jobs |
| `watch_analyze` | MODERATE | **one command** — read a brand, score every dimension, save the pack (workbook, report, deck) |

## One command

The whole pipeline behind a single sentence:

> *"Do a full competitor analysis on High 5 Casino and save the results."*

`watch_analyze` reads the brand's landing page plus the sub-pages that actually
carry facts (terms, promotions, payments — discovered from the homepage), files
every verifiable claim, scores each dimension the evidence supports, and writes
the pack — workbook, board report and executive deck — to `~/Desktop` by
default.

Two efficiencies matter at this scale. Pages are read **once** and extracted
against **all twelve dimensions in a single model call** — one call per page
instead of one per page-dimension pair, since the page text is identical either
way. And scoring passes the peer brands' evidence for the same dimension as
context, so a 1–5 judgement is comparative rather than a guess in isolation;
where there are no peers yet the score comes back flagged `provisional`.

## The four deliverables

**Executive scorecard.** `watch_scorecard format=xlsx path=…` writes a
four-sheet workbook: *Scorecard* (brands × dimensions, weighted totals, both
views), *Weights* (the frame, with sub-criteria and cadences), *Evidence* (the
full register — every score traceable to a source URL), *Gaps* (what is
unobserved or overdue). An unscored dimension is a **blank cell, never a zero**;
a zero would read as "terrible" when it means "not yet observed".

**Material change detection.** `watch_snapshot` freezes a cycle;
`watch_diff` reports only what genuinely moved — a score change of at least a
full point, a rank change, a dimension newly scored or withdrawn, a large
coverage shift, or a brand entering or leaving. Sub-threshold wobble is
suppressed, because a report that surfaces everything trains its readers to
ignore it. A dimension going from unscored to scored is *always* material: that
is new knowledge, not noise.

**Board report.** `watch_board_report` assembles standings, the material
changes, and outstanding evidence gaps, then turns each change into an
implication, a recommendation classified as `no_regret` /
`transition_requirement` / `post_transition` / `monitor`, and the decision the
board must make. The classification uses the no-regret test: *"would we still
be pleased we did this if the transition plan, competitor rankings or strategic
priorities changed next month?"*

Judgement is generated by the model from the factual diff, under instruction to
use only the facts given. If no model is available the report still ships the
full factual record and says plainly that implications have not been applied —
it never silently omits the distinction between fact and judgement.

**Executive deck.** Part of the pack, not an option: `watch_analyze` writes it
beside the workbook and report, and `watch_board_report path=…` writes it
beside the report (`deck=false` to skip, `deck_path=…` to place it).
`watch_executive_deck path=…` regenerates it on its own at any time. It is the
same facts and the same judgement as ~10 16:9 slides for the room: cover with the evidence basis;
executive summary; standings as a native bar chart with our brand in amber;
our brand against the ranked leader, dimension by dimension (ahead / behind /
not comparable yet); material changes; implications and recommendations
grouped by class; decisions required; evidence and confidence (how much of the
model is measured, what is unobserved or overdue); and an appendix with the
scores-by-dimension heatmap and the method. Charts are native PowerPoint
objects, so the client can restyle or lift them.

A slide is where the organ's rules are most easily lost, so the deck enforces
them itself. Unscored is a blank cell and no bar — never a zero, which reads
as "worst". A provisional brand is listed under the chart with a dagger and
its reason, not drawn in it: a bar is trusted without its footnote, and a brand
scored 5/5 on one 15%-weight dimension would otherwise lead the picture at
100.0. The summary and implications slides each say whether a model wrote
them; with no model the summary is built from the numbers alone and says
*facts only*, and the decisions slide says *not yet evaluated* rather than
*none required* — those two must never look alike.

The standalone deck does not snapshot. `watch_board_report` closes the cycle,
and cuts the report and the deck from the same diff *before* the snapshot, so
they describe one period.

## Autonomous collection — and why you can trust it

`watch_observe` fetches a brand's public pages and files what it finds. The
obvious failure mode is a model producing a plausible competitor fact that
appears nowhere on the page it just read — a register full of confident fiction
is worse than an empty one, because it *looks* like diligence.

So collection is built around one checkable guarantee: **every claim must carry
a verbatim excerpt, and that excerpt is verified against the fetched page before
the claim is saved.** Comparison ignores case and whitespace (a model may re-wrap
what it quotes) but nothing else, and an excerpt under 20 characters is rejected
outright since a short string matches by luck. Claims that fail are **discarded
and counted**, and the rejection count comes back in the result — a high
rejection rate is a signal worth seeing, not hiding.

### Reading sites that don't want to be read

Most consumer sites are JS applications that serve a plain HTTP client an empty
shell, and some block non-browser requests outright. Measured across five of
the seeded brands, only one returned usable content over plain HTTP: one was a
403, three were shells of 0–44 characters.

So collection **escalates**: plain HTTP first (fast, no contention), and when
the result is empty, blocked, or under ~600 characters, the same URL is opened
in the agent's real Chrome, which executes the app and carries a real
fingerprint. The escalation is per page — a site may serve a static terms page
and a JS lobby. A page that reads fine over HTTP never wakes the browser, since
it is a slow shared resource. If no browser is available, sparse-but-real text
is still read rather than discarded; only a genuinely empty result is an error.

The verification guarantee is unchanged either way: claims are checked against
whatever text actually came back.

Everything collected this way is stamped `collector='agent'`,
`customer_state='logged_out'`, `confidence='medium'`: quoted from a live page
and substring-verified is solid on provenance, but a marketing page is still a
brand describing itself. If the fetch fails, the run reports the error and
writes nothing.

## Per-state observation

Offers, availability and pricing vary by US state, so a single network exit
cannot answer "what does Texas see?". `proxy.pool` maps states to exits:

```yaml
proxy:
  pool:
    - {state: TX, host: tx.provider.example, port: 8080, username: u, password: p}
    - {state: CA, host: ca.provider.example, port: 8080}
```

`watch_observe geo_state=TX` then routes through the Texas exit and stamps the
evidence `geo_state=TX`. The pool works independently of `proxy.enabled` —
observing as a customer elsewhere is a separate concern from routing the
agent's own browser traffic.

## Refresh cadence and staleness

Every dimension declares a cadence (weekly / monthly / quarterly). A brand ×
dimension pair is **stale** when its newest live evidence is older than that
cadence, and **never observed** when there is none. Both surface in the board
report and on the workbook's Gaps sheet, which is what stops a scorecard
quietly ageing into fiction.

## Seed packs

A pack is a ready-made scoring frame plus the brands to track, so an engagement
is productive on day one. `social_casino_t1` encodes a T1 sweepstakes-casino
scope: 12 weighted dimensions with their sub-criteria and refresh cadences
(promotional and marketing weekly, operational monthly, financial and
state-policy quarterly), and 14 brands.

```
watch_dimension action=seed pack=social_casino_t1
```

The tools themselves are market-agnostic — a new engagement is a new pack in
`core/watch_seeds.py`, not new code.

## Customer states and geo

Evidence records the state it was observed from: `logged_out`, `registered`,
`verified`, `purchaser`, `redeemer`, `vip`, plus `geo_state` for per-state
observation.

**Policy: authenticated states are operator-collected.** The agent gathers
logged-out and public evidence (site, terms, ad libraries, trust sites,
filings). Anything requiring an account is entered by the operator with
`collector='human'` — automated account creation on live operators is ToS- and
KYC-fraught and is not something the agent should do on its own initiative.
The register models both, and always records *who* observed a fact.

## Typical cycle

```
watch_dimension action=seed pack=social_casino_t1   # once, at engagement start
watch_queue     action=schedule                     # once: weekly/monthly/quarterly jobs

watch_analyze   subject="High 5 Casino"             # the whole pipeline, one call

# …or drive the stages by hand:
watch_queue                                         # what is due now
watch_observe   subject=McLuck dimension=… geo_state=TX   # agent, public pages
watch_evidence  action=add collector=human …        # operator, logged-in states
watch_score     subject=… dimension=… score=4       # refused without evidence
watch_scorecard    format=xlsx path=~/scorecard.xlsx
watch_board_report path=~/board-march.md            # + board-march.pptx beside it; snapshots on the way out
watch_executive_deck path=~/deck.pptx               # slides only, any time; no snapshot
```

Once scheduled, the loop runs itself: each cadence job asks `watch_queue` what
is due, observes it, and scores what has enough evidence. The operator's job
narrows to the authenticated states and the board decisions.
