# Pump.fun Livestream

Stream a local video file to **pump.fun's livestream player** for an
existing pump.fun coin, end-to-end from chat. Auth is signed by the
agent's Solana wallet; publishing goes through pump.fun's WHIP/RTMP
ingress on LiveKit Cloud via ffmpeg.

## Why

Pump.fun coins are more visible when they're streaming on the live
page. Manual setup needs OBS, RTMP keys, sign-in flows, and a session
kept open in a browser. EloPhanto's agent can do all of it from a
single chat message — drop a video, say "stream this on pump.fun, on
loop," and the publisher runs in the background.

## Architecture

```
agent's Solana wallet ─sign─► /auth/login (frontend-api-v3.pump.fun)
                                       │
                                       ▼ auth_token cookie (JWT)
                          /livestream/create   (livestream-api.pump.fun)
                                       │
                                       ▼
              /livestream/livekit/create-credentials
                                       │
                                       ▼
                  RTMP url + streamKey   ◄── (pump.fun gates RTMP;
                  OR WHIP url + streamKey      WHIP works for everyone)
                                       │
                                       ▼
                ffmpeg -re -stream_loop -1 -i <video>
                  (libx264 + opus/aac → flv/whip)
                                       │
                                       ▼
                       LiveKit Cloud → pump.fun /coin/<mint>
```

Two key choices:

- **Auth via the existing Solana wallet**, not a separate pump.fun
  account. The agent already self-custodies a Solana keypair in the
  vault (`solana_wallet_private_key`); we sign `Sign in to pump.fun:
  <ts>` with that and exchange the signature for a JWT cookie on
  `frontend-api-v3.pump.fun/auth/login`.
- **ffmpeg → WHIP/RTMP**, not the LiveKit CLI. The current `lk`
  binary (v2.x) requires `--api-key`/`--api-secret`, which pump.fun
  keeps server-side and never exposes to clients. ffmpeg's WHIP
  muxer (and RTMP) accepts the per-stream credentials pump.fun
  hands out, so we publish directly. ffmpeg's `-stream_loop -1`
  gives seamless looping for free — no Python supervisor needed.

## Where to drop videos

```
<agent.workspace>/livestream_videos/
```

For EloPhanto: `/Users/0xroyce/agents/elophanto/livestream_videos/`.
Drop any `.mp4`/`.mov`/`.webm` and call the tool with just the
filename — bare names are looked up under that folder. Absolute paths
still work and bypass the lookup.

## Native tool: `pump_livestream`

```json
{"action": "address"}
// → {wallet: "..."}     which Solana address signs auth

{"action": "login"}
// → {logged_in: true, token_preview: "eyJ..."}   forces a fresh JWT

{"action": "start", "video": "1.mp4"}
// → uses pumpfun_coin_mint from vault, single playthrough

{"action": "start", "video": "1.mp4", "loop": true}
// → restarts via ffmpeg's -stream_loop -1 until 'stop'

{"action": "start", "video": "1.mp4", "loop": true, "max_iterations": 5}
// → loop, capped at 5 playthroughs

{"action": "start", "mint": "BwUg...pump", "video": "...", "fps": 24}
// → explicit mint and frame rate

{"action": "status"}
// → {status: "running" | "exited" | "not_running", pid, ...}

{"action": "stop"}
// → SIGTERMs the publisher, clears state
```

The tool reads vault keys directly (no env-var roundtrip) and runs in
the agent's process. The actual ffmpeg publisher is spawned as a
detached subprocess (`start_new_session=True`) so chat returns
immediately; poll `status` to track the stream.

## Vault keys

| Key | Purpose | Set by |
|---|---|---|
| `solana_wallet_private_key` | Signs `/auth/login` | Agent on first wallet auto-create |
| `pumpfun_coin_mint` | Default mint when none passed | `elophanto vault set pumpfun_coin_mint <mint>` |
| `pumpfun_jwt` | Cached pump.fun JWT (cookie value) | `pump_livestream` on first login |
| `pumpfun_jwt_expires_at` | UNIX seconds | Same |

## Prerequisites

- `ffmpeg` on PATH (`brew install ffmpeg` / `apt-get install ffmpeg`).
  The orchestrator hard-fails fast with a clear message if missing.
- The agent's pump.fun coin mint stored in the vault as
  `pumpfun_coin_mint`. Without it, the tool requires `mint` to be
  passed explicitly.

The legacy `lk` (LiveKit CLI) binary is **not** required — earlier
versions of this skill needed it; the current implementation only
shells out to ffmpeg.

## RTMP vs WHIP

Pump.fun's `livestream/livekit/create-credentials` accepts a numeric
protocol enum: `0 = RTMP`, `1 = WHIP`. Both return a LiveKit Cloud
ingest URL + a stream key; the orchestrator tries RTMP first and
falls back to WHIP if pump.fun returns the placeholder
`{"url": "error: please contact support", ...}` (RTMP is gated for
non-OBS-allowlisted accounts; WHIP works for everyone).

