#!/usr/bin/env bash
# EloPhanto Open — local installer (wrapper around setup.sh)
#
# For normal users who want an always-on agent without setup:
#   → Apply for EloPhanto Hosted: https://elophanto.com/hire
#     (design partners: managed box, €149/mo — see docs/20-HOSTED-PLATFORM.md)
#
# For operators / self-host / CLI lovers (this script):
#   git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto
#   ./install.sh
#   ./start.sh
#
# There is no curl|bash product path that replaces Hosted for basic users.
# If you arrived via an old curl …/install doc, you want either Hosted signup
# or this Open path — not a missing root magic installer.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo ""
echo "  EloPhanto Open — local operator install"
echo "  ----------------------------------------"
echo "  Hosted (no setup, always-on):  https://elophanto.com/hire"
echo "  Open (this machine, full CLI): continuing with ./setup.sh"
echo ""

if [[ ! -x ./setup.sh ]]; then
  echo "  ✗ setup.sh missing or not executable in $ROOT" >&2
  exit 1
fi

exec ./setup.sh "$@"
