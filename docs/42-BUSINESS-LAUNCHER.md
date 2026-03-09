# Business Launcher

## Overview

EloPhanto can spin up a revenue-generating business end-to-end: validate an idea,
build an MVP, deploy it to the internet, launch on platforms, and grow
autonomously. The `business-launcher` skill teaches the agent a structured
7-phase pipeline that coordinates its existing capabilities (browser automation,
deployment, email, payments, swarm, organization, autonomous mind) into a
coherent business creation workflow.

This is not a toy demo. The agent uses real tools to create real products on real
infrastructure, posts on real platforms, and tracks real revenue. The human
owner handles the parts that legally require a person (business registration,
Stripe KYC, domain purchase, tax compliance).

## The Model: AI as Cofounder

The agent does ~80% of the execution work:
- Market research and competitor analysis
- Name/domain selection and validation
- Full-stack MVP development (via swarm or direct coding)
- Deployment to Vercel/Railway/Supabase
- Content creation and platform posting
- Email outreach
- Ongoing marketing via specialist agents
- Revenue monitoring

The human handles ~20% — the identity and legal gates:
- Business registration (LLC/sole prop)
- Payment processor setup (Stripe KYC)
- Domain purchase and DNS
- Tax compliance

For crypto-native businesses, the agent's own wallet can handle payments
directly, reducing human involvement further.

## Business Type Classification

Before anything else, the agent classifies the business along two dimensions:

**Business type:**

| Type | Examples |
|---|---|
| Tech / SaaS | Dev tool, dashboard, API, automation |
| Local service | Horse riding, tutoring, cleaning, gym, salon |
| Professional service | Consulting, design agency, coaching |
| Ecommerce | Physical products, handmade goods, merch |
| Digital product | Course, template, ebook, preset pack |
| Content / Media | Blog, newsletter, podcast companion |

**Customer type:**

| Type | Implications |
|---|---|
| B2C | Emotion-driven, visual, social proof, lower price, higher volume |
| B2B | ROI-driven, case studies, LinkedIn/email, higher price, longer cycle |

This classification drives every downstream decision: what to build,
where to launch, how to grow, and what content to create.

## The 8 Phases

```
┌──────────────────────────────────────────────────────────────┐
│  Phase 0: CLASSIFY                                           │
│  Business type (tech/local/service/ecommerce/digital/content)│
│  Customer type (B2B / B2C)                                   │
├──────────────────────────────────────────────────────────────┤
│  Phase 1: VALIDATE                                           │
│  Market research, competitors, domain check, opportunity score│
│  Gate: Owner approves idea (score ≥ 9/15)                    │
├──────────────────────────────────────────────────────────────┤
│  Phase 2: PLAN                                               │
│  Revenue model, MVP scope, tech stack, pricing               │
│  Gate: Owner approves plan                                   │
├──────────────────────────────────────────────────────────────┤
│  Phase 3: BUILD                                              │
│  Type-specific MVP (booking site, SaaS app, store, etc.)     │
│  Ship the first working version, not the perfect one         │
├──────────────────────────────────────────────────────────────┤
│  Phase 4: DEPLOY                                             │
│  deploy_website + create_database, verify live URL           │
│  Gate: Owner sets up Stripe, buys domain, reviews site       │
├──────────────────────────────────────────────────────────────┤
│  Phase 5: LAUNCH                                             │
│  Channels matched to business type (see below)               │
│  Platform-specific content, email outreach                   │
├──────────────────────────────────────────────────────────────┤
│  Phase 6: GROW                                               │
│  Type-specific growth (SEO / reviews / LinkedIn / Instagram) │
│  Specialist agents for marketing + research                  │
├──────────────────────────────────────────────────────────────┤
│  Phase 7: OPERATE                                            │
│  Autonomous mind maintenance, recurring goals, email monitor │
└──────────────────────────────────────────────────────────────┘
```

## Launch Channels by Business Type

The most important design decision: where to launch depends entirely on where
the customers are.

| Business Type | Primary Channels | Never Use |
|---|---|---|
| Tech / SaaS | Product Hunt, HN, dev.to, X, Indie Hackers | Nextdoor, local groups |
| Local service | Google Business, Yelp, Facebook local groups, Nextdoor, Instagram | Product Hunt, HN, dev.to |
| Professional / B2B | LinkedIn, industry forums, email outreach, Medium | TikTok, Nextdoor |
| Ecommerce | Instagram, Pinterest, TikTok, Etsy, Facebook Marketplace | HN, dev.to |
| Digital product | X, Gumroad Discover, YouTube, Reddit, Product Hunt | Nextdoor, Yelp |
| Content site | SEO first, then social amplification | Product Hunt |

