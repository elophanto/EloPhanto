#!/usr/bin/env bash
# EloPhanto — Quick launcher
# Activates the venv and runs elophanto with any arguments.
# Usage: ./start.sh              → CLI chat (direct mode)
#        ./start.sh --web        → gateway + web dashboard
#        ./start.sh gateway      → gateway only (CLI + channels)
#        ./start.sh telegram     → telegram adapter
#        ./start.sh vault list   → any elophanto command

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "Virtual environment not found. Run ./setup.sh first."
    exit 1
fi

# --web flag: start gateway + web dashboard together
if [ "$1" = "--web" ]; then
    WEB_DIR="$SCRIPT_DIR/web"
    if [ ! -d "$WEB_DIR/node_modules" ]; then
        echo "Web dashboard dependencies not installed. Running npm install..."
        (cd "$WEB_DIR" && npm install)
    fi

    # Kill any leftover gateway from a previous unclean shutdown
    STALE_PID=$(lsof -ti :18789 2>/dev/null || true)
    if [ -n "$STALE_PID" ]; then
        echo "Killing stale gateway on port 18789 (pid $STALE_PID)..."
        kill -KILL $STALE_PID 2>/dev/null || true
        sleep 0.5
    fi

    echo "Starting EloPhanto gateway + web dashboard..."
    echo "  Gateway:   ws://127.0.0.1:18789"
    echo "  Dashboard: http://localhost:3000"
    echo ""

    GATEWAY_PID=""
    WEB_PID=""

    cleanup() {
        trap '' EXIT INT TERM HUP  # ignore all signals during cleanup
        echo ""
        echo "Shutting down..."
        # SIGTERM first — let gateway release the port gracefully
        [ -n "$WEB_PID" ]     && kill "$WEB_PID"     2>/dev/null
        [ -n "$GATEWAY_PID" ] && kill "$GATEWAY_PID" 2>/dev/null
        # Give 2 seconds for graceful shutdown, then force kill
        sleep 2
        [ -n "$WEB_PID" ]     && kill -KILL "$WEB_PID"     2>/dev/null
        [ -n "$GATEWAY_PID" ] && kill -KILL "$GATEWAY_PID" 2>/dev/null
        wait 2>/dev/null
        exit 0
    }
    trap cleanup INT TERM HUP EXIT

    # Start gateway in background (--no-cli since there's no terminal stdin)
    elophanto gateway --no-cli &
    GATEWAY_PID=$!

    # Give gateway a moment to start
    sleep 1

    # Start web dashboard
    (cd "$WEB_DIR" && npx vite --host) &
    WEB_PID=$!

    # Wait for either to exit
    wait $GATEWAY_PID $WEB_PID
fi

# Run elophanto with all passed arguments, default to 'chat'
if [ $# -eq 0 ]; then
    exec elophanto chat
else
    exec elophanto "$@"
fi
