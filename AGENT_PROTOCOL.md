# EloPhanto Agent Protocol v1.0

**Version:** 1.0  
**Status:** Stable  
**Date:** 2026-04-03

---

## 1. Overview

The EloPhanto Agent Protocol defines how any external agent, client, or channel adapter communicates with an EloPhanto instance. It uses a WebSocket control plane for real-time bidirectional messaging and HTTP endpoints for stateless queries and webhooks.

All channel adapters (CLI, Telegram, Discord, Slack, Web) are thin clients that connect to the gateway. The gateway manages sessions, routes messages to the agent, and broadcasts events back to the appropriate channel.

```
Channel Adapter <--ws--> Gateway <--direct--> Agent
                                  <--direct--> SessionManager
```

---

## 2. Transport

### 2.1 WebSocket

- **Default endpoint:** `ws://127.0.0.1:18789`
- **Protocol:** RFC 6455 WebSocket
- **Encoding:** UTF-8 JSON, one message per WebSocket frame
- **Keepalive:** Clients SHOULD send WebSocket ping frames every 30 seconds. The gateway responds with pong frames automatically.
- **Reconnection:** Clients SHOULD implement exponential backoff on disconnect (1s, 2s, 4s, ... up to 60s).

### 2.2 HTTP

The gateway serves HTTP on the same port. HTTP requests are handled before WebSocket upgrade.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | Health check |
| `GET` | `/capabilities` | No | Agent capability discovery |
| `POST` | `/hooks/wake` | Bearer | Wake the agent from sleep |
| `POST` | `/hooks/task` | Bearer | Submit a task via webhook |

---

## 3. Authentication

### 3.1 WebSocket

After the WebSocket connection is established, the client MUST send a `status` message with an `auth_token` field within 5 seconds:

```json
{
  "type": "status",
  "id": "uuid",
  "session_id": "",
  "channel": "telegram",
  "user_id": "user123",
  "data": {
    "status": "auth",
    "auth_token": "bearer-token-value"
  }
}
```

If authentication fails, the gateway sends an `error` message and closes the connection.

If no `gateway.auth_token_ref` is configured, authentication is skipped (local-only mode).

### 3.2 HTTP Webhooks

Webhook endpoints require a Bearer token in the `Authorization` header:

```
Authorization: Bearer <token>
```

The `/health` and `/capabilities` endpoints do not require authentication.

---

## 4. Message Format

Every message — in both directions — uses the `GatewayMessage` envelope:

```json
{
  "type": "string",
  "id": "uuid-v4",
  "session_id": "uuid-v4 | empty",
  "channel": "cli | telegram | discord | slack | web | empty",
  "user_id": "string | empty",
  "data": { }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | One of the message types defined in Section 5. |
| `id` | UUID v4 | Yes | Unique message identifier. Auto-generated if omitted. |
| `session_id` | string | No | Session identifier. Empty for session-less messages. |
| `channel` | string | No | Originating channel adapter identifier. |
| `user_id` | string | No | User identifier within the channel. |
| `data` | object | Yes | Type-specific payload. See Section 5. |

---

## 5. Message Types

### 5.1 Client to Gateway

#### `chat`

Send a user message to the agent.

```json
{
  "type": "chat",
  "channel": "telegram",
  "user_id": "user123",
  "session_id": "session-uuid",
  "data": {
    "content": "What is the weather today?",
    "attachments": [
      {
        "type": "image",
        "url": "https://example.com/photo.jpg"
      }
    ]
  }
}
```

| Data Field | Type | Required | Description |
|------------|------|----------|-------------|
| `content` | string | Yes | The user's message text. |
| `attachments` | array | No | Optional file or media attachments. |

#### `approval_response`

Respond to a tool approval request.

```json
{
  "type": "approval_response",
  "id": "original-approval-request-id",
  "data": {
    "approved": true
  }
}
```

The `id` field MUST match the `id` of the original `approval_request` message.

| Data Field | Type | Required | Description |
|------------|------|----------|-------------|
| `approved` | boolean | Yes | Whether the user approves the action. |

#### `command`

Execute a slash command.

```json
{
  "type": "command",
  "channel": "cli",
  "user_id": "owner",
  "session_id": "session-uuid",
  "data": {
    "command": "tools",
    "args": {}
  }
}
```

| Data Field | Type | Required | Description |
|------------|------|----------|-------------|
| `command` | string | Yes | Command name (e.g., `tools`, `skills`, `dashboard`, `goal`, `exit`). |
| `args` | object | No | Command-specific arguments. |

#### `capability_request`

Request the agent's capabilities over the WebSocket connection.

```json
{
  "type": "capability_request",
  "channel": "web",
  "user_id": "user123",
  "data": {}
}
```

No data fields are required. The gateway responds with a `capability_response`.

### 5.2 Gateway to Client

#### `response`

Agent response to a user message.

```json
{
  "type": "response",
  "session_id": "session-uuid",
  "data": {
    "content": "The weather is sunny today.",
    "done": true,
    "reply_to": "original-chat-message-id",
    "provider": "openrouter",
    "model": "anthropic/claude-sonnet-4"
  }
}
```

| Data Field | Type | Required | Description |
|------------|------|----------|-------------|
| `content` | string | Yes | The response text. |
| `done` | boolean | Yes | `true` if this is the final response chunk. |
| `reply_to` | string | No | The `id` of the original `chat` message. |
| `provider` | string | No | LLM provider used. |
| `model` | string | No | Model identifier used. |

#### `approval_request`

Request user approval before executing a sensitive tool.

```json
{
  "type": "approval_request",
  "session_id": "session-uuid",
  "data": {
    "tool_name": "execute_command",
    "description": "Run shell command: rm -rf /tmp/cache",
    "params": {
      "command": "rm -rf /tmp/cache"
    }
  }
}
```

| Data Field | Type | Required | Description |
|------------|------|----------|-------------|
| `tool_name` | string | Yes | Name of the tool requesting approval. |
| `description` | string | Yes | Human-readable description of the action. |
| `params` | object | Yes | Tool parameters that will be executed. |

#### `event`

Broadcast event from the agent.

```json
{
  "type": "event",
  "session_id": "session-uuid",
  "data": {
    "event": "task_complete",
    "result": "Successfully deployed website.",
    "duration_ms": 4500
  }
}
```

| Data Field | Type | Required | Description |
|------------|------|----------|-------------|
| `event` | string | Yes | Event subtype (see Section 6). |
| *varies* | any | No | Event-specific payload fields. |

#### `capability_response`

Response to a `capability_request` with full agent capabilities.

```json
{
  "type": "capability_response",
  "data": {
    "protocol_version": "1.0",
    "tools": [
      {"name": "web_search", "description": "Search the web", "group": "browser"}
    ],
    "skills": ["systematic-debugging", "product-launch"],
    "providers": ["openrouter", "zai"],
    "version": "0.9.0"
  }
}
```

| Data Field | Type | Required | Description |
|------------|------|----------|-------------|
| `protocol_version` | string | Yes | Protocol version (currently `"1.0"`). |
| `tools` | array | Yes | Available tools with name, description, and group. |
| `skills` | array | Yes | Available skill names. |
| `providers` | array | Yes | Configured LLM provider names. |
| `version` | string | Yes | Agent software version. |

### 5.3 Bidirectional

#### `status`

Heartbeat, authentication, or status exchange.

```json
{
  "type": "status",
  "data": {
    "status": "ok"
  }
}
```

| Data Field | Type | Required | Description |
|------------|------|----------|-------------|
| `status` | string | Yes | Status code: `ok`, `auth`, `busy`, `idle`. |
| *varies* | any | No | Additional status-specific fields. |

#### `error`

Error notification.

```json
{
  "type": "error",
  "session_id": "session-uuid",
  "data": {
    "detail": "Session not found",
    "reply_to": "original-message-id"
  }
}
```

| Data Field | Type | Required | Description |
|------------|------|----------|-------------|
| `detail` | string | Yes | Human-readable error description. |
| `reply_to` | string | No | The `id` of the message that caused the error. |

---

## 6. Event Types

Events are delivered via `event` messages. The `data.event` field identifies the subtype.

### 6.1 Task Events

| Event | Description | Additional Fields |
|-------|-------------|-------------------|
| `task_complete` | A task finished successfully. | `result`, `duration_ms` |
| `task_error` | A task failed. | `error`, `traceback` |
| `step_progress` | Intermediate progress update. | `step`, `total`, `description` |

### 6.2 Session Events

| Event | Description | Additional Fields |
|-------|-------------|-------------------|
| `session_created` | New session established. | `session_id`, `channel`, `user_id` |

### 6.3 Goal Events

| Event | Description | Additional Fields |
|-------|-------------|-------------------|
| `goal_started` | A goal began execution. | `goal_id`, `description` |
| `goal_checkpoint_complete` | A goal checkpoint passed. | `goal_id`, `checkpoint` |
| `goal_completed` | A goal finished successfully. | `goal_id`, `summary` |
| `goal_failed` | A goal failed. | `goal_id`, `error` |
| `goal_paused` | A goal was paused. | `goal_id`, `reason` |
| `goal_resumed` | A goal was resumed. | `goal_id` |

### 6.4 Agent Swarm Events

| Event | Description | Additional Fields |
|-------|-------------|-------------------|
| `agent_spawned` | A child agent was created. | `child_id`, `task` |
| `agent_completed` | A child agent finished. | `child_id`, `result` |
| `agent_failed` | A child agent failed. | `child_id`, `error` |
| `agent_redirected` | A child agent was redirected to a new task. | `child_id`, `new_task` |
| `agent_stopped` | A child agent was stopped. | `child_id`, `reason` |
| `agent_security_alert` | Security concern with a child agent. | `child_id`, `alert` |
| `child_report` | Status report from a child agent. | `child_id`, `report` |
| `child_approval_request` | Child agent requests parent approval. | `child_id`, `action` |
| `child_task_assigned` | Task delegated to a child agent. | `child_id`, `task` |
| `child_feedback` | Feedback sent to a child agent. | `child_id`, `feedback` |

### 6.5 Mind Events

| Event | Description | Additional Fields |
|-------|-------------|-------------------|
| `mind_wakeup` | The agent woke from sleep. | `trigger` |
| `mind_action` | The agent is performing an action. | `action`, `detail` |
| `mind_tool_use` | The agent invoked a tool. | `tool_name`, `params` |
| `mind_sleep` | The agent entered sleep mode. | `reason` |
| `mind_paused` | The agent was paused. | `reason` |
| `mind_resumed` | The agent was resumed. | |
| `mind_revenue` | Revenue event recorded. | `amount`, `currency`, `source` |
| `mind_error` | Internal agent error. | `error` |

### 6.6 Heartbeat Events

| Event | Description | Additional Fields |
|-------|-------------|-------------------|
| `heartbeat_check` | Periodic health check. | `timestamp` |
| `heartbeat_action` | Agent performed a scheduled action. | `action` |
| `heartbeat_idle` | Agent is idle. | `idle_since` |

### 6.7 Webhook Events

| Event | Description | Additional Fields |
|-------|-------------|-------------------|
| `webhook_received` | Incoming webhook received. | `hook_type`, `payload` |
| `webhook_task_started` | Task started from a webhook. | `task_id`, `hook_type` |

### 6.8 System Events

| Event | Description | Additional Fields |
|-------|-------------|-------------------|
| `shutdown` | The agent is shutting down. | `reason` |
| `user_message` | A user message was received (broadcast to other clients). | `content`, `channel` |
| `notification` | General notification. | `title`, `body` |

---

## 7. Session Lifecycle

### 7.1 Session Creation

Sessions are created implicitly when a client sends a `chat` message without a `session_id`, or explicitly via a `command` message with `command: "new_session"`.

The gateway responds with a `session_created` event containing the new `session_id`.

### 7.2 Session Resumption

To resume an existing session, include the `session_id` in subsequent messages. The gateway validates the session exists and has not expired.

### 7.3 Session Expiry

Sessions expire after the configured timeout (default: 24 hours of inactivity). The `session_timeout_hours` parameter in the gateway configuration controls this.

### 7.4 Unified Sessions

When `unified_sessions` is enabled (default), a single user across multiple channels shares one session. The gateway maps `(user_id)` to a session, allowing continuity between e.g. Telegram and CLI.

---

## 8. Capability Discovery

Capability discovery allows clients and other agents to understand what an EloPhanto instance can do before interacting with it.

### 8.1 HTTP Endpoint

```
GET /capabilities
```

Returns:

```json
{
  "protocol_version": "1.0",
  "agent_id": "sha256-fingerprint",
  "tools": [
    {"name": "web_search", "description": "Search the web", "group": "browser"}
  ],
  "skills": ["systematic-debugging", "product-launch"],
  "providers": ["openrouter", "zai"],
  "channels": ["cli", "telegram", "discord"],
  "features": ["browser", "payments", "email"]
}
```

### 8.2 WebSocket Message

Clients may also request capabilities over an active WebSocket connection by sending a `capability_request` message. The gateway responds with a `capability_response` message.

---

## 9. Task Delegation Between Agents

EloPhanto supports multi-agent orchestration via the swarm system. A parent agent can spawn child agents and delegate tasks.

### 9.1 Spawning a Child Agent

The parent uses the `swarm_spawn` tool internally. External clients observe the delegation via events:

1. `child_task_assigned` -- a task was delegated to a child
2. `agent_spawned` -- the child agent was created
3. `child_report` -- periodic status from the child
4. `agent_completed` or `agent_failed` -- the child finished

### 9.2 Controlling Child Agents

External clients can interact with child agents through commands:

- `swarm_status` -- query status of all child agents
- `swarm_redirect` -- redirect a child to a new task
- `swarm_stop` -- terminate a child agent

### 9.3 Child Approval Flow

When a child agent requires approval, the event chain is:

1. Child emits `child_approval_request` to the parent session
2. The parent (or user) responds via `approval_response`
3. The child proceeds or aborts based on the response

---

## 10. Error Handling

### 10.1 Error Message

All errors are delivered as `error` type messages with a `detail` field.

### 10.2 Common Error Conditions

| Condition | Detail | Recovery |
|-----------|--------|----------|
| Invalid JSON | `"invalid message format"` | Resend with valid JSON. |
| Unknown message type | `"unknown message type: X"` | Check supported types. |
| Session not found | `"session not found"` | Create a new session. |
| Session expired | `"session expired"` | Create a new session. |
| Authentication failed | `"unauthorized"` | Reconnect with valid token. |
| Rate limited | `"rate limited"` | Back off and retry. |
| Agent busy | `"agent is busy"` | Wait for current task to finish. |

### 10.3 Connection Errors

If the WebSocket connection drops, clients SHOULD:

1. Attempt reconnection with exponential backoff
2. Re-authenticate on the new connection
3. Resume the previous session using the stored `session_id`

---

## 11. HTTP Webhook Endpoints

### 11.1 `POST /hooks/wake`

Wake the agent from sleep mode.

**Request body:**
```json
{
  "reason": "scheduled task"
}
```

**Response:** `200 OK` with `{"status": "ok"}`

### 11.2 `POST /hooks/task`

Submit a task for the agent to execute.

**Request body:**
```json
{
  "task": "Check email and summarize unread messages",
  "channel": "webhook",
  "priority": "normal"
}
```

**Response:** `200 OK` with `{"status": "accepted", "task_id": "uuid"}`

---

## 12. Backward Compatibility

### 12.1 Versioning Policy

- The protocol version follows semantic versioning: `MAJOR.MINOR`
- **Minor** increments add new message types, event types, or optional fields. Existing clients continue to work.
- **Major** increments indicate breaking changes to the message envelope or existing type semantics.

### 12.2 Forward Compatibility

- Clients MUST ignore unknown fields in messages.
- Clients MUST ignore unknown message types (log and discard).
- Clients MUST ignore unknown event subtypes.

### 12.3 Deprecation

- Deprecated features are announced at least one minor version before removal.
- Deprecated fields include a `deprecated: true` marker in capability responses when applicable.

---

## Appendix A: Quick Reference

### Message Types

| Type | Direction | Purpose |
|------|-----------|---------|
| `chat` | Client -> Gateway | User message |
| `approval_response` | Client -> Gateway | Approve/deny tool execution |
| `command` | Client -> Gateway | Slash command |
| `capability_request` | Client -> Gateway | Discover agent capabilities |
| `response` | Gateway -> Client | Agent reply |
| `approval_request` | Gateway -> Client | Request tool approval |
| `event` | Gateway -> Client | Broadcast event |
| `capability_response` | Gateway -> Client | Agent capabilities |
| `status` | Bidirectional | Heartbeat / auth / status |
| `error` | Bidirectional | Error notification |

### Default Configuration

| Parameter | Default |
|-----------|---------|
| Host | `127.0.0.1` |
| Port | `18789` |
| Max sessions | `50` |
| Session timeout | `24 hours` |
| Unified sessions | `true` |