## Revenue Models

| Model | Best For | Price Range | Payment |
|---|---|---|---|
| **Subscription** | Tech / SaaS | $9-99/mo | Stripe |
| **Per-call API** | Developer tools | Free tier + $19+/mo | Stripe / crypto |
| **Booking/retainer** | Local + professional service | Market rate | Stripe / Square |
| **Per-item sales** | Ecommerce | Varies | Stripe / Shopify |
| **One-time purchase** | Digital product | $9-199 | Gumroad / Stripe |
| **Ads + affiliate** | Content site | N/A | Ad networks |

## Tool Coordination

Each phase maps to specific EloPhanto tools:

**Validate:** `web_search`, `browser_navigate`, `browser_extract` (competitor research),
`shell_execute` (whois domain check), `knowledge_write` (persist findings)

**Build:** `swarm_spawn` (parallel coding agents), `file_write`, `shell_execute`,
`create_database` (Supabase), `skill_read` (load tech-specific skills)

**Deploy:** `deploy_website` (Vercel/Railway auto-detect), `create_database`,
`browser_navigate` (verify live URL)

**Launch:** `browser_navigate`, `browser_click`, `browser_type_text`,
`browser_paste_html` (post on platforms), `email_send` (outreach),
`knowledge_search` (avoid duplicate posts)

**Grow:** `organization_spawn` (marketing + research specialists),
`organization_delegate`, `schedule_task` (recurring content),
`browser_navigate` (analytics)

**Operate:** `goal_create` (long-term maintenance goal), `email_monitor`
(customer inquiries), `set_next_wakeup` (autonomous mind scheduling)

## Owner Gates

The pipeline has mandatory approval checkpoints where the agent stops and
presents findings to the owner. This prevents autonomous spending, premature
launches, and building the wrong thing.

| Gate | After Phase | What's Presented |
|---|---|---|
| Idea approval | Validate | Competitors, market gap, score, proposed name |
| Plan approval | Plan | Revenue model, feature list, tech stack, pricing |
| Launch approval | Deploy | Live URL, Stripe/domain setup needed |

The agent NEVER proceeds past a gate without explicit owner approval.

## How It Works Across Sessions

A business takes days or weeks to build — it doesn't fit in a single conversation.
The agent uses the **goal system** and **knowledge persistence** to maintain
continuity:

1. **Classify + Validate** run immediately in the first conversation.
2. After owner approval, the agent calls `goal_create` with one checkpoint per
   remaining phase (Plan, Build, Deploy, Launch, Grow, Operate).
3. After each phase completes, the agent saves state to knowledge via
   `knowledge_write` at `knowledge/projects/[business-name]/phase-N-[name].md`.
4. The autonomous mind picks up the goal in future sessions and continues
   from the last completed checkpoint.
5. At owner gates (after Validate, Plan, Deploy), the agent stops and waits
   for explicit approval before proceeding.

This means the owner can start a business in one conversation, close the laptop,
and come back later — the agent remembers where it left off and what's next.

## Integration with Other Systems

**Organization System:** Phase 6 spawns persistent specialist agents for
marketing and research. These specialists have their own knowledge vaults and
autonomous minds — they continue creating content and monitoring competitors
even when the owner isn't engaged.

**Agent Swarm:** Phase 3 can spawn Claude Code, Codex, or Gemini CLI agents
for parallel development. Frontend and backend can be built simultaneously.

**Autonomous Mind:** Phase 7 integrates the business into the agent's
background thinking loop. The mind checks analytics, posts scheduled content
via specialists, monitors email for customer inquiries, and reports revenue
updates to the owner.

**Goals System:** A recurring goal tracks the business lifecycle:
weekly content, monthly analytics, quarterly pricing review.

**Knowledge System:** All research, competitor data, pricing analysis, launch
URLs, and customer feedback are persisted to the knowledge base. This prevents
duplicate work and enables informed decisions in later phases.

## Payment Handling

Before asking the owner, the agent checks what's already available:

