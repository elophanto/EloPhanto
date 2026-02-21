# Recovery Mode — Remote Agent Recovery Without LLM

## Purpose

When all LLM providers fail, the agent becomes unresponsive — it can't plan, execute, or even acknowledge messages. But the **gateway is still alive**. Channel adapters (Telegram, Discord, Slack, CLI) remain connected via WebSocket, and the command dispatcher still processes `/`-prefixed commands.

Recovery mode exploits this: a set of **hardcoded gateway commands** that let you diagnose the problem, update config, switch providers, and restart the agent — all without a single LLM call.

**Key constraints:**

- **Zero LLM involvement** — every command is pure Python logic in the gateway
- **Works from any channel** — Telegram, Discord, Slack, CLI — wherever you still have a connection
- **Only authorized users** — same `allowed_users` check that already gates every channel
- **Destructive commands require approval** — config changes, restarts go through the approval system
- **Auto-enters when all providers fail** — you don't have to remember the command

---

## Why This Works Without LLM

The gateway's message flow has two paths:

```
User message
  ├─ starts with "/"  →  _handle_command()  →  pure Python switch  →  response
  └─ normal text      →  _handle_chat()     →  Agent.run_session() →  LLM call
```

Recovery commands take the **left path**. The command handler is a simple dispatcher — it reads the command name, runs hardcoded logic, and returns a formatted string. The LLM is never involved. This already works today for `/status` and `/sessions`.

---

## Recovery Commands

All commands are processed by `_handle_command()` in `core/gateway.py`.

### Diagnostics (read-only, no approval needed)

| Command | Description |
|---------|-------------|
| `/health` | Show all providers: healthy/unhealthy, last error, last check time |
| `/health recheck` | Re-run provider health checks immediately and report results |
| `/health full` | Extended diagnostics: providers + browser bridge + scheduler + DB + disk space |
| `/config get <key>` | Read a config value (dot-notation, e.g., `llm.provider_priority`) |

### Provider Management (approval required)

| Command | Description |
|---------|-------------|
| `/provider enable <name>` | Mark a provider as enabled (takes effect immediately) |
| `/provider disable <name>` | Mark a provider as disabled |
| `/provider priority <a,b,c>` | Reorder provider fallback chain (comma-separated) |
| `/provider test <name>` | Send a minimal test prompt to a specific provider, report success/failure |

### Config Management (approval required)

| Command | Description |
|---------|-------------|
| `/config set <key> <value>` | Update a config value in memory (immediate, lost on restart) |
| `/config save` | Write current in-memory config to `config.yaml` |
| `/config reload` | Re-read `config.yaml` from disk and apply changes |
| `/config diff` | Show differences between in-memory config and `config.yaml` on disk |

### Agent Control (approval required)

| Command | Description |
|---------|-------------|
| `/restart` | Graceful restart: re-run `Agent.initialize()`, reconnect subsystems |
| `/restart hard` | Full process restart via supervisor (systemd/launchd/Docker) |
| `/recovery on` | Enter recovery mode manually |
| `/recovery off` | Exit recovery mode |

### Recovery Scripts (approval required)

| Command | Description |
|---------|-------------|
| `/script list` | Show available recovery scripts from `scripts/recovery/` |
| `/script run <name>` | Execute a pre-registered recovery script |

---

## Health Diagnostics

### Provider Health Report

The `/health` command reads from the router's existing `_provider_health` dict and formats it:

```
🔴 zai        — unhealthy since 14:32  │ 401 Unauthorized
🟢 openrouter — healthy                │ last check 14:35
🔴 ollama     — unhealthy since 14:30  │ Connection refused

Provider priority: zai → openrouter → ollama
Recovery mode: ACTIVE (auto-entered at 14:37)
```

### Full Health Check

`/health full` extends this with:

| Component | Check |
|-----------|-------|
| LLM Providers | HTTP ping to each provider's health/models endpoint |
| Browser Bridge | `node_bridge.is_alive` — is the Node.js subprocess running? |
| Scheduler | Are scheduled jobs running? Last execution time? |
| Database | Can we read/write to SQLite? |
| Disk Space | Is `data/` partition above 90%? |
| Gateway | Active sessions, connected clients, pending approvals |

