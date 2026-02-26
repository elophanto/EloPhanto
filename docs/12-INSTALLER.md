# EloPhanto — First-Run Installer & Setup

## Problem

EloPhanto depends on Python 3.12+, several system packages, Ollama (optional), a Chrome extension, and an encrypted vault. A technical user could set this up manually. A basic user cannot and should not have to.

The goal: **one command to go from zero to a running agent.**

## Installer Script

A single shell script (`install.sh`) that handles everything. The user runs:

```bash
curl -fsSL https://elophanto.com/install | bash
```

Or if they've cloned the repo:

```bash
git clone https://github.com/elophanto/elophanto.git
cd elophanto
./install.sh
```

The script is interactive — it asks questions, shows progress, and explains what it's doing at each step. It never silently installs things.

## What the Installer Does

### Step 1: Detect Operating System

```
Detecting your system...
✓ Operating System: Ubuntu 22.04 (Linux)
✓ Architecture: x86_64
✓ Shell: bash
```

Supported platforms:
- **Linux**: Ubuntu/Debian (apt), Fedora/RHEL (dnf), Arch (pacman)
- **macOS**: Homebrew
- **Windows**: WSL2 required. The installer detects native Windows and guides the user to install WSL2 first.

If the OS is unsupported, the installer prints manual setup instructions and exits cleanly.

### Step 2: Check and Install System Dependencies

The installer checks for each dependency and only installs what's missing.

```
Checking dependencies...
✓ git (2.39.0) — already installed
✓ curl — already installed
✗ Python 3.12+ — not found
  → Install Python 3.12? [Y/n]: y
  Installing Python 3.12 via apt...
  ✓ Python 3.12.1 installed
✓ Node.js 22+ — already installed (v22.19.0)
✗ uv (Python package manager) — not found
  → Install uv? [Y/n]: y
  Installing uv...
  ✓ uv 0.5.1 installed
✓ SQLite 3.40+ — already installed
```

#### Required Dependencies

| Dependency | Why | Install Method |
|---|---|---|
| Python 3.12+ | Agent core runtime | System package manager or pyenv |
| Node.js 22+ | Browser bridge, web dashboard, optional JS plugins | System package manager or nvm |
| git | Version control for self-modifications | System package manager |
| curl | Downloading resources | System package manager |
| uv | Fast Python package manager | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| SQLite 3.40+ | Database (usually pre-installed) | System package manager |

#### Optional Dependencies

| Dependency | Why | When Needed |
|---|---|---|
| Ollama | Local LLM inference | If user wants local models |
| Playwright browsers | Headless browser fallback | If user wants browser automation without extension |
| Docker | Containerized deployment | Advanced users only |

```
Optional: Would you like to install Ollama for local AI models? [Y/n]: y
Installing Ollama...
✓ Ollama installed
→ Pulling recommended model (qwen2.5:14b)? This requires ~8GB. [Y/n]: n
  Skipped. You can pull models later with: ollama pull <model>
```

### Step 3: Create Project Environment

```
Setting up EloPhanto...
→ Creating virtual environment...
  ✓ Virtual environment created at ~/.elophanto/venv
→ Installing Python dependencies...
  ✓ 24 packages installed (litellm, aiogram, cryptography, ...)
→ Building Chrome extension...
  ✓ Extension built at ~/.elophanto/extension/
→ Initializing database...
  ✓ SQLite database created at ~/.elophanto/db/elophanto.db
→ Creating knowledge base...
  ✓ Knowledge directories created
  ✓ System knowledge files seeded
→ Initializing git repository...
  ✓ Git repo initialized with initial commit
```

### Step 4: Interactive Configuration Wizard

This is the `elophanto init` wizard, automatically launched after installation.

```
═══════════════════════════════════════════
  Welcome to EloPhanto Setup
  Your self-evolving AI agent
═══════════════════════════════════════════

Let's configure your agent. You can change any of these later.

── Security ──────────────────────────────

Create a master password for your secret vault.
This encrypts all your API keys and tokens locally.
Master password: ********
Confirm: ********
✓ Vault created and encrypted

── AI Models ─────────────────────────────

Which AI providers would you like to use?
(You need at least one to start)

[1] OpenRouter (cloud — Claude, GPT, Gemini, etc.)
    → Requires API key from openrouter.ai
[2] Z.ai / GLM (cloud — excellent for coding)
    → Requires API key from z.ai
[3] Ollama (local — free, private, needs GPU)
    → Already installed ✓
[4] All of the above
[5] Skip for now (configure later)

Choice: 1

OpenRouter API key: sk-or-v1-xxxx...
✓ API key validated and stored in vault

── Telegram (Optional) ───────────────────

Would you like to control EloPhanto from Telegram?
This lets you chat with your agent from your phone.

Set up Telegram? [y/N]: y

To create a Telegram bot:
1. Open Telegram and message @BotFather
2. Send /newbot and follow the prompts
3. Copy the bot token BotFather gives you

Bot token: 7123456789:AAH...
✓ Bot token validated and stored in vault

Your Telegram user ID (message @userinfobot to get it): 123456789
✓ User ID saved. Only you can control this bot.

── Browser Control (Optional) ────────────

Would you like EloPhanto to control your Chrome browser?
This gives it access to your logged-in sessions.

Set up browser control? [y/N]: y

The Chrome extension has been built at:
  ~/.elophanto/extension/

To install it:
1. Open Chrome and go to chrome://extensions
2. Enable "Developer mode" (top right toggle)
3. Click "Load unpacked"
4. Select the folder: ~/.elophanto/extension/
5. Click the EloPhanto icon in Chrome and enter this token:
   → abc123-def456-ghi789
   (This token is also saved in your vault)

Press Enter when the extension is installed...
✓ Extension connected!

── Permission Mode ───────────────────────

How much autonomy should EloPhanto have?

[1] Ask Always — Approve every action (safest, recommended to start)
[2] Smart Auto — Auto-approve safe actions, ask for risky ones
[3] Full Auto — Everything runs automatically (advanced users)

Choice: 1
✓ Permission mode set to "Ask Always"

── Autonomous Mind (Optional) ────────────

Enable autonomous background thinking?
The agent will work on goals, revenue, and maintenance
between your conversations. Pauses when you speak.

Enable autonomous mind? [y/N]: y
  Default wakeup interval (seconds): 300
  Budget (% of daily LLM budget): 15.0
  Terminal verbosity [minimal/normal/verbose]: normal
✓ Autonomous mind enabled — wakes every 300s, 15.0% budget.

── Done! ─────────────────────────────────

✓ EloPhanto is ready!

Start your agent:   elophanto start
Chat with it:       elophanto chat
Check status:       elophanto status
View help:          elophanto help

Your agent will learn and grow over time.
Happy automating! 🐘
```

