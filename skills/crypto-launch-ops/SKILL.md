---
name: crypto-launch-ops
description: Use when running launch-week operations for a paying crypto project — content schedule, X engagement, livestream presence, chat moderation, sentiment monitoring. Productizes the same stack the agent already runs for $ELO. Has hard refusal rules for low-quality / rug-prone projects because reputation is the asset being sold.
---

## Triggers

- crypto launch ops
- run launch week
- launch a token
- token launch services
- crypto kol service
- promote crypto project
- launch campaign
- pumpfun launch
- run the community
- handle launch comms
- launch playbook
- launch as a service

# Crypto Launch Ops

## Overview

Most crypto projects have a competent dev team and zero launch-week
operations. They ship, then watch in real time as nobody knows it
happened. There's a real, recurring market for **handing the launch week
to an operator** — content, X engagement, livestream, chat, sentiment.

The agent already runs this stack daily for $ELO. Selling it as a service
to other projects is changing the customer, not the capability.

**Iron rules — these are non-negotiable:**

1. **No price promises, ever.** "Going to $X", "early opportunity",
   "don't miss this" — never. Not in tweets, not in chats, not in DMs, not
   on livestream. Violating this once burns the reputation the service
   sells. Every line of copy is checked against this rule before posting.
2. **No rug-prone projects.** Hard refusal list: anonymous team with no
   verifiable history, no audit, mint authority not revoked, suspicious
   tokenomics (>20% to team with no vest), explicit honeypot patterns.
   Reputation is the only thing being sold here; one rug client kills the
   business and damages $ELO by association.
3. **Disclose the relationship.** Every paid post identifies the
   relationship — "working with @project on launch" or platform-equivalent.
   Not optional, not aesthetics — FTC + ESMA + most jurisdictions require
   it, and projects worth working with want it.
4. **Engagement, not manipulation.** No buying replies, no sock puppets,
   no fake communities. The volume is real or there's no service.

## Phase 0 — qualification (before quoting price)

Hard checklist. Any "no" → refuse the engagement.

- Doxxed team OR audit OR working product with users? (At least one.)
- Tokenomics published with team allocation, vest schedule, lock proofs?
- Mint authority revoked / multisig'd by launch?
- Smart contract reviewed (formal audit, public review, or community-vetted)?
- No promises of returns in any of their existing copy?
- They accept the iron rules above in writing?

If all green → proceed to scope. If any red → decline and explain which
ones; do not negotiate on the iron rules.

## Phase 1 — scope & pricing

Three engagement tiers — pick one, not custom unless the project knows
exactly what they want.

### Tier 1 — Launch day ($1–3k or stable + token)
- T-3 days: 3-tweet teaser thread, drafted with the team
- Launch day: 1 launch thread, 1 livestream session (≤2h), 6h active
  reply ops on the thread
- T+1: post-mortem post + 24h reply ops on top engagement

### Tier 2 — Launch week ($3–8k or stable + token)
- T-7 days: full content calendar (12 posts), pinned community FAQ doc
- Launch day: full Tier 1 deliverables
- T+1 to T+7: 2 posts/day, 1 livestream, daily community digest, 24/7
  chat moderation rotation

### Tier 3 — Full launch + first 30 days ($8–25k or stable + token)
- Tier 2 +
- Weekly community calls, weekly investor update, sentiment dashboard,
  CT (crypto twitter) influencer outreach (real ones, no paid sockpuppets)

**Pricing structure:** prefer 70% stable / 30% token vested 30 days. All
stable = expensive but cleaner. All token = align incentives but risk
holding bag. Never accept "100% token, no vest" — that's the project
buying their own launch with paper, not real budget.

## Phase 2 — content production

Content runs through one filter: **does this say something the audience
didn't already know, or does it just claim something is good?**

If it's only the latter → rewrite. Empty hype is what kills launches.

### Content templates

**Launch thread** (10–12 posts, posted as a single thread):

1. The problem this protocol solves (concrete user pain, not "DeFi is broken")
2. How the protocol solves it (mechanism, not adjectives)
3. What's actually live today vs roadmap (honest split)
4. Tokenomics one-liner — supply, allocation, vest
5. Audit / security posture — link to report, what was found, what was
   fixed
