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

# Create venv and install dependencies
echo ""
echo "  → Installing dependencies..."
uv sync 2>/dev/null
uv pip install -e . 2>/dev/null
echo "  ✓ Dependencies installed"

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

# Create default config if missing
if [ ! -f "config.yaml" ]; then
    echo "  → Run 'elophanto init' to create your configuration"
fi

echo ""
echo "  Setup complete! To get started:"
echo ""
echo "    source .venv/bin/activate    # activate the environment"
echo "    elophanto init               # first-time configuration"
echo "    elophanto chat               # start chatting"
echo ""
