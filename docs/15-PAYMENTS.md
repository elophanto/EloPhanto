# EloPhanto — Agent Payments

> **Status: Phase 1 Done** — Core crypto wallet with dual provider support: local self-custody wallet (default, zero config) + Coinbase AgentKit (optional, managed custody, gasless, swaps). 7 tools, spending limits, audit trail. Phase 2 (fiat/Stripe) and Phase 3 (invoicing) planned.

## Overview

A general-purpose agent needs the ability to **spend money**. Ordering products, buying hosting, paying invoices, purchasing crypto, subscribing to services, tipping on platforms — all of these require the agent to initiate financial transactions on the user's behalf.

EloPhanto's payment system supports two rails:

- **Traditional payments** — credit/debit cards, bank transfers, invoices via payment providers (Stripe, PayPal, etc.)
- **Crypto payments** — on-chain transfers, token swaps, multi-chain support via wallet providers

Both rails integrate with EloPhanto's existing permission system — every transaction goes through the approval flow, with configurable spending limits and thresholds.

### Design Principles

- **Agent gets its own wallet** — Like a prepaid card: user funds it, agent spends within limits. User's main wallet is never exposed.
- **Dual wallet providers** — Local self-custody (default, zero config) or Coinbase CDP (optional, managed custody with gasless + swaps)
- **Private keys secured** — Local wallet stores encrypted key in vault (Fernet + PBKDF2). CDP manages keys server-side.
- **Always require approval for real transactions** — Even in `full_auto` mode, payments above threshold require explicit user consent
- **Audit everything** — Every transaction logged with full context (who requested, why, approval chain, result)
- **Credentials in vault** — Payment API keys and tokens stored encrypted, retrieved at execution time, never in LLM context
- **Multi-channel approval** — Approve a $500 purchase from Telegram while the agent runs on your desktop

## Agent Wallet Setup

The agent creates its own wallet on first use — the user funds it like a prepaid card.

### First-Time Setup (Local Wallet — Default)

```
# In config.yaml:
payments:
  enabled: true
  crypto:
    enabled: true
    provider: local       # zero config, wallet auto-creates

# Start the agent — wallet generates automatically
./start.sh chat
  → "Created local wallet: 0xABC...def on base"
  → "Send USDC to this address to fund your agent."
```

No API keys needed. The private key is encrypted in the vault.

### First-Time Setup (Coinbase CDP — Optional)

```
# In config.yaml:
payments:
  enabled: true
  crypto:
    enabled: true
    provider: agentkit    # managed custody, gasless, swaps

# Store CDP credentials
elophanto vault set cdp_api_key_name YOUR_KEY_NAME
elophanto vault set cdp_api_key_private YOUR_PRIVATE_KEY

# Install AgentKit
./setup.sh   # auto-detects provider: agentkit and installs
```

The wallet address is persisted in the vault and visible to the agent.

### Funding & Spending

```
User sends 100 USDC to 0xABC...def on Base
    │
    ▼
Agent can now spend up to configured limits:
    - Per-transaction: $100
    - Daily: $500
    - Monthly: $5,000
    │
    ▼
User: "What's your balance?"
Agent: "72.01 USDC on Base (0xABC...def)"
    │
    ▼
User: "Pay 0x123... 50 USDC"
Agent: "Send 50 USDC to 0x123...? [Approve / Deny]"
    → User approves via Telegram
    → Gasless transfer on Base
    → Agent: "Sent. TX: 0x789... Balance: 22.01 USDC"
```

### Low Balance Alerts

When the wallet drops below a configurable threshold, the agent notifies the user:

```
Agent → Telegram: "Low balance: 5.23 USDC remaining on Base.
        Fund 0xABC...def to continue payments."
```

### Why Own Wallet (Not User's Wallet)

| | Agent's own wallet | User connects wallet |
|---|---|---|
| **Risk** | Limited to funded amount | Full wallet balance exposed |
| **UX** | Fund once, agent spends autonomously | Approve every transaction on phone |
| **Safety** | Worst case: lose what's in the wallet | Worst case: lose everything |
| **Autonomy** | Agent can spend within limits 24/7 | Requires user to be online for WalletConnect |

The agent's wallet is a spending account, not a savings account.

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
| **Wallet** | Local self-custody (default) or Coinbase AgentKit (optional) |
| **Chains** | Base (default), Ethereum (extensible) |
| **Tokens** | Native tokens (ETH) + ERC-20 tokens (USDC, USDT, DAI) |
| **Gas** | Local wallet: user pays gas (< $0.01 on Base). CDP: gasless via paymaster |
| **Protocols** | x402 for machine-to-machine stablecoin payments (CDP only) |

### Wallet Providers

EloPhanto supports two wallet providers, selectable via `config.yaml`:

