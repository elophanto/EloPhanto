#!/usr/bin/env bash
# EloPhanto — One-command update
#
# Pulls the latest code from origin, refreshes Python deps, rebuilds the
# browser bridge, and runs `elophanto config migrate` so new config
# sections added in newer releases (e.g. the Phase 3 arbiter) are
# patched into your existing config.yaml without losing your settings.
#
# Safe to run repeatedly. Stops on the first failure. Stashes any local
# changes before pulling and restores them after.
#
# Usage: ./update.sh

set -e

echo ""
echo "  ╔══════════════════════════════════════════════════════════════╗"
echo "  ║   EloPhanto — update (git pull + deps + bridge + config)     ║"
echo "  ╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Locate project root (the directory this script lives in) ──
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$PROJECT_DIR"

# ── Sanity check: must be a git repo ──
if [ ! -d ".git" ]; then
    echo "  ✗ Not a git repository: $PROJECT_DIR"
    echo "    Re-install with: git clone https://github.com/elophanto/EloPhanto.git"
    exit 1
fi

# ── Stash local changes if any ──
STASHED=0
if [ -n "$(git status --porcelain)" ]; then
    echo "  → Stashing local changes..."
    git stash push -m "elophanto-update-autostash" >/dev/null
    STASHED=1
fi

# ── Fetch + pull ──
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
echo "  → Fetching origin/$BRANCH..."
git fetch origin --quiet

BEHIND=$(git rev-list "HEAD..origin/$BRANCH" --count 2>/dev/null || echo "?")
if [ "$BEHIND" = "0" ]; then
    echo "  ✓ Already up to date with origin/$BRANCH"
else
    echo "  → Pulling $BEHIND new commit(s)..."
    if ! git pull --ff-only origin "$BRANCH"; then
        echo "  ✗ Pull failed (merge conflict?). Resolve with 'git pull' manually."
        if [ "$STASHED" -eq 1 ]; then
            git stash pop >/dev/null 2>&1 || true
        fi
        exit 1
    fi
fi

# ── Restore stash ──
if [ "$STASHED" -eq 1 ]; then
    echo "  → Restoring local changes from stash..."
    if ! git stash pop >/dev/null 2>&1; then
        echo "  ⚠ Could not restore stash automatically — run 'git stash pop' manually."
    fi
fi

# ── Update Python deps ──
export PATH="$HOME/.local/bin:$PATH"
if command -v uv &>/dev/null; then
    echo "  → Updating Python dependencies (uv)..."
    uv pip install -e . --quiet || echo "  ⚠ uv install failed; try ./setup.sh"
else
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    fi
    echo "  → Updating Python dependencies (pip)..."
    python3 -m pip install -e . --quiet || echo "  ⚠ pip install failed; try ./setup.sh"
fi

# ── Rebuild browser bridge ──
if [ -f "bridge/browser/package.json" ] && command -v npm &>/dev/null; then
    echo "  → Rebuilding browser bridge..."
    (cd bridge/browser && npm install --silent && npm run build --silent) || \
        echo "  ⚠ Bridge rebuild failed; run 'npm run build' in bridge/browser/ manually."
fi

# ── Install / refresh web dashboard deps ──
# web/node_modules is gitignored, so a pull never brings deps. Verify
# vite ACTUALLY RUNS (not just that a symlink exists — a partial /
# cross-machine node_modules leaves .bin/vite dangling, which is the
# 'Cannot find module .../vite/dist/node/cli.js' failure). If it
# doesn't run, do a clean reinstall from the committed lockfile.
if [ -f "web/package.json" ] && command -v npm &>/dev/null; then
    if (cd web && ./node_modules/.bin/vite --version >/dev/null 2>&1); then
        echo "  ✓ Web dashboard deps (already installed)"
    else
        echo "  → Installing web dashboard dependencies (clean)..."
        if [ -f "web/package-lock.json" ]; then
            (cd web && npm ci --silent) || (cd web && rm -rf node_modules && npm install --silent) || \
                echo "  ⚠ Web deps install failed; run 'cd web && npm install' manually."
        else
            (cd web && rm -rf node_modules && npm install --silent) || \
                echo "  ⚠ Web deps install failed; run 'cd web && npm install' manually."
        fi
    fi
fi

# ── Run config migrations ──
# This is the crucial step that distinguishes update.sh from a bare
# `git pull`: new releases add config sections (e.g. autonomous_mind.arbiter
# in Phase 3) that the operator's existing config.yaml is missing. The
# migrate command surgically inserts them with safe defaults, preserving
# the operator's existing values and comments. Idempotent.
if [ -f "config.yaml" ]; then
    echo "  → Checking for new config sections..."
    # Activate venv so `python3 -m cli.main` finds our deps.
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate 2>/dev/null || true
    fi
    if ! python3 -m cli.main config migrate -y; then
        echo "  ⚠ Config migration failed; review config.yaml manually."
        exit 1
    fi
else
    echo "  ⚠ No config.yaml — skipping config migration."
    echo "    Run './setup.sh' or 'elophanto init' first."
fi

# ── Sync skills if registry is reachable ──
if command -v elophanto &>/dev/null; then
    echo "  → Syncing skills index..."
    elophanto skills sync --quiet 2>/dev/null || true
fi

echo ""
echo "  ✓ Update complete. Restart EloPhanto to pick up the new version."
echo ""
