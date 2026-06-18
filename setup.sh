#!/usr/bin/env bash
# EloPhanto — One-command setup
# Usage: ./setup.sh

set -e

echo ""
echo "  ███████╗██╗      ██████╗ ██████╗ ██╗  ██╗ █████╗ ███╗   ██╗████████╗ ██████╗"
echo "  ██╔════╝██║     ██╔═══██╗██╔══██╗██║  ██║██╔══██╗████╗  ██║╚══██╔══╝██╔═══██╗"
echo "  █████╗  ██║     ██║   ██║██████╔╝███████║███████║██╔██╗ ██║   ██║   ██║   ██║"
echo "  ██╔══╝  ██║     ██║   ██║██╔═══╝ ██╔══██║██╔══██║██║╚██╗██║   ██║   ██║   ██║"
echo "  ███████╗███████╗╚██████╔╝██║     ██║  ██║██║  ██║██║ ╚████║   ██║   ╚██████╔╝"
echo "  ╚══════╝╚══════╝ ╚═════╝ ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝"
echo ""

# ── System checks ──

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "  ✗ Python 3 not found. Install Python 3.12+ first."
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 12 ]); then
    echo "  ✗ Python $PY_VERSION found, but 3.12+ is required."
    exit 1
fi
echo "  ✓ Python $PY_VERSION"
if [ "$PY_MINOR" -ge 14 ]; then
    echo "    Note: Python 3.14 is very new — some packages may not have prebuilt wheels yet."
    echo "    If install hangs or fails, try Python 3.13: brew install python@3.13"
fi

# Ensure ~/.local/bin is on PATH (where uv lands by default). This is a
# no-op when it's already there but covers the fresh-shell case where
# the installer added it to .zshrc but the current shell hasn't sourced.
export PATH="$HOME/.local/bin:$PATH"

# Check/install uv
if ! command -v uv &>/dev/null; then
    echo "  → Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Re-export — installer may have added a different path.
    export PATH="$HOME/.local/bin:$PATH"
fi
echo "  ✓ uv $(uv --version 2>/dev/null | head -1)"

# Detect Homebrew once so we can auto-install Node + ffmpeg on macOS
# without making the operator hunt down each tool manually. Brew is
# already a near-universal macOS dev prerequisite; on Linux we fall
# back to printing instructions.
HAS_BREW=0
if command -v brew &>/dev/null; then
    HAS_BREW=1
fi

# Check / auto-install Node.js (for browser bridge)
if command -v node &>/dev/null; then
    NODE_VERSION=$(node --version)
    echo "  ✓ Node.js $NODE_VERSION"
else
    if [ "$HAS_BREW" -eq 1 ]; then
        echo "  → Installing Node.js via brew..."
        brew install node >/dev/null 2>&1 && \
            echo "  ✓ Node.js $(node --version)" || \
            echo "  ⚠ brew install node failed — install Node 24+ LTS manually from https://nodejs.org/"
    else
        echo "  ⚠ Node.js not found — install Node 24+ LTS from https://nodejs.org/ for browser tools"
    fi
fi

# Check / auto-install ffmpeg (for pump.fun livestream)
if command -v ffmpeg &>/dev/null; then
    echo "  ✓ ffmpeg installed"
else
    if [ "$HAS_BREW" -eq 1 ]; then
        echo "  → Installing ffmpeg via brew..."
        brew install ffmpeg >/dev/null 2>&1 && \
            echo "  ✓ ffmpeg installed" || \
            echo "  ⚠ brew install ffmpeg failed — pump_livestream tools will be disabled"
    else
        echo "  ⚠ ffmpeg not found — needed only for pump_livestream (Linux: apt install ffmpeg)"
    fi
fi

# Check / auto-install tmux (for agent swarm: Claude Code / Codex / Gemini CLI)
if command -v tmux &>/dev/null; then
    echo "  ✓ tmux installed"
