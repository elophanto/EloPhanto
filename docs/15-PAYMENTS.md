# EloPhanto — Agent Payments

> **Status: Idea Phase** — This document describes a planned capability, not yet implemented.

## Overview

A general-purpose agent needs the ability to **spend money**. Ordering products, buying hosting, paying invoices, purchasing crypto, subscribing to services, tipping on platforms — all of these require the agent to initiate financial transactions on the user's behalf.

EloPhanto's payment system supports two rails:

- **Traditional payments** — credit/debit cards, bank transfers, invoices via payment providers (Stripe, PayPal, etc.)
- **Crypto payments** — on-chain transfers, token swaps, multi-chain support via wallet providers

Both rails integrate with EloPhanto's existing permission system — every transaction goes through the approval flow, with configurable spending limits and thresholds.

### Design Principles

- **Never store raw private keys** — Use signing providers, hardware wallet bridges, or custodial APIs
- **Always require approval for real transactions** — Even in `full_auto` mode, payments above threshold require explicit user consent
- **Audit everything** — Every transaction logged with full context (who requested, why, approval chain, result)
- **Credentials in vault** — Payment API keys and tokens stored encrypted, retrieved at execution time, never in LLM context
- **Multi-channel approval** — Approve a $500 purchase from Telegram while the agent runs on your desktop

## Architecture

```
User: "Buy me a VPS on Hetzner, cheapest option"
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  Agent Core (plan → execute → reflect)                   │
│                                                          │
│  1. Research: browse Hetzner pricing (browser tools)     │
│  2. Select: CX22, €3.99/month                           │
│  3. Plan: payment_preview → payment_process              │
└────────────┬────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────┐
│  Payment Tool: payment_preview (SAFE)                    │
│  → Returns: €3.99, Stripe, card ending 4242              │
│  → No approval needed (read-only)                        │
└────────────┬────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────┐
│  Payment Tool: payment_process (CRITICAL)                │
│  → Executor checks permission level                      │
│  → Amount €3.99 < daily limit €50 ✓                      │
│  → But CRITICAL level → always requires approval         │
└────────────┬────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────┐
│  Approval Flow (via gateway)                             │
│                                                          │
│  CLI:      [Approve €3.99 to Hetzner via Stripe? y/n]   │
│  Telegram: [✅ Approve] [❌ Deny] inline keyboard         │
│  Discord:  ✅ / ❌ reaction buttons                       │
└────────────┬────────────────────────────────────────────┘
             │ User approves
             ▼
┌─────────────────────────────────────────────────────────┐
│  Execution                                               │
│                                                          │
│  1. Retrieve stripe_api_key from vault                   │
│  2. Call Stripe API / process card payment                │
│  3. Log to payment_audit table                           │
│  4. Return receipt to agent                              │
└─────────────────────────────────────────────────────────┘
```

## Traditional Payments

### Card Payments (Stripe)

The primary rail for online purchases, subscriptions, and services.

| Component | Detail |
|-----------|--------|
| **Provider** | Stripe API (or PayPal, Square, Adyen) |
| **Credentials** | `stripe_api_key` stored in vault |
| **Card storage** | Stripe tokenized cards — never raw card numbers in vault |
| **Virtual cards** | Stripe Issuing for per-merchant disposable cards |
| **3D Secure** | Handled via browser automation when required |

```
Payment Flow (Stripe):
    Agent → payment_process tool
        → Retrieve stripe_api_key from vault
        → Stripe API: create PaymentIntent
        → If 3DS required: browser automation for authentication
        → Confirm payment
        → Return: payment_intent_id, receipt_url, status
```

### Virtual Cards

For enhanced security, the agent can create disposable virtual cards per merchant:

- **One-time cards** — Single use, auto-expire after transaction
- **Merchant-locked** — Card only works at specific merchant
- **Spending cap** — Hard limit set at card creation time
- **Auto-cancel** — Card invalidated after task completion

