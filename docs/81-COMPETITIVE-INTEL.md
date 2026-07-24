# EloPhanto — Competitive Intelligence (Market Model)

> **Status: P1 built (evidence + scoring spine).** A market can be modelled as
> tracked brands, weighted dimensions, an evidence register with full
> provenance, and 1–5 scores that are **refused unless evidence backs them**.
> The executive scorecard renders in markdown today; XLSX export, month-over-
> month diffing and the board report are P2, autonomous collection is P3.
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

## The two rules

Both are enforced in code, not prompt, because the analysis is worthless if
they can be talked around.

**1. A missing datapoint is never a bad score.** `watch_score` refuses to score
a dimension that has no evidence. The honest representation of "we don't know"
is a `NULL` score plus its coverage gap. A brand that is merely opaque must
never be reported as a weak competitor. Coverage and confidence sit *beside*
the score and never fold into it.

**2. Evidence is append-only.** A correction or re-observation writes a new row
and supersedes the old one. Nothing is overwritten, so a month-over-month diff
reflects what genuinely changed rather than what got edited.

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

Reporting both makes thin evidence impossible to mistake for strength.

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
| `watch_scorecard` | SAFE | ranked scorecard + both alternative views + coverage/confidence |

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

## Roadmap

- **P2** — XLSX scorecard export, `watch_diff` (material change vs a snapshot),
  `watch_board_report` (changes → implications → recommendations classified as
  no-regret / transition / post-transition / monitor → decisions required).
- **P3** — `watch_observe` autonomous collection passes, per-dimension staleness
  queue driven by refresh cadence, per-state proxy pool and personas, scheduled
  weekly / monthly / quarterly refresh.
