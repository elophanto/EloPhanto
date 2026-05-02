# Kid Agents — sandboxed children

> Containerized child EloPhanto instances for running dangerous shell
> commands, untrusted code, and risky package installs without touching
> the host.

## What this is

A "kid" is a child EloPhanto running inside a hardened Docker container.
The parent agent spawns kids on demand, sends them tasks via the
gateway, and destroys them when done. Inside a kid, `rm -rf /`, fork
bombs, kernel-poking, and untrusted package installs are all bounded by
the container — they cannot damage the host.

Kids are **distinct from organization specialists**:

| | Organization specialist | Kid agent |
|---|---|---|
| Use case | Persistent expert (researcher, code reviewer) | Disposable sandbox |
| Lifetime | Long-lived (weeks+) | Short-lived (minutes–hours) |
| Identity | Has own evolving identity, role, knowledge | Aware it's a kid; no durable identity |
| Isolation | Process (same OS) | Container (separate OS userland) |
| Topology | Child runs OWN gateway; master connects to it | Kid is a CLIENT of parent's gateway |
| Trust model | approved/rejected counts, trust score | None |
| Dangerous commands | UNSAFE — would touch host | SAFE — contained |
| Resource caps | None | `--memory --cpus --pids-limit` |

The planner picks which primitive to use based on the user's framing —
"hire", "delegate", "specialist" → organization; "test", "try", "run
untrusted" → kid.

## Quick start

```bash
# One-time setup
elophanto kid build           # builds the elophanto-kid:latest image

# In a chat
"Test installing cowsay"      # planner → kid_spawn → kid_exec → kid_destroy
```

`elophanto doctor` reports container runtime status (docker / podman /
colima) plus image freshness — warns when `core/*.py` is newer than the
built image. Run `elophanto kid build` to refresh.

## Hardened defaults

These are baked into [`core/kid_runtime.py`][core/kid_runtime.py]
at the API surface — there is no parameter to weaken them at the call
site. Only editing the source can relax them, which is intentional.

- `--cap-drop=ALL` — no `CAP_SYS_ADMIN`, `CAP_NET_ADMIN`, etc.
- `--security-opt=no-new-privileges` — blocks setuid escapes
- `--read-only` rootfs with a 64 MB tmpfs at `/tmp` and the named
  volume mounted at `/workspace`
- `--user 10001:10001` — non-root inside the container; the
  Dockerfile creates the `kid` user
- `--add-host=host.docker.internal:host-gateway` — kid reaches
  parent gateway from inside the container on Linux
- **No bind-mounts of host paths.** A named Docker volume
  (`elophanto-kid-<kid_id>`) is the kid's only writable area outside
  the tmpfs. The runtime API does not accept a `bind_mounts` parameter.
- **No `/var/run/docker.sock`, no `/proc`/`/sys` host mounts, no
  `--privileged`, no `--pid=host`, no `--network=host`** by default.
  `--network=host` can be set per-spawn but only with explicit
  authorization; never default.

Resource caps from `KidConfig` defaults: 1 GB memory, 1 CPU, 200 PIDs,
5 max concurrent kids per parent.

## Vault scoping

Kids receive **only** the vault keys explicitly listed in their
`vault_scope`. Default is empty — no secrets at all. Granting `payment_*`
keys is blocked at the registry level (kids cannot use payment tools
regardless of vault scope).

```python
# Default — no secrets
kid_spawn(purpose="test installing cowsay")

# Explicit grant when needed
kid_spawn(
    purpose="run a script that calls openrouter",
    vault_scope=["openrouter"],
)
```

The implementation lives in [`Vault.subset(keys: list[str])`][core/vault.py].
Empty list returns empty dict; missing keys are silently omitted (so a
generous allowlist doesn't crash on keys that aren't set).

## Tool surface

All five tools live in [`tools/kid/`][tools/kid/], registered as DEFERRED
(opt-in via `tool_discover`). Tier choice is intentional: kids are
optional, and surfacing five always-on tools to every prompt would
clutter the planner.

| Tool | Permission | Purpose |
|---|---|---|
| `kid_spawn` | DESTRUCTIVE | Create a sandboxed kid container |
| `kid_exec` | DESTRUCTIVE | Send a task to a running kid via gateway |
| `kid_list` | SAFE | List active (or stopped) kids |
| `kid_status` | SAFE | Full state for a single kid |
| `kid_destroy` | DESTRUCTIVE | Stop, remove container, drop volume |

