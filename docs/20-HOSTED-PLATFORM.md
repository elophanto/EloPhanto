# EloPhanto — Hosted Platform & Desktop App

> **Status: Spec** — Hybrid distribution strategy: desktop app (free, local-first) + cloud instances (pro, always-on) at elophanto.com.

## Context

EloPhanto has 16 phases implemented: 90+ tools, browser automation, 4 channel adapters, skills marketplace with security, crypto payments, email, identity, document analysis, and an autonomous goal loop. The open-source repo is feature-rich but requires Python 3.12+, Node.js, and terminal comfort to run.

The problem: **most potential users will never self-host**. Open source captures developers, but the real market is anyone who wants a personal AI agent. A hosted version removes the installation barrier entirely while keeping the local-first option for developers and privacy-conscious users.

### Market Reality

- Open source AI agent tools are proliferating — dev mindshare is fragmented
- Self-hosting limits adoption to technical users
- Always-on agents (Telegram/Discord/Slack bots, scheduled tasks) require a running machine — most users don't have a server
- Hosted = recurring revenue, which funds continued development
- Desktop app = zero hosting cost for free tier, builds install base

## Strategy: Hybrid Model

Two distribution channels, one product:

```
┌─────────────────────────────────────────────────────────────┐
│                     elophanto.com                            │
├──────────────────────┬──────────────────────────────────────┤
│                      │                                       │
│   DESKTOP APP        │   CLOUD PLATFORM                     │
│   (Free)             │   (Pro — $X/month)                   │
│                      │                                       │
│   Download & run     │   Sign up → get your own agent       │
│   Everything local   │   Always-on 24/7                     │
│   Your machine       │   Isolated container per user        │
│   Your data          │   Web dashboard                      │
│   Works offline      │   All channels always connected      │
│   Channels need      │   Scheduled tasks run unattended     │
│     app running      │   Automatic updates                  │
│                      │                                       │
│   Tauri (Rust+Web)   │   Fly.io Machines                   │
│   Mac / Windows /    │   Supabase Auth                      │
│     Linux            │   Stripe Billing                     │
│                      │                                       │
├──────────────────────┴──────────────────────────────────────┤
│   Same agent core · Same web UI · Same gateway protocol     │
│   Export/import between local ↔ cloud                        │
└─────────────────────────────────────────────────────────────┘
```

**Why this wins on all three axes:**

| Criterion | Desktop App | Cloud Platform |
|-----------|-------------|---------------|
| **Adoption** | Zero friction for developers — download, run, done | Zero friction for everyone else — sign up, configure, go |
| **Security** | Best possible — everything stays on your machine | Per-user container isolation — own vault, own data, own network |
| **Scalability** | Costs us nothing — users provide their own compute | Pay-per-user — only paying subscribers use cloud resources |

---

## Desktop App

### Technology: Tauri

Tauri over Electron because:
- **~10x smaller** binary (Tauri ~15MB vs Electron ~150MB)
- **Rust backend** — native performance, better security sandbox
- Uses system webview instead of bundled Chromium
- Better memory footprint for an always-running agent

### Architecture

```
┌──────────────────────────────────────────────┐
│              Tauri App Shell                  │
│  ┌─────────────────────────────────────────┐ │
│  │          Web Dashboard (React)          │ │ ← System webview
│  │  Chat · Tools · Skills · Settings       │ │
│  └──────────────┬──────────────────────────┘ │
│                 │ WebSocket (ws://127.0.0.1)  │
│  ┌──────────────┴──────────────────────────┐ │
│  │        EloPhanto Gateway                │ │
│  │  Agent · Tools · Vault · Knowledge      │ │ ← Python subprocess
│  │  Browser Bridge (Node.js subprocess)    │ │
│  └─────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────┐ │
│  │  Tauri Rust Backend (process manager)   │ │ ← Manages Python + Node.js
│  └─────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘
```

The Tauri Rust backend:
1. Bundles a Python virtual environment (or uses system Python)
2. Starts the EloPhanto gateway as a subprocess
3. Starts the browser bridge as a subprocess
4. Serves the web dashboard via system webview
5. Dashboard connects to gateway via WebSocket (same protocol as CLI adapter)
6. Manages lifecycle: auto-start on login, graceful shutdown, crash recovery

### Bundled Dependencies

