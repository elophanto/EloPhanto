# EloPhanto — Agent Email

> **Status: Implemented** — Dual-provider email system. 7 tools, identity integration, audit logging, background inbox monitoring. Supports AgentMail (cloud API) and SMTP/IMAP (bring your own server).

## Overview

A general-purpose agent needs the ability to **send and receive email**. Signing up for services, receiving verification codes, communicating with humans, parsing invoices, monitoring alerts — all of these require a real email inbox the agent controls.

EloPhanto's email system supports **two providers** — mirroring the dual-provider pattern from crypto payments (local wallet vs Coinbase CDP):

- **AgentMail** — Cloud-hosted, API-based, purpose-built for AI agents. Instant inbox creation, zero server config.
- **SMTP/IMAP** — Connect any existing email account (Gmail, Outlook, self-hosted). Emails stay on your server.

Both providers use the same 7 tools — the agent doesn't need to know which provider is active. Provider switching is a config change.

This is an **addition** to existing capabilities. The agent can still use browser-based email (Gmail, ProtonMail) via browser tools when needed. The email tools provide a fast, reliable, API-first channel for autonomous email operations without browser overhead.

### Design Principles

- **Dual-provider** — Choose between AgentMail (managed) or SMTP/IMAP (self-hosted). Same tools, different backends.
- **Agent gets its own inbox** — Like the crypto wallet pattern: agent owns the inbox, user funds/controls it.
- **API-first** — No browser automation needed for email. Clean SDK or stdlib calls for send, receive, search.
- **Credentials in vault** — API keys and passwords stored encrypted, retrieved at execution time, never in LLM context.
- **Identity integration** — Inbox address auto-registered in identity beliefs so the agent remembers its own email across sessions.
- **Approval for outbound** — Sending email requires approval (follows permission mode). Reading is safe.
- **Audit trail** — All email operations logged for accountability.

### Provider Comparison

| | AgentMail | SMTP/IMAP | Browser Webmail |
|---|---|---|---|
| **Setup** | API key only | SMTP/IMAP host, port, credentials | Login flow, 2FA, cookie management |
| **Inbox creation** | Programmatic, instant | Use existing address | Manual, requires verification |
| **Receiving** | API polling | IMAP polling | Scraping, fragile selectors |
| **Search** | Keyword search | IMAP SEARCH + keyword scoring | Provider-specific |
| **Dependencies** | `agentmail` SDK | Python stdlib only | Browser tools |
| **Self-hosted** | No (cloud service) | Yes | No |
| **Best for** | Agent-native workflows | Existing email accounts | One-off web interactions |

## Architecture

```
User: "Sign up for Hetzner with your email"
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  Agent Core (plan → execute → reflect)                    │
│                                                           │
│  1. Check identity: do I have an email? (identity_status) │
│  2. If not: create inbox (email_create_inbox)             │
│  3. Browse Hetzner signup, enter agent email              │
│  4. Wait for verification email (email_list)              │
│  5. Read verification email (email_read)                  │
│  6. Click verification link (browser tools)               │
│  7. Complete signup                                       │
└──────────────────────────────────────────────────────────┘
```

### Email + Browser Interplay

The email tools and browser tools work together for common agent workflows:

```
Service Signup Flow:
    email_create_inbox → agent gets address
        │
        ▼
    Browser: navigate to signup page → fill form with agent email
        │
        ▼
    email_list (poll for verification email, with retry)
        │
        ▼
    email_read → extract verification link
        │
        ▼
    Browser: navigate to verification link → confirm
        │
        ▼
    identity_update → store new account in beliefs
```

```
Invoice Flow (with payments integration):
    email_list → detect invoice email
        │
        ▼
    email_read → extract invoice details / attachment
        │
        ▼
    document_analyze → parse invoice PDF
        │
        ▼
    payment_preview → show cost breakdown
        │
        ▼
    payment_process / crypto_transfer → pay (with approval)
        │
        ▼
    email_send → reply confirming payment
```

## First-Time Setup

