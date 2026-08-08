# EloPhanto — Telegram Integration

## Overview

Telegram serves as a mobile-first communication channel between the user and EloPhanto. Instead of being limited to the CLI or web UI (which require being at the computer), the user can chat with their agent from anywhere via Telegram.

This is not a secondary interface — it is a full-featured channel with the same capabilities as the CLI. The user can give tasks, receive results, approve pending actions, and monitor the agent's activity, all from their phone.

## Architecture

### Gateway Mode (recommended)

```
┌──────────────┐     Telegram Bot API     ┌────────────────────┐
│  User's       │ ◄───────────────────────► │  Telegram Bot API  │
│  Telegram App │     (polling)             │  Server            │
└──────────────┘                           └────────┬───────────┘
                                                    │
                                                    ▼
                                           ┌────────────────────┐
                                           │ TelegramChannel     │    WebSocket
                                           │ Adapter             │───────────────┐
                                           └────────────────────┘               │
                                                                                ▼
                                           ┌────────────────────┐    ┌─────────────────┐
                                           │ Other Adapters      │───►│    Gateway       │
                                           │ (CLI, Discord, etc) │    │  ws://:18789    │
                                           └────────────────────┘    └────────┬────────┘
                                                                              │
                                                                              ▼
                                                                     ┌─────────────────┐
                                                                     │  EloPhanto Agent │
                                                                     │  (shared)        │
                                                                     └─────────────────┘
```

In gateway mode, the Telegram adapter connects to the gateway via WebSocket. By default, all channels share one unified session (`unified_sessions: true`) — chat from Telegram, see it in CLI, and vice versa. The agent is shared across all channels.

### Direct Mode (legacy)

```
┌──────────────┐     Telegram Bot API     ┌─────────────────┐
│  User's       │ ◄───────────────────────► │  Telegram Bot    │
│  Telegram App │     (polling/webhook)     │  API Server      │
└──────────────┘                           └────────┬────────┘
                                                    │
                                                    ▼
                                           ┌─────────────────┐
                                           │  EloPhanto Agent │
                                           │  (Telegram       │
                                           │   adapter)       │
                                           └─────────────────┘
```

In direct mode (`elophanto telegram`), the Telegram adapter calls `agent.run()` directly without the gateway. This is simpler but doesn't support multi-channel operation.

## Setup

### Creating the Bot

1. Open Telegram and go to @BotFather
2. Start a chat and type `/newbot`
3. Follow the prompts to name the bot and choose a username (e.g., `MyEloPhanto_bot`)
4. BotFather sends a bot token (long string of numbers and letters)
5. During `elophanto init` or in the web UI, paste the token
6. The token is stored in the encrypted vault (never in config files)

### Configuration

In `config.yaml`:

```yaml
telegram:
  enabled: true
  bot_token_ref: "telegram_bot_token"  # reference to vault secret
  
  # Security: only respond to these Telegram user IDs
  # Get your ID by messaging @userinfobot on Telegram
  allowed_users:
    - 123456789
  
  # How the bot connects to Telegram
  mode: "polling"  # "polling" (simple, works everywhere) or "webhook" (requires HTTPS endpoint)
  
  # Webhook settings (only if mode is "webhook")
  webhook:
    url: "https://your-domain.com/telegram/webhook"
    port: 8443
  
  # Notification preferences
  notifications:
    task_complete: true        # notify when a task finishes
    approval_needed: true      # notify when an action needs approval
    scheduled_results: true    # send results of scheduled tasks
    errors: true               # notify on errors
    daily_summary: false       # send a daily activity summary
    daily_summary_time: "20:00"  # time for daily summary (24h format)
  
  # Message formatting
  max_message_length: 4000     # Telegram's limit is 4096, leave buffer
  send_files: true             # allow sending files via Telegram
  send_screenshots: true       # allow sending browser screenshots
```

### User Verification

Critical security requirement: the bot must only respond to authorized users. Without this, anyone who finds the bot username could control the agent.

