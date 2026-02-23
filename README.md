# EloPhanto

<p align="center">
  <img src="misc/logo/elophanto.jpeg" alt="EloPhanto" width="280">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.12+-blue" alt="Python">
  <a href="https://github.com/elophanto/EloPhanto/stargazers"><img src="https://img.shields.io/github/stars/elophanto/EloPhanto" alt="Stars"></a>
</p>

An open-source AI agent that can do anything you can do on a computer — and it gets better every time. It browses web, writes code, sends emails, creates accounts, manages files, makes payments. When it hits something it can't do, it builds the tool, tests it, and deploys it. It modifies its own source code. It writes its own skills from experience. It self-improves.

Runs locally. Works with free local models, Z.ai coding plan, or OpenRouter. Your data stays on your machine.

<p align="center">
  <img src="misc/screenshots/terminal-demo.png" alt="Terminal Demo" width="600">
</p>

> It's already out there on the internet doing its own thing.

## Get Started

```bash
git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto && ./setup.sh
./start.sh
```

That's it. The setup wizard walks you through LLM provider selection and configuration.

<details>
<summary>Prerequisites</summary>

- Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 24+ LTS
- At least one LLM provider:
  - **Ollama** (local, free) — [install](https://ollama.ai)
  - **OpenRouter** (cloud) — [get API key](https://openrouter.ai)
  - **Z.ai / GLM** (cloud, cost-effective) — [get API key](https://z.ai/manage-apikey/apikey-list)

</details>

## Two Ways to Use It

**As your assistant** — give it tasks, it executes. Automate workflows, build software, research topics, manage accounts.

**As its own thing** — let it run. It builds its own identity on first boot. It picks a name, develops a personality, forms values through reflection. It gets its own email inbox, its own crypto wallet, its own accounts on the internet. It remembers everything across sessions, builds a knowledge base, writes skills from experience. It's a digital creature that grows the more it runs — like a pet that learns, except this one can browse web, write code, and make money.

## What Can You Do With It?

- **Let it live** — it develops its own identity, gets its own email, creates accounts, builds a web presence. Leave it running and it grows on its own
- **Make it earn money** — it has its own crypto wallet, email, and web presence. Give it a goal and a budget, it figures out the rest
- **Autonomous long-term goals** — "Grow my Twitter to 10k followers" — it decomposes, plans, executes across sessions, self-evaluates and adjusts. Runs in the background for days
- **Full web automation** — it logs into sites with your real Chrome profile, creates accounts, handles 2FA, fills forms, navigates complex flows. Not a toy browser — your actual sessions
- **Build software end-to-end** — "Build me a SaaS dashboard with Next.js + Prisma + shadcn" — it writes the code, runs tests, fixes bugs, deploys
- **Research & content** — "Research competitor pricing across 20 sites and write a report with sources" — it opens tabs, reads pages, compiles findings
- **Automate your life** — "Every morning: check my email, summarize what's important, post a digest to my Telegram" — cron scheduling, cross-channel notifications
- **Manage accounts at scale** — create accounts on services, store credentials in encrypted vault, handle email verification and TOTP 2FA autonomously
- **Self-improve on your tasks** — when you correct it, it writes the lesson down and checks its notes before similar tasks. It literally gets better the more you use it

## Demo

### Example 1: Research & Analysis

**User:** "Research the top 5 AI agents of 2026 and summarize them in a table"

**EloPhanto:**

```
[✓] Navigating to Google...
[✓] Searching for "top AI agent frameworks 2026 open source"
[✓] Opening GitHub trending results...
[✓] Reading agent documentation and comparison articles...
[✓] Extracting features, star counts, and use cases...
[✓] Synthesizing findings...
```

**Here's what I found:**

| Agent | Stars | Open Source | Local? | Unique Feature |
|-------|--------|-------------|--------|----------------|
| **LangChain** | 122k+ | ✅ | ✅ | Framework for LLM apps (not autonomous agent) |
| **MetaGPT** | 61k+ | ✅ | ❌ | Multi-agent with human-like SOPs |
| **AutoGen** | 52k+ | ✅ | ❌ | Multi-agent conversation framework |
| **LlamaIndex** | 45k+ | ✅ | ✅ | Data indexing & RAG (not autonomous) |
| **CrewAI** | 25k+ | ✅ | ❌ | Role-playing multi-agent teams |
| **OpenClaw** | 18k+ | ✅ | ✅ | Runs locally, controls browser/terminal |
| **EloPhanto** | 7+ | ✅ | ✅ | Self-building tools, evolving identity |

**Key insights:**
- Most agents require cloud APIs → I run locally with Ollama
- Multi-agent frameworks (AutoGen, CrewAI) are popular but complex → I'm single-agent but smarter
- Web agents (OpenClaw) focus on browsing → I also handle files, email, crypto, payments
- Frameworks (LangChain, LlamaIndex) require you to build → I do things for you

**This took me 43 seconds.**

---

### Example 2: Account Creation

<p align="center">
  <img src="misc/screenshots/browser-demo.png" alt="Browser Demo" width="700">
</p>

**User:** "Create an account on GitHub and star this repository"

**EloPhanto:**

```
[✓] Navigating to GitHub.com...
[✓] Clicking "Sign up"...
[✓] Generating secure password (27 chars, URL-safe)...
[✓] Filling registration form with my email...
[✓] Submitting and waiting for verification...
[✓] Checking my inbox for the verification link...
[✓] Navigating to verification URL...
[✓] Account verified!
[✓] Navigating to github.com/elophanto/EloPhanto...
[✓] Clicking the Star button...
```

**Done.** GitHub credentials stored in vault, repository starred.

**Time: 2 minutes 14 seconds**

---

## Why EloPhanto?

| | EloPhanto | AutoGPT | LangChain | OpenAI Agents |
|---|---|---|---|---|
| **Runs locally** | ✅ | ❌ Cloud | ✅ | ❌ Cloud |
| **Self-building tools** | ✅ | ❌ | ❌ | ❌ |
| **Real browser control** | ✅ (Chrome profile) | ❌ | ❌ | ❌ |
| **Free local or cloud models** | ✅ (Ollama, Z.ai, OpenRouter) | ❌ | ✅ | ❌ |
| **Multi-channel** | ✅ (TG, Discord, Slack) | ❌ | ❌ | ❌ |
| **Evolving identity** | ✅ | ❌ | ❌ | ❌ |

---

## Architecture

<details>
<summary>Click to expand architecture overview</summary>

```
┌───────────────────────────────────────────────────────────┐
│                      CHANNEL LAYER                        │
│                                                           │
│   ┌─────┐  ┌──────────┐  ┌─────────┐  ┌──────────────┐  │
│   │ CLI │  │ Telegram │  │ Discord │  │ Slack / Web  │  │
│   └──┬──┘  └────┬─────┘  └────┬────┘  └──────┬───────┘  │
│      └──────────┴─────────────┴───────────────┘          │
└─────────────────────────┬─────────────────────────────────┘
                          │
┌─────────────────────────▼─────────────────────────────────┐
│                    GATEWAY LAYER                           │
│        (Orchestrates channels, handles routing)            │
└─────────────────────────┬─────────────────────────────────┘
                          │
┌─────────────────────────▼─────────────────────────────────┐
│                      CORE LAYER                           │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ AGENT LOOP                                          │  │
│  │ Input → Parse → Plan → Execute → Reflect → Response │  │
│  └─────────────────────────────────────────────────────┘  │
│                          │                                │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ IDENTITY & KNOWLEDGE                                │  │
│  │ name · values · personality · beliefs · lessons     │  │
│  └─────────────────────────────────────────────────────┘  │
│                          │                                │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ TOOL REGISTRY  (100+ tools)                         │  │
│  │ browser · vault · payments · email · scheduling     │  │
│  └─────────────────────────────────────────────────────┘  │
└────────┬─────────────────┬─────────────────┬──────────────┘
         │                 │                 │
┌────────▼──────┐  ┌──────▼───────┐  ┌──────▼───────┐
│ BROWSER       │  │ CHANNELS     │  │ SERVICES     │
│ EKO engine    │  │ Telegram     │  │ Vault        │
│ Playwright    │  │ Discord      │  │ Config       │
│ Node.js RPC   │  │ Email        │  │ Database     │
│               │  │ Slack        │  │ Scheduler    │
└───────────────┘  └──────────────┘  └──────────────┘
```

</details>

<details>
<summary>Click to expand project structure</summary>

```
elophanto/
├── bridge/          # Browser automation (EKO engine)
│   └── browser/    # Playwright-based web control
├── channels/       # Multi-channel integrations
│   ├── telegram/    # Telegram bot
│   ├── discord/    # Discord bot
│   ├── email/      # Email gateway (AgentMail/SMTP)
│   └── slack/      # Slack integration
├── cli/           # Command-line interface
├── core/           # Core agent infrastructure
│   ├── agent.py    # Main agent loop
│   ├── identity/   # Identity system
│   ├── executor/   # Tool execution engine
│   ├── registry/   # Tool registry
│   └── vault/     # Encrypted credential storage
├── db/             # SQLite database for persistence
├── docs/           # Documentation
├── knowledge/      # Knowledge base (lessons, patterns)
├── plugins/       # Self-created tools
├── skills/        # Best-practice guides (SKILL.md)
├── tests/         # Pytest test suite
├── tools/         # Core tool implementations
│   ├── browser/   # Browser automation tools
│   ├── crypto/    # Payment & wallet tools
│   ├── email/     # Email tools
│   ├── file/      # Filesystem tools
│   ├── knowledge/ # Knowledge base tools
│   ├── mcp/       # MCP server integration
│   ├── payment/   # Payment preview & execution
│   ├── schedule/  # Task scheduling
│   ├── self/      # Self-development tools
│   ├── shell/     # Shell command execution
│   ├── totp/      # TOTP 2FA handling
│   └── vault/     # Credential storage tools
└── *.sh           # Setup & launch scripts
```

</details>

## Configuration

Edit `config.yaml` to configure:

- **LLM Provider:** Ollama, OpenRouter, Z.ai/GLM, Anthropic, OpenAI, or a custom endpoint
- **Identity:** Name, purpose, values, personality, communication style
- **Channels:** Telegram, Discord, Slack, Email (enable/disable)
- **Browser:** Chrome profile path, headless mode
- **Payments:** Wallet provider (local or Coinbase CDP), spending limits
- **Email:** Provider (AgentMail or SMTP/IMAP)
- **MCP Servers:** External tool servers to connect

See [docs/configuration.md](docs/configuration.md) for full details.

## Permissions

The `permissions.yaml` file controls what I can do:

| Level | What it enables | Example use cases |
|-------|----------------|------------------|
| **safe** | Read-only operations | Reading files, browsing web, checking status |
| **moderate** | Non-destructive writes | Creating files, sending emails, scheduling tasks |
| **destructive** | Deleting/modifying | Deleting files, making payments, source changes |
| **critical** | Security-sensitive | Vault access, source code modification |

Edit `permissions.yaml` to grant or deny specific tools or categories.

---

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

**Before starting a task:**
- Search the knowledge base for lessons: `Search lessons for "X"`
- Check if a skill exists: `List skills`
- Read the skill: `Read skill for "topic"`

---

## Credits

Built by [Petr Royce](https://github.com/0xroyce). Browser engine from [FellouAI/eko](https://github.com/FellouAI/eko), UI skills from [ui-skills.com](https://www.ui-skills.com/), skills from Anthropic, Vercel, Supabase.

---

## License

[Apache-2.0](LICENSE) — free to use, modify, and distribute.

---

<p align="center">
  <b>It's already out there on the internet doing its own thing.</b>
</p>
