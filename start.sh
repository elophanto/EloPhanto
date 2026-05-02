#!/usr/bin/env bash
# EloPhanto — Quick launcher
# Activates the venv and runs elophanto with any arguments.
# Usage: ./start.sh                  → CLI chat (direct mode)
#        ./start.sh --web            → gateway + web dashboard
#        ./start.sh gateway          → gateway only (CLI + channels)
#        ./start.sh telegram         → telegram adapter
#        ./start.sh vault list       → any elophanto command
#        ./start.sh --daemon         → install + start as background daemon
#                                       (launchd on macOS, systemd on Linux —
#                                        keeps running after terminal closes)
#        ./start.sh --stop-daemon    → stop and remove the daemon
#        ./start.sh --daemon-status  → show running / stopped state
#        ./start.sh --daemon-logs    → tail the daemon log

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

# ── Daemon shortcuts ──
# `./start.sh --daemon`         → install + start as background service (launchd/systemd)
# `./start.sh --stop-daemon`    → stop + remove the daemon
# `./start.sh --daemon-status`  → show state (running / stopped / not installed)
# `./start.sh --daemon-logs`    → tail the daemon log
case "${1:-}" in
    --daemon)
        shift
        exec elophanto daemon install "$@"
        ;;
    --stop-daemon)
        shift
        exec elophanto daemon uninstall "$@"
        ;;
    --daemon-status)
        exec elophanto daemon status
        ;;
    --daemon-logs)
        shift
        exec elophanto daemon logs "$@"
        ;;
esac

# ── Preflight: refuse to start if the doctor finds blockers ──
# Skipped when running diagnostic / setup commands directly so the
# user can fix whatever the doctor would have flagged.
case "${1:-}" in
    doctor|init|vault|skills|mcp|update|rollback|--help|-h|"")
        # for empty arg (default → chat) we DO want to gate
        if [ -z "${1:-}" ] || [ "${1:-}" = "--web" ]; then
            if ! elophanto doctor >/dev/null 2>&1; then
                echo ""
                echo "  ⚠ EloPhanto doctor found blockers. Running again with full output:"
                echo ""
                elophanto doctor || true
                echo ""
                echo "  Fix the items above, then re-run ./start.sh."
                echo "  (skip the gate with: SKIP_DOCTOR=1 ./start.sh)"
                if [ "${SKIP_DOCTOR:-0}" != "1" ]; then
                    exit 1
                fi
                echo "  SKIP_DOCTOR=1 set — proceeding anyway."
            fi
        fi
        ;;
esac

# ── Bootstrap autoprompt: if knowledge/system is empty the planner ──
# improvises and the user gets bad answers on day one. Offer to bootstrap.
if [ ! -f "knowledge/system/identity.md" ] && [ -t 0 ]; then
    echo ""
    echo "  knowledge/system/{identity,capabilities,styleguide}.md is missing."
    echo "  The planner uses these for grounding — without them the agent"
    echo "  improvises and tends to hallucinate on day one."
    echo ""
    read -r -p "  Run \`elophanto bootstrap\` now? (Y/n) " ans
    case "${ans}" in
        [Nn]*) echo "  Skipped. Run \`elophanto bootstrap\` later." ;;
        *) elophanto bootstrap ;;
    esac
    echo ""
fi

# Kill any leftover gateway from a previous unclean shutdown
STALE_PID=$(lsof -ti :18789 2>/dev/null || true)
if [ -n "$STALE_PID" ]; then
    echo "Killing stale gateway on port 18789 (pid $STALE_PID)..."
    kill -KILL $STALE_PID 2>/dev/null || true
    sleep 0.5
fi

# --web flag: start gateway + web dashboard together
if [ "$1" = "--web" ]; then
    WEB_DIR="$SCRIPT_DIR/web"
    if [ ! -d "$WEB_DIR/node_modules" ]; then
        echo "Web dashboard dependencies not installed. Running npm install..."
        (cd "$WEB_DIR" && npm install)
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