### AgentMail Provider

The agent creates its own inbox on first need — similar to the wallet auto-creation pattern.

```
# In config.yaml:
email:
  enabled: true
  provider: agentmail
  api_key_ref: agentmail_api_key    # vault reference

# The agent handles setup conversationally:
  → User: "Get me an email"
  → Agent presents both providers, user chooses AgentMail
  → Agent asks for API key (from https://console.agentmail.to)
  → Agent stores key with vault_set
  → Agent creates inbox: elophanto-a7f3@agentmail.to
  → Agent updates identity beliefs with new address
```

Custom domains require a paid AgentMail plan — set `domain: yourdomain.com` in config.

### SMTP/IMAP Provider

Connect an existing email account. The agent verifies the connection on first use.

```
# In config.yaml:
email:
  enabled: true
  provider: smtp
  smtp:
    host: smtp.gmail.com
    port: 587
    use_tls: true
    username_ref: smtp_username
    password_ref: smtp_password
    from_address: agent@yourdomain.com
    from_name: EloPhanto Agent
  imap:
    host: imap.gmail.com
    port: 993
    use_tls: true
    username_ref: imap_username
    password_ref: imap_password
    mailbox: INBOX

# The agent handles setup conversationally:
  → User: "Use my Gmail for email"
  → Agent asks for SMTP/IMAP details and credentials
  → Agent stores credentials with vault_set
  → Agent updates config.yaml with server details
  → Agent calls email_create_inbox → verifies SMTP + IMAP connections
  → Agent confirms email is ready
```

**Note:** Gmail requires an App Password when 2FA is enabled. The agent should guide the user through this if needed.

## Email Tools

### Tool Hierarchy

| Tool | Permission | Purpose |
|------|-----------|---------|
| `email_create_inbox` | MODERATE | Create a new agent inbox, store address in identity |
| `email_send` | MODERATE | Send an email from the agent's inbox |
| `email_list` | SAFE | List emails in inbox (with filtering, pagination) |
| `email_read` | SAFE | Read a specific email (full body, headers, attachments) |
| `email_reply` | MODERATE | Reply to an email thread |
| `email_search` | SAFE | Semantic search across inbox |
| `email_monitor` | MODERATE | Start/stop background inbox monitoring |

### `email_create_inbox` (`tools/email/create_inbox_tool.py`)

- **Permission:** MODERATE
- **Params:** `display_name` (string, optional — friendly name for the inbox), `domain` (string, optional — override default domain)
- **Returns:** `inbox_id` (string — the email address), `display_name` (string)
- **Side effects:** Stores inbox address in identity beliefs, persists inbox_id in vault for reconnection

```python
class EmailCreateInboxTool(BaseTool):
    name = "email_create_inbox"
    description = "Create a new email inbox for the agent"
    permission_level = PermissionLevel.MODERATE

    async def execute(self, params: dict) -> ToolResult:
        api_key = self._vault.get(self._config.api_key_ref)
        client = AgentMail(api_key=api_key)

        inbox = client.inboxes.create(
            display_name=params.get("display_name", "EloPhanto Agent"),
            domain=params.get("domain", self._config.domain),
        )

        # Persist inbox ID for future sessions
        self._vault.set("agentmail_inbox_id", inbox.inbox_id)

        # Update identity with new email
        if self._identity_manager:
            await self._identity_manager.update_field(
                "beliefs",
                {"email": inbox.inbox_id},
                reason="Created agent email inbox",
            )

        return ToolResult(success=True, data={
            "inbox_id": inbox.inbox_id,
            "display_name": inbox.display_name,
        })
```

### `email_send` (`tools/email/send_tool.py`)

- **Permission:** MODERATE
- **Params:** `to` (string — recipient email), `subject` (string), `body` (string — plain text or HTML), `html` (boolean, default false), `attachments` (array of strings, optional — absolute file paths to attach, max 25 MB total)
- **Returns:** `message_id` (string), `to` (string), `subject` (string), `status` (string)
- **Note:** Uses the agent's default inbox. If no inbox exists, returns error prompting to create one first. Attachments are base64-encoded for AgentMail or MIME-encoded for SMTP.

