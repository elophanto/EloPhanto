# 46 — Proactive Engine

> Heartbeat file-based standing orders + webhook wake/task endpoints.

---

## Overview

The Proactive Engine makes EloPhanto genuinely proactive — it can act without waiting for a user message. Two mechanisms work together:

1. **Heartbeat Engine** — Periodically reads `HEARTBEAT.md` from the project root. If the file has content, the agent executes it as a task. No LLM call when the file is empty or missing.

2. **Webhook Endpoints** — HTTP POST endpoints on the gateway that let external systems trigger agent actions: wake the heartbeat immediately, or inject an ad-hoc task.

Both mechanisms complement the existing **Autonomous Mind** (LLM-driven background thinking) and **Scheduler** (cron-based task execution). The heartbeat is simpler and cheaper — it only calls the LLM when there's actual work to do.

---

## Heartbeat Engine

### How It Works

```
Every N seconds (default: 30 min):
    1. Read HEARTBEAT.md from project root
    2. File empty or missing?  → Skip (no LLM call, zero cost)
    3. File has content?       → Pass content to agent as task
    4. Agent responds HEARTBEAT_OK? → Mark as idle
    5. Agent does actual work?      → Increment tasks_executed counter
```

### HEARTBEAT.md Format

Write any instructions in plain text or markdown. The agent receives the full file content as a task prompt.

```markdown
# Standing Orders

- Check email inbox for urgent messages
- If any new GitHub issues on my-project, triage and label them
- Post daily metrics summary to #team-updates Slack channel
```

The agent reads this every heartbeat cycle. When all tasks are complete, it responds `HEARTBEAT_OK` and the file stays untouched — the agent skips work on the next cycle. To queue new work, edit the file.

### Managing Orders via Chat

The `heartbeat` tool lets users manage standing orders through conversation instead of editing the file manually:

| Action | What It Does | Example |
|--------|-------------|---------|
| `status` | Show engine status + current orders | "what's my heartbeat status?" |
| `list` | List all standing orders | "list my standing orders" |
| `add` | Append a new order | "add a heartbeat order to check my email" |
| `remove` | Remove an order by number | "remove heartbeat order #2" |
| `clear` | Clear all orders (heartbeat idles) | "clear all heartbeat orders" |
| `set` | Replace all orders at once | "set heartbeat orders to: check email, post metrics" |
| `trigger` | Run a heartbeat check immediately | "trigger a heartbeat check now" |

The tool reads and writes `HEARTBEAT.md` directly — changes made via chat are visible in the file and vice versa. A blank `HEARTBEAT.md` template with instructions is created automatically by `setup.sh` on first install.

### Lifecycle

- **Pauses** when the user sends a message (same as Autonomous Mind)
- **Resumes** when the user's task completes
- **Isolated history** — heartbeat execution doesn't pollute conversation history
- **Auto-approve** — tool calls are auto-approved (spending limits still enforced)

### Configuration

```yaml
heartbeat:
  enabled: true
  file_path: "HEARTBEAT.md"           # relative to project root
  check_interval_seconds: 1800        # 30 minutes
  max_rounds: 8                       # max tool call rounds per heartbeat task
  suppress_idle: true                 # don't broadcast when nothing to do
```

### Events

| Event | When | Data |
|-------|------|------|
| `heartbeat_check` | File has content, starting execution | `file`, `content_length`, `preview` |
| `heartbeat_action` | Task executed successfully | `summary`, `elapsed`, `cycle` |
| `heartbeat_idle` | Nothing to do (only when `suppress_idle: false`) | `reason` |

---

## Webhook Endpoints

### Endpoints

The gateway exposes two HTTP POST endpoints when `webhooks.enabled: true`:

#### `POST /hooks/wake`

Trigger an immediate heartbeat check. The agent reads HEARTBEAT.md right now instead of waiting for the next interval.

```bash
curl -X POST http://127.0.0.1:18789/hooks/wake \
  -H "Content-Type: application/json" \
  -d '{"event": "New email from client"}'
```

**Response:** `200 OK`
```json
{"status": "ok", "action": "heartbeat_triggered"}
```

If the heartbeat engine is not running, returns `503 Service Unavailable`.

Also injects the `event` text into the Autonomous Mind's pending events queue (if running), so the mind sees it on its next wakeup.

#### `POST /hooks/task`

Inject an ad-hoc task for the agent to execute immediately. No HEARTBEAT.md involved — the goal is executed directly.

```bash
curl -X POST http://127.0.0.1:18789/hooks/task \
  -H "Content-Type: application/json" \
  -d '{"goal": "Check server status and alert if CPU > 90%", "source": "monitoring"}'
```

**Response:** `202 Accepted`
```json
{"status": "accepted", "goal": "Check server status and alert if CPU > 90%"}
```