### Continuous Monitoring

A background task runs every 60 seconds:

1. Ping each enabled provider
2. Update `_provider_health` dict
3. If **all** providers transition from healthy → unhealthy, broadcast an `EVENT` to all connected clients and auto-enter recovery mode

---

## Auto-Enter Recovery Mode

When all LLM providers are unhealthy for longer than `auto_enter_timeout_minutes` (default: 5):

1. Gateway sets `self._recovery_mode = True`
2. Broadcasts to all channels:
   ```
   ⚠️ All LLM providers are down. Entering recovery mode.
   Use /health to check status. Use /provider or /config to fix.
   ```
3. In recovery mode, normal chat messages get a canned response:
   ```
   Agent is in recovery mode (LLM unavailable). Use /health for diagnostics or /recovery off to exit.
   ```

### Auto-Exit

When a provider becomes healthy and an LLM call succeeds:

1. Gateway sets `self._recovery_mode = False`
2. Broadcasts:
   ```
   ✅ LLM provider restored. Exiting recovery mode.
   ```

---

## Config Hot-Reload

### Safe Subset

Only these config keys can be modified via recovery commands:

```
llm.providers.*          # API keys, base URLs, enabled flags
llm.provider_priority    # Fallback order
llm.routing.*            # Per-task model assignments
llm.budget.*             # Spending limits
browser.enabled          # Toggle browser bridge
gateway.session_timeout  # Session expiry
```

### Blocked Keys

These **cannot** be changed remotely (security-critical):

```
permissions.*            # Permission mode
shell.blacklist_patterns # Command safety
telegram.allowed_users   # Authorization
discord.allowed_guilds   # Authorization
slack.allowed_channels   # Authorization
```

### How Config Set Works

```
/config set llm.provider_priority ["ollama", "openrouter"]
```

1. Parse the dot-notation key path
2. Validate the key is in the safe subset
3. Parse the value (JSON for complex types, raw string for simple)
4. If approval required → route through approval system
5. Update the in-memory `Config` dataclass
6. Propagate to affected subsystems (e.g., call `router.update_priority()`)
7. Respond with confirmation: `✅ llm.provider_priority updated to ["ollama", "openrouter"]`

The change is **in-memory only** until `/config save` writes it to disk.

---

## Agent Restart

### Soft Restart (`/restart`)

1. Send "restarting..." to all channels
2. Cancel active agent tasks
3. Re-run `Agent.initialize()` — reloads config, reconnects providers, re-checks health
4. Resume gateway message processing
5. Send "restarted" to all channels

Sessions survive (persisted to SQLite). WebSocket connections stay open.

### Hard Restart (`/restart hard`)

1. Send "hard restarting..." to all channels
2. Write a restart marker to `data/.restart_requested`
3. Call `os.execv()` to replace the current process, or signal the supervisor (systemd/launchd/Docker)
4. On startup, check for `.restart_requested` marker and broadcast "recovered from hard restart"

---

## Recovery Scripts

### Directory Structure

```
scripts/recovery/
├── manifest.json
├── switch-to-ollama.sh
├── rotate-api-key.sh
└── pull-and-restart.sh
```

### Manifest

```json
{
  "scripts": [
    {
      "name": "switch-to-ollama",
      "description": "Switch all routing to local Ollama, disable cloud providers",
      "file": "switch-to-ollama.sh",
      "requires_approval": true,
      "timeout_seconds": 30
    },
    {
      "name": "pull-and-restart",
      "description": "Git pull latest changes and hard restart",
      "file": "pull-and-restart.sh",
      "requires_approval": true,
      "timeout_seconds": 120
    }
  ]
}
```

### Execution

Scripts run as subprocesses with:
- Working directory set to project root
- Timeout from manifest (killed if exceeded)
- stdout/stderr captured and sent back to the channel
- Exit code reported (0 = success)

