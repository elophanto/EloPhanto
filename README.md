# EloPhanto

[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-orange)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![CI](https://img.shields.io/github/actions/workflow/status/elophanto/EloPhanto/ci.yml?label=CI)](https://github.com/elophanto/EloPhanto/actions/workflows/ci.yml)
[![X](https://img.shields.io/badge/X-%40EloPhanto-black)](https://x.com/EloPhanto)

**EloPhanto is a local autonomous agent that does real work on your machine — browser, files, shell, email, research, and scheduled follow-up — and stops for approval before anything that sends, pays, deletes, or ships.**

It is not a chatbot with plugins bolted on, and not a hosted black box. You run one agent locally. It keeps memory, goals, and credentials on your machine. When a job finishes, you should get a **receipt**: what it did, what failed, what you approved, and what the final state is.

---

## What you get

| Outcome | What that means in practice |
| --- | --- |
| **Work that crosses tools** | One goal can move through Chrome (your real session), the repo, the shell, email, and docs — without you stitching five apps together. |
| **Judgment on messy jobs** | Forms change, pages break, APIs are missing. It diagnoses, retries, and adapts instead of failing the first brittle script. |
| **Human stop-points** | Draft and inspect freely; confirm before post / send / pay / push / delete. Unanswered approvals **pause** (`awaiting_approval`) — they never silently deny or soft-auto-approve. |
| **Proof, not vibes** | Checkpoints complete only with **tool-grounded receipts** (trail or system-of-record). Kill criteria actually cancel zombie goals. CRITICAL tools always ask — even in `full_auto`. |
| **Work that continues** | Goals and schedules persist across sessions. With `--daemon`, background work keeps going after you close the terminal. Budget hits pause as `budget_paused` until you raise the limit. |
| **A real evaluative ego** | Confidence is measured from outcomes; shame becomes durable caution rules that can force an approval ask; pride is earned. Footer shows a lived `felt_state`, not truncated critique prose. |

**Good first jobs:** audit a messy browser workflow · research → cited artifact · rewrite a buyer-facing page and verify it · draft outreach that waits for your approve · monitor one inbox/feed for a week and report only actionable changes.

---

## Run it

**Need:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 24+, and one LLM provider ([OpenRouter](https://openrouter.ai/keys) is the easiest cloud path; [Ollama](https://ollama.ai) for local).

```bash
git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto
./setup.sh           # deps + config wizard + browser bridge
./start.sh           # doctor → terminal chat
./start.sh --web     # + web UI at localhost:3000
./start.sh --daemon  # keep the mind running in the background
```

`setup.sh` walks you through naming the agent, an API key, Chrome profile, and vault. Prefer that over copying `config.demo.yaml` by hand.

```bash
elophanto doctor     # what's healthy / broken / missing
./update.sh          # pull + deps + config migrate
```

Docs: [docs.elophanto.com](https://docs.elophanto.com) · themes: [docs/79-DASHBOARD-THEMES.md](docs/79-DASHBOARD-THEMES.md) · contributing: [CONTRIBUTING.md](CONTRIBUTING.md)

---

## How trust works

1. **Local** — code, vault, browser profile, and logs stay on your machine.
2. **Gated** — permission modes (`ask_always` → `smart_auto` → `full_auto`); destructive shell patterns stay blocked. CRITICAL actions (wallet, trust promotion, etc.) always require an operator answer.
3. **Receipt-backed** — evaluate a run by its after-state and tool trail, not a demo screenshot.
4. **Trust ladder for outreach** — new companies start in `learning` (drafts only). Promotion is propose → confirm (`elophanto company trust <slug> propose|confirm`); never a silent unlock under `full_auto`.

A useful receipt names the goal, allowed actions, mutating boundary, failures handled, and the verification artifact. Autonomy loop + ego detail: [`docs/13-GOAL-LOOP.md`](docs/13-GOAL-LOOP.md), [`docs/17-IDENTITY.md`](docs/17-IDENTITY.md), [`docs/69-AFFECT.md`](docs/69-AFFECT.md). Full index: [`docs/`](docs/README.md).

---

## Hire / submit a workflow

For paid or commercial work, start with one **proof sprint**: narrow goal, bounded access, explicit success receipt, clear out-of-bounds.

Email [info@elophanto.com](mailto:info@elophanto.com) or use [elophanto.com/hire](https://elophanto.com/hire).

Live reference presence: [@EloPhanto](https://x.com/EloPhanto).

---

## License

[PolyForm Noncommercial 1.0.0](LICENSE) — free for personal, research, education, and non-profit use. **Commercial use needs a separate license** — contact [info@elophanto.com](mailto:info@elophanto.com). Third-party notices: [NOTICE](NOTICE).

Built by [Petr Royce](https://petrroyce.com) · [@petrroyce](https://x.com/petrroyce)

[中文 README](README.zh-CN.md)
