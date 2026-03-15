# EloPhanto — Payment Requests (Receiving Money)

> **Status: Planned** — Extends the existing payment system with the ability to receive payments. New tool (`payment_request`), request tracker, blockchain transaction scanning. Works with both Solana and EVM wallets.

## Overview

The agent can **send** crypto (Phase 1 done) but cannot yet **receive** payments for services it provides. This feature closes that gap — the agent can create payment requests (invoices), share payment details with counterparties, and monitor the blockchain for incoming transactions that match.

Combined with the prospecting system, this enables full revenue loops: find work → deliver → invoice → get paid.

### Design Principles

- **Same wallet, new direction** — Uses the existing agent wallet (local or CDP). No new wallet setup needed.
- **On-chain verification** — Scans real blockchain state to confirm payments. No trust required.
- **Shareable payment details** — Generates Solana Pay URIs or EVM payment links the agent can send via email, chat, or any channel.
- **Expiry & lifecycle** — Requests expire after a configurable TTL. Stale requests auto-expire.
- **Audit trail** — All requests logged to `payment_audit` alongside outgoing transactions.

## Architecture

```
Client: "How do I pay you?"
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  Agent: payment_request create                           │
│                                                          │
│  1. Get agent wallet address from PaymentsManager        │
│  2. Generate unique reference for matching                │
│  3. Create payment_requests DB record (status: pending)   │
│  4. Build payment link (Solana Pay URI / EVM URI)         │
│  5. Log to audit trail                                    │
│  6. Return: address, amount, token, link, reference       │
└────────────┬────────────────────────────────────────────┘
             │
             ▼
Agent shares payment details via email / chat / Telegram
             │
             ▼
Client sends crypto to agent wallet address
             │
             ▼
┌─────────────────────────────────────────────────────────┐
│  Agent: payment_request check                            │
│                                                          │
│  1. Fetch pending request from DB                        │
│  2. Scan blockchain for incoming transactions             │
│     - Solana: getSignaturesForAddress + getTransaction    │
│     - EVM: eth_getLogs (ERC-20 Transfer events)           │
│  3. Match by amount + token (tolerance: 0.1%)             │
│  4. If match found: update status → paid, store tx hash  │
│  5. Return: status, tx_hash, sender, amount               │
└─────────────────────────────────────────────────────────┘
```

### Payment Flow (End to End)

```
1. Agent completes work for a client
2. Agent creates payment request:
   → "Please send 50 USDC to HxK7...abc on Solana"
   → Includes Solana Pay link: solana:HxK7...abc?amount=50&spl-token=USDC_MINT
3. Agent sends details via email_send or chat message
4. Client pays via any Solana wallet (Phantom, Solflare, etc.)
5. Agent checks request status (manually or via heartbeat)
   → Scans recent incoming transactions
   → Finds matching 50 USDC transfer
   → Marks request as paid, stores tx hash
6. Agent confirms receipt to client
7. Audit trail records the full lifecycle
```

## Tool: `payment_request`

Single tool with 4 actions — mirrors the `payment_history` pattern.

### Actions

| Action | Permission | Description |
|--------|-----------|-------------|
| `create` | SAFE | Create a payment request with amount, token, memo |
| `check` | SAFE | Check if a pending request has been paid (scans blockchain) |
| `list` | SAFE | List requests filtered by status |
| `cancel` | MODERATE | Cancel a pending request |

### Input Schema

```json
{
  "action": "create | check | list | cancel",
  "amount": 50.0,
  "token": "USDC",
  "memo": "Website redesign — Phase 1",
  "ttl_minutes": 1440,
  "request_id": "abc123",
  "status": "pending | paid | expired | cancelled"
}
```

### Example Responses

