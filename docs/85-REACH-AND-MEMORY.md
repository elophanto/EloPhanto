# 85 — Reach, Memory, and Autonomy Guards

*OAuth + Google Workspace, three new channels, companion devices, voice, media,
standing preferences, loop detection, and agent packages.*

Status: shipped 2026-08-10. Companion to [84 — The Action Layer](84-ACTION-LAYER.md).

## User-service OAuth — `core/oauth.py`

Authorization code + PKCE against a loopback redirect, which is the shape Google
and Microsoft require for a native app and needs no client secret to be safe.

A user token differs from a pasted API key in ways the store has to handle:
it expires (often hourly, so refresh is transparent), the *refresh* token is the
real prize (so it never leaves the store — `access_token()` is the only
accessor), and consent is per-scope.

Stored encrypted in the vault when one is unlocked; a `0600` file otherwise,
with a warning, so a fresh install still works.

```
elophanto oauth login google
elophanto oauth list           # accounts, never tokens
elophanto oauth logout google
elophanto oauth scope --add-owned api.mygym.example
```

Well-known endpoints ship for `google`, `microsoft`, and `github` — the operator
supplies only a `client_id`.

### Google Workspace

`gmail` — `search` (Gmail query syntax), `read`, `send`, `reply`, `archive`,
`mark_read`, `labels`. Reads are SAFE; **send and reply are CRITICAL**, because
outbound mail is irreversible and goes out in the operator's name.

`gcal` — `list`, `create`, `update`, `delete`, `freebusy`, `calendars`. Delete
is CRITICAL, and so is creating an event *with attendees*: both mail everyone
invited, which is a social act as much as a data change. Updates use `PATCH` so
a partial edit cannot silently strip the guest list.

This finally replaces ICS-file-only calendar awareness with the real thing.

## Channels — reach

| Channel | Transport | Notes |
|---|---|---|
| Signal | `signal-cli` JSON-RPC over stdio | Linked device — **sends as the operator** |
| iMessage | `chat.db` polling + AppleScript | macOS only, needs Full Disk Access |
| WhatsApp | Meta Cloud API *or* a local bridge | Cloud is official; bridge is Baileys-style |

All three share one property worth stating: **an empty allowlist means closed,
not open.** Signal and iMessage send as the operator rather than as a bot, so an
open default would let anyone who can message them drive the agent.

WhatsApp cloud mode arrives by webhook at `POST /hooks/whatsapp`, which
authenticates Meta's way — `hub.verify_token` on the GET handshake, HMAC-SHA256
on POSTs — rather than through the generic bearer-token webhook path.

## Companion devices — `core/nodes.py`

A *node* is a device that lends the agent senses: a phone's camera and location,
a laptop's screen. It is **not** a chat channel — nodes answer capability
invocations, they do not hold conversations. The model stays on the gateway
where the tools, memory, and approval gates live, so adding a platform means
implementing a few handlers, not porting an agent.

Protocol: `NODE_REGISTER` → `NODE_INVOKE` → `NODE_RESULT`, correlated by
`request_id` with a timeout, over the existing WebSocket.

Two conservative rules:

- **Registration is not authorization.** A device advertises what it *can* do;
  whether the agent may invoke it is decided against the operator's allowlist.
  A device claiming `shell.run` does not thereby get one.
- **Sensitive capabilities are opt-in per node** (`camera.*`, `screen.*`,
  `mic.record`, `location.get`, `sms.send`, `shell.run`, `computer.act`) *and*
  escalate `node_invoke` to CRITICAL. The difference between an assistant and a
  surveillance device is entirely whether the camera fires without asking.

```yaml
nodes:
  allowed_capabilities:
    "*": [location.get]
    phone-abc123: [camera.snap, screen.snapshot]
```

## Voice — `core/speech.py`, `channels/voice_adapter.py`

STT in, TTS out, behind one provider seam shared with media understanding.
Providers: OpenAI, local Whisper, ElevenLabs, macOS `say`. Local options are
preferred where configured — audio is among the most personal data an operator
has, and sending every utterance to a vendor should be a choice.

The rule enforced in the adapter rather than left to the model: **high-impact
actions need a fresh spoken confirmation.** Recognition is lossy, rooms contain
other people, and "send it" is four phonemes from a dozen other things. An
approval that a mis-transcription can satisfy is not an approval — so anything
ambiguous re-asks instead of proceeding.

Replies are stripped for speech: code blocks are summarized rather than read
aloud, markdown furniture is dropped.

## Media