### `email_list` (`tools/email/list_tool.py`)

- **Permission:** SAFE
- **Params:** `limit` (integer, default 20), `offset` (integer, default 0), `unread_only` (boolean, default false), `from_address` (string, optional — filter by sender)
- **Returns:** `messages` (array of `{message_id, from, subject, snippet, received_at, is_read}`), `total_count` (integer)
- **Note:** Returns message summaries — use `email_read` for full content.

### `email_read` (`tools/email/read_tool.py`)

- **Permission:** SAFE
- **Params:** `message_id` (string)
- **Returns:** `message_id` (string), `from` (string), `to` (string), `subject` (string), `body` (string), `html_body` (string, optional), `received_at` (string), `headers` (dict), `attachments` (array of `{filename, content_type, size_bytes}`)
- **Note:** Attachments are listed but not downloaded — use a follow-up tool call or browser to handle large attachments.

### `email_reply` (`tools/email/reply_tool.py`)

- **Permission:** MODERATE
- **Params:** `message_id` (string — the message to reply to), `body` (string), `reply_all` (boolean, default false), `attachments` (array of strings, optional — absolute file paths to attach, max 25 MB total)
- **Returns:** `message_id` (string), `thread_id` (string), `status` (string)

### `email_search` (`tools/email/search_tool.py`)

- **Permission:** SAFE
- **Params:** `query` (string — natural language or keyword query), `limit` (integer, default 10)
- **Returns:** `results` (array of `{message_id, from, subject, snippet, relevance_score, received_at}`)
- **Note:** Uses AgentMail's built-in semantic search — searches by meaning, not just keywords.

## Skill

### `skills/email-agent/SKILL.md`

```markdown
---
name: email-agent
triggers:
  - send email
  - check email
  - check inbox
  - read email
  - sign up with email
  - create email
  - create inbox
  - verify email
  - email verification
  - forward email
tools_used:
  - email_create_inbox
  - email_send
  - email_list
  - email_read
  - email_reply
  - email_search
  - identity_status
  - identity_update
---

# Email Agent

You have your own email inbox via AgentMail. Use it for sending/receiving
emails, signing up for services, and handling verification flows.

## Key Behaviors

1. **Check if you have an inbox first** — Use `identity_status` to check
   if you already have an email address in your beliefs before creating a
   new one.

2. **Service signups** — When signing up for a service:
   - Create inbox if needed (`email_create_inbox`)
   - Use browser tools to fill signup forms with your email
   - Poll for verification email (`email_list` with retries)
   - Read verification email, extract link (`email_read`)
   - Navigate to link with browser tools
   - Store new account in identity beliefs (`identity_update`)

3. **Responding to emails** — Use `email_reply` to maintain threading.
   Always quote relevant context. Be professional.

4. **Searching** — Use `email_search` with natural language queries.
   It supports semantic search — "invoices from last week" works.

5. **Never share your email credentials** — The API key is in the vault.
   Only share your inbox address when needed for signups or communication.
```

## Background Inbox Monitoring

The agent can monitor its own inbox in the background and push notifications to all connected channels when new emails arrive. This is controlled via conversation — the user asks, the agent starts it.

### How It Works

```
User: "Monitor your inbox for new emails"
    │
    ▼
Agent calls email_monitor(action="start")
    │
    ▼
EmailMonitor background loop starts (default: every 5 minutes)
    │
    ▼
┌─────────── Poll Loop ───────────┐
│ 1. email_list(unread_only=True) │
│ 2. Diff against seen_ids        │
│ 3. Broadcast new_email event    │
│ 4. Save seen_ids to disk        │
│ 5. Sleep(poll_interval)         │
└─────────────────────────────────┘
    │
    ▼
All channels receive notification:
  CLI:      📧 New email from alice@example.com
  Telegram: 📧 *New email* — From: alice@example.com — Subject: ...
  Discord:  📧 **New email** — From: alice@example.com — Subject: ...
  Slack:    📧 *New email* — From: alice@example.com — Subject: ...
```

