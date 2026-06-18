# EloPhanto — ABE Finance Rail (Fiat / Stripe)

> **Status: Built, test-mode, mock-validated (2026-06-18).** The fiat rail
> (Stripe) for ABE businesses: get paid, record revenue, see runway, provision
> spend-controlled cards — all **test-mode by default, no real money, no KYC**
> to develop. Live is a deliberate, KYC-gated, per-capability flip. The Stripe
> calls are covered by unit tests against **mocks**; end-to-end validation
> against a real Stripe **test** account is the recommended next step before
> going live.
>
> ABE (Autonomous Business Entity) is a concept originated by Petr Royce in
> 2023. See [76-ABE-FRAMEWORK.md](76-ABE-FRAMEWORK.md) and
> [78-ABE-OPERATOR-GUIDE.md](78-ABE-OPERATOR-GUIDE.md). Crypto rail:
> [15-PAYMENTS.md](15-PAYMENTS.md).

## Why a fiat rail

Crypto (Base/Solana) was EloPhanto's only money rail. Most online businesses
get paid in fiat. The fiat rail adds Stripe so an ABE can receive card/bank
payments, hold a balance, and provision outbound spend — the economic spine an
autonomous business needs to reach its **first unattended dollar** and then run
net-positive.

## Core model: one rail per business (fiat XOR crypto)

A business chooses **one** payment rail at onboard — `fiat` (Stripe) or
`crypto` (wallet). Stored as `companies.payment_rail`. One rail keeps
cash-on-hand and runway a single honest number; a secondary rail is a future
extension, not v1.

## KYC / financial-readiness state machine

An agent cannot be the accountable legal person, so every business that touches
real money has a real legal entity + verified operator behind it. This is
tracked as `companies.entity_state`, **orthogonal to the trust ladder** (which
gates live *actions*; this gates live *money*):

```
none → forming → kyc_pending → verified → restricted
```

- Real money movement (live fiat) requires `entity_state == 'verified'`.
- `restricted` = the processor froze the account (money blocked; P0).
- Advanced via the `company_set_entity_state` tool (MODERATE) — the operator
  asserts the entity + KYC are real; the agent does not self-certify.

The entity can be **brought-your-own** (existing company + Stripe account) or
**formed via Stripe Atlas** (~$500, Delaware C-corp/LLC + EIN + bank + Stripe).
Atlas is not an API — it's an operator-completed application; the agent assists,
the operator is the director.

## Test vs live mode (the debug switch)

`payments.fiat.mode: test | live` (default **test**).

| | TEST (default) | LIVE |
|---|---|---|
| Stripe keys | `sk_test_` | `sk_live_` |
| Money | none — simulated | real |
| KYC | not required | required (`verified`) |
| Books | recorded `mode=test`, **excluded from real revenue** | counts |

Going live needs **both**: `entity_state=verified` **and** an explicit operator
flip to `mode: live` (per-capability). The provider refuses a live key under
test mode and vice-versa — a key/mode mismatch is rejected, never silently used.

## Capabilities

### Receive (built, autonomous)
- **`fiat_payment_link`** (MODERATE) — create a shareable Stripe payment link to
  get paid. Idempotent. Live requires `entity_state=verified`.
- **`fiat_reconcile`** (SAFE) — pull recent succeeded payments and record them in
  the ledger as `usd`/`in`, deduped by Stripe id (`note=stripe:<id>`). Also
  records refunds as compensating `usd`/`out` rows so net never overstates
  realized revenue (best-effort; flags `refunds_checked=false` on a refund-list
  failure). **Auto-scheduled every 30 min** per fiat company via the
  direct-tool cron (no LLM, ~$0/fire), passing `company_id` explicitly so it
  records under the right business.

The receive loop is hands-off: create link → customer pays → auto-reconcile
records it (refund-aware, company-correct, mode-correct) → metabolism updates.

### Hold + runway (organ 1, metabolism)
- `cash_on_hand()` reads the Stripe balance (available + pending — *not* the bank
  balance; Stripe settles on a lag).
- `runway_weeks = cash_on_hand ÷ trailing-4wk weekly burn`. Surfaced on the
  `[COMPANY]` state line in live+verified mode; test mode shows
  `rail=fiat[mode=TEST]` only (no fake runway).
- Metabolism net = revenue − spend, where spend already includes the agent's
  **own cognition cost** (LLM spend is mirrored into the ledger). Test-mode
  receipts are excluded from real revenue (`mode='live'` filter).