| | Local Wallet (default) | Coinbase CDP (optional) |
|---|---|---|
| **Provider** | `local` | `agentkit` |
| **Custody** | Self-custody — private key encrypted in vault, never leaves your machine | Managed — Coinbase holds keys via Developer Platform |
| **Setup** | Zero config — wallet auto-creates on first use | Requires free CDP API key from portal.cdp.coinbase.com |
| **Dependencies** | `eth-account` (installed by setup.sh) | `coinbase-agentkit` (install via setup.sh when configured) |
| **Transfers** | ETH + ERC-20 (USDC, etc.) | ETH + ERC-20 (USDC, etc.) |
| **DEX swaps** | Not supported | Supported (ETH↔USDC etc.) |
| **Gas fees** | User pays from ETH balance (< $0.01 on Base) | Gasless on Base via paymaster |
| **Chains** | Base (default), Base Sepolia, Ethereum | All EVM chains + Solana |
| **Best for** | Local-first users, simple transfers, full self-custody | Users who need swaps, gasless transactions, or multi-chain |

Recommended default: **Local wallet** on **Base** — zero config, self-custody, minimal gas fees. Switch to Coinbase CDP when you need swaps or gasless transactions.

### Token Swaps (Coinbase CDP only)

The agent can swap tokens when using the Coinbase CDP provider (e.g., convert ETH to USDC to pay for a service). Not available with the local wallet provider.

```
Agent needs to pay $50 in USDC but only has ETH
    │
    ▼
1. payment_preview: Check ETH/USDC rate via AgentKit swap action
2. crypto_swap: Swap ~0.02 ETH → 50 USDC (approval required)
3. crypto_transfer: Send 50 USDC to recipient (approval required)
```

### Multi-Chain Support

```
Supported Chains:

Chain          │ Native Token │ Stablecoins     │ DEX              │ Gasless
───────────────┼──────────────┼─────────────────┼──────────────────┼────────
Base (default) │ ETH          │ USDC            │ Uniswap (CDP)    │ Yes (CDP paymaster)
Base Sepolia   │ ETH          │ USDC (test)     │ —                │ No
Ethereum       │ ETH          │ USDC, USDT, DAI │ Uniswap (CDP)    │ No
```

Chains are configured in `config.yaml`. The agent selects the optimal chain based on cost (gas fees) and recipient requirements.

## Payment Tools

### Tool Hierarchy

| Tool | Permission | Purpose |
|------|-----------|---------|
| `wallet_status` | SAFE | Show agent wallet address, balances, chain |
| `payment_balance` | SAFE | Check balances (card, bank, crypto wallets) |
| `payment_validate` | SAFE | Validate address format, IBAN, card token |
| `payment_preview` | SAFE | Show fees, exchange rates, total cost — no execution |
| `payment_process` | CRITICAL | Execute fiat payment (card, bank transfer) |
| `crypto_transfer` | CRITICAL | Execute on-chain transfer from agent wallet |
| `crypto_swap` | CRITICAL | Execute token swap on DEX from agent wallet |
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
  cdp_api_key_name        → Coinbase Developer Platform API key name
  cdp_api_key_private     → Coinbase Developer Platform API private key
  crypto_wallet_id        → AgentKit wallet ID (created on first use)
  bank_account_iban       → IBAN for SEPA transfers
  plaid_access_token      → Open Banking access token
```

**Never stored in vault:**
- Raw credit card numbers (use tokenized references)
- Bank login credentials (use Open Banking APIs)

Note: The local wallet provider stores the private key encrypted in the vault (`local_wallet_private_key`). This is secure — the vault uses Fernet encryption with PBKDF2 key derivation.

### CLI Setup

```bash
# Store Stripe credentials
elophanto vault set stripe_api_key sk_live_...

# Store Coinbase Developer Platform credentials
elophanto vault set cdp_api_key_name organizations/...
elophanto vault set cdp_api_key_private "-----BEGIN EC PRIVATE KEY-----..."

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
  default_provider: stripe            # For card/fiat payments

  wallet:
    auto_create: true                 # Create agent wallet on first enable
    low_balance_alert: 10.0           # Notify user when balance drops below this (USD)
    default_token: USDC               # Default token for the agent wallet

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
    default_chain: base               # Base L2 (low gas fees)
    provider: local                   # "local" (self-custody) or "agentkit" (Coinbase CDP)
    rpc_url: ""                       # Override RPC endpoint (empty = chain default)
    cdp_api_key_name_ref: cdp_api_key_name       # Vault key reference (agentkit only)
    cdp_api_key_private_ref: cdp_api_key_private  # Vault key reference (agentkit only)
    gas_priority: normal              # slow, normal, fast
    max_gas_percentage: 10            # Reject if gas > 10% of amount
    chains:
      - base
      - ethereum

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

**Phase 1 Done** — Crypto payments with dual wallet provider support. 7 tools, spending limits, audit trail, chat-based setup.

### Implemented

| Rail | Provider | Status |
|------|----------|--------|
| **Crypto (local)** | Local self-custody via `eth-account` | Done — default provider, zero config |
| **Crypto (CDP)** | Coinbase AgentKit | Done — optional, requires CDP API key |
| **Fiat** | Stripe | Planned (Phase 2) |
| **Invoicing** | Parse + pay | Planned (Phase 3) |

### Quick Start

**Local wallet (default):** Enable `payments.enabled: true` and `payments.crypto.enabled: true` in config.yaml (or ask the agent to set it up from chat). Wallet auto-creates on first run.

**Coinbase CDP:** Set `payments.crypto.provider: agentkit`, store CDP credentials in vault, run `./setup.sh` to install AgentKit dependencies.
