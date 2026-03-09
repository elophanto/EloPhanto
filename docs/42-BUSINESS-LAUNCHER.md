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

## The 7 Phases

```
┌──────────────────────────────────────────────────────────────┐
│  Phase 1: VALIDATE                                           │
│  Market research, competitors, domain check, opportunity score│
│  Gate: Owner approves idea (score ≥ 9/15)                    │
├──────────────────────────────────────────────────────────────┤
│  Phase 2: PLAN                                               │
│  Revenue model, MVP scope, tech stack, pricing               │
│  Gate: Owner approves plan                                   │
├──────────────────────────────────────────────────────────────┤
│  Phase 3: BUILD                                              │
│  Spawn swarm agents or build directly, landing page, database│
│  Ship the first working version, not the perfect one         │
├──────────────────────────────────────────────────────────────┤
│  Phase 4: DEPLOY                                             │
│  deploy_website + create_database, verify live URL           │
│  Gate: Owner sets up Stripe, buys domain, reviews site       │
├──────────────────────────────────────────────────────────────┤
│  Phase 5: LAUNCH                                             │
│  Product Hunt, Indie Hackers, HN, X, Reddit, dev.to         │
│  Platform-specific content, email outreach                   │
├──────────────────────────────────────────────────────────────┤
│  Phase 6: GROW                                               │
│  Spawn marketing + research specialists, SEO pipeline,       │
│  scheduled content, analytics monitoring, product iteration  │
├──────────────────────────────────────────────────────────────┤
│  Phase 7: OPERATE                                            │
│  Autonomous mind maintenance, recurring goals, email monitor,│
│  revenue tracking, customer support triage                   │
└──────────────────────────────────────────────────────────────┘
```

## Revenue Models

The skill supports four proven revenue models, each with a detailed playbook:

| Model | Build Cost | Time to Revenue | Tools Used |
|---|---|---|---|
| **Micro-SaaS** | $0-200 | 2-4 weeks | Next.js + Supabase + Stripe |
| **API Service** | $0-50 | 1-2 weeks | Python/Node on Railway |
| **Digital Product** | $0 | 1 week | Content creation + Gumroad |
| **Content Site** | $0 | 4-8 weeks (SEO ramp) | Next.js + MDX + ads |

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

## Limitations

1. **Legal identity** — business registration, EIN, and contracts require a
   human. The agent cannot form an LLC or sign Terms of Service.
2. **Payment processor KYC** — Stripe, PayPal, and traditional processors
   require human identity verification for merchant accounts.
3. **Domain purchase** — requires a payment method and DNS configuration
   that the agent cannot perform without browser access to a registrar
   (possible but requires stored payment credentials).
4. **Quality ceiling** — the agent ships fast but rough. Human review is
   critical for customer-facing copy, pricing decisions, and brand quality.
5. **Customer judgment** — tier-1 support is automatable, but nuanced
   refund decisions, relationship management, and edge cases need a human.

## Example Conversation

```
User: I want to spin up a micro-SaaS for developers

Agent: Starting Phase 1: VALIDATE. Let me research the developer tools market.

  → web_search "developer tools micro-saas 2026 gaps"
  → web_search "developer productivity tools pricing"
  → browser_navigate https://www.producthunt.com/topics/developer-tools
  → browser_extract (competitor list with pricing)
  → shell_execute "whois devflowkit.com" → Available!

  Validation Report:
  ┌──────────────────────────────────────────────┐
  │ Idea: DevFlowKit — CI/CD pipeline templates  │
  │ Gap: Existing tools are complex, no one-click │
  │ Competitors: 3 (all priced $29-49/mo)        │
  │ Score: Market=4, Feasibility=4, Revenue=3    │
  │ Total: 11/15 ✓                               │
  │ Domain: devflowkit.com — AVAILABLE            │
  └──────────────────────────────────────────────┘

  Proceed to Phase 2: PLAN?

User: Yes, go ahead

Agent: Phase 2: PLAN
  Revenue model: Micro-SaaS subscription
  MVP: Template browser + one-click apply to GitHub Actions
  Stack: Next.js + Supabase + shadcn
  Pricing: $9/mo (undercutting $29 competitors)
  ...
```

## Files

- **Skill:** `skills/business-launcher/SKILL.md`
- **Triggers:** business, startup, launch, saas, revenue, monetize, side project,
  indie hacker, spin up, make money, earn money, entrepreneurship