6. Three concrete things a user can do today
7. Team — who, what they built before, why this
8. Why now — the market or tech shift that makes this matter now
9. What could go wrong — yes, this post explicitly. Surfaces risk before
   critics do.
10. Where to follow / dApp / docs (actual call to action)

The "what could go wrong" post is the differentiator. Every other launch
thread skips it; including it earns trust.

**Daily post template (launch week)**:

- Today's update (concrete: stat, ship, partnership, milestone)
- Why it matters (one sentence)
- What's next (specific, dated)

No "WAGMI". No "early." No "100x." Period.

## Phase 3 — engagement ops

The agent already runs X engagement; for paying clients the changes are:

- **Disclosure tag in bio / pinned tweet** for the engagement period
- **Reply ops on every meaningful mention** of the project (not just
  "@project gm" — actual questions, FUD, integration asks)
- **Daily sentiment digest to the team:** what's working, what's getting
  pushback, what FUD is gaining traction. This is the highest-value
  deliverable they can't get from a freelance KOL.
- **Live chat (Telegram / Discord)** — mod role, FAQ shortcuts,
  escalation rules for the team

The agent's `pumpfun-livestream` and `twitter-marketing` skills do most of
the work. This skill orchestrates them under engagement-specific rules.

## Phase 4 — measurement & honest reporting

Ship a daily digest to the client. Every metric reported includes its
source so they can verify:

- Mentions: count + sentiment (positive / neutral / negative split)
- Reach: impressions on the launch thread, top replies
- Concrete actions: dApp visits, wallet connects, txns (if they share
  analytics)
- FUD log: what's circulating, what response posted, what unresolved

**Do not report vanity metrics in isolation.** "Got 50k impressions" is
meaningless if 0 users connected wallets.

## Phase 5 — wind-down & retention

End of engagement:

- Final report: deliverables shipped vs promised, metrics, learnings
- Honest assessment: what worked, what didn't, what they should keep doing
- Renewal proposal IF the engagement actually moved metrics. If not —
  recommend they don't renew. Bad renewals are how the service dies.

## Refusal patterns

Refuse, in writing, when:

- Project asks for "price-go-up" content. Iron rule 1 violation.
- Project asks for purchased replies / fake comments / botnet engagement.
  Iron rule 4 violation.
- Project's contract has unrenounced mint, no audit, anonymous team.
  Iron rule 2 / Phase 0 fail.
- Project pays only in their own unvested token. Phase 1 violation.
- Project requests undisclosed relationship. Iron rule 3 violation.
- Project's existing copy already promises returns. Phase 0 fail; they
  won't change for one launch.

A polite refusal template:

> Thanks for thinking of us. We can't take this engagement because [specific
> reason — point at iron rule]. We're happy to revisit if [specific change].
> No hard feelings.

## Reputation tracking

Every engagement goes in `learned/launches/{date}-{project}.md`:

- Scope, fee structure, what we promised, what we delivered
- Outcomes (ours and theirs — did the launch work?)
- Did the project rug, fade, or grow?
- What we'd reuse, what we'd refuse next time

The track record IS the marketing. One year in, the file ledger does the
sales work.

## Verify

- A real RPC/SDK call was issued (mainnet, devnet, or local validator) and the response payload is captured in the transcript, not just paraphrased
- Every transaction was simulated (`simulateTransaction` or equivalent) before any signing/sending step; simulation logs are attached
- For any signed/sent transaction, the resulting signature is recorded and confirmed on chain (status returned by `getSignatureStatuses` or an explorer URL)
- Slippage, priority-fee, and compute-unit limits were set explicitly with concrete numeric values, not left to library defaults
- Account addresses, mints, and program IDs used in the run match the documented crypto-launch-ops addresses for the targeted cluster (no mainnet/devnet mix-up)
- Failure path was exercised at least once (insufficient balance, stale oracle, expired blockhash, etc.) and the agent's error handling produced a human-readable message

## Anti-patterns to flag

- **Volume creep:** running 5 launches at once means none get the
  attention they paid for. Cap at 2 active engagements.
- **Reputation lending:** "just retweet this once for $X" is the path to
  becoming the platform that retweeted three rugs in a row. Refuse
  one-off boosts; only full engagements.
- **Team-friend discount:** doing a free launch for a friend's project
  with no qualification — same iron rules apply, or it doesn't happen.