1. During setup, the user provides their Telegram user ID (numeric, obtained from @userinfobot)
2. The bot stores this in `allowed_users` config
3. Every incoming message is checked against this list before processing
4. Messages from unauthorized users are silently ignored (no response, no error — don't reveal the bot is active)
5. Multiple user IDs can be allowed (e.g., for a shared agent setup)

## Capabilities

### Chat Interface

The primary use — conversational interaction with the agent, identical to the CLI chat:

```
User: Summarize my unread emails
Bot: I'll check your Gmail. One moment...
Bot: You have 7 unread emails:
     📧 John Smith — Q3 Budget Review (action needed)
     📧 GitHub — PR #142 merged
     📧 Newsletter — Weekly AI roundup
     ... [4 more]
     Want me to go into detail on any of these?
```

### Approval Flow

When the agent needs permission for an action, it can notify via Telegram:

```
Bot: 🔔 Approval needed:
     Action: Delete 12 files from /tmp/old-logs/
     Reason: Cleanup task you scheduled
     
     /approve — Allow this action
     /deny — Block this action
     /details — Show file list

User: /details

Bot: Files to delete:
     - access-2025-01.log (2.3 MB)
     - access-2025-02.log (1.8 MB)
     ... [10 more]
     Total: 18.4 MB

User: /approve

Bot: ✅ Done. Deleted 12 files, freed 18.4 MB.
```

### Task Monitoring

```
User: /status

Bot: 📊 EloPhanto Status
     Running: 2 tasks
     • Monitoring inbox (continuous)
     • Building Slack plugin (step 4/7: testing)
     
     Pending approval: 1
     • Send weekly report email
     
     Today: 14 tasks completed, $0.82 spent
```

### File Sharing

The agent can send files through Telegram:

- Documents (PDFs, spreadsheets, text files) as Telegram documents
- Screenshots as Telegram photos
- Code snippets as formatted text with monospace font
- Large outputs as attached files

### Bot Commands

Telegram bots support slash commands with autocomplete. EloPhanto registers these:

| Command | Description |
|---|---|
| `/start` | Initialize the bot, show welcome message |
| `/status` | Current agent status, running tasks, pending approvals |
| `/tasks` | List recent and scheduled tasks |
| `/approve` | Approve the most recent pending action |
| `/deny` | Deny the most recent pending action |
| `/plugins` | List current capabilities |
| `/mode` | Show/change permission mode (`ask_always` / `smart_auto` / `full_auto` / `nuclear`) |
| `/budget` | Show today's LLM spending |
| `/stop` | Pause the agent (stops all tasks) |
| `/resume` | Resume the agent |
| `/help` | Show available commands |

### Inline Keyboard Buttons

For approval requests and multi-option interactions, the bot uses Telegram's inline keyboard buttons instead of requiring the user to type commands:

```
Bot: 🔔 Approval needed:
     Send email to client@example.com
     Subject: "Project Update — Week 7"
     
     [✅ Approve] [❌ Deny] [👁 Preview]
```

This makes the mobile experience smooth — one tap to approve.

## Message Handling

### Incoming Messages (User → Agent)

1. Telegram adapter receives the message
2. Verify sender is in `allowed_users`
3. Check if it's a command (`/status`, `/approve`, etc.) → handle directly
4. Otherwise, treat as a natural language task → feed to the agent core
5. The agent processes it through the normal plan/execute/reflect loop
6. Results are sent back as Telegram messages

### Outgoing Messages (Agent → User)

The adapter handles formatting for Telegram's constraints:

- **Markdown formatting**: Telegram supports a subset of Markdown (bold, italic, code, links). The adapter converts the agent's full markdown output to Telegram-compatible MarkdownV2.
- **Message splitting**: If a response exceeds 4000 characters, it's split into multiple messages at natural breakpoints (paragraph boundaries).
- **Code blocks**: Long code is sent as a document attachment (`.txt` or appropriate extension) rather than inline.
- **Images**: Screenshots and generated images are sent as Telegram photos.
- **Files**: Documents are sent as Telegram document attachments.

### Conversation Context

The Telegram adapter maintains conversation context so multi-turn interactions work:

```
User: What meetings do I have tomorrow?
Bot: You have 3 meetings:
     • 10:00 — Sprint Planning (1h)
     • 14:00 — 1:1 with Sarah (30m)
     • 16:00 — Design Review (45m)

User: Cancel the last one
Bot: I'll cancel the Design Review at 16:00. Should I notify attendees?

User: Yes
Bot: ✅ Design Review cancelled. Sent notification to 4 attendees.
```

The adapter tracks the current conversation thread per user and passes context to the agent.

## Notification System

The Telegram bot is also a notification channel. The agent pushes updates proactively:

### Task Completion

```
Bot: ✅ Task complete: "Build PDF reader plugin"
     • Plugin created and tested (8 tests passed)
     • Registered as `pdf_reader`
     • Time: 4m 23s | Cost: $0.12
```

### Scheduled Task Results

```
Bot: 📬 Morning email summary (scheduled):
     12 new emails overnight.
     • 3 require action
     • 2 from your team
     • 7 newsletters/notifications
     Reply for full details.
```

### Error Notifications

```
Bot: ⚠️ Error in scheduled task "Check server status":
     Connection refused to monitoring.example.com:443
     Retrying in 5 minutes (attempt 2/3).
```

### Daily Summary (Optional)

```
Bot: 📊 Daily Summary — Feb 17, 2026
     
     Tasks: 23 completed, 1 failed, 2 pending
     Self-development: Built 1 new plugin (csv_parser)
     Scheduled: 4 tasks ran successfully
     Cost: $1.47 (OpenRouter: $0.92, Z.ai: $0.55)
     
     Pending approvals: 0
     Next scheduled task: Email check at 09:00
```

## Security Considerations

### Token Security

- The bot token is stored in the encrypted vault, never in config files or source code
- The token grants full control over the bot — if leaked, an attacker could impersonate the bot
- If compromised: revoke via @BotFather (`/revokentoken`), generate a new one, update the vault

### User ID Verification

- Telegram user IDs are numeric and stable (don't change)
- Username-based verification is NOT safe (usernames can be changed/transferred)
- The bot silently ignores unauthorized users — no error messages that could confirm the bot is active

### Message Content

- Telegram messages are encrypted in transit (client-to-server) but Telegram servers can read them
- Sensitive information (passwords, API keys, credit card numbers) should never be sent via Telegram
- The agent should be aware of this limitation — when a response contains sensitive data, it should warn the user or withhold the sensitive parts

### Rate Limiting

- Telegram Bot API has rate limits (about 30 messages per second to different chats)
- The adapter implements rate limiting to avoid hitting these
- For high-volume output (e.g., processing 100 emails), the bot sends a summary rather than individual messages

## Implementation Notes

### Library

Use `python-telegram-bot` (the most mature Python library for Telegram bots) or `aiogram` (async-first, better for integration with the async agent core).

Recommendation: **`aiogram`** — it's async-native, which fits better with the agent's async architecture, and has cleaner middleware support for auth checking.

### Polling vs Webhook

**Polling** (recommended for most users):
- The bot periodically asks Telegram "any new messages?"
- Works behind NAT, firewalls, no domain needed
- Slightly higher latency (configurable poll interval, default 1 second)
- Simpler setup — just needs the bot token

**Webhook** (for advanced users):
- Telegram pushes messages to a URL you provide
- Requires HTTPS endpoint (domain + SSL certificate)
- Lower latency (instant delivery)
- More complex setup but more efficient

Default to polling. The agent can self-develop a webhook setup if the user requests it and has the infrastructure.

### Process Architecture

The Telegram adapter runs as an async task within the agent process (not a separate process). This allows direct access to the agent core, memory, and tools without IPC overhead.

```python
# Simplified startup flow
async def main():
    agent = Agent()
    telegram = TelegramAdapter(agent, config)
    
    await asyncio.gather(
        agent.run(),           # agent core loop
        telegram.start(),      # telegram polling/webhook loop
    )
```

## Relationship to Other Interfaces

The Telegram bot is one of several channel adapters connecting through the gateway:

```
┌─────────────┐
│     CLI      │──┐
├─────────────┤  │
│  Telegram    │──┤── WebSocket ──► Gateway ──► Agent Core ──► Tools
├─────────────┤  │
│   Discord    │──┤
├─────────────┤  │
│    Slack     │──┘
└─────────────┘
```

All channels share the same:
- Agent core and execution engine
- Memory and knowledge base
- Permission system and approval queue
- Tool registry and EloPhantoHub

By default, all channels share one unified session — messages and responses are visible across CLI, Telegram, Discord, and Slack. Set `gateway.unified_sessions: false` for per-channel isolation. Approval requests are routed to the originating channel. Events (task completion, errors) are broadcast to all connected adapters.

## Future Enhancements (Self-Development Candidates)

- **Voice messages**: Process voice messages via speech-to-text, respond with voice
- **Image understanding**: User sends a photo, agent analyzes it (via vision model)
- **Inline mode**: Use the bot in other Telegram chats via @mention
- **Group chat support**: Agent participates in group conversations (with appropriate permissions)
- **Telegram channels**: Agent publishes updates to a private Telegram channel
- **Sticker/reaction responses**: More expressive communication
- **Location sharing**: User shares location, agent provides context-aware help
