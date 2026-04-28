"""CLI wrapper around ``tools.pumpfun.orchestrator`` for shell debugging.

Inside the agent, prefer the ``pump_livestream`` native tool — it uses
the agent's already-unlocked vault directly. This script is for manual
testing from a shell, where ``VAULT_PASSWORD`` must be supplied.

Usage::

    VAULT_PASSWORD=... python pump_auth.py login
    VAULT_PASSWORD=... python pump_auth.py token
    VAULT_PASSWORD=... python pump_auth.py whoami
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Make the project root importable
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _unlock_vault():  # type: ignore[no-untyped-def]
    """Open the project vault using VAULT_PASSWORD from env."""
    from core.config import load_config
    from core.vault import Vault

    password = os.environ.get("VAULT_PASSWORD")
    if not password:
        raise RuntimeError(
            "VAULT_PASSWORD env var required to unlock the vault. "
            "Set it via the agent shell session, or run via the "
            "pump_livestream native tool from chat (no env var needed)."
        )
    config = load_config()
    return Vault.unlock(config.project_root, password)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pump.fun auth helper (CLI wrapper around the orchestrator)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="Force a fresh sign+login, cache JWT")
    sub.add_parser("token", help="Print cached JWT (refresh if stale)")
    sub.add_parser("whoami", help="Print the wallet address that would sign")
    args = parser.parse_args()

    from tools.pumpfun.orchestrator import LivestreamOrchestrator

    vault = _unlock_vault()
    orch = LivestreamOrchestrator(vault)

    if args.cmd == "login":
        token = orch.login()
        print(json.dumps({"jwt_preview": f"{token[:24]}...", "cached": True}))
    elif args.cmd == "token":
        print(orch.get_token())
    elif args.cmd == "whoami":
        print(orch.wallet_address())


if __name__ == "__main__":
    main()