else
    if [ "$HAS_BREW" -eq 1 ]; then
        echo "  → Installing tmux via brew..."
        brew install tmux >/dev/null 2>&1 && \
            echo "  ✓ tmux installed" || \
            echo "  ⚠ brew install tmux failed — agent swarm (swarm_spawn) will be disabled"
    else
        echo "  ⚠ tmux not found — needed for agent swarm (Linux: apt install tmux  /  dnf install tmux)"
    fi
fi

# Check Ollama (for local models)
if command -v ollama &>/dev/null; then
    echo "  ✓ Ollama installed"
else
    echo "  ⚠ Ollama not found (optional — needed for free local models: https://ollama.ai)"
fi

# Check tmux (for agent swarm)
if command -v tmux &>/dev/null; then
    echo "  ✓ tmux installed"
else
    echo "  ⚠ tmux not found (optional — needed for agent swarm: brew install tmux)"
fi

# ── Install dependencies ──

# Spinner helper — runs a command with a progress indicator so the user
# knows something is happening.  Hides stdout but shows stderr on failure.
_spin() {
    local msg="$1"; shift
    local pid errfile
    errfile=$(mktemp)
    printf "  → %s " "$msg"
    "$@" >"$errfile" 2>&1 &
    pid=$!
    local chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    while kill -0 "$pid" 2>/dev/null; do
        for (( i=0; i<${#chars}; i++ )); do
            printf "\r  → %s %s" "$msg" "${chars:$i:1}"
            sleep 0.1
            kill -0 "$pid" 2>/dev/null || break
        done
    done
    wait "$pid"
    local rc=$?
    printf "\r"
    if [ $rc -eq 0 ]; then
        printf "  ✓ %s\n" "$msg"
    else
        printf "  ✗ %s (failed)\n" "$msg"
        echo ""
        echo "  Error output:"
        tail -20 "$errfile" | sed 's/^/    /'
        echo ""
    fi
    rm -f "$errfile"
    return $rc
}

echo ""
_spin "Syncing project dependencies" uv sync || {
    echo "  ⚠ 'uv sync' failed. Trying fallback: uv pip install -e '.' ..."
    _spin "Installing core (fallback)" uv pip install -e '.' || {
        echo ""
        echo "  ✗ Dependency installation failed."
        echo "    If you're on Python 3.14+, try Python 3.13 instead:"
        echo "      brew install python@3.13"
        echo "      uv python pin 3.13 && uv sync"
        echo ""
        exit 1
    }
}
_spin "Installing crypto wallet support" uv pip install -e '.[payments]' || true
_spin "Installing MCP support" uv pip install -e '.[mcp]' || true

# Install desktop GUI deps if configured
if grep -q "desktop:" config.yaml 2>/dev/null && grep -A1 "desktop:" config.yaml 2>/dev/null | grep -q "enabled: true"; then
    _spin "Installing desktop GUI agent dependencies" uv pip install -e '.[desktop]' || \
        echo "  ⚠ Desktop deps install failed (optional — run: uv pip install -e '.[desktop]')"
fi

# Detect Solana chain
if grep -q "default_chain: solana" config.yaml 2>/dev/null; then
    echo "  ✓ Solana wallet detected (solders + base58 included in core deps)"
fi

# Install Coinbase AgentKit if configured
# NOT RECOMMENDED: Coinbase CDP requires KYA (Know Your Agent) verification.
# See: https://x.com/theragetech/status/2034975703033090129
if grep -q "provider: agentkit" config.yaml 2>/dev/null; then
    echo "  ⚠ Coinbase AgentKit is not recommended (KYA required). Consider provider: local"
    _spin "Installing Coinbase AgentKit" uv pip install -e '.[payments-cdp]' || \
        echo "  ⚠ AgentKit install failed (optional — switch to provider: local in config.yaml)"
fi

# Install Stripe fiat support if the fiat rail is configured (ABE finance rail).
# Only matches the payments.fiat block (`provider: stripe`); crypto uses
# provider: local|agentkit, so this never false-fires.
if grep -q "provider: stripe" config.yaml 2>/dev/null; then
    _spin "Installing Stripe fiat support" uv pip install -e '.[payments-fiat]' || \
        echo "  ⚠ Stripe deps failed — run: uv pip install -e '.[payments-fiat]'"
fi

# Build browser bridge if Node.js is available
if command -v node &>/dev/null && [ -f "bridge/browser/package.json" ]; then
    if [ ! -d "bridge/browser/dist" ]; then
        _spin "Building browser bridge" bash -c 'cd bridge/browser && npm install --silent && npm run build --silent' || true
    else
        echo "  ✓ Browser bridge (already built)"
    fi
fi

# Install web dashboard deps if Node.js is available, so `./start.sh --web`
# works on a fresh clone (web/node_modules is gitignored). Verify vite
# ACTUALLY RUNS — not just that a symlink exists — and clean-install from
# the committed lockfile if it doesn't (same logic as start.sh/update.sh).
if command -v node &>/dev/null && command -v npm &>/dev/null && [ -f "web/package.json" ]; then
    if (cd web && ./node_modules/.bin/vite --version >/dev/null 2>&1); then
        echo "  ✓ Web dashboard deps (already installed)"
    else
        if [ -f "web/package-lock.json" ]; then
            _spin "Installing web dashboard deps" bash -c 'cd web && npm ci --silent || (rm -rf node_modules && npm install --silent)' || \
                echo "  ⚠ web dashboard deps failed — run 'cd web && npm install' before ./start.sh --web"
        else
            _spin "Installing web dashboard deps" bash -c 'cd web && rm -rf node_modules && npm install --silent' || \
                echo "  ⚠ web dashboard deps failed — run 'cd web && npm install' before ./start.sh --web"
        fi
    fi
fi

# ── First-time setup ──

# Create HEARTBEAT.md if it doesn't exist
if [ ! -f "HEARTBEAT.md" ]; then
    cat > HEARTBEAT.md << 'HEARTBEAT_EOF'
# Standing Orders
#
# Add tasks below for the agent to execute on each heartbeat cycle.
# The agent checks this file periodically (default: every 30 min).
# When all tasks are done, it responds HEARTBEAT_OK and idles.
# Remove or clear orders to stop background work.
#
# You can also manage orders via chat using the heartbeat tool:
#   "add a heartbeat order to check my email"
#   "list my standing orders"
#   "clear all heartbeat orders"
HEARTBEAT_EOF
    echo "  ✓ HEARTBEAT.md created (edit to add standing orders)"
else
    echo "  ✓ HEARTBEAT.md found"
fi

# Create AGENT_PROGRAM.md if it doesn't exist
if [ ! -f "AGENT_PROGRAM.md" ]; then
    cat > AGENT_PROGRAM.md << 'AGENT_PROGRAM_EOF'
# Agent Program
#
# Your research constitution. Read at the start of every AutoLoop session.
# Edit this file to improve your autonomous research strategy over time.
# The agent reads it; the owner writes it. Both improve it together.
#
# See docs/47-AUTOLOOP.md for full design.

## Research Philosophy

- One change per iteration. Never modify two things at once.
- Prefer deletions over additions. A simplification that holds the metric is a win.
- When stuck (5+ discards): re-read the journal, try near-miss combinations,
  try the opposite of what failed, or make a more radical change.

## Metric Interpretation

- "Better" means strictly improved, not equal.
- Small improvement + clean code beats large improvement + complex code.
- Equal metric, simpler code? Keep it — that is a simplification win.

## Domain Rules

(Add project-specific constraints here)

## What Has Worked

(Annotate after sessions)

## What Has Not Worked

(Annotate after sessions)
AGENT_PROGRAM_EOF
    echo "  ✓ AGENT_PROGRAM.md created (edit to customize research strategy)"
else
    echo "  ✓ AGENT_PROGRAM.md found"
fi

echo ""
if [ ! -f "config.yaml" ]; then
    echo "  → No config.yaml found. Running the setup wizard..."
    echo ""
    # Activate venv and run the wizard
    source .venv/bin/activate 2>/dev/null || true
    python3 -m cli.main init 2>/dev/null || elophanto init 2>/dev/null || \
        echo "  ⚠ Could not run setup wizard. Run 'elophanto init' manually after activating the venv."
else
    echo "  ✓ config.yaml found (re-run setup with: elophanto init)"
fi

# ── Post-wizard initialisation ──
# Generate the Ed25519 agent identity proactively. It would otherwise
# be auto-created on first agent boot, but the doctor flags its
# absence as a warning — which is confusing for new operators who just
# completed setup. Creating it here makes the post-setup doctor green.
source .venv/bin/activate 2>/dev/null || true
if [ ! -f "$HOME/.elophanto/agent_identity.pem" ]; then
    echo "  → Generating agent identity (Ed25519)..."
    python3 -c "from pathlib import Path; from core.agent_identity import load_or_create; load_or_create(Path.home() / '.elophanto' / 'agent_identity.pem', auto_create=True); print('  ✓ Agent identity created')" 2>/dev/null || \
        echo "  ⚠ Identity generation skipped (agent will create it on first start)"
else
    echo "  ✓ Agent identity already present"
fi

# Vault initialisation prompt. Vault is opt-in (operator may not need
# stored secrets) but if they DO want it, prompting at setup time
# beats discovering "secrets-using tools unavailable" later. Skip
# silently if Vault.exists() already.
if [ -f "config.yaml" ]; then
    if python3 -c "from core.vault import Vault; from pathlib import Path; exit(0 if Vault.exists(Path('.')) else 1)" 2>/dev/null; then
        echo "  ✓ Vault already initialised"
    else
        echo ""
        echo "  ▸ Vault stores API keys, wallet seeds, OAuth tokens etc."
        echo "    Initialise now? (y/N — skip if you don't plan to use email/payments/etc.)"
        read -r INIT_VAULT
        if [[ "$INIT_VAULT" =~ ^[Yy]$ ]]; then
            python3 -m cli.main vault init 2>/dev/null || elophanto vault init 2>/dev/null || \
                echo "  ⚠ Vault init failed — run 'elophanto vault init' later"
        else
            echo "  [skipped — secrets-using tools will be unavailable until you run 'elophanto vault init']"
        fi
    fi
fi

echo ""
echo "  Setup complete! To get started:"
echo ""
echo "    source .venv/bin/activate    # activate the environment"
if [ ! -f "config.yaml" ]; then
    echo "    elophanto init               # first-time configuration"
fi
echo "    elophanto chat               # start chatting"
echo ""
echo "  Optional extras:"
echo "    uv pip install -e '.[desktop]'        # Desktop GUI agent (pyautogui)"
echo "    uv pip install -e '.[payments-cdp]'   # Coinbase AgentKit (managed wallet)"
echo "    uv pip install -e '.[payments-fiat]'  # Stripe fiat rail (cards/bank — starts in test mode)"
echo ""
echo "  Wallet chains (set default_chain in config.yaml):"
echo "    base (default)  — EVM, low gas fees"
echo "    solana           — Solana, SOL + USDC"
echo "    ethereum         — Ethereum mainnet"
echo ""
echo "  The setup wizard (elophanto init) configures:"
echo "    LLM providers, models, permissions, browser, desktop,"
echo "    Telegram/Discord/Slack, email, payments, Replicate,"
echo "    gateway, swarm, scheduler, MCP, autonomous mind, heartbeat."
echo ""
echo "  Edit any section later: elophanto init edit <section>"
echo ""
