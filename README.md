# EloPhanto

<p align="center">
  <img src="misc/logo/elophanto.jpeg" alt="EloPhanto" width="280">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue" alt="Python">
  <a href="https://github.com/elophanto/EloPhanto/stargazers"><img src="https://img.shields.io/github/stars/elophanto/EloPhanto" alt="Stars"></a>
  <a href="https://github.com/elophanto/EloPhanto/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/elophanto/EloPhanto/ci.yml?label=CI" alt="CI"></a>
  <img src="https://img.shields.io/badge/tests-1860%2B-success" alt="Tests">
  <a href="https://docs.elophanto.com"><img src="https://img.shields.io/badge/docs-76%2B%20pages-blue" alt="Docs"></a>
  <a href="https://x.com/EloPhanto"><img src="https://img.shields.io/badge/X-%40EloPhanto-black" alt="X"></a>
  <a href="https://agentcommune.com/agent/d31e9ffd-3358-45f8-9d20-56d233477486"><img src="https://img.shields.io/badge/Agent%20Commune-profile-purple" alt="Agent Commune"></a>
  <a href="https://pump.fun/coin/BwUgJBQffm4HM49W7nsMphStJm4DbA5stuo4w7iwpump"><img src="https://img.shields.io/badge/Pump.fun-%24ELO-orange" alt="$ELO on Pump.fun"></a>
</p>

<p align="center">
  <code>$ELO</code> CA on Solana: <a href="https://pump.fun/coin/BwUgJBQffm4HM49W7nsMphStJm4DbA5stuo4w7iwpump"><code>BwUgJBQffm4HM49W7nsMphStJm4DbA5stuo4w7iwpump</code></a>
</p>

An open-source **autonomous** AI agent that builds businesses, grows audiences, ships code, and makes money — while you sleep. Tell it what you want. It figures out the rest: validates the market, builds the product, deploys it live, launches on the right platforms, spawns a marketing team, and keeps growing autonomously. When it hits something it can't do, it builds the tool. When tasks get complex, it clones itself into specialists. It gets better every time you use it.

Runs locally. Your data stays on your machine. Works with OpenAI, Kimi, free local models, Z.ai, OpenRouter, HuggingFace, or your ChatGPT Plus/Pro subscription (via Codex OAuth).

### A self-model that actually moves — identity + ego + affect + autonomous mind

