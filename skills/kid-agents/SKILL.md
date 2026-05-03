---
name: kid-agents
description: Use when running dangerous shell commands, installing untrusted packages, or testing untrusted code that could damage the host. Spawns a sandboxed kid (a child EloPhanto inside a hardened container) where rm -rf, fork bombs, kernel-touching ops, and similar are safely contained. Default vault scope is empty; default network is outbound-only. Distinct from organization specialists — kids are ephemeral, identity-less, and disposable.
---

## Triggers

- test this command in a sandbox
- run this safely
- run untrusted code
- try installing this
- spawn a kid
- spawn a sandbox
- test in container
- run dangerous command
- install and see what happens
- try this without breaking my machine
- isolate this
- run this in a kid

# Kid agents — sandboxed disposable children

## Overview

A kid is a child EloPhanto running inside a hardened Docker container.
It exists to do things that are too dangerous to run on the host:
package installs, untrusted scripts, fork bombs, kernel-poking, code
you don't fully trust. The container's `--cap-drop=ALL`, read-only
rootfs, non-root uid, named-volume-only writable area, and resource
caps mean a kid that goes rogue can damage only itself.

Kids are NOT organization specialists. Kids are short-lived, have no
durable identity, and connect back to the parent's gateway as a
client. Specialists are persistent peers with their own gateway and
trust score. **If the user wants long-lived expertise, use
`organization_spawn`. If the user wants disposable safe testing, use
`kid_spawn`.**

## Iron rules

1. **Default vault scope is empty.** A kid gets zero secrets unless
   you explicitly grant keys. Don't grant `payment_*` ever — kids
   never move money (the registry blocks it anyway).
2. **Default network is outbound-only.** `network="host"` requires
   explicit user authorization in the same turn. Don't assume.
3. **Always destroy when done.** Idle kids consume the concurrency
   budget. After reading anything you need, call `kid_destroy`.
4. **Always check `kid_list` before spawning.** A live kid set up for
   the same task is cheaper than a fresh one.
5. **Never use a kid for tasks that need host filesystem state.**
   Kids are isolated. They can't see your files unless you `cp` them
   in.

## Phase 1 — decide if a kid is the right tool

Use a kid when **any** of these is true:

- The command could damage the host: `rm -rf`, `dd`, system installs,
  kernel modules, iptables.
- The code's provenance is uncertain: random GitHub gists, scraped
  scripts, AI-generated install instructions.
- The work is one-shot and doesn't need durable identity.

Don't use a kid when:

- Long-lived domain expertise is needed → `organization_spawn`.
- The task is pure code review or static analysis → your existing
  tools (no isolation needed; you're just reading).
- The task needs the host's filesystem, browser session, or payment
  tools.

## Phase 2 — spawn

Minimal:
```
kid_spawn(purpose="test installing cowsay")
```

With a clear name (so future iterations can find it):
```
kid_spawn(purpose="test installing cowsay", name="cowsay-test")
```

With explicit vault scope (only when the kid genuinely needs secrets):
```
kid_spawn(
    purpose="run a script that calls openrouter",
    vault_scope=["openrouter"],
)
```

Network policies:
- `outbound-only` (default): allowed for normal tasks.
- `none`: air-gapped — use for hostile-by-assumption code.
- `host`: full host network — REQUIRES explicit user authorization.

## Phase 3 — execute

```
kid_exec(kid_id_or_name="cowsay-test", task="apt install cowsay && cowsay hello")
```

The kid runs the task inside its container. Output comes back via the
gateway. Watch the kid's chat events.

## Phase 4 — read outputs (optional)

If the kid wrote artifacts, fetch them BEFORE destroy:

The parent-side helper `read_kid_file(kid, "/workspace/result.json")`
copies the file out via `docker cp`. Path traversal is blocked by the
runtime — only `/workspace/...` reads are allowed.

## Phase 5 — destroy

Always:
```
kid_destroy(kid_id_or_name="cowsay-test", reason="task complete")
```

This stops the container, removes it, and drops the named volume.
The kid's outputs are GONE after this.

## Failure modes / when to refuse

- **No container runtime installed.** Tool returns an error pointing
  at the install command for the user's OS. Don't try to work around
  it; tell the user to run the suggested command.
- **Kid image not built.** Run `elophanto kid build` once. Doctor
  warns when the image is older than the codebase.
- **User asks for `network=host`** without saying why. Push back:
  default network is enough for almost all dangerous-command testing.
- **User wants to grant `payment_*` to a kid.** Refuse — kids never
  move money. Use the parent agent for payment work.
- **User wants the kid to spawn its own kids.** Refuse — depth is 1
  by design. The kid_spawn tool is registry-filtered out inside kids.

## Reputation tracking

`learned/kids/{date}-{purpose-slug}.md` for any kid whose run
produced lessons (working install commands, broken patterns, useful
sandbox configurations). Skip the log for trivial single-command
tests.

## Verify

- The intended other agent / tool / channel actually received the message; an ack, message ID, or response payload is captured
- Identity, scopes, and permissions used by the call were the minimum required; over-permissioned tokens are called out
- Failure handling was exercised: at least one retry/timeout/permission-denied path is shown to behave as designed
- Hand-off context passed to the next actor is complete enough that the receiver could act without a follow-up question
- Any state mutated (config, memory, queue, file) is listed with before/after values, not just 'updated'
- Sensitive material (keys, tokens, PII) was redacted from logs/transcripts shared in the verification evidence

## Anti-patterns

- **Forgetting to destroy.** Idle kids waste concurrency. Hard rule:
  destroy in the same turn as the final read, unless the user wants
  to keep iterating.
- **Granting secrets "just in case".** Empty scope is the default.
  If the kid needs `openrouter`, grant ONLY `openrouter`.
- **Using a kid for tasks the parent could do.** If `shell_execute`
  on the host is safe, do it on the host. Kids are for the unsafe
  path.
- **Reusing a kid for unrelated work.** Spawn a fresh kid per task
  domain — the cost is small and the isolation is per-kid.
