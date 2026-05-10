# Proposal: Remote browser support

**Status:** Draft — proposed, not approved.
**Author:** EloPhanto + Claude (Opus 4.7)
**Date:** 2026-05-06
**Related:** [docs/08-BROWSER.md](../08-BROWSER.md)

---

## Problem

EloPhanto currently runs the user's local Chrome via the Playwright-based Node bridge (`bridge/browser/`), with `cdp_port: 9222` and the user's profile directory mounted in. This works, but it has three real problems for some users and some workloads:

1. **Privacy/contamination.** The agent shares cookies, sessions, and history with the user's personal Chrome profile. Some users won't accept this.
2. **No headless option that actually works.** Sophisticated bot detection (Cloudflare, X, PerimeterX, DataDome) catches headless Chrome via TLS fingerprint, WebGL renderer, AudioContext, missing `chrome.*` properties, and HTTP/2 frame ordering. `navigator.webdriver` patching alone doesn't save you.
3. **No isolation/parallelism.** Single browser tied to the operator's machine. Sub-agents, scheduled scrapes, and headless CI runs all collide on the same profile.

A remote-browser option solves all three at once.

## Goals

- Add a config flag so the existing bridge can connect to a remote CDP WebSocket instead of (or in addition to) local Chrome.
- Keep **one tool surface** — every existing tool (`browser_navigate`, `browser_type_text`, `browser_eval`, `twitter_post`, etc.) works unchanged regardless of whether the browser is local or remote.
- Support a tiered cost model: cheap DIY for benign tasks, paid SaaS only when needed.
- No `browser-harness`-style paradigm transplant. We are not switching the agent's interaction model.

## Non-goals

- Replacing the local-Chrome path. Local stays the default; remote is opt-in.
- Building our own residential proxy / chromium-patch infra. We're consumers, not vendors.
- Ports of every existing browser tool. They should keep working unchanged.

## Why headless fails (background, for future readers)

By 2026, anti-bot vendors check signals that live below the JS sandbox:

| Signal | Where it lives | Spoofable from JS? |
|---|---|---|
| TLS/JA3+JA4 fingerprint | Network stack (C++) | No |
| HTTP/2 frame ordering | Network stack (C++) | No |
| WebGL renderer string | GPU driver | Partially — easy to lie, hard to lie consistently |
| AudioContext fingerprint | Audio stack | Partially |
| `chrome.app` / `chrome.csi` / `chrome.loadTimes` | Native bindings | Stubs detectable |
| Mouse movement entropy | Real input device | Spoofable but rare |
| Battery API / device memory / hardware concurrency | Native | Detectable on cross-check |
| `navigator.webdriver` | JS flag | Yes — but this is the *first* check, not the last |

A patched chromium binary is the only way to fix the network-layer signals. Stealth-JS plugins (`puppeteer-extra-plugin-stealth`, etc.) help with the upper layers but can't touch TLS/HTTP fingerprints.

## How browser-use cloud (and competitors) actually do it

Three stacked layers:

1. **Patched chromium binary** — TLS/HTTP stack tuned to match real Chrome. Engineering effort we don't have and shouldn't replicate.
2. **Residential or mobile-carrier proxies** — IP looks like a Comcast home, not a Hetzner datacenter. ~$10–25/GB.
3. **Scale** — one flagged IP is a small % of their pool. For us, one flagged IP = 100% of ours.

That's why pay-per-minute. We become a customer of one of these networks when we need the top tier; we don't try to build it.

## Proposed three-tier deployment model

| Tier | Cost | Coverage | Use when |
|---|---|---|---|
| **0 — Local** (today) | $0 + your real Chrome | High for any site that doesn't fingerprint hard, but contaminates personal profile | Dev/manual workflows on the operator's box |
| **1 — DIY headed-on-VPS** | ~$5/mo Hetzner | ~70% of sites | Background autonomy without touching personal Chrome; benign sites |
| **2 — Tier 1 + residential proxy** | Tier 1 + $5-15/GB | ~85% | Sites that flag datacenter IPs but don't deep-fingerprint |
| **3 — Cloud SaaS** | Pay-per-minute (~$0.05/min) | ~95-99% | X automation, Cloudflare-protected sites, sites that defeated Tier 2 |

Per-task selection: cheap tier by default, escalate only when needed.

## Architecture: `browser.mode` config

The whole proposal collapses to one config-level abstraction:

```yaml
browser:
  enabled: true
  mode: profile        # profile | fresh | remote
  # ---- profile mode (current default) ----
  user_data_dir: /Users/0xroyce/Library/Application Support/Google/Chrome
  profile_directory: Profile 1
  use_system_chrome: true
  cdp_port: 9222
  # ---- fresh mode (new) ----
  fresh_user_data_dir: ~/.elophanto/browser-profile  # isolated profile, no contamination
  # ---- remote mode (new) ----
  remote_cdp_ws: ""                                  # e.g. wss://api.browser-use.com/cdp/<session>
  remote_provider: ""                                # informational: hetzner | browser-use | hyperbrowser | steel | local
  remote_session_timeout_minutes: 60
  # ---- shared ----
  headless: false
  viewport_width: 1280
  viewport_height: 720
```

**`mode: profile`** — current behavior. Default. No regressions.
**`mode: fresh`** — same local Chrome, but a clean isolated `--user-data-dir`. Solves the "I don't want the agent in my personal profile" complaint. ~30 LOC change, no new infra.
**`mode: remote`** — bridge connects to `remote_cdp_ws` instead of launching local Chrome. Same Playwright `connect_over_cdp(wsEndpoint=...)` call. The whole tool surface is unchanged.

The remote endpoint can be:
- A Hetzner / Fly / Railway box running headed Chromium under xvfb (Tier 1)
- A residential-proxied chromium on the same (Tier 2)
- Browser Use Cloud / Hyperbrowser / Steel.dev / Anchor / Browserless (Tier 3)

## Integration shape (Tier 3 example)

```python
# pseudo-code, not committed
class CloudBrowserSession:
    async def acquire(self) -> str:
        """Return a CDP wsEndpoint. Provider-specific."""

class BrowserUseCloudSession(CloudBrowserSession):
    async def acquire(self) -> str:
        r = await httpx.post(
            "https://api.browser-use.com/api/v2/browsers",
            headers={"X-Browser-Use-API-Key": self._api_key_ref_resolved},
            json={"profile_id": self._profile_id, "cloud_proxy_country_code": "us", "cloud_timeout": 60},
        )
        return r.json()["cdp_url"]
```

Bridge then connects via `chromium.connect_over_cdp(wsEndpoint)`. Done. The bridge doesn't need to know which provider.

## Per-task escalation

To make the tiered model usable, the agent should be able to ask for a specific tier:

```python
# tool param addition (proposed, not implemented)
browser_open_session(tier="local" | "fresh" | "remote-cheap" | "remote-stealth")
```

Defaults: most tools land on whatever `browser.mode` is set to globally. Tools known to need stealth (twitter_post, anything hitting Cloudflare) can request `"remote-stealth"` explicitly. Cost-aware: paid tiers gated behind the existing payments approval flow.

## Profile sync (Tier 3 specific)

Browser Use Cloud (and similar) support uploading a local Chrome profile so the cloud browser starts already logged in. Their flow:

```bash
export BROWSER_USE_API_KEY=<key> && curl -fsSL https://browser-use.com/profile.sh | sh
```

For us this means: operator does the X/Discord/Gmail logins once locally in a fresh profile, runs the upload, and after that scheduled tasks against the cloud browser have the same auth. **No agent involvement** in this flow — operator-driven, one-time.

## What this is NOT

- **Not adopting browser-use's framework.** They have agent + tools + LLM routing baked in. We have our own. We're consuming their *browser CDP endpoint*, not their agent stack.
- **Not adopting browser-harness.** Different paradigm (`-c '<python>'` code execution vs tool calls). Reviewed separately and rejected for primary use.
- **Not auto-update or auto-install.** Operator opts in to remote mode by editing config.

## Implementation phases

### Phase 1 — `mode: fresh` (low effort, high value)
Touches: `bridge/browser/src/index.ts` (or wherever Chrome launch happens), `core/config.py`, `tools/browser/manager.py`.
- Add `mode` field to `BrowserConfig`.
- When `mode == "fresh"`, launch local Chromium with `--user-data-dir=<fresh_user_data_dir>` and ignore `profile_directory`.
- Document in [docs/08-BROWSER.md](../08-BROWSER.md) that fresh mode persists logins across runs but doesn't share with the operator's Chrome.
- ~30 LOC + 1 doc paragraph.

