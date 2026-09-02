#!/usr/bin/env python3
"""Live check of the agent-driven sign-in and signed-in read, outside the
chat — the same Agent, the same tools, the same vault (docs/90).

    ELOPHANTO_VAULT_PASSWORD=… python3 scripts/watch_live_check.py --brand "Spin Blitz" [--brand …] [--read]

Runs ``watch_login`` for each brand (the agent gets the form on screen,
the code types the credentials, the model judges with proof) and, with
``--read``, the registered catalog read for every brand whose session is
live. Close the chat first: the browser profile is shared.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", action="append", default=[], help="brand name in the register (repeatable)")
    ap.add_argument("--read", action="store_true", help="after sign-in, read the lobby/store/promos/VIP as a player")
    ap.add_argument("--kinds", default="provider,game,coin_package,promotion,loyalty_tier")
    ap.add_argument("--company", default="elophanto")
    args = ap.parse_args()

    from core.agent import Agent
    from core.config import load_config
    from core.vault import Vault

    cfg = load_config("config.yaml")
    agent = Agent(cfg)
    pw = os.environ.get("ELOPHANTO_VAULT_PASSWORD", "")
    if Vault.exists(".") and pw:
        agent._vault = Vault.unlock(".", pw)
        print("vault unlocked")
    elif Vault.exists("."):
        print("ELOPHANTO_VAULT_PASSWORD not set — sign-ins need the vault", file=sys.stderr)
        return 2
    await agent.initialize()
    reg = agent._registry
    login = reg.get("watch_login")
    collect = reg.get("watch_catalog_collect")
    if login is None or collect is None:
        print("watch tools not registered", file=sys.stderr)
        return 2

    live: list[str] = []
    for brand in args.brand:
        print(f"\n=== watch_login: {brand}")
        res = await login.execute({"action": "login", "subject": brand, "retry_after_hours": 0,
                                   "company_id": args.company})
        rows = (res.data or {}).get("results") or (res.data or {}).get("rows") or []
        if not res.success:
            print("  error:", res.error)
        for r in rows if isinstance(rows, list) else []:
            print(f"  {r.get('brand')}: {r.get('verdict')} — {str(r.get('note', ''))[:200]}")
            if r.get("agent"):
                print("    agent:", json.dumps(r["agent"])[:300])
            if r.get("verdict") in ("logged_in", "already_logged_in"):
                live.append(str(r.get("brand")))
    if args.read:
        for brand in live:
            print(f"\n=== registered read: {brand}")
            res = await collect.execute({"subject": brand, "kinds": args.kinds.split(","),
                                         "customer_state": "registered", "research": False,
                                         "sign_in_if_missing": False, "company_id": args.company})
            if not res.success:
                print("  error:", res.error)
                continue
            for b in (res.data or {}).get("brands", []):
                print(f"  {b.get('subject')}: pages_read={b.get('pages_read')} " +
                      ", ".join(f"{k}={v.get('found', 0)}/{v.get('new', 0)} new" for k, v in b.get("kinds", {}).items()))
    try:
        await agent.shutdown()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
