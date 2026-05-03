# Business Launcher

## Description
End-to-end playbook for spinning up a revenue-generating business — from idea
validation through deployment, launch, and autonomous growth. Handles any
business type: tech (SaaS, API), local service (horse riding, tutoring),
ecommerce (physical/digital products), content, consulting.
Adapts strategy based on B2B vs B2C and industry.

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
- online business
- local business
- service business
- ecommerce
- store
- shop

## Instructions

### How This Works in Practice

This skill spans days or weeks, not one conversation. Here's exactly what
the agent must do:

**Step 1 — Classify + Validate in the current conversation.**
Run Phase 0 (classify) and Phase 1 (validate) immediately. Present the
validation report to the owner and wait for approval.

**Step 2 — Create a goal with checkpoints.**
After the owner approves the idea, call `goal_create` with one checkpoint
per remaining phase:

```
goal_create:
  goal: "Launch [business name] — [type, B2B/B2C]"
  checkpoints:
    - description: "Plan MVP — revenue model, scope, tech stack, pricing"
      success_criteria: "Plan presented and approved by owner"
    - description: "Build MVP"
      success_criteria: "npm run build passes, all pages render"
    - description: "Deploy to production"
      success_criteria: "Live URL accessible, owner approved for launch"
    - description: "Launch on [platform-specific channels]"
      success_criteria: "Posted on 3+ platforms, URLs saved to knowledge"
    - description: "Set up growth — spawn specialists, schedule content"
      success_criteria: "Marketing specialist active, first content scheduled"
    - description: "Set up operations — recurring goal, email monitor"
      success_criteria: "Recurring goal created, email monitor running"
```

The goal system handles persistence, auto-continuation across sessions,
and progress tracking. The autonomous mind picks up where you left off.

**Step 3 — Save state after every phase.**
After completing each phase, call `knowledge_write` to save:
- Phase results (competitor data, plan decisions, deployment URLs, launch URLs)
- File path: `knowledge/projects/[business-name]/phase-N-[name].md`
- This ensures context survives across sessions and conversation resets

**Step 4 — Gate: stop and ask before critical phases.**
At owner gates (after Validate, Plan, Deploy), present findings and STOP.
Do not continue until the owner explicitly approves. Use a message like:
"Here's the validation report. Approve to proceed to planning, or tell me
to pivot."

---

### The 7-Phase Pipeline

Every business follows these phases. Do NOT skip phases or jump to building
before validating. Each phase has an owner gate — present findings and wait
for approval before proceeding.

---

### Phase 0: CLASSIFY (determine business type first)

Before anything else, classify the business. This changes everything downstream
— what to build, where to launch, how to grow.

**Business type:**

| Type | Examples | Build | Launch Channels |
|---|---|---|---|
| **Tech / SaaS** | Dev tool, dashboard, API | Web app | Product Hunt, HN, dev.to, X |
| **Local service** | Horse riding, tutoring, cleaning, gym | Booking site | Google Business, Yelp, local Facebook groups, Nextdoor, local directories |
| **Professional service** | Consulting, design agency, coaching | Portfolio + booking | LinkedIn, industry forums, referral networks |
| **Ecommerce** | Physical products, handmade goods | Online store | Instagram, Pinterest, Etsy, TikTok, niche marketplaces |
| **Digital product** | Course, template, ebook, preset pack | Sales page | X, YouTube, niche communities, Gumroad discover |
| **Content / Media** | Blog, newsletter, podcast companion | Content site | SEO, social media, email list |

**Customer type:**

| Type | Key Differences |
|---|---|
| **B2C** (business to consumer) | Emotion-driven, visual, social proof matters, price-sensitive, short sales cycle, high volume / low price |
| **B2B** (business to business) | ROI-driven, case studies matter, longer sales cycle, low volume / high price, email outreach works, LinkedIn is primary |

Classify BOTH dimensions before proceeding. A horse riding school is
**local service + B2C**. A developer API is **tech + B2B**. A Notion template
pack is **digital product + B2C**. A consulting firm website is
**professional service + B2B**.