### Phase 2 — `mode: remote` with manual wsEndpoint
- Add `remote_cdp_ws` config.
- When `mode == "remote"`, bridge calls `chromium.connect_over_cdp(remote_cdp_ws)` instead of launching.
- Document Tier-1 Hetzner setup as a reference recipe (xvfb + headed Chromium + remote-debugging-port + tunnel).
- No SaaS provider integration yet — operator pastes the CDP URL.
- ~50 LOC + a Hetzner setup doc.

### Phase 3 — Provider plugin: Browser Use Cloud
- New module: `tools/browser/providers/browser_use_cloud.py` implementing `acquire() -> wsEndpoint`.
- API key in vault as `browser_use_api_key`.
- Optional `cloud_proxy_country_code` and `cloud_timeout` config.
- Cost telemetry: log per-session minutes against `payments` budget; gate session creation behind `payments.approval` thresholds.
- ~100 LOC.

### Phase 4 — Per-task tier selection (optional, future)
- `browser_open_session(tier=...)` tool.
- Skill-level guidance: which tools should request which tier.
- Probably not needed v1; revisit after Phase 3 has real usage data.

## Risks

1. **Latency.** Remote browser adds ~50-200ms to every CDP round-trip. The agent makes a *lot* of CDP calls; this could meaningfully slow tasks. Mitigation: batch where possible (we already do `browser_get_elements` once per page).
2. **Session lifetime.** Browser Use Cloud free tier is 15 min, paid is 4 hours. Long-running scraping or multi-step automation can hit this. Mitigation: build session-restart logic into the bridge so a timed-out session is replaced transparently. **Important:** this is invisible to the agent; tools must not surface "session expired" as a real error.
3. **Cost runaway.** Pay-per-minute means a stuck loop bleeds money. Mitigation: hard daily/per-task cap in `payments.limits`; tool refuses to acquire a paid session if cap reached.
4. **API surface drift.** SaaS providers change auth headers, endpoint paths. Mitigation: provider plugin pattern isolates the change; one file per vendor.
5. **Profile sync auth surface.** Cloud-uploaded profiles contain real cookies. Treat as a vault-grade secret; never log the upload payload, never re-download to disk.

## Open questions

- Do we want one provider plugin or several (Browser Use Cloud + Hyperbrowser + Steel.dev)? Probably start with one (Browser Use Cloud — most documented, generous free tier) and add others on demand.
- Should `mode: remote` be a per-tool override or a process-wide setting? Lean: process-wide v1, per-task in Phase 4.
- Is there a path to running the *agent's own* outbound HTTP through the same residential proxy when the agent is doing direct API calls (not through the browser)? Out of scope for v1, worth noting.

## Decision criteria

Approve Phases 1 + 2 if any of these hold:
- We've had ≥1 user complaint about Chrome profile contamination.
- We've had ≥1 task that failed because of headless detection (we have — see X account flagging logs).
- We want background scheduled tasks to run without the operator's Chrome being open.

Approve Phase 3 if any of these hold:
- A site we need (X, LinkedIn, anything Cloudflare-protected) consistently flags Tier 1/2 attempts.
- We have paying users whose tasks justify the cost overhead.
- We want operator-free deployment (no local Chrome at all).

## Appendix: Tier-1 reference recipe (Hetzner CX11, headed-on-xvfb)

Not committed; sketched here so future-you doesn't have to rediscover it.

```bash
# On a fresh Hetzner Ubuntu box
apt update && apt install -y xvfb google-chrome-stable
# Start virtual display
Xvfb :99 -screen 0 1280x720x24 &
export DISPLAY=:99
# Launch headed Chrome with remote debugging
google-chrome \
  --remote-debugging-port=9222 \
  --remote-debugging-address=0.0.0.0 \
  --no-first-run \
  --no-default-browser-check \
  --disable-gpu \
  --user-data-dir=$HOME/.config/elophanto-chrome &
# Tunnel back to operator (over Tailscale or SSH)
# operator side: ssh -L 9223:localhost:9222 hetzner
# config.yaml: browser.remote_cdp_ws = ws://localhost:9223/devtools/browser/<id>
```

The ws ID is discoverable via `curl http://localhost:9223/json/version`. We'd add a tiny helper to do that lookup automatically.

---

**Bottom line:** Phase 1 is a 30-line change that solves the most common operator complaint. Phase 2 is the prerequisite for everything beyond. Phase 3 only when a real workload demands it. Don't build Phase 4 ahead of need.
