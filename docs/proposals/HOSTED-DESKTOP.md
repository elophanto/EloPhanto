# Proposal: Hosted EloPhanto desktop on Hetzner

**Status:** Draft — proposed, not approved. Recipe rewritten 2026-05-10 with corrected Hetzner SKU specs (CX22 is 2 vCPU/4 GB, not 4/8 as 2024 rename made unclear) and click-by-click provisioning.
**Author:** EloPhanto + Claude (Opus 4.7)
**Date:** 2026-05-07 (initial), 2026-05-10 (recipe rewrite)
**Related:** [docs/08-BROWSER.md](../08-BROWSER.md), [docs/proposals/REMOTE-BROWSER.md](REMOTE-BROWSER.md)

---

## Important: "headless" is overloaded

This proposal uses two different things people often conflate:

- **Headless OS image** — what Hetzner ships. No GUI on the Linux server, only SSH/console. Standard for every cloud VM (AWS, GCP, DigitalOcean, OVH — same). **We accept this** and install a real desktop on top in §4.
- **Headless Chrome (`--headless`)** — Chrome running with no UI surface, no real DOM event loop, no popups, no 2FA UI. **We never use this.** The Chrome inside the container is full GUI Chrome (`headless: false` in config.yaml), running inside the XFCE desktop we install. KasmVNC streams that desktop to your browser so you can see and drive it from anywhere.

---

## Problem

EloPhanto today runs on the operator's own machine, driving the operator's own Chrome profile. Three real friction points:

1. **The agent steals your computer.** When EloPhanto is running browser-driven X automation, you can't use Chrome yourself without colliding with the agent. The browser-singleton constraint is real (one Chrome process per `--user-data-dir`).
2. **Your laptop has to be on.** The autonomous mind, scheduler, and any in-flight task all stop when you close the lid. The daemon mode helps on the same machine, but if the laptop's elsewhere, nothing runs.
3. **You can't watch from anywhere.** SSH gives you logs and a CLI. It doesn't show you what the agent's actually *seeing* in Chrome — the iframe content, the X composer, the captcha challenge it's puzzling over. Eyeballing the live screen is irreplaceable when something goes wrong.

The fix shape: **a Linux box that runs EloPhanto + Chrome 24/7, with the desktop streamable to any browser tab**. Not vapor — every component below is off-the-shelf and operator-runnable in half a day.

## Goals

- A Linux server that hosts EloPhanto and a fully-featured Chrome (logged-in profiles, cookies, sessions persist).
- The desktop is streamable from any browser — no client app required for the operator.
- Operator can step in, type, click, drive Chrome themselves at any moment to fix something the agent got stuck on.
- Cheap enough to run permanently (~€5/month).
- Self-hosted; no third-party SaaS in the loop unless the operator opts in.
- Near-zero EloPhanto code changes — uses the existing `browser.mode: profile` path against an in-container Chrome profile.

## Non-goals

