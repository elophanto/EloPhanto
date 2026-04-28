---
name: pumpfun-livestream
description: Stream a local video file to Pump.fun's livestream UI for the agent's coin. Wraps Pump.fun's livestream API (create, host-token) and LiveKit's CLI publisher behind a Python orchestrator that signs auth with the agent's existing Solana wallet.
homepage: https://pump.fun
---

# Pump.fun Livestream

Stream a local video to **Pump.fun's livestream player** for an existing
Pump.fun coin. The skill is plug-and-play: you provide the coin mint
address and a local video path, the orchestrator handles auth, transcoding,
and publishing.

## Triggers

- "stream this video to pump.fun"
- "go live on pump"
- "pump.fun livestream"
- "broadcast on pump"
- "pumpfun stream", "live on pump.fun"

## How it works (architecture)

```
agent's Solana wallet ─sign─► /auth/login ─JWT─► all subsequent calls
                                              │
                                              ▼
   /livestreams/create-livestream (mint) ──► stream record
                                              │
                                              ▼
   /livestreams/livekit/token/host (mint, creator) ──► LiveKit JWT
                                              │
                                              ▼
   ffmpeg(local.mp4 → raw.h264) ──► lk room join --publish ──► LiveKit room
                                                                   │
                                                                   ▼
                                                        pump.fun live page
```

Pump.fun does not run their own video stack — they're a thin wrapper
around **LiveKit Cloud**. The skill does NOT mint a coin, trade, or
move SOL; it only operates on a coin the agent already owns.

## Prerequisites

### 1. The agent's coin mint

The agent's pump.fun coin mint address must be stored in the vault as
`pumpfun_coin_mint`. EloPhanto's existing pump.fun coin:

```bash
elophanto vault set pumpfun_coin_mint BwUgJBQffm4HM49W7nsMphStJm4DbA5stuo4w7iwpump
```

### 2. Where to drop videos

The agent's workspace has a dedicated folder for streamable videos:

```
<agent.workspace>/livestream_videos/
```

For EloPhanto: `/Users/0xroyce/agents/elophanto/livestream_videos/`

Drop any `.mp4`, `.mov`, `.webm`, etc. into that folder, then call the
tool with just the **filename** — no need to type the full path:

```json
{"action": "start", "video": "elephant-trailer.mp4"}
// → resolves to /Users/0xroyce/agents/elophanto/livestream_videos/elephant-trailer.mp4
```

Absolute paths still work and bypass the lookup:

```json
{"action": "start", "video": "/Users/0xroyce/Desktop/clip.mp4"}
```

### 3. System binaries

Two CLI binaries must be on PATH. Verify with:

```bash
which ffmpeg && ffmpeg -version | head -1
which lk     && lk --version
```

Install if missing:

| OS | ffmpeg | lk (LiveKit CLI) |
|---|---|---|
| macOS | `brew install ffmpeg` | `brew install livekit-cli` |
| Linux | `apt-get install ffmpeg` | Download from https://github.com/livekit/livekit-cli/releases (pick the right `lk_linux_*` binary, `chmod +x`, move to `/usr/local/bin/lk`) |

### 4. Solana wallet (already in the vault)

The skill reads the agent's existing keypair from `solana_wallet_private_key`
(set automatically when the wallet was created). No extra setup.

### 4. Vault password

Both auth and orchestrator scripts need `VAULT_PASSWORD` in the
environment to decrypt the wallet. The agent's running session already
has it; pass it through when invoking the script via `shell_execute`.

## Workflow

### From chat (preferred — uses the `pump_livestream` native tool)

The agent calls a single tool with one of these actions:

```json
{"action": "address"}
// → {wallet: "..."} — show which wallet would sign auth

{"action": "login"}
// → forces a fresh JWT exchange (debugging only — auth happens
// automatically on every other call)

{"action": "start", "video": "/abs/path/to/video.mp4"}
// → uses pumpfun_coin_mint from vault. Returns
//   {status: "started", pid, started_at, log_file, ...}

{"action": "start", "mint": "BwUg...pump", "video": "...", "fps": 24}
// → explicit mint and frame rate

{"action": "start", "video": "trailer.mp4", "loop": true}
// → resolves to <workspace>/livestream_videos/trailer.mp4 and
//   restarts the publisher every time the video ends. Stop with
//   {"action": "stop"}. Optional "max_iterations": N caps the loop.

{"action": "status"}
// → {status: "running" | "exited" | "not_running", ...}

{"action": "stop"}
// → SIGTERMs the publisher, removes transcoded .h264, clears state
```

The tool reads vault keys directly (no env var roundtrip) and runs in
the agent's running Python process. The actual `lk` publisher is
spawned as a detached subprocess so the chat returns immediately;
poll `status` to track the stream.

### From shell (debugging — needs VAULT_PASSWORD)

```bash
cd /path/to/EloPhanto
VAULT_PASSWORD=$VAULT_PASSWORD python skills/pumpfun-livestream/scripts/pump_livestream.py \
  start \
  $(elophanto vault get pumpfun_coin_mint) \
  /path/to/video.mp4
```

This will:

1. Sign a login message with the agent's wallet, exchange it for a
   pump.fun JWT (cached in the vault as `pumpfun_jwt`).
2. POST `/livestreams/create-livestream` with the mint (idempotent —
   409 "already exists" is silently tolerated).