This prevents a compromised merchant from making additional charges.

### Bank Transfers

For larger payments, invoices, or services that don't accept cards:

| Method | Use Case |
|--------|----------|
| **SEPA** | EU bank transfers |
| **ACH** | US bank transfers |
| **SWIFT** | International wire transfers |
| **Open Banking** | API-based bank payments (Plaid, TrueLayer) |

Bank transfers require higher approval thresholds due to irreversibility.

### Invoice Payments

The agent can detect, parse, and pay invoices:

1. **Receive** — Invoice arrives via email, Telegram, or file upload
2. **Parse** — Extract amount, recipient, due date, payment details (OCR or structured data)
3. **Validate** — Cross-reference with known vendors, check for anomalies
4. **Preview** — Show user the parsed invoice details
5. **Pay** — Process via appropriate rail (card, bank transfer, crypto)
6. **Archive** — Store receipt and link to original invoice

## Crypto Payments

### On-Chain Transfers

Direct blockchain transactions for crypto-native services.

| Component | Detail |
|-----------|--------|
| **Wallet** | Non-custodial via signing provider (WalletConnect, Fireblocks, or local signer) |
| **Chains** | Ethereum, Solana, Bitcoin, Polygon, Arbitrum, Base (extensible) |
| **Tokens** | Native tokens (ETH, SOL, BTC) + ERC-20/SPL tokens (USDC, USDT, DAI) |
| **Gas** | Auto-estimate, user-configurable priority (slow/normal/fast) |

### Wallet Management

The agent should **never** store raw private keys. Instead:

| Approach | Security | UX |
|----------|----------|----|
| **Signing provider API** (Fireblocks, Dfns) | Highest — keys in HSM | API call to sign |
| **WalletConnect** | High — keys on user's device | Approval on phone wallet |
| **Local encrypted keystore** | Medium — encrypted on disk | Password-protected, vault-stored |
| **Hardware wallet bridge** | Highest — keys never leave device | Physical confirmation required |

Recommended default: **Signing provider API** for automated flows, **WalletConnect** for high-value transactions requiring physical confirmation.

### Token Swaps

The agent can swap tokens when needed (e.g., convert ETH to USDC to pay for a service):

```
Agent needs to pay $50 in USDC but only has ETH
    │
    ▼
1. payment_preview: Check ETH/USDC rate on DEX aggregator (1inch, Jupiter)
2. crypto_swap: Swap ~0.02 ETH → 50 USDC (approval required)
3. crypto_transfer: Send 50 USDC to recipient (approval required)
```

### Multi-Chain Support

```
Supported Chains:

Chain          │ Native Token │ Stablecoins     │ DEX
───────────────┼──────────────┼─────────────────┼────────────
Ethereum       │ ETH          │ USDC, USDT, DAI │ Uniswap
Solana         │ SOL          │ USDC, USDT      │ Jupiter
Bitcoin        │ BTC          │ —               │ —
Polygon        │ POL          │ USDC, USDT      │ Uniswap
Arbitrum       │ ETH          │ USDC, USDT      │ Uniswap
Base           │ ETH          │ USDC            │ Uniswap
```

Chains are configured in `config.yaml`. The agent selects the optimal chain based on cost (gas fees) and recipient requirements.

## Payment Tools

### Tool Hierarchy

| Tool | Permission | Purpose |
|------|-----------|---------|
| `payment_balance` | SAFE | Check balances (card, bank, crypto wallets) |
| `payment_validate` | SAFE | Validate address format, IBAN, card token |
| `payment_preview` | SAFE | Show fees, exchange rates, total cost — no execution |
| `payment_process` | CRITICAL | Execute fiat payment (card, bank transfer) |
| `crypto_transfer` | CRITICAL | Execute on-chain transfer |
| `crypto_swap` | CRITICAL | Execute token swap on DEX |
| `invoice_parse` | MODERATE | Parse invoice from file/email |
| `invoice_pay` | CRITICAL | Parse + pay invoice (compound action) |
| `payment_history` | SAFE | Query transaction history and receipts |