**Create:**
```json
{
  "request_id": "req_a1b2c3d4",
  "wallet_address": "HxK7...abc",
  "chain": "solana",
  "token": "USDC",
  "amount": 50.0,
  "memo": "Website redesign — Phase 1",
  "reference": "ref_e5f6g7h8",
  "payment_link": "solana:HxK7...abc?amount=50&spl-token=EPjFW...USDC&reference=ref_e5f6g7h8",
  "expires_at": "2026-03-16T15:00:00Z",
  "status": "pending"
}
```

**Check (paid):**
```json
{
  "request_id": "req_a1b2c3d4",
  "status": "paid",
  "matching_tx_hash": "5xYz...abc",
  "matching_amount": 50.0,
  "matching_sender": "9kLm...xyz",
  "paid_at": "2026-03-15T14:32:10Z"
}
```

## Database

### `payment_requests` Table

```sql
CREATE TABLE IF NOT EXISTS payment_requests (
    request_id TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    chain TEXT NOT NULL,
    token TEXT NOT NULL,
    amount REAL NOT NULL,
    memo TEXT,
    reference TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    matching_tx_hash TEXT,
    matching_amount REAL,
    matching_sender TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    paid_at TEXT,
    session_id TEXT,
    channel TEXT,
    task_context TEXT
);
```

### Status Lifecycle

```
pending → paid       (incoming tx matched)
pending → expired    (TTL exceeded)
pending → cancelled  (agent or user cancels)
```

## Blockchain Scanning

### Solana

Uses two RPC calls:
1. `getSignaturesForAddress(wallet_address, {limit: 20})` — recent tx signatures
2. `getTransaction(signature)` — full tx details with pre/post token balances

Matching logic:
- Compare `postTokenBalances - preTokenBalances` for the agent's address
- Match by token mint + amount (within 0.1% tolerance for rounding)

### EVM (Base, Ethereum)

Uses `eth_getLogs` with the ERC-20 Transfer event:
- Topic 0: `0xddf252ad...` (Transfer event signature)
- Topic 2: agent wallet address (padded to 32 bytes)
- Lookback: 1000 blocks (~30 min on Base)

For native ETH: compare current balance against stored baseline (best-effort).

## Payment Links

### Solana Pay URI

```
solana:<address>?amount=<amount>&spl-token=<mint>&reference=<ref>&memo=<memo>
```

Compatible with Phantom, Solflare, and any Solana Pay-enabled wallet.

### EVM URI (EIP-681)

```
ethereum:<token_contract>@<chain_id>/transfer?address=<agent_address>&uint256=<amount_wei>
```

Compatible with MetaMask, Coinbase Wallet, and other EIP-681 wallets.

## Integration with Chat & Channels

The tool returns structured data that the agent formats for the active channel:

```
Telegram:
  💰 Payment Request
  Amount: 50 USDC
  Chain: Solana
  Address: HxK7...abc
  Memo: Website redesign — Phase 1
  [Copy Address] [Open Wallet]

Email:
  Subject: Payment Request — 50 USDC
  Body: Payment details + Solana Pay link + QR code instructions

CLI:
  Payment request created: req_a1b2c3d4
  Send 50 USDC to HxK7...abc on Solana
  Expires: 2026-03-16 15:00 UTC
```

## Configuration

No new config section needed — uses existing `payments` config:

```yaml
payments:
  enabled: true
  crypto:
    enabled: true
    default_chain: solana
    provider: local
```

The payment request tool reads the wallet address and chain from `PaymentsManager`.

## Implementation Files

| File | Purpose |
|------|---------|
| `core/payments/request_tracker.py` | Request lifecycle: create, check, expire, cancel |
| `tools/payments/request_tool.py` | `payment_request` tool (4 actions) |
| `core/payments/solana_wallet.py` | Add `get_incoming_transactions()` |
| `core/payments/local_wallet.py` | Add `get_incoming_transactions()` |
| `core/payments/manager.py` | Delegation methods for request tracker |
| `core/database.py` | Add `payment_requests` table to schema |
| `core/registry.py` | Register tool |
| `core/agent.py` | Add to `_inject_payment_deps` |
