# 64 — Polymarket Integration

> Prediction market trading on Polygon via the official Polymarket
> agent-skills bundle. Read-only market data and orderbook access by
> default; live order placement gated behind owner approval.

**Status:** Skill installed
**Priority:** P2 — Optional capability
**Source:** [Polymarket/agent-skills](https://github.com/Polymarket/agent-skills) (official)

---

## What's installed

`skills/web3-polymarket/` — verbatim copy of the official Polymarket
skill, plus a small "EloPhanto Setup" section prepended that explains
how to wire the agent's vault into the SDK.

| File | Purpose |
|------|---------|
| `SKILL.md` | Entry point — when to use, API config, client setup, core patterns |
| `authentication.md` | L1 EIP-712 + L2 HMAC-SHA256, builder headers |
| `order-patterns.md` | GTC / GTD / FOK / FAK, post-only, cancel, batch, heartbeat |
| `market-data.md` | Gamma API, Data API, CLOB orderbook, subgraph |
| `websocket.md` | Market / user / sports channels, ping/pong |
| `ctf-operations.md` | Split, merge, redeem, neg risk |
| `bridge.md` | Deposits, withdrawals, multi-chain |
| `gasless.md` | Relayer client, attribution, builder setup |

The agent loads only `SKILL.md` by default (~5KB); the reference files
are loaded on demand when a specific topic comes up.

---

## What's NOT installed

This is **skill-only**. There is no `polymarket_*` tool group — the
agent uses the skill as a playbook to write Python scripts on demand
that call `py-clob-client` directly. This mirrors the pattern we use
for `agentcash-onboarding`, `web-deployment`, etc.

If we later want native tool wrappers (e.g. `polymarket_place_order`,
`polymarket_orderbook`), that's a separate doc and would add:
- `tools/polymarket/` group with permission-gated tools
- `py-clob-client` as a hard dependency in `pyproject.toml`
- Config section under `payments.polymarket:` with funder address etc.

---

## Setup (one-time)

### 1. Install the SDK
The agent will run this on first use:
```bash
pip install py-clob-client
```
We deliberately don't pin it in `pyproject.toml` — Polymarket isn't
core, and avoiding the dep keeps cold installs fast.

### 2. Get a Polygon wallet
You need a Polygon EOA private key. Either:
- **Easy path (recommended):** Sign up at polymarket.com with email/Google,
  go to Settings → Export Private Key. This is a Gnosis Safe proxy
  wallet (`signature_type=2`). The skill will use the proxy address as
  the "funder."
- **Advanced:** Bring your own EOA / MetaMask wallet (`signature_type=0`)
  and fund it with USDC.e + POL for gas.

### 3. Store credentials in the vault
```
vault_set polymarket_private_key 0xYOUR_PRIVATE_KEY
vault_set polymarket_funder_address 0xYOUR_PROXY_ADDRESS
vault_set polymarket_signature_type 2
```

### 4. Verify
Ask the agent: *"check my polymarket positions"* — it should:
1. Match this skill via the trigger
2. Read SKILL.md
3. Install `py-clob-client` if missing
4. Pull credentials via `vault_lookup`
5. Use Data API to list your positions (no auth needed for read)

---

## Safety rails

The skill instructs the agent to:
- Treat **order placement** as a destructive operation — surface
  `(token, side, price, size, USDC cost)` and wait for explicit owner
  approval before submitting.
- Treat **read-only operations** (orderbook, prices, positions, market
  search) as safe — no approval needed.
- Never log or echo `polymarket_private_key`.
- Verify USDC.e + POL balance before placing trades when using EOA
  signature type.

These match the conventions in `core/executor.py` permission tiers and
the existing `agent-commune` / `agentcash-onboarding` skills.

---

## What the agent can now do

- **Read market data:** orderbook, midpoint, spread, depth, market
  search by tag/slug, event resolution status
- **Stream:** WebSocket subscriptions for real-time orderbook updates,
  user trade fills, sports scores
- **Trade (with approval):** place GTC/GTD/FOK/FAK orders, cancel,
  batch operations, post-only limit orders
- **CTF operations:** split positions, merge complementary positions,
  redeem winning shares, handle negative risk markets
- **Bridge:** deposit USDC from Ethereum mainnet, withdraw to user's
  preferred chain
- **Gasless:** for Gnosis Safe wallets, use the relayer so the user
  doesn't need POL for gas

---

## Architecture notes

**Why a skill, not a tool group?**
- Polymarket is one of many possible prediction-market integrations.
  Adding it as a skill keeps the core lean.
- The Python SDK (`py-clob-client`) is well-maintained and complete.
  Wrapping every method as a tool would duplicate work.
- Skill format lets the agent compose Polymarket calls with anything
  else (writing them as one-off scripts via `execute_code` or
  `shell_execute`).

**Why USDC.e and not USDC?**
- Polymarket's CTF Exchange contract was deployed before native USDC
  was available on Polygon. It uses the bridged USDC (USDC.e) at
  `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`. Withdrawing to native
  USDC requires a swap.

**Why Gnosis Safe (signature_type=2) by default?**
- Most Polymarket users sign up via Magic Link (email/Google), which
  creates a Gnosis Safe proxy wallet for them. This is also the
  signature type that supports gasless trading via the relayer.

---

## References

- Official skill: https://github.com/Polymarket/agent-skills
- Python SDK: https://github.com/Polymarket/py-clob-client
- TypeScript SDK: https://github.com/Polymarket/clob-client
- API docs: https://docs.polymarket.com