3. GET `/livestreams/livekit/token/host` for a LiveKit JWT.
4. ffmpeg-transcode the input to raw H.264 (`video.h264` next to it).
5. Spawn `lk room join --publish video.h264 --exit-after-publish` as a
   detached subprocess.
6. Persist process state to `~/.elophanto/livestream-state/<mint>.json`
   so the agent can `status`/`stop` later.

The script returns immediately with `{status: "started", pid, ...}`.
The actual stream runs in the background until the video ends.

### Status check

```bash
python skills/pumpfun-livestream/scripts/pump_livestream.py status <mint>
```

Returns one of:

- `running` — publisher subprocess alive, stream is live
- `exited` — process died (check `log_file` field for ffmpeg/lk output)
- `not_running` — no record at all

### Stop a stream

```bash
python skills/pumpfun-livestream/scripts/pump_livestream.py stop <mint>
```

SIGTERMs the publisher (with a SIGKILL fallback after 3s), removes the
transcoded `.h264` (unless `--keep-h264` was set on start), and clears
state.

### Lower-level commands

For debugging or partial flows:

```bash
# Just check or refresh the cached pump.fun JWT
python skills/pumpfun-livestream/scripts/pump_auth.py token

# Force a fresh login
python skills/pumpfun-livestream/scripts/pump_auth.py login

# Just register the stream record (no publishing)
python skills/pumpfun-livestream/scripts/pump_livestream.py create <mint>

# Just transcode (no streaming)
python skills/pumpfun-livestream/scripts/pump_livestream.py transcode \
  in.mp4 out.h264

# Just fetch a fresh host LiveKit token
python skills/pumpfun-livestream/scripts/pump_livestream.py token <mint>
```

## Tuning

| Concern | Knob |
|---|---|
| Frame rate | `--fps 30` (default 30; lower = smaller files, fewer dropped frames) |
| LiveKit cluster | `--livekit-url wss://...` or `LIVEKIT_URL` env. Defaults to `wss://pump-prod-tg2x9b6r.livekit.cloud`. Override only if you've inspected pump.fun's frontend and confirmed a different cluster URL. |
| Keep transcoded file | `--keep-h264` — useful for re-publishing without re-encoding |
| Skip create | `--skip-create` — when the stream record already exists and you just want to publish again |

## What's intentionally NOT included

- **Audio.** The orchestrator strips audio (`-an` in ffmpeg). Audio
  publishing requires a second LiveKit track and the codec must be
  Opus (`.ogg`). Easy to add later: re-run ffmpeg to produce
  `video.opus`, pass both files to `lk room join --publish` (it
  accepts repeated `--publish` flags).
- **Live chat ingest.** Pump.fun's chat is a separate API surface
  (likely a websocket on the same `frontend-api-v3.pump.fun` host). Not
  part of v1 — see follow-up notes below.
- **Auto-restart on disconnect.** If the LiveKit publisher dies
  mid-video, `status` will show `exited` and the agent must decide
  whether to restart. No supervisor loop.
- **Multi-coin / multi-stream concurrency.** State is keyed by mint, so
  in theory two different mints can stream concurrently. Same mint
  twice = the second `start` returns `{status: "already_running"}`.

## Adding chat (next step)

Pump.fun's chat almost certainly rides on the same LiveKit room as a
"data channel" or text track (LiveKit supports both video, audio, and
arbitrary data messages). Two implementation paths:

1. **LiveKit data channel.** When connected as host via `lk`, send chat
   as a LiveKit data message. Requires a small Python client using
   `livekit-server-sdk-python` (or the LiveKit Realtime SDK), since
   `lk` doesn't expose a "send chat" CLI flag.
2. **Pump.fun chat REST/WS endpoint.** Inspect pump.fun's frontend to
   see if there's a `/livestreams/<mint>/chat` POST endpoint or a
   websocket. If so, post chat over that with the JWT we already have.

Either way, the auth (`pump_auth.py`) is reusable. Add a
`chat <mint> <message>` subcommand to `pump_livestream.py` once the
endpoint is confirmed.

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `VAULT_PASSWORD env var required` | Script invoked without the agent's vault password in env | Pass `VAULT_PASSWORD=$VAULT_PASSWORD` when calling via `shell_execute` |
| `Pump.fun login failed (401)` | Auth message format is rejected | Inspect pump.fun's web frontend network tab during a real login; tweak `_build_message()` in `pump_auth.py` to match |
| `'ffmpeg' not found on PATH` | Missing system binary | See Prerequisites table above |
| `'lk' not found on PATH` | Missing system binary | See Prerequisites table above |
| `LiveKit token endpoint returned no token` | Wrong JWT or stream record not yet created for that mint | Run `pump_auth.py login` first; then `pump_livestream.py create <mint>` |
| `start` succeeds but pump.fun shows no stream | Default LiveKit URL doesn't match pump.fun's actual cluster | Inspect pump.fun's network tab during a manual stream; pass real URL via `--livekit-url` |
| `exited` status with empty video on pump.fun | ffmpeg ran but the codec/container wasn't accepted by LiveKit | Check `log_file` from `status` output; usually a codec issue |

## Source layout

```
skills/pumpfun-livestream/
├── SKILL.md            # this file — agent-facing playbook
└── scripts/
    ├── pump_auth.py    # wallet → JWT, cached in vault
    └── pump_livestream.py   # create / token / transcode / start / stop / status
```

Both scripts are pure-Python, depend only on `httpx`, `solders`,
`base58` (already pinned in EloPhanto), and the system `ffmpeg` + `lk`
binaries.