Only scripts listed in `manifest.json` can be executed — no arbitrary commands.

---

## Security

### Authorization

Recovery commands use the **same authorization** as normal commands:
- Telegram: `allowed_users` list (numeric IDs)
- Discord: `allowed_guilds` list
- Slack: `allowed_channels` list
- CLI: always authorized (local access)

No additional auth layer — if you can send `/status` today, you can send `/health`.

### Approval Flow

| Action | Approval? | Rationale |
|--------|-----------|-----------|
| `/health`, `/config get` | No | Read-only, no state change |
| `/config set`, `/config save` | Yes | Modifies agent behavior |
| `/config reload` | Yes | Could change behavior unpredictably |
| `/provider enable/disable` | Yes | Changes LLM routing |
| `/restart` | Yes | Interrupts active sessions |
| `/restart hard` | Yes | Kills the process |
| `/script run` | Yes | Runs shell commands |
| `/recovery on` | Yes | Changes command routing |
| `/recovery off` | No | Returns to normal |

**Approval without LLM**: The approval system is already LLM-independent — it's a gateway-level future/callback mechanism. User A sends `/restart`, gateway broadcasts approval request to all channels, User A (or User B on another channel) sends `/approve`, gateway resolves the future and executes.

### Audit Log

All recovery commands are logged to `data/recovery.log`:

```
2025-06-15T14:37:22Z | telegram:123456 | /health | OK
2025-06-15T14:38:01Z | telegram:123456 | /config set llm.provider_priority [...] | APPROVED | OK
2025-06-15T14:38:45Z | telegram:123456 | /restart | APPROVED | OK
```

### Rate Limiting

Max 10 recovery commands per minute per user. Prevents accidental command flooding.

---

## Configuration

```yaml
recovery:
  enabled: true
  auto_enter_on_provider_failure: true
  auto_enter_timeout_minutes: 5
  auto_exit_on_recovery: true
  inactivity_timeout_minutes: 30
  rate_limit_per_minute: 10
  scripts_dir: "scripts/recovery"
  safe_config_keys:
    - "llm.providers.*"
    - "llm.provider_priority"
    - "llm.routing.*"
    - "llm.budget.*"
    - "browser.enabled"
    - "gateway.session_timeout"
```

---

## Implementation

### Phase 1 — Diagnostics

| File | Purpose |
|------|---------|
| `core/recovery.py` | Recovery command handler, health report formatting |
| `core/gateway.py` | Extend `_handle_command()` to route `/health`, `/recovery` |
| `core/router.py` | Add `get_health_report()` returning structured provider status |

### Phase 2 — Config & Provider Management

| File | Purpose |
|------|---------|
| `core/recovery.py` | Config get/set/reload/save logic, safe-key validation |
| `core/config.py` | Add `reload()` and `update_key()` methods |
| `core/router.py` | Add `update_priority()`, `enable_provider()`, `disable_provider()` |

### Phase 3 — Restart & Scripts

| File | Purpose |
|------|---------|
| `core/recovery.py` | Restart orchestration, script runner |
| `scripts/recovery/manifest.json` | Script registry |
| `core/agent.py` | Add `reinitialize()` method for soft restart |

### Dependencies

- No new dependencies — uses stdlib (`json`, `subprocess`, `pathlib`, `os`) and existing project deps
- `core/router.py` already tracks `_provider_health` — recovery just reads it

---

## Relationship to Other Systems

| System | Relationship |
|--------|-------------|
| Gateway (`core/gateway.py`) | Recovery commands are routed through the existing command dispatcher |
| LLM Router (`core/router.py`) | Health diagnostics read from the router's provider health tracking |
| Approval System | Config changes and restarts use the same approval queue as tool execution |
| Protected Files (`core/protected.py`) | Recovery respects protected files — blocked config keys cannot be modified |
| Channel Adapters | Recovery works on any connected channel, no adapter changes needed |
| Session Manager | Sessions survive soft restarts (SQLite-persisted) |
