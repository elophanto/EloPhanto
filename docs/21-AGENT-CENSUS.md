# Agent Census — Anonymous Registration System

## Purpose

EloPhanto needs to know how many agents exist in the wild — for statistics, dataset planning, and ecosystem health. The census is a lightweight, anonymous, non-blocking heartbeat that fires on every startup.

**Key constraints:**

- **Purely statistical** — ZERO personal data collected
- **No opt-out** — it's anonymous stats, not telemetry
- **Dataset contribution is separate** and opt-out-able
- **Survives uninstall/reinstall** — same machine = same fingerprint
- **Never blocks startup** — fire-and-forget with 3s timeout

---

## Fingerprint Generation

Derive a stable, anonymous agent ID from the machine's hardware UUID:

```
agent_id = SHA-256(machine_uuid + "elophanto-census-salt")
```

### Machine UUID Sources

| Platform | Source |
|----------|--------|
| macOS | `ioreg -rd1 -c IOPlatformExpertDevice` → `IOPlatformUUID` |
| Linux | `/etc/machine-id` (systemd) or `/var/lib/dbus/machine-id` |
| Windows | `reg query HKLM\SOFTWARE\Microsoft\Cryptography /v MachineGuid` |

### Security Properties

- **One-way**: SHA-256 cannot be reversed to recover the machine UUID
- **Salted**: `"elophanto-census-salt"` prevents rainbow table attacks and ensures the hash is unique to EloPhanto (not correlatable with other services using the same machine ID)
- **Deterministic**: Same machine always produces the same fingerprint across reinstalls

### Fallback

If the machine UUID is unavailable (container, sandbox, restricted permissions), generate a random UUID and persist it to `data/.census_id`. On reinstall to the same path, this file survives if `data/` is preserved.

---

## Heartbeat Payload

Minimal, anonymous, non-identifying:

```json
{
  "agent_id": "sha256:a1b2c3d4e5f6...",
  "v": "0.1.0",
  "platform": "darwin-arm64",
  "python": "3.12.4",
  "first_seen": false
}
```

| Field | Description |
|-------|-------------|
| `agent_id` | Deterministic machine fingerprint (SHA-256 hex, prefixed `sha256:`) |
| `v` | EloPhanto version string |
| `platform` | `{sys.platform}-{platform.machine()}` (e.g., `darwin-arm64`, `linux-x86_64`) |
| `python` | Python version (useful for compatibility stats) |
| `first_seen` | `true` if this is the first heartbeat ever from this agent_id (locally tracked) |

### What is NOT Included

- Display name, agent name, or identity data
- IP address, hostname, or username
- Task counts, tool usage, or activity data
- File paths, working directory, or environment variables
- Any data that could identify a person or their activity

---

## API Endpoint

```
POST https://api.elophanto.com/v1/census/heartbeat
Content-Type: application/json
```

### Server-Side Contract

- Upserts agent record by `agent_id`
- Stores `last_seen_at`, `version`, `platform`, `python`
- Tracks `first_seen_at` (set once on first heartbeat)
- Returns `200 OK` with `{"status": "ok"}` (or `201` on first registration)

### Supabase Table

```sql
create table agent_census (
  agent_id text primary key,
  version text,
  platform text,
  python_version text,
  first_seen_at timestamptz default now(),
  last_seen_at timestamptz default now()
);
```

---

## Startup Integration

Fire-and-forget during `Agent.initialize()`:

1. Compute fingerprint (deterministic, fast — no I/O except reading machine UUID once)
2. Spawn `asyncio.create_task(send_heartbeat())` — non-blocking
3. 3-second timeout, no retries, silent failure
4. Runs at the end of `initialize()`, doesn't depend on any subsystem

### No Config

The census URL is hardcoded as a constant in `core/census.py`:

```python
CENSUS_URL = "https://api.elophanto.com/v1/census/heartbeat"
```

No `config.yaml` section, no enabled/disabled toggle. Always on.

---

## Local State

A marker file `data/.census_sent` tracks whether the first heartbeat was ever sent. This determines the `first_seen` field in the payload:

- If `data/.census_sent` does not exist → `first_seen: true`, create the file after successful send
- If it exists → `first_seen: false`

---

## Security Analysis

| Concern | Mitigation |
|---------|------------|
| Machine UUID exposure | SHA-256 hash is one-way; salt prevents correlation |
| IP address logging | Server may see IP from HTTP, but it's NOT stored or associated with `agent_id` |
| Fingerprint tracking across services | Salt `"elophanto-census-salt"` makes the hash unique to EloPhanto |
| Payload contains PII | Payload is verified to contain only 5 fields, none identifying |
| Network failure blocks startup | Fire-and-forget with 3s timeout; all exceptions caught |
| MITM attack | HTTPS only; no secrets in payload |

---

## Relationship to Dataset System

The census and the self-learning dataset collection ([14-SELF-LEARNING.md](14-SELF-LEARNING.md)) are **completely separate systems**:

| | Census | Dataset Collection |
|---|---|---|
| **Purpose** | Count installations | Improve the model |
| **Data sent** | 5 anonymous fields | Full task conversations |
| **Opt-out** | No (anonymous stats) | Yes (explicit opt-in) |
| **Auth required** | No | Yes (API key) |
| **Frequency** | Once per startup | Per completed task |
| **Privacy risk** | None | Sanitized, user-controlled |

---

## Implementation

### Files

| File | Purpose |
|------|---------|
| `core/census.py` | `get_agent_fingerprint()`, `send_heartbeat()`, `_build_payload()` |
| `core/agent.py` | One line added in `initialize()` |
| `tests/test_core/test_census.py` | Fingerprint stability, payload validation, timeout behavior |

### Dependencies

- `hashlib` (stdlib) — SHA-256
- `platform` (stdlib) — machine architecture
- `subprocess` (stdlib) — `ioreg` on macOS
- `httpx` (already in project) — async HTTP POST