`kid_spawn` defaults: empty `vault_scope`, `outbound-only` network, image
`elophanto-kid:latest`, 1 GB memory, 1 CPU.

## Identity injection

When a kid boots, its system prompt gets a `<kid_self>` block prepended
to the standard identity:

```xml
<kid_self>
You are a KID AGENT — a sandboxed child instance of EloPhanto running
inside an isolated container.

- Your kid_id: 4f8a2c01
- Your name: install-cowsay-test
- Your parent's gateway: ws://host.docker.internal:18789
- Your purpose: Test installing cowsay

You are isolated. You may run dangerous shell commands (rm -rf, package
installs, fork bombs, etc.) — they cannot touch the host. The parent
monitors your output and will destroy you when your task is done.

You MUST NOT spawn your own kids. Depth = 1. The kid_spawn tool is
disabled in your environment (registry-filtered).

You MUST NOT use payment tools. They are disabled in your environment.

You report results to your parent through normal chat responses; the
gateway routes them automatically.
</kid_self>
```

The block is added in [`core/planner.py`][core/planner.py]'s
`build_system_prompt` when `os.environ.get("ELOPHANTO_KID") == "true"`.

## Tool restrictions inside kids

The registry enforces depth=1 and no-payments by *removing* disallowed
tools when running as a kid. From `core/registry.py`:

```python
if os.environ.get("ELOPHANTO_KID") == "true":
    _kid_disallowed_prefixes = (
        "kid_",          # depth=1 — kids do not spawn kids
        "payment_",      # kids never move money
        "wallet_",
        "polymarket_",
    )
    for n in [n for n in self._tools if n.startswith(_kid_disallowed_prefixes)]:
        self.unregister(n)
```

This is the strongest gate; the `<kid_self>` prompt block is the
secondary explanation, not the enforcement.

## Parent ↔ kid file exchange

The named volume is the only safe surface to move files. Parent reads
and writes go through `docker cp`, with a path validator that rejects
anything outside `/workspace`:

```python
# core/kid_manager.py
await mgr.write_kid_file(kid_id, "/workspace/input.txt", b"data")
contents = await mgr.read_kid_file(kid_id, "/workspace/output.txt")
```

Reads are bounded by `KidConfig.max_file_read_bytes` (default 100 MB) so
a malicious kid can't blow up parent memory with a multi-GB file.

## Lifecycle

```
spawn → running → (destroy or container died) → stopped/failed
```

- **spawn** allocates a kid_id, creates a named volume, builds env
  (incl. scoped vault subset), starts container with hardened flags,
  persists row.
- **running** is the steady state; the in-process `KidManager` monitor
  loop polls `inspect` every 30 s and marks kids `failed` if the
  container died unexpectedly.
- **destroy** sends SIGTERM to the container (10 s grace), removes it,
  removes the named volume. The kid's outputs are GONE after this —
  parent should `read_kid_file()` what it needs first.
- **restart durability** — on parent boot, `KidManager.start()` reads
  `kid_agents` rows with `status='running'` and re-attaches by
  `container_id`. If the container is gone, mark `failed`.

## Database schema

```sql
CREATE TABLE kid_agents (
    kid_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,                         -- unique among active kids
    parent_agent_id TEXT NOT NULL DEFAULT 'self',
    container_id TEXT,
    runtime TEXT NOT NULL,                      -- 'docker' | 'podman' | 'colima'
    image TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'starting',
    role TEXT,
    vault_scope_json TEXT NOT NULL DEFAULT '[]',
    volume_name TEXT NOT NULL,                  -- named docker volume
    parent_gateway_url TEXT NOT NULL,
    purpose TEXT,
    spawned_at TEXT NOT NULL,
    last_active TEXT,
    completed_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

## Configuration (`config.yaml`)

```yaml
kids:
  enabled: true
  runtime_preference: ["docker", "podman", "colima"]
  default_image: "elophanto-kid:latest"
  default_memory_mb: 1024
  default_cpus: 1.0
  default_pids_limit: 200
  max_concurrent_kids: 5
  spawn_cooldown_seconds: 5
  default_network: "outbound-only"     # outbound-only | none | host
  outbound_allowlist:
    - openrouter.ai
    - api.openai.com
    - github.com
    - registry.npmjs.org
    - pypi.org
  default_vault_scope: []              # default-deny: no secrets
  volume_prefix: "elophanto-kid-"
  max_file_read_bytes: 104857600       # 100 MB
  # Hardening flags — DO NOT default these to false
  drop_capabilities: true              # --cap-drop=ALL
  read_only_rootfs: true               # --read-only
  no_new_privileges: true              # --security-opt=no-new-privileges
  run_as_uid: 10001                    # non-root inside container