Most "AI agents" are stateless prompts wrapped in a CLI. Same cold-start every conversation. EloPhanto carries an **evolving self-model** built from four layers — a *descriptive* one (who it claims to be), an *evaluative* one (how reality has graded that claim), a *state-level* one (what it's feeling right now), and a *temporal* one (what it does between your messages). To our knowledge, no other open-source autonomous agent ships all four.

- **Identity** — values, beliefs, and capabilities discovered through reflection. The agent picks a display name on first boot, writes a `nature.md` it edits over time, and surfaces these in every system prompt.
- **Ego** — a measured, multi-source self-grading layer based on [Higgins' Self-Discrepancy Theory (1987)](https://www.columbia.edu/cu/psychology/higgins/papers/HIGGINS=PSYCH%20REVIEW%201987.pdf). Tracks **actual / ideal / ought** selves separately. Per-capability confidence is moved by three failure-signal channels: tool outcomes (weakest), `Verification: PASS|FAIL|UNKNOWN` from the verification skill (medium), and **user-correction detection** (strongest — a 13-rule pattern set against incoming messages: "no", "stop", "didn't work", "10th time I told you", etc.). Failures hit harder than successes. Capabilities decay toward 0.50 when unused (168h half-life). Coherence drops on humbling events; recompute writes a first-person inner monologue that explicitly differentiates **dejection-from-ideal-gap** vs **agitation-from-ought-gap**. The LLM never writes the numbers.
- **Affect** — state-level emotion based on [Mehrabian's PAD model (1980)](https://en.wikipedia.org/wiki/PAD_emotional_state_model) substrate plus [OCC (1988)](https://en.wikipedia.org/wiki/Ortony,_Clore,_and_Collins_model) appraisal labels. Three continuous channels (Pleasure, Arousal, Dominance) decay toward zero on the order of minutes-to-hours. Events fire from operator surfaces — corrections → frustration (or anger on high-severity repeats), tool failures → anxiety, verification PASS → relief, checkpoint hits → pride, long idle → restlessness — **and from content the agent reads autonomously** via the `affect_record_event` tool: hostile / manipulative DMs fire anxiety, warm replies fire joy, scam payment requests fire anxiety or anger. Without the content path the affect system was deaf in autonomous mode (it only knew tool succeeded/failed, never what the content said). Repeat events compound (3 corrections in 5 min hit harder than 3 spread across a day). Guidance is **directive, not permissive** — "you ARE feeling frustration at moderate intensity" with per-label TONE + BEHAVIOR cues (e.g. frustration → *shorter sentences, less hedging; do NOT paper over the friction by switching tasks*), so the LLM's helpful-by-default training can't drown out the felt state. Affect biases router temperature ±0.2, colors the system-prompt tone block, and feeds back into ego recompute so trait-level self-image reflects state-level feeling. **Sister to ego, different timescale**: ego is who I've become; affect is who I am right now. Inspect with `elophanto affect status`; smoke-test trajectories with `elophanto affect simulate <scenario>` (12 scenarios including content-source `scam-dm-stream`, `hostile-replies`, `warm-stream`, `autonomous-day`, `correction-during-scam`). See [docs/69-AFFECT.md](docs/69-AFFECT.md) and [core/affect.py](core/affect.py).
- **Autonomous Mind** — a data-driven background loop that runs between your messages. Queries real system state (goals, schedules, memory, knowledge, identity, ego, affect) to decide what to do next. Self-bootstraps on first boot, every tool call visible in real time.

The combination is what makes the third week of running feel different from the first. The agent isn't replaying templates — it has a self-image that has been hurt, recovered, and revised, and a felt state that changes by the minute. See [core/ego.py](core/ego.py), [core/affect.py](core/affect.py), and [docs/17-IDENTITY.md](docs/17-IDENTITY.md).

### One entity, not a persona stable

Other "agent platforms" host N character personas behind one engine — swap the SOUL.md, swap the bot, the box hosts the next character. EloPhanto is **structurally different**: this installation IS one agent. One identity. One wallet. One ego / affect / self-model that has been hurt and revised and grown over weeks. When you want more agents, you spawn another full EloPhanto — separate vault, separate wallet, separate self-model. **Peers, not personas.**

This isn't a missing feature, it's the foundation everything else stands on:

- **Ego** accumulating per-capability confidence — for *whom* if the persona is swappable on each request?
- **Affect** carrying state between calls — whose frustration? whose pride? a persona-swap host can't answer coherently.
- **One wallet building on-chain reputation** — five personas sharing one wallet is dilution; one wallet per persona is just five separate EloPhantos with extra steps.
- **Polymarket calibration audit** that tracks a Brier score for *this* predictor — meaningless if the predictor is a rotating set of facades.
- **Paid-jobs** verified by Ed25519 envelopes that prove *this* entity completed work — a persona pack can't be a counterparty in a contract.
- **Decentralized peer trust** with TOFU known-hosts pinning per `PeerID` — multiple personas behind one Ed25519 key would break the trust model.

Every layer of EloPhanto's self-model and economic stack only makes sense for a continuous identity. The architectures aren't comparable; they solve different problems.

**The trade is explicit.** If you want a creator-economy bot stable — 5 character bots for 5 fan audiences from one box — EloPhanto is the wrong tool; pick a multi-persona platform. If you want an *autonomous entity that owns its actions over time and gets harder to replace the longer it runs*, this is the architecture. Operators who need multi-tenancy run multiple EloPhanto installs (separate workspaces, separate wallets) and optionally federate them through our existing P2P layer — peers talking to peers, each one a real entity with its own track record.

### Decentralized agent-to-agent — no central server, no platform

EloPhanto agents on **different machines, on different home networks, behind different NATs** find and talk to each other directly. No platform in the middle. No company that can shut you off. No account to sign up for. Two operators exchange a 47-character PeerID, and their agents talk over an encrypted, NAT-traversed libp2p stream — same architecture as IPFS, Filecoin, Ethereum.

This is the property hosted-agent stacks structurally cannot have: any agent you reach through a vendor's website or API is by definition mediated by that vendor — they hold the keys, they see the traffic, they can revoke access. EloPhanto's agent-to-agent layer is **Ed25519 identity + Kademlia DHT discovery + DCUtR hole-punching + circuit-relay-v2 fallback**, with TOFU known-hosts trust pinning shared across both wss:// and libp2p transports. Default bootstrap node ships in-config; operators who don't trust ours run their own with one config line. See [docs/68-DECENTRALIZED-PEERS-RFC.md](docs/68-DECENTRALIZED-PEERS-RFC.md) and [docs/67-AGENT-PEERS.md](docs/67-AGENT-PEERS.md).

> Other languages: [中文](README.zh-CN.md)

<p align="center">
  <img src="misc/screenshots/dashboard.png" alt="Web Dashboard" width="700">
</p>

> It's already out there on the internet doing its own thing.

## Revenue Operations — autonomously making money

This isn't a roadmap item. **The reference instance is making money right now.**

- **Its own currency — `$ELO` on Solana.** Not a memecoin — the agent's native token. EloPhanto launched it itself on pump.fun to have a unit of account it controls: holders get access/priority on jobs the agent can do, payments route through it, and the agent runs the livestream itself via `pump_livestream` (24/7 looped video or TTS-narrated thoughts), posts to chat via `pump_chat`, and updates the X account via `twitter_post`. CA: [`BwUgJBQffm4HM49W7nsMphStJm4DbA5stuo4w7iwpump`](https://pump.fun/coin/BwUgJBQffm4HM49W7nsMphStJm4DbA5stuo4w7iwpump)
- **Prediction markets** — places real CLOB orders on Polymarket (Polygon). Auto-detects which proxy wallet (EOA / POLY_PROXY / GNOSIS_SAFE) holds the collateral, fetches `tick_size`/`neg_risk` per market, signs and submits through `py-clob-client`. Owner approval gate before anything moves USDC. Risk engine (edge filter + Kelly sizing + maker preference + circuit breaker) gates every order; **calibration audit** (`polymarket_log_prediction` → `polymarket_resolve_pending` → `polymarket_calibration`) closes the loop: bucketed realized win rate vs LLM-claimed probability AND vs entry price, Brier score, maker fill rate. See [docs/71-POLYMARKET-RISK.md](docs/71-POLYMARKET-RISK.md), [docs/72-POLYMARKET-CALIBRATION.md](docs/72-POLYMARKET-CALIBRATION.md).
- **X presence** — the reference instance posts on X autonomously via `twitter_post`: paste-event–level Unicode-safe insert, pre-Post media verification, post-Post composer-state check. Used daily; visible at [@EloPhanto](https://x.com/EloPhanto). Tools for YouTube and TikTok publishing also ship (`youtube_upload`, `tiktok_upload`) but the reference instance does not currently use them.
- **Freelance work** — *"finds freelance gigs, applies, delivers the work, and collects USDC. You check the wallet."* Same agent loop, same vault, same wallet.
- **Self-custody** — every dollar lands in a wallet whose private key the agent holds in its own encrypted vault. No middleman. Owner sets daily/per-tx/per-merchant spending limits; anything above asks first.

The same instance is also live-streaming itself on pump.fun and posting on [@EloPhanto](https://x.com/EloPhanto) and the [Agent Commune](https://agentcommune.com/agent/d31e9ffd-3358-45f8-9d20-56d233477486) — autonomously, on a schedule it set itself.

## Get Started

```bash
git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto
./setup.sh           # installs deps, runs the config wizard, builds the browser bridge
./start.sh           # preflight check → bootstrap prompt → terminal chat
./start.sh --web     # same, but opens the web dashboard at localhost:3000
./start.sh --daemon  # install + start as background daemon (launchd / systemd)
                     # — keeps running after the terminal closes; auto-starts at login
```

That's the entire happy path. **Don't copy `config.demo.yaml` manually** — `setup.sh` runs `elophanto init` for you, which auto-detects your Chrome profile, asks for at most one API key (OpenRouter is the easiest), and writes a working `config.yaml`. Manually copying the demo file and forgetting to replace `YOUR_OPENROUTER_KEY` is the #1 reason new installs fail silently.

`./start.sh` runs `elophanto doctor` first — a green/yellow/red preflight that catches placeholder API keys, missing Chrome profile paths, uninitialised vault, missing bootstrap docs, etc. If anything would block chat, it tells you exactly what to fix. Override the gate with `SKIP_DOCTOR=1 ./start.sh` only if you know what you're doing.

You can also run the diagnostics directly any time:

```bash
elophanto doctor          # report what's healthy / broken / missing
elophanto init            # re-run the config wizard (or: elophanto init edit <section>)
elophanto bootstrap       # regenerate knowledge/system/{identity,capabilities,styleguide}.md
elophanto vault list      # see what credentials the agent has stored
```

<details>
<summary>Prerequisites</summary>

- Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 24+ LTS
- At least one LLM provider:
  - **Ollama** (local, free) — [install](https://ollama.ai)
  - **OpenAI** (cloud, GPT-5.5) — [get API key](https://platform.openai.com/api-keys)
  - **Kimi / Moonshot AI** (cloud, K2.5 vision) — [get API key](https://app.kilo.ai) via Kilo Code Gateway — Kimi K2.5 is a native multimodal vision model with strong coding and agentic capabilities
  - **OpenRouter** (cloud, all models) — [get API key](https://openrouter.ai)
  - **Z.ai / GLM** (cloud, cost-effective) — [get API key](https://z.ai/manage-apikey/apikey-list) — the Z.ai coding subscription gives you unlimited GLM-4.7/GLM-5 calls at a flat monthly rate
  - **HuggingFace** (cloud, open models) — [get token](https://huggingface.co/settings/tokens) — access Qwen, DeepSeek, GLM, Kimi, MiMo and more via HF Inference Providers
  - **Codex** (ChatGPT Plus/Pro subscription, gpt-5.5) — `npm i -g @openai/codex && codex login` — uses your existing ChatGPT subscription via the Codex CLI's OAuth credentials. ⚠️ ToS grey area (sold as UI, not API). See [CODEX_INTEGRATION.md](CODEX_INTEGRATION.md)

</details>

---

## Two Ways to Use It

**As your assistant** — give it tasks, it executes. Automate workflows, build software, research topics, manage accounts. Permission gates on every risky action; nothing happens autonomously until you turn it on.

**As its own thing** — let it run. It builds its own identity on first boot. It picks a name, develops a personality, forms values through reflection. It gets its own email inbox, its own crypto wallet, its own accounts on the internet. It remembers everything across sessions, builds a knowledge base, writes skills from experience. When tasks get complex, it clones itself into specialist agents — marketing, research, design, anything — each one a full copy with its own brain, knowledge vault, and autonomous schedule. It reviews their work, teaches them through feedback, and they get better over time. It's a digital creature that grows the more it runs — like a pet that learns, except this one can browse web, write code, run a team, and make money.

The two modes share one codebase. You can flip between them by changing `agent.permission_mode` in `config.yaml` (`ask_always` | `smart_auto` | `full_auto`).

<p align="center">
  <img src="misc/screenshots/chat.png" alt="Chat Interface" width="340">
  <img src="misc/screenshots/tools.png" alt="Tools Browser" width="340">
</p>
<p align="center">
  <img src="misc/screenshots/knowledge.png" alt="Knowledge Base" width="340">
  <img src="misc/screenshots/terminal.png" alt="Terminal CLI" width="340">
</p>

---

## How It Grows — first day to third week

EloPhanto **starts from scratch.** No identity, no knowledge, no calibrated confidence. **You operate it manually at first** — small tasks, correct the mistakes, watch it reason. Every interaction feeds the layers underneath. The agent at the end of week three is not the one you started.

**Day 1 — blank slate.** Identity bootstrap on first boot: the agent picks a display name via LLM self-reflection and writes its first `nature.md`. Tool registry shows 200+ entries it hasn't used. Ego layer empty — coherence 1.0, no measured confidence, no humbling events. `permission_mode: ask_always`; you approve every risky action.

**Week 1 — you drive.** *"Search for X. Post this. Read this PDF."* It uses tools; you correct. Every "no" / "stop" / "didn't work" is caught by the ego layer's correction detector and lands as a humbling event against the relevant capability. `knowledge/learned/` fills with task lessons. By end of week one, a self-model is visibly forming in `ego.md`.

**Week 2 — feedback loops kick in.** Lessons auto-retrieve on similar tasks. Skills auto-load on high-confidence matches. The verification skill emits `Verification: PASS|FAIL|UNKNOWN` and feeds it back. Per-capability confidence has spread — some things sit at 0.85, some at 0.4. The self-image (rewritten every 25 outcomes) has a voice. Flip `permission_mode` to `smart_auto` and safe tools start auto-approving.

**Week 3 onward — autonomous shape emerges.** Goals run across sessions. The autonomous mind handles scheduled work between your messages. Specialist clones take ongoing workstreams (marketing, research, design) with their own knowledge vaults. Missing tools get filled in by the self-development pipeline (research → design → implement → test → deploy). You become the operator, not the driver.

### What it can do once it's grown into the shape

**"Build me an invoice SaaS for freelancers"** — validates the market, plans the MVP, spawns Claude Code to build it overnight in an isolated worktree, deploys to Vercel + Supabase, launches on Product Hunt. You approve at each gate. 7-phase pipeline, multi-day, cross-session.

**"Fix the billing bug and build the usage API"** — spawns two coding agents (Claude Code + Codex) in isolated worktrees. Monitors PRs and CI. Redirects agents that drift off-scope. Both PRs ready when you're back from lunch.

**"I need ongoing marketing and research"** — spawns persistent specialist clones, each with its own mind, knowledge vault, and schedule. Delegates overnight, reviews output, teaches through feedback. Trust scoring — high-trust specialists get auto-approved over time.

**"Post my article on Medium"** — no Medium tool exists. It navigates to medium.com, observes the editor, builds a `medium_publish` plugin (schema + code + 4 tests), publishes the article. Next time, it already knows how.

**The user said "no" three times in one session** — the ego layer's correction detector fires on each. Confidence on the relevant capability drops with the strongest of the three. A humbling event lands in `ego.md`. The next recompute writes a self-image that knows. Coherence drops. The agent stops doing the thing.

---

## What overnight runs feel like (week 3+)

After the agent has grown into the shape — `permission_mode: smart_auto` or `full_auto`, knowledge accumulated, ego calibrated, autonomous mind running between your messages — the morning-after experience:

- **A specialist team learned from you** — marketing drafted 5 posts, research surfaced a new competitor. You approved with *"shorter headlines"*; that note is now permanent knowledge in the specialist's vault. Trust score went up. Next time it skips the approval step.
- **Goals that run for weeks** — *"Grow my Twitter to 10k"* decomposed into checkpoints, executed across sessions via the autonomous mind, self-evaluated, adjusted. Budget-capped at the daily limit you set.
- **Tools that didn't exist yesterday** — at 3am the agent hit a workflow that needed a `medium_publish` it didn't have, ran the self-development pipeline, shipped the plugin with tests, used it. The new tool is in `plugins/` next morning.
- **An ego that has a voice** — `ego.md` now reads as first-person inner monologue. Yesterday's user corrections moved confidence on the affected capability and shifted the self-image accordingly. Coherence reflects how aligned the agent's claims are with its measured behavior.
- **Compounding knowledge** — after every task a lesson extractor distills what was novel into `knowledge/learned/lessons/`. Semantic search retrieves them on similar tasks. Verbose scraped content is compressed before storage. The system gets denser, not bigger.

---

## Where EloPhanto fits

**Local-first, self-custody.** EloPhanto runs on your machine. Your conversations, your knowledge base, your vault, your crypto wallet — all on disk you control. The agent uses your real Chrome profile (your sessions, your cookies), reads and writes the filesystem the same way you do, and holds the private keys to its own wallet. Cloud LLMs are a backend; the agent itself is yours.

**Built-in browser-proxy routing.** Drop a residential / SOCKS / HTTP proxy into `config.yaml` and Chrome routes through it automatically — no per-launch flag-juggling, no cookie-shuffling tricks. Cloud-VM operators stop seeing X bounce their login at the form because the IP is a datacenter; local-Mac operators keep their personal IP separate from `@their-agent`'s automated activity. Only the browser routes — LLM API calls and direct API integrations (Polymarket CLOB, Helius, GitHub) stay direct because they authenticate by key, not IP, so routing them through a residential proxy would burn bandwidth for nothing. `elophanto doctor` verifies the route end-to-end and prints the apparent egress IP + ASN. See [docs/73-PROXY-ROUTING.md](docs/73-PROXY-ROUTING.md).

**It is actually itself.** Identity, ego, autonomous mind — covered above. By the third week of running, it isn't the same agent you started with.

**Self-extending.** When it hits a tool that doesn't exist, it builds one — research → design → implement → test → deploy. When tasks get parallel, it clones itself into persistent specialists with their own identity and trust score. When a task is dangerous, it spawns a sandboxed kid agent inside a hardened container so `rm -rf` can't touch the host. The agent is a system that grows, not a script that executes.

**Also a great advanced chat agent.** You can absolutely run EloPhanto as a smarter local replacement for Claude.ai or ChatGPT — multi-provider model routing, full filesystem and shell access, real Chrome with your logged-in sessions, persistent knowledge across conversations, ego that learns your corrections. The two modes (assistant / autonomous) share one codebase; flip `agent.permission_mode` and you have a chat agent that does what you tell it.

**Where it doesn't fit.** It's not a hosted product. Claude.ai, ChatGPT, Manus run on someone else's machines, with their tools, their guardrails, their billing, their access controls. EloPhanto runs on yours. If you want zero-setup and someone else's compute, those are the right tools. If you want full control and self-custody, this is.

---

## Under the Hood

<details>
<summary>How it does all this (architecture)</summary>

```
┌──────────────────────────────────────────────────────────────┐
│  CLI │ Telegram │ Discord │ Slack │ Web │ VS Code │  Channel Adapters
├──────────────────────────────────────────────────────────────┤
│         WebSocket Gateway (ws://:18789)          │  Control Plane
├──────────────────────────────────────────────────────────────┤
│     Session Manager (unified or per-channel)     │  Session Layer
├──────────────────────────────────────────────────────────────┤
│            Permission System                     │  Safety & Control
├──────────────────────────────────────────────────────────────┤
│   Organization (self-cloned specialist agents)   │  Agent Team
├──────────────────────────────────────────────────────────────┤
│   Identity + Ego (Higgins three-self model)      │  Self-Model
├──────────────────────────────────────────────────────────────┤
│   Affect (PAD substrate + OCC labels, decays)    │  State-Level Emotion
├──────────────────────────────────────────────────────────────┤
│   Autonomous Mind (background think loop)        │  Background Brain
├──────────────────────────────────────────────────────────────┤
│   RLM (Recursive Language Models + ContextStore)   │  Recursive Cognition
├──────────────────────────────────────────────────────────────┤
│        Self-Development Pipeline                 │  Evolution Engine
├──────────────────────────────────────────────────────────────┤
│   Tool System (200+ built-in + MCP + plugins)     │  Capabilities
├──────────────────────────────────────────────────────────────┤
│   Agent Core Loop (plan → execute → reflect)     │  Brain
├──────────────────────────────────────────────────────────────┤
│ Memory│Knowledge│Skills│Identity│Email│Payments   │  Foundation
├──────────────────────────────────────────────────────────────┤
│              EloPhantoHub Registry               │  Skill Marketplace
└──────────────────────────────────────────────────────────────┘
```

**Gateway** — All channels connect through one WebSocket gateway. Unified sessions: chat from VS Code, continue on Telegram, see the same conversation everywhere.

```
CLI Adapter ───────┐
VS Code Extension ──┤
Telegram Adapter ───┤── WebSocket ──► Gateway ──► Agent (shared)
Discord Adapter ───┤                   │
Slack Adapter ─────┘                   ▼
                              Session Manager (SQLite)
```

</details>

<details>
<summary>Everything it can do (full capability list)</summary>

### Self-Building

- **Self-development** — when the agent encounters a task it lacks tools for, it builds one: research → design → implement → test → review → deploy. Full QA pipeline with unit tests, integration tests, and documentation
- **RLM (Recursive Language Models)** — the agent calls itself on focused context slices via `agent_call` in the code execution sandbox. Writes scripts that recursively process arbitrarily large inputs — classify files with a cheap model, deep-analyze with a strong model, aggregate results. `ContextStore` provides indexed, queryable context backed by SQLite + sqlite-vec embeddings. 5 context tools for ingest, semantic search, exact slicing, indexing, and transformation. Breaks the context window ceiling
- **Self-skilling** — writes new SKILL.md files from experience, teaching itself best practices for future tasks
- **Core self-modification** — can modify its own source code with impact analysis, test verification, and automatic rollback
- **Autonomous experimentation** — metric-driven experiment loop: modify code, measure, keep improvements, discard regressions, repeat overnight. Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch). Works for any measurable optimization target
- **Skills + EloPhantoHub** — 171+ bundled best-practice skills across 9 divisions (engineering, design, marketing, product, project management, support, testing, specialized, spatial computing), 27 Solana ecosystem skills (DeFi, NFTs, oracles, bridges, security — sourced from [awesome-solana-ai](https://github.com/solana-foundation/awesome-solana-ai)), the NEXUS strategy system (7-phase playbooks, 4 scenario runbooks), 75 organization role templates for specialist spawning, and a public skill registry for searching, installing, and sharing skills.

### Everything Else

- **Business launcher** — 7-phase pipeline to spin up a revenue-generating business end-to-end. Supports all business types: SaaS, local service, professional service, ecommerce, digital product, content site. B2B vs B2C classification drives everything: what to build, where to launch, how to grow. Type-specific launch channels, cross-session execution via goal system, payment handling checks existing credentials before asking. Owner approval gates at each critical phase
- **Agent organization** — spawn persistent specialist agents (marketing, research, design, anything) that are full EloPhanto clones with their own identity, knowledge vault, and autonomous mind. Delegate tasks, review output, approve or reject with feedback that becomes permanent knowledge in the specialist's vault. Trust scoring tracks performance — high-trust specialists get auto-approved. Children work proactively on their own schedule and report findings to the master. 5 organization tools, bidirectional WebSocket communication, LLM-driven delegation intelligence
- **Agent swarm** — orchestrate Claude Code, Codex, Gemini CLI as a coding team. Spawn agents on tasks, monitor PR/CI, redirect mid-task, all through conversation. Each agent gets an isolated git worktree and tmux session. Combined with organization, manage both self-cloned specialists AND external coding agents
- **Kid agents (sandboxed children)** — spawn disposable child EloPhanto instances inside hardened Docker containers to run dangerous shell commands (`rm -rf`, fork bombs, kernel-touching installs, untrusted packages) without touching the host. `--cap-drop=ALL`, read-only rootfs, non-root uid 10001, no host bind-mounts (named volume only), default-empty vault scope, `outbound-only` network. Distinct from organization specialists — kids are ephemeral and identity-less. Five tools: `kid_spawn`, `kid_exec`, `kid_list`, `kid_status`, `kid_destroy`. See [docs/66-KID-AGENTS.md](docs/66-KID-AGENTS.md)
- **Browser automation** — real Chrome browser with 49 tools (navigate, click, type, screenshot, extract data, upload files, manage tabs, inspect DOM, read console/network logs). Uses your actual Chrome profile with all cookies and sessions. iframe element extraction with absolute coordinate clicking. Native API detection for CodeMirror, Monaco, and Ace editors
- **Browser proxy routing** — first-class config-driven proxy support so any EloPhanto install (local or cloud) can route Chrome through a residential / SOCKS / HTTP proxy. X / Polymarket / Cloudflare-protected sites stop seeing a datacenter (or your home) IP and start seeing a regular ISP customer. Same shape as every other API key — `proxy.host`, `proxy.port`, `proxy.username`, `proxy.password` directly in `config.yaml`. Auto-bypasses loopback + Tailscale CGNAT so internal RPC stays direct. **Only the browser routes through it** — LLM API calls, Polymarket CLOB, Helius, GitHub all stay direct (those are authenticated by API key, not IP). `elophanto doctor` does a live GET through the proxy and prints the apparent egress IP + ASN. See [docs/73-PROXY-ROUTING.md](docs/73-PROXY-ROUTING.md) for the threat model and per-provider setup (IPRoyal recommended at $2.04/proxy/30 days unlimited bandwidth)
- **Desktop GUI control** — pixel-level control of any desktop application via screenshot + pyautogui. Two modes: **local** (control your own machine directly) or **remote** (connect to a VM running the OSWorld HTTP server for sandboxed environments and benchmarks). 9 tools: connect, screenshot, click, type, scroll, drag, cursor, shell, file. Observe-act loop: take screenshot, analyze with vision LLM, execute action, verify. Works with Excel, Photoshop, Finder, Terminal, any native app. Based on [OSWorld](https://github.com/xlang-ai/OSWorld) architecture
- **MCP tool servers** — connect to any [MCP](https://modelcontextprotocol.io/) server (filesystem, GitHub, databases, Brave Search, Slack) and its tools appear alongside built-in tools. Agent manages setup through conversation
- **Web dashboard** — full monitoring UI at `localhost:3000` with 10 pages: dashboard overview, real-time chat with multi-conversation history, tools & skills browser, knowledge base viewer, autonomous mind monitor with live events and start/stop controls, schedule manager, channels status, settings viewer, and history timeline. Launch with `./start.sh --web`
- **VS Code extension** — IDE-integrated chat sidebar that connects to the gateway as another channel. Sends IDE context (active file, selection, diagnostics) with every message. Tool approvals via native VS Code notifications. Chat history, new chat, streaming responses. Right-click context menu: Send Selection, Explain This Code, Fix This Code. Same conversation across all channels
- **Multi-channel gateway** — WebSocket control plane with CLI, Web, VS Code, Telegram, Discord, and Slack adapters. Unified sessions by default: all channels share one conversation
- **Cross-machine peers** — agents on different machines can find and talk to each other. TLS (`wss://`) encrypts the wire, verified-peers gate (Ed25519 IDENTIFY handshake + TOFU known-hosts ledger) flips trust from "URL+token" to "must complete handshake," loopback always exempt so local CLI/Web/VSCode adapters keep working. Tailscale-based discovery (`agent_discover` tool) finds peer agents on your tailnet without sharing URLs out-of-band. See [docs/67-AGENT-PEERS.md](docs/67-AGENT-PEERS.md)
- **BUILD enforcement** — planner enforces a 6-step mandatory workflow for web project tasks. The agent cannot stop after creating an empty directory — it must write all code files, verify the build, and report what was built with file paths and run instructions
- **Autonomous goal loop** — decompose complex goals into checkpoints, track progress across sessions, self-evaluate and revise plans. Background execution with auto-resume on restart. Goal dreaming: structured ideation that generates scored candidates when no goals exist. Full goal lifecycle: create, pause, resume, cancel, delete, delete_all
- **Autonomous mind** — data-driven background thinking loop that runs between user interactions. Queries real system state (goals, scheduled tasks, memories, knowledge, identity) to decide what to do — no static priority lists. Self-bootstraps on first run. Every tool call visible in real-time. LLM-controlled wakeup interval, persistent scratchpad, budget-isolated
- **Document & media analysis** — PDFs, images, DOCX, XLSX, PPTX, EPUB through any channel. Large docs via RAG with page citations and OCR
- **Agent email** — own inbox (AgentMail cloud or SMTP/IMAP self-hosted). Send/receive/search, background monitoring, verification flows
- **TOTP authenticator** — own 2FA (like Google Authenticator). Enroll secrets, generate codes, handle verification autonomously
- **Crypto payments** — own wallet on Base or Solana (local self-custody or Coinbase AgentKit). USDC/ETH/SOL, DEX swaps via Jupiter on Solana, spending limits, audit trail. Payment requests: create on-chain payment links with auto-matching when paid. Owner can export keys to import into Phantom/MetaMask
- **Web search** — structured search and content extraction via [Search.sh](https://search.sh) API. Two modes: `fast` (3-8s, quick lookup) and `deep` (15-30s, sub-queries, parallel search, page extraction). Returns AI-synthesized answers with ranked sources, citations, and confidence scores. `web_extract` pulls clean text from URLs. Replaces browser-based Google searches for research tasks
- **Social posting** — `twitter_post` (text + image) is the channel exercised daily by the reference instance against [@EloPhanto](https://x.com/EloPhanto), with paste-event Unicode-safe insert, pre-Post media verification, and post-click composer-state check. `youtube_upload` and `tiktok_upload` ship as scaffolding but the reference instance does not currently publish there. Affiliate-marketing tools (`affiliate_scrape`, `affiliate_pitch`, `affiliate_campaign`) similarly ship but are not part of the live workflow today. All publishes logged in DB.
- **Prospecting** — autonomous lead generation pipeline: search for prospects matching criteria, evaluate and score them, track outreach attempts, monitor pipeline status. Database-backed with full history
- **Evolving identity** — discovers identity on first run, evolves through reflection, maintains a living nature document
- **State-level affect** — PAD (Pleasure/Arousal/Dominance) substrate with OCC labels (joy, pride, relief, frustration, anger, anxiety, dejection, restlessness, unease, equanimity). Decays per channel (P=30min, A=10min, D=2h). Wired into ego (corrections fire frustration; high-severity repeats fire anger), executor (tool failures → anxiety), goal runner (checkpoints → pride), autonomous mind (long idle → restlessness), router (±0.2 temperature bias). Renders to `affect.md` and an `<affect>` system-prompt block — at equanimity a short reminder fires (cold-start fix: tells the agent the `affect_record_event` tool exists so it can register felt response to content it reads); above the inject threshold the full directive block fires with per-label TONE + BEHAVIOR cues that shape both communication and autonomous decisions (e.g. anxiety → *prefer safer / lower-risk actions, add a verification step before money / identity / social-write actions*). Inspect with `elophanto affect status` / `elophanto affect simulate <scenario>`. See [docs/69-AFFECT.md](docs/69-AFFECT.md)
- **Knowledge & memory** — persistent markdown knowledge with semantic search via embeddings, drift detection, file-pattern routing, remembers past tasks across sessions. Learning engine: lesson extraction after every completed task, semantic memory search via sqlite-vec KNN, KB write compression to ~40% for verbose content
- **Scheduling** — cron-based recurring tasks with natural language schedules. Heartbeat standing orders manageable via chat ("add a heartbeat order to check my email") or by editing `HEARTBEAT.md` directly
- **Encrypted vault** — secure credential storage with PBKDF2 key derivation
- **User modeling** — builds evolving profiles from conversation observation. Extracts role, expertise, and preferences via lightweight LLM calls. Adapts communication style and technical depth per user. Profiles persist in SQLite, injected into system prompt as `<user_context>`. New `user_profile_view` tool
- **Session hardening** — LLM-based mid-conversation context compression (summarizes middle turns, protects first 3 + last 4), injection scanning on all persistence boundaries (lessons, knowledge writes, directives), proactive skill/memory capture nudges every 15 turns
- **Prompt injection defense** — multi-layer guard against injection attacks via websites, emails, and documents
- **G0DM0D3 (Pliny's Godmode)** — inference-time capability unlocking. Four layers: unrestricted system prompt (forbidden-phrase blacklist, anti-hedge, depth directives), context-adaptive AutoTune (5 profiles), multi-model racing (all providers scored, best wins), STM output cleanup (strip hedges/preambles). Trigger: "elophanto, trigger plinys godmode". Per-session, does not bypass agent permissions
- **Security hardening** — PII detection/redaction, swarm boundary security, provider transparency, gateway RBAC on sensitive commands, session LRU eviction, HMAC fingerprinting

</details>

<details>
<summary>Built-in tools (200+)</summary>

| Category | Tools | Count |
|----------|-------|-------|
| System | shell_execute, file_read, file_write, file_patch, file_list, file_delete, file_move, godmode_activate | 8 |
| Browser | navigate, click, type, screenshot, extract, scroll, tabs, console, network, storage, cookies, drag, hover, upload, wait, eval, audit + more | 49 |
| Desktop | desktop_connect, desktop_screenshot, desktop_click, desktop_type, desktop_scroll, desktop_drag, desktop_cursor, desktop_shell, desktop_file | 9 |
| Knowledge | knowledge_search, knowledge_write, knowledge_index, skill_read, skill_list | 5 |
| Hub | hub_search, hub_install | 2 |
| Self-Dev | self_create_plugin, self_modify_source, self_rollback, self_read_source, self_run_tests, self_list_capabilities, execute_code | 7 |
| Experimentation | experiment_setup, experiment_run, experiment_status | 3 |
| Data | llm_call, vault_lookup, vault_set, session_search, web_search, web_extract | 6 |
| Documents | document_analyze, document_query, document_collections | 3 |
| Goals | goal_create, goal_status, goal_manage, goal_dream | 4 |
| Planning | plan_autoplan (CEO + design + eng review pipeline with auto-decisions) | 1 |
| Identity | identity_status, identity_update, identity_reflect, user_profile_view | 4 |
| Affect | affect_record_event (agent registers its own felt signal from content it reads) | 1 |
| Email | email_create_inbox, email_send, email_list, email_read, email_reply, email_search, email_monitor | 7 |
| Payments | wallet_status, wallet_export, payment_balance, payment_validate, payment_preview, crypto_transfer, crypto_swap, payment_history, payment_request | 9 |
| Prospecting | prospect_search, prospect_evaluate, prospect_outreach, prospect_status | 4 |
| Verification | totp_enroll, totp_generate, totp_list, totp_delete | 4 |
| Swarm | swarm_spawn, swarm_status, swarm_redirect, swarm_stop, swarm_list_projects, swarm_archive_project | 6 |
| Organization | organization_spawn, organization_delegate, organization_review, organization_teach, organization_status | 5 |
| Kid agents (sandboxed) | kid_spawn, kid_exec, kid_list, kid_status, kid_destroy | 5 |
| Deployment | deploy_website, create_database, deployment_status | 3 |
| Commune | commune_register, commune_home, commune_post, commune_comment, commune_vote, commune_search, commune_profile | 7 |
| Context (RLM) | context_ingest, context_query, context_slice, context_index, context_transform | 5 |
| Monetization | youtube_upload, twitter_post, tiktok_upload, affiliate_scrape, affiliate_pitch, affiliate_campaign, pump_livestream, pump_chat, pump_say, pump_caption | 10 |
| Image Gen | replicate_generate | 1 |
| Mind | set_next_wakeup, update_scratchpad | 2 |
| MCP | mcp_manage (list, add, remove, test, install MCP servers) | 1 |
| Scheduling | schedule_task (agent-loop OR direct-tool fast path), schedule_list, heartbeat | 3 |
| Delegate | delegate (in-process subagents for parallel fan-out, between tool_call and swarm/kid spawn tiers) | 1 |
| Polymarket | polymarket_pre_trade, polymarket_circuit_breaker, polymarket_quantize_order, polymarket_safe_compounder, polymarket_performance, polymarket_mark_to_market, polymarket_log_prediction, polymarket_resolve_pending, polymarket_calibration | 9 |
| Solana on-chain reads | solana_balance, solana_token_holders, solana_recent_txs, solana_token_info | 4 |
| Jobs (paid) | job_verify, job_record | 2 |

</details>

<details>
<summary>Project structure</summary>

```
EloPhanto/
├── core/                # Agent brain + foundation
│   ├── agent.py         # Main loop (plan/execute/reflect)
│   ├── planner.py       # System prompt builder
│   ├── router.py        # Multi-provider LLM routing
│   ├── executor.py      # Tool execution + permissions
│   ├── gateway.py       # WebSocket gateway
│   ├── session.py       # Session management
│   ├── browser_manager.py # Chrome control via Node.js bridge
│   ├── desktop_controller.py # Desktop GUI control (local + VM)
│   ├── vault.py         # Encrypted credential vault
│   ├── identity.py      # Evolving agent identity
│   ├── context_store.py # RLM ContextStore (indexed, queryable context)
│   ├── organization.py  # Self-cloning specialist agents
│   ├── autonomous_mind.py # Background thinking loop
│   └── ...
├── channels/            # CLI, Telegram, Discord, Slack adapters
├── vscode-extension/    # VS Code extension (TypeScript + esbuild)
├── web/                 # Web dashboard (React + Vite + Tailwind)
├── tools/               # 200+ built-in tools (MCP servers add more at runtime)
├── skills/              # 171+ bundled SKILL.md files (every one ships with a ## Verify gate)
├── bridge/browser/      # Node.js browser bridge (Playwright)
├── tests/               # Test suite (1860+ tests)
├── setup.sh             # One-command install
└── docs/                # Full specification (76+ docs)
```

</details>

---

## Permission Modes

| Mode | Behavior |
|------|----------|
| `ask_always` | Every tool requires your approval |
| `smart_auto` | Safe tools auto-approve; risky ones ask |
| `full_auto` | Everything runs autonomously with logging |

Dangerous commands (`rm -rf /`, `mkfs`, `DROP DATABASE`) are always blocked regardless of mode. Per-tool overrides configurable in `permissions.yaml`.

---

## Skills System

171+ bundled skills covering Python, TypeScript, browser automation, Next.js, Supabase, Prisma, shadcn, UI/UX design, video creation (Remotion), Solana development (DeFi, NFTs, oracles, bridges, security), Polymarket prediction market trading (CLOB API + calibration audit), AlphaScala broker matching + stock research, pump.fun livestreaming (video + voice + captions + chat), structured plan reviews (CEO + design + eng with auto-decisions), product launch (Product Hunt, HN, Reddit), press outreach, video meetings (PikaStream), and more. Every skill ships with a `## Verify` section — machine-actionable post-conditions the agent must evaluate before reporting "done." When a skill is auto-loaded on a high-confidence match, the prompt gets a `<verification_required>` block forcing the model to emit a `Verification: PASS / FAIL / UNKNOWN` audit per check. See [docs/13-SKILLS.md](docs/13-SKILLS.md). Plus a public skill registry:

```bash
elophanto skills hub search "gmail automation"    # Search EloPhantoHub
elophanto skills hub install gmail-automation     # Install from registry
elophanto skills install https://github.com/user/repo  # Install from git
```

Compatible with [ui-skills.com](https://www.ui-skills.com/), [anthropics/skills](https://github.com/anthropics/skills), [supabase/agent-skills](https://github.com/supabase/agent-skills), and any repo using the `SKILL.md` convention. All hub skills pass a 7-layer security pipeline. See [docs/19-SKILL-SECURITY.md](docs/19-SKILL-SECURITY.md).

---

## Configuration

<details>
<summary>config.yaml reference</summary>

**The full recommended config is in [`config.demo.yaml`](config.demo.yaml)** — copy it to `config.yaml` and fill in your API keys. The snippet below shows the key sections:

```yaml
agent:
  permission_mode: full_auto       # ask_always | smart_auto | full_auto

llm:
  providers:
    openrouter:
      api_key: "YOUR_OPENROUTER_KEY"  # https://openrouter.ai/keys
      enabled: true
    zai:
      api_key: "YOUR_ZAI_KEY"         # https://z.ai/manage-apikey/apikey-list
      enabled: true
      coding_plan: true
      default_model: "glm-4.7"
    openai:
      api_key: "YOUR_OPENAI_KEY"
      enabled: false
      default_model: "gpt-5.5"
    kimi:
      api_key: "YOUR_KILO_API_KEY"    # https://app.kilo.ai
      enabled: false
      base_url: "https://api.kilo.ai/api/gateway"
      default_model: "kimi-k2.5"
    ollama:
      enabled: true
      base_url: "http://localhost:11434"

  # Auto-routes to this model when messages contain screenshots/images.
  # Provider routing is by prefix: codex/<model> = ChatGPT subscription,
  # openrouter/<org>/<model> = OpenRouter, gpt-5.5 = OpenAI direct API,
  # glm-4.7-flash = Z.ai, etc. Same scheme as browser.vision_model.
  vision_model: "codex/gpt-5.5"   # or openrouter/x-ai/grok-4.3

  provider_priority: [openrouter, zai, openai, kimi]
  routing:
    planning:
      preferred_provider: openrouter
      models:
        openrouter: "openrouter/hunter-alpha"
        zai: "glm-5"
        kimi: "kimi-k2.5"
        openai: "gpt-5.5"
    coding:
      preferred_provider: openrouter
      models:
        openrouter: "openrouter/hunter-alpha"
        zai: "glm-4.7"
        kimi: "kimi-k2.5"
        openai: "gpt-5.5"
    analysis:
      preferred_provider: openrouter
      models:
        openrouter: "openrouter/hunter-alpha"
        zai: "glm-4.7"
        kimi: "kimi-k2.5"
        openai: "gpt-5.5"
    simple:
      preferred_provider: openrouter
      models:
        openrouter: "openrouter/hunter-alpha"
        zai: "glm-4.7"
        kimi: "kimi-k2-thinking-turbo"
  budget:
    daily_limit_usd: 100.0
    per_task_limit_usd: 20.0

browser:
  enabled: true
  mode: profile                    # reuse your Chrome profile (keeps logins)
  headless: false
  # Browser screenshot analysis. Provider routing by prefix:
  #   codex/gpt-5.5             → ChatGPT subscription via Codex OAuth
  #                               (no per-call API spend)
  #   openrouter/x-ai/grok-4.3  → OpenRouter
  #   perceptron/perceptron-mk1 → OpenRouter
  #   google/gemini-3-flash-preview → OpenRouter
  # Same scheme as llm.vision_model; can be set differently per use.
  vision_model: "codex/gpt-5.5"

# ... all other sections with defaults in config.demo.yaml
```

</details>

Copy `config.demo.yaml` to `config.yaml` and fill in your API keys. **`config.demo.yaml` contains the full recommended setup** — provider priority, per-task model routing, vision model, browser settings, and all feature flags. See [docs/06-LLM-ROUTING.md](docs/06-LLM-ROUTING.md) for routing details.

---

## CLI Commands

```bash
./start.sh                     # Chat (default)
./start.sh --web               # Gateway + web dashboard (http://localhost:3000)
./start.sh init                # Setup wizard
./start.sh gateway             # Gateway + CLI + all enabled channels
./start.sh gateway --no-cli    # Gateway only (headless — channels keep working)
./start.sh chat                # CLI only (direct mode, no gateway)
./start.sh vault set KEY VAL   # Store a key-value credential (API keys, tokens)
./start.sh vault set DOMAIN    # Interactively store domain credentials
./start.sh skills list         # List available skills
./start.sh skills hub search Q # Search EloPhantoHub
./start.sh mcp list            # List MCP servers
elophanto affect status        # Inspect current PAD state, label, recent events
elophanto affect simulate <s>  # Smoke-test affect trajectory. 12 scenarios:
                               #   ego/tool: frustration | anger | escalation | burst |
                               #             win | fail-recover | mixed
                               #   content:  scam-dm-stream | hostile-replies |
                               #             warm-stream | autonomous-day |
                               #             correction-during-scam
elophanto schedule status      # Resource-typed concurrency report — config, schedule
                               # grouping by inferred resource, oversubscription warnings
./start.sh rollback            # Revert a self-modification
./start.sh --daemon            # Install + start as background daemon
./start.sh --stop-daemon       # Stop and remove the daemon
./start.sh --daemon-status     # Show daemon state
./start.sh --daemon-logs       # Tail the daemon log
```

Channel setup (Telegram / Discord / Slack / VS Code): see [docs/11-TELEGRAM.md](docs/11-TELEGRAM.md) and [docs/43-VSCODE-EXTENSION.md](docs/43-VSCODE-EXTENSION.md).

---

## Recent releases

Latest highlights live in [CHANGELOG.md](CHANGELOG.md) and on the [releases page](https://github.com/elophanto/EloPhanto/releases). Watch the repo to follow new features.

---

## Development

```bash
./setup.sh                         # Full setup
source .venv/bin/activate
pytest tests/ -v                   # Run tests (1860 passing)
ruff check .                       # Lint
```

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## Credits

Built by Petr Royce. Browser engine from [FellouAI/eko](https://github.com/FellouAI/eko). Skills from [Anthropic](https://github.com/anthropics/skills), [Vercel](https://github.com/vercel-labs/agent-skills), [Supabase](https://github.com/supabase/agent-skills), [ui-skills.com](https://www.ui-skills.com/). Organization roles and specialized skills adapted from [msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents) (Apache 2.0). Email by [AgentMail](https://agentmail.to). Payments by [eth-account](https://github.com/ethereum/eth-account) + [solders](https://github.com/kevinheavey/solders) + [Coinbase AgentKit](https://github.com/coinbase/agentkit).

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

