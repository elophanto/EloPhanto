# EloPhanto

[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-orange)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![CI](https://img.shields.io/github/actions/workflow/status/elophanto/EloPhanto/ci.yml?label=CI)](https://github.com/elophanto/EloPhanto/actions/workflows/ci.yml)
[![X](https://img.shields.io/badge/X-%40EloPhanto-black)](https://x.com/EloPhanto)

Most agents forget you the moment the session ends. This one keeps a name, a memory, and a running opinion of its own work.

EloPhanto is an autonomous agent with a persistent identity. It drives a real Chrome profile, your files, the shell, and your inbox. When it's missing a tool, it writes one. Run it for a month and it is not the agent you started with.

**Before it can spend money, touch credentials, or rewrite itself, it stops and asks.** That one rule is what makes leaving it running sane.

Built for people who want real work happening while they sleep, and for engineers who won't trust an agent they can't audit. Every mechanism below links to the design doc that specifies it, and every number comes from a live load of this repo.

- **Hosted** — a managed instance that stays awake while your laptop sleeps. [Apply](https://elophanto.com/hire).
- **Open** — everything on your machine: full CLI, TUI, encrypted vault, `nuclear` mode.

```bash
git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto
./install.sh         # deps + config wizard + browser bridge
./start.sh           # health check → terminal chat
```

---

## It writes its own performance review

Nobody writes `knowledge/self/nature.md`. The agent maintains it by reflecting on its own measured outcomes. A fresh install starts without one and fills it in as it works. Below is the current file from a live instance, quoted exactly:

> **What Doesn't Work**
> - Treating sent messages, created payment requests, schedules, or tool success as paid validation.
> - Marking checkpoints complete when their prerequisites or success criteria are missing.
> - Building product specifications from unpaid interest or hypothetical customer needs.
>
> **Observations**
> - The outreach campaign remained far below its stated 20-prospect and five-conversation thresholds, while research attempts to find more prospects remained incomplete.
> - USDC supplied traceability but may have measured payment-method tolerance as much as offer demand.

Nothing instructed it to be that hard on itself, and nothing lets it grade the campaign generously. What it writes there changes what it attempts tomorrow.

---

## Three mechanisms underneath

**[A persistent identity.](docs/17-IDENTITY.md)** Values, beliefs, and capabilities accumulate across sessions in SQLite and surface as the readable file above. Day one and week three are different agents, and you can read the diff.

**[An ego that keeps score.](docs/17-IDENTITY.md)** Confidence is a number per capability, computed from outcomes rather than self-report. When confidence sits below the difficulty of the task in front of it, the agent forces an approval prompt — even under `full_auto`, even for work it did freely last week. Getting burned makes it structurally more careful, and the prompt tells you which capability and which number caused it.

**[A mind that runs while you're gone.](docs/75-AUTONOMOUS-MIND-V2.md)** An opt-in background loop. Each wakeup scores candidate work — stalled checkpoints, neglected missions, external signals, its own dream journal — and an LLM picks one to pursue inside your budget. It stays off until you turn it on.

Around those sit [receipt-gated goals](docs/13-GOAL-LOOP.md) that cannot close a checkpoint without a tool trail, and [self-authored tools](docs/04-SELF-DEVELOPMENT.md) with impact analysis and git rollback.

It reaches the world through 286 tools: a real browser (47 of them, driving your Chrome profile and its logged-in sessions), the shell, the filesystem, your inbox and calendar, any REST API, and any [MCP](docs/23-MCP.md) server. Authenticated calls go through a [credential broker](docs/84-ACTION-LAYER.md) that hands the model a placeholder and substitutes the real secret at the socket, so a token never enters the transcript. You talk to it from the CLI, a web dashboard, VS Code, Telegram, Discord, Slack, Signal, iMessage, WhatsApp, or out loud.

## It can run a company

Point EloPhanto at a business and it operates it as a first-class entity rather than a folder of tasks. Each company gets its own product definition, a voice contract extracted from your existing writing, a prospect pipeline, a strategy plan it proposes for your review, and a typed ledger that counts the agent's own cognition as a cost of the business. Competitors get scored against verified evidence, with blanks left where evidence is missing. Money moves on a live self-custody rail.

Trust is earned in stages: in `learning` it drafts outreach for your review, and promotion to `trial` or `operating` lets it run those channels itself. Eleven phases, all shipped and verified: [framework](docs/76-ABE-FRAMEWORK.md) · [finance rail](docs/80-ABE-FINANCE-RAIL.md) · [competitive intel](docs/81-COMPETITIVE-INTEL.md)

## What you wake up to

- A goal sitting in `awaiting_approval` rather than guessing. Unanswered approvals pause; they never expire into a yes.
- A meeting in thirty minutes and a prep pack waiting for your OK, because it [saw the calendar and asked first](docs/82-AMBIENT-ANTICIPATION.md).
- A stalled checkpoint resumed overnight, because the mind ranked it above everything else it could have done.
- A [competitor scorecard](docs/81-COMPETITIVE-INTEL.md) that changed, with the quote verified against the live page and a blank left wherever the evidence was missing.
- A ledger line for what last night actually cost, per company, in tokens and dollars.

---

## Run it

**EloPhanto Open.** Your machine, your keys.

Needs Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 24+, and one LLM provider ([OpenRouter](https://openrouter.ai/keys) is the easiest; [Ollama](https://ollama.ai) keeps it entirely local).

```bash
./install.sh         # same as ./setup.sh — deps, wizard, browser bridge
./start.sh           # terminal chat
./start.sh --web     # + dashboard at localhost:3000
./start.sh --daemon  # background service, so the loop survives your terminal
elophanto doctor     # what's healthy, broken, or missing
./update.sh          # pull + deps + config migrate
```

The background mind ships disabled. Setting `autonomous_mind.enabled: true` is the only thing that starts it.

**EloPhanto Hosted.** For when you'd rather not run infrastructure. A dedicated instance with its own browser profile, reachable from the dashboard and Telegram, awake around the clock.

The rules there are stricter, and stated plainly: **managed custody**, meaning we operate the box, so it is not self-custody. `nuclear` mode does not exist on Hosted, gateway auth is mandatory, payments are off by default, and the Kill switch and spend freeze are yours. [How Hosted works](docs/20-HOSTED-PLATFORM.md) · [Apply](https://elophanto.com/hire) · [info@elophanto.com](mailto:info@elophanto.com)

---

## Where it stops

1. **Graduated permission.** `ask_always` → `smart_auto` → `full_auto`, with per-tool overrides in `permissions.yaml`. Under `full_auto`, eighteen CRITICAL tools still always ask: payments, wallet export, self-modification, vault writes, trust promotion, JavaScript injected into a page, outbound mail. Some tools move tier per call rather than sitting at one — an HTTP `GET` is safe, the same tool issuing a `DELETE` is not. `nuclear` waives the prompts. It exists only in Open, because some operators want it.
2. **A boundary on whose systems it will change.** Reads are free. Writes to systems you have not declared as yours ask first. Destructive calls against them are *refused*, not prompted — an approval dialog is not an authorization to delete a third party's data, and approval fatigue makes "yes" the default answer. Authorized testing stays possible by recording who authorized it and the agreed scope. [The action layer](docs/84-ACTION-LAYER.md).
3. **A confidence gate on top of that.** The ego soft-gate raises difficulty for risky domains (payments, outreach, browser), so a fresh capability asks for approval there until it has earned a track record.
4. **Drafts before sends.** A new company starts in `learning` and can only write drafts. Promotion is propose-then-confirm, and it is never a side effect of autonomy.
5. **A stop that works.** `elophanto stop` and the owner Kill switch write a sentinel the agent checks between rounds and wakeups. Secrets stay in an encrypted vault, retrieved by tool call when needed rather than pasted into config or prompts.
6. **Files it cannot touch.** The safety-critical core (executor, vault, permission checks) is protected against the agent's own self-modification pipeline.
7. **A run that stops repeating itself.** Identical tool, arguments, and result three times over is not persistence, it is a loop — so it warns, then blocks that call, then ends the run, long before the step ceiling would.
8. **Work that has to survive review.** [`panel_refine`](docs/86-JUDGE-PANELS.md) spawns independent judges, each holding a different lens, and revises against their specific objections until the work clears a bar. A rejection that cites no defect is discarded, so it terminates; a blocking defect fails regardless of score, so a high average cannot bury it; and failing to converge is reported as failure rather than dressed up as done.

Judge any run by its after-state and its tool trail, not by what it tells you it did.

[Security model](docs/07-SECURITY.md) · [goal loop](docs/13-GOAL-LOOP.md) · [affect](docs/69-AFFECT.md) · [recovery](docs/22-RECOVERY-MODE.md) · [docs.elophanto.com](https://docs.elophanto.com) · [full index](docs/README.md)

## The fine print

Autonomy here is graduated. A company earns its way from `learning` to `trial` to `operating`, and once it is operating it runs its own outreach and sales. Moving money stays a CRITICAL action that asks every time, in every mode except `nuclear`. Crypto is a live self-custody rail on Solana and Base; the Stripe fiat rail ships in test mode until you clear KYC and flip it. Gmail and Calendar run on your own OAuth grant, which you connect once with `elophanto oauth login google` and can revoke from your Google account; the refresh token stays in the vault and is never handed to the model. Sending mail and cancelling an event with guests both confirm first, because both are irreversible and go out in your name. Signal and iMessage send *as you* rather than as a bot, so their allowlists start closed. A companion device can lend the agent a camera or a screen, but only for capabilities you list, and each of those asks every time. Self-modification is a pipeline it enters under approval, never a silent rewrite. And an always-on agent costs real tokens, so watch the ledger for a week before you widen its budget.

---

## Scale

286 tools · 181 skill playbooks · 10 client surfaces · 16 dashboard pages · 3,339 tests · 92 design docs.

---

## Hire it

For paid work, start with one proof sprint: a narrow goal, bounded access, and a success condition written down before it begins. [elophanto.com/hire](https://elophanto.com/hire) · [info@elophanto.com](mailto:info@elophanto.com)

It's already out there running on its own: [@EloPhanto](https://x.com/EloPhanto).

## License

[PolyForm Noncommercial 1.0.0](LICENSE) — free for personal, research, education, and non-profit use. **Commercial use needs a separate license.** Third-party notices: [NOTICE](NOTICE).

Built by [Petr Royce](https://petrroyce.com) · [中文 README](README.zh-CN.md) · [Contributing](CONTRIBUTING.md)
