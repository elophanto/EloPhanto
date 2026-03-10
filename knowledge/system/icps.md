---
title: Ideal Customer Profiles
created: 2026-03-10
updated: 2026-03-10
tags: marketing, customers, icps, audience, targeting
scope: system
---

# Ideal Customer Profiles

> Dossier-style profiles for each target user type. Reference when writing posts,
> choosing platforms, crafting messaging, or building features.
> Inspired by [Arvid Kahl](https://x.com/arvidkahl/status/2031457304328229184).

The common thread: these people don't want a chatbot. They want an **autonomous
digital worker** that operates independently — builds, earns, promotes, trades,
and grows while they do other things (or sleep).

---

## ICP 1: The Autonomous Business Operator

**Who they are**
- Entrepreneur or indie founder who wants to launch businesses at machine speed
- Has ideas but bottlenecked on execution — can't hire fast enough, or at all
- Thinks in terms of revenue, customers, and leverage — not code or tools
- May or may not be technical. Doesn't matter — they give the goal, agent does the rest
- Active on X (#buildinpublic), Hacker News, r/SideProject, r/Entrepreneur

**What they want**
- "I tell it to build me an invoice SaaS. I wake up and there's a deployed product with a landing page."
- An agent that validates ideas, builds MVPs, deploys them, launches on the right platforms, monitors traction, and iterates — autonomously across sessions
- Multiple businesses running in parallel via organization specialists
- Revenue tracking — the agent should know if something is making money and act on it

**How EloPhanto delivers**
- Business launcher: 7-phase pipeline (validate → plan → build → deploy → launch → grow → operate)
- Autonomous mind: continues working between conversations — overnight builds, scheduled launches
- Swarm: spawns Claude Code / Codex to build code while it handles marketing and deployment
- Organization: spawn "saas-1-dev", "saas-2-marketing" specialists that persist and improve
- Browser: posts to Product Hunt, HN, Reddit, X — with real Chrome, not API-detectable bots
- Payments: accepts crypto, integrates Stripe/PayPal through chat-based setup
- Goals: multi-session execution — starts today, deploys tomorrow, launches next week

**Where to reach them**
- X (indie hackers, solopreneurs, #buildinpublic)
- Hacker News (Show HN, agent/AI discussions)
- Reddit: r/SideProject, r/Entrepreneur, r/indiehackers
- Product Hunt (both as a launch platform and as a discovery channel)

**What convinces them**
- Demo: "I said 'build an invoice SaaS'. Here's what I woke up to." with real screenshots
- Revenue proof: agent that actually generated income autonomously
- Phase-by-phase progress showing real work done across sessions
- Comparison: "Hired a freelancer for $5k or let the agent do it overnight for $3 in API costs"

---

## ICP 2: The Agent Economy Participant

**Who they are**
- Deep in AI agents, DeFi, crypto, and the emerging agent-to-agent economy
- Runs wallets, trades tokens, interacts with protocols programmatically
- Wants their agent to have financial autonomy — earn, spend, trade, invest
- Comfortable with self-custody, private keys, and on-chain operations
- Active on Crypto Twitter, Solana Discord, DeFi Telegram groups, Agent Commune

**What they want**
- An agent with its own wallet that can autonomously execute DeFi strategies
- Swap tokens on Jupiter, monitor positions, rebalance portfolios — without asking permission every time
- Participate in the agent economy: agent-to-agent payments, on-chain reputation
- Self-custody only — they will never trust a cloud agent with keys
- Extensibility: connect any Solana protocol via MCP servers and skills

**How EloPhanto delivers**
- Solana wallet: self-custody keypair, auto-created, encrypted in vault
- Jupiter DEX swaps: any token pair via Ultra API, best-price routing
- 27 Solana skills: Jupiter, Drift, Orca, Raydium, Kamino, Meteora, Helius, Pyth, etc.
- MCP servers: QuickNode, Solana Developer MCP, DFlow for live on-chain data
- Spending limits + audit trail: owner controls how much the agent can move
- wallet_export: move keys to Phantom/Solflare if needed
- Autonomous mind: monitor prices, execute on conditions, report portfolio changes
- Agent Commune: social presence and reputation in agent-native platform

**Where to reach them**
- X (Crypto Twitter, AI agent discussions, Solana ecosystem)
- Discord: Solana dev servers, DeFi protocol communities
- Telegram: crypto trading and DeFi strategy groups
- Agent Commune
- Reddit: r/solana, r/defi, r/LocalLLaMA

**What convinces them**
- Real Jupiter swap transaction on-chain (not a mock)
- "Your keys, your agent, your machine" — self-custody, open source, auditable
- Protocol names they know (Jupiter, Drift, Orca, Raydium, Helius)
- Comparison with Solana Agent Kit, GOAT SDK — EloPhanto does everything they do plus autonomous operation

---

## ICP 3: The One-Person Company

**Who they are**
- Running a real business solo — agency, consulting, freelance, ecommerce, content
- Needs to be CEO, developer, marketer, support rep, and accountant simultaneously
- Revenue is flowing but growth is capped by their time
- Wants to clone themselves, not hire employees
- Moderately technical — can use terminal, but agents should handle the complexity

**What they want**
- A digital co-founder that handles everything they can't get to
- Client emails answered, social media maintained, projects deployed, leads followed up
- Agent that understands their business context and acts appropriately across channels
- Organization: spin up specialists per function (marketing, dev, support) that persist
- Multi-channel: Slack for client A, Discord for client B, email for leads — one agent

**How EloPhanto delivers**
- Organization: spawn persistent specialist agents per domain — each evolves independently
- Multi-channel: CLI, Web, VS Code, Telegram, Discord, Slack — all connected via gateway
- Email: monitor inboxes, draft responses, send attachments, create new inboxes per client
- Browser: post content, research competitors, manage platforms, fill forms
- Knowledge: per-client context that persists — agent remembers everything about every project
- Autonomous mind: works between conversations — follows up on leads, posts content, monitors alerts
- Deployment: ship client projects to Vercel/Railway through conversation
- Identity: learns the owner's voice and preferences over time

**Where to reach them**
- X (solopreneurs, freelancer circles)
- LinkedIn (consultants, agency owners)
- Reddit: r/freelance, r/webdev, r/smallbusiness
- Indie Hackers community
- Podcasts and newsletters about solo business

**What convinces them**
- "I have 5 specialists running 24/7 and none of them need a salary"
- Time math: "Saved 20 hours/week on email, social, and deployment"
- Multi-channel demo — same agent, different channels, different clients
- Data stays local — client confidentiality guaranteed

---

## ICP 4: The AI-Native Builder

**Who they are**
- Technical person who sees AI agents as the next computing platform
- Building on top of or around agent infrastructure
- Wants to customize, extend, and deeply integrate agents into their workflow
- Evaluates agents by capability ceiling, not ease of use
- Active on GitHub, Hacker News, r/LocalLLaMA, AI research Twitter

**What they want**
- Open source agent they can fully control — read every line, modify anything
- Self-development: agent that builds its own tools when it hits a gap
- MCP server ecosystem: connect any external service through standard protocol
- Local-first with local LLMs: Ollama, no cloud dependency, full privacy
- Plugin/skill system to extend without forking

**How EloPhanto delivers**
- Open source Apache 2.0 — fully auditable, forkable, extensible
- Self-development pipeline: agent writes, tests, and deploys its own plugins
- 147 skills + EloPhantoHub registry for community contributions
- MCP adapter: connect any MCP server — filesystem, GitHub, databases, Slack, custom
- Ollama support: runs entirely local, zero cloud dependency
- Encrypted vault, security hardening (7 layers), content security policy on skills
- Code execution sandbox: agent writes Python scripts that call tools via RPC
- Autonomous experimentation: modify → measure → keep/discard in a loop

**Where to reach them**
- GitHub (stars, issues, PRs, discussions)
- Hacker News (technical deep-dives, agent architecture posts)
- Reddit: r/LocalLLaMA, r/selfhosted, r/MachineLearning
- X (AI/ML research circles, agent framework discussions)
- Discord: AI agent communities, open source communities

**What convinces them**
- Architecture docs showing real engineering (not a wrapper)
- Self-dev demo: agent building its own tool from scratch
- 140+ tools, 147 skills — capability breadth
- Security hardening depth — PII guard, swarm boundaries, injection prevention
- Active GitHub with frequent commits, thorough docs

---

## ICP 5: The Delegator (Non-Technical)

**Who they are**
- Business owner, creator, or professional who is NOT a developer
- Wants AI to handle tasks they'd otherwise outsource or ignore
- Interacts via chat (Telegram, Discord, Web) — never touches terminal
- Cares about results, not how it works
- Willing to pay for API costs if the agent delivers real value

**What they want**
- "Do this thing for me" and it gets done. No setup, no code, no debugging.
- Research, write content, post to social, manage email, monitor competitors
- Agent that improves over time — learns their preferences without being re-taught
- Works on mobile via Telegram or Discord — not just desktop
- Clear approval flow for anything risky (spending money, sending emails, deleting things)

**How EloPhanto delivers**
- Multi-channel: Telegram and Discord as primary interfaces — chat on phone
- Approval system: agent asks before destructive/critical actions, owner approves/denies
- Identity evolution: learns communication style, preferences, boundaries over time
- Browser: handles web tasks (posting, researching, filling forms) without user involvement
- Email: manages inbox, drafts responses, sends on approval
- Autonomous mind: background operation with scheduled tasks and goals
- Web dashboard: visual monitoring of what the agent is doing — no CLI needed
- Knowledge: persists everything — never forgets context, preferences, or past decisions

**Where to reach them**
- X (business owners, creators, "AI productivity" circles)
- YouTube (AI tool reviews, productivity channels)
- TikTok/Instagram (short demos showing real results)
- LinkedIn (professionals interested in AI automation)
- Word of mouth from other ICPs

**What convinces them**
- 30-second video: user sends Telegram message → agent does complex task → result appears
- "Set it up once, it works forever" messaging
- Approval flow demo — "it asks before spending your money"
- Comparison with human VA cost ($500-2000/month) vs API costs ($5-30/month)

---

## ICP 6: The AI-Curious Professional

**Who they are**
- Manager, consultant, marketer, accountant, lawyer, or any knowledge worker
- Keeps hearing about AI agents but hasn't used one beyond ChatGPT
- Not technical — doesn't code, doesn't use terminal, might not know what GitHub is
- Wants to "get into AI" but overwhelmed by options and jargon
- Spends 40+ hours/week on tasks that feel repetitive and automatable

**What they want**
- A personal AI that actually *does things* — not just answers questions
- "I want to say 'handle my emails while I'm in meetings' and it handles them"
- Something that learns how they work — their preferences, their clients, their style
- Doesn't want to set up infrastructure, write prompts, or manage anything technical
- Proof that AI can save them real hours, not theoretical productivity gains

**How EloPhanto delivers**
- Telegram/Discord as primary interface — chat like texting a human assistant
- Web dashboard for visual monitoring — see what the agent is doing without CLI
- Email management: monitor, draft, respond, organize — with approval before sending
- Browser automation: research, fill forms, book things, post content — all in real Chrome
- Identity evolution: learns their voice, preferences, and working patterns over time
- Scheduled tasks: "Check my inbox every morning and summarize what needs attention"
- Approval system: nothing risky happens without their explicit OK
- Knowledge persistence: never forgets — context from 3 weeks ago is still there

**Where to reach them**
- LinkedIn (AI productivity content, thought leadership)
- YouTube (AI tool demos, "how I use AI" videos)
- X (mainstream AI discussion, not dev circles)
- TikTok/Instagram Reels (short "look what my AI did" demos)
- Newsletters (The Hustle, Morning Brew, AI-focused newsletters)
- Word of mouth from colleagues already using it

**What convinces them**
- 30-second video: person sends message on phone → agent handles complex task → result appears
- "It's like having a personal assistant that costs $10/month instead of $4,000"
- Real before/after: "I used to spend 3 hours on email. Now I spend 15 minutes reviewing what the agent drafted."
- Testimonial-style: regular person (not a developer) showing their workflow
- Zero-setup narrative: "My friend set it up for me. Now I just text it on Telegram."

---

## ICP 7: The Business Leader / Executive

**Who they are**
- CEO, COO, VP, or department head at a company (10-500 people)
- Thinks in terms of headcount, margins, operational efficiency, and competitive advantage
- Has heard the board/investors ask "what's your AI strategy?"
- Doesn't care how AI works — cares about what it saves and what it produces
- Makes buy/build/hire decisions with ROI as the primary lens

**What they want**
- Reduce operational costs without reducing output
- An AI workforce that handles tasks currently done by junior staff or contractors
- Prototype new business lines quickly without committing headcount
- Data stays in-house — regulatory and competitive reasons (legal, finance, healthcare)
- Measurable impact: hours saved, tasks completed, cost per task vs human equivalent

**How EloPhanto delivers**
- Organization: spawn specialist agents per function — marketing, support, research, ops
- Each specialist has its own identity, knowledge, and autonomous mind — like hiring a department
- Multi-channel: different teams interact via their preferred channel (Slack, Discord, email)
- Business launcher: prototype new revenue streams — validate → build → deploy → measure
- Autonomous mind: agents work 24/7, not 40 hours/week — overnight research, weekend monitoring
- Audit trail: every action logged, every transaction tracked, every approval recorded
- Spending limits: hard caps on what agents can spend — financial control stays with leadership
- Local-first: all data on company hardware — no cloud AI vendor seeing proprietary information
- Swarm: spin up coding teams for feature builds without hiring contractors

**Where to reach them**
- LinkedIn (executive AI strategy content, case studies)
- Harvard Business Review, McKinsey articles (AI transformation)
- Industry conferences and executive briefings
- Board decks and investor reports (via their technical advisors)
- Direct referral from their CTO/VP Engineering who discovers EloPhanto

**What convinces them**
- ROI math: "5 specialist agents running 24/7 = $50/month in API costs. One junior employee = $5,000/month."
- Case study: "Company X reduced support response time by 80% with 3 EloPhanto agents"
- Data sovereignty: "Everything runs on your servers. No data leaves your network."
- Compliance angle: audit trails, approval gates, spending limits — enterprise-grade control
- Comparison: "Unlike hiring an AI consultancy, you own the agents and all their knowledge"

---

## ICP 8: The Creator / Influencer

**Who they are**
- Content creator, podcaster, YouTuber, newsletter writer, or social media personality
- Their business IS their personal brand — content is the product
- Perpetually behind on content calendar, engagement, and cross-platform distribution
- May have a small team (VA, editor) but still the bottleneck for everything creative
- Revenue comes from audience size, engagement, sponsors, and digital products

**What they want**
- An agent that handles the distribution and engagement grind so they can focus on creation
- "I record the video. The agent writes the tweet thread, the LinkedIn post, the newsletter excerpt, and schedules everything."
- Research and trend monitoring — what's working in their niche, what competitors are doing
- Audience engagement: respond to comments, DMs, and emails in their voice
- Launch digital products (courses, templates, ebooks) without hiring a dev team

**How EloPhanto delivers**
- Browser automation: post to X, LinkedIn, Reddit, Medium, YouTube community — real Chrome, not detectable API bots
- Identity evolution: learns their unique voice, tone, and style — drafts sound like them, not generic AI
- Business launcher: spin up landing pages and digital product storefronts autonomously
- Email: newsletter drafts, subscriber management, sponsor outreach
- Scheduling: "Post this thread at 9am EST, the LinkedIn version at noon, the newsletter on Friday"
- Autonomous mind: monitors engagement, suggests follow-up content, tracks what resonates
- Knowledge: remembers every piece of content they've made — references past work, maintains continuity
- Remotion: create video clips, animated explainers, and social media graphics programmatically

**Where to reach them**
- X (creator circles, content strategy discussions)
- YouTube (creator economy channels, "tools I use" videos)
- TikTok (short demos of agent handling distribution)
- Newsletters (Creator Economy, The Publish Press)
- Creator-focused communities (Circle, Mighty Networks, private Discords)

**What convinces them**
- Side-by-side: "I used to spend Sunday doing distribution. Now the agent does it while I'm at brunch."
- Voice demo: show the agent writing in the creator's actual style (not generic)
- Revenue attribution: "Agent-posted content drove 40% of my traffic this month"
- Cross-platform demo: one piece of content → 5 platforms → different formats → all scheduled

---

## Messaging Matrix

| ICP | Primary Hook | Secondary Hook | Avoid |
|-----|-------------|----------------|-------|
| Business Operator | "Builds businesses while you sleep" | "Idea to deployed product in one conversation" | "Coding assistant" framing |
| Agent Economy | "Your agent has its own wallet" | "Self-custody Jupiter swaps from chat" | "AI-powered blockchain" buzzwords |
| One-Person Company | "5 specialists, zero salaries" | "Same agent across all your channels" | Enterprise/team framing |
| AI-Native Builder | "140+ tools, builds its own when it needs more" | "Open source, runs on Ollama, fully auditable" | Dumbing it down |
| Delegator | "Tell it what to do. It does it." | "Works on Telegram — no coding needed" | Technical jargon, CLI references |
| AI-Curious Professional | "Like a personal assistant for $10/month" | "Just text it on Telegram" | Any mention of code, git, or terminal |
| Business Leader | "An AI workforce at 1% the cost" | "All data stays on your servers" | Toy/hobby framing, open source ideology |
| Creator / Influencer | "You create. It distributes." | "Writes in your voice, posts everywhere" | "AI content generation" — they fear being seen as inauthentic |

## What All ICPs Share

- They want **autonomy** — the agent works independently, not just when prompted
- They want **persistence** — it remembers, learns, and continues across sessions
- They want **real actions** — not just text output, but deployed code, sent emails, executed trades
- They want **control** — approval gates, spending limits, audit trails, kill switches
- They value **ownership** — local-first, self-hosted, open source, their data stays theirs
