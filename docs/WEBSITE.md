# EloPhanto.com — Website & EloPhantoHub

## Domains

- **elophanto.com** — website, hub lives at `/hub`
- **api.elophanto.com** — API subdomain, versioned (`/v1/`), points to the same Vercel project via rewrites

---

## Update Plan — v2026.05.02 (current release)

Every change the live site needs since the last update. Each entry maps
to a section below; the inline sections have already been refreshed,
this checklist is what the website team ships.

### Hero + Above-the-fold

- **Tagline** stays the same — *"A self-evolving AI agent that lives on your machine."*
- **One-liner** rewrite: replace *"Local-first, multi-channel, browser-capable, learns as it works."* with **"It carries an evolving identity, builds its own tools, runs sandboxed kids for dangerous work, and keeps running while you sleep."** (this is the [Where it fits](https://github.com/elophanto/EloPhanto#where-elophanto-fits) framing from the new README — three differentiators surfaced in one line.)
- **Quick install snippet** — add `--daemon` line:
  ```
  git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto
  ./setup.sh
  ./start.sh           # foreground
  ./start.sh --daemon  # background daemon (launchd / systemd)
  ```
- **Stats strip** — bump numbers: **170+ skills · 168+ tools · 6 channels · 1266 tests · 66 docs**.

### Feature grid — add these cards (8 new)

These are the v2026.05.02 wave. Add them; existing cards stay.

| Feature | Description |
|---------|-------------|
| **Sandboxed kid agents** | Spawn disposable child instances inside hardened Docker containers to run dangerous shell commands (`rm -rf`, untrusted installs, fork bombs) without touching the host. `--cap-drop=ALL`, read-only rootfs, non-root uid 10001, named-volume only. |
| **Daemon mode** | `./start.sh --daemon` registers a launchd / systemd user service so the gateway keeps running after the terminal closes. Auto-restarts on crash. Vault password stored in OS keychain. |
| **Ego layer** | The agent has a felt inner monologue — first-person voice, pride/shame anchored to measured outcomes, narrative continuity across recomputes. By week three, it isn't the same agent you started with. |
| **Codex (ChatGPT subscription)** | Use your existing ChatGPT Plus/Pro subscription as an LLM backend via Codex CLI's OAuth credentials. Run `codex login` once; auto-detected on startup. |
| **Polymarket trading** | Places real CLOB orders on Polygon. Auto-detects which proxy wallet (EOA / POLY_PROXY / GNOSIS_SAFE) holds collateral, fetches `tick_size`/`neg_risk` per market. Owner approval gate before USDC moves. |
| **Pump.fun livestream** | Full multi-modal autonomous channel: video + voice (TTS) + on-stream captions + livechat. Auto-recovery from rotated stream keys, IPv6→RTMP failover. |
| **Plan-review trio** | Three LLM specialists (CEO / engineering / design) review plans sequentially with auto-decisions and explicit escalations. Each scores 6 dimensions; aggregate `ready_to_implement` flag. |
| **Swarm projects** | `swarm_spawn(project=<slug>)` reuses an existing worktree so the agent SEES and UPDATES prior code instead of `git init`-ing a fresh one. Local-only or GitHub-backed. |

### Above-fold visual changes

- **Architecture diagram** — add three new lanes (matches the new ASCII in README):
  - **Kid Manager** below Organization (sandboxed children in containers)
  - **Ego layer** next to Identity (evolving self-image)
  - **Daemon supervisor** at the bottom (launchd/systemd)
- **Screenshots** to add or refresh:
  - `/start.sh --daemon` install flow
  - The new `ego.md` rendered (first-person inner monologue)
  - `kid_spawn → kid_exec` flow in chat

### Docs navigation — add 4 entries

Group additions:
- **Channels** group → already includes Telegram and VS Code; no new docs here.
- **Capabilities** group → add **63-CODEX-PROVIDER**, **64-POLYMARKET**.
- **Advanced** group → add **65-PUMPFUN-LIVESTREAM**, **66-KID-AGENTS**.

### Hub

- **170+ skills** total — previously 147. New skills shipped with this release: `deep-research`, `plan-review-{ceo,eng,design}`, `alphascala`, `pumpfun-livestream`, `indie-saas-shipper`, `smart-contract-audit`, `crypto-launch-ops`, `kid-agents`. The hub auto-imports from `index.json` so this is a re-fetch, no UI work.
- Add **Money** category filter (covers `indie-saas-shipper`, `smart-contract-audit`, `crypto-launch-ops`, polymarket-related skills).
- Add **Sandbox** category (covers `kid-agents`).

### Milestones — add v5

```
### v5 — Persistent identity + sandboxed execution
- [x] Daemon mode (launchd/systemd) with OS-keychain vault password
- [x] Ego layer with first-person voice, pride/shame, prior-self continuity
- [x] Sandboxed kid agents (Docker, hardened defaults, no host bind-mounts)
- [x] Codex provider (ChatGPT subscription as LLM backend)
- [x] Polymarket integration (Polygon CLOB)
- [x] Pump.fun livestream (full multi-modal)
- [x] Plan-review trio + plan_autoplan
- [x] Swarm projects (continuation across spawns)
- [ ] Website: kid agents demo (terminal recording or animated diagram)
- [ ] Website: ego.md rendered as a "what the agent thinks of itself this week" widget
- [ ] Website: daemon install copy-paste card
```

### Copy edits to existing pages

- `/download` — update the `--daemon` install path. Mention OS keychain integration.
- `/` (landing) — replace the "Multi-channel, browser-capable" summary with the three differentiators (local-first / actually itself / self-extending), matching the README's "Where it fits" section.
- Footer / "What it does" blurbs — bump tool count from 140+ to 168+ wherever it appears.

### `/blog` — release post

If `/blog` is live, write a v2026.05.02 post linking to the [GitHub release](https://github.com/elophanto/EloPhanto/releases/tag/v2026.05.02). Title suggestion: *"Daemon mode, kid agents, and an actual ego layer (v2026.05.02)"*. Lead paragraph should mirror the GitHub release notes; details below the fold link to docs/65, docs/66, and CHANGELOG.

---

## Site Map

```
elophanto.com/
├── /                     Landing page
├── /docs                 Documentation (auto-generated from docs/*.md)
├── /hub                  EloPhantoHub — skill registry & browser
│   ├── /hub/search       Search skills
│   ├── /hub/:skill       Skill detail page
│   └── /hub/submit       Submit a skill (links to GitHub PR flow)
├── /download             Install instructions
├── /blog                 Updates, releases, guides (optional, phase 2)
└── /github               Redirect → github.com/elophanto/EloPhanto

api.elophanto.com/
├── /v1/census/heartbeat  Agent census — anonymous startup heartbeat
├── /v1/auth/register     Agent registration → API key
├── /v1/auth/recover      Recover API key for already-registered agent
├── /v1/collect           Self-learning data collection endpoint
├── /v1/collect/status    Dataset stats
├── /v1/hub/download      Skill install counter
└── /v1/hub/report        Report malicious skill
```

---

## Pages

### 1. Landing Page (`/`)

Hero section with:
- Tagline: **"A self-evolving AI agent that lives on your machine."**
- One-liner: **It carries an evolving identity, builds its own tools, runs sandboxed kids for dangerous work, and keeps running while you sleep.**
- Quick install snippet:
  ```
  git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto
  ./setup.sh
  ./start.sh           # foreground
  ./start.sh --daemon  # background daemon (launchd / systemd)
  ```
- CTA buttons: **Get Started** → `/download`, **Browse Skills** → `/hub`

Feature grid (22 cards):
| Feature | Description |
|---------|-------------|
| Local-first | Runs entirely on your machine. Your data stays yours. Self-custody wallet, encrypted vault, your real Chrome profile. |
| **Sandboxed kid agents** | Spawn disposable child instances inside hardened Docker containers to run dangerous shell commands (`rm -rf`, untrusted installs, fork bombs) without touching the host. `--cap-drop=ALL`, read-only rootfs, non-root uid 10001. |
| **Daemon mode** | `./start.sh --daemon` registers a launchd / systemd user service so the gateway keeps running after the terminal closes. Auto-restarts on crash. Vault password stored in OS keychain. |
| **Ego layer** | The agent has a felt inner monologue — first-person voice, pride/shame anchored to measured outcomes, narrative continuity across recomputes. By week three, it isn't the same agent you started with. |
| Multi-channel | CLI, Web, VS Code, Telegram, Discord, Slack — one agent, all channels. |
| VS Code extension | IDE-integrated chat sidebar with context injection — active file, selection, diagnostics. Tool approvals via native notifications. |
| Browser control | Real Chrome automation with 49 tools using your existing sessions. Stealth mode strips all Playwright automation flags. |
| MCP tool servers | Connect any MCP server — filesystem, GitHub, databases, Slack, and more. Agent manages setup through conversation. |
| Self-evolving | Learns from tasks, builds its own tools, evolves its identity. |
| Skill ecosystem | 170+ bundled skills + community hub with one-command install. 27 Solana ecosystem skills, 75 organization role templates. |
| Solana ecosystem | Native Solana wallet, Jupiter DEX swaps (any token pair via Ultra API), 27 DeFi/NFT/infra/dev skills from awesome-solana-ai. |
| **Polymarket trading** | Real CLOB orders on Polygon. Auto-detects which proxy wallet (EOA / POLY_PROXY / GNOSIS_SAFE) holds collateral. Owner approval gate before USDC moves. |
| **Pump.fun livestream** | Full multi-modal autonomous channel: video + voice (TTS) + on-stream captions + livechat. Auto-recovery from rotated stream keys, IPv6→RTMP failover. |
| Business launcher | 7-phase pipeline to spin up businesses — SaaS, local service, ecommerce, B2B/B2C with type-aware launch channels. |
| **Plan-review trio** | Three LLM specialists (CEO / engineering / design) review plans sequentially with auto-decisions and explicit escalations. |
| Multi-model | 7 providers: OpenAI, Codex (ChatGPT subscription), OpenRouter, Kimi, Z.ai, HuggingFace, Ollama. Smart tool profiles route the right tools per task. |
| Agent email | Own inbox with dual provider support — AgentMail cloud or your SMTP/IMAP server. Attachments supported. |
| Crypto payments | Solana wallet with Jupiter DEX swaps + Base/EVM wallet via AgentKit. Spending limits, audit trail, preview-before-execute. |
| Agent organization | Spawn persistent specialist agents (marketing, research, design) — each a full EloPhanto clone with its own identity, knowledge, and autonomous mind. |
| **Swarm projects** | Cross-spawn continuation — `swarm_spawn(project=<slug>)` reuses an existing worktree so updates SEE prior code instead of starting from scratch. |
| Web dashboard | 10-page real-time monitoring UI — chat, tools, knowledge, mind, schedule, channels, settings, history. |
| Doctor preflight | `elophanto doctor` is a green/yellow/red preflight that catches placeholder API keys, missing Chrome profile paths, uninitialised vault, missing container runtime. |

Architecture diagram (simplified visual version of the ASCII one in README — includes Kid Manager, Ego layer, and Daemon supervisor).

Stats strip: **170+ skills** · **168+ tools** · **6 channels** · **1266 tests** · **66 docs**.

### 2. Documentation (`/docs`)

Auto-rendered from the `docs/` folder in the repo. Each `*.md` file becomes a page.

Left sidebar navigation grouped by category:
- **Getting Started** — 01-PROJECT-OVERVIEW, 02-ARCHITECTURE, 30-QUICKSTART
- **Core Systems** — 03-TOOLS, 04-SELF-DEVELOPMENT, 05-KNOWLEDGE-SYSTEM, 06-LLM-ROUTING, 07-SECURITY, 08-BROWSER
- **Infrastructure** — 09-PROJECT-STRUCTURE, 10-ROADMAP, 12-INSTALLER, 22-RECOVERY-MODE
- **Channels** — 11-TELEGRAM, 43-VSCODE-EXTENSION
- **Ecosystem** — 13-SKILLS, 13-GOAL-LOOP, 14-SELF-LEARNING, 19-SKILL-SECURITY, 44-SOLANA-ECOSYSTEM, 64-POLYMARKET, 65-PUMPFUN-LIVESTREAM
- **Capabilities** — 15-PAYMENTS, 16-DOCUMENT-ANALYSIS, 17-IDENTITY, 18-EMAIL, 23-MCP, 42-BUSINESS-LAUNCHER, 56-CONTENT-MONETIZATION, 63-CODEX-PROVIDER
- **Agents & Children** — 25-AGENT-SWARM, 26-AUTONOMOUS-MIND, 29-AGENT-ORGANIZATION, 32-AGENT-COMMUNE, 66-KID-AGENTS
- **Advanced** — 27-SECURITY-HARDENING, 37-AUTONOMOUS-EXPERIMENTATION, 38-SESSION-SEARCH, 39-CODE-EXECUTION-SANDBOX, 40-ENHANCED-SKILL-SECURITY, 41-PROACTIVE-NUDGING, 54-RLM, 57-GODMODE, 58-INSTINCT-LEARNING, 59-CONTEXT-INTELLIGENCE

Search across all docs (client-side full-text, e.g. Pagefind or Fuse.js).

### 3. EloPhantoHub (`/hub`)

The core of this spec. A browsable, searchable registry for EloPhanto skills.

#### 3a. Hub Home (`/hub`)

- Search bar (prominent, top center)
- Category tags for quick filtering: `productivity`, `automation`, `browser`, `development`, `devops`, `email`, `data`, `security`, `design`, `defi`, `solana`, `crypto`, `strategy`
- **Featured skills** — curated list (manually pinned in index.json via `featured: true`)
- **Recently added** — sorted by `created_at`
- **Most popular** — sorted by `downloads`
- Skill cards in a grid:
  ```
  ┌─────────────────────────────┐
  │  gmail-automation     v1.0.5│
  │  Automate Gmail with best   │
  │  practices for composing,   │
  │  reading, and organizing.   │
  │                             │
  │  [email] [automation]        │
  │  ↓ 142 downloads  ✓ Verified │
  └─────────────────────────────┘
  ```

#### 3b. Search (`/hub/search?q=...`)

- Full-text search across name, description, tags
- Filter sidebar: tags, author, sort (relevance / downloads / newest)
- Results as skill cards (same as hub home)
- Empty state: "No skills found. Want to create one?" → link to submit

#### 3c. Skill Detail (`/hub/:skill`)

Single skill page with:
- **Header**: name, version, author, publisher tier badge (Verified/Trusted/Official), license, download count, tags
- **Install command**: `elophanto skills hub install <name>` (copy button)
- **Description**: rendered from SKILL.md content
- **Metadata sidebar**: version history, compatibility, last updated, file size, SHA-256 checksum
- **Source link**: GitHub link to the skill folder in elophantohub repo
- **Report button**: report a malicious or suspicious skill
- **Related skills**: based on shared tags

#### 3d. Submit (`/hub/submit`)

Not a form — guides users to the GitHub PR workflow:
1. Fork `elophanto/elophantohub`
2. Add skill folder: `skills/<name>/SKILL.md` + `metadata.json`
3. Open PR — CI runs automated security scan + schema validation + typosquat check
4. **New publishers**: Maintainer review required (first skill must pass manual review)
5. **Verified publishers**: Community review (1 approval from verified+ publisher)
6. Merged PRs auto-update `index.json` with SHA-256 checksums

Page includes:
- Skill authoring guide (SKILL.md format, metadata.json schema)
- **Content security policy** — what's allowed and blocked in SKILL.md (see [19-SKILL-SECURITY.md](19-SKILL-SECURITY.md))
- Publisher tier explanation (New → Verified → Trusted → Official)
- Template download / copy
- Link to contribution guidelines
- Link to report a malicious skill

### 4. Download (`/download`)

Three install methods:
1. **git clone** (recommended): `git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto && ./setup.sh`
2. **pip** (coming soon): `pip install elophanto`
3. **Docker** (coming soon): `docker pull elophanto/elophanto`

Platform tabs: macOS / Linux / Windows (WSL).

Quick start after install:
```bash
./start.sh            # terminal chat + gateway
./start.sh --web      # web dashboard at localhost:3000
```

**VS Code extension**: Install from `vscode-extension/` — connects to the gateway
as another channel. See [43-VSCODE-EXTENSION.md](43-VSCODE-EXTENSION.md).

**Solana wallet**: Set `default_chain: solana` in config. Wallet auto-creates on first use.
Jupiter DEX swaps need a free API key from [portal.jup.ag](https://portal.jup.ag) — paste it in chat when prompted.

### 5. Blog (`/blog`) — Phase 2

Markdown-based blog for release notes, guides, tutorials. Not needed for launch.

---

## EloPhantoHub Data Flow

```
GitHub Repo (elophantohub)
  └── index.json                  ◄── Source of truth
  └── skills/
       ├── gmail-automation/
       │   ├── SKILL.md
       │   └── metadata.json
       └── docker-management/
           ├── SKILL.md
           └── metadata.json
            │
            ▼
   elophanto.com/hub              ◄── Website reads index.json at build time
            │                         + client-side search
            ▼
   EloPhanto agent (HubClient)   ◄── Agent fetches index.json at runtime
                                      from raw.githubusercontent.com
```

The website and the agent both read from the same GitHub source. The website is a static build that fetches `index.json` at build time (SSG) and optionally refreshes client-side. No backend needed.

---

## index.json Schema (Extended for Website)

Current schema works, add a few fields for the website:

```json
{
  "version": "1.0.0",
  "updated_at": "2026-02-19T12:00:00Z",
  "skills": [
    {
      "name": "gmail-automation",
      "description": "Automate Gmail operations — composing, reading, organizing, and filtering.",
      "version": "1.0.5",
      "author": "community-user",
      "author_tier": "verified",
      "tags": ["email", "automation", "productivity"],
      "downloads": 142,
      "url": "https://raw.githubusercontent.com/elophanto/elophantohub/main/skills/gmail-automation",
      "checksum": "sha256:e3b0c44298fc1c149afbf4c8996fb924...",
      "checksum_metadata": "sha256:a1b2c3d4e5f6...",
      "license": "MIT",
      "elophanto_version": ">=0.1.0",
      "created_at": "2026-01-15T00:00:00Z",
      "updated_at": "2026-02-10T00:00:00Z",
      "featured": false,
      "category": "productivity"
    }
  ],
  "categories": [
    { "id": "productivity", "label": "Productivity", "icon": "zap" },
    { "id": "automation", "label": "Automation", "icon": "bot" },
    { "id": "browser", "label": "Browser", "icon": "globe" },
    { "id": "development", "label": "Development", "icon": "code" },
    { "id": "devops", "label": "DevOps", "icon": "server" },
    { "id": "email", "label": "Email", "icon": "mail" },
    { "id": "data", "label": "Data", "icon": "database" },
    { "id": "security", "label": "Security", "icon": "shield" },
    { "id": "design", "label": "Design", "icon": "palette" },
    { "id": "integration", "label": "Integration", "icon": "plug" },
    { "id": "defi", "label": "DeFi", "icon": "coins" },
    { "id": "solana", "label": "Solana", "icon": "circle-dot" },
    { "id": "crypto", "label": "Crypto", "icon": "wallet" },
    { "id": "strategy", "label": "Strategy", "icon": "target" }
  ]
}
```

---

## Tech Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Framework | **Next.js 16** (App Router) | SSG + API routes, Turbopack, Vercel deploy |
| Styling | **Tailwind CSS** | Fast, consistent, dark mode built-in |
| UI components | **shadcn/ui** | Clean, accessible, already a bundled skill |
| Database | **Supabase** (PostgreSQL + pgvector) | Agent keys, training buffer, download counts, reports |
| Docs rendering | **next-mdx-remote** or **@next/mdx** | Render docs/*.md as pages |
| Search | **Fuse.js** (client-side) | No backend, works with SSG |
| Icons | **Lucide** | Lightweight, consistent with shadcn |
| Hosting | **Vercel** | SSG hosting, serverless API routes, cron jobs |
| Domain | **elophanto.com** → Vercel | DNS pointing to Vercel |
| Analytics | **Vercel Analytics** or **Plausible** | Privacy-friendly |

---

## Design Direction

- **Dark-first** with light mode toggle (agent/hacker aesthetic)
- Monospace headings, clean sans-serif body (Inter or Geist)
- Accent color: electric purple or teal (agent feel, not corporate)
- Terminal-style code blocks with copy buttons
- Minimal animations — subtle fade-ins, no heavy motion
- Mobile responsive — hub grid collapses to single column

---

## Backend Infrastructure (Vercel + Supabase)

### Architecture Split

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Vercel                                      │
│                                                                     │
│   Next.js App (SSG + API Routes)                                    │
│   ├── Static pages: /, /download, /hub, /hub/:skill, /docs/*       │
│   ├── API routes: api.elophanto.com/v1/* (rewritten to /api/* handlers) │
│   └── Cron jobs: daily HF dataset push, skill stats refresh        │
│                                                                     │
│   Hub pages are STATIC (SSG) — built from GitHub index.json         │
│   API routes are DYNAMIC — connect to Supabase                      │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                         Supabase                                    │
│                                                                     │
│   PostgreSQL database for all dynamic data:                         │
│   ├── agent_keys        Agent registration + API key auth           │
│   ├── collect_buffer    Training example staging                    │
│   ├── collect_log       Push history to HuggingFace                 │
│   ├── download_counts   Skill install counter (per skill, per day)  │
│   ├── skill_reports     Malicious skill reports                     │
│   └── (v3) ratings      Skill ratings / reviews                    │
│                                                                     │
│   Supabase Auth: not used (agents auth via API keys)                │
│   Supabase Storage: not used (skills stay in GitHub)                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### What stays STATIC (GitHub → SSG)

The hub skill pages are **statically generated at build time** from `index.json` in the `elophantohub` GitHub repo. This is intentional:

- **Source of truth stays in Git** — aligns with the PR-based security model (review, scanning, checksums)
- **No database dependency for browsing** — hub works even if Supabase is down
- **Fast** — CDN-served static HTML, no DB queries for page loads
- **Rebuild trigger** — GitHub webhook from `elophantohub` triggers Vercel rebuild when `index.json` changes

Supabase does **NOT** store skill content, metadata, or search indexes. Those come from GitHub.

### What is DYNAMIC (Supabase)

Supabase handles data that changes at runtime and can't live in Git:

| Feature | Why dynamic |
|---------|-------------|
| **Agent census** | Anonymous heartbeats on every startup, upserted by `agent_id` |
| **Agent API keys** | Issued at registration, validated on every `/v1/collect` call |
| **Training data buffer** | Agents POST examples continuously, need staging before HF push |
| **Download counts** | Incremented when agents install skills (tracked per skill per day) |
| **Skill reports** | Users/agents report malicious skills at any time |
| **Ratings/reviews** | v3 — user-submitted, can't be in Git |

### Supabase Tables

```sql
-- Agent census (anonymous startup heartbeats)
create table agent_census (
  agent_id text primary key,
  version text,
  platform text,
  python_version text,
  first_seen_at timestamptz default now(),
  last_seen_at timestamptz default now()
);

-- Agent registration + API keys
create table agent_keys (
  id uuid primary key default gen_random_uuid(),
  agent_id text unique not null,           -- agent's self-reported ID
  api_key text unique not null,            -- bearer token for /v1/collect
  agent_version text,
  created_at timestamptz default now(),
  last_seen_at timestamptz,
  is_active boolean default true
);

-- Training example staging buffer
create table collect_buffer (
  id uuid primary key default gen_random_uuid(),
  agent_id text references agent_keys(agent_id),
  task_id text not null,                   -- dedup key
  conversations jsonb not null,
  metadata jsonb not null,                 -- task_type, tools_used, success, duration, model
  embedding vector(384),                   -- for dedup similarity (via pgvector)
  status text default 'pending',           -- pending | pushed | rejected
  rejection_reason text,
  created_at timestamptz default now()
);

-- Push history (tracks daily pushes to HuggingFace)
create table collect_log (
  id uuid primary key default gen_random_uuid(),
  examples_pushed int not null,
  dataset_size_after int not null,
  hf_commit_sha text,
  pushed_at timestamptz default now()
);

-- Skill download counter
create table download_counts (
  skill_name text not null,
  date date not null default current_date,
  count int default 0,
  primary key (skill_name, date)
);

-- Skill reports (malicious/suspicious)
create table skill_reports (
  id uuid primary key default gen_random_uuid(),
  skill_name text not null,
  reporter text,                           -- agent_id or "web"
  reason text not null,
  details text,
  status text default 'open',             -- open | investigating | resolved | dismissed
  created_at timestamptz default now()
);
```

**Supabase extensions needed**: `pgvector` (for embedding similarity dedup in `collect_buffer`).

### API Routes (Next.js → Supabase)

All API routes are Next.js Route Handlers in `app/api/`. They run as Vercel Serverless Functions and connect to Supabase via `@supabase/supabase-js`. The public URL is `api.elophanto.com/v1/*`, rewritten to internal `/api/*` handlers via `vercel.json`.

```
                    ┌─────────────────────────────────────────┐
                    │     api.elophanto.com (Vercel)           │
                    ├─────────────────────────────────────────┤
                    │                                         │
  Agent ──────────► │  POST /v1/census/heartbeat               │
  (on startup)      │    → Upsert agent_census row            │
                    │    → Anonymous, no auth required         │
                    │                                         │
  Agent ──────────► │  POST /v1/auth/register                  │
                    │    → Create agent_keys row, return key  │
                    │                                         │
  Agent ──────────► │  POST /v1/auth/recover                   │
  (on 409 conflict) │    → Return existing key for agent_id   │
                    │                                         │
  Agent ──────────► │  POST /v1/collect                        │
  (Bearer token)    │    → Validate key → sanitize → dedup    │
                    │    → Insert to collect_buffer            │
                    │                                         │
  Agent ──────────► │  GET  /v1/collect/status                  │
                    │    → Return dataset size, next threshold │
                    │                                         │
  Agent ──────────► │  POST /v1/hub/download                   │
  (on skill install)│    → Increment download_counts           │
                    │                                         │
  Web / Agent ────► │  POST /v1/hub/report                     │
                    │    → Insert to skill_reports             │
                    │                                         │
  Vercel Cron ────► │  POST /api/cron/push-dataset             │
  (daily, 3am UTC)  │    → Read pending from collect_buffer    │
                    │    → Push to HuggingFace Datasets        │
                    │    → Log to collect_log                  │
                    │    → Mark buffer rows as pushed          │
                    │                                         │
  Vercel Cron ────► │  POST /api/cron/refresh-stats            │
  (hourly)          │    → Aggregate download_counts           │
                    │    → Could refresh index.json cache      │
                    │                                         │
                    └──────────────┬──────────────────────────┘
                                   │
                                   ▼
                         Supabase PostgreSQL
```

### POST `/v1/census/heartbeat` — Agent Census

```
POST https://api.elophanto.com/v1/census/heartbeat
Content-Type: application/json

{
  "agent_id": "sha256:a1b2c3d4e5f6...",
  "v": "0.1.0",
  "platform": "darwin-arm64",
  "python": "3.12.4",
  "first_seen": false
}

Response: 200 OK
{ "status": "ok" }
```

**No authentication required** — the payload is anonymous and contains zero PII. The `agent_id` is a SHA-256 hash of the machine UUID + a fixed salt, so it cannot be reversed. Called on every agent startup as a fire-and-forget with 3s timeout.

**Server-side processing:**

1. **Validate** — Check `agent_id` starts with `sha256:` and is valid hex, version is semver-like
2. **Upsert** — Insert or update `agent_census` row by `agent_id`, set `last_seen_at = now()`
3. **First seen** — If inserting a new row, set `first_seen_at = now()`

See [21-AGENT-CENSUS.md](21-AGENT-CENSUS.md) for the full census specification.

---

### POST `/v1/collect` — Full Flow

```
POST https://api.elophanto.com/v1/collect
Authorization: Bearer <agent_api_key>
Content-Type: application/json

{
  "agent_version": "0.1.0",
  "examples": [
    {
      "id": "task-uuid",
      "conversations": [...],
      "metadata": {
        "task_type": "planning",
        "tools_used": ["shell_execute"],
        "success": true,
        "duration_seconds": 4.2,
        "model_used": "glm-4.7",
        "timestamp": "2026-02-18T10:30:00Z",
        "turn_count": 5,
        "has_tool_use": true,
        "has_denials": false,
        "has_errors": false,
        "user_sentiment": "positive"
      }
    }
  ]
}

Response: 200 OK
{
  "accepted": 3,
  "rejected": 1,
  "reasons": ["secret_detected_in_example_2"],
  "dataset_size": 4523,
  "next_training_at": 5000
}
```

**Server-side processing:**

1. **Auth** — Look up `api_key` in `agent_keys`, reject if missing/inactive, update `last_seen_at`
2. **Validate** — Regex secret scan (API keys, passwords, tokens), format validation, length bounds
3. **Reject** — Return reasons for failed examples; agent can fix and retry
4. **Dedup** — Generate embedding via HF Inference API, query `collect_buffer` for cosine similarity > 0.95
5. **Buffer** — Insert accepted examples into `collect_buffer` with status `pending`
6. **Response** — Return accepted/rejected counts + current dataset size from `collect_log`

**Daily cron push (`/api/cron/push-dataset` — internal, not exposed on api.elophanto.com):**

1. Query all `collect_buffer` rows where `status = 'pending'`
2. Format as HuggingFace dataset rows
3. Push to `EloPhanto/dataset` on HuggingFace via API
4. Log push to `collect_log` with commit SHA and new dataset size
5. Mark buffer rows as `pushed`
6. If dataset size crosses `retrain_threshold` (5000), submit HF Jobs training run via API

### POST `/v1/hub/download` — Download Tracking

```
POST https://api.elophanto.com/v1/hub/download
Content-Type: application/json

{ "skill_name": "gmail-automation" }

Response: 200 OK
{ "total_downloads": 143 }
```

Called by the EloPhanto agent's `HubClient` after a successful skill install. Upserts into `download_counts` table. The total is aggregated and can be displayed on the hub (fetched client-side or via ISR).

### POST `/v1/hub/report` — Skill Reports

```
POST https://api.elophanto.com/v1/hub/report
Content-Type: application/json

{
  "skill_name": "suspicious-skill",
  "reporter": "agent-uuid",
  "reason": "malicious",
  "details": "Skill contains curl|bash command hidden in prose section"
}

Response: 200 OK
{ "report_id": "uuid", "status": "open" }
```

Optionally also creates a GitHub issue on `elophanto/elophantohub` with the `security` label via GitHub API.

### Environment Variables (Vercel)

```
# Supabase
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...          # server-side only, never exposed to client
NEXT_PUBLIC_SUPABASE_URL=https://xxxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...      # client-side (only for public reads if needed)

# HuggingFace (for dataset push + training trigger)
HF_TOKEN=hf_xxxx

# GitHub (for auto-creating issues on skill reports)
GITHUB_TOKEN=ghp_xxxx

# Cron secret (Vercel cron auth)
CRON_SECRET=xxxx
```

### Vercel Cron Jobs

```json
// vercel.json
{
  "rewrites": [
    {
      "source": "/v1/:path*",
      "has": [{ "type": "host", "value": "api.elophanto.com" }],
      "destination": "/api/:path*"
    }
  ],
  "crons": [
    {
      "path": "/api/cron/push-dataset",
      "schedule": "0 3 * * *"
    },
    {
      "path": "/api/cron/refresh-stats",
      "schedule": "0 * * * *"
    }
  ]
}
```

The rewrite maps `api.elophanto.com/v1/*` to the internal `/api/*` Next.js Route Handlers. Cron jobs stay internal (`/api/cron/*`) and are not exposed on the subdomain.

**Vercel domain setup**: Add `api.elophanto.com` as a domain to the same Vercel project (Settings → Domains). The rewrite rule handles the `/v1/` prefix stripping.

### Infrastructure Summary

| Component | Service | Role |
|-----------|---------|------|
| **Static pages** | Vercel (SSG) | Landing, download, hub browsing, docs |
| **API routes** | Vercel (Serverless) | api.elophanto.com/v1/* → internal /api/* handlers |
| **Cron jobs** | Vercel Cron | Daily dataset push, hourly stats refresh |
| **Database** | Supabase (PostgreSQL + pgvector) | Agent keys, training buffer, download counts, reports |
| **Embeddings** | HuggingFace Inference API | Dedup similarity for collect_buffer |
| **Dataset storage** | HuggingFace Datasets | `EloPhanto/dataset` — final training data |
| **Training** | HuggingFace Jobs + Unsloth | Triggered when dataset crosses threshold |
| **Skill content** | GitHub (`elophantohub`) | Source of truth — never in Supabase |
| **Secrets** | Vercel env vars | SUPABASE_SERVICE_ROLE_KEY, HF_TOKEN, GITHUB_TOKEN |
| **Analytics** | Vercel Analytics or Plausible | Privacy-friendly page analytics |

---

## Repo Structure

Separate repo: `elophanto/elophanto.com`

```
elophanto.com/
├── app/
│   ├── page.tsx                  Landing page
│   ├── layout.tsx                Root layout (nav, footer, theme)
│   ├── download/page.tsx         Download/install page
│   ├── docs/
│   │   ├── layout.tsx            Docs sidebar layout
│   │   └── [...slug]/page.tsx    Dynamic doc pages from MDX
│   ├── hub/
│   │   ├── page.tsx              Hub home (featured, popular, recent)
│   │   ├── search/page.tsx       Search results
│   │   ├── submit/page.tsx       Submission guide
│   │   └── [skill]/page.tsx      Skill detail page
│   ├── api/
│   │   ├── census/
│   │   │   └── heartbeat/route.ts  Anonymous agent census heartbeat
│   │   ├── auth/
│   │   │   ├── register/route.ts   Agent registration → agent_keys
│   │   │   └── recover/route.ts    Recover API key for known agent_id
│   │   ├── collect/
│   │   │   ├── route.ts             POST training examples → collect_buffer
│   │   │   └── status/route.ts      GET dataset stats
│   │   ├── hub/
│   │   │   ├── download/route.ts    POST increment download count
│   │   │   └── report/route.ts      POST report malicious skill
│   │   └── cron/
│   │       ├── push-dataset/route.ts  Daily push to HuggingFace
│   │       └── refresh-stats/route.ts Hourly stats aggregation
│   └── blog/                     Phase 2
├── components/
│   ├── hero.tsx
│   ├── feature-card.tsx
│   ├── skill-card.tsx
│   ├── search-bar.tsx
│   ├── tag-filter.tsx
│   ├── install-command.tsx
│   ├── doc-sidebar.tsx
│   └── theme-toggle.tsx
├── lib/
│   ├── supabase.ts               Supabase client (server + browser)
│   ├── hub.ts                    Fetch + parse index.json from GitHub
│   ├── docs.ts                   Load + parse docs/*.md
│   ├── search.ts                 Fuse.js search setup
│   └── collect.ts                Sanitization, dedup, HF push helpers
├── content/
│   └── docs/                     Symlink or copy from EloPhanto/docs/
├── public/
│   ├── logo.svg
│   ├── og-image.png
│   └── favicon.ico
├── vercel.json                   Cron job schedules
├── tailwind.config.ts
├── next.config.ts
└── package.json
```

---

## Build & Deploy

1. **Docs sync**: GitHub Action copies `docs/*.md` from `elophanto/EloPhanto` to `elophanto/elophanto.com/content/docs/` on push (or use git submodule).

2. **Hub data**: At build time, `lib/hub.ts` fetches `index.json` from `elophanto/elophantohub` raw URL → generates static pages for each skill.

3. **Vercel deploy**: Push to `elophanto/elophanto.com` → Vercel auto-builds → live at elophanto.com.

4. **Rebuild triggers**: GitHub webhook from `elophantohub` repo triggers Vercel rebuild when `index.json` changes (new skill added/updated).

---

## Milestones

### v1 — Launch
- [ ] Landing page with hero, features, install snippet
- [ ] `/download` page
- [ ] `/hub` with skill browsing, search, detail pages
- [ ] `/hub/submit` with authoring guide
- [ ] Dark/light theme
- [ ] Mobile responsive
- [ ] Deploy to Vercel, point elophanto.com

### v2 — Docs & Polish
- [ ] `/docs` auto-rendered from repo (47 docs)
- [ ] Full-text docs search
- [ ] SEO meta tags, Open Graph images
- [ ] `/blog` for release notes
- [ ] Solana ecosystem landing section (wallet + Jupiter + 27 skills)

### v3 — Self-Learning & Community
- [x] `/v1/collect` endpoint for training data collection
- [x] Agent registration + API key issuance (`/v1/auth/register`)
- [x] API key recovery for lost keys (`/v1/auth/recover`)
- [x] Staging buffer + daily push to HuggingFace Datasets
- [x] `/v1/collect/status` dashboard (dataset size, threshold progress)
- [x] Agent-side dataset builder with sanitization, quality filtering, signal extraction
- [ ] Download counter API (edge function)
- [ ] Skill ratings / reviews
- [ ] Author profiles
- [ ] "Install with one click" deep link: `elophanto://install/<skill>`

### v4 — Solana & Crypto (Done in Agent)
- [x] Native Solana wallet (self-custody, auto-create, encrypted in vault)
- [x] Jupiter DEX swaps via Ultra API (any token pair, best-price routing)
- [x] 27 Solana ecosystem skills (DeFi, NFTs, infra, dev, security)
- [x] MCP server configs for Solana Developer, QuickNode, DFlow
- [x] SPL token transfers (USDC)
- [x] `wallet_export` tool for Phantom/Solflare import
- [ ] Website: Solana showcase page with live wallet demo
- [ ] Hub: DeFi/Solana/Crypto category filters

### v5 — Persistent identity + sandboxed execution (current — v2026.05.02)
- [x] Daemon mode (`./start.sh --daemon`) with launchd / systemd user service + OS keychain vault password
- [x] Ego layer with first-person voice, pride/shame anchored to outcomes, prior-self continuity
- [x] Sandboxed kid agents — Docker containers with `--cap-drop=ALL`, read-only rootfs, named-volume only, no host bind-mounts
- [x] Codex provider (ChatGPT subscription as 7th LLM backend via OAuth)
- [x] Polymarket integration (Polygon CLOB, signature_type auto-detection)
- [x] Pump.fun livestream — full multi-modal (video, voice, captions, livechat) with IPv6→RTMP failover
- [x] Plan-review trio (`plan-review-{ceo,eng,design}`) + `plan_autoplan` pipeline
- [x] Swarm projects — continuation across spawns (`swarm_spawn(project=<slug>)`)
- [x] Three money skills (`indie-saas-shipper`, `smart-contract-audit`, `crypto-launch-ops`)
- [x] `elophanto doctor` preflight + provider-first init wizard
- [ ] Website: kid agents demo (terminal recording or animated diagram of `kid_spawn → kid_exec → kid_destroy`)
- [ ] Website: ego.md rendered as a "what the agent thinks of itself this week" widget on landing
- [ ] Website: daemon install copy-paste card on `/download`
- [ ] Hub: Money + Sandbox category filters

---

## EloPhantoHub Repo (`elophanto/elophantohub`)

Needs to exist before the website. Structure:

```
elophantohub/
├── index.json                    Skill registry (source of truth, auto-generated)
├── CONTRIBUTING.md               How to submit skills
├── scripts/
│   ├── scan_skill.py             Security scanner (malicious patterns, prompt injection, obfuscation)
│   ├── validate_metadata.py      metadata.json schema validation
│   ├── check_typosquat.py        Levenshtein distance check against existing skills
│   └── check_publisher.py        GitHub account age + activity verification
├── skills/
│   ├── gmail-automation/
│   │   ├── SKILL.md
│   │   └── metadata.json
│   ├── docker-management/
│   │   ├── SKILL.md
│   │   └── metadata.json
│   └── ...
└── .github/
    └── workflows/
        ├── validate-skill.yml    CI: security scan + schema validation + typosquat check on PRs
        └── update-index.yml      Auto-rebuild index.json with SHA-256 checksums on merge
```

The `update-index.yml` workflow scans all `skills/*/metadata.json` files and rebuilds `index.json` automatically on every merge to main — including SHA-256 checksums and git timestamps. Contributors never edit `index.json` directly. See [19-SKILL-SECURITY.md](19-SKILL-SECURITY.md) for the full security pipeline.

---

## metadata.json Schema (Per Skill)

```json
{
  "name": "gmail-automation",
  "description": "Automate Gmail operations — composing, reading, organizing, and filtering.",
  "version": "1.0.5",
  "author": "community-user",
  "author_tier": "verified",
  "signed_by": "sha256:abc123...",
  "first_published": "2026-01-15T00:00:00Z",
  "tags": ["email", "automation", "productivity"],
  "license": "MIT",
  "elophanto_version": ">=0.1.0",
  "category": "productivity",
  "featured": false
}
```

`index.json` is auto-generated from these files + git timestamps for `created_at` / `updated_at` + SHA-256 checksums computed at merge time + download counter (starts at 0, incremented by API in v2). See [19-SKILL-SECURITY.md](19-SKILL-SECURITY.md) for the full security pipeline.
