# 84 — The Action Layer

*Authenticated HTTP, the credential broker, and the self-owned-scope guard.*

Status: shipped 2026-08-10.

## Why

EloPhanto could already *reach* the world: a real Chrome profile with the
operator's logged-in sessions, a shell, an MCP client. What it could not do
was the plainest thing an assistant does — call an API as you.

The workarounds each broke something:

- **Browser automation** works, but it drives a UI built for humans. Slow,
  brittle against a redesign, and hopeless for anything without a web front end.
- **`curl` via `shell_execute`** puts the secret on a command line, which means
  in the process table, in the shell history, and in the transcript the model
  reads back.
- **Standing up an MCP server** per service is a lot of ceremony for one POST.

So the gap was never "can it act" — it was "can it act *authenticated*, without
the secret passing through the model". That is what this layer adds.

It also adds the thing that has to come with it. An agent holding your
credentials can reach endpoints that are not yours to change, and no amount of
*caller* authentication distinguishes those cases: "cancel my booking" and
"cancel someone else's" are the same shape of request. The scope guard is the
axis that tells them apart.

## The three layers

Every `http_request` passes through all three, in this order, before a socket
opens.

### 1. Network policy — `core/net_policy.py`

Blocks loopback, RFC1918, link-local (including `169.254.169.254`, the cloud
metadata endpoint), CGNAT, multicast, and the IPv6 equivalents. Resolves
hostnames before deciding, so `evil.example → 127.0.0.1` is caught, and unwraps
IPv4-mapped / 6to4 / NAT64 addresses so the same target cannot be smuggled
through a different encoding.

Redirects are followed **by hand**, re-validating every hop — httpx's own
redirect handling would resolve the next hop without consulting policy, which is
exactly the hole an SSRF chain walks through. `Authorization` and `Cookie` are
dropped on cross-origin redirect.

Break-glass: `network.allow_hosts` for a specific internal host you mean to
reach; `network.allow_private_network` for the general case.

### 2. Scope guard — `core/scope_guard.py`

Classifies the *target*, crossed with how reversible the action is:

|                    | READ | WRITE | DESTRUCTIVE |
|--------------------|------|-------|-------------|
| **OWNED**          | run  | run   | ask         |
| **UNKNOWN**        | run  | ask   | **refuse**  |
| **THIRD_PARTY**    | run  | ask   | **refuse**  |
| *foreign account*  | run  | ask   | **refuse, no prompt** |

"Destructive" is not just `DELETE` — plenty of APIs delete via `POST`, so paths
containing `delete`, `revoke`, `ban`, `refund`, `transfer` and friends count too.
"Foreign account" is a path that addresses another person's record
(`/users/8813/…` rather than `/users/me/…`).

The bottom-right cell is the point of the module. It **refuses rather than
prompts**, because an approval dialog is not an authorization to destroy a third
party's data — approval fatigue makes "yes" the default answer and the blast
radius is someone else's account.

Ownership is declared, not guessed, in `data/owned_scope.yaml`. A documented
template ships as `owned_scope.demo.yaml` at the repo root — `data/` is
gitignored, so the live file never leaves your machine:

```bash
cp owned_scope.demo.yaml data/owned_scope.yaml
```

An absent or empty file is safe: nothing is owned, so every destructive
external call is refused. Start there and add hosts as you need them.

```yaml
owned:
  - api.mygym.example
  - "*.mycompany.com"
third_party:
  - api.competitor.example
authorizations:
  - target: staging.client.example
    scope: "GET,POST,DELETE /api/test-fixtures/*"
    authorized_by: "Jane Doe, CTO — contract #4417"
    expires: "2026-12-31"
```

`authorizations` is how legitimate authorized testing stays possible without
turning the guard off: record who authorized it and the agreed scope, and the
guard honours exactly that and nothing more. An expired or blank scope covers
nothing.

Manage it with `elophanto oauth scope --add-owned api.mygym.example`.

### 3. Credential broker — `core/credentials.py`

The model names a **slug**; it never sees a secret.

```
resolve(slug) → SecretString      # str()/repr() are redacted
issue_sentinel(secret) → «cred:ab12cd34»
materialize(obj)                  # called once, at the socket
redact(obj)                       # scrubs an echoed secret from the response
```

The sentinel is what travels through tool params, logs, and the transcript.
`materialize` runs at exactly one place per flow — building the request — and
the sentinel map is cleared when the call finishes.

Reference forms: `env:VAR`, `${VAR}`, `vault:key#field`, `file:/path#json.pointer`,
`oauth:provider`.

Policy is per-slug: `auto` (no prompt), `approve` (default), `deny`. A
`grant_ttl_seconds` turns one approval into a standing grant, so a six-call
booking flow prompts once. Every resolve — granted, denied, auto — writes to
`credential_audit` with the caller's stated `reason`. Values are never logged.

