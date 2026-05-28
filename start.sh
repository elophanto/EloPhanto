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

# Ensure uv is discoverable. The uv installer writes ~/.local/bin
# into shell rc files but the current session may not have re-sourced
# yet, so doctor reports "uv not on PATH" even after a successful
# setup. Prepending unconditionally is a no-op when already there.
export PATH="$HOME/.local/bin:$PATH"

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
    if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
        echo "❌ Node.js + npm are required for the web dashboard."
        echo "   Install Node 20+ LTS from https://nodejs.org/ and re-run."
        exit 1
    fi
    # vite 6 needs Node 18+. An older Node is a common cause of a
    # broken install that then fails at runtime.
    NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
    if [ "$NODE_MAJOR" -lt 18 ] 2>/dev/null; then
        echo "❌ Node $(node -v) is too old — the web dashboard (vite 6) needs Node 18+."
        echo "   Install Node 20+ LTS from https://nodejs.org/ and re-run."
        exit 1
    fi

    # Verify vite ACTUALLY RUNS, not just that a symlink exists. A
    # partial / cross-machine / interrupted node_modules leaves the
    # .bin/vite symlink in place while vite/dist/node/cli.js is missing
    # — which is exactly the 'Cannot find module …/vite/dist/node/cli.js'
    # error. So we run `vite --version` and, if it fails, do a CLEAN
    # reinstall (npm ci wipes node_modules and rebuilds from the
    # committed package-lock.json — the reproducible, self-healing path).
    web_vite_ok() { (cd "$WEB_DIR" && ./node_modules/.bin/vite --version >/dev/null 2>&1); }
    if ! web_vite_ok; then
        echo "Web dashboard deps missing or broken — reinstalling (clean)..."
        if [ -f "$WEB_DIR/package-lock.json" ]; then
            (cd "$WEB_DIR" && npm ci) || (cd "$WEB_DIR" && rm -rf node_modules && npm install)
        else
            (cd "$WEB_DIR" && rm -rf node_modules && npm install)
        fi
    fi
    if ! web_vite_ok; then
        echo "❌ vite still won't run after a clean reinstall."
        echo "   Node: $(node -v)  npm: $(npm -v)"
        echo "   Try manually:  cd web && rm -rf node_modules package-lock.json && npm install"
        echo "   Then paste the npm output here if it still fails."
        exit 1
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

    # Start web dashboard — use the locally-installed vite binary
    # directly (not `npx`, which can try to fetch a different version).
    # Silence DEP0205 (module.register) — a benign deprecation Node 22+
    # raises about vite's tooling; harmless, just noise at the prompt.
    # --disable-warning is supported on Node 21.1+; older Node ignores
    # the env var, so it's safe to set unconditionally.
    (cd "$WEB_DIR" && NODE_OPTIONS="${NODE_OPTIONS:-} --disable-warning=DEP0205" ./node_modules/.bin/vite --host) &
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
