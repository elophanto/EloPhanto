# 72 — Polymarket calibration audit

**Status:** v1 implementation (2026-05-10).
**Author:** EloPhanto + Claude (Opus 4.7).
**Related:** [docs/64-POLYMARKET.md](64-POLYMARKET.md), [docs/71-POLYMARKET-RISK.md](71-POLYMARKET-RISK.md), [skills/web3-polymarket/SKILL.md](../skills/web3-polymarket/SKILL.md), [core/polymarket_calibration.py](../core/polymarket_calibration.py).

---

## What this answers

The risk engine ([docs/71-POLYMARKET-RISK.md](71-POLYMARKET-RISK.md)) decides *whether* to trade. This calibration audit answers two questions the risk engine cannot:

1. **Is the LLM calibrated?** When the bot says "70% confidence", does the resolved win rate actually land near 70%? If not, every edge-filter threshold downstream is using a probability the LLM can't deliver.
2. **Do we have edge over the market?** When we enter at $0.40, does the market actually resolve YES 40% of the time? Above-diagonal = real edge; below-diagonal = paying spread for nothing.

Plus two operational questions the analytics tools didn't surface:

3. **Brier score** — overall probabilistic accuracy. <0.25 means the bot is at least better than always claiming 50%. Above 0.25 = anti-correlated with reality (flip the predictions and we'd do better).
4. **Maker fill rate** — fraction of post-only orders that filled before resolution. Low fill rate = maker offset is wrong; we're sitting on a price the book never reaches.

The chart in the [Polymarket Quantitative Trading Framework](https://x.com/0xMovez/status/2053102961673256990) (actual win rate vs contract price) falls out of this audit's `by_entry_price` bucketing for free.

---

## Architecture

Three SAFE tools, one feedback loop, one pure-math module that does no I/O:

```
                                                     ┌─────────────────────┐
                                                     │ core/polymarket_    │
                                                     │ calibration.py      │
                                                     │  • bucketing        │
                                                     │  • Brier score      │
                                                     │  • build_report()   │
                                                     └────────▲────────────┘
                                                              │
   pre_trade gate passes                                      │ pure functions,
            │                                                 │ no DB / network
            ▼                                                 │
  ┌─────────────────────┐    write    ┌──────────────────────┴──────────┐
  │ polymarket_log_     │────────────▶│ polymarket_predictions          │
  │ prediction (SAFE)   │             │  (in main data/elophanto.db)    │
  │  • llm_prob         │             │   side, entry_price, llm_prob,  │
  │  • side, price,size │             │   confidence_band, kelly_frac,  │
  │  • confidence_band  │             │   order_type, market_slug, ...  │
  └─────────────────────┘             │                                 │
                                      │   resolved_at, settle_price,    │
  ┌─────────────────────┐    update   │   outcome (WIN/LOSS/PUSH),      │
  │ polymarket_resolve_ │────────────▶│   realized_pnl                  │
  │ pending (SAFE)      │             └──────────┬──────────────────────┘
  │  • Gamma API        │                        │
  │  • per-slug cache   │                        │ read
  └─────────────────────┘                        │
                                                 ▼
                                       ┌──────────────────────┐
                                       │ polymarket_          │
                                       │ calibration (SAFE)   │
                                       │  • by_claimed_prob   │
                                       │  • by_entry_price    │
                                       │  • by_confidence_band│
                                       │  • brier_score       │
                                       │  • maker_fill_rate   │
                                       └──────────────────────┘
```

### Why a separate table from `polynode-trading.db`

The polynode binary owns `polynode-trading.db` and writes its `order_history` table autonomously. We don't co-modify it — adding columns there would couple us to the polynode release cycle and could break on its next migration. Instead the audit table lives in our main `data/elophanto.db` and joins by `(token_id, created_at)` proximity when correlation with on-chain rows is needed.

---

## Tools

### `polymarket_log_prediction` — feed the audit

Called immediately after `polymarket_pre_trade` returns `gate.allowed=true` and BEFORE `client.create_and_post_order(...)`. Inputs:

| Field | Required | Notes |
|---|---|---|
| `token_id` | ✓ | CTF token id we're betting on |
| `side` | ✓ | `YES` or `NO` |
| `entry_price` | ✓ | 0–1, the price we pay for one share of the side we're taking |
| `size` | ✓ | shares (intended position) |
| `llm_prob` | ✓ | LLM's probability that *YES* wins (always YES-frame, 0–1). The audit re-frames internally to "side I took". |
| `confidence_band` | optional | `high` / `medium` / `low` — same as input to the pre-trade gate |
| `kelly_fraction` | optional | Kelly fraction returned by safe_compounder, for later cross-reference |
| `order_type` | optional | `post-only` / `GTC` / `FOK` etc. — used to compute maker fill rate |
| `market_slug` | optional | Polymarket event slug — required for Gamma API resolution lookup |
| `rationale` | optional | One-line LLM thesis (audit trail) |

Returns `{prediction_id, logged_at, side, entry_price, llm_prob}`.

### `polymarket_resolve_pending` — fetch resolutions

Reads `polymarket_predictions` rows where `resolved_at IS NULL`, batches by `market_slug`, hits `https://gamma-api.polymarket.com/events/slug/<slug>` once per unique slug (cached within the run), parses the `closed` flag and `outcomePrices`, classifies WIN/LOSS/PUSH against the side we took, computes per-share PnL, and writes the four resolution columns.

Cron: `0 */6 * * *` (every 6h). Polymarket markets resolve weekly to monthly; checking more often is wasted API quota. Returns `{checked, resolved, still_pending, skipped_no_slug, errors, unique_markets_queried}`.

### `polymarket_calibration` — the report

Reads resolved predictions and produces:

```jsonc
{
  "n_resolved": 47,
  "overall_win_rate": 0.5532,
  "brier_score": 0.2148,                       // <0.25 → better than always-50
  "by_claimed_prob": [
    {
      "bucket": "60-70%", "n": 12, "wins": 8,
      "realized_win_rate": 0.6667, "avg_claimed": 0.6450,
      "calibration_gap": 0.0217                 // realized − claimed; positive = outperforming
    },
    ...
  ],
  "by_entry_price": [...],                     // same shape, bucketed by implied market prob
  "by_confidence_band": {                      // single bucket per band
    "high":   { "n": 18, "wins": 13, "realized_win_rate": 0.7222, "avg_claimed": 0.7500 },
    "medium": { "n": 22, "wins": 11, ... },
    "low":    { "n": 7, "wins": 2, ... }
  },
  "maker_fill_rate": 0.6818,                   // post-only fills / post-only placed
  "n_maker_orders": 22
}
```

Optional inputs: `since` (ISO timestamp lower bound), `bucket_width` (default 0.10 = 10% bins).

---

## Interpreting the report

### Brier score

| Range | Meaning |
|---|---|
| 0.00–0.18 | Excellent — sharp probabilistic accuracy. Rare on Polymarket-shape markets. |
| 0.18–0.22 | Good — calibrated bot with real edge. |
| 0.22–0.25 | OK — better than always-50% but not by much. |
| 0.25 | Random / always-50%. |
| > 0.25 | Anti-correlated with reality. **Flip the predictions and you'd do better.** Pause trading. |

Sample size matters — Brier on n<30 is noisy. The audit returns `n_resolved` so the consumer can decide.

### Per-bucket calibration

A bucket where `realized_win_rate ≈ avg_claimed` is calibrated for that probability range. `calibration_gap` (realized − claimed) signals direction:

- **Positive gap** (e.g. claimed 65%, realized 75%) — that probability range *outperforms* the LLM's own estimate. The bot is too conservative; could size up.
- **Negative gap** — overconfident at that range. The edge filter's threshold for the corresponding `confidence_band` should tighten.

### Maker fill rate

| Range | Meaning |
|---|---|
| > 0.80 | Maker offset is conservative; we're getting filled but maybe leaving rebate on the table. |
| 0.50–0.80 | Healthy. |
| < 0.50 | Maker offset is too aggressive (we're 1¢ inside the ask but the book never reaches us). Either reduce the offset, accept taker fills, or skip the trade. |

### Confidence-band drift

If `by_confidence_band["high"].calibration_gap < -0.10` over `n ≥ 30`, the high-confidence band's edge threshold (`polymarket.high_confidence_edge` in `config.yaml`) is too lax — the bot is mistaking "I'm sure" for "I'm right". Tighten by 1-2 percentage points; re-audit weekly.

---

## Wiring it up

### One-time

The schema lands automatically on next agent restart (`_SCHEMA` migration in [core/database.py](../core/database.py) is idempotent). The three tools register themselves as PROFILE tier in group `polymarket`, so any task whose profile includes that group sees them without `tool_discover`.

### Recurring

Two scheduled tasks (operator-created via the chat agent or `schedule_task` directly):

```yaml
# Schedule 1 — feed the audit
name: "Polymarket Calibration — Resolve Pending (6h)"
cron: "0 */6 * * *"
task_goal: |
  Run polymarket_resolve_pending. Read-only Gamma API call to update
  settle_price + outcome on closed markets. No orders, no approval.

# Schedule 2 — weekly drift check
name: "Polymarket Calibration — Weekly Summary"
cron: "0 9 * * 0"
task_goal: |
  Run polymarket_calibration; save the full report to
  knowledge/learned/polymarket-calibration/weekly-{date}.md.
  Brief the owner ONLY if:
    (a) brier_score > 0.25 over n_resolved >= 30
    (b) any band's realized trails claimed by > 0.10 over n >= 30
    (c) maker_fill_rate < 0.50 over n_maker_orders >= 20
```

### Per-trade

The skill ([skills/web3-polymarket/SKILL.md](../skills/web3-polymarket/SKILL.md) §8a) mandates calling `polymarket_log_prediction` between gate-pass and order-placement. Without that call the audit is empty.

---

## What this replaces / complements

| Concern | Tool | Status before | Status after |
|---|---|---|---|
| "Are we losing money?" | `polymarket_performance` | Realized + open-position PnL | Unchanged — performance is still the day-to-day "how am I doing" read |
| "Did this trade have edge?" | `polymarket_pre_trade` | edge = abs(llm_prob − price) ≥ threshold | Unchanged — gate logic is per-trade |
| **"Is the LLM calibrated?"** | **(none)** | Not measurable | `polymarket_calibration.by_claimed_prob` |
| **"Are our entry prices priced correctly?"** | **(none)** | Not measurable | `polymarket_calibration.by_entry_price` |
| **"Is our high-confidence band actually high-confidence?"** | **(none)** | Not measurable | `polymarket_calibration.by_confidence_band` |
| **"Are post-only orders filling?"** | **(none)** | Not measurable | `polymarket_calibration.maker_fill_rate` |

---

## Test coverage

`tests/test_core/test_polymarket_calibration.py` (38 tests):

- **Pure math** — `to_winner_perspective` re-frames YES/NO correctly; bucketing edges; Brier score on perfect/random/anti predictors; `_compute_realized_pnl` on YES/NO win/loss combinations.
- **Tools** — `log_prediction` rejects invalid sides + out-of-range probs; `resolve_pending` caches per slug (one Gamma call per unique market regardless of dup predictions); `calibration` filters resolved-only and computes maker fill rate against PROFILE-tier post-only orders.
- **End-to-end** — `since` filter, empty-DB-returns-zero-n, partial-resolution rolls up correctly.

---

## Future work

| Item | Why | Effort |
|---|---|---|
| Self-learning thresholds | Feed `by_confidence_band.calibration_gap` back into `confidence_band` `min_edge` config so the gate auto-tightens when a band drifts. | ~200 LOC + needs ≥4 weeks of audit data |
| Order-book depth pre-check | Maker post-only at "1¢ inside ask" is great, but if there's only $5 of size at that level the order never fills. Check book depth ≥ intended size before posting. | ~50 LOC, ships independently |
| Bayesian update tool | When news lands, `polymarket_bayesian_update(market, prior_prob, evidence_summary)` produces a posterior via likelihood ratio instead of cold-re-evaluating. | ~250 LOC |
| Cross-DB join with polynode-trading.db | True maker fill rate requires knowing whether the post-only order actually filled or got cancelled. Today we approximate via `resolved_at IS NOT NULL`. | ~150 LOC, depends on stable polynode schema |