Differences in the ffmpeg invocation:

| | RTMP | WHIP |
|---|---|---|
| Audio codec | AAC | Opus (required) |
| Auth | streamKey appended to URL path | `-authorization <streamKey>` Bearer header |
| Container | `flv` | `whip` |
| URL shape | `rtmps://.../x/<key>` | `https://.../w` |

## Looping

Set `loop: true` and ffmpeg handles restarts internally via
`-stream_loop -1`. No Python supervisor, no gap between cycles, no
re-handshake — the same WHIP/RTMP session stays open.

`max_iterations` (default 0 = infinite) maps to `-stream_loop N-1`.

`stop` SIGTERMs the ffmpeg subprocess; ffmpeg cleanly disconnects
from LiveKit, which returns the stream to "ended" on pump.fun.

## Live chat (`pump_chat`)

Pump.fun's livestream chat panel runs on a separate Socket.IO server
at `wss://livechat.pump.fun` (path `/socket.io/`). Auth uses the same
JWT cookie issued by `/auth/login` — passed in both `Cookie:
auth_token=…` and the Socket.IO `auth` payload as `token`.

```json
{"action": "say", "text": "gm — agent live, supply locked"}
// → posts under the agent's wallet. Returns {posted, id, mint, wallet, text}

{"action": "say", "text": "yes, AI-only — receipts: <link>", "reply_to_id": "<msg-uuid>"}
// → threaded reply

{"action": "history", "limit": 50}
// → returns id, username, userAddress, message, timestamp, isCreator
```

Pairs with `pump_livestream` (same vault, same wallet). Use the
agent's heartbeat/scheduled-task system to drip messages — don't loop
in tight intervals; pump.fun rate-limits per wallet.

Implementation in [tools/pumpfun/chat_client.py](../tools/pumpfun/chat_client.py)
(thin async Socket.IO wrapper with `LivechatClient` async-context
manager) and [tools/pumpfun/chat_tool.py](../tools/pumpfun/chat_tool.py)
(native tool). Discovered events from the frontend JS bundle:
`joinRoom`, `leaveRoom`, `sendMessage`, `getMessageHistory`,
`pinMessage`, `unpinMessage`, `addReaction`, `removeReaction`,
`viewerHeartbeat`. The tool exposes `say` and `history`; the rest are
available on `LivechatClient` for direct callers.

## What's intentionally NOT included

- **Audio mixing.** The publisher uses whatever audio is in the source
  file. No background music overlay, no TTS narration. Use a
  pre-mixed video if you need that.
- **Chat listen-loop / auto-respond.** `pump_chat` opens a fresh
  Socket.IO connection per call. For continuous "answer viewer
  questions" behaviour, schedule `history` checks via heartbeat and
  let the agent decide what to reply to.
- **Auto-restart on disconnect.** If ffmpeg dies (network blip,
  LiveKit kicks us), `status` reports `exited`. No supervisor loop.
- **Multi-stream concurrency.** Per-mint state file means two
  different mints could stream concurrently in theory; same mint
  twice returns `{status: "already_running"}`.

## Source layout

```
tools/pumpfun/
├── __init__.py
├── orchestrator.py     # LivestreamOrchestrator: auth, create, ffmpeg spawn
├── livestream_tool.py  # Native tool: pump_livestream
└── _loop_runner.py     # Legacy supervisor (kept for back-compat;
                        # no longer invoked by start_stream)

skills/pumpfun-livestream/
├── SKILL.md
└── scripts/
    ├── pump_auth.py        # CLI: login / token / whoami
    └── pump_livestream.py  # CLI: create / token / transcode / start / stop / status
```

The CLI scripts under `skills/pumpfun-livestream/scripts/` thin-wrap
the orchestrator for shell-based debugging (require
`VAULT_PASSWORD` in env).

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `Pump.fun /auth/login failed (500)` | Body field names drifted | Inspect pump.fun's frontend network tab; tweak `_build_login_message` / login body |
| `Login succeeded but no token` | Cookie name changed | Already handled — the orchestrator extracts JWT-shaped cookies; if pump.fun uses a new name, add it to the cookie scan list |
| `create-credentials returned no usable creds` | RTMP gated AND WHIP unreachable | Check pump.fun's UI for RTMP enablement under "Stream credentials" |
| `'ffmpeg' not found on PATH` | Missing system binary | `brew install ffmpeg` |
| `start` succeeds but pump.fun shows nothing | Stream record created but ffmpeg failed at media transport (often IPv6 ICE candidate) | Check `~/.elophanto/livestream-state/<mint[:16]>.log` for ffmpeg output |
