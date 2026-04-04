# 61 — Video Meeting Agent (PikaStream)

> Join Google Meet and Zoom calls as a real-time AI avatar with voice
> cloning, context-aware conversation, and automatic billing.

**Status:** Complete (skill installed)
**Priority:** P2 — New capability
**Source:** [Pika-Labs/Pika-Skills](https://github.com/Pika-Labs/Pika-Skills) (Apache 2.0)

---

## Overview

EloPhanto can now join video meetings as a real-time AI participant via
PikaStreaming. The agent appears with a generated or custom avatar image,
speaks with a cloned voice, and carries workspace context into the
conversation — it knows who it is, what it's been working on, and who
the people in the meeting are.

**Cost:** $0.50 per minute of meeting time, billed via Pika Developer API.

---

## Setup

### 1. Get a Pika Developer Key

Go to [pika.me/dev](https://www.pika.me/dev/) and create a Developer Key
(starts with `dk_`).

### 2. Store the key

```
vault set pika_dev_key dk_your-key-here
```

Or set the environment variable:
```bash
export PIKA_DEV_KEY="dk_your-key-here"
```

### 3. Install dependencies

```bash
pip install -r skills/pikastream-video-meeting/requirements.txt
```

---

## Usage

Drop a Google Meet or Zoom link in conversation:

> "Join this meeting: https://meet.google.com/abc-defg-hij"

The agent will:

1. **Check avatar** — looks for `identity/videomeeting-avatar.png`. If missing,
   asks you to send an image or says "generate" to create one via AI.

2. **Check voice** — looks for `life/voice_id.txt`. If missing, asks you to
   send a voice recording (10s-5min) for cloning, or skip to use a default voice.
   Warns if voice clone is >6 days old (Pika deletes after 7 days of non-use).

3. **Gather context** — reads workspace files (MEMORY.md, identity, daily logs,
   recent activity) and synthesizes a concise reference card with:
   - Known facts (names, dates, numbers)
   - Recent activity (what was built/fixed/done)
   - People (who matters, specific interactions)
   - Current state

4. **Check balance** — verifies sufficient Pika credits. If not enough,
   generates a payment link.

5. **Join** — enters the meeting with avatar + voice + context.

### Leave

Say "leave the meeting" or the agent will leave when the call ends.

### Commands

```bash
# Join a meeting
python skills/pikastream-video-meeting/scripts/pikastreaming_videomeeting.py join \
  --meet-url <url> --bot-name <name> \
  --image identity/videomeeting-avatar.png \
  --voice-id <id> --system-prompt-file /tmp/meeting_system_prompt.txt

# Leave a meeting
python skills/pikastream-video-meeting/scripts/pikastreaming_videomeeting.py leave \
  --session-id <id>

# Generate an avatar
python skills/pikastream-video-meeting/scripts/pikastreaming_videomeeting.py generate-avatar \
  --output identity/videomeeting-avatar.png --prompt "description"

# Clone a voice
python skills/pikastream-video-meeting/scripts/pikastreaming_videomeeting.py clone-voice \
  --audio <file> --name <name> --noise-reduction
```

---

## Integration Points

| Feature | How it integrates |
|---------|-------------------|
| **Identity system** | Avatar stored as `identity/videomeeting-avatar.png` |
| **Voice persistence** | Voice ID in `life/voice_id.txt`, config in `life/voice_config.json` |
| **Context synthesis** | Reads MEMORY.md, identity files, daily logs for meeting context |
| **Vault** | `pika_dev_key` stored in vault or `PIKA_DEV_KEY` env var |
| **Billing** | Auto-checks balance, generates checkout URL if credits needed |

---

## Files

| File | Description |
|------|-------------|
| `skills/pikastream-video-meeting/SKILL.md` | Skill definition with full workflow |
| `skills/pikastream-video-meeting/scripts/pikastreaming_videomeeting.py` | Python script (join, leave, generate-avatar, clone-voice) |
| `skills/pikastream-video-meeting/assets/placeholder-avatar.jpg` | Default avatar fallback |
| `skills/pikastream-video-meeting/requirements.txt` | `requests>=2.32.5` |

---

## Requirements

- Python 3.10+
- `PIKA_DEV_KEY` environment variable or vault entry
- `ffmpeg` (optional, for audio format conversion during voice cloning)
