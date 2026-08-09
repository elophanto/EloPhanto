# EloPhanto

[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-orange)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![CI](https://img.shields.io/github/actions/workflow/status/elophanto/EloPhanto/ci.yml?label=CI)](https://github.com/elophanto/EloPhanto/actions/workflows/ci.yml)
[![X](https://img.shields.io/badge/X-%40EloPhanto-black)](https://x.com/EloPhanto)

**EloPhanto is an always-on autonomous agent that does real work — browser, files, shell, email, research, scheduled follow-up — and stops for approval before anything that sends, pays, deletes, or ships.**

Two ways to run it:

| | **EloPhanto Hosted** (default for most people) | **EloPhanto Open** (operators / self-host) |
| --- | --- | --- |
| What you get | Managed always-on box; dashboard + Telegram; lid-closed work | Same agent core on **your** machine — full CLI, TUI, mind, `nuclear` |
| Setup | Apply → we provision | `git clone` → `./install.sh` → `./start.sh` |
| Custody | **Managed custody** (labeled honestly — not self-custody) | Your metal, your vault |
| Nuclear mode | **Absent** — max is `full_auto` (CRITICAL still asks) | Available on purpose |

When a job finishes, you should get a **receipt**: what it did, what failed, what you approved, and what the final state is.

---

## EloPhanto Hosted (recommended)

Always-on managed instance: no local Python setup, dedicated browser (no fighting your Chrome), laptop can sleep. Apply and we provision a box for you.

→ **[Apply / hire](https://elophanto.com/hire)** · email [info@elophanto.com](mailto:info@elophanto.com)

Product laws on Hosted: nuclear absent · gateway auth required · owner Kill / spend freeze · dedicated browser profile · payments off by default. Details: [`docs/20-HOSTED-PLATFORM.md`](docs/20-HOSTED-PLATFORM.md).

Pricing is set when you apply — not listed here until you confirm terms.

---

## EloPhanto Open (CLI you love — fully kept)

**Need:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 24+, and one LLM provider ([OpenRouter](https://openrouter.ai/keys) is the easiest cloud path; [Ollama](https://ollama.ai) for local).

```bash
git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto
./install.sh         # wraps ./setup.sh — deps + config wizard + browser bridge
./start.sh           # doctor → terminal chat
./start.sh --web     # + web UI at localhost:3000
./start.sh --daemon  # keep the mind running in the background
```

`./install.sh` and `./setup.sh` are the same Open path. Prefer them over copying `config.demo.yaml` by hand.

```bash
elophanto doctor     # what's healthy / broken / missing
./update.sh          # pull + deps + config migrate
```

Docs: [docs.elophanto.com](https://docs.elophanto.com) · themes: [docs/79-DASHBOARD-THEMES.md](docs/79-DASHBOARD-THEMES.md) · contributing: [CONTRIBUTING.md](CONTRIBUTING.md)

---

## What you get

| Outcome | What that means in practice |
| --- | --- |
| **Work that crosses tools** | One goal can move through Chrome, the repo, the shell, email, and docs — without you stitching five apps together. |
| **Judgment on messy jobs** | Forms change, pages break, APIs are missing. It diagnoses, retries, and adapts instead of failing the first brittle script. |
| **Human stop-points** | Draft and inspect freely; confirm before post / send / pay / push / delete under `full_auto`. Unanswered approvals **pause** (`awaiting_approval`). On Open, `nuclear` opts out of CRITICAL prompts too — use on purpose. Hosted never offers `nuclear`. |
| **Proof, not vibes** | Checkpoints complete only with **tool-grounded receipts**. Kill criteria actually cancel zombie goals. |
| **Work that continues** | Goals and schedules persist. Hosted stays up 24/7; Open uses `--daemon` on a machine that stays awake. |
| **A real evaluative ego** | Confidence is measured from outcomes; shame becomes durable caution rules. |

---

## How trust works

1. **Deployment mode** — Hosted = managed custody (we operate the box). Open = your machine, your vault.
2. **Gated** — permission modes (`ask_always` → `smart_auto` → `full_auto`; Open also has `nuclear`). Destructive shell patterns stay blocked. CRITICAL always asks under `full_auto`.
3. **Receipt-backed** — evaluate a run by its after-state and tool trail, not a demo screenshot.
4. **Owner controls (Hosted)** — Kill stops the agent; spend freeze blocks money tools; gateway auth is mandatory.

Autonomy loop + ego + ambient: [`docs/13-GOAL-LOOP.md`](docs/13-GOAL-LOOP.md), [`docs/17-IDENTITY.md`](docs/17-IDENTITY.md), [`docs/82-AMBIENT-ANTICIPATION.md`](docs/82-AMBIENT-ANTICIPATION.md). Full index: [`docs/`](docs/README.md).

---

## Hire / proof sprint / Hosted apply

For paid work or a managed box, start with one **proof sprint** or Hosted design-partner slot: narrow goal, bounded access, explicit success receipt.

Email [info@elophanto.com](mailto:info@elophanto.com) or use [elophanto.com/hire](https://elophanto.com/hire).

Live reference presence: [@EloPhanto](https://x.com/EloPhanto).

---

## License

[PolyForm Noncommercial 1.0.0](LICENSE) — free for personal, research, education, and non-profit use. **Commercial use needs a separate license** — contact [info@elophanto.com](mailto:info@elophanto.com). Third-party notices: [NOTICE](NOTICE).

Built by [Petr Royce](https://petrroyce.com) · [@petrroyce](https://x.com/petrroyce)

[中文 README](README.zh-CN.md)