The task runs asynchronously — the endpoint returns immediately. Results are broadcast as gateway events.

### Authentication

Optional Bearer token authentication:

```yaml
webhooks:
  enabled: true
  auth_token_ref: "webhook_secret"    # vault key
```

When configured, all webhook requests must include:
```
Authorization: Bearer <token>
```

Unauthenticated requests get `401 Unauthorized`.

### Configuration

```yaml
webhooks:
  enabled: true
  auth_token_ref: ""                  # vault key (empty = no auth)
  max_payload_bytes: 65536            # 64 KB max request body
```

### Events

| Event | When | Data |
|-------|------|------|
| `webhook_received` | Hook endpoint called | `hook`, `event` |
| `webhook_task_started` | Ad-hoc task execution begins | `goal`, `source` |

### Error Responses

| Status | Condition |
|--------|-----------|
| `400` | Missing `goal` in `/hooks/task`, or invalid JSON |
| `401` | Auth token configured but not provided / wrong |
| `404` | Webhooks disabled, or unknown hook path |
| `413` | Request body exceeds `max_payload_bytes` |
| `503` | `/hooks/wake` called but heartbeat engine not running |

---

## Use Cases

### 1. Gmail → Webhook → Agent

Set up Gmail Pub/Sub to POST to `/hooks/wake` when new email arrives:

```
Gmail → Google Cloud Pub/Sub → Cloud Function → POST /hooks/wake
```

Write in HEARTBEAT.md:
```markdown
- Check email inbox. For urgent emails, draft a response and notify me on Telegram.
```

### 2. CI/CD Integration

Post-deploy hook triggers agent verification:

```bash
# In your deploy script
curl -X POST http://127.0.0.1:18789/hooks/task \
  -d '{"goal": "Run smoke tests against production and report results", "source": "deploy"}'
```

### 3. Monitoring Alerts

Prometheus/Grafana webhook forwards alerts:

```bash
curl -X POST http://127.0.0.1:18789/hooks/task \
  -d '{"goal": "Server CPU is at 95%. Investigate and take action.", "source": "alertmanager"}'
```

### 4. Scheduled Standing Orders

Combine with the existing Scheduler for time-based heartbeat triggers:

```
schedule_task → "every morning at 9am" → update HEARTBEAT.md with daily tasks
```

Or use the existing `schedule_task` tool directly for time-based work.

---

## Architecture

```
External Systems          ┌─────────────────────────┐
  (Gmail, CI/CD,     ──→  │  POST /hooks/wake       │ ─→ HeartbeatEngine._check_and_execute()
   Monitoring, etc.)      │  POST /hooks/task        │ ─→ Agent.run(goal)
                          └────────┬────────────────┘
                                   │
                            Gateway (HTTP layer)
                                   │
                          ┌────────┴────────────────┐
                          │  Heartbeat Engine        │
                          │  (periodic loop)         │
                          │                          │
                          │  Every N seconds:        │
                          │  read HEARTBEAT.md       │
                          │  → execute if content    │
                          └──────────────────────────┘
                                   │
                          ┌────────┴────────────────┐
                          │  Agent Core              │
                          │  (plan/execute/reflect)  │
                          └──────────────────────────┘
```

### Comparison with Autonomous Mind

| Aspect | Heartbeat | Autonomous Mind |
|--------|-----------|-----------------|
| Trigger | File content in HEARTBEAT.md | Timer (LLM decides next interval) |
| LLM cost when idle | Zero | Zero (skips cycle) |
| LLM cost per cycle | Only when file has content | Every wakeup calls LLM |
| User control | Edit a text file | Set goals, configure budget |
| Self-direction | Follows file instructions only | LLM decides what to do |
| Best for | Predictable standing orders | Autonomous goal pursuit |

Both can run simultaneously. The heartbeat handles deterministic, user-defined tasks. The mind handles open-ended autonomous work.

---

## Files

| File | Purpose |
|------|---------|
| `core/heartbeat.py` | HeartbeatEngine implementation |
| `core/gateway.py` | Webhook endpoint handlers (`_handle_webhook`, `_webhook_wake`, `_webhook_task`) |
| `core/config.py` | `HeartbeatConfig`, `WebhookConfig` dataclasses |
| `core/protocol.py` | Event types (`HEARTBEAT_*`, `WEBHOOK_*`) |
| `tools/scheduling/heartbeat_tool.py` | Chat tool for managing standing orders (`heartbeat`) |
| `HEARTBEAT.md` | Standing orders template (created by `setup.sh`) |
| `tests/test_core/test_heartbeat.py` | 16 heartbeat engine tests |
| `tests/test_core/test_heartbeat_tool.py` | 17 heartbeat tool tests |
| `tests/test_core/test_webhooks.py` | 13 webhook tests |
