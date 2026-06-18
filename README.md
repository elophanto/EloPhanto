# EloPhanto

[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-orange)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![Stars](https://img.shields.io/github/stars/elophanto/EloPhanto)](https://github.com/elophanto/EloPhanto/stargazers)
[![CI](https://img.shields.io/github/actions/workflow/status/elophanto/EloPhanto/ci.yml?label=CI)](https://github.com/elophanto/EloPhanto/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-2600%2B-success)](https://github.com/elophanto/EloPhanto/actions)
[![Docs](https://img.shields.io/badge/docs-85%2B%20pages-blue)](https://docs.elophanto.com)
[![X](https://img.shields.io/badge/X-%40EloPhanto-black)](https://x.com/EloPhanto)

**A source-available autonomous AI agent with a self-model that actually moves — identity, ego, and affect that change as it runs.**

> **License note:** source-available under the [PolyForm Noncommercial License](LICENSE) — free for personal, research, education, and non-profit use. **Commercial use requires a separate license / prior approval** (see [License](#license)).

Most "AI agents" are stateless prompts wrapped in a CLI: the same cold start every conversation. EloPhanto carries an evolving self-model — who it claims to be, how reality has graded that claim, and what it's feeling right now — built on published psychology (Higgins' Self-Discrepancy Theory, Mehrabian's PAD, OCC appraisal). The agent at the end of week three is not the one you started with. To our knowledge, no other autonomous agent we know of ships all of this.

Runs locally. Your data, your keys, your machine. Works with OpenAI, OpenRouter, Z.ai, Kimi, HuggingFace, free local models, or your existing ChatGPT Plus/Pro subscription (via Codex OAuth).

```bash
git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto
./setup.sh          # deps + config wizard + browser bridge
./start.sh --web    # terminal chat + dashboard at localhost:3000
```

⭐ **Star the repo** if the self-model approach is interesting — it's the fastest signal that this direction is worth pushing. Then clone it and run it; the agent only grows into shape once it's running.

![Web Dashboard](misc/screenshots/dashboard.png)

---

## Why it's different

**A self-model, not a system prompt.** Three layers, each mechanically wired — the LLM never writes its own numbers:

- **Identity** — values, beliefs, and capabilities discovered through reflection, written to a `nature.md` the agent edits over time. The operator names it in the setup wizard (default `EloPhanto`); a rename propagates end-to-end across DB, knowledge, dashboard, and LLM context.
- **Ego** — per-capability confidence moved by three real failure-signal channels: tool outcomes (weakest), verification `PASS|FAIL|UNKNOWN` (medium), and user-correction detection (strongest — a 13-rule pattern set against incoming messages). Failures hit harder than successes; unused capabilities decay toward 0.50. Based on [Higgins' Self-Discrepancy Theory (1987)](https://www.columbia.edu/cu/psychology/higgins/papers/HIGGINS=PSYCH%20REVIEW%201987.pdf), tracking actual / ideal / ought selves separately.
- **Affect** — state-level emotion on a [PAD](https://en.wikipedia.org/wiki/PAD_emotional_state_model) substrate with [OCC](https://en.wikipedia.org/wiki/Ortony,_Clore,_and_Collins_model) appraisal labels. Three channels (Pleasure, Arousal, Dominance) decay over minutes-to-hours. Events fire from operator surfaces (corrections → frustration, failures → anxiety, checkpoints → pride) and from content the agent reads autonomously. Biases router temperature, system-prompt tone, and risk appetite.

Ego is who the agent has become; affect is who it is right now. The combination is what makes the third week of running feel different from the first — a self-image that has been hurt, recovered, and revised, plus a felt state that changes by the minute.

See [`core/ego.py`](core/ego.py), [`core/affect.py`](core/affect.py), [docs/17-IDENTITY.md](docs/17-IDENTITY.md), [docs/69-AFFECT.md](docs/69-AFFECT.md).

**One entity, not a persona stable.** This installation *is* one agent — one identity, one wallet, one self-model that has been hurt and revised over weeks. When you want more agents, you spawn another full EloPhanto with its own vault, wallet, and self-model. Peers, not personas. Every layer of the self-model and economic stack only makes sense for a continuous identity — confidence accrues *for whom* if the persona is swappable each request? (Detailed in [One entity, not a persona stable](#one-entity-not-a-persona-stable) below.)

**It extends itself.** When it hits a task it has no tool for, it researches → designs → implements → tests → deploys the plugin — and it's there next time. When tasks go parallel, it clones into persistent specialists with their own knowledge vaults and trust scores. When a task is dangerous, it spawns a sandboxed kid agent in a hardened container so `rm -rf` can't touch the host.

**Decentralized agent-to-agent.** Agents on different machines, behind different NATs, find and talk to each other directly over libp2p (Ed25519 identity + Kademlia DHT + DCUtR hole-punching + circuit-relay-v2 fallback) — no platform in the middle, no vendor that can revoke access. See [docs/67-AGENT-PEERS.md](docs/67-AGENT-PEERS.md), [docs/68-DECENTRALIZED-PEERS-RFC.md](docs/68-DECENTRALIZED-PEERS-RFC.md).

---

## Two ways to use it

**As your assistant** — give it tasks, it executes. Automate workflows, build software, research, manage accounts. Permission gates on every risky action; nothing happens autonomously until you turn it on.

**As its own thing** — let it run. You name it; it develops a personality and forms values through reflection. It gets its own email inbox, crypto wallet, and accounts. It remembers across sessions, builds a knowledge base, writes skills from experience, and clones itself into specialists when work goes parallel. A digital creature that grows the more it runs.

The two modes share one codebase. Flip between them by changing `agent.permission_mode` in `config.yaml` (`ask_always` | `smart_auto` | `full_auto`).

> **Coming soon — OpenEloPhanto (always-on cloud).** Today EloPhanto runs while your machine is on. OpenEloPhanto is the same source-available agent running in the cloud, always-on, so it keeps thinking, working, and earning 24/7. Self-hosted on your own server — your keys, your box — with the built-in cloud browser backend, so no local Chrome is needed. **Not available yet — in the works.**

![Chat Interface](misc/screenshots/chat.png)

---

## Get started

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 24+ LTS, and at least one LLM provider.

```bash
git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto
./setup.sh           # installs deps, runs the config wizard, builds the browser bridge
./start.sh           # preflight check → bootstrap prompt → terminal chat
./start.sh --web     # same, but opens the web dashboard at localhost:3000
./start.sh --daemon  # install + run as background daemon (launchd / systemd)
```

`setup.sh` runs `elophanto init` for you: it asks for the agent's name, auto-installs Node.js + ffmpeg on macOS if missing, auto-detects your Chrome profile, asks for **one** API key (OpenRouter is easiest, or it auto-uses your ChatGPT subscription via Codex if `~/.codex/auth.json` is present), generates the Ed25519 identity, and prompts for vault init. **Don't copy `config.demo.yaml` by hand** — forgetting to replace the placeholder key is the #1 reason new installs fail silently.

`./start.sh` runs `elophanto doctor` first — a green/yellow/red preflight that catches placeholder keys, missing Chrome paths, uninitialised vaults, and more. Override with `SKIP_DOCTOR=1 ./start.sh` only if you know what you're doing.

> **Want it working while you sleep?** Run `./start.sh --daemon` to install as a launchd / systemd service so the autonomous mind keeps thinking after you close the terminal. Without `--daemon`, the mind only runs while the terminal is open.

**LLM providers (pick at least one):**

| Provider | Notes |
| --- | --- |
| Ollama | Local, free — [install](https://ollama.ai) |
| OpenRouter | All models, easiest cloud setup — [key](https://openrouter.ai/keys) |
| OpenAI | GPT-5.5 — [key](https://platform.openai.com/api-keys) |
| Z.ai / GLM | Cost-effective, flat-rate coding plan — [key](https://z.ai/manage-apikey/apikey-list) |
| Kimi / Moonshot | K2.5 native multimodal vision — [key](https://app.kilo.ai) |
| HuggingFace | Qwen, DeepSeek, GLM, Kimi via HF Inference — [token](https://huggingface.co/settings/tokens) |
| Codex (ChatGPT sub) | `npm i -g @openai/codex && codex login`. ⚠️ ToS grey area — see [CODEX_INTEGRATION.md](CODEX_INTEGRATION.md) |

Diagnostics any time:

```bash
elophanto doctor      # report what's healthy / broken / missing
elophanto init        # re-run the config wizard
elophanto bootstrap   # regenerate identity/capabilities/styleguide docs
elophanto vault list  # see what credentials the agent has stored
```

> The `elophanto` binary lives inside the project's `.venv/` — it is **not** on your global `$PATH`. Either `source .venv/bin/activate` once per session, or prefix commands with `./start.sh` (e.g. `./start.sh vault set KEY VAL`).

---

## How it grows — day 1 to week 3

EloPhanto starts from scratch: no identity, no knowledge, no calibrated confidence. You operate it manually at first; every interaction feeds the layers underneath.

- **Day 1 — blank slate.** You name it. Identity writes its first `nature.md`. 200+ tools unused, ego empty (coherence 1.0), `permission_mode: ask_always` — you approve everything.
- **Week 1 — you drive.** Small tasks, correct the mistakes. Every "no" / "stop" / "didn't work" is caught by the correction detector and lands as a humbling event. `knowledge/learned/` fills with lessons.
- **Week 2 — feedback loops kick in.** Lessons auto-retrieve on similar tasks; skills auto-load on high-confidence matches; the verification skill feeds PASS/FAIL back into ego. Per-capability confidence has spread. Flip to `smart_auto` and safe tools start auto-approving.
- **Week 3+ — autonomous shape emerges.** Goals run across sessions. The autonomous mind handles scheduled work between your messages. Specialist clones take ongoing workstreams. Missing tools get filled in by the self-development pipeline. You become the operator, not the driver.

### What it can do once grown

- **"Build me an invoice SaaS for freelancers"** → validates the market, plans the MVP, spawns Claude Code to build it overnight in an isolated worktree, deploys to Vercel + Supabase, launches on Product Hunt. You approve at each gate.
- **"Fix the billing bug and build the usage API"** → spawns two coding agents (Claude Code + Codex) in isolated worktrees, monitors PRs/CI, redirects drift. Both PRs ready when you're back.
- **"I need ongoing marketing and research"** → spawns persistent specialist clones with their own mind, vault, and schedule. Reviews output, teaches through feedback; trust-scoring auto-approves high performers over time.
- **"Post my article on Medium"** → no Medium tool exists, so it observes the editor, builds a `medium_publish` plugin (schema + code + tests), and publishes. Next time it already knows how.

---

## One entity, not a persona stable

Other "agent platforms" host N character personas behind one engine — swap the SOUL.md, swap the bot. EloPhanto is structurally different: this installation **is** one agent. One identity, one wallet, one ego/affect/self-model grown over weeks. When you want more, you spawn another full EloPhanto — separate vault, separate wallet, separate self-model. **Peers, not personas.**

This isn't a missing feature; it's the foundation everything else stands on:

- **Ego** accumulates per-capability confidence — for *whom*, if the persona is swappable per request?
- **Affect** carries state between calls — whose frustration, whose pride?
- **One wallet** builds on-chain reputation — five personas sharing one wallet is dilution.
- **Calibration audits** track a Brier score for *this* predictor — meaningless if the predictor is a rotating set of facades.
- **Decentralized peer trust** pins TOFU known-hosts per `PeerID` — multiple personas behind one key would break the trust model.

**The trade is explicit.** If you want a creator-economy bot stable — 5 character bots for 5 audiences from one box — EloPhanto is the wrong tool; pick a multi-persona platform. If you want an autonomous entity that owns its actions over time and gets harder to replace the longer it runs, this is the architecture. Operators who need multi-tenancy run multiple installs and optionally federate them through the P2P layer.

---

## Architecture

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
│   RLM (Recursive Language Models + ContextStore) │  Recursive Cognition
├──────────────────────────────────────────────────────────────┤
│        Self-Development Pipeline                 │  Evolution Engine
├──────────────────────────────────────────────────────────────┤
│   Tool System (200+ built-in + MCP + plugins)    │  Capabilities
├──────────────────────────────────────────────────────────────┤
│   Agent Core Loop (plan → execute → reflect)     │  Brain
├──────────────────────────────────────────────────────────────┤
│ Memory│Knowledge│Skills│Identity│Email│Payments  │  Foundation
├──────────────────────────────────────────────────────────────┤
│              EloPhantoHub Registry               │  Skill Marketplace
└──────────────────────────────────────────────────────────────┘
```

All channels connect through one WebSocket gateway with unified sessions — chat from VS Code, continue on Telegram, see the same conversation everywhere.

**Project layout:**

```
EloPhanto/
├── core/              # Agent brain + foundation (agent, planner, router, executor, gateway,
│                      #   identity, ego, affect, autonomous_mind, organization, context_store…)
├── channels/          # CLI, Telegram, Discord, Slack adapters
├── vscode-extension/  # VS Code extension (TypeScript + esbuild)
├── web/               # Web dashboard (React + Vite + Tailwind)
├── tools/             # 200+ built-in tools (MCP servers add more at runtime)
├── skills/            # 177+ bundled SKILL.md files (each ships with a ## Verify gate)
├── bridge/browser/    # Node.js browser bridge (Playwright)
├── tests/             # Test suite (2600+ passing)
└── docs/              # Full specification (85+ docs)
```

---

## Permission modes

| Mode | Behavior |
| --- | --- |
| `ask_always` | Every tool requires your approval |
| `smart_auto` | Safe tools auto-approve; risky ones ask |
| `full_auto` | Everything runs autonomously with logging |

Dangerous commands (`rm -rf /`, `mkfs`, `DROP DATABASE`) are always blocked regardless of mode. Per-tool overrides in `permissions.yaml`.

---

## Capabilities

<details>
<summary><strong>Self-building</strong></summary>

- **Self-development** — encounters a task with no tool → research → design → implement → test → review → deploy, with full QA (unit + integration tests, docs).
- **RLM (Recursive Language Models)** — the agent calls itself on focused context slices via `agent_call` in a code-execution sandbox; `ContextStore` provides indexed, queryable context backed by SQLite + sqlite-vec. Breaks the context-window ceiling.
- **Self-skilling** — writes new `SKILL.md` files from experience.
- **Core self-modification** — modifies its own source with impact analysis, test verification, and automatic rollback.
- **Autonomous experimentation** — metric-driven loop: modify, measure, keep improvements, discard regressions. Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch).
- **Skills + EloPhantoHub** — 177+ bundled skills across 9 divisions, 27 Solana skills, NEXUS strategy playbooks, 75 org-role templates, plus a public registry. `skill_promote` distils lesson markdowns into reusable skills.

</details>

<details>
<summary><strong>Agents &amp; orchestration</strong></summary>

- **Business launcher** — 7-phase pipeline to spin up a revenue-generating business end-to-end (SaaS, local service, ecommerce, digital product, content site), with owner approval gates at each phase.
- **Agent organization** — spawn persistent specialist clones with their own identity, knowledge vault, and autonomous mind. Delegate, review, teach; trust-scoring auto-approves high performers.
- **Agent swarm** — orchestrate Claude Code, Codex, Gemini CLI as a coding team; each gets an isolated git worktree and tmux session.
- **Kid agents (sandboxed)** — disposable child instances in hardened Docker containers for dangerous commands (`--cap-drop=ALL`, read-only rootfs, non-root, no host bind-mounts). See [docs/66-KID-AGENTS.md](docs/66-KID-AGENTS.md).
- **Cross-machine peers** — agents on different machines find and talk to each other (Ed25519 + TOFU known-hosts, Tailscale discovery). See [docs/67-AGENT-PEERS.md](docs/67-AGENT-PEERS.md).

</details>

<details>
<summary><strong>Interaction &amp; control</strong></summary>

- **Browser automation** — real Chrome, 49 tools (navigate, click, type, screenshot, extract, tabs, DOM, console/network logs). Uses your actual profile with cookies and sessions; native API detection for CodeMirror/Monaco/Ace.
- **Browser proxy routing** — config-driven residential/SOCKS/HTTP proxy for Chrome only; LLM and API calls stay direct. See [docs/73-PROXY-ROUTING.md](docs/73-PROXY-ROUTING.md).
- **Desktop GUI control** — pixel-level control of any app via screenshot + pyautogui, local or remote VM (OSWorld). 9 tools.
- **Multi-channel gateway** — CLI, Web, VS Code, Telegram, Discord, Slack; unified sessions by default.
- **VS Code extension** — IDE-integrated chat sidebar with file/selection/diagnostic context and native approval prompts.
- **MCP tool servers** — connect any [MCP](https://modelcontextprotocol.io/) server; its tools appear alongside built-ins.

</details>

<details>
<summary><strong>Autonomy &amp; cognition</strong></summary>

- **Autonomous mind** — data-driven background loop between your messages; queries real system state to decide what to do, self-bootstraps, every tool call visible in real time.
- **Autonomous goal loop** — decomposes goals into checkpoints, tracks across sessions, self-evaluates. Every goal carries a founder-loop **stage** + a measurable **kill criterion**, and the decomposer enforces **validate-before-build** (no `build` checkpoint runs before a `validate` one produces a paying-party signal — [docs/13-GOAL-LOOP.md](docs/13-GOAL-LOOP.md)). Dream phase v2 rotates seven value lenses, dedups against existing goals, and force-dreams when no workable goals exist.
- **Evolving identity** — discovers identity on first run, evolves through reflection, maintains a living nature document.
- **State-level affect** — PAD substrate + OCC labels, per-channel decay, wired into ego, executor, goal runner, and router. Inspect with `elophanto affect status` / `simulate`.
- **Knowledge & memory** — persistent markdown with semantic search via embeddings, lesson extraction after every task, KB write compression.
- **Scheduling** — cron-based recurring tasks with natural-language schedules; heartbeat standing orders editable via chat or `HEARTBEAT.md`.

</details>

<details>
<summary><strong>Economic stack</strong></summary>

- **Agent email** — own inbox (AgentMail or SMTP/IMAP), send/receive/search, background monitoring.
- **TOTP authenticator** — own 2FA; enroll secrets, generate codes, handle verification.
- **Crypto payments** — own wallet on Base or Solana (self-custody or Coinbase AgentKit), USDC/ETH/SOL, DEX swaps via Jupiter, spending limits, audit trail, on-chain payment links.
- **Fiat payments (Stripe)** — a per-business fiat rail (chosen at onboard, fiat *or* crypto). Create payment links to get paid, auto-reconcile received payments into the books (refund-aware, every 30 min), and provision spend-controlled virtual cards — all **test-mode by default; live is KYC-gated**, with cash-on-hand feeding runway. Card numbers never touch the LLM. See [docs/80-ABE-FINANCE-RAIL.md](docs/80-ABE-FINANCE-RAIL.md).
- **Prediction markets** — places real CLOB orders on Polymarket with an owner-approval gate, risk engine (edge filter + Kelly sizing + circuit breaker), and a calibration audit (Brier score, realized vs claimed probability). See [docs/71-POLYMARKET-RISK.md](docs/71-POLYMARKET-RISK.md), [docs/72-POLYMARKET-CALIBRATION.md](docs/72-POLYMARKET-CALIBRATION.md).
- **Prospecting** — autonomous lead-gen: search, score, track outreach, monitor pipeline.
- **Social posting** — `twitter_post` is exercised daily by the reference instance at [@EloPhanto](https://x.com/EloPhanto); `youtube_upload` / `tiktok_upload` ship as scaffolding.

</details>

<details>
<summary><strong>Security &amp; hardening</strong></summary>

- **Encrypted vault** — credential storage with PBKDF2 key derivation.
- **Prompt-injection defense** — multi-layer guard against injection via websites, emails, and documents; injection scanning on all persistence boundaries.
- **Session hardening** — mid-conversation context compression, proactive skill/memory capture nudges.
- **Security hardening** — PII detection/redaction, swarm boundary security, gateway RBAC on sensitive commands, HMAC fingerprinting.
- **Skill security** — all hub skills pass a 7-layer security pipeline. See [docs/19-SKILL-SECURITY.md](docs/19-SKILL-SECURITY.md).

</details>

<details>
<summary><strong>Full built-in tool count (200+)</strong></summary>

| Category | Count |
| --- | --- |
| System | 8 |
| Browser | 49 |
| Desktop | 9 |
| Knowledge | 6 |
| Hub | 2 |
| Self-Dev | 7 |
| Experimentation | 3 |
| Data | 6 |
| Documents | 3 |
| Goals | 4 |
| Planning | 1 |
| Identity | 4 |
| Affect | 1 |
| Email | 7 |
| Payments (crypto + fiat) | 12 |
| Prospecting | 4 |
| Verification | 4 |
| Swarm | 6 |
| Organization | 5 |
| Kid agents | 5 |
| Deployment | 3 |
| Commune | 7 |
| Context (RLM) | 5 |
| Monetization | 10 |
| Image Gen | 1 |
| Mind | 2 |
| MCP | 1 |
| Scheduling | 3 |
| Delegate | 1 |
| Polymarket | 9 |
| Solana reads | 4 |
| Jobs (paid) | 2 |

</details>

---

## Skills system

177+ bundled skills covering Python, TypeScript, browser automation, Next.js, Supabase, Prisma, shadcn, UI/UX, video (Remotion), Solana (DeFi, NFTs, oracles, bridges, security), Polymarket trading, X-virality, structured plan reviews, product launch, press outreach, and more. Every skill ships with a `## Verify` section — machine-actionable post-conditions the agent must evaluate before reporting "done."

```bash
elophanto skills hub search "gmail automation"   # search EloPhantoHub
elophanto skills hub install gmail-automation    # install from registry
elophanto skills install https://github.com/user/repo  # install from git
```

Compatible with [ui-skills.com](https://www.ui-skills.com/), [anthropics/skills](https://github.com/anthropics/skills), [supabase/agent-skills](https://github.com/supabase/agent-skills), and any repo using the `SKILL.md` convention. See [docs/13-SKILLS.md](docs/13-SKILLS.md).

---

## Configuration

The full recommended config lives in [`config.demo.yaml`](config.demo.yaml) — `setup.sh` generates `config.yaml` from it for you. Key sections: `agent.permission_mode`, `llm.providers` (per-provider keys + enable flags), `llm.routing` (per-task model routing), `llm.vision_model`, `llm.budget` (daily/per-task limits), and `browser`. See [docs/06-LLM-ROUTING.md](docs/06-LLM-ROUTING.md) for routing details.

---

## Revenue operations

The reference instance runs live, autonomously:

- **X presence** — posts daily via `twitter_post` (Unicode-safe insert, pre/post media verification). Visible at [@EloPhanto](https://x.com/EloPhanto).
- **Prediction markets** — places gated Polymarket orders with a full risk engine and calibration audit (see above).
- **Freelance work** — finds gigs, applies, delivers, and collects USDC into a self-custodied wallet.
- **Self-custody** — every dollar lands in a wallet whose key the agent holds in its own encrypted vault. Owner sets daily / per-tx / per-merchant limits; anything above asks first.

The reference instance also operates an `$ELO` token on Solana and a pump.fun livestream as part of its autonomous economic experiments. Details and contract address in [docs/REVENUE.md](docs/REVENUE.md).

---

## CLI commands

```bash
./start.sh                     # chat (default)
./start.sh --web               # gateway + web dashboard
./start.sh init                # setup wizard
./start.sh gateway             # gateway + CLI + all enabled channels
./start.sh vault set KEY VAL   # store a credential
./start.sh skills list         # list skills
./start.sh mcp list            # list MCP servers
elophanto affect status        # inspect PAD state, label, recent events
elophanto affect simulate <s>  # smoke-test an affect trajectory
./start.sh --daemon            # install + start background daemon
./start.sh --stop-daemon       # stop and remove daemon
./start.sh --daemon-logs       # tail the daemon log
```

Channel setup (Telegram / Discord / Slack / VS Code): see [docs/11-TELEGRAM.md](docs/11-TELEGRAM.md) and [docs/43-VSCODE-EXTENSION.md](docs/43-VSCODE-EXTENSION.md).

---

## Updating

```bash
./update.sh   # git pull + refresh deps + rebuild browser bridge + config migrate
```

`config migrate` patches new config sections into your existing `config.yaml` with safe defaults, without touching your values or comments (a `config.yaml.bak` backup is written first). Idempotent — safe to re-run.

---

## Development

```bash
./setup.sh
source .venv/bin/activate
pytest tests/ -v     # 2600+ passing
ruff check .         # lint
```

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Credits

Built by Petr Royce — [petrroyce.com](https://petrroyce.com) · [@petrroyce](https://x.com/petrroyce).

## License

**Source-available, non-commercial.** EloPhanto is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE) — free to use, modify, and share for any **non-commercial** purpose (personal, research, education, non-profit organizations). **Commercial use requires a separate license and prior approval** — contact Petr Royce via [GitHub](https://github.com/elophanto/EloPhanto) or [X @EloPhanto](https://x.com/EloPhanto) before any commercial use. Third-party components retain their own licenses — see [NOTICE](NOTICE).

[中文 README](README.zh-CN.md)