1. `knowledge_search` for existing payment setup (Stripe, bank account, PayPal)
2. `vault_lookup` for stored API keys (`stripe_key`, `paypal_key`)
3. `wallet_status` for the agent's own crypto wallet

If credentials already exist from a previous business or setup, the agent
reuses them. If nothing is configured:

- **Fiat:** Ask the owner to set up Stripe/PayPal and provide API keys.
  Revenue goes to the owner's bank account.
- **Crypto:** Use the agent's own wallet (`wallet_status`, `crypto_transfer`)
  to accept payments on-chain.

## Limitations

1. **Legal identity** — business registration, EIN, and contracts require a
   human. The agent cannot form an LLC or sign Terms of Service.
2. **Payment processor KYC** — if no Stripe/PayPal is already configured,
   the owner must set one up (requires human identity verification).
4. **Domain purchase** — requires a payment method and DNS configuration
   that the agent cannot perform without browser access to a registrar
   (possible but requires stored payment credentials).
5. **Quality ceiling** — the agent ships fast but rough. Human review is
   critical for customer-facing copy, pricing decisions, and brand quality.
5. **Customer judgment** — tier-1 support is automatable, but nuanced
   refund decisions, relationship management, and edge cases need a human.

## Example: Tech Business (B2B SaaS)

```
User: I want to spin up a micro-SaaS for developers

Agent: Phase 0: CLASSIFY → Tech / SaaS, B2B
       Starting Phase 1: VALIDATE.

  → web_search "developer tools micro-saas 2026 gaps"
  → browser_navigate https://www.producthunt.com/topics/developer-tools
  → shell_execute "whois devflowkit.com" → Available!

  Validation Report:
  ┌──────────────────────────────────────────────┐
  │ Type: Tech / SaaS — B2B                      │
  │ Idea: DevFlowKit — CI/CD pipeline templates  │
  │ Competitors: 3 (all priced $29-49/mo)        │
  │ Score: Market=4, Feasibility=4, Revenue=3    │
  │ Total: 11/15 ✓                               │
  │ Domain: devflowkit.com — AVAILABLE            │
  │ Launch: Product Hunt, HN, dev.to, X          │
  └──────────────────────────────────────────────┘
```

## Example: Local Service Business (B2C)

```
User: I want to create a website for my horse riding school in Austin

Agent: Phase 0: CLASSIFY → Local service, B2C
       Starting Phase 1: VALIDATE.

  → web_search "horse riding lessons Austin TX"
  → browser_navigate https://www.google.com/maps (horse riding near Austin)
  → browser_extract (competitor list: 7 local schools, pricing $50-120/lesson)
  → shell_execute "whois austintrailrides.com" → Available!

  Validation Report:
  ┌──────────────────────────────────────────────────────┐
  │ Type: Local service — B2C                            │
  │ Idea: Austin Trail Rides — horse riding lessons      │
  │ Competitors: 7 local (pricing $50-120/lesson)        │
  │ Gap: Most have outdated sites, no online booking     │
  │ Score: Market=3, Feasibility=5, Revenue=4            │
  │ Total: 12/15 ✓                                       │
  │ Domain: austintrailrides.com — AVAILABLE              │
  │ Launch: Google Business, Yelp, Facebook local groups, │
  │         Instagram, Nextdoor                           │
  └──────────────────────────────────────────────────────┘

  Phase 2: PLAN
  Revenue model: Booking fees ($75/lesson, $500/10-pack)
  MVP: Mobile-first site with services, pricing, photos,
       location map, Calendly booking embed, testimonials
  Stack: Next.js on Vercel (free hosting)
  Priority: Google Business Profile setup after deploy

  Phase 5: LAUNCH (after build + deploy)
  → Google Business Profile (owner verifies)
  → Yelp listing with photos and services
  → Facebook: "Austin Horse Lovers" group, "Austin Parents" group
  → Nextdoor: neighborhood post in Austin area
  → Instagram: @austintrailrides with lesson photos and reels
  → NOT: Product Hunt, Hacker News, dev.to (wrong audience)
```

## Files

- **Skill:** `skills/business-launcher/SKILL.md`
- **Triggers:** business, startup, launch, saas, revenue, monetize, side project,
  indie hacker, spin up, make money, earn money, local business, service business,
  ecommerce, store, shop, online business, entrepreneurship