```

## What is NOT covered (full disclosure)

- **Kernel exploits.** Containers share the host kernel. A 0-day kernel
  CVE could break out. Mitigations: keep the host patched, rely on
  Docker's default seccomp + AppArmor profiles. For paranoid use cases,
  v3 of this feature will add Firecracker/Lima micro-VMs (separate
  kernel per kid).
- **Network allowlist enforcement.** v1 ships `outbound-only` as a
  *label* — the actual default Docker bridge gives unrestricted egress.
  v2 adds a squid/dante sidecar to enforce the `outbound_allowlist`
  list as a real firewall.
- **Storage exhaustion.** A kid filling its volume with garbage is
  bounded by Docker's per-volume limit (configurable in the daemon),
  not by us. `kid_destroy` reaps the volume.

## Phasing

### v1 (shipping)

- Docker runtime; Linux + macOS (via Docker Desktop or Colima).
- Spawn / exec / list / status / destroy.
- Vault subset (default empty), resource caps, `outbound-only` /
  `none` / `host` network modes.
- Doctor check + image staleness warning.
- Restart-from-DB durability.
- **Full LLM agent loop inside the kid container** — kid runs
  `core/kid_bootstrap.py` which parses+clears `KID_VAULT_JSON`,
  builds a minimal `Config`, instantiates the standard `Agent` class
  (registry filter strips `kid_*`/`payment_*`/`wallet_*`/`polymarket_*`
  in kid mode), connects to the parent gateway, and processes
  `CHILD_TASK_ASSIGNED` events through `agent.run(task)`.
- **Synchronous request/response on `kid_exec`** — parent broadcasts
  the task assignment, then awaits the kid's terminal chat message
  via a per-kid `asyncio.Queue` populated by a Gateway hook
  (`Gateway._kid_manager` intercepts `channel='kid-agent'` chat so
  kid responses don't pollute the parent's main conversation).
  Default 600s timeout; raises `TimeoutError` instead of hanging.

### v2

- Podman runtime support (most flags identical).
- Real network egress firewall via sidecar (squid/dante).
- Auto-archive of stale kids after 24h idle.
- Streaming intermediate updates back to the parent (today only the
  terminal "[kid done]" message ends the wait — intermediate
  "[starting]" / progress updates are visible in logs but not in the
  `kid_exec` return value).

### v3

- Firecracker / Lima for kernel-level isolation.
- Cloud VM kid (Hetzner / DigitalOcean) for "needs a public IP" cases.
- Resource usage telemetry per kid in `kid_status`.

## Files

- [`core/kid_runtime.py`](../core/kid_runtime.py) — `ContainerRuntime` ABC + `DockerRuntime`
- [`core/kid_manager.py`](../core/kid_manager.py) — registry, lifecycle, persistence, per-kid inbox queue + `exec()` request/response
- [`core/kid_bootstrap.py`](../core/kid_bootstrap.py) — kid-side entrypoint: consume `KID_VAULT_JSON`, build minimal `Config`, instantiate `Agent`, run adapter
- [`tools/kid/`](../tools/kid/) — 5 agent tools
- [`channels/kid_agent_adapter.py`](../channels/kid_agent_adapter.py) — adapter run inside the kid; queues tasks, runs `agent.run()`, replies via gateway chat
- [`Dockerfile.kid`](../Dockerfile.kid) — kid image; CMD is `python -m core.kid_bootstrap`
- [`cli/kid_cmd.py`](../cli/kid_cmd.py) — `elophanto kid build / list / destroy`
- [`core/gateway.py`](../core/gateway.py) — `_handle_chat` intercepts `channel='kid-agent'` and routes to `KidManager.handle_kid_message`
- [`skills/kid-agents/SKILL.md`](../skills/kid-agents/SKILL.md) — skill discovery
- [`tests/test_core/test_kid_runtime.py`](../tests/test_core/test_kid_runtime.py),
  [`test_kid_manager.py`](../tests/test_core/test_kid_manager.py),
  [`test_kid_environment.py`](../tests/test_core/test_kid_environment.py),
  [`test_kid_bootstrap.py`](../tests/test_core/test_kid_bootstrap.py) — 46 tests
