# 73 — Proxy routing (browser only, v1)

**Status:** v1 implementation (2026-05-10).
**Author:** EloPhanto.
**Related:** [docs/08-BROWSER.md](08-BROWSER.md), [docs/proposals/HOSTED-DESKTOP.md](proposals/HOSTED-DESKTOP.md).

---

## What this solves

EloPhanto's browser drives real Chrome through Playwright. When the agent runs on a cloud VM (Hetzner, AWS, GCP, DigitalOcean) Chrome's traffic egresses the provider's datacenter ASN — a public, well-known IP range. Sites that take anti-bot seriously (X / Twitter is the canonical example; Cloudflare-protected sites in general) match against published datacenter ranges and apply the harshest rate limits, the most aggressive captcha gating, or outright login refusal *before they even show a password field*.

When the agent runs on the operator's local Mac, the opposite problem: every automated action egresses the operator's home IP, correlating `@your-agent`'s automated activity with the human's personal account, tax filings, ISP records.

This proxy layer fixes both. Route Chrome through a residential proxy (or SOCKS / HTTP forward), keep API traffic direct, and the agent's browser footprint looks like a regular home internet user.

## What stays direct

**Only Chrome routes through the proxy in v1.** Everything else stays direct:

- LLM API calls (OpenRouter / Codex / Anthropic / Z.ai / OpenAI / Kimi / HuggingFace / Ollama) — authenticated by API key, not IP. Proxy would just burn bandwidth + add latency.
- Polymarket CLOB API, Gamma API — same story.
- Helius RPC, DAS API.
- pump.fun JWT / frontend-api-v3 / livestream WHIP.
- GitHub API (gh CLI, git push/pull).
- AgentMail / SMTP / IMAP.
- The gateway, MCP servers, agent peers (loopback / Tailscale auto-bypassed).

The Phase 2 `apply_to` list reserves space for per-tool-group routing if you want `web_search` or `web_extract` routed too — but think hard before enabling it. The proxy bill scales with what you route through it.

## Config

In `config.yaml`:

```yaml
proxy:
  enabled: true                  # off by default
  type: socks5                   # socks5 | http | https
  host: 203.0.113.10             # provider host or IP
  port: 12323                    # provider port
  username: "YOUR_PROXY_USERNAME"   # plaintext — provider gives you these
  password: "YOUR_PROXY_PASSWORD"
  bypass:                        # additional domains to bypass
    - "*.example.com"            # (loopback + 100.64/10 tailnet auto-bypassed)
  apply_to: [browser]            # v1 honours 'browser' only
  state: ""                      # US state this exit is pinned to ("NV"), if any — see below
```

