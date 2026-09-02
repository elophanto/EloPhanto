#!/usr/bin/env python3
"""Live check of the agent-driven sign-in and signed-in read, outside the
chat — the same Agent, the same tools, the same vault (docs/90).

    ELOPHANTO_VAULT_PASSWORD=… python3 scripts/watch_live_check.py --brand "Brand E" [--brand …] [--read]

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
    ap.add_argument("--dry-form", action="store_true",
                    help="no vault: only let the agent get each brand's sign-in form on screen and report")
    args = ap.parse_args()

    import logging

    from core.agent import Agent
    from core.config import load_config
    from core.vault import Vault

    cfg = load_config("config.yaml")
    # The agent's steps (every tool it calls, every verdict) go to a log
    # beside the login checks, so a miss can be read afterwards.
    log_dir = Path(str(getattr(cfg, "workspace", "") or "workspace")) / "login-checks"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, filename=str(log_dir / "live-check.log"),
                        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
    logging.getLogger("websockets").setLevel(logging.WARNING)
    agent = Agent(cfg)
    pw = os.environ.get("ELOPHANTO_VAULT_PASSWORD", "")
    if Vault.exists(".") and pw:
        agent._vault = Vault.unlock(".", pw)
        print("vault unlocked")
    elif Vault.exists(".") and not args.dry_form:
        print("ELOPHANTO_VAULT_PASSWORD not set — sign-ins need the vault (or use --dry-form)", file=sys.stderr)
        return 2
    await agent.initialize()
    reg = agent._registry
    if args.dry_form:
        return await dry_form(agent, args.brand, args.company)
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


async def dry_form(agent, brands: list[str], company: str) -> int:
    """The agent's half only: get the sign-in form on screen (or report a
    live session / a puzzle / no form), with proof — no credentials
    involved. A screenshot per brand is filed beside the login checks."""
    from core.watch_login import agent_opens_form, judge_session, page_text
    from core.watch_observe import dismiss_consent

    wm = agent._watch_manager
    bm = agent._browser_manager
    shots = Path(str(getattr(agent._config, "workspace", "") or "workspace")) / "login-checks"
    shots.mkdir(parents=True, exist_ok=True)
    for brand in brands:
        subj = await wm.get_subject_by_name(brand, company)
        if subj is None:
            print(f"\n=== {brand}: not in the register")
            continue
        print(f"\n=== dry form: {brand} — {subj.url}")
        await bm.call_tool("browser_navigate", {"url": subj.url})
        await bm.call_tool("browser_wait", {"ms": 3500})
        await dismiss_consent(bm)
        rep = await agent_opens_form(agent, subj.url)
        print(f"  agent: STATE={rep['state']}  PROOF={rep['proof'][:120]!r}  steps={rep['steps']}")
        print(f"  tools used: {', '.join(rep['tools'])}")
        print(f"  agent said: {rep['note'][:300]}")
        m_state, evidence = await judge_session(agent._router, await page_text(bm))
        print(f"  page judged: {m_state} ({evidence[:80]!r})")
        target = shots / f"{subj.url.split('//')[-1].split('/')[0].removeprefix('www.').replace('.', '-')}-dryform.jpg"
        try:
            await bm.call_tool("browser_capture", {"path": str(target)})
            print(f"  screenshot: {target}")
        except Exception as e:
            print(f"  screenshot failed: {e}")
    try:
        await agent.shutdown()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