**No approval callback means no credential.** Failing closed is the only safe
default; silently granting would make the policy a lie.

> LLM provider keys are *not* part of this. They stay in `config.yaml` under
> `llm.providers` and are read by the router. This layer is for credentials the
> agent wields against third parties on the operator's behalf. Keeping the two
> separate is deliberate.

## Permission moves with the call

`http_request` is one tool spanning a wide risk range, so a single static tier
would either over-prompt on `GET` or under-gate `DELETE`. `BaseTool.dynamic_permission_level(params)`
lets a tool re-tier itself per call; the executor consults it first.

- `GET`/`HEAD`/`OPTIONS` → SAFE
- write to a declared-owned host → MODERATE
- foreign write → DESTRUCTIVE (asks)
- anything destructive → CRITICAL

The executor only honours a genuine `PermissionLevel` from that hook. Anything
else — a bug, a mock, a stale string — logs a warning and keeps the static tier,
so a classification defect cannot open a gate.

## A 200 with no answer is a failed call

When the response is an OpenAI-shaped chat completion whose content is empty,
`http_request` returns `success=False` and puts the reason and the fix in the
error. The body is still in `data`, so nothing is lost.

This exists because "the request worked" and "you got an answer" are different
questions, and only the first one has an HTTP status. Asked to prompt an
endpoint for an SVG (2026-08-15), the agent sent a correct request and got a
clean 200 containing 24,164 characters of reasoning, `content: null` and
`finish_reason: "length"` — the model had spent its whole 8,192-token budget
thinking and never started the answer. The agent reported "it did not return
actual SVG code" and stopped: honest, and useless. The response said exactly
what went wrong and exactly what to change, and none of it reached the agent
as something it had to act on.

The diagnosis distinguishes the causes, because the fixes differ:

| Response | Diagnosis | Fix offered |
|---|---|---|
| `finish_reason: length` + reasoning present | budget spent on reasoning | raise `max_tokens` 2-4x, or lower `reasoning_effort` |
| `finish_reason: length`, no reasoning | cut off before any content | raise `max_tokens` |
| `content_filter` / `refusal` | endpoint declined | rephrase, or report the refusal |
| empty content, reasoning present | answer missing, thinking present | retry; then inspect `message` keys for a non-standard field |

A short-but-present answer is never flagged — truncation is the caller's
judgement to make, not the tool's.

## Configuration

```yaml
credentials:
  default_mode: approve
  bindings:
    gym: "env:GYM_API_TOKEN"
    trello: "vault:trello#token"
    gcal: "oauth:google"
  policies:
    gym: {mode: approve, grant_ttl_seconds: 900}

scope:
  enabled: true
  foreign_write: ask       # allow | ask | deny
  foreign_destructive: deny
  owned_destructive: ask
  strict_unknown: false

network:
  allow_hosts: []
  deny_hosts: []
  allowlist_only: false
  allow_private_network: false
  max_redirects: 5
```

## Worked example — booking a gym class

```
http_request(
  method="POST",
  url="https://api.mygym.example/v1/bookings",
  credential="gym",
  json={"classId": "sp-2214"},
  reason="Book Tuesday 18:00 spin class as the operator asked"
)
```

1. Scope guard: `api.mygym.example` is declared owned, `POST` is a write → run.
2. Network policy: public host, https, no odd port → allowed.
3. Broker: policy is `approve` with a 15-minute grant → operator sees
   *"Use credential 'gym' … Reason: Book Tuesday 18:00 spin class"*, approves once.
4. Sentinel goes into the `Authorization` header; the real token is substituted
   as the request is built and dropped immediately after.
5. Response is scrubbed for any echoed secret before the model reads it.

Cancelling *your own* booking is the same flow with `DELETE`, which escalates to
CRITICAL and confirms. Deleting *someone else's* membership is refused at step 1
and never reaches the network — which is the whole design.

## Files

| Path | Role |
|---|---|
| `core/credentials.py` | Broker, `SecretString`, sentinels, audit |
| `core/scope_guard.py` | Target classification, authorizations, verdicts |
| `core/net_policy.py` | SSRF classification, allow/deny, URL validation |
| `tools/http/request_tool.py` | The `http_request` tool |
| `core/executor.py` | Consults `dynamic_permission_level` |
| `tools/base.py` | The `dynamic_permission_level` hook |
| `cli/oauth_cmd.py` | `elophanto oauth scope` |
| `data/owned_scope.yaml` | Operator's ownership declaration |

Tests: `tests/test_core/test_scope_guard.py`, `test_credentials.py`,
`test_net_policy.py`, `tests/test_tools/test_http_request.py`.