`state` matters only if you use the competitive-intel organ's per-state
observation (`watch_observe geo_state=FL`). Evidence stamped with a state is a
provenance claim — "this is what a Nevada customer sees" — so the organ will
only route a specific-state request through an exit that *declares* that
state: a `proxy.pool` entry, or this single proxy with `state` set. With an
IPRoyal residential password ending `_state-florida`, set `state: FL`. If
neither declares it, `watch_observe geo_state=FL` **refuses** rather than
fetch from wherever this box sits and stamp it Florida. Declaring it is not
the end of it: the organ then pins the exit to one address and geolocates it
before stamping anything, because targeting is best-effort. See
[81-COMPETITIVE-INTEL.md](81-COMPETITIVE-INTEL.md#per-state-observation).

**Only Chrome is proxied.** A `curl` from the shell, `http_request`,
`web_search` and every API call egress the host directly — by design (see
*What stays direct*). So a curl to an IP echo will show the host's IP with the
proxy on and working; it proves nothing about the proxy. The agent is told
this in its `<runtime_state>` (`<network proxy="on" … scope="browser">`)
because on 2026-08-15 it wasn't, checked both ways, got two different answers,
and spent a checkpoint trying to reconcile them. To verify the exit, open an
IP echo in the agent's browser once — or run `elophanto doctor`.

Credentials sit directly in this section — same shape as every other API key in EloPhanto's config (`llm.providers.openrouter.api_key`, `polymarket.private_key`, etc.). `config.yaml` is gitignored by default; if your config sits on a multi-user box, lock it down with `chmod 600 config.yaml`.

## Verify the route

`elophanto doctor` exercises the proxy on every run and prints the apparent egress IP + ASN:

```
[!] proxy             egress 73.x.x.x (AS7922 Comcast Cable, US) via socks5://proxy.iproyal.com:12321
```

- **`ok`** — proxy reachable, real GET went through, IP printed matches expectation. ✓
- **`warn`** — proxy reachable but requires auth and we couldn't unlock the vault from doctor (proxy will work once the agent starts with the vault unlocked).
- **`fail`** — proxy host/port unreachable. Check provider dashboard, firewall, that the endpoint is in their allowlist for your account.
- **`skip`** — `enabled: false`, agent runs direct.

If `enabled: true` but the doctor row is `fail`, the agent will refuse to launch the browser cleanly. Fix the proxy or set `enabled: false` to run direct.

## Per-provider setup

### IPRoyal (recommended for cost / reliability)

1. Sign up at [iproyal.com](https://iproyal.com).
2. **Residential Proxies → Pay As You Go** (~$1.75 / GB, $5 minimum top-up).
3. **Recommended for our use case: ISP Dedicated** ($2.04/proxy/30 days, unlimited bandwidth, static IP). Cheaper at our usage pattern (~50 MB/day) than residential's $1.75/GB pay-as-you-go. Pick "United States, any city" unless you have an account-persona reason to want a specific city.
4. Buy 1 proxy. Dashboard prints a row: host, port, username, password.
5. Config (paste the values from the dashboard directly):
   ```yaml
   proxy:
     enabled: true
     type: socks5            # IPRoyal ISP exposes both http and socks5; socks5 is fine for Chrome
     host: 203.0.113.10      # the IP/host they give you
     port: 12323
     username: "YOUR_PROXY_USERNAME"
     password: "YOUR_PROXY_PASSWORD"
   ```
6. `elophanto doctor` should now print the residential egress IP, e.g. *"egress 203.0.113.10 (AS11426 Charter Communications, US) via socks5://203.0.113.10:12323"*.

### Smartproxy (alternative, similar tier)

1. Sign up at [smartproxy.com](https://smartproxy.com).
2. **Residential → Pay-as-you-go** (~$3.50 / GB).
3. Use the **sticky session** endpoint format: `gate.smartproxy.com:7000` (sticky IP for 30 min).
4. Same config shape — `type: http`, host and port from the dashboard.

### NetNut (premium)

Use NetNut when sites are aggressively blocking IPRoyal / Smartproxy IPs (common for finance + dating + sneakers). Pricing starts at $50/mo for 5 GB, but their pool overlaps less with the publicly-flagged proxy lists.

### Mullvad / IVPN / generic datacenter VPN

❌ Don't. These are datacenter-VPN IPs — same anti-bot flag as the Hetzner public IP you're trying to escape. The whole point is residential.

## Bandwidth budget

The agent's typical day uses **~50 MB of browser traffic** (X feed scrolls, KOL replies, Polymarket UI screenshots, pump.fun chat). $5 of IPRoyal credit covers ~3 months at this rate.

If you're posting media-heavy threads or doing video-streaming via browser, bandwidth will spike — but those flows usually go through dedicated tools (`twitter_post` for media uploads, `pump_livestream` for ffmpeg direct upload), and those tools route differently. Most bandwidth-heavy stuff is API-direct, not browser.

## What goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `elophanto doctor` shows `fail` on `proxy` | Proxy host unreachable from your network | Check provider dashboard — common gotcha: residential proxies often allowlist by IP, so your VM's outbound IP must be added before they'll route. |
| Login still bouncing on X even with proxy enabled | Profile is fresh and Linux fingerprint is screaming "bot" even from residential IP | Import existing cookies from your Mac Chrome as a one-time onboarding (see [HOSTED-DESKTOP.md](proposals/HOSTED-DESKTOP.md) §5b). Once cookies are warm, X is much more lenient on subsequent IPs. |
| Proxy bill scaling fast | Apps inside the desktop are using the proxy (manual browsing, downloads) | The Chrome instance the agent drives is the only one that uses the proxy — but if you manually launch Chrome from the noVNC desktop and browse YouTube, you're using your proxy bandwidth. Either be careful, or run a second Chrome profile manually with `--no-proxy-server`. |
| Latency feels worse with proxy on | Expected — every page load now adds 100-300ms for the residential hop | Acceptable for agent automation. If you're using the noVNC desktop manually for non-automated browsing and the lag is annoying, launch a second Chrome instance with `--no-proxy-server` for personal use. |
| Shell `curl ifconfig.me` shows the host IP with the proxy on | Expected — only Chrome routes; shell, `http_request`, `web_search` and API calls are direct | Verify with the agent's browser or `elophanto doctor`, not curl. |
| Rotating residential IP changes every request; logins get flagged | Residential pay-as-you-go rotates per request unless a session is pinned | IPRoyal: append `_session-<8 chars>_lifetime-30m` (or `1h`, `24h`) to the password. |
| `watch_observe geo_state=NV` refuses with "No network exit for geo_state" | Nothing declares a Nevada exit | Set `proxy.state: NV` if the single proxy is pinned there, or add a `proxy.pool` entry for NV. Don't just drop `geo_state` — that removes the state claim from the evidence. |
| `watch_observe` refuses with "Exit verification failed … landed in VA" | State targeting is best-effort; the provider routed you elsewhere | Retry — each attempt re-rolls the exit. Some states are reliable (Florida, Pennsylvania sampled clean), Texas missed ~half the time. |
| Sweepstakes-casino sites geo-block you *with* a working state proxy | That state may be one the operator does not serve — NV, WA, MI, ID, MT are common exclusions for sweeps | Observe from a state the brands actually serve. The block page itself is legitimate evidence of state availability. |
| IPRoyal account gone after a lapse | Unrenewed accounts are deleted, not paused — and the credentials in config die with them | Prepay more than one cycle or set a reminder for day 28; keep the account email somewhere you'll find it. |

## Threat model

**What the proxy hides:**
- Real source IP from the destination site (X, Polymarket UI, pump.fun frontend).
- Datacenter ASN signature.
- Correlation between agent's browser activity and operator's home IP.

**What it does NOT hide:**
- Browser fingerprint (canvas, WebGL, fonts, screen size, timezone, language) — fix these by matching server timezone to proxy egress region (`TZ=America/Los_Angeles` for a US residential proxy) and using real Chrome (not Chromium).
- WebRTC IP leak — Chrome's WebRTC can expose the real IP via STUN even behind a SOCKS proxy. Mitigated by Chrome's policy `--disable-features=WebRtcHideLocalIpsWithMdns` plus the `media.peerconnection.ice.proxy_only` setting. v1 doesn't auto-set this; manual flag if you need it.
- Account ownership — if `@your-agent` posts identifiable content (mints, wallets, your personal projects), the IP is irrelevant. Don't expect anonymity from a proxy alone.

**What the proxy provider can see:**
- Every URL the agent visits and every request body (TLS is end-to-end so they don't see the response body, but URLs / SNI / DNS are all visible to them).
- Treat them as a trusted MITM. Pick providers with a clear no-log policy and reasonable jurisdiction (IPRoyal: Lithuanian, Smartproxy: Lithuanian/US, NetNut: Israeli).

## Tests

`tests/test_core/test_proxy_config.py` (added 2026-05-10):
- `ProxyConfig` defaults disabled with empty host/port.
- `proxy_url()` builds `scheme://host:port` correctly for all 3 types.
- `proxy_url()` returns empty string when disabled or host/port missing.
- Bad `type` value falls back to `socks5` with a warning.
- `apply_to` defaults to `["browser"]` when unset.
- `bypass` parses string list correctly.

## Future work (Phase 2+)

| Item | Why | Effort |
|---|---|---|
| Per-tool-group routing | Route `web_search` / `web_extract` through proxy too without re-routing LLM calls | Small — `apply_to` already exists in config, just needs wiring at each tool's HTTP layer |
| Auto-rotation per task | IPRoyal sticky-IP rotates on a schedule; we expose this as `proxy.rotate_minutes` | Medium — depends on provider's session-token format |
| Circuit breaker fallback | If proxy is unreachable, fall back to direct egress (configurable safety vs continuity tradeoff) | Small — health check + flag flip |
| CamouFox integration | Firefox-based browser with anti-fingerprint built in. Use for the hardest cases (X DMs, sneaker sites, etc.) | Medium-large — separate browser bridge |
| Multi-proxy pool | Route different tasks through different providers (residential for X, mobile for pump.fun, datacenter for high-volume scraping) | Large — proxy.providers[] + per-task selection |
