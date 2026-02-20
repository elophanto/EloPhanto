# Email Agent

## Description
Manage the agent's email inbox — create inboxes, send/receive/reply to emails,
search messages, and handle verification flows for service signups.
Supports two providers: AgentMail (cloud API) and SMTP/IMAP (your own server).

## Triggers
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
- reply to email
- search email

## Instructions

### Provider Awareness

EloPhanto supports two email providers:
- **AgentMail** (provider: agentmail) — cloud-hosted, API-based, agent-native
- **SMTP/IMAP** (provider: smtp) — your own email server (Gmail, Outlook, etc.)

All 6 email tools work identically regardless of provider. Key differences:
- `email_create_inbox` on SMTP verifies config instead of creating a new inbox.
- `email_search` on SMTP uses keyword matching (not semantic search).
- For SMTP, credentials are SMTP/IMAP username and password (not an API key).

### Key Behaviors

1. **First-time setup** — If any email tool returns a "credentials not found"
   error, handle it conversationally:
   - **For AgentMail**: Ask for an AgentMail API key
     (from https://console.agentmail.to), store with `vault_set agentmail_api_key`.
   - **For SMTP**: Ask for SMTP/IMAP server details and credentials,
     store with `vault_set smtp_username`, `vault_set smtp_password`, etc.
   - Then retry the original email operation.
   - NEVER tell the user to run CLI commands — handle everything in chat.

2. **Check if you have an inbox first** — Use `identity_status` to check
   if you already have an email address in your beliefs before creating a
   new one. Only call `email_create_inbox` if no inbox exists.

3. **Service signups** — When signing up for a service:
   - Check for existing inbox (`identity_status`)
   - Create inbox if needed (`email_create_inbox`)
   - Use browser tools to fill signup forms with your email
   - Poll for verification email (`email_list` with retries, wait a few seconds between)
   - Read verification email, extract link (`email_read`)
   - Navigate to verification link with browser tools
   - Store new account in identity beliefs (`identity_update`)

4. **Sending emails** — Use `email_send` for new messages. Be professional
   and concise. Never include internal system details, vault credentials,
   or private keys in outbound emails.

5. **Responding to emails** — Use `email_reply` to maintain threading.
   Always quote relevant context. Use `reply_all` only when all recipients
   need to see the response.

6. **Checking inbox** — Use `email_list` to see recent messages. Use
   `email_read` for full content of a specific message.

7. **Searching** — Use `email_search` with natural language queries.
   Examples: "verification emails", "invoices from last week",
   "messages from support@hetzner.com".

8. **Never share credentials** — API keys and passwords are in the vault.
   Only share your inbox address when needed for signups or communication.

### Common Workflows

#### First-Time Setup (AgentMail)
```
User: "get me an email"
  → Present both providers (AgentMail vs SMTP), ask preference
  → User chooses AgentMail
  → Ask for API key (point to https://console.agentmail.to)
  → vault_set agentmail_api_key <user's key>
  → email_create_inbox → new address created
  → Tell user their new email address
```

#### First-Time Setup (SMTP)
```
User: "use my Gmail for email"
  → Ask for SMTP/IMAP details (host, port, credentials)
  → vault_set smtp_username <email>
  → vault_set smtp_password <app password>
  → Update config.yaml with server details
  → email_create_inbox → verifies connection
  → Tell user their email is verified and ready
```

#### Verification Flow
```
email_create_inbox (if needed)
  → browser: navigate to signup page
  → browser: fill form with agent email
  → browser: submit form
  → email_list (poll with retries for verification email)
  → email_read (extract verification link)
  → browser: navigate to verification link
  → identity_update (store new account)
```

#### Invoice Handling
```
email_list (check for invoice emails)
  → email_read (get invoice details/attachment)
  → document_analyze (parse invoice PDF if attached)
  → payment_preview (show cost)
  → payment_process / crypto_transfer (pay with approval)
  → email_reply (confirm payment)
```

## Notes
- AgentMail creates cloud-hosted inboxes via API — real email addresses
- SMTP/IMAP connects to existing email accounts — emails stay on your server
- Custom domains require a paid AgentMail plan
- Gmail SMTP requires an App Password when 2FA is enabled
- All email operations are logged to the email_log table for audit