All CRITICAL tools require explicit user approval regardless of permission mode.

### Tool Implementation Pattern

Tools follow the existing `BaseTool` pattern with vault injection:

```python
class PaymentProcessTool(BaseTool):
    name = "payment_process"
    description = "Process a payment via card or bank transfer"
    permission_level = PermissionLevel.CRITICAL

    def __init__(self):
        self._vault = None       # Injected by agent
        self._config = None      # Payment config injected

    async def execute(self, params: dict) -> ToolResult:
        provider = params["provider"]       # "stripe", "paypal"
        amount = params["amount"]
        currency = params["currency"]
        recipient = params["recipient"]
        method = params.get("method", "card")

        # Retrieve credentials from vault at execution time
        api_key = self._vault.get(f"{provider}_api_key")
        if not api_key:
            return ToolResult(
                success=False,
                error=f"No {provider} credentials in vault. "
                      f"Run: elophanto vault set {provider}_api_key YOUR_KEY"
            )

        # Process payment via provider API
        # ... provider-specific logic ...

        return ToolResult(success=True, data={
            "transaction_id": tx_id,
            "amount": amount,
            "currency": currency,
            "status": "completed",
            "receipt_url": receipt_url,
        })
```

## Approval & Safety

### Spending Limits

Configurable limits prevent runaway spending:

| Limit | Default | Scope |
|-------|---------|-------|
| **Per-transaction** | $100 | Single payment |
| **Daily** | $500 | Rolling 24 hours |
| **Monthly** | $5,000 | Calendar month |
| **Per-merchant** | $200 | Single recipient per day |

Transactions exceeding any limit are **always** held for approval, even in `full_auto` mode.

### Approval Tiers

```
Amount          │ Approval Required
────────────────┼────────────────────────────────
< $10           │ Standard approval (follows permission mode)
$10 – $100      │ Always requires approval
$100 – $1,000   │ Requires approval + confirmation ("Are you sure?")
> $1,000        │ Requires approval + cooldown period (5 min delay)
```

### Multi-Channel Approval

Payment approvals route through the gateway to whichever channel the user is active on:

```
Agent running on desktop, user on phone:

Agent: "I need to pay $49.99 for the Hetzner VPS"
    │
    ├──► CLI (no user present)
    │
    ├──► Telegram ✓ (user active)
    │    📱 "Approve payment?"
    │    [✅ Approve $49.99] [❌ Deny]
    │
    └──► Discord (offline)
```

The first channel to respond resolves the approval. Others are notified.

### Safety Checks

Before any payment executes:

1. **Balance check** — Sufficient funds/tokens available
2. **Recipient validation** — Valid address/IBAN/account format
3. **Duplicate detection** — Same amount + recipient within 1 hour → warn
4. **Rate limit** — Max 10 transactions per hour
5. **Blacklist check** — Known scam addresses/merchants blocked
6. **Gas estimation** — For crypto, ensure gas fees are reasonable (< 10% of amount)

## Credential Management

### Vault Storage

All payment credentials stored in the encrypted vault:

```
Vault Keys:
  stripe_api_key          → Stripe secret key
  stripe_card_token       → Tokenized card reference
  paypal_client_id        → PayPal API client ID
  paypal_client_secret    → PayPal API secret
  crypto_signer_api_key   → Signing provider API key
  crypto_wallet_address   → Public wallet address (not secret, but convenient)
  bank_account_iban       → IBAN for SEPA transfers
  plaid_access_token      → Open Banking access token
```

**Never stored in vault:**
- Raw credit card numbers (use tokenized references)
- Raw private keys (use signing providers)
- Bank login credentials (use Open Banking APIs)

### CLI Setup