- **Replacing the local-Chrome path.** Operators who prefer running on their own machine keep doing that. This is opt-in.
- **GPU compute.** No model inference happens on this box. The agent still calls cloud LLMs via OpenRouter / Codex / etc.
- **High-FPS / video-class streaming.** Webtop's noVNC-over-WebSocket gives you ~15 FPS at 1080p, which is plenty for watching an agent type. If you need 60 FPS, see "Future work" — different stack.
- **Multi-tenant.** One operator, one EloPhanto instance per box. Sharing-watch-access is supported (multi-user web login); running multiple agents on the same box is out of scope.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Hetzner CPX32 (~€6.5/mo, 4 vCPU, 8GB RAM, 80GB SSD, Ubuntu 24.04) │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Docker host                                               │  │
│  │  ┌──────────────────────────────────────────────────────┐  │  │
│  │  │  linuxserver/webtop container (Ubuntu XFCE)         │  │  │
│  │  │   ├── Chrome (real browser, persistent profile)     │  │  │
│  │  │   ├── EloPhanto (cloned + venv + running)           │  │  │
│  │  │   ├── Node.js bridge (browser CDP)                  │  │  │
│  │  │   └── XFCE desktop                                  │  │  │
│  │  │                                                      │  │  │
│  │  │   Volumes:                                           │  │  │
│  │  │     /config        ← profile, agent home            │  │  │
│  │  │     /workspace     ← EloPhanto repo + data          │  │  │
│  │  └──────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────┘  │
│                          ↑                                        │
│                    Tailscale (or Caddy + auth)                    │
└──────────────────────────────────────────────────────────────────┘
                           ↑
            ┌──────────────┴────────────────┐
            │                                │
        Browser tab                    SSH (admin)
        (https://...3001)              (operator)
        watch + drive                  configure
```

**Key choice:** EloPhanto and Chrome live in the **same container**, sharing one display. EloPhanto drives Chrome via the existing CDP bridge over `localhost`. No `mode: remote` needed — this is the existing `mode: profile` path, just on a server. The streaming layer (Webtop) is orthogonal to the agent.

## Which Hetzner server to pick

Hetzner's lineup as of 2026 (Cloud → Server creation page). Pick by RAM first — Chrome alone eats 2–3 GB with a handful of tabs, plus XFCE (~500 MB), EloPhanto + Node bridge (~1 GB), and headroom for the OS. **8 GB RAM is the floor**; 4 GB will swap-thrash under any real browser load.

| SKU | vCPU | RAM | Disk | Price/mo (EU / US) | Verdict for this box |
|---|---|---|---|---|---|
| CPX22 | 2 AMD shared | 4 GB | 80 GB | €4.85 / €9.67 | ❌ Too small — Chrome OOMs |
| **CPX32** | **4 AMD shared** | **8 GB** | **160 GB** | **€8.49 / €16.93** | ✅ **Recommended default** — fits the workload cleanly with disk headroom |
| CPX42 | 8 AMD shared | 16 GB | 320 GB | €15.42 / €30.84 | Overkill unless 20+ tabs / heavy concurrent automation |
| CCX13 | 2 AMD **dedicated** | 8 GB | 80 GB | €14.86 / ~€29 | ✅✅ No noisy-neighbor lag; switch up to this if streaming feels janky |

EU prices apply to Helsinki / Falkenstein / Nuremberg. US prices (Ashburn / Hillsboro) and Singapore are roughly 2× higher because of co-lo costs. If your latency tolerance is loose (you're watching the agent type, not gaming), pick an EU location — same SKU, half the price.

Recommendation: **start with CPX32** in your closest location. If browser streaming feels laggy under load, upgrade to CCX13 — Hetzner lets you resize in-place with one click (a few minutes of downtime). Older docs may reference the Intel `CX32` SKU; Hetzner has been consolidating onto the AMD `CPX*` line, so CPX32 is the current equivalent.

| Other costs | Cost | Notes |
|---|---|---|
| Bandwidth | included | 20 TB/month with the box |
| Tailscale Free | $0 | Up to 100 devices, 3 users — for private access |
| Domain + Caddy TLS | $0–10/year | Optional; Tailscale alone works for personal use |
| Hetzner Storage Box (backups) | €3.20/mo for 1 TB | Optional but recommended for the agent's vault + knowledge |
| **Total realistic monthly** | **~€7–10/mo** | Less than a Spotify Family plan |

## Recipe

### Pre-flight (do these once, from your laptop)

1. **Hetzner Cloud account.** Sign up at [console.hetzner.cloud](https://console.hetzner.cloud) if you don't have one. Add a payment method. Verification takes ~10 minutes if it's a fresh account.
2. **SSH keypair.** If you don't already have one: `ssh-keygen -t ed25519 -C "elophanto-host"` on your laptop. Copy the public key (`~/.ssh/id_ed25519.pub`); you'll paste it into Hetzner's UI in a moment.
3. **Tailscale account.** Sign up at [tailscale.com](https://tailscale.com) (free, GitHub/Google login works). This gives you private access to the box without exposing ports to the public internet.

### 1. Provision the box (click-by-click in Hetzner Cloud)

In [console.hetzner.cloud](https://console.hetzner.cloud):

1. **Project** → create a new project, call it `elophanto`. Click in.
2. **Servers** → **Add Server**.
3. **Location** — pick whatever's closest to you. Within Europe: Helsinki, Falkenstein, Nuremberg. USA: Ashburn (VA), Hillsboro (OR). Asia: Singapore. Latency matters a little for the streaming UX but not much.
4. **Image** — **OS Images** tab → **Ubuntu** → select **24.04** from the dropdown. (This is the screenshot the user already had open; that selection is correct.)
5. **Type** — **Shared vCPU** category → **AMD** → click **CPX32** (4 vCPU, 8 GB RAM, 160 GB SSD). Price depends on location: ~€8.49/mo in EU, ~€16.93/mo in US. Don't pick CPX22 (4 GB is too small for Chrome + XFCE + EloPhanto) and don't pick the ARM `CAX*` line (Chrome + Docker images are easier on x86).
6. **Networking** — leave defaults (IPv4 + IPv6 enabled). No need to attach a private network unless you'll run multiple boxes.
7. **SSH Keys** — click **Add SSH key** → paste your `id_ed25519.pub` contents → name it `laptop`. Tick the checkbox next to it.
8. **Volumes / Firewalls / Backups** — skip all three for now. (You can enable Hetzner Backups for +20% if you want point-in-time snapshots — recommended for a real production box; optional for a personal one.)
9. **Cloud Config / Placement / Labels** — skip.
10. **Name** — `elophanto-host` (or whatever).
11. **Create & Buy now**.

Hetzner provisions in ~30 seconds. The **Overview** page shows you the box's public IPv4 — copy it.

**Verify (from your laptop):**

```bash
ssh root@<your-server-ip>      # should drop you straight in, no password
```

If you get `Permission denied`, the SSH key didn't attach — re-paste in Hetzner UI → **Security** → **SSH Keys**, then **Rebuild** the server (or just delete + recreate; it's faster).

### 2. Harden the box and install Docker

Still SSH'd in as root:

```bash
# Patch everything
apt update && apt upgrade -y

# Install Docker, Compose plugin, and a few utilities we'll need
apt install -y docker.io docker-compose-plugin curl git ufw fail2ban

# Start Docker on boot
systemctl enable --now docker

# Non-root user for the agent (avoids the container running as host-root)
useradd -m -s /bin/bash -G docker eph
mkdir -p /home/eph/.ssh
cp /root/.ssh/authorized_keys /home/eph/.ssh/
chown -R eph:eph /home/eph/.ssh
chmod 700 /home/eph/.ssh && chmod 600 /home/eph/.ssh/authorized_keys

# Basic firewall — only SSH and Tailscale by default
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp                        # SSH
ufw allow in on tailscale0              # all Tailscale traffic
ufw --force enable

# Fail2ban catches SSH brute-force attempts
systemctl enable --now fail2ban
```

**Verify:**

```bash
docker run --rm hello-world             # should pull and print "Hello from Docker!"
ufw status                              # should show "Status: active"
ssh eph@<server-ip>                     # from your laptop, should also work
```

### 3. Install Tailscale (private access — no public port exposure)

Skipping this means exposing the streaming port to the public internet, which means rotating credentials properly. Tailscale gives you a private tailnet for free; the Hetzner box becomes another node on your tailnet, reachable only from your other devices.

Still as `root` on the Hetzner box:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --ssh --hostname=elophanto-host
```

The command prints a URL like `https://login.tailscale.com/a/abc123...`. Open it on your laptop, log in, **Authorize**. The Hetzner box now appears in your tailnet at a `100.x.y.z` address.

**Verify:**

```bash
tailscale ip -4                         # prints the box's 100.x.y.z address — save this
```

From your laptop (with Tailscale running):

```bash
ping 100.x.y.z                          # should answer instantly
ssh eph@100.x.y.z                       # same SSH but over Tailscale instead of public IP
```

From now on, use `100.x.y.z` everywhere — public IP becomes ssh-only fallback.

### 4. Drop in the Docker Compose stack (XFCE desktop + Chrome, streamable from any browser)

This is where the headless OS gets its desktop. We use **[linuxserver/webtop](https://docs.linuxserver.io/images/docker-webtop/)** — a maintained Docker image bundling Ubuntu + XFCE + a full Chromium + KasmVNC server. KasmVNC turns the XFCE screen into a WebSocket stream you open in any normal browser. **The Chrome inside the container is full GUI Chrome, not `--headless`** — it has a real display server (X11 + Xvfb under the hood), real DOM event loop, real popups, real 2FA UI. You see and interact with it exactly the same way you would on your laptop.

Switch to the `eph` user (recommended) or stay as root and `su - eph`:

```bash
su - eph
cd ~
mkdir -p config workspace
nano docker-compose.yml         # paste the YAML below
```

`/home/eph/docker-compose.yml`:

```yaml
services:
  desktop:
    image: lscr.io/linuxserver/webtop:ubuntu-xfce
    container_name: elophanto-desktop
    restart: unless-stopped
    security_opt:
      - seccomp:unconfined         # Required by Chrome inside the container
    environment:
      - PUID=1000                  # eph user inside the container
      - PGID=1000
      - TZ=Europe/Berlin           # change to your timezone
      - SUBFOLDER=/                # Web UI mounted at root of port 3001
      - TITLE=EloPhanto
    volumes:
      - ./config:/config           # Persistent home (Chrome profile + EloPhanto)
      - ./workspace:/workspace     # EloPhanto repo + agent data + logs
    ports:
      - 127.0.0.1:3001:3001        # Bind to LOCALHOST only — Tailscale forwards in
    shm_size: "2gb"                # Chrome wants real shared memory
    devices:
      - /dev/dri:/dev/dri          # GPU pass-through if available (optional)
```

**Why each line:**
- `image: ...webtop:ubuntu-xfce` — Ubuntu base, XFCE desktop, Chromium pre-installed, KasmVNC pre-configured. No manual XFCE/VNC install.
- `seccomp:unconfined` — Chrome's renderer sandbox needs syscalls Docker's default seccomp profile blocks. Standard Webtop requirement, well-known, documented.
- `PUID=1000 / PGID=1000` — maps the container processes to your host `eph` user so file ownership is clean on `./config` and `./workspace`.
- `127.0.0.1:3001:3001` — **intentional binding to localhost only**. The only ways in are: (a) Tailscale forwarding (`100.x.y.z:3001` works because Tailscale's `tailscale0` interface is included via `ufw allow in on tailscale0`), or (b) SSH local-forwarding (`ssh -L 3001:localhost:3001 eph@100.x.y.z`). Public exposure is opt-in via the Caddy step.
- `shm_size: "2gb"` — Chrome's renderer needs real shared memory. Default 64 MB causes mysterious tab crashes.
- `/dev/dri:/dev/dri` — GPU pass-through. Hetzner shared-CPU VMs don't have GPUs, so this device usually doesn't exist (Docker will warn and skip). Harmless either way; leave the line in.

Start it:

```bash
docker compose up -d
docker compose logs -f desktop          # tail the first boot — Ctrl-C when you see "ready"
```

First boot pulls ~2 GB of image and initializes XFCE — give it 60–90 seconds.

**Verify:** open `https://100.x.y.z:3001` (your tailnet IP, port 3001) from any browser on your laptop. You should see the **XFCE desktop, with Chrome icon on the taskbar**, rendered in your browser tab. Self-signed cert on first visit; accept the warning. Right-click the desktop → Open Terminal → confirm you're inside the container with `whoami` (should be `abc`, Webtop's internal user mapped to host's uid 1000).

### 5. Log into accounts in the in-container Chrome (do this BEFORE installing EloPhanto)

You want EloPhanto to inherit a Chrome profile that's already logged into the services it'll automate (X, Gmail, Polymarket, pump.fun, etc.). Easier to do this manually first than to make the agent do it.

In the browser tab streaming the desktop:

1. Click the **Chrome** icon on the XFCE taskbar (or right-click desktop → Applications → Google Chrome).
2. Log into your accounts one by one: X, Gmail, GitHub, Polymarket, pump.fun, whatever else the agent needs.
3. **Solve any 2FA / passkey challenges yourself** while you're driving. The interactive desktop is exactly for this — the agent can't pass these alone, but you can, and the session cookies persist in `/config` after.
4. Close Chrome cleanly (File → Quit). EloPhanto needs to launch its own Chrome process against the same profile; if there's a stale Chrome running, the singleton lock blocks it.

Profile state is now persisted at `/config/.config/google-chrome/` inside the container (= `/home/eph/config/.config/google-chrome/` on the host).

### 6. Install EloPhanto inside the container

Open the terminal in the streaming desktop (right-click desktop → Open Terminal) — OR SSH directly into the container from your laptop. Both work; the terminal-in-desktop is friendlier if you're new to this.

```bash
cd /workspace
git clone https://github.com/elophanto/EloPhanto.git
cd EloPhanto
./setup.sh                        # installs Python deps via uv, builds the browser bridge
elophanto init                    # config wizard
```

The wizard will:
1. Ask for an OpenRouter API key (cheapest get-started path; you can add more providers later).
2. Detect the in-container Chrome profile at `/config/.config/google-chrome/`.
3. Write `config.yaml` with the right paths.

**The relevant `config.yaml` section should look like this** (the wizard fills this in, but verify):

```yaml
browser:
  enabled: true
  mode: profile                          # use existing profile, NOT --headless
  user_data_dir: /config/.config/google-chrome
  profile_directory: Default
  use_system_chrome: true
  cdp_port: 9222
  headless: false                        # explicitly false — full GUI Chrome
  profile_refresh_hours: 0               # don't auto-refresh: agent logins persist
```

`headless: false` is the line that matters most — full GUI Chrome, with the real DOM event loop, popups, file dialogs, extensions, 2FA inputs. KasmVNC streams the screen; Chrome itself never runs in `--headless` mode.

### 7. Run EloPhanto as a daemon

```bash
cd /workspace/EloPhanto
./start.sh --daemon                # Installs as systemd user service
elophanto daemon-status            # should show "running"
```

The daemon survives container restarts (the container itself survives reboots via `restart: unless-stopped` in compose). The agent starts the Node browser bridge, which launches Chrome against the profile you logged in to in §5. Watch in the browser tab — Chrome will pop open inside XFCE within ~5 seconds.

**Verify the full stack is alive:**

```bash
elophanto affect status            # current emotional state (PAD numbers + label)
elophanto schedule status          # cron schedules + concurrency report
elophanto doctor                   # full preflight (green/yellow/red)
tail -f logs/latest.log            # raw events
```

All of these work in the in-container terminal *or* over SSH. The desktop tab is for when you want to *see* the Chrome window — the agent's autonomous activity is fully introspectable from CLI too.

### 8. Optional: domain + Caddy + auto-TLS

If you want a real domain instead of `100.x.y.z`, drop a Caddy reverse proxy in front:

```yaml
services:
  caddy:
    image: caddy:2
    restart: unless-stopped
    ports:
      - 443:443
      - 80:80
    volumes:
      - ./caddy/Caddyfile:/etc/caddy/Caddyfile
      - ./caddy/data:/data
    # ... and add `desktop` to its network
```

`Caddyfile`:
```
agent.yourdomain.com {
    reverse_proxy desktop:3001
    basicauth {
        operator <bcrypt-hash>
    }
}
```

Caddy gets you a real Let's Encrypt cert and basic auth. Now `https://agent.yourdomain.com` works from anywhere without Tailscale. Tradeoff: you've made the box internet-reachable; rotate the basic auth password and consider adding fail2ban.

## EloPhanto config changes

**None required.** The existing `browser.mode: profile` path works directly against the in-container Chrome profile. The only thing changes is *where* the agent and Chrome live.

If you eventually want the agent to live elsewhere (your laptop) and only Chrome to live on the Hetzner box, that's the unrelated `mode: remote` proposal in [REMOTE-BROWSER.md](REMOTE-BROWSER.md). For this proposal, agent + Chrome are colocated.

## Operational notes

### Monitoring

```bash
docker compose logs -f desktop                   # Webtop + everything in container
ssh root@server "tail -f /var/log/syslog"        # Host-level
elophanto daemon-logs                            # EloPhanto daemon log
elophanto polymarket performance                 # Trading performance
```

For external monitoring, point [Uptime Kuma](https://uptime.kuma.pet) at port 3001 from another box, alerts on downtime.

### Backups

The only stateful directories are `~/config` (Chrome profile, XFCE prefs) and `~/workspace` (EloPhanto data, knowledge, ego, affect, vault). Both worth backing up. Cheapest path: weekly `tar` to Hetzner Storage Box (~€3/mo for 1TB) via cron.

```bash
# /etc/cron.weekly/elophanto-backup
0 3 * * 0 tar czf /tmp/eph-$(date +%F).tgz /home/eph/config /home/eph/workspace \
  && rclone copy /tmp/eph-*.tgz hetzner-storage:elophanto-backups/ \
  && find /tmp -name "eph-*.tgz" -mtime +1 -delete
```

### Updates

```bash
docker compose pull && docker compose up -d   # Webtop image
ssh into desktop:
  cd /workspace/EloPhanto && git pull && elophanto update
```

### Failure modes worth knowing

- **Chrome OOMs at peak load.** Symptom: tab crashes, EloPhanto's `browser_navigate` starts timing out. Fix: bump from CPX32 (8 GB) to CX42 (16 GB) or CCX13 (dedicated CPU + 8 GB), or limit Chrome's `--memory-pressure-threshold`. CPX32's 8 GB is plenty for most flows; sustained heavy multi-tab work might exceed it.
- **Webtop streaming lags during high CPU.** Lower the in-browser quality slider, or step up to a dedicated-vCPU instance (CCX13).
- **Tailscale device limit.** Free tier caps at 100 devices, 3 users. Plenty for personal use.
- **Hetzner suspended your account because your traffic spiked.** Rare but happens; usually a misbehaving scraper. Check `docker stats` and `iftop`.
- **The container's clock drifted.** Schedules fire late. `docker exec elophanto-desktop sudo apt install ntp -y` to fix once.

## Risks to flag

1. **The streaming desktop is now part of your attack surface.** Webtop runs as root inside the container by default; the user-mode `PUID/PGID` env vars bring it to non-root. Tailscale + bind-to-localhost is the right default; public exposure via Caddy + basic auth is fine but has the usual basic-auth caveats. Don't open port 3001 publicly without auth in front.
2. **Chrome profile sync between local and remote.** If you keep using Chrome locally too, your sessions diverge. Pick one home for each account, or use Chrome's built-in Google account sync. EloPhanto doesn't help with this.
3. **The agent now has its own keys somewhere you don't fully control.** Same risk as the local install — vault is encrypted, but a compromised host means a compromised vault. Tailscale auth + SSH key auth + non-root container user keeps the surface narrow. Don't reuse a passphrase from your laptop.
4. **Hetzner ToS on residential / personal use.** Hetzner is fine for any normal use; they care about scrapers running flat-out, mass-mail, and crypto miners. EloPhanto is none of those. They've been around 25 years and are German-strict but reasonable.

## Phasing

**Phase 1 — Webtop + Tailscale (this proposal).** ~3-4 hours of setup, €5/mo.

**Phase 2 — Caddy + domain + basic auth (optional).** ~30 minutes of setup, $10/year for domain. Useful if you want browser-only access from devices that don't have Tailscale.

**Phase 3 — Multi-region failover (very optional).** Two boxes, one active one warm-standby, periodic rsync of `/home/eph/{config,workspace}`. Only worth it if uptime becomes a real business need, not for personal use.

## Future work

- **Hardware-accelerated streaming (selkies-gstreamer / Sunshine + Moonlight).** Higher FPS, lower latency. Worth it if Webtop's quality starts feeling laggy. Requires GPU-bearing Hetzner SKU (their CCX line doesn't have GPUs; you'd need a different provider for that).
- **Mobile companion app.** PWA wrapping the streaming URL, push notifications for approvals. Maybe.
- **Per-task fresh Chrome profiles.** Spin a new XFCE session per task to truly isolate cookies — useful if you want one profile for X automation, another for shopping, etc. Webtop supports this with workspaces.

## What this is NOT

- A replacement for `mode: remote` in [REMOTE-BROWSER.md](REMOTE-BROWSER.md). That's the *agent-here, Chrome-there* split. This is *agent + Chrome together, you watching from elsewhere*. Different problem.
- A managed agent service. You operate the box. Hetzner runs the hardware; everything above the OS is yours.
- A hardened production setup. The defaults here are "operator on a tailnet runs the box for themselves." For commercial deployment add: WAF, intrusion detection, audit logging, DR plan, on-call rotation. Out of scope for this proposal.

## Decision

**Approve if:**
- You want the agent running 24/7 without your laptop being on.
- You want to *see* what it's doing in Chrome from any device.
- You're comfortable with one half-day of one-time setup for permanent ~€5/mo hosting.
- The local-Chrome contamination problem (agent + you fighting for the browser) actually bothers you.

**Don't approve if:**
- Your laptop staying on isn't actually a problem.
- You don't trust yourself to keep the box updated.
- You'd rather pay for a managed service (Browser Use Cloud cloud browsers + EloPhanto local works fine for the browser-only piece).

## Bottom line

A Hetzner **CPX32** (€8.49/mo EU / €16.93 US, 4 AMD vCPU / 8 GB / 160 GB) + linuxserver/webtop Docker container + Tailscale gives you a 24/7 EloPhanto with a real Chrome you can watch and drive from any browser tab, in one half-day of setup. The Chrome inside the container is full GUI Chrome — not `--headless` — running inside an XFCE desktop streamed via KasmVNC, so 2FA, passkeys, popups, extensions, and the Chrome profile all work the same way they do on your laptop. EloPhanto needs zero code changes — its existing `browser.mode: profile` path drives the in-container Chrome over CDP exactly the way it drives your local Chrome today.

When you decide to do this, I can scaffold a one-shot `bin/provision-hetzner-desktop.sh` that runs the steps above against a fresh box.