### Spend (built — provisioning only)
- **`fiat_issue_card`** (CRITICAL) — provision a bounded virtual card via Stripe
  Issuing under an operator-configured cardholder (`payments.fiat.cardholder_id`
  — tied to the legal entity; the agent does not mint cardholders). Bounded by
  an operator-set `spend_limit` + `interval` (organ-6 envelope). Returns only
  **id / last4 / expiry**.

**PCI boundary (hard rule):** the raw card number/CVC **never enter the
process** — the provider never asks Stripe to `expand` them, and the tool strips
any card-data keys before returning. So a PAN cannot reach an LLM prompt or a
log. *Using* a card to pay a vendor (which needs the PAN) is **deliberately
deferred** until there's an out-of-band handler proven to keep the PAN out of
LLM/logs. The agent provisions governed cards; it does not handle raw numbers.

## Finance invariants (how the rail stays safe)

1. No money moves without a ledger row + an audit trail.
2. Every money-moving Stripe call carries an idempotency key — retries can't
   double-charge / double-issue.
3. Raw card data + secret keys never enter an LLM prompt, a log, or plaintext
   storage. Receive uses hosted Stripe Checkout/Payment Links (SAQ-A).
4. The agent operates **within** envelopes (spend limits, mode, entity gate); it
   cannot widen them — raising a limit or going live is an operator act.
5. Test-mode money never counts as real cash/revenue/runway.

## Config

```yaml
payments:
  fiat:
    enabled: false          # off by default
    provider: stripe
    mode: test              # test (no real money, no KYC) | live
    base_currency: USD
    secret_key_ref: stripe_secret_key   # key lives in the vault, never here
    publishable_key_ref: stripe_publishable_key
    webhook_secret_ref: stripe_webhook_secret
    issuing_enabled: false  # opt-in even within fiat (Spend)
    cardholder_id: ""       # ich_... (operator-provisioned, for Issuing)
```

`config migrate` (run by `./update.sh`) surfaces this section for existing
installs. The deps (`stripe`, `stripe-agent-toolkit`) are the `payments-fiat`
extra, auto-installed by `setup.sh`/`update.sh` when `provider: stripe` is set.

## Easy setup

```
./setup.sh → wizard: "Enable Stripe (test mode)? y" → paste a free sk_test_ key
           → elophanto vault set stripe_secret_key sk_test_...
./start.sh → doctor shows: payments: fiat [mode=TEST] — no real money
Operator flow: company_onboard(payment_rail=fiat) → fiat_payment_link (sandbox)
           → finish KYC → company_set_entity_state(verified) → mode: live → real money
```

`doctor` surfaces the mode and refuses ambiguity; in live mode the money tools
enforce the `verified` gate.

## Deferred (documented, not silently dropped)

- **Card usage** (retrieve PAN to pay a vendor) — the PCI-heavy half; needs a
  proven out-of-band handler.
- **Spend → ledger recording** — issued-card charges mirrored as `usd`/`out`
  (a reconcile extension; pairs with usage).
- **Real-time authorization webhook** — v1 relies on static `spending_controls`,
  avoiding a public-endpoint requirement.
- **Webhooks for receive** — v1 polls via `fiat_reconcile` (no public endpoint);
  webhook + cursor are a scale follow-up.
- **End-to-end test-mode validation** against a real Stripe test account — the
  Stripe calls are mock-tested; validating them live (free, no KYC) is the
  recommended next step.

## Code map

| Concern | Location |
|---|---|
| Provider | `core/payments/fiat_stripe.py` (`StripeFiatProvider`) |
| Receive tool | `tools/payments/fiat_link_tool.py` |
| Reconcile (+ refunds) | `tools/payments/fiat_reconcile_tool.py` |
| Spend tool | `tools/payments/fiat_card_tool.py` |
| Rail + KYC state | `core/company.py` (`payment_rail`, `entity_state`) |
| KYC walkthrough tool | `tools/companies/entity_state_tool.py` |
| Onboarding rail choice | `tools/companies/onboard_tool.py` |
| Metabolism / runway | `core/ledger.py` (`Metabolism`, `runway_weeks`, `mode`) |
| Auto-reconcile seed | `core/agent.py` (`_seed_fiat_reconcile_schedules`) |
| Config | `core/config.py` (`PaymentFiatConfig`) |
