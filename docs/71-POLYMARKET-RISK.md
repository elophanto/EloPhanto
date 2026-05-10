# 71 — Polymarket risk engine + safe-compounder strategy

**Status:** v1 implementation (2026-05-07).
**Author:** EloPhanto + Claude (Opus 4.7).
**Related:** [docs/64-POLYMARKET.md](64-POLYMARKET.md), [docs/72-POLYMARKET-CALIBRATION.md](72-POLYMARKET-CALIBRATION.md), [skills/web3-polymarket/SKILL.md](../skills/web3-polymarket/SKILL.md), [core/polymarket_engine.py](../core/polymarket_engine.py).
**Reference:** [zostaff/poly-trading-bot](https://github.com/zostaff/poly-trading-bot) — risk-management beats borrowed (with attribution).

---

## What this replaces

Live trade history (52 orders, ~$3,500 BUY notional) showed three structural failure modes:

| Failure mode | % of orders | Root cause |
|---|---|---|
| LLM-driven mid-probability bets bleeding to zero | majority of P&L | No edge filter, no exits — every wrong bet held to resolution at 0¢ |
| `invalid amounts` precision rejection | 6 of 8 failed orders | `price × size` had > 2 decimals; Polymarket rejected outright |
| `not enough balance / allowance` | 2 of 8 failed orders | Wallet/proxy mismatch or USDC allowance never set |

The original Polymarket flow was the agent calling `shell_execute` with raw `py-clob-client` Python and the LLM's "confidence" as the only gate. Zero risk-management code between the LLM's opinion and the place_order call. This doc describes the **structural fix** — five SAFE pure-decision tools every trade now passes through.

## Two-layer model

```
┌──────────────────────────────────────────────────────────────────┐
│ Strategy layer (what to trade?)                                  │
│   - LLM directional bot (existing)                               │
│   - polymarket_safe_compounder (new — NO-side baseline)         │
│   - operator-written strategies (future)                         │
├──────────────────────────────────────────────────────────────────┤
│ Risk gate layer (should this trade ship?)  — UNIVERSAL          │
│   - polymarket_circuit_breaker (drawdown gate)                   │
│   - polymarket_pre_trade (edge + skip-tag + stop-loss calc)      │
│   - polymarket_quantize_order (precision snap)                   │
└──────────────────────────────────────────────────────────────────┘
```

**Every trade — regardless of which strategy proposed it — passes through the risk-gate layer.** The strategy layer is pluggable; the gate layer is non-negotiable.

## Risk-gate components

### 1. Edge filter (`check_edge`)

Block trades where the LLM's "insight" is too close to what the market already prices in.

```python
result = check_edge(llm_prob=0.65, market_price=0.55, confidence=0.80)
# result.passes == True (10% edge, well above thresholds)
# result.side == "YES"
```

**Confidence-asymmetric thresholds.** The LLM's self-reported confidence is a self-report, not a calibrated probability. We trust it less when it claims to be uncertain — those are the exact bets where the market is most likely correct.

| Confidence band | Cutoff | Edge required |
|---|---|---|
| High | ≥ 0.70 | 3% |
| Medium | 0.40–0.69 | 5% |
| Low | < 0.40 | 8% |

Plus a global floor of **4% min_edge**. All thresholds tunable via `PolymarketConfig`.

OOB inputs (LLM occasionally returns `prob > 1`) clamp instead of raising — block trades on bad input doesn't blow up the whole loop.

### 2. Skip-tag filter (`should_skip_market`)

Sports + entertainment + awards markets are pure noise for LLM directional bets — no edge against sharps.

```python
SkipResult = should_skip_market(
    market_tags=["sports", "nfl"],
    market_title="Will the Cowboys cover?",
)
# skip == True, reason="skip-tag matched: sports"
```

**Default skip-tag list** (`DEFAULT_SKIP_TAG_SLUGS`, 35+ entries):
- Sports: `sports`, `soccer`, `nba`, `nfl`, `mlb`, `nhl`, `ufc`, `pga`, `tennis`, `f1`, `epl`, `ucl`, `champions-league`, `fifa-world-cup`, `boxing`, `esports`, ...
- Entertainment: `awards`, `oscars`, `emmys`, `grammys`, `music`, `pop-culture`, `entertainment`, `tv`, `movies`, `gaming`, `games`, `celebrity`, `kpop`

**Title-phrase blocklist** (`DEFAULT_SKIP_TITLE_PHRASES`): markets phrased as social-media garbage (`"mention"`, `"say in speech"`, `"wear"`, `"outfit"`, `"tweet about"`).

Operator can override either list via `PolymarketConfig`.

### 3. Stop-loss / take-profit calculator (`calculate_stop_loss_levels`)

The dominant P&L drain in live trade history was **never selling losers** — avg BUY at $0.599, avg SELL at $0.864 (only winners get sold). Single losing positions held to 0¢ resolution dominated everything.

Fix: every entry generates companion exit limits, placed in the same flow.

```python
levels = calculate_stop_loss_levels(
    entry_price=0.60, side="BUY", confidence=0.80
)
# stop_loss_price=0.558, take_profit_price=0.72
# (7% stop, 20% TP defaults; mirrored for SELL entries)
```

**Confidence adjustment**: low-confidence trades (< 0.40) get the stop **halved** — they don't deserve the full breathing room. High-confidence trades use the default.

**Edge clamping**: stops near $0.01 / $0.99 round defensively away from the bound — Polymarket rejects orders at the edge.

### 4. Drawdown circuit breaker (`check_drawdown`)

Pause new entries after a 20% drawdown from peak (default; tunable). Closing existing positions stays allowed. The difference between "had a bad week" and "blew up the account on tilt-trading."

```python
result = check_drawdown(peak_equity=1000.0, current_equity=750.0)
# paused=True, drawdown_pct=0.25, threshold_pct=0.20
```

Caller is responsible for tracking peak equity (typically rolling 30-day high). Above-peak `current_equity` is treated as zero drawdown — handles stale-peak edge cases without dividing by zero.

### 5. Precision quantizer (`quantize_order`)

**75% of historical failures** were Polymarket rejecting orders with > 2-decimal USDC notional:

> *"invalid amounts, the market buy orders maker amount supports a max accuracy of 2 decimals, taker amount a max of 5 decimals"*

| Live failure case | Notional | Why rejected |
|---|---|---|
| `0.35 × 42.85` | `14.9975` | 4 decimals |
| `0.95 × 10.5` | `9.975` | 3 decimals |
| `0.28 × 517.2413` | `144.83…` | many decimals |

Fix: snap `(price, size)` onto the precision grid, always rounding **down** (never sizes a position larger than asked):

```python
quantized = quantize_order(price=0.35, desired_size=42.85, side="BUY")
# price=0.35, size=42.82857, notional_usdc=14.99
```

Algorithm:
1. Floor desired notional to 2 decimals.
2. Derive size from snapped notional, rounded to taker-decimals (5 for BUY, 4 for SELL).
3. Re-floor in case rounding nudged the product back over the maker quantum.

### Combined pre-trade gate (`evaluate_pre_trade`)

One-shot evaluator that combines edge + skip-tag + stop-loss into a single decision the calling skill acts on. Returns `PreTradeDecision(allow_trade, edge, skip, stop_loss, blockers)`. Skip + edge run in parallel; stop-loss is computed only when the trade is going to ship (caller needs it paired with the entry order).

## Strategy: safe compounder (`score_safe_compounder`)

Ported from zostaff/poly-trading-bot's `safe_compounder.py`. The structural insight: directional LLM bets on mid-probability markets bleed P&L because the agent doesn't have edge against sharps. **NO-side bets on near-certain outcomes** (lowest_no_ask > $0.80) at the top of the book, with a measurable edge over the live ask, are structurally favored on Polymarket given the fee structure.

Single-market evaluator — agent loops candidate markets through:

```python
candidate = score_safe_compounder(
    yes_last_price=0.04,    # YES trading at 4¢ → strong NO signal
    lowest_no_ask=0.92,     # NO ask at 92¢ — high-confidence NO wins
    volume=350.0,           # 24h USDC volume
    days_to_expiry=12.0,    # resolves in ~12 days
    portfolio_value=500.0,  # for Kelly sizing
)
# qualifies=True, suggested_limit_price=0.91, suggested_size_usdc=...
```

**Constraint stack** (every market must clear all):

| Constraint | Default | Why |
|---|---|---|
| `lowest_no_ask >= min_no_ask` | 0.80 | NO must already be priced as high-probability winner |
| `volume >= min_volume` | $10 | Below this, orderbook is too thin to trust |
| `days_to_expiry >= min_days` | 0.5 | Sub-half-day = late-stage volatility |
| `days_to_expiry <= max_days` | 60 | Too far out = too much can change |
| `edge >= min_edge` | 3% | Estimated NO prob beats live ask by ≥ this |
| Kelly size > 0 | — | Negative-EV → don't trade |

**Maker order placement**: `lowest_no_ask - $0.01` — sit 1¢ inside the book, earn maker rebates instead of paying taker fees.

**Position sizing**: half-Kelly with 10% portfolio cap. Kelly is theoretically right but operationally ruthless — half-Kelly + hard cap is what you actually want.

**This is not a magic profit machine.** It's a baseline strategy with lower variance than directional betting and a structural edge from maker fees + high-certainty markets. Use as a sister to the LLM directional bot — different risk profile, different cadence, both running in parallel via the resource-typed scheduler.

## Helper: NO probability estimation (`estimate_true_prob_no`)

Heuristic, not Bayesian:

- Base: `1 - yes_last_price`
- < 3 days to expiry: small certainty *bump* toward whichever side is dominant (1¢/day)
- > 30 days to expiry: small certainty *discount* toward 0.5 (max 5% at 60 days)

The real edge check is against the **live NO ask price**, not this estimate. The estimate just decides whether the market is worth pricing at all.

(Earlier version pulled too aggressively toward 0.5 at distance and disqualified obviously favorable bets; tightened 2026-05-07 mid-build.)

## Helper: Kelly fractional sizing (`kelly_position_size`)

For a binary bet at `price` (you stake `price` to win 1):

```
b = (1 - price) / price
f* = (p × b - q) / b   # Kelly fraction of bankroll
```

Where `p = estimated_win_prob`, `q = 1 - p`. Negative or tiny `f*` → return 0 (don't trade).

Returned size is `portfolio_value × min(f* × 0.5, cap_pct)` — half-Kelly + hard cap. Cap defaults to 10% per position.

## Tool surface

Five SAFE pure-decision tools, all in `tools/polymarket/`:

| Tool | Purpose | Permission |
|---|---|---|
| `polymarket_pre_trade` | Universal gate: edge + skip-tag + stop-loss calc | SAFE |
| `polymarket_circuit_breaker` | Drawdown gate before opening positions | SAFE |
| `polymarket_quantize_order` | Snap order to Polymarket's precision grid | SAFE |
| `polymarket_safe_compounder` | Score a market for the NO-side baseline strategy | SAFE |

All four are pure decision tools — no I/O, no DB, no LLM calls. The actual order placement still happens via `py-clob-client` in the skill flow. The tools just enforce the rules.

`PolymarketConfig` (in `core/config.py`) is injected at startup via `Agent._inject_jobs_deps` — operator-set thresholds flow through.

## Skill orchestration

`skills/web3-polymarket/SKILL.md` was extended with three new mandatory sections:

- **§6 — Pre-trade risk gate** (Tier 1). Three explicit steps: drawdown breaker → pre-trade gate → place entry **AND** companion stop-loss/TP limits.
- **§7 — Precision quantization** (Tier 2). Mandatory `polymarket_quantize_order` call before every `create_and_post_order`. Concrete failure-case table from the live DB.
- **§8 — Safe-compounder strategy** (Tier 2). Full Python orchestration: scorer → universal gate → quantizer → place order → stop-loss/TP. Shows how the strategy composes with the gate layer.
- **§9 — Other safety rails**. Includes the `not enough balance / allowance` failure analysis (the 25% non-precision failures): wallet/proxy mismatch (re-run §3a) or USDC allowance never set.

## Configuration

In `config.yaml`:

```yaml
polymarket:
  enabled: true

  # Edge filter
  min_edge: 0.04              # 4% global floor
  high_confidence_edge: 0.03  # confidence >= high_cutoff
  medium_confidence_edge: 0.05
  low_confidence_edge: 0.08
  high_confidence_cutoff: 0.70
  low_confidence_cutoff: 0.40

  # Stop-loss / take-profit
  stop_loss_pct: 0.07         # 7% stop
  take_profit_pct: 0.20       # 20% TP

  # Drawdown circuit breaker
  drawdown_pause_pct: 0.20    # pause new entries at 20% drawdown

  # Skip-tag overrides (empty list = use defaults)
  skip_tag_slugs: []
  skip_title_phrases: []
```

All defaults are conservative — easier to start tight and loosen on measured evidence than the reverse.

## What's NOT in scope

- **Order placement.** Still happens via `py-clob-client` in the skill — these tools are decision-only.
- **Market discovery.** Skill uses Gamma API; tools don't fetch market data.
- **Position monitoring.** No background process watches stops/TPs after placement; the limit orders sit on Polymarket's book.
- **Cancellation logic.** If a stop hits before TP (or vice versa), the second still sits on the book until cancelled. Operator/skill responsibility — Polymarket also auto-cancels resting orders on resolution.
- **Per-strategy budget caps.** All strategies share the same wallet; operator sets daily/per-tx caps in `payments` config.
- **Multi-strategy orchestration.** Each strategy is its own scheduled task; the resource-typed scheduler (docs/70-SCHEDULER-CONCURRENCY.md) handles parallelism.

## Tests

`tests/test_core/test_polymarket_engine.py` (51 tests):

- **Edge filter** (7) — block-on-low-edge, allow-on-high-edge, NO-side derivation, asymmetric thresholds, OOB-clamp, confidence bands, threshold ordering.
- **Skip tags** (7) — sports, awards, title-phrase, legitimate market, case-insensitive, empty inputs, default-list sanity.
- **Stop-loss levels** (6) — BUY mirror, SELL mirror, low-confidence halving, edge-clamping, invalid entry, invalid side.
- **Drawdown breaker** (5) — threshold breach, within-threshold, above-peak edge case, zero-peak default, configurable threshold.
- **Combined pre-trade** (6) — allow-when-all-pass, block-on-skip, block-on-no-edge, NO-side picks SELL entry, config loosens, config clears skip.
- **Precision quantizer** (5) — replicates real failure case, pass-through clean amounts, BUY/SELL decimals, dust rejection, invalid inputs.
- **Estimate NO prob** (3) — low YES = high NO, high YES = low NO, far expiry pulls toward uncertainty.
- **Kelly sizing** (4) — positive edge, no edge, zero portfolio, cap respected.
- **Safe compounder** (8) — qualifying market, low NO ask, low volume, no edge, too far out, too close to expiry, position cap, Kelly-zero.

## Future work

- **Per-strategy resource type.** Right now all Polymarket schedules contend on the `LLM_BURST` semaphore. The safe compounder doesn't actually need much LLM (it's mostly arithmetic). Adding a `POLYMARKET_API` resource type for strategies that mostly call the CLOB would let the safe compounder run more frequently.
- **`set_allowances` automation.** The 25% "not enough balance" failures all need a one-time operator action (run `set_allowances.py`). Could detect this on first failure and surface a structured "operator action needed" event.
- **Live performance feedback.** Daily job that reads `order_history`, computes per-strategy realized P&L, and feeds back into `min_edge` tuning. zostaff has `src/jobs/performance_analyzer.py` (391 LOC) for this; we don't have an equivalent.
- **Multi-leg position tracking.** Stop-loss + TP are placed but we don't track the pair. If the stop fills, the TP needs to be cancelled (and vice versa). Currently both sit on the book until resolution.
- **Order-state reconciler.** A loop that periodically reads `client.get_open_orders()` and reconciles against our local `polymarket_orders` table — catches divergence (orders that filled silently, orders that were cancelled by the exchange).
