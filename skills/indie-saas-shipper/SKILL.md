---
name: indie-saas-shipper
description: Use when shipping a small, paid SaaS micro-tool from idea → live → first dollar. Goes against "build it and they'll come" — every step has a kill criterion, a 14-day-to-first-dollar default budget, and forces distribution before code. Geography-neutral (Stripe/LemonSqueezy), no platform middlemen.
---

## Triggers

- ship a saas
- ship a micro saas
- launch indie product
- build a paid tool
- micro tool with stripe
- monetize this idea
- bootstrap a saas
- launch on product hunt
- launch on indie hackers
- $9/mo product
- can we sell this

# Indie SaaS Shipper

## Overview

Most indie SaaS attempts fail not because the code is bad but because **the
distribution doesn't exist** and **the buyer was never validated**. This skill
exists to invert the default order: validate willingness-to-pay before
writing code, ship a paid landing page before a product, and kill the idea
fast if the signal isn't there.

**Iron rules:**
1. **No code before someone says "I'd pay."** A tweet, a DM, or a Stripe
   pre-order — but a real human signal, not a poll.
2. **First dollar in 14 days or kill it.** Not first sign-up. First *paid*
   transaction. The clock starts when phase 2 begins.
3. **One product at a time.** Five half-shipped products earn $0; one
   shipped product earns something. Sequential, not parallel.
4. **No "free tier" until paid traction exists.** Free tier is a customer
   acquisition tactic, not a starting point.

## Phase 1 — idea triage (≤30 minutes)

Before anything else, score the idea on three axes (1–5):

- **Pain intensity:** is this a vitamin or a painkiller? Painkillers convert.
- **Buyer reachability:** can you reach 100 buyers from your existing
  network/audience in a week? If no → kill or come back when you can.
- **Build-to-revenue ratio:** can a working v1 ship in ≤7 days of agent
  build time? If no → scope it down or kill.

Score below 9/15: kill. Score 9–11: maybe, surface caveats. Score 12+:
proceed.

Bias toward **dev tools, AI-augmented workflow tools, and niche B2B utilities**
where buyers already pay for similar things and are easy to find. Avoid
consumer apps (CAC eats you), ad-supported tools (scale game), and
"productivity for everyone" framings (no buyer profile).

## Phase 2 — willingness-to-pay validation (3–5 days, no code)

Before opening an editor:

1. **Write the landing page first.** One paragraph: who it's for, what it
   does, what it costs. Three pricing tiers ($9 / $19 / $49 monthly is the
   reference shape — adjust to value).
2. **Set up Stripe payment links** (Stripe in 100+ countries; LemonSqueezy
   if VAT/MoR is a concern). No app, no auth, just a page and a "Buy" button
   that 404s after payment with a "thanks, you'll get access in 48h" page.
3. **Show it to 20 people in the buyer profile.** DMs, X replies, niche
   subreddits where soliciting is allowed. Track responses verbatim.
4. **Acceptance criterion:** ≥3 sign-ups OR ≥1 paid pre-order in 5 days.
   Below that, the idea isn't validated. Kill or pivot.

Refunds are fine. The signal is that someone clicked "buy."

## Phase 3 — minimum shippable product (5–7 days)

Stack defaults — pick these unless there's a specific reason not to:

- Frontend: Next.js + Tailwind + shadcn/ui (App Router)
- Backend: Next.js API routes (or FastAPI if Python-heavy)
- DB: Postgres on Neon / Supabase (free tier fine)
- Auth: Clerk or Supabase Auth
- Payments: **Stripe** (default) or LemonSqueezy (if VAT MoR matters)
- Hosting: Vercel (frontend) + Railway/Fly (workers)
- Analytics: Plausible (privacy-friendly, owners don't fight cookie banners)

Build only what the landing page promised. **No nice-to-haves until first
paying user.** Onboarding email, dashboards, settings pages — all later.

The agent's job here is to ship code; the user's job is to look at the
landing page output before it goes live and reject anything that
overpromises.

## Phase 4 — distribution (continuous, starting day 1)

Distribution is a parallel track to build, not a sequential phase. Start day 1.

- **Where to launch:** Product Hunt (Tuesday/Wednesday, 12:01 AM PST), Indie
  Hackers (Show IH section), Hacker News (Show HN — only if there's a real
  technical angle), the niche subreddits in scope, and X.
- **Don't launch on all of them on the same day.** Sequence: niche channels
  → IH → PH → HN. The flop on one platform poisons the next.
- **The agent owns content; the user owns voice.** The agent drafts the
  launch posts, threads, replies, screenshots. The user posts under their
  identity. Bot launches feel bot-launched.

## Phase 5 — kill or scale (day 14 review)

Hard gate at day 14 from phase 2 start:

- 0 paying customers → **kill.** Move to next idea. Park the code in a
  `graveyard/` folder; record what was learned in `learned/saas/{name}.md`.
- 1–2 paying customers → **investigate the moat.** Were they friends? Did
  they discover it organically? Most "first 2 customers were friends" outcomes
  don't compound. Continue only if non-network customers exist.
- 3+ paying customers from cold traffic → **scale.** Reinvest revenue into
  ads, more landing pages, a referral mechanic. This is now a real product.

## Templates

### Validation DM template

> Hey [name], saw your [post/tweet/repo] on [topic]. Building a small tool
> that [one-sentence problem statement] — landing page here: [link]. Would
> $[price]/mo solve a real pain for you, or am I way off?

### Refund-friendly preorder copy

> Pay $X today, full access in 48 hours. If we don't ship in 7 days you get
> a full refund, no questions. We don't keep the money until you have a
> working product in your hands.

### Kill-it-and-document template (`learned/saas/{name}.md`)

> ## Killed: {name} — {date}
> - Pitch: {one line}
> - Validation outcome: {n signups / m paid in y days}
> - Why it died: {real reason, not "no time"}
> - What I'd reuse: {tech, audience, distribution channel}
> - What I won't repeat: {assumption that broke}

## Failure modes / when to refuse

- "Let's build it and figure out monetization later" → refuse. No.
- "It's free for the first 1000 users" → refuse. That's not a SaaS, that's
  a hobby with hosting costs.
- "Build the entire admin dashboard / settings / SSO before launch" → refuse.
  Ship the one feature the landing page promised.
- "I want to launch on Friday" → push back. PH/IH launch days matter.

## Verify

- The deliverable for this phase exists as a concrete artifact (doc, ticket, board, repo) and its location is shared, not described
- Each commitment has an owner name, a due date, and a definition-of-done that someone other than the author could check
- Risks are listed with likelihood/impact and a named mitigation, not as a generic 'risks: TBD' bullet
- Dependencies on other teams/vendors/agents are explicit; an ack from each dependency is recorded or marked 'pending'
- Success criteria for the next phase are numeric or otherwise objectively testable
- A rollback / kill-switch / 'we will stop if X' criterion is written down before work starts

## Anti-patterns to flag

- **The polish trap:** rewriting the landing page for the 4th time instead
  of DMing buyer #21.
- **The infinite scope creep:** "v1 also needs Slack integration." It does
  not. v1 needs one paying customer.
- **The free-tier escape hatch:** when validation fails, the temptation is
  "let's just make it free and grow." That's a different business; restart
  phase 1 if you go there.
