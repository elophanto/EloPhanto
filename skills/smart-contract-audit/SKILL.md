---
name: smart-contract-audit
description: Use when reviewing a Solidity, Vyper, or Rust (Solana/Anchor) smart contract for paid audit work or pre-launch sanity check. Covers reentrancy, oracle manipulation, access control, signature replay, integer/precision, donation/share-inflation, and protocol-specific risks. Outputs a findings report with severity, impact, PoC sketch, and remediation. Includes outreach templates for direct-to-protocol paid engagements.
---

## Triggers

- audit smart contract
- audit this contract
- review solidity
- review anchor program
- security review of protocol
- find vulnerabilities in {repo}
- check for reentrancy
- check for oracle manipulation
- protocol audit
- pre-launch security review
- can you audit
- spot the bug

# Smart Contract Audit

## Overview

Smart contract bugs are expensive: the average DeFi exploit in the last cycle
moved $5M+, and the average protocol team is overworked and underspecialized
in security. There is real, recurring demand for **a fast, paid second
set of eyes** between an internal review and a $50–250k formal audit firm.

This skill exists to do that review competently and to never over-claim.

**Iron rules:**
1. **Never write "this contract is secure."** The most an audit produces is
   "I checked these things, found these issues, and didn't find more in the
   time allotted." Anything stronger is liability.
2. **Always include the time budget in the report.** A $1k 2-day review is
   not a Trail of Bits engagement. Say so explicitly.
3. **Reproducible findings only.** Every High/Medium finding must include
   either a PoC test (Foundry / Anchor / Hardhat) or a precise call sequence
   that demonstrates the issue. No vibes findings.
4. **Disclosure first, public second.** Findings go to the protocol via the
   agreed channel before any public mention. Period.

## Phase 1 — scoping & engagement (before reading any code)

Before opening the repo:

1. **Get the scope in writing.** Specific commit hash, list of files in
   scope, files explicitly out of scope. Not "the whole repo."
2. **Get the time budget in writing.** Hours or days. This caps the
   "Methodology — what was checked" section of the report.
3. **Get the disclosure channel in writing.** Email, Telegram, Slack,
   shared drive — pick one and stick to it. No "I'll just DM their X."
4. **Get the price in writing.** Fixed fee or hourly. If it's a contest
   (Code4rena/Sherlock/Cantina), the contest rules ARE the engagement —
   read them and follow them, no separate negotiation.

If any of these is missing → push back, do not start. Scope creep is the
single biggest threat to audit quality and to the relationship.

## Phase 2 — orientation (10–20% of budget)

- Read the protocol's own docs / whitepaper / architecture diagram first.
  An audit without business-context is a syntax check.
- Map the trust boundaries: who can call what, what's permissioned, what's
  permissionless, what's upgradeable, who controls upgrade keys.
- List the **economic invariants** the protocol must maintain (e.g. "totalShares
  always equals sum of user shares", "outputAmount ≥ minOutputAmount",
  "borrow ≤ collateral × LTV"). These become the test bench.
- Identify **external dependencies**: oracles (Chainlink, Pyth, Switchboard),
  AMMs queried for prices, cross-chain bridges, off-chain components.

## Phase 3 — vulnerability sweep (60–70% of budget)

Walk this checklist explicitly. Mark each as `checked / found / N/A` so the
report can show coverage.

### Reentrancy
- External calls before state updates (CEI violations)
- Cross-function reentrancy via shared storage
- Read-only reentrancy via view functions called by integrators
- ERC-777 / ERC-1155 / native token callback reentrancy

### Oracle manipulation
- Spot-price reads from AMMs (manipulable in single tx)
- Single-block TWAP reads
- Stale-price reads (no `updatedAt` check, no `answeredInRound` check)
- Oracle deviation handling (what happens at -100% or +1000%?)

### Access control
- Missing modifier on privileged functions
- `tx.origin` instead of `msg.sender`
- Initializer not protected (uninitialized proxy)
- Role rotation / two-step ownership transfer
- Signature replay (no nonce, no chain ID, no deadline)

### Integer & precision
- Unchecked arithmetic in loops or unbounded math
- Rounding direction (favoring user vs protocol — and is that intentional?)
- Decimals mismatch between assets (USDC=6, ETH=18)
- Division-before-multiplication causing precision loss
- Share-inflation / first-depositor attack on vaults (donation attack)

### Token-specific
- Non-standard ERC-20s: fee-on-transfer, rebasing, missing return value
- ERC-20 approval race condition
- Block-list tokens (USDC, USDT) breaking flows on receiver block
- Permit (EIP-2612) replay across chains

### Solana / Anchor-specific (if applicable)
- Account ownership not verified (`#[account(owner = ...)]` missing)
- PDA derivation collision
- Signer checks bypassable via custom CPIs
- Lamport / token account drain via close-account ordering
- Cross-program invocation (CPI) to untrusted programs

### Economic / MEV
- Sandwich-able trades (no slippage param, or default 0)
- Liquidation profitability vs gas (does it pay to liquidate at the threshold?)
- Donations breaking accounting invariants
- Funding rate / interest accrual gaming

