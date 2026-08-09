# EloPhanto — Install & first run

## Two products, one core

| Path | Who | Command |
| --- | --- | --- |
| **Hosted** | Most people — always-on, no laptop babysitting | Apply at [elophanto.com/hire](https://elophanto.com/hire) — we provision a managed box |
| **Open** | Operators who want CLI / TUI / `nuclear` / self-host | `git clone` → `./install.sh` → `./start.sh` |

There is **no** `curl | bash` that turns a non-technical user into a running agent on their laptop. That fantasy lived in older drafts of this doc. Hosted is the answer for basic users; Open is the answer for you if you love the terminal.

---

## EloPhanto Open (this repo)

```bash
git clone https://github.com/elophanto/EloPhanto.git
cd EloPhanto
./install.sh          # thin wrapper → ./setup.sh
./start.sh            # doctor → terminal chat
./start.sh --web      # gateway + web UI @ localhost:3000
./start.sh --daemon   # OS service so the mind outlives the terminal
```

### What `./install.sh` / `./setup.sh` actually do

1. Require **Python 3.12+** already installed (they do not install Python for you).
2. Install **uv** if missing; on macOS+Homebrew optionally Node / ffmpeg / tmux.
3. `uv sync` for Python deps; build browser bridge + web dashboard deps.
4. Run `elophanto init` (config wizard) if no `config.yaml`.
5. Optional vault init.

They do **not** install Ollama, load a Chrome extension wizard from fiction, or run the full test suite.

### After setup

```bash
elophanto doctor      # health / blockers
./update.sh           # pull + deps + config migrate
```

Doctor may refuse to start until blockers are fixed; set `SKIP_DOCTOR=1` only if you know why.

### Templates

| File | Use |
| --- | --- |
| `config.demo.yaml` | Open demo / copy-paste starting point |
| `config.hosted.yaml` | Hosted image template (`ELOPHANTO_CLOUD=1`) |
| `profiles/hosted.yaml` | Hosted profile overrides (nuclear absent) |
| `permissions.hosted.yaml` | Hosted tool ask-overrides |

---

## EloPhanto Hosted

See [`20-HOSTED-PLATFORM.md`](20-HOSTED-PLATFORM.md) and [`proposals/HOSTED-DESKTOP.md`](proposals/HOSTED-DESKTOP.md).

- Single-tenant managed instance (`ELOPHANTO_CLOUD=1`)
- Gateway auth token required (fail-closed)
- `nuclear` **unavailable**
- Owner Kill + spend freeze via gateway commands
- Design partner pricing: €149/mo + LLM pass-through (see Hosted doc)

Provisioning API: `python -m cloud.provision` (mints vault password + gateway token).

---

## Offline / air-gapped Open

Clone on a connected machine, vendor wheels as needed, then on the air-gapped box:

```bash
./setup.sh   # with deps already present / offline wheelhouse
./start.sh
```

Use local Ollama (or offline-capable providers) and disable network tools you do not need via `permissions.yaml` / the Minimal profile.

---

## Windows

Use **WSL2** (Ubuntu). Native Windows is not a supported Open install path.