| Component | Bundling Strategy |
|-----------|------------------|
| Python 3.12+ | Embedded Python (PyInstaller-style) or require system Python |
| EloPhanto core | Bundled in app resources |
| Node.js | Embedded Node binary for browser bridge |
| uv | Bundled for dependency management |
| Browser bridge | Pre-built `node_modules/` in app resources |
| Skills | Bundled 30 skills in app resources |

### Desktop-Specific Features

- **System tray** — agent runs in background, tray icon shows status
- **Notifications** — native OS notifications for task completions, approvals needed
- **Auto-start** — optional launch on login
- **Global hotkey** — quick-invoke agent from anywhere (e.g., `Ctrl+Space`)
- **File drag-and-drop** — drop files into chat for document analysis
- **Menu bar quick actions** — schedule task, open chat, view history

### Desktop Installer Matrix

| Platform | Format | Distribution |
|----------|--------|-------------|
| macOS | `.dmg` | elophanto.com + `brew install --cask elophanto` |
| Windows | `.msi` | elophanto.com + `winget install elophanto` |
| Linux | `.AppImage` + `.deb` | elophanto.com + package repos |

---

## Cloud Platform

### Per-User Instance Model

Each paying user gets their own isolated EloPhanto container. This is not multi-tenant — each container is a full EloPhanto installation with its own:

