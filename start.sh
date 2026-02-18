#!/usr/bin/env bash
# EloPhanto — Quick launcher
# Activates the venv and runs elophanto with any arguments.
# Usage: ./start.sh chat
#        ./start.sh telegram
#        ./start.sh vault list

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

# Run elophanto with all passed arguments, default to 'chat'
if [ $# -eq 0 ]; then
    exec elophanto chat
else
    exec elophanto "$@"
fi