`media_understand` — transcribe audio and video (ffmpeg extracts the track),
describe images through the configured vision model. Attachments are how people
actually send information; an agent that can only read text asks them to retype
what they already sent.

`video_generate`, `music_generate` — Replicate-backed, CRITICAL, and honest
about cost. Neither retries silently, because a retried generation is a second
bill.

## Standing preferences — `core/preferences.py`

Separate from the inferred user profile on purpose: **observations and
preferences fail differently.** Being wrong about an observation costs a little
relevance; being wrong about a directive means doing the thing the operator
explicitly forbade.

**Supersede in place.** A store that appends ends up holding "always use tabs"
*and* "always use spaces", and the model follows whichever it retrieved. New
directives replace old ones on the same subject. Exact topic keys are not enough
— "use tabs" and "use spaces" produce different keys — so matching uses the
overlap coefficient over topic tokens, which reads them as the same subject
differing only in value. Every supersede is logged and the old row is kept
queryable: a wrong supersede is recoverable, a silent contradiction is not.

**Provenance decides injection.** `owner` (stated) injects every turn; `agent`
(inferred) injects marked as such; `untrusted` — anything derived from content
the agent merely *read* — is stored and searchable but **never auto-injected**.
That last rule is what stops a prompt-injected page from writing the agent's
standing orders.

Rendered NEVER-first, so a model skimming a long prompt hits prohibitions before
preferences. Tools: `preference_record`, `preference_list`.

## Hybrid recall — `core/rerank.py`

Pure relevance ranking degrades as a corpus grows: the top-k become
near-duplicates, five chunks of one post-mortem crowd out the one that would
have contradicted them, and the model reads a narrow slice as consensus.

MMR (λ = 0.65) blends relevance with novelty against what is already selected,
after dropping verbatim repeats. Similarity is token Jaccard — no embedding
needed, so it works on the keyword path too.

One detail that mattered: scores are normalized by **dividing by the max**, not
min-max. Min-max stretches whatever range is present, so three near-tied
duplicates become 1.0 / 0.98 / 0.96 while a useful chunk three points behind
collapses to 0.0, and no λ can then promote it.

## Loop detection — `core/loop_detect.py`

A stuck agent is not idle: it spends money and wall-clock re-running the same
failing call until `max_steps` cuts it off hundreds of calls later. The step
ceiling is a budget, not a diagnosis.

What identifies a loop is the **triple**: same tool, same arguments, same
result. Any one repeating is normal; all three mean the agent is not learning
from what it is doing.

Graduated, because a legitimate retry looks identical to a first repeat:
2nd → warn (told to the model in the tool result), 3rd → block that call,
4th → end the run. State is per-run, so an hourly cron job does not inherit
last run's counters.

## Live steering

Mid-turn messages already reached the running loop; they were framed as
`[user added mid-turn: …]`, which reads as extra background. A message arriving
mid-run is usually a *correction*, so it is now framed as
`[STEER — … treat it as superseding your current approach where the two
conflict]`.

## Agent packages — `core/package.py`

A working agent is not just code: it is a persona, skills, plugins, MCP servers,
scheduled work, and the config tying them together. A **package** is all of that
as one directory with a `PHANTO.md` manifest.

```
elophanto package export outreach-assistant --skill api-playbook --skill booking-flows
elophanto package inspect ./outreach-assistant-package
elophanto package install ./outreach-assistant-package
```

Two safety properties, both learned from what package managers get wrong:

- **Import is inert until confirmed.** Nothing installs, no schedule arms, no
  MCP server launches until the operator approves the plan. A manifest arrives
  from someone else's machine; it is a request, not an instruction.
- **MCP servers and schedules are reported, never applied.** Both execute code
  on the operator's machine on someone else's schedule, so they stay a
  deliberate second step.
- **Credentials never travel.** The manifest records which credential *slugs* a
  package needs, never their values.

## New configuration

```yaml
oauth:      {enabled, providers: {google: {client_id, client_secret, scopes}}}
signal:     {enabled, account, allowed_numbers, signal_cli_path}
imessage:   {enabled, allowed_handles, poll_seconds}
whatsapp:   {enabled, mode, allowed_numbers, phone_number_id, verify_token, bridge_command}
nodes:      {enabled, allowed_capabilities}
voice_channel: {enabled, stt_provider, tts_provider, tts_voice, confirm_high_impact}
loop_detection: {enabled, warn_at, block_at, abort_at}
```

## Tests

`test_preferences.py`, `test_loop_detect.py`, `test_rerank.py`,
`test_nodes_and_package.py`, `test_skill_requires_and_oauth.py`.
