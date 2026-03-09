# Business Launcher

## Description
End-to-end playbook for spinning up a revenue-generating business — from idea
validation through deployment, launch, and autonomous growth. Uses EloPhanto's
existing tools (browser, deployment, email, payments, swarm, organization,
autonomous mind) as a coordinated pipeline.

## Triggers
- business
- startup
- launch a business
- make money
- revenue
- micro-saas
- side project
- spin up
- monetize
- build and launch
- go to market
- business idea
- saas
- product launch
- indie hacker
- entrepreneurship
- income
- earn money

## Instructions

### The 7-Phase Pipeline

Every business follows these phases. Do NOT skip phases or jump to building
before validating. Each phase has an owner gate — present findings and wait
for approval before proceeding.

---

### Phase 1: VALIDATE (research before anything)

**Goal:** Confirm the idea has a real market before writing a single line of code.

1. **Define the opportunity** — what problem does this solve? For whom?
2. **Market research** — use `web_search` and `browser_navigate` to:
   - Find 5+ existing competitors (pricing, features, reviews)
   - Estimate market size (search volume, existing user counts)
   - Identify gaps (what competitors do badly, what's missing)
3. **Check domain availability** — use `shell_execute` with `whois` or `nslookup`
   to verify the .com is available. If taken, pick a different name. Never proceed
   with a taken domain.
4. **Score the opportunity:**
   - Market gap (1-5): How underserved is this niche?
   - Feasibility (1-5): Can we build an MVP in 1-2 days?
   - Revenue potential (1-5): Is there a clear path to paying customers?
   - Total score must be ≥ 9/15 to proceed.
5. **Save research** — use `knowledge_write` to persist competitor analysis,
   pricing data, and market findings for future reference.

**GATE:** Present the validation report (competitors, gaps, score, proposed
name + domain) to the owner. Wait for approval. Do NOT proceed to Phase 2
without explicit go-ahead.

---

### Phase 2: PLAN (scope the thinnest possible MVP)

**Goal:** Define what to build — the smallest thing that creates real value.

1. **Pick the revenue model:**

   | Model | Best When | Payment Method |
   |---|---|---|
   | Micro-SaaS (subscription) | Recurring need, tool/dashboard | Stripe (owner sets up) |
   | API service (per-call) | Developer audience, technical | Stripe / crypto |
   | Digital product (one-time) | Templates, tools, datasets | Gumroad / crypto |
   | Content site (ads/affiliate) | Broad audience, SEO-driven | Ad networks / affiliate |
   | Freelance service | Expertise packaging | Direct invoice / crypto |

2. **Define MVP scope** — list exactly what v1 includes:
   - Core feature (ONE thing, not three)
   - Landing page with value proposition
   - Auth (if SaaS) — Supabase Auth is free
   - Database (if needed) — Supabase Postgres
   - Payment integration placeholder (Stripe link or crypto address)
3. **Choose tech stack** — match to the project type:
   - **SaaS:** Next.js + Supabase + shadcn (use `nextjs`, `supabase`, `shadcn` skills)
   - **API:** Node.js or Python on Railway
   - **Landing page only:** Next.js on Vercel
   - **Content site:** Next.js with MDX on Vercel
4. **Set pricing** — research competitor pricing (Phase 1 data) and price
   10-30% below the cheapest competitor to undercut on entry.

**GATE:** Present the plan (revenue model, features list, tech stack, pricing)
to the owner. Wait for approval.

---

### Phase 3: BUILD (execute fast, ship ugly)

**Goal:** Working MVP in 1-2 days. Perfection is the enemy.

1. **Spawn coding agents** if the project is complex:
   - Use `swarm_spawn` with `repo: "new"` for a fresh isolated project
   - Frontend + backend can be parallel agents
   - Each agent gets a context-enriched prompt with the plan from Phase 2
2. **Or build directly** if it's simple:
   - Scaffold with `shell_execute` (e.g., `npx create-next-app`)
   - Write code via `file_write`
   - Test locally via `shell_execute` (`npm run build`, `npm run dev`)
3. **Landing page is mandatory** — even API products need a landing page:
   - Clear headline: what it does in one sentence
   - 3 benefit bullets
   - Screenshot or demo GIF
   - Pricing section
   - CTA button (sign up / buy / get API key)
4. **Create database** if needed: `create_database` with initial schema SQL
5. **Build locally first** — always `npm run build` before deploying

**Rules:**
- Ship the FIRST working version, not the perfect one
- No admin panels, no dashboards, no analytics in v1
- One core feature, working end-to-end
- Use existing libraries, don't build from scratch
- Copy competitor UX patterns — don't reinvent

---

### Phase 4: DEPLOY (go live)

**Goal:** Product accessible on the internet with a real URL.

1. **Deploy** using `deploy_website`:
   - Static / simple API → Vercel (free)
   - LLM calls / WebSockets / cron → Railway ($5/mo credit)
   - Auto-detect handles most cases
2. **Create database** if not done: `create_database` → Supabase
3. **Wire environment variables** — pass all credentials via `env_vars`:
   - Supabase URL + keys
   - API keys (if the product calls external APIs)
   - Never hardcode secrets
4. **Verify deployment** — open the URL with `browser_navigate`, test the flow
5. **Domain setup** — inform the owner they need to:
   - Buy the domain (Namecheap, Cloudflare, etc.)
   - Point DNS to the hosting provider
   - This is the one step that requires human action

**GATE:** Ask the owner to:
- Set up Stripe (if SaaS/subscription) — requires human KYC verification
- Buy and configure the domain (DNS)
- Review the live site and approve for launch

---

### Phase 5: LAUNCH (get first users)

**Goal:** Real humans see and use the product.

1. **Write launch content** — create platform-specific posts:
   - **Product Hunt:** title, tagline, description, first comment
   - **Indie Hackers:** product showcase + story
   - **Hacker News:** Show HN post (title only, link to site)
   - **X / Twitter:** launch thread (5-7 tweets, hook first)
   - **Reddit:** relevant subreddit post (genuine, not spammy)
   - **dev.to / Hashnode:** technical article about how it's built
2. **Post using browser automation** — use `browser_navigate`, `browser_click`,
   `browser_type_text`, `browser_paste_html` to publish on each platform
3. **Check existing accounts** — use `knowledge_search` and `vault_lookup` to
   find stored credentials before creating new accounts
4. **Email outreach** — if B2B, use `email_send` to reach potential customers:
   - Personalized subject line
   - One-paragraph pitch
   - Clear CTA (try free / book demo)
   - Max 10 cold emails per day to start
5. **Save all launch URLs** to knowledge for tracking

**Rules:**
- Never post the same content on multiple platforms — customize per audience
- Hacker News: technical angle, no marketing language
- Product Hunt: focus on the problem solved
- Reddit: be a community member, not a marketer
- Check `knowledge_search` before posting to avoid duplicate posts

---

### Phase 6: GROW (iterate based on data)

**Goal:** Sustained user acquisition and product improvement.

1. **Spawn marketing specialist** — use `organization_spawn` with role="marketing":
   - Seed with brand guidelines, launch URLs, competitor data from Phase 1
   - Delegate: "Create weekly content calendar for X and LinkedIn"
   - The specialist works proactively via its autonomous mind
2. **Spawn research specialist** — use `organization_spawn` with role="research":
   - Delegate: "Monitor competitor updates weekly"
   - Delegate: "Track mentions of our product and report sentiment"
3. **SEO content pipeline** — schedule with `schedule_task`:
   - Weekly blog post targeting long-tail keywords
   - Use `web_search` to find keywords competitors rank for
   - Write content via `file_write`, publish via browser automation
4. **Monitor analytics** — periodically check via browser:
   - Vercel/Railway dashboard for traffic
   - Supabase dashboard for user signups
   - Social media for mentions and engagement
5. **Iterate on product** — when users report issues or request features:
   - Use `swarm_spawn` for code changes
   - Redeploy via `deploy_website`

---

### Phase 7: OPERATE (autonomous maintenance)

**Goal:** The business runs with minimal human involvement.

1. **Autonomous mind integration** — the background mind should:
   - Check analytics weekly (browser automation)
   - Post content on schedule (via marketing specialist)
   - Monitor inbox for customer inquiries (via `email_monitor`)
   - Report revenue and growth metrics to owner
2. **Create a recurring goal** — use `goal_create`:
   - "Maintain and grow [business name]"
   - Checkpoints: weekly content, monthly analytics review, quarterly pricing review
3. **Revenue tracking** — monitor payment provider dashboards via browser
4. **Customer support** — monitor email, respond to queries, escalate complex issues to owner

---

### Revenue Models — Detailed Playbooks

#### Micro-SaaS
```
Validate → find pain point in niche community
Build → Next.js + Supabase + Stripe
Price → $9-29/mo (undercut competitors)
Launch → Product Hunt + Indie Hackers + niche community
Grow → SEO content + social proof
```

#### API Service
```
Validate → find developers solving a repetitive problem
Build → Python/Node API on Railway + docs page
Price → free tier (100 calls/day) + $19/mo for 10K calls
Launch → dev.to article + Hacker News + relevant Discord servers
Grow → developer content + code examples + SDK
```

#### Digital Product
```
Validate → find repeated questions in communities
Build → create the resource (template, guide, dataset, tool)
Price → $19-49 one-time on Gumroad
Launch → X thread showing the value + Reddit post in niche sub
Grow → create free samples → funnel to paid product
```

#### Content Site
```
Validate → find high-volume keywords with low competition
Build → Next.js + MDX blog on Vercel
Price → none (monetize with ads + affiliate links)
Launch → publish 10 SEO articles before promoting
Grow → 2-3 articles/week, build email list, affiliate partnerships
```

---

### Tools Used Per Phase

| Phase | Primary Tools |
|---|---|
| Validate | `web_search`, `browser_navigate`, `browser_extract`, `shell_execute` (whois), `knowledge_write` |
| Plan | `knowledge_search` (retrieve Phase 1 data), `skill_read` (tech skills) |
| Build | `swarm_spawn`, `file_write`, `file_read`, `shell_execute`, `create_database` |
| Deploy | `deploy_website`, `create_database`, `browser_navigate` (verify) |
| Launch | `browser_navigate`, `browser_click`, `browser_type_text`, `browser_paste_html`, `email_send`, `knowledge_search` |
| Grow | `organization_spawn`, `organization_delegate`, `schedule_task`, `browser_navigate` |
| Operate | `goal_create`, `email_monitor`, `set_next_wakeup`, `update_scratchpad` |

---

### What Requires Human Action

These steps CANNOT be done autonomously — always inform the owner:

1. **Business registration** — LLC/sole proprietorship filing (legal requirement)
2. **Stripe setup** — KYC verification requires human identity documents
3. **Domain purchase** — requires payment method and DNS configuration
4. **Bank account** — business bank account for payouts
5. **Tax compliance** — EIN, state registrations, sales tax

For crypto-only businesses, steps 2 and 4 can be replaced with the agent's
own wallet (`wallet_status`, `crypto_transfer`), but legal registration and
tax compliance still require a human.

---

### Anti-Patterns

- **Building before validating** — the #1 startup mistake. Always validate first.
  If score < 9/15, pivot to a different idea.
- **Over-engineering v1** — no auth system, no admin panel, no microservices.
  Ship the simplest thing that works.
- **Skipping owner gates** — never deploy or spend money without explicit approval.
  Present findings, wait for go-ahead.
- **Ignoring competitors** — if 10 well-funded companies do this, find a niche.
  If zero companies do this, question whether anyone wants it.
- **Same content everywhere** — each platform has its own culture. Product Hunt
  is not Reddit. Hacker News is not X. Customize every post.
- **Paying for ads in v1** — organic first. Paid acquisition after product-market
  fit is proven (users return without prompting).
- **No domain check** — never build anything without first confirming the .com
  is available. A taken domain means pick a different name.
- **Forgetting to save research** — all competitor data, pricing, and market
  findings must go to `knowledge_write`. You'll need them in Phase 6.