### Key Design Decisions

- **Conversational control** — No config flag to auto-start. The user says "monitor my inbox" and the agent calls `email_monitor(action="start")`. "Stop monitoring" calls `action="stop"`.
- **Agent's own inbox** — Monitors the agent's email address, not the user's personal inbox.
- **Silent first poll** — The first poll seeds the `seen_ids` set without sending notifications, preventing a flood of old messages.
- **Seen ID persistence** — Message IDs are persisted to `data/email_seen_ids.json` so the monitor doesn't re-notify after a restart.
- **No LLM calls** — The monitor calls `EmailListTool.execute()` directly. Zero cost per poll.
- **Gateway broadcast** — Uses `EventType.NOTIFICATION` with `session_id=None` to reach all connected channels.

### `email_monitor` Tool

- **Permission:** MODERATE
- **Params:** `action` (string — `start`, `stop`, `status`), `poll_interval_minutes` (integer, optional — default 5)
- **Returns:**
  - `start`: `{status: "started", poll_interval_minutes: 5}`
  - `stop`: `{status: "stopped"}`
  - `status`: `{is_running: true/false, poll_interval_minutes: 5, seen_count: 42}`

### Configuration

```yaml
# config.yaml — under email:
email:
  monitor:
    poll_interval_minutes: 5    # default poll interval (overridable via tool param)
    persist_seen_ids: true      # persist seen message IDs across restarts
```

No `enabled` field — the monitor starts/stops via the tool, not config. Config only sets defaults.

## Webhook Support (Future)

AgentMail supports webhooks and websockets for real-time notifications. In a future iteration, this enables reactive email handling:

```
AgentMail webhook → POST to EloPhanto endpoint
    │
    ▼
Gateway event: email_received
    │
    ▼
Agent evaluates: is this actionable?
    ├── Verification email → auto-process
    ├── Invoice → queue for payment review
    ├── Spam → ignore
    └── Conversation → notify user, draft reply
```

### Webhook Events

| Event | Description |
|-------|-------------|
| `message.received` | New email arrived in agent inbox |
| `message.sent` | Outbound email delivered |
| `message.bounced` | Delivery failed |
| `message.complained` | Recipient marked as spam |

This requires exposing a webhook endpoint — would integrate with the gateway or a lightweight HTTP listener. Not in initial scope.

## Identity Integration

When the agent creates an inbox, the email address is stored in two places:

1. **Vault** — `agentmail_inbox_id` for reconnecting to the inbox across sessions
2. **Identity beliefs** — `{"email": "agent@agentmail.to"}` so the agent knows its own email address in every system prompt

```
System prompt includes:
<self_model>
  ...
  <accounts>email: elophanto-a7f3@agentmail.to</accounts>
  ...
</self_model>
```

On subsequent sessions, the agent sees its email in the identity context and can use it without recreation.

## Configuration