### Step 5: Verify Installation

The installer runs a quick self-test before finishing:

```
Running verification...
✓ Python 3.12.1 — OK
✓ Virtual environment — OK
✓ All packages installed — OK
✓ Database accessible — OK
✓ Knowledge base indexed — OK
✓ Vault encryption/decryption — OK
✓ LLM connection (OpenRouter) — OK
✓ Telegram bot (polling) — OK
✓ Chrome extension (connected) — OK

All checks passed. EloPhanto is ready to use.
```

If any check fails, the installer provides clear error messages and suggested fixes.

## Installation Directory

Everything lives under `~/.elophanto/`:

```
~/.elophanto/
├── venv/                    # Python virtual environment
├── core/                    # Agent source code
├── tools/                   # Built-in tools
├── plugins/                 # Agent-created plugins
├── knowledge/               # Markdown knowledge base
├── extension/               # Chrome extension (built)
├── db/
│   └── elophanto.db         # SQLite database
├── logs/                    # Agent activity logs
├── config.yaml              # Configuration
├── permissions.yaml         # Permission rules
├── vault.enc                # Encrypted secrets
├── vault.salt               # Vault salt
└── .git/                    # Version control
```

The `elophanto` CLI command is installed globally (via pip/uv) and knows to look in `~/.elophanto/` for everything.

## Update Mechanism

```bash
elophanto update
```

This:
1. Pulls the latest version from PyPI (or git)
2. Runs database migrations if schema changed
3. Rebuilds the Chrome extension if updated
4. Re-indexes knowledge if indexing logic changed
5. Preserves all user data, plugins, knowledge, vault, and config
6. Runs the verification suite

The agent can also self-update if a new version is available (with user approval).

## Uninstall

```bash
elophanto uninstall
```

Options:
- `--keep-data`: Remove the program but keep `~/.elophanto/` (knowledge, plugins, vault)
- `--everything`: Remove everything including all data (requires confirmation)
- Default (no flag): Asks the user what to keep

## Platform-Specific Notes

### macOS

- Python: installed via Homebrew (`brew install python@3.12`) or pyenv
- Node.js: installed via Homebrew or nvm
- Xcode Command Line Tools may be needed: `xcode-select --install`
- The installer detects and handles Apple Silicon (ARM64) vs Intel

### Windows (WSL2)

- Native Windows is not supported — WSL2 is required
- The installer detects native Windows and provides WSL2 setup instructions:
  ```
  EloPhanto requires WSL2 (Windows Subsystem for Linux).
  
  To install WSL2:
  1. Open PowerShell as Administrator
  2. Run: wsl --install
  3. Restart your computer
  4. Open Ubuntu from the Start menu
  5. Re-run this installer inside WSL2
  ```
- Chrome extension still runs in Windows Chrome, connects to agent in WSL2 via localhost

### Linux

- Most straightforward platform
- The installer detects the package manager (apt, dnf, pacman, zypper) automatically
- May need `sudo` for system package installation — the installer asks before using sudo

## Offline Installation

For air-gapped environments:

1. On a connected machine: `elophanto package --offline` creates a tarball with all dependencies
2. Transfer the tarball to the target machine
3. Run `./install.sh --offline` which uses the bundled dependencies

This is an advanced use case and not part of the initial release, but the installer architecture should support it from the start (dependency resolution separated from download).

## Error Handling

The installer is designed to fail gracefully:

- Every step is idempotent — running the installer twice doesn't break anything
- If a step fails, the installer explains what went wrong and how to fix it
- Partial installations are safe — you can re-run the installer to pick up where it left off
- The installer creates a log file (`~/.elophanto/install.log`) for debugging
- Common errors have specific, human-readable messages:

```
✗ Python 3.12+ not found and could not be installed automatically.

This usually means your system's package manager doesn't have
Python 3.12 available. You can install it manually:

  Option 1: Use pyenv
    curl https://pyenv.run | bash
    pyenv install 3.12.1
    pyenv global 3.12.1

  Option 2: Download from python.org
    https://www.python.org/downloads/

Then re-run this installer.
```

## Script Design Principles

- **Always ask before installing anything** — no silent installations
- **Show what's happening** — progress indicators, clear status messages
- **Explain why** — briefly explain what each dependency is for
- **Fail clearly** — human-readable errors with actionable solutions
- **Be idempotent** — safe to run multiple times
- **Respect the user's system** — use virtual environments, don't pollute global packages
- **Support unattended mode** — `./install.sh --yes` accepts all defaults for automated deployment