- Agent core + all tools
- Encrypted vault (user's own encryption key)
- Knowledge base
- Skills library
- SQLite databases (memory, sessions, tasks, payments)
- Browser bridge (full Chrome with real profile)
- Channel adapter connections
- Config

```
                    ┌────────────────────────┐
                    │   app.elophanto.com     │
                    │   (Web Dashboard)       │
                    │   Supabase Auth         │
                    │   Stripe Billing        │
                    └──────────┬─────────────┘
                               │
                    ┌──────────┴─────────────┐
                    │    Fly.io Proxy         │
                    │    Route by user_id     │
                    └──────────┬─────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                     │
  ┌───────┴────────┐  ┌───────┴────────┐  ┌────────┴───────┐
  │ User A Machine │  │ User B Machine │  │ User C Machine │
  │                │  │                │  │                │
  │ EloPhanto      │  │ EloPhanto      │  │ EloPhanto      │
  │ Gateway :18789 │  │ Gateway :18789 │  │ Gateway :18789 │
  │ Own vault      │  │ Own vault      │  │ Own vault      │
  │ Own knowledge  │  │ Own knowledge  │  │ Own knowledge  │
  │ Own skills     │  │ Own skills     │  │ Own skills     │
  │ Own browser    │  │ Own browser    │  │ Own browser    │
  │ Telegram bot   │  │ Discord bot    │  │ Slack bot      │
  └────────────────┘  └────────────────┘  └────────────────┘
       Fly Machine         Fly Machine         Fly Machine
```

### Why Per-User Containers (Not Multi-Tenant)

EloPhanto agents run shell commands, access the filesystem, control a browser, and hold encrypted credentials. Multi-tenant isolation for this workload is extremely difficult:

| Concern | Multi-Tenant Risk | Per-Container Solution |
|---------|-------------------|----------------------|
| Shell execution | User A's agent could access User B's files | Each container has its own filesystem |
| Vault credentials | Shared encryption = shared risk | Own vault, own encryption key |
| Browser sessions | Shared browser = cookie leakage risk | Own Chrome instance with real profile |
| Resource exhaustion | One user's heavy task starves others | Per-container CPU/memory limits |
| Security breach | Compromised agent exposes all users | Blast radius = one user |

The cost premium of per-container vs multi-tenant is worth the security guarantee.

### Infrastructure: Fly.io Machines

Fly.io Machines are ideal because:
- **Start/stop on demand** — machines can hibernate when idle, wake on request (saves ~70% vs always-on)
- **Per-machine isolation** — each is a microVM with its own kernel
- **Persistent volumes** — attach storage for knowledge/vault/database
- **Global regions** — deploy close to user's primary channel (Telegram servers in Europe, etc.)
- **Simple API** — create, start, stop, destroy machines programmatically

#### Machine Spec per User

| Resource | Allocation | Notes |
|----------|-----------|-------|
| CPU | 1 shared vCPU | Scales to 2 on burst |
| RAM | 512MB | 1GB for browser-heavy users |
| Storage | 1GB persistent volume | Expandable |
| Network | Private IPv6 + Fly proxy | No public IP exposed |
| Browser | Full Chrome (new headless) | Real browser engine with profile, cookies, sessions |

#### Cost Estimate per User

| State | Cost/Month | Notes |
|-------|-----------|-------|
| Active (24/7) | ~$5-7 | 1 shared CPU, 512MB, 1GB vol |
| Hibernating (wake on request) | ~$1-2 | Storage only when stopped |
| Blended (active 8h/day avg) | ~$3-4 | Typical usage pattern |

### Machine Lifecycle

```
User signs up
    │
    ▼
Provision Machine (Fly API)
    ├── Create machine with EloPhanto Docker image
    ├── Attach persistent volume
    ├── Set env vars (auth token, user config)
    ├── Initialize vault with user's encryption key
    └── Start gateway
    │
    ▼
Machine Running
    ├── Gateway accepts WebSocket connections
    ├── Web dashboard connects via proxy
    ├── Channel adapters connect (Telegram, Discord, Slack)
    ├── Scheduled tasks run
    └── Auto-hibernate after inactivity timeout (configurable)
    │
    ▼
Machine Hibernated (cost saving)
    ├── Persistent volume retained
    ├── No CPU/RAM charges
    └── Wake on: web dashboard visit, incoming Telegram message, scheduled task
    │
    ▼
Machine Destroyed (account deleted / churned)
    ├── Export offered before deletion
    ├── 30-day grace period
    └── Volume destroyed after grace period
```

### Wake-on-Request

For hibernated machines to respond to incoming Telegram/Discord messages:

1. **Webhook mode** for Telegram (instead of polling) — Fly proxy receives webhook, wakes machine
2. **Gateway proxy service** — lightweight always-on service that holds channel connections and buffers messages, wakes user's machine on incoming message
3. **Scheduled wake** — machine wakes 1 min before scheduled tasks, hibernates after completion

Option 2 is the most reliable:

```
┌──────────────────────┐
│ Gateway Proxy (shared)│ ← Always running, lightweight
│                       │
│ Telegram webhooks ────┤
│ Discord gateway ──────┤──→ Buffer message
│ Slack events ─────────┤──→ Wake user's Fly Machine
│                       │──→ Forward message to gateway
│ Scheduled task timer ─┤──→ Wake machine at scheduled time
└──────────────────────┘
```

---

## Web Dashboard

The web dashboard is the **same React app** for both desktop and cloud. It connects to the agent via WebSocket gateway protocol.

### Pages

| Page | Description |
|------|-------------|
| **Chat** | Main conversation interface. Send messages, view responses, approve/deny tool calls. File upload for document analysis. |
| **Tools** | Browse 90+ tools by category. View execution history, success rates. Enable/disable tools. |
| **Skills** | Manage installed skills. Browse EloPhantoHub. Install/remove skills. View security warnings. |
| **Knowledge** | Browse knowledge base. Search with semantic matching. Add/edit/delete entries. |
| **Schedule** | View scheduled tasks. Create new schedules with natural language. Enable/disable. View run history. |
| **Channels** | Configure Telegram/Discord/Slack. Connection status. Per-channel settings. |
| **Settings** | Permission mode, LLM providers, browser settings, vault management, identity config. |
| **History** | Full task execution history. Filter by date, tool, status. Replay conversations. |
| **Billing** | (Cloud only) Subscription management, usage stats, LLM cost tracking. |

### Tech Stack

| Component | Technology |
|-----------|-----------|
| Framework | React 19 + TypeScript |
| Styling | Tailwind CSS + shadcn/ui |
| State | Zustand (lightweight, fits agent state model) |
| WebSocket | Native WebSocket (gateway protocol) |
| Build | Vite (fast, good Tauri integration) |
| Desktop | Tauri webview serves the same build |
| Cloud | Deployed to Vercel (static) or served from Fly proxy |

### Gateway Protocol Integration

The dashboard uses the existing gateway protocol — no new API needed:

```typescript
// Connect to agent gateway
const ws = new WebSocket('ws://localhost:18789');  // Desktop
// or
const ws = new WebSocket('wss://app.elophanto.com/agent/ws');  // Cloud (proxied)

// Send chat message
ws.send(JSON.stringify({
  type: 'chat',
  session_id: sessionId,
  content: 'Search for flights to Tokyo'
}));

// Receive response
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  // msg.type: 'response' | 'approval_request' | 'event' | 'status'
};

// Approve tool execution
ws.send(JSON.stringify({
  type: 'approval_response',
  session_id: sessionId,
  approved: true
}));
```

---

## Authentication & Billing

### Supabase Auth

Already in the stack for the website. Extended for platform auth with additional tables:

- **users** — account info, tier (free/pro/team), Fly machine ID, region, status
- **subscriptions** — Stripe subscription tracking, plan, billing status
- **llm_usage** — per-user LLM cost metering (provider, model, tokens, cost)

Table schemas and API routes are in WEBSITE.md (not public).

### Stripe Integration

| Plan | Price | Includes |
|------|-------|---------|
| **Free** | $0 | Desktop app only. No cloud features. |
| **Pro** | $19/month | Cloud instance, 24/7 uptime, all channels, 10GB storage, $5/mo LLM credit |
| **Pro Annual** | $15/month (billed annually) | Same as Pro |
| **Team** | $49/month | 5 agent instances, shared knowledge, team vault, priority support |

LLM costs above the included credit are passed through from the provider at a small margin.

### Registration Flow

```
1. User visits elophanto.com
2. Clicks "Get Started" → lands on app.elophanto.com/signup
3. Supabase Auth: email/password or GitHub OAuth
4. Free tier: download desktop app link
5. Pro tier: enter payment → Stripe checkout
6. On successful payment:
   a. Create Fly Machine via API
   b. Attach persistent volume
   c. Initialize with user's config
   d. Start gateway
   e. Redirect to web dashboard (connected to their agent)
7. User configures: LLM provider keys (cloud API only — no Ollama), channel tokens, permission mode
8. Agent is live
```

---

## Security Model (Cloud)

### Isolation Guarantees

| Layer | Mechanism |
|-------|----------|
| Compute | Fly.io microVM — hardware-level isolation (Firecracker) |
| Network | Private IPv6, no public ports. All traffic through Fly proxy with auth. |
| Storage | Dedicated volume per user. No shared filesystem. |
| Vault | Per-user encryption key derived from user's password (PBKDF2). We never store the decryption key. |
| Browser | Full Chrome per container using `--headless=new` mode. Full browser engine with persistent profile, cookies, sessions. Same capabilities as headed Chrome — avoids captcha triggers and fingerprinting detection. |
| LLM keys | Stored in user's vault. Never leave the container. Passed directly to LLM API, not through our servers. |

### LLM Providers: Desktop vs Cloud

Cloud containers run on shared CPUs with no GPU. This means **Ollama (local LLM inference) is not available in cloud mode** — it requires a GPU or significant local compute that Fly.io shared machines don't provide.

| Provider | Desktop | Cloud | Notes |
|----------|---------|-------|-------|
| **Ollama** (local) | Yes | **No** | Requires GPU/local compute. Desktop only. |
| **OpenRouter** (cloud) | Yes | Yes | Default for cloud instances |
| **Z.ai / GLM** (cloud) | Yes | Yes | Cost-effective coding models |
| **OpenAI API** | Yes | Yes | Direct API key |
| **Managed LLM** (ours) | No | Yes | We provide the key, user pays per usage |

### User's LLM Keys

Users bring their own cloud LLM API keys (OpenRouter, Z.ai, OpenAI, etc.). Keys are stored in the user's encrypted vault inside their container. We never see or proxy LLM calls — the agent calls LLM providers directly from the container.

For cloud users who don't want to manage API keys, we offer a managed LLM option:
- We provide a shared OpenRouter key
- Usage metered and billed to the user
- LLM calls still happen from the user's container

### Browser: Full Chrome, Not Old Headless

Cloud containers run **full Chrome** with `--headless=new` (Chrome's new headless mode, available since Chrome 112). This is critically different from the old `--headless` flag or standalone headless Chromium:

| | Old Headless / Headless Chromium | Full Chrome `--headless=new` |
|---|---|---|
| Engine | Separate stripped-down implementation | Same full browser engine as headed Chrome |
| Captchas | Frequently triggered — sites detect old headless | Behaves identically to a real user's browser |
| Fingerprinting | Missing APIs (`window.chrome`, plugins) expose it | Full browser fingerprint, indistinguishable from desktop |
| Profile persistence | Limited cookie/session support | Full Chrome profile: cookies, localStorage, extensions, sessions |
| Site compatibility | Some sites block old headless entirely | Works with any site a normal browser would |

EloPhanto's existing `browser.mode: profile` setting carries over to cloud. Each user's container has its own Chrome profile directory on the persistent volume — login sessions, cookies, and browser state persist across machine hibernation/wake cycles.

No Xvfb or virtual display needed — new headless mode runs without a display server while maintaining full capabilities.

### Network Policy

```
User's Container:
  ALLOW outbound: LLM APIs (openrouter.ai, api.openai.com, z.ai, etc.)
  ALLOW outbound: EloPhantoHub (github.com raw)
  ALLOW outbound: Channel APIs (api.telegram.org, discord.com, slack.com)
  ALLOW outbound: User-configured URLs (browser automation targets)
  ALLOW inbound: Fly proxy only (authenticated WebSocket)
  DENY: Inter-container traffic
  DENY: Internal network scanning
```

### Data Portability

Users can export all their data at any time:

```bash
# Cloud → Local
# From web dashboard: Settings → Export → Download .tar.gz
# Contains: knowledge/, skills/, vault.db (encrypted), config.yaml, session history

# Local → Cloud
# From web dashboard: Settings → Import → Upload .tar.gz
# Merges knowledge, skills, sessions. Vault re-encrypted with cloud key.
```

---

## Implementation Roadmap

| Phase | What | Dependencies |
|-------|------|-------------|
| **H1: Web Dashboard** | React app with chat, tools, skills, settings pages. Connects via gateway WebSocket protocol. | None — gateway protocol exists |
| **H2: Cloud Infrastructure** | Fly.io machine provisioning API, Supabase auth, Stripe billing, Docker image for EloPhanto | H1 (dashboard to connect to) |
| **H3: Desktop App** | Tauri shell wrapping web dashboard + Python subprocess manager. Mac first, then Windows/Linux. | H1 (dashboard as the UI) |
| **H4: Gateway Proxy** | Shared lightweight service for wake-on-request. Holds channel connections, buffers messages, wakes machines. | H2 (machines to wake) |
| **H5: Managed LLM** | Shared OpenRouter key, per-user metering, usage billing integration. | H2 (billing infrastructure) |
| **H6: Team Features** | Shared knowledge bases, team vault, multiple agent instances, role-based access. | H2 (user management) |

### H1 is the critical path

The web dashboard is shared between desktop and cloud. Build it first:
1. It works immediately with the existing gateway (just open in a browser during development)
2. Desktop app wraps it in Tauri (H3)
3. Cloud platform serves it (H2)

This is the Phase 8 "Web UI" that's been planned since the original roadmap.

### Docker Image

```dockerfile
FROM python:3.12-slim

# System deps — full Chrome (not old headless Chromium).
# Uses --headless=new for full browser engine with profile support.
RUN apt-get update && apt-get install -y \
    nodejs npm \
    chromium chromium-sandbox \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# EloPhanto
COPY . /app
WORKDIR /app
RUN pip install uv && uv sync --no-dev
RUN cd bridge/browser && npm ci

# Persistent data mount point
VOLUME /data
ENV ELOPHANTO_DATA_DIR=/data

# Gateway port
EXPOSE 18789

CMD ["python", "-m", "cli.main", "gateway", "--host", "0.0.0.0"]
```

### Fly.io Machine Provisioning

On signup, a management service provisions the user's machine:

1. Create persistent volume (1GB, user's nearest region)
2. Create Fly Machine with EloPhanto Docker image
3. Mount volume at `/data` (knowledge, vault, skills, database)
4. Configure gateway to listen on internal port
5. Set up Fly proxy routing (HTTPS → machine gateway)
6. Machine auto-restarts on failure, auto-hibernates on inactivity

---

## Summary

The hybrid model gives EloPhanto two growth engines:

1. **Desktop app** (free) — builds the install base. Developers and privacy-focused users run locally. Costs us nothing to support. Organic growth through GitHub + word of mouth.

2. **Cloud platform** (paid) — captures the larger market. Anyone can have an always-on personal AI agent without touching a terminal. Per-user container isolation keeps the security model sound. Recurring revenue funds development.

Both share the same agent core, the same web dashboard, the same gateway protocol. Build once, deploy twice. The web dashboard (H1) is the critical first step — everything else builds on it.
