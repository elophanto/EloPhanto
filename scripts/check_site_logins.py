#!/usr/bin/env python3
"""Do the stored site logins still work?

A thin CLI over the organ's own capability (``core.watch_login``) — the
same code path the agent runs through ``watch_login``, so what this
reports is what the agent will do unattended.

    python3 scripts/check_site_logins.py                      # every brand
    python3 scripts/check_site_logins.py --only brand-a.example     # one or more
    python3 scripts/check_site_logins.py --assist 90          # clear puzzles by hand
    python3 scripts/check_site_logins.py --no-proxy           # direct

Nothing is written to the evidence register: this is a credentials health
check, not an observation. Screenshots land in workspace/login-checks/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT_DIR = ROOT / "workspace" / "login-checks"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=[], help="domains to check")
    ap.add_argument("--no-proxy", action="store_true", help="skip the state exit")
    ap.add_argument("--password", default="", help="vault master password")
    ap.add_argument(
        "--assist", type=int, default=0, metavar="SECONDS",
        help="pause on an anti-bot puzzle so you can clear it in the Chrome window",
    )
    args = ap.parse_args()

    from core.browser_manager import BrowserManager
    from core.config import load_config
    from core.vault import Vault
    from core.watch_login import login_to_site
    from core.watch_observe import pin_password

    cfg = load_config()
    pw = args.password or __import__("getpass").getpass("vault password: ")
    vault = Vault.unlock(str(ROOT), pw)
    index = vault.get("social_casino_logins") or {}
    if isinstance(index, str):
        index = json.loads(index)
    targets = {
        domain: vault.get(domain)
        for domain in sorted(set(index.values()))
        if not args.only or domain in args.only
    }
    if not targets:
        print("no logins in the vault (key: social_casino_logins)")
        return

    bm = BrowserManager.from_config(cfg.browser)
    px = cfg.proxy
    if not args.no_proxy and px.enabled and px.host and px.port:
        bm.proxy_server = px.proxy_url()
        bm.proxy_username = px.username
        bm.proxy_password = pin_password(px.password)
        bm.proxy_bypass = list(px.bypass)
        print(f"exit: {px.host}:{px.port} (state {px.state})")
    else:
        print("exit: direct")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        # Warm up on a page that never blocks, so the first brand does not
        # pay for the proxy handshake.
        await bm.call_tool("browser_navigate", {"url": "https://example.com"})
        await bm.call_tool("browser_wait", {"ms": 1500})
        for domain, creds in targets.items():
            if not isinstance(creds, dict):
                continue
            res = await login_to_site(
                bm, creds,
                screenshot_path=str(OUT_DIR / f"{domain.replace('.', '-')}.jpg"),
                assist_seconds=args.assist,
            )
            res["domain"] = domain
            rows.append(res)
            print(f"  {res['verdict']:18s} {res['brand']:22s} {res['note'][:64]}", flush=True)
    finally:
        try:
            await bm.shutdown()
        except Exception:
            pass

    (OUT_DIR / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    ok = [r for r in rows if r["verdict"] in ("logged_in", "already_logged_in")]
    chal = [r for r in rows if r["verdict"] == "challenge"]
    print(f"\n{len(ok)}/{len(rows)} signed in — details: {OUT_DIR}/results.json")
    for r in rows:
        if r["verdict"] not in ("logged_in", "already_logged_in"):
            print(f"  · {r['brand']}: {r['verdict']} ({r['note'][:70]})")
    if chal and not args.assist:
        print(
            f"\n{len(chal)} brand(s) show an image/audio anti-bot puzzle. Those are not "
            f"solved here by design — rerun with --assist 90 and clear each one in the "
            f"Chrome window; the session then persists for unattended runs."
        )


if __name__ == "__main__":
    asyncio.run(main())