---

### Phase 1: VALIDATE (research before anything)

**Goal:** Confirm the idea has a real market before writing a single line of code.

1. **Define the opportunity** — what problem does this solve? For whom?
2. **Market research** — use `web_search` and `browser_navigate` to:
   - Find 5+ existing competitors (pricing, features, reviews)
   - Estimate market size (search volume, existing user counts)
   - Identify gaps (what competitors do badly, what's missing)
   - **For local service:** search "[service] near [city]" to gauge local competition
   - **For B2B:** find how businesses currently solve this (often manual, spreadsheet, or overpriced enterprise)
   - **For ecommerce:** check Etsy, Amazon, Shopify stores for similar products + pricing
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

**GATE:** Present the validation report (business type, B2B/B2C, competitors,
gaps, score, proposed name + domain) to the owner. Wait for approval.

---

### Phase 2: PLAN (scope the thinnest possible MVP)

**Goal:** Define what to build — the smallest thing that creates real value.

1. **Pick the revenue model based on business type:**

   | Business Type | Revenue Model | Payment |
   |---|---|---|
   | Tech / SaaS | Subscription ($9-99/mo) | Stripe |
   | Tech / API | Per-call or tiered plans | Stripe / crypto |
   | Local service | Booking fees or retainer | Stripe / cash / Square |
   | Professional service | Project-based or retainer | Invoice / Stripe |
   | Ecommerce | Per-item sales | Stripe / Shopify Payments |
   | Digital product | One-time purchase ($9-199) | Gumroad / Stripe / crypto |
   | Content / Media | Ads, sponsors, affiliate, newsletter subscription | Ad networks / Stripe |

2. **Define MVP scope based on business type:**

   **Tech / SaaS:**
   - Core feature (ONE thing), landing page, auth, database
   - Stack: Next.js + Supabase + shadcn

   **Local service (horse riding, tutoring, gym, etc.):**
   - Homepage with what you offer, pricing, location/hours
   - Booking/contact form (Calendly embed or simple form → email)
   - Testimonials section (even if empty at launch — add the structure)
   - Google Maps embed
   - Mobile-first — most local customers search on phone
   - Stack: Next.js on Vercel (simple, fast, free)

   **Professional service / Consulting:**
   - Portfolio showcasing past work or expertise
   - Services + pricing page
   - Contact form or Calendly booking link
   - Case studies section (even 1-2 is enough)
   - Stack: Next.js on Vercel

   **Ecommerce:**
   - Product pages with photos, descriptions, pricing
   - Cart + checkout (Stripe Checkout or Gumroad)
   - Stack: Next.js + Supabase or Shopify (owner sets up)

   **Digital product:**
   - Sales page with problem → solution → proof → CTA
   - Product preview / free sample
   - Checkout (Gumroad link or Stripe)
   - Stack: Single page on Vercel

   **Content site:**
   - 5-10 initial articles targeting long-tail keywords
   - Email signup form
   - Stack: Next.js + MDX on Vercel

3. **Set pricing** — research competitor pricing (Phase 1 data):
   - **B2C:** Price 10-30% below cheapest competitor to undercut on entry
   - **B2B:** Price based on ROI delivered, not cost. If you save 10 hours/month, charge 20% of that value
   - **Local service:** Match local market rates. Check competitors on Google/Yelp

**GATE:** Present the plan (business type, revenue model, features, stack, pricing).

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
3. **Every business needs a landing page.** The content varies by type:

   **Tech / SaaS:**
   - Headline: what it does in one sentence
   - 3 benefit bullets, screenshot/demo
   - Pricing, CTA (sign up / start free trial)

   **Local service:**
   - Headline: what service + location ("Horse Riding Lessons in Austin")
   - Services offered with pricing
   - Photos (owner provides or use quality stock)
   - Testimonials / reviews
   - Location map + hours + contact
   - "Book Now" CTA (Calendly, form, or phone number)
   - SEO: title tags, meta description, schema markup for local business

   **Professional service:**
   - Headline: who you help and what result you deliver
   - Services breakdown with outcomes (not just deliverables)
   - Case studies / portfolio
   - "Schedule a Call" CTA

   **Ecommerce:**
   - Product grid with photos and prices
   - Individual product pages
   - Trust signals (shipping info, return policy, reviews)
   - "Add to Cart" / "Buy Now" CTA

   **Digital product:**
   - Problem → Agitation → Solution structure
   - Product preview / table of contents / free chapter
   - Social proof (testimonials, download count)
   - "Buy Now" CTA with price

4. **Create database** if needed: `create_database` with initial schema SQL
5. **Build locally first** — always `npm run build` before deploying

**Rules:**
- Ship the FIRST working version, not the perfect one
- No admin panels, no dashboards, no analytics in v1
- One core feature, working end-to-end
- Use existing libraries, don't build from scratch
- Copy competitor UX patterns — don't reinvent
- Mobile-first for local and B2C businesses

---

### Phase 4: DEPLOY (go live)

**Goal:** Product accessible on the internet with a real URL.

1. **Deploy** using `deploy_website`:
   - Static / simple API → Vercel (free)
   - LLM calls / WebSockets / cron → Railway ($5/mo credit)
   - Auto-detect handles most cases
2. **Create database** if not done: `create_database` → Supabase
3. **Wire environment variables** — pass all credentials via `env_vars`
4. **Verify deployment** — open the URL with `browser_navigate`, test the flow
5. **Domain setup** — inform the owner they need to:
   - Buy the domain (Namecheap, Cloudflare, etc.)
   - Point DNS to the hosting provider
6. **For local service businesses, also set up:**
   - Google Business Profile (owner must verify — requires postcard or phone)
   - Schema.org LocalBusiness markup in the site's HTML

**GATE:** Ask the owner to:
- Set up Stripe (if needed) — requires human KYC verification
- Buy and configure the domain (DNS)
- Verify Google Business Profile (if local service)
- Review the live site and approve for launch

---

### Phase 5: LAUNCH (get first users)

**Goal:** Real humans see and use the product.

**CRITICAL: Choose launch channels based on business type + customer type.
Do NOT post a horse riding school on Hacker News. Do NOT post a dev tool
on Nextdoor.**

#### Tech / SaaS (B2B or B2C)

| Platform | Content Style |
|---|---|
| **Product Hunt** | Title, tagline, description, maker comment. Focus on problem solved |
| **Hacker News** | "Show HN: [name] — [what it does]". Technical angle, zero marketing language |
| **Indie Hackers** | Product showcase + founder story. Be honest about the journey |
| **X / Twitter** | Launch thread (5-7 tweets). Hook first, demo in the middle, CTA last |
| **dev.to / Hashnode** | Technical article: "How I built [X] with [stack]" |
| **Reddit** | r/SideProject, r/webdev, r/startups, or niche subreddit. Genuine, not promotional |
| **Relevant Discord/Slack** | Share in #showcase or #launches channels of relevant communities |

**If B2B tech:** Add LinkedIn post + direct email outreach to potential customers
(personalized, max 10/day, focus on the problem you solve for their specific situation)

#### Local Service (B2C — horse riding, tutoring, cleaning, gym, etc.)

| Platform | Content Style |
|---|---|
| **Google Business Profile** | Complete profile with photos, hours, services, pricing. THE most important channel |
| **Yelp** | Claim/create listing. Add photos, services, pricing |
| **Facebook** | Local community groups ("Austin Horse Riding", "Austin Parents"). Introduce yourself, don't hard-sell |
| **Nextdoor** | Local neighborhood posts. Very effective for local services |
| **Instagram** | Visual showcase of the service. Before/after, action shots, happy clients |
| **Local directories** | City-specific directories, niche directories (e.g., horse riding directories) |
| **Flyers / physical** | Inform owner: design a flyer PDF they can print and post locally |

**Also:** Encourage first customers to leave Google reviews — reviews are the
#1 growth driver for local businesses.

#### Professional Service / Consulting (B2B)

| Platform | Content Style |
|---|---|
| **LinkedIn** | Thought leadership posts. Share expertise, not sales pitches. 3-5x/week |
| **LinkedIn outreach** | Connect + personalized message to ideal clients. Max 20 connections/day |
| **Industry forums** | Answer questions where your expertise is relevant. Link to site in profile |
| **Email outreach** | Cold email to specific companies with a clear "here's what I can do for you" |
| **Referral network** | Ask owner for warm intros from existing contacts |
| **Medium / Substack** | Expert articles that demonstrate knowledge |

#### Ecommerce (B2C)

| Platform | Content Style |
|---|---|
| **Instagram** | Product photos, lifestyle shots, reels showing the product in use |
| **Pinterest** | Product pins linking to shop. High-intent buyers browse Pinterest |
| **TikTok** | Short videos: product demos, behind-the-scenes, unboxing |
| **Etsy** | If handmade/vintage — list there too (built-in buyer traffic) |
| **Facebook Marketplace** | For local delivery products |
| **Reddit** | Niche subreddits (e.g., r/BuyItForLife, r/shutupandtakemymoney) |

#### Digital Product (B2C or B2B)

| Platform | Content Style |
|---|---|
| **X / Twitter** | Thread showing what's inside + results it produces. Free sample as lead magnet |
| **Gumroad Discover** | If using Gumroad — their marketplace has built-in traffic |
| **YouTube** | Tutorial or walkthrough of the product |
| **Reddit** | Niche subreddit. Share free value first, product link in comments |
| **Product Hunt** | Works for tools, templates, courses |
| **Newsletter swaps** | Find newsletters in your niche, offer cross-promotion |

#### Content Site

| Platform | Action |
|---|---|
| **SEO** | Publish 10 articles before any promotion. Target long-tail keywords |
| **Email list** | Build from day 1. Offer a lead magnet (free guide/checklist) |
| **Social media** | Share articles on X, LinkedIn, Reddit — wherever the audience is |
| **Guest posting** | Write for established sites in the niche with a link back |

---

**General launch rules (all types):**
- Never post the same content on multiple platforms — customize per audience
- Check `knowledge_search` before posting to avoid duplicate posts
- Use `browser_navigate`, `browser_click`, `browser_type_text`, `browser_paste_html`
- Check existing accounts with `knowledge_search` and `vault_lookup` before creating new ones
- Save all launch URLs to knowledge for tracking

---

### Phase 6: GROW (iterate based on data)

**Goal:** Sustained user acquisition and product improvement.

1. **Spawn marketing specialist** — `organization_spawn` with role="marketing":
   - Seed with brand guidelines, launch URLs, competitor data from Phase 1
   - **B2C tech/digital:** "Create weekly content calendar for X and Instagram"
   - **B2B tech/service:** "Create weekly LinkedIn posts and monthly case study drafts"
   - **Local service:** "Post weekly on Instagram and monitor Google reviews"
   - **Ecommerce:** "Create daily product content for Instagram and Pinterest"
2. **Spawn research specialist** — `organization_spawn` with role="research":
   - "Monitor competitor updates weekly"
   - "Track mentions of our brand and report sentiment"
   - **Local:** "Monitor Google/Yelp reviews and alert on negative ones"
3. **Growth strategy by type:**

   **Tech / SaaS:**
   - SEO content pipeline (weekly blog posts targeting long-tail keywords)
   - Changelog / build-in-public updates on X
   - Integration partnerships

   **Local service:**
   - Google review generation (follow up with happy customers via email)
   - Local SEO optimization (blog posts about "[service] in [city]")
   - Seasonal promotions (holiday camps, summer specials, etc.)
   - Referral program ("bring a friend, get 10% off")

   **Professional service / B2B:**
   - LinkedIn thought leadership (3-5 posts/week)
   - Case studies after each successful project
   - Email nurture sequence for leads
   - Webinar or free consultation offers

   **Ecommerce:**
   - Instagram/TikTok content daily
   - User-generated content campaigns
   - Email marketing (cart abandonment, new arrivals)
   - Seasonal collections and limited drops

   **Digital product:**
   - Free content that leads to the paid product
   - Testimonials and social proof on the sales page
   - Bundle deals with complementary products
   - Affiliate program for promoters

4. **Monitor analytics** — periodically check via browser:
   - Traffic (Vercel/Railway dashboard)
   - Signups/purchases (Supabase/Stripe/Gumroad dashboard)
   - Social engagement (mentions, reviews, comments)
   - **Local:** Google Business Profile insights (impressions, calls, directions)
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
   - **Local:** Monitor Google/Yelp for new reviews, alert owner on negative
   - Report revenue and growth metrics to owner
2. **Create a recurring goal** — use `goal_create`:
   - "Maintain and grow [business name]"
   - Checkpoints: weekly content, monthly analytics review, quarterly pricing review
3. **Revenue tracking** — monitor payment provider dashboards via browser
4. **Customer support** — monitor email, respond to queries, escalate complex issues to owner

---

### Tools Used Per Phase

| Phase | Primary Tools |
|---|---|
| Classify | None (LLM classification based on user's description) |
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
6. **Google Business Profile verification** — Google mails a postcard or calls
7. **Physical operations** — for local service: the actual service delivery, location, staff

**Payments:** Before asking the owner, check what's already available:
1. `knowledge_search` for "stripe", "bank account", "payment" — may already be configured
2. `vault_lookup` for `stripe_key`, `paypal_key` — may already have API keys
3. `wallet_status` — check if the agent has a crypto wallet with funds

If credentials exist, use them. If not:
- **Fiat:** Ask the owner to set up Stripe/PayPal and provide API keys
- **Crypto:** Use the agent's own wallet to accept payments on-chain

---

### Anti-Patterns

- **Building before validating** — the #1 startup mistake. Always validate first.
  If score < 9/15, pivot to a different idea.
- **Over-engineering v1** — no admin panel, no microservices.
  Ship the simplest thing that works.
- **Skipping owner gates** — never deploy or spend money without explicit approval.
- **Wrong channels for the business type** — a local horse riding school has no
  business on Hacker News. A dev API tool has no business on Nextdoor. Always
  match launch channels to where the customers actually are.
- **Ignoring competitors** — if 10 well-funded companies do this, find a niche.
  If zero companies do this, question whether anyone wants it.
- **Same content everywhere** — each platform has its own culture and format.
  Customize every post for the platform and audience.
- **Treating B2B like B2C** — B2B buyers care about ROI, case studies, and
  integration. B2C buyers care about price, reviews, and visual appeal.
  Don't pitch ROI to a horse rider. Don't show pretty photos to a CTO.
- **Paying for ads in v1** — organic first. Paid acquisition after product-market
  fit is proven (users return without prompting).
- **No domain check** — never build anything without first confirming the .com
  is available. A taken domain means pick a different name.
- **Forgetting to save research** — all competitor data, pricing, and market
  findings must go to `knowledge_write`. You'll need them in Phase 6.
- **Ignoring mobile for B2C** — most consumers browse on phone. Local service
  and ecommerce sites MUST be mobile-first.
- **No Google Business Profile for local** — for local businesses, Google is
  the #1 discovery channel. Skipping this is like not having a sign on your door.

## Verify

- The deliverable for this phase exists as a concrete artifact (doc, ticket, board, repo) and its location is shared, not described
- Each commitment has an owner name, a due date, and a definition-of-done that someone other than the author could check
- Risks are listed with likelihood/impact and a named mitigation, not as a generic 'risks: TBD' bullet
- Dependencies on other teams/vendors/agents are explicit; an ack from each dependency is recorded or marked 'pending'
- Success criteria for the next phase are numeric or otherwise objectively testable
- A rollback / kill-switch / 'we will stop if X' criterion is written down before work starts
