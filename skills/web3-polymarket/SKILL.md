---
name: web3-polymarket
description: Polymarket integration for prediction market trading on Polygon. Covers authentication (L1 EIP-712, L2 HMAC-SHA256, builder headers), order placement (GTC/GTD/FOK/FAK, batch, post-only, heartbeat), market data (Gamma API, Data API, orderbook, subgraph), WebSocket streaming (market/user/sports channels), CTF operations (split, merge, redeem, negative risk), bridge (deposits, withdrawals, multi-chain), and gasless relayer transactions. Use when building AI agents, autonomous market makers, prediction market UIs, or any application integrating with Polymarket on Polygon.
compatibility: Requires network access to Polymarket APIs (clob.polymarket.com, gamma-api.polymarket.com) and Polygon RPC
---

# Polymarket Skill

> **Source:** Official Polymarket skill from [Polymarket/agent-skills](https://github.com/Polymarket/agent-skills). Keep in sync with upstream. The "EloPhanto Setup" section below is local — everything else mirrors upstream.

## EloPhanto Setup

**Triggers:** "polymarket", "prediction market", "place a bet", "polygon", "CLOB", "trading bot for polymarket".

### 1. Install the Python SDK on first use
```bash
pip install py-clob-client-v2     # use the -v2 fork; the legacy `py-clob-client` package returns order_version_mismatch on new orders as of 2026-05-11
```
(Run via `shell_execute`. Not in `pyproject.toml` by default — only installed when this skill is actually used.)

### 2. Store credentials in the vault (one-time)
```
vault_set polymarket_private_key VALUE   # Polygon EOA private key (the funding wallet)
vault_set polymarket_funder_address VALUE # Proxy/safe address from polymarket.com/settings (only if signature_type != 0)
vault_set polymarket_signature_type 2    # 0=EOA, 1=POLY_PROXY, 2=GNOSIS_SAFE (most common = 2)
```

### 3. Use credentials in Python via `vault_lookup`
```python
from py_clob_client.client import ClobClient

pk = vault_lookup("polymarket_private_key")
funder = vault_lookup("polymarket_funder_address")
sig_type = int(vault_lookup("polymarket_signature_type") or "2")

temp = ClobClient("https://clob.polymarket.com", key=pk, chain_id=137)
creds = temp.create_or_derive_api_creds()
client = ClobClient(
    "https://clob.polymarket.com",
    key=pk, chain_id=137,
    creds=creds,
    signature_type=sig_type,
    funder=funder,
)
```

### 3a. Auto-detect which signature_type holds the collateral

The same `polymarket_private_key` can have funds across **multiple
proxy types** (EOA, POLY_PROXY, GNOSIS_SAFE). Polymarket's web UI
shows whichever wallet you're toggled to; users routinely deposit
into one (e.g. POLY_PROXY) while their vault config points at
another (e.g. GNOSIS_SAFE). Result: SDK reports `$0 USDC` and the
order fails with "insufficient balance" or `order_version_mismatch`
for reasons that look like coding errors.

**Always probe all three before placing the first order of a
session** and use whichever one is funded:

```python
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

best_sig_type = None
best_balance_usdc = 0.0
for sig_type in (0, 1, 2):
    try:
        c = ClobClient(
            "https://clob.polymarket.com",
            key=pk, chain_id=137,
            signature_type=sig_type,
            funder=funder,
        )
        c.set_api_creds(c.create_or_derive_api_creds())
        bal = c.get_balance_allowance(
            BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL, signature_type=sig_type
            )
        )
        usdc = int(bal.get("balance", 0)) / 1_000_000
        print(f"sig_type={sig_type}: ${usdc:.2f} USDC")
        if usdc > best_balance_usdc:
            best_balance_usdc, best_sig_type = usdc, sig_type
    except Exception as e:
        print(f"sig_type={sig_type}: probe failed ({e!r})")

if best_sig_type is None or best_balance_usdc == 0:
    raise SystemExit("No funded Polymarket wallet found for this key.")

# Use the funded sig_type for the rest of the session.
client = ClobClient(
    "https://clob.polymarket.com",
    key=pk, chain_id=137,
    signature_type=best_sig_type,
    funder=funder,
)
client.set_api_creds(client.create_or_derive_api_creds())
```

If the detected `best_sig_type` differs from the vault setting,
**update the vault** so future sessions don't re-probe:
`vault_set polymarket_signature_type <N>`.

### 4. Place orders ONLY via the API. Never via the browser.

**Hard rule:** all Polymarket order placement must go through
`py-clob-client`. **Never** drive `polymarket.com` via the browser
tools to place a trade. The web UI uses Privy/embedded-wallet flows
that aren't compatible with the funder wallet stored in the vault —
mis-clicks place real orders, and the agent has no way to verify the
order before it submits. If the SDK fails, **stop and report the
exact error**; do not switch to the GUI as a fallback.

### 5. Discover tick_size and neg_risk dynamically (don't hardcode)

`create_order` requires both options. Both are per-market and the
SDK / on-chain values are authoritative — guessing a wrong tick_size
("0.01" vs "0.001") rejects the order with a confusing error.

```python
# Fetch directly from the CLOB
tick_size = client.get_tick_size(token_id)        # "0.001" / "0.01" / "0.1"
neg_risk  = client.get_neg_risk(token_id)         # bool

signed = client.create_order(
    OrderArgs(token_id=token_id, price=price, size=size, side=BUY),
    options={"tick_size": tick_size, "neg_risk": neg_risk},   # ← keyword arg, dict
)
resp = client.post_order(signed, OrderType.GTC)
```

If `get_neg_risk` isn't available in your installed py-clob-client
version, read `negRisk` from the market metadata via gamma-api:

```python
import requests
m = requests.get(
    "https://gamma-api.polymarket.com/events",
    params={"slug": EVENT_SLUG}, timeout=20,
).json()[0]["markets"]
neg_risk = next(mk for mk in m if mk["clobTokenIds"] and token_id in mk["clobTokenIds"])["negRisk"]
```

The `options` parameter is **keyword-only in newer SDK versions** —
passing it positionally raises `TypeError`. Always use `options=`.

### 6. **MANDATORY** pre-trade risk gate (do this BEFORE every place_order)

The agent's live trade history showed serial losses from buying mid-probability markets with no edge measurement and no exits. Two tools enforce the constraints; **both must pass before placing an entry order**.

**Step A — drawdown circuit breaker.** Before opening ANY new position:

```python
breaker = polymarket_circuit_breaker(
    peak_equity=<rolling 30-day high USD>,
    current_equity=<current portfolio USD>,
)
if breaker["paused"]:
    # Drawdown threshold (default 20%) breached. Do NOT open new
    # positions. Closing existing ones stays allowed. Wait for
    # equity to recover or operator override.
    raise SystemExit(breaker["reason"])
```

**Step B — pre-trade gate.** For each candidate market:

```python
gate = polymarket_pre_trade(
    llm_prob=<your estimated probability of YES>,
    market_price=<current YES price from orderbook>,
    confidence=<your self-reported confidence 0-1>,
    market_tags=<list of Polymarket parent-event tag slugs>,
    market_title=<market question text>,
)
if not gate["allow_trade"]:
    # blockers will list reasons: edge too small, sports tag,
    # title-phrase blocklist hit, etc. Skip this market.
    continue

stop_levels = gate["stop_loss"]
# stop_levels["stop_loss_price"] and ["take_profit_price"] are the
# companion limit orders you MUST place immediately on entry fill.
```

**Step C — place the entry order, THEN immediately place the companion stop-loss + take-profit limits.**

⚠️ **Stop-limits on Polymarket are NOT triggered orders** — they're regular limit orders sitting on the book. If your "stop-loss" price crosses the current orderbook (e.g. setting a sell-stop at 0.94 when the highest bid is 0.95), it **executes instantly** at the best bid, immediately closing the position you just opened. Before posting the protective limit, fetch the current top-of-book and verify your stop price is *outside* it (below highest bid for sell-stops, above lowest ask for buy-stops). See the 2026-05-11 retro: agent self-flagged this after accidentally selling 7.49 of a 7.5-share NO position via a stop-limit that crossed the book.

```python
# 1. Entry order at market or your chosen limit
entry_resp = client.create_and_post_order(OrderArgs(
    token_id=token_id,
    price=entry_price,
    size=size,
    side=BUY if gate["edge"]["side"] == "YES" else SELL,
))

# 2. Stop-loss limit (sell-side for a BUY entry, buy-side for SELL)
client.create_and_post_order(OrderArgs(
    token_id=token_id,
    price=stop_levels["stop_loss_price"],
    size=size,
    side=SELL if gate["edge"]["side"] == "YES" else BUY,
))

# 3. Take-profit limit
client.create_and_post_order(OrderArgs(
    token_id=token_id,
    price=stop_levels["take_profit_price"],
    size=size,
    side=SELL if gate["edge"]["side"] == "YES" else BUY,
))
```

**Why this is non-negotiable:** the gate's edge filter blocks trades where your "insight" is already priced in (paying spread for nothing). The skip-tag filter excludes sports / entertainment / awards markets — pure noise that LLM bets have no edge against sharps. The stop-loss + take-profit pair caps downside on every position so single losing positions can't dominate P&L. The circuit breaker stops you from tilt-trading after a bad week.

Tunable via `polymarket:` section in `config.yaml` (edge thresholds, stop pcts, drawdown threshold, skip-tag overrides). See `core/polymarket_engine.py` for the math.

### 6a. **MANDATORY** drawdown halt + owner-ack (built into pre_trade)

Pass `peak_equity` and `current_equity` into `polymarket_pre_trade` on every call. The gate runs the circuit breaker inline: if drawdown ≥ `polymarket.drawdown_pause_pct` (default 20%), `allow_trade` becomes `false` with a `drawdown_halt` blocker. **Closing existing positions stays allowed; only NEW entries are gated.** To re-enable new entries, surface the drawdown to the owner with the exact `drawdown.reason` from the gate's response, get explicit go-ahead, then re-call with `drawdown_acknowledged=true`. Never set the ack flag without that explicit owner conversation in the current session.

### 6b. **MANDATORY** upside-alignment rule (built into pre_trade)

The aggressive mandate is **strong returns with frequent opportunities**. A 95.6¢ → $1.00 grind is a +4.6% gross max — that's capital-preservation, not edge-hunting. Compute max gross upside before every entry:

- **YES side** at price `P`: `upside_pct = (1 - P) / P`
- **NO side** at price `P` (the YES price on the orderbook): `upside_pct = P / (1 - P)`

Pass `upside_pct` into `polymarket_pre_trade`. The gate refuses (`allow_trade=false`, `upside_misaligned` blocker) when:

- `upside_pct < 0.10` and `capital_preservation_ack` is unset → skip the trade entirely
- `upside_pct < 0.20` and time-to-resolution > 14 days → low yield AND slow turnover; almost never worth it

The alignment ladder you want to climb:

| Upside | Time to resolve | Verdict |
|---|---|---|
| ≥ 20% | any | Aligned with mandate — normal Kelly sizing |
| 10–20% | < 14 days | Borderline — open small (~3% bankroll), needs n_resolved data to defend |
| < 10% | any | Capital-preservation only — pass `capital_preservation_ack=true` AND limit position to <2% bankroll, OR skip |

This is the agent's own self-rule, derived from the 2026-05-11 cash-parking-bet retro: *"hunt for clear mispriced near-term event with 20%+ upside, or don't bet."* Encoded here as a permanent gate, not a one-off lesson.

### 7. **MANDATORY** precision quantization (do this BEFORE every create_and_post_order)

Polymarket rejects orders whose `price × size` (USDC notional) has more than 2 decimals. Live trade history showed **6 of 8 failed orders** hit this exact rule:

> *"invalid amounts, the market buy orders maker amount supports a max accuracy of 2 decimals, taker amount a max of 5 decimals"*

Concrete examples that were silently rejected:

| desired price × size  | computed notional | result |
|---|---|---|
| `0.35 × 42.85` | `14.9975` USDC | rejected (4 decimals) |
| `0.95 × 10.5` | `9.975` USDC | rejected (3 decimals) |
| `0.28 × 517.2413` | `144.83...` USDC | rejected (many decimals) |

Use `polymarket_quantize_order` to snap onto the precision grid before every order:

```python
quantized = polymarket_quantize_order(
    price=0.35,
    desired_size=42.85,
    side="BUY",
)
# quantized -> {price: 0.35, size: 42.82857, notional_usdc: 14.99, side: "BUY",
#               rationale: "desired notional 14.9975 → snapped 14.99 USDC ..."}

# Then place with the SNAPPED size:
client.create_and_post_order(OrderArgs(
    token_id=token_id,
    price=quantized["price"],
    size=quantized["size"],
    side=BUY,
))
```

The tool always rounds DOWN — your position is never larger than what you asked for; it's at most a fraction of a share smaller. Combined with the pre-trade gate (§6) and the strategy scorer (§8), this closes the precision-error loss leak.

### 8. Safe-compounder strategy (NO-side baseline)

The pre-trade gate (§6) is mandatory but neutral — it checks any trade your strategy proposes. The directional LLM bot you've been running tends to find low-edge mid-probability bets that bleed P&L. Add the safe-compounder as a structurally-favored sister strategy that runs in parallel.

**The insight:** trade NO on markets where the lowest NO ask is already > $0.80 (high-probability NO wins), the time-decay-amplified NO probability beats the live ask by ≥ 3%, and Kelly sizing returns a positive fraction. Place the maker order 1¢ inside the lowest NO ask — sit on the book and earn rebates instead of paying taker fees.

```python
candidate = polymarket_safe_compounder(
    yes_last_price=0.05,         # YES is trading at 5¢ → strong NO signal
    lowest_no_ask=0.92,          # NO ask at 92¢ — high-confidence NO wins
    volume=350.0,                # 24h USDC volume on this market
    days_to_expiry=12.0,         # Resolves in ~12 days
    portfolio_value=500.0,       # Total Polymarket portfolio in USDC
)

if not candidate["qualifies"]:
    # rationale lists which constraint failed (low volume, no edge,
    # sub-half-day expiry, off-band price, etc.). Skip this market.
    continue

# Then run the universal pre-trade gate as well:
gate = polymarket_pre_trade(
    llm_prob=candidate["estimated_no_prob"],
    market_price=candidate["suggested_limit_price"],
    confidence=0.75,             # safe-compounder is structurally high-confidence
    market_tags=market_tags,
    market_title=market_title,
)
if not gate["allow_trade"]:
    continue

# Snap size to precision grid:
quantized = polymarket_quantize_order(
    price=candidate["suggested_limit_price"],
    desired_size=candidate["suggested_size_usdc"] / candidate["suggested_limit_price"],
    side="BUY",  # buying NO tokens = BUY on the NO token side
)

# Place the maker limit order on the NO token at lowest_no_ask - 1¢
client.create_and_post_order(OrderArgs(
    token_id=no_token_id,
    price=quantized["price"],
    size=quantized["size"],
    side=BUY,
))
# Then immediately place stop-loss + take-profit per §6 (Step C).
```

This is **not a magic profit machine.** It's a baseline strategy with lower variance than directional betting and a structural edge from maker fees + high-certainty markets. Use as a sister to your LLM directional bot — different risk profile, different cadence, both running in parallel via the resource-typed scheduler.

Defaults from `core/polymarket_engine.py` (operator-tunable in future via PolymarketConfig if you need): `min_no_ask=0.80`, `min_edge=0.03`, `min_volume=$10`, `days_to_expiry=[0.5, 60]`, `max_position_pct=10%` (half-Kelly capped), `maker_offset=$0.01`.

### 8a. **MANDATORY** calibration audit logging (do this AFTER pre-trade gate, BEFORE create_and_post_order)

The risk gates (§6) tell you whether to trade. The calibration audit tells you whether your trades are *any good* — bucketing realized win rate vs the LLM's stated probability AND vs entry price. Without it, you can't tell if the bot is making money for the right reasons or just lucky.

Three tools, one feedback loop. **All three steps below are mandatory in this exact order before placing any new entry**:

**Step 1 — read calibration first.** Call `polymarket_calibration` BEFORE deciding to enter. The report tells you whether the bot's "high confidence" claims have been calibrated by actual resolutions. Skip the trade if any of these are true:
- `brier_score > 0.25` over `n_resolved ≥ 30` — bot is anti-correlated with reality, flag to owner.
- `by_confidence_band[band].calibration_gap < -0.10` over n ≥ 30 in that band — that band's edge threshold is too lax. Tighten `polymarket.<band>_confidence_edge` in `config.yaml` before betting more in that band.
- `n_resolved < 10` — you don't have enough resolved data to defend the strategy. Either keep entries tiny (<2% bankroll) or hold off until the data accumulates.

**Step 2 — call `polymarket_safe_compounder` to compute Kelly fraction**, even when running the directional bot. The Kelly fraction is the sizing strategy's signature; you'll need it threaded into log_prediction so the calibration audit can later answer *"was my sizing any good?"*. If safe_compounder declines the trade entirely, that's a signal — re-examine the thesis.

**Step 3 — call `polymarket_log_prediction`** AFTER the pre-trade gate passes (with drawdown + upside ack as needed from §6a/§6b) and BEFORE `client.create_and_post_order`. Pass:
   - `token_id`, `side` (`YES`/`NO`), `entry_price`, `size`
   - `llm_prob` — your probability that *YES* wins (always YES-frame; the audit re-frames internally)
   - `confidence_band` — same value you fed to `polymarket_pre_trade`
   - **`kelly_fraction` — the value returned by `polymarket_safe_compounder` in step 2.** The tool warns when this is zero/missing on a non-trivial size; treat that warning as a hard fix-it-now, not an FYI.
   - `order_type` (`post-only` / `GTC` / `FOK` / etc.), `market_slug`, one-line `rationale`

`polymarket_resolve_pending` fetches Polymarket Gamma API and updates `settle_price` + `outcome` + `realized_pnl` on resolved markets. Schedule it on a cadence that fits your fastest-resolving market type: every 5 min for 15-min crypto Up/Down markets, every hour for hourly news binaries, every 6h for weekly markets. ONE cron at the fastest cadence is fine — the tool's per-slug cache dedupes Gamma calls so checking every 5 min for 100 pending markets is still only 100 unique HTTP requests per run (loose well within Gamma rate limits). Operator-side; agent normally doesn't invoke it directly.

```python
# Example: log a prediction right after the gate passes.
log_result = polymarket_log_prediction(
    token_id=order_args["token_id"],
    side=order_args["side"],
    entry_price=order_args["price"],
    size=order_args["size"],
    llm_prob=my_yes_prob,
    confidence_band=gate_input["confidence_band"],
    kelly_fraction=gate["sizing"]["kelly_fraction"],
    order_type=order_args.get("order_type", "GTC"),
    market_slug=market["slug"],
    rationale=one_line_thesis,
)
# THEN place the actual order.
client.create_and_post_order(...)
```

### 9. Performance inspection (operator-side, optional for the agent)

Operator inspects trade history with:

```bash
elophanto polymarket performance              # all-time + 30d + 7d side-by-side
elophanto polymarket performance --window 7d  # last week only
elophanto polymarket performance --positions  # add per-position tables
elophanto polymarket performance --failures-only  # just the error breakdown
```

Output leads with **net P&L assuming open positions resolve at zero** (the conservative honest read), then breaks out realized vs. unrealized so the operator can mark specific positions to market if any are still worth something.

The same data is exposed to the agent via `polymarket_performance` for ad-hoc reads when explicitly asked ("how am I doing on Polymarket?"). It is **not** required for every trade — the universal risk gates (§6, §7) already enforce the constraints; calling the analyzer before each order risks token cost without behavior change.

### 10. Other safety rails
- **Always confirm with the owner before placing real-money orders.** Treat trade execution as `DESTRUCTIVE` permission level — surface the order params (token, side, price, size, USDC cost) and wait for explicit approval.
- Read-only operations (orderbook, market data, positions) need no approval.
- Polymarket trades USDC.e on Polygon. Make sure the funder wallet has USDC.e and a small amount of POL for gas (only if `signature_type=0`; gasless via Gnosis Safe doesn't need POL).
- **`not enough balance / allowance` failures** — 2 of 8 historical failures hit this. Two causes: (a) wallet/proxy mismatch — re-run §3a `Auto-detect which signature_type holds the collateral` and use whichever sig_type actually holds the funds; (b) USDC allowance never set on the Polymarket contracts — operator runs `python scripts/set_allowances.py` once per wallet (script ships in `py-clob-client` examples).
- Never log or echo `polymarket_private_key`.

---

## When to use this skill

Use this skill when the user asks about or needs to build:
- Polymarket API authentication (L1/L2, API keys, HMAC signing)
- Placing or managing orders (limit, market, GTC, GTD, FOK, FAK, batch, cancel)
- Reading orderbook data (prices, spreads, midpoints, depth)
- Market data fetching (events, markets, by slug, by tag, pagination)
- WebSocket subscriptions (market channel, user channel, sports)
- CTF operations (split, merge, redeem positions)
- Negative risk markets (multi-outcome, conversion, augmented neg risk)
- Bridge operations (deposits, withdrawals, multi-chain)
- Gasless transactions (relayer client, order attribution)
- Builder program integration (order attribution, API keys, tiers)
- Polymarket SDK usage (TypeScript @polymarket/clob-client, Python py-clob-client)

## API Configuration

| API | Base URL | Auth | Purpose |
|-----|----------|------|---------|
| CLOB | `https://clob.polymarket.com` | L2 for trade endpoints | Orderbook, prices, order submission |
| Gamma / Data | `https://gamma-api.polymarket.com` | None | Events, markets, search |
| Data API | `https://data-api.polymarket.com` | None | Trades, positions, user data |
| WebSocket (Market) | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | None | Real-time orderbook |
| WebSocket (User) | `wss://ws-subscriptions-clob.polymarket.com/ws/user` | API creds in message | Trade/order updates |
| WebSocket (Sports) | `wss://sports-api.polymarket.com/ws` | None | Live scores |
| Relayer | `https://relayer-v2.polymarket.com/` | Builder headers | Gasless transactions |
| Bridge | `https://bridge.polymarket.com` | None | Deposits/withdrawals |

## Contract Addresses (Polygon)

| Contract | Address |
|----------|---------|
| USDC (USDC.e) | `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` |
| CTF (Conditional Tokens) | `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` |
| CTF Exchange | `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` |
| Neg Risk CTF Exchange | `0xC5d563A36AE78145C45a50134d48A1215220f80a` |
| Neg Risk Adapter | `0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296` |

## Client Setup

### TypeScript
```typescript
import { ClobClient, Side, OrderType } from "@polymarket/clob-client";
import { Wallet } from "ethers"; // v5.8.0

const HOST = "https://clob.polymarket.com";
const CHAIN_ID = 137;
const signer = new Wallet(process.env.PRIVATE_KEY);

// Step 1: L1 — derive API credentials
const tempClient = new ClobClient(HOST, CHAIN_ID, signer);
const apiCreds = await tempClient.createOrDeriveApiKey();

// Step 2: L2 — init trading client
const client = new ClobClient(
  HOST,
  CHAIN_ID,
  signer,
  apiCreds,
  2,                // signatureType: 0=EOA, 1=POLY_PROXY, 2=GNOSIS_SAFE
  "FUNDER_ADDRESS"  // proxy wallet address from polymarket.com/settings
);
```

### Python
```python
from py_clob_client.client import ClobClient
import os

host = "https://clob.polymarket.com"
chain_id = 137
pk = os.getenv("PRIVATE_KEY")

# Step 1: L1 — derive API credentials
temp_client = ClobClient(host, key=pk, chain_id=chain_id)
api_creds = temp_client.create_or_derive_api_creds()

# Step 2: L2 — init trading client
client = ClobClient(
    host,
    key=pk,
    chain_id=chain_id,
    creds=api_creds,
    signature_type=2,  # 0=EOA, 1=POLY_PROXY, 2=GNOSIS_SAFE
    funder="FUNDER_ADDRESS",
)
```

## Quick Reference: Order Types

| Type | Behavior | Use Case |
|------|----------|----------|
| **GTC** | Rests on book until filled or cancelled | Default limit orders |
| **GTD** | Active until expiration (UTC seconds). Min = `now + 60 + N` | Auto-expire before events |
| **FOK** | Fill entirely immediately or cancel | All-or-nothing market orders |
| **FAK** | Fill what's available, cancel rest | Partial-fill market orders |

- FOK/FAK BUY: `amount` = dollar amount to spend
- FOK/FAK SELL: `amount` = number of shares to sell
- Post-only: GTC/GTD only — rejected if would cross spread

## Quick Reference: Signature Types

| Type | Value | Description |
|------|-------|-------------|
| EOA | `0` | Standard Ethereum wallet (MetaMask). Funder is the EOA address and will need POL for gas. |
| POLY_PROXY | `1` | Custom proxy wallet for Magic Link email/Google users who exported PK from Polymarket.com. |
| GNOSIS_SAFE | `2` | Gnosis Safe multisig proxy wallet (most common). Use for any new or returning user. |

## Core Pattern: Place an Order

### TypeScript
```typescript
const response = await client.createAndPostOrder(
  {
    tokenID: "TOKEN_ID",
    price: 0.50,
    size: 10,
    side: Side.BUY,
  },
  {
    tickSize: "0.01",  // from client.getTickSize(tokenID) or market object
    negRisk: false,    // from client.getNegRisk(tokenID) or market object
  },
  OrderType.GTC
);
console.log(response.orderID, response.status);
```

### Python
```python
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

response = client.create_and_post_order(
    OrderArgs(token_id="TOKEN_ID", price=0.50, size=10, side=BUY),
    options={"tick_size": "0.01", "neg_risk": False},
    order_type=OrderType.GTC,
)
print(response["orderID"], response["status"])
```

## Core Pattern: Read Orderbook

### TypeScript
```typescript
// No auth needed
const readClient = new ClobClient("https://clob.polymarket.com", 137);
const book = await readClient.getOrderBook("TOKEN_ID");
console.log("Best bid:", book.bids[0], "Best ask:", book.asks[0]);

const mid = await readClient.getMidpoint("TOKEN_ID");
const spread = await readClient.getSpread("TOKEN_ID");
```

### Python
```python
read_client = ClobClient("https://clob.polymarket.com", chain_id=137)
book = read_client.get_order_book("TOKEN_ID")
mid = read_client.get_midpoint("TOKEN_ID")
spread = read_client.get_spread("TOKEN_ID")
```

## Core Pattern: WebSocket Subscribe

```typescript
const ws = new WebSocket("wss://ws-subscriptions-clob.polymarket.com/ws/market");

ws.onopen = () => {
  ws.send(JSON.stringify({
    type: "market",
    assets_ids: ["TOKEN_ID"],
    custom_feature_enabled: true,
  }));
  // Send PING every 10s to keep alive
  setInterval(() => ws.send("PING"), 10_000);
};

ws.onmessage = (event) => {
  if (event.data === "PONG") return;
  const msg = JSON.parse(event.data);
  // msg.event_type: "book" | "price_change" | "last_trade_price" | "tick_size_change" | "best_bid_ask" | "new_market" | "market_resolved"
};
```

## Reference files (load on demand)

Only read these when the task requires deeper detail on a specific topic:

- **Authentication** (L1/L2, builder headers, credential lifecycle): [authentication.md](authentication.md)
- **Order patterns** (GTC/GTD/FOK/FAK, tick sizes, cancel, heartbeat, errors): [order-patterns.md](order-patterns.md)
- **Market data** (Gamma API, Data API, CLOB orderbook, subgraph): [market-data.md](market-data.md)
- **WebSocket** (market/user/sports channels, subscribe, heartbeat): [websocket.md](websocket.md)
- **CTF operations** (split, merge, redeem, neg risk, token IDs): [ctf-operations.md](ctf-operations.md)
- **Bridge** (deposits, withdrawals, supported chains/tokens, status): [bridge.md](bridge.md)
- **Gasless transactions** (relayer client, wallet deployment, builder setup): [gasless.md](gasless.md)

## Verify

- A real RPC/SDK call was issued (mainnet, devnet, or local validator) and the response payload is captured in the transcript, not just paraphrased
- Every transaction was simulated (`simulateTransaction` or equivalent) before any signing/sending step; simulation logs are attached
- For any signed/sent transaction, the resulting signature is recorded and confirmed on chain (status returned by `getSignatureStatuses` or an explorer URL)
- Slippage, priority-fee, and compute-unit limits were set explicitly with concrete numeric values, not left to library defaults
- Account addresses, mints, and program IDs used in the run match the documented web3-polymarket addresses for the targeted cluster (no mainnet/devnet mix-up)
- Failure path was exercised at least once (insufficient balance, stale oracle, expired blockhash, etc.) and the agent's error handling produced a human-readable message