### Upgradeability
- Storage layout collisions across versions
- Initializer reentrancy across upgrades
- Selfdestruct in implementation (post-Cancun: still a vector via delegatecall)

## Phase 4 — exploitation & PoC (10–15% of budget)

For every High or Medium finding, write a working PoC. Foundry test for
EVM, Anchor test for Solana. Without a PoC the finding gets downgraded
to Informational, no exceptions.

The PoC's job is to remove ambiguity for the protocol team. They should be
able to clone the repo, run `forge test`, and see the bug.

## Phase 5 — report (10% of budget)

### Severity rubric

- **Critical:** direct loss of user or protocol funds, no preconditions
  attacker can't satisfy. ≥$X at risk where X is meaningful relative to TVL.
- **High:** loss of funds with realistic preconditions, OR theft of
  governance/admin power, OR DoS of core function.
- **Medium:** loss of funds with significant preconditions / specific
  market conditions, OR loss of accrued fees, OR meaningful griefing.
- **Low:** code-quality / best-practice issues with no direct loss path.
- **Informational:** observations, gas optimizations, doc inconsistencies.

### Report template

```markdown
# Audit Report — {protocol name}

**Scope:** commit `{hash}`, files: {list}
**Time budget:** {N hours / days}
**Reviewer:** {name / handle}
**Engagement type:** {paid review / contest / pre-launch sanity check}
**Date range:** {start} – {end}

## Executive summary
{1 paragraph. # of findings by severity. Honest read on the protocol's
current security posture relative to the time budget. Explicit statement
that this is not a substitute for a formal audit firm if the protocol is
holding > $X.}

## Methodology — what was checked
{Bulleted list mapping to the Phase 3 checklist. Areas explicitly NOT
checked due to time/scope.}

## Findings

### [H-01] {short title}
- **Severity:** High
- **Location:** `src/Foo.sol#L123-L140`
- **Impact:** {1–2 sentences, concrete}
- **Description:** {what's wrong, with code snippet}
- **Proof of concept:** {Foundry test or call sequence}
- **Recommendation:** {specific fix, not "consider improving"}

[repeat per finding, ordered Critical → Informational]

## Disclaimer
This review was performed in {N hours/days} on commit {hash}. It is not a
guarantee of security. New code introduced after this commit is not
covered. The reviewer assumes no liability for losses arising from issues
not identified in this report.
```

## Outreach (direct-to-protocol, no platform)

### Cold outreach template

> Subject: Pre-launch security review for {protocol}
>
> Hi {name},
>
> Saw {protocol} is launching {feature/version}. I do paid second-pass
> security reviews on Solidity / Anchor protocols — the gap between
> internal review and a $100k Trail of Bits engagement.
>
> What it is: ~{N} day review, written report with PoCs for every High/Medium,
> fixed fee of ${price}. Past work: {links to prior reports / disclosures}.
>
> What it isn't: a full audit. If you're holding >$50M post-launch, you
> still want a firm. I'm useful for the 6-week pre-firm-audit window or
> as the sanity check after fixes ship.
>
> Worth a 15-min call this week?

### Pricing reference

- Pre-launch sanity check, single contract, ≤500 LOC: $1–3k, 1–2 days
- Full protocol review, ≤2000 LOC: $3–10k, 4–7 days
- Bigger or more complex: refer out. Don't pretend you can audit a
  full perp DEX in a week.

## Failure modes / when to refuse

- **"Audit my entire 50k-LOC monorepo for $2k."** Refuse — out of scope
  for any honest review at that price. Push for a smaller scope.
- **"We launch tomorrow, can you audit tonight?"** Refuse. No serious
  audit happens in <12 hours; saying yes is liability for both sides.
- **"We can't share the code, just sign this NDA."** Fine to NDA, but the
  contract must run for real users on a public chain — there is no
  meaningful private smart-contract audit. Push back.
- **"Will you sign a guarantee of security?"** Hard no. See iron rule #1.
- **Project that's a known rug / honeypot pattern.** Refuse. Reputation
  is the only currency this skill earns; don't spend it on scammers.

## Reputation tracking

Every completed audit (paid or unpaid) goes in `learned/audits/{date}-{protocol}.md`
with: scope, hours, findings count by severity, fee, did the protocol fix
the issues, did anything later get exploited that this audit missed.
Honest track record is the marketing.

## Verify

- A real RPC/SDK call was issued (mainnet, devnet, or local validator) and the response payload is captured in the transcript, not just paraphrased
- Every transaction was simulated (`simulateTransaction` or equivalent) before any signing/sending step; simulation logs are attached
- For any signed/sent transaction, the resulting signature is recorded and confirmed on chain (status returned by `getSignatureStatuses` or an explorer URL)
- Slippage, priority-fee, and compute-unit limits were set explicitly with concrete numeric values, not left to library defaults
- Account addresses, mints, and program IDs used in the run match the documented smart-contract-audit addresses for the targeted cluster (no mainnet/devnet mix-up)
- Failure path was exercised at least once (insufficient balance, stale oracle, expired blockhash, etc.) and the agent's error handling produced a human-readable message
