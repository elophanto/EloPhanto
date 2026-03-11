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

# Check/install uv
if ! command -v uv &>/dev/null; then
    echo "  → Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
echo "  ✓ uv $(uv --version 2>/dev/null | head -1)"

# Check Node.js (for browser bridge)
if command -v node &>/dev/null; then
    NODE_VERSION=$(node --version)
    echo "  ✓ Node.js $NODE_VERSION"
else
    echo "  ⚠ Node.js not found (optional — needed for browser automation)"
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

echo ""
echo "  → Installing dependencies..."
uv sync 2>/dev/null
uv pip install -e '.[payments]' 2>/dev/null
uv pip install -e '.[mcp]' 2>/dev/null
echo "  ✓ Core dependencies installed (includes crypto wallet + MCP support)"

# Install desktop GUI deps if configured
if grep -q "desktop:" config.yaml 2>/dev/null && grep -A1 "desktop:" config.yaml 2>/dev/null | grep -q "enabled: true"; then
    echo "  → Installing desktop GUI agent dependencies..."
    uv pip install -e '.[desktop]' 2>/dev/null && \
        echo "  ✓ Desktop agent deps installed (pyautogui + aiohttp)" || \
        echo "  ⚠ Desktop deps install failed (optional — run: uv pip install -e '.[desktop]')"
fi

# Detect Solana chain
if grep -q "default_chain: solana" config.yaml 2>/dev/null; then
    echo "  ✓ Solana wallet detected (solders + base58 included in core deps)"
fi

# Install Coinbase AgentKit if configured
if grep -q "provider: agentkit" config.yaml 2>/dev/null; then
    echo "  → Installing Coinbase AgentKit (CDP provider detected)..."
    uv pip install -e '.[payments-cdp]' 2>/dev/null && \
        echo "  ✓ Coinbase AgentKit installed" || \
        echo "  ⚠ AgentKit install failed (optional — switch to provider: local in config.yaml)"
fi

# Build browser bridge if Node.js is available
if command -v node &>/dev/null && [ -f "bridge/browser/package.json" ]; then
    if [ ! -d "bridge/browser/dist" ]; then
        echo "  → Building browser bridge..."
        (cd bridge/browser && npm install --silent 2>/dev/null && npm run build --silent 2>/dev/null) || true
        echo "  ✓ Browser bridge built"
    else
        echo "  ✓ Browser bridge (already built)"
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