```bash
# Store Stripe credentials
elophanto vault set stripe_api_key sk_live_...

# Store crypto signing provider
elophanto vault set crypto_signer_api_key dfns_...

# Store wallet address
elophanto vault set crypto_wallet_address 0x...

# List payment credentials
elophanto vault list | grep -E "stripe|paypal|crypto|bank"
```

## Audit Trail

### Transaction Log

Every payment attempt is logged, regardless of outcome:

```sql
CREATE TABLE payment_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    tool_name TEXT NOT NULL,           -- payment_process, crypto_transfer, etc.
    amount REAL NOT NULL,
    currency TEXT NOT NULL,            -- USD, EUR, ETH, USDC, BTC
    recipient TEXT NOT NULL,           -- address, merchant, IBAN
    payment_type TEXT NOT NULL,        -- card, bank_transfer, crypto, swap
    provider TEXT,                     -- stripe, paypal, uniswap, etc.
    chain TEXT,                        -- ethereum, solana, bitcoin (crypto only)
    status TEXT NOT NULL,              -- pending, approved, denied, executed, failed
    approval_id INTEGER,              -- FK to approval_queue
    session_id TEXT,                   -- Gateway session that initiated
    channel TEXT,                      -- cli, telegram, discord
    task_context TEXT,                 -- Why the payment was made
    transaction_ref TEXT,             -- tx_hash, payment_intent_id, etc.
    fee_amount REAL,                  -- Transaction fee / gas
    fee_currency TEXT,
    error TEXT,                       -- Error message if failed
    FOREIGN KEY(approval_id) REFERENCES approval_queue(id)
);
```

### Reporting

```bash
# View recent transactions
elophanto payments history

# View spending summary
elophanto payments summary --period month

# Export for accounting
elophanto payments export --format csv --period 2026-02
```

The agent can also query its own payment history via the `payment_history` tool to avoid duplicate payments and track spending.

## Configuration

```yaml
# config.yaml (future)
payments:
  enabled: false                      # Opt-in
  default_currency: USD
  default_provider: stripe            # For card payments

  limits:
    per_transaction: 100.0            # Max single payment
    daily: 500.0                      # Rolling 24h limit
    monthly: 5000.0                   # Calendar month limit
    per_merchant_daily: 200.0         # Per recipient per day

  approval:
    always_ask_above: 10.0            # Always require approval above this
    confirm_above: 100.0              # Double-confirm above this
    cooldown_above: 1000.0            # 5-min delay above this
    cooldown_seconds: 300

  crypto:
    enabled: false
    default_chain: ethereum
    signer_provider: ""               # fireblocks, dfns, walletconnect
    gas_priority: normal              # slow, normal, fast
    max_gas_percentage: 10            # Reject if gas > 10% of amount
    chains:
      - ethereum
      - solana
      - base

  providers:
    stripe:
      api_key_ref: stripe_api_key     # Vault key reference
    paypal:
      client_id_ref: paypal_client_id
      client_secret_ref: paypal_client_secret
```

```yaml
# permissions.yaml additions
tool_overrides:
  payment_process: ask                # Always require approval
  crypto_transfer: ask                # Always require approval
  crypto_swap: ask                    # Always require approval
  invoice_pay: ask                    # Always require approval
  payment_balance: auto               # Safe, auto-approve
  payment_preview: auto               # Safe, auto-approve
  payment_history: auto               # Safe, auto-approve
```

## Status

**Idea Phase** — This document captures the design direction for agent-initiated payments. Implementation has not started. Key prerequisites:

1. Define which payment provider to integrate first (Stripe recommended for fiat)
2. Define which signing provider to integrate first for crypto
3. Set up payment_audit table in database schema
4. Build payment tools following existing `BaseTool` pattern
5. Add payment configuration to `config.yaml` and `permissions.yaml`
6. End-to-end test with a test-mode Stripe key before any real payments