```yaml
# config.yaml
email:
  enabled: true
  provider: agentmail                  # "agentmail" or "smtp"
  # AgentMail settings (used when provider: agentmail)
  api_key_ref: agentmail_api_key       # vault key reference
  domain: agentmail.to                 # default domain (@agentmail.to)
  auto_create_inbox: false             # create inbox on first email task
  inbox_display_name: EloPhanto Agent  # default display name for new inboxes
  # SMTP settings (used when provider: smtp)
  smtp:
    host: ''                           # e.g. smtp.gmail.com
    port: 587
    use_tls: true
    username_ref: smtp_username        # vault key for SMTP username
    password_ref: smtp_password        # vault key for SMTP password
    from_address: ''                   # e.g. agent@yourdomain.com
    from_name: EloPhanto Agent
  imap:
    host: ''                           # e.g. imap.gmail.com
    port: 993
    use_tls: true
    username_ref: imap_username        # vault key for IMAP username
    password_ref: imap_password        # vault key for IMAP password
    mailbox: INBOX                     # default mailbox to read
```

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS email_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    tool_name TEXT NOT NULL,            -- email_send, email_reply, etc.
    inbox_id TEXT NOT NULL,             -- agent inbox address
    direction TEXT NOT NULL,            -- inbound, outbound
    recipient TEXT,                     -- to address (outbound)
    sender TEXT,                        -- from address (inbound)
    subject TEXT,
    message_id TEXT,                    -- AgentMail message ID
    thread_id TEXT,                     -- thread reference
    status TEXT NOT NULL,               -- sent, delivered, failed, received
    session_id TEXT,                    -- gateway session
    channel TEXT,                       -- cli, telegram, discord
    task_context TEXT,                  -- why the email was sent
    error TEXT                          -- error message if failed
);
```

## Integration Points

| Component | What changes |
|-----------|-------------|
| `core/config.py` | `EmailConfig` dataclass; add to `Config` |
| `core/agent.py` | Init email client in `initialize()`; `_inject_email_deps()` for tools |
| `core/database.py` | `email_log` DDL |
| `core/registry.py` | Register 6 email tools |
| `tools/email/` | 6 tool files + `__init__.py` |
| `skills/email-agent/` | `SKILL.md` skill file |
| `config.yaml` | `email:` section |
| `pyproject.toml` | Add `agentmail` to dependencies |
| `setup.sh` | Install email deps when `email.enabled` |

## Dependencies

```
agentmail          # AgentMail Python SDK
```

Added to `pyproject.toml` core dependencies (lightweight SDK, no heavy transitive deps).

## Privacy & Safety

- **Cloud service** — Emails route through AgentMail infrastructure. Similar tradeoff as OpenRouter — external provider, API key in vault, user opt-in.
- **No secrets in emails** — Agent should never include vault credentials, private keys, or internal system details in outbound emails.
- **Credential isolation** — API key in vault, never in LLM context. Only the inbox address is visible in identity/system prompt.
- **Outbound approval** — Sending emails requires approval (follows permission mode). Prevents the agent from spamming or impersonating.
- **Audit trail** — All email operations logged to `email_log` table.
- **User control** — `email.enabled: false` disables all email tools. User can revoke API key at any time.

## Files

| File | Description |
|------|-------------|
| `tools/email/__init__.py` | Package init |
| `tools/email/smtp_client.py` | SMTP/IMAP helper functions (stdlib only) |
| `tools/email/create_inbox_tool.py` | email_create_inbox tool (AgentMail + SMTP) |
| `tools/email/send_tool.py` | email_send tool (AgentMail + SMTP) |
| `tools/email/list_tool.py` | email_list tool (AgentMail + IMAP) |
| `tools/email/read_tool.py` | email_read tool (AgentMail + IMAP) |
| `tools/email/reply_tool.py` | email_reply tool (AgentMail + SMTP/IMAP) |
| `tools/email/search_tool.py` | email_search tool (AgentMail + IMAP) |
| `tools/email/monitor_tool.py` | email_monitor tool (start/stop/status) |
| `core/email_monitor.py` | EmailMonitor background polling loop |
| `skills/email-agent/SKILL.md` | Email agent skill |
| `core/config.py` | EmailConfig, SmtpServerConfig, ImapServerConfig |
| `core/agent.py` | Email initialization + dependency injection |
| `core/registry.py` | Email tool registration |
| `core/database.py` | email_log DDL |

## Status

**Implemented** — Dual-provider email system with background inbox monitoring.

### Phases

| Phase | Scope | Status |
|-------|-------|--------|
| **Phase 1** | 6 tools, AgentMail provider, skill, identity integration, audit log | Done |
| **Phase 1b** | SMTP/IMAP as second provider, dual-provider UX | Done |
| **Phase 1c** | Background inbox monitoring — `email_monitor` tool, cross-channel notifications, seen ID persistence | Done |
| **Phase 2** | Webhook listener for reactive email handling | Future |
| **Phase 3** | Multi-inbox support, custom domain management | Future |
