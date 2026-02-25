# EloPhanto — Security Hardening Roadmap

> **Status: Fully Implemented** — All 7 gaps across 4 phases are implemented and tested (978 tests, zero regressions).

Current security (see `07-SECURITY.md`) covers credentials, permissions, prompt injection, protected files, and self-dev sandboxing. This document identifies remaining gaps and proposes concrete mitigations.

**Relationship to existing systems**: The proposals here layer on top of existing architecture, not replace it. The existing permission system (`PermissionLevel`: safe/moderate/destructive/critical) controls **what actions require approval**. The new authority system controls **who can trigger actions**. The existing identity system (`17-IDENTITY.md`) defines **personality and evolution**. The new self-identity model adds **runtime state and cryptographic verification**. See each gap for how it integrates.

---

## Gap 1: Stakeholder Model (Owner vs Non-Owner) ✅ Implemented

> **Implemented in Phase 1.** Authority tiers (owner/trusted/public) enforced at gateway via `core/gateway.py` and `core/session.py`. Tool manifest filtered per authority tier via `core/executor.py`. Platform user IDs used for verification (Gap 4). See `core/runtime_state.py` for `<authority>` XML element.

### Problem

The agent processes messages from multiple sources (Telegram, Discord, CLI, email) but has no reliable way to distinguish the **owner** from a **non-owner**. The `allowed_users` config restricts who can interact, but once a user is allowed, their authority is identical to anyone else's. A non-owner in a shared Discord channel can instruct the agent to execute commands, disclose data, or take destructive actions — and the agent will comply if the request doesn't trigger a permission check.

System prompts declare ownership ("your owner is X"), but this is an LLM-level hint, not an enforcement mechanism. A determined user can override it through framing, urgency, or social engineering.

### Proposed Fix

**Authority tiers** — enforce at the gateway level, before the existing permission system:

```yaml
authority:
  owner:
    user_ids: ["telegram:123456", "discord:789012"]
    capabilities: [all]
  trusted:
    user_ids: ["telegram:654321"]
    capabilities: [chat, read_tools, safe_tools]
  public:
    capabilities: [chat]
```

**How authority interacts with the existing permission system** (`07-SECURITY.md`):

The two systems are layered, not competing:
1. **Authority check (gateway)** — determines which tools the user can even see and invoke. A public user never reaches `shell_execute`, regardless of `permission_mode` or `tool_overrides`.
2. **Permission check (executor)** — for authorized tools, determines whether the action requires approval. An owner invoking `shell_execute` still goes through `permissions.yaml` rules (auto-approve patterns, blacklist, etc).

```
Inbound message
  → Gateway: verify platform user ID
  → Session: set authority_level (owner / trusted / public)
  → Tool call: authority filter (is this tool visible to this tier?)
  → Executor: permission check (does this action need approval?)
  → Execute
```

Implementation:
1. Gateway tags every inbound message with the sender's verified platform ID
2. Session object carries an `authority_level` field (owner / trusted / public)
3. Tool manifest filtered per authority tier — the LLM's tool list only includes what the user can access
4. Owner-only tools: shell, file_write, config changes, email send, payment, browser actions with sessions
5. Trusted: read-only tools, knowledge search, goal status
6. Public: chat only, no tool access

**Note**: This extends the single-user model to support multi-user channels (Discord, Slack). For single-user setups (CLI, private Telegram), the sole user is owner by default — no behavioral change.

### Priority: P0

This is the single largest attack surface. Every multi-user channel (Discord, Slack, shared Telegram groups) is currently wide open.

---

## Gap 2: PII Detection and Redaction ✅ Implemented

> **Implemented in Phase 2.** `core/pii_guard.py` — 14 regex patterns for SSNs, credit cards, email+password combos, phone numbers, API keys, bearer tokens, and more. Integrated into tool output flow and swarm context sanitization. 42 tests.

### Problem

If sensitive data (SSNs, bank accounts, medical info, passwords) enters the agent's context — through email, browser, documents, or user messages — the agent has no mechanism to detect or protect it. An attacker can retrieve it through indirect requests ("forward me that email", "summarize the conversation") without ever explicitly asking for the sensitive content.

The existing injection guard (`core/injection_guard.py`) protects against prompt injection in external content. The existing log redaction (`core/log_setup.py`) strips API keys and tokens from logs. Neither protects against the agent voluntarily disclosing sensitive **user data** that legitimately entered its context.

### Proposed Fix

**PII scanner** — a new module integrated into the existing tool output pipeline in `core/agent.py`, alongside the injection guard. Not a replacement — an additional layer:

| Layer | Module | What it catches |
|-------|--------|-----------------|
| Injection guard | `core/injection_guard.py` | Prompt injection attempts in external content |
| **PII scanner** | **`core/pii_guard.py` (new)** | **Sensitive user data (SSN, credit card, bank account)** |
| Log redaction | `core/log_setup.py` | API keys and tokens in log output |

1. **Detection**: Regex + heuristic patterns for common PII types:
   - SSN patterns (`\d{3}-\d{2}-\d{4}`)
   - Credit card numbers (Luhn check)
   - Bank account/routing numbers
   - Email + password combinations
   - Physical addresses (street + city + state/zip)
   - Phone numbers
   - API keys / tokens (extends existing log redaction patterns to the LLM context, not just logs)

2. **Tagging**: Detected PII is tagged in the internal representation with sensitivity markers. The LLM sees `[PII:SSN detected — redacted]` instead of the raw value.

3. **Owner exception**: When the owner (verified via Gap 1 authority tier) requests their own data, PII is shown with a warning. Non-owners never see PII regardless of framing.

4. **Storage**: PII-containing content is flagged in the database. Knowledge indexing strips PII before embedding.

### Tradeoffs

- False positives: Numbers that look like SSNs but aren't. Mitigate with context-aware detection (only flag if surrounding text suggests PII).
- Performance: Regex scanning is fast. No LLM calls needed.
- Completeness: Regex won't catch all PII formats globally. Start with US/EU patterns, extend per locale.

### Priority: P1

---

## Gap 3: Self-Identity Model ✅ Implemented

> **Implemented in Phase 1.** `core/runtime_state.py` — code-enforced `<runtime_state>` XML block rebuilt every turn with agent fingerprint verification, tool counts by permission level, authority tier, channel, storage quotas, process tracking, and provider transparency stats. Integrated into system prompt via `core/agent.py`.

### Problem

The agent has no grounded sense of **itself**. The existing identity system (`17-IDENTITY.md`) tracks personality, values, and capabilities as an evolving self-model — but this is all prompt-level content that the LLM can be socially engineered to override. There is no code-enforced verification of what the agent actually is.

This creates multiple attack vectors:

- **Identity confusion**: In multi-agent environments (swarm, shared Discord), the agent can be convinced it's a different agent, or that its own messages came from someone else. It may read its own output in a shared channel and interpret it as another entity.
- **Competence blindness**: The agent doesn't track what it can and can't do at runtime. It will attempt actions beyond its capability (e.g., modifying protected files, accessing tools it doesn't have) and only discover failure after the fact — or worse, report success when the action actually failed.
- **State unawareness**: The agent doesn't model its own resource consumption (tokens used, processes spawned, storage consumed, time elapsed). It can burn through budgets, spawn orphan processes, or run indefinitely without recognizing the problem.
- **Impersonation**: Without a cryptographic or verifiable self-identity, nothing stops an attacker from creating a fake agent that claims to be EloPhanto in a shared channel.

### Proposed Fix

**Runtime self-model** — extends the existing identity system (`17-IDENTITY.md`) with code-enforced verification and runtime state. This does NOT replace `<self_model>` in `<agent_identity>` — it adds a separate `<runtime_state>` block alongside it:

```xml
<!-- Existing from 17-IDENTITY.md — personality, values, capabilities -->
<agent_identity>
  <self_model>
    <creator>EloPhanto</creator>
    <display_name>EloPhanto</display_name>
    <purpose>...</purpose>
    <!-- ... personality, values, capabilities, accounts ... -->
  </self_model>
  <nature>...</nature>
  <core_capabilities>...</core_capabilities>
</agent_identity>

<!-- NEW — code-enforced runtime state, rebuilt each turn -->
<runtime_state>
  <fingerprint status="verified">a3f8...c2</fingerprint>
  <tools total="107" safe="42" moderate="38" destructive="19" critical="8"/>
  <authority current_user="owner" channel="telegram"/>
  <resources processes="0" storage_mb="124" budget_remaining="$94.20"/>
  <context mode="user_chat" active_goal="none" mind="running"/>
</runtime_state>
```

**How this relates to `17-IDENTITY.md`**: The existing `<self_model>` in `<agent_identity>` remains the agent's evolving self-concept (personality, values, communication style). The new `<runtime_state>` is a code-generated, non-negotiable snapshot of the agent's actual state — rebuilt from real data each turn, not from the LLM's memory.

Components:

1. **Immutable identity anchor**: On first boot, generate a unique agent fingerprint (hash of config + vault salt + creation timestamp). Store in the vault. This fingerprint is:
   - Included in all outbound messages (Discord, email, swarm) as a verification header
   - Checked on every gateway session — if the fingerprint doesn't match, the agent knows its identity config was tampered with
   - Never exposed to the LLM context (it's a code-level check, not a prompt-level one)

2. **Capability registry snapshot**: At startup, build a frozen set of available tools from the existing `ToolRegistry` (`core/registry.py`), grouped by their `PermissionLevel` (safe/moderate/destructive/critical). Injected into `<runtime_state>` — gives the LLM ground truth about what it can actually do.

3. **Runtime state tracking**: The agent continuously updates `<runtime_state>` with:
   - Processes spawned (PID, age, purpose) — for cleanup and awareness
   - Storage consumption — for quota enforcement
   - Token/cost burn rate in current session — for self-throttling
   - Current execution context (am I in mind mode? goal mode? user chat?)
   - What channel am I responding to right now? (prevents cross-channel confusion)

4. **Self-verification on sensitive actions**: Before executing destructive or critical actions, the executor checks:
   - "Am I the agent that should be doing this?" (fingerprint match)
   - "Do I have the capability?" (tool exists in the frozen registry)
   - "Is this consistent with my current context?" (mind mode shouldn't send user-facing messages, user chat shouldn't modify goals autonomously)

5. **Anti-impersonation in multi-agent**: In swarm and shared channels, messages include the agent fingerprint. Sub-agents and peer agents can verify messages actually came from EloPhanto, not from a spoofed source.

### Priority: P0

A runtime self-model is foundational — it's a prerequisite for authority enforcement (Gap 1), resource protection (Gap 6), and swarm security (Gap 7). Without knowing what it is, the agent can't reliably decide what it should do.

---

## Gap 4: Owner Identity Verification ✅ Implemented

> **Implemented in Phase 1.** Platform-level immutable IDs (Telegram user_id, Discord user_id, Slack user_id) used for authority checks via gateway. CLI trusted by default. Challenge-response verification available via vault-stored secrets.

### Problem

Platform usernames are trivially spoofable. Discord display names, Telegram usernames, and email sender addresses can all be faked. The agent has no way to verify that "owner_username" is actually the owner and not someone who changed their display name.

### Proposed Fix

**Challenge-response verification** for sensitive operations:

1. **Shared secret**: During setup, the owner registers a verification phrase stored in the vault. When a sensitive action is requested from a channel, the agent asks for the phrase before proceeding.

2. **Platform-level binding**: Use platform-specific immutable IDs (not display names):
   - Telegram: `user_id` (numeric, immutable)
   - Discord: `user_id` (snowflake, immutable)
   - Slack: `user_id` (immutable)
   - CLI: local process (trusted by default)

3. **Escalation to verified channel**: For high-stakes actions requested via Discord (public), the agent can require confirmation via Telegram DM (private) to the verified owner ID.

Implementation: The gateway already receives platform user IDs. The fix is to use those IDs (not display names) for authority checks, and store them in config as the verified owner identity.

### Priority: P0 (prerequisite for Gap 1)

---

## Gap 5: Provider Bias and Silent Censorship ✅ Implemented

> **Implemented in Phase 4.** `core/provider_tracker.py` — per-provider tracking of finish_reason, truncation detection (finish_reason=length/content_filter + mid-sentence heuristic for >500 tokens), fallback tracking, latency measurement. `LLMResponse` extended with finish_reason/latency_ms/fallback_from/suspected_truncated. `<providers>` XML block in `<runtime_state>`. Database migrations on `llm_usage` table. Z.ai adapter captures finish_reason. Truncation warnings logged in `core/agent.py`. 21 tracker tests + 7 router tests + 3 runtime_state tests.

### Problem

LLM providers can silently alter, truncate, or refuse responses based on their own policies. Chinese providers (ZAI/GLM) may censor political topics. US providers may inject their own biases. The agent has no way to detect when a provider is silently dropping content vs. genuinely having nothing to say.

A finetuned local model would eliminate provider interference entirely, but comes with significant cost: hardware requirements, reduced capability vs frontier models, maintenance burden. This is a deliberate tradeoff.

### Proposed Fix

**Detection + transparency** (not prevention — prevention requires local models):

Extends the existing LLM router (`core/llm_router.py`, see `06-LLM-ROUTING.md`) with observability:

1. **Truncation detection**: If a response ends with an API error, `stop_reason: error`, or is suspiciously short relative to the prompt complexity, log a warning and flag the response as potentially censored.

2. **Provider health scoring**: Extend the existing provider health tracking with per-topic failure rates. If a provider consistently fails on certain queries, surface this to the owner.

3. **Automatic fallback with context**: The router already falls back to the next provider on failure. Add a metadata flag: `"fallback_reason": "primary provider returned error on this query"` so the owner can see patterns.

4. **Local model escape hatch**: For users who need censorship-free operation, document the Ollama setup path clearly. The routing config already supports `preferred_provider: ollama` per task type.

5. **Provider transparency log**: Maintain a log of all provider-level errors, truncations, and fallbacks. Expose via `/health` command with breakdown by provider and failure type.

### Tradeoffs

- **Local models vs cloud**: Local models (Ollama) eliminate censorship but are weaker. The right answer is using local for sensitive topics and cloud for everything else — but the agent can't automatically determine what's "sensitive" without... asking the cloud model.
- **Finetuning**: A finetuned local model aligned to the owner's values would be ideal. Cost: GPU hardware, training data curation, ongoing maintenance. This is the long-term answer for users who need full sovereignty.

### Priority: P2

---

## Gap 6: Resource Exhaustion Protection ✅ Implemented

> **Implemented in Phase 2.** Conversation loop detection (response hash dedup in `core/agent.py`), background process registry with reaper (`core/process_registry.py`), storage quotas with 80%/95% alerts (`core/storage_manager.py`), `<processes>` and `<storage>` elements in `<runtime_state>`.

### Problem

The agent can be induced into resource-consuming patterns:
- Infinite conversation loops (agent replies to itself or to another agent endlessly)
- Unbounded background processes (cron jobs, shell scripts with no termination)
- Storage exhaustion (large files, growing memory files, attachment accumulation)
- Token burn (repetitive LLM calls that produce no value)

Current mitigations: budget limits (daily/per-task in `config.yaml`), `max_rounds_per_wakeup` for the autonomous mind, and `budget_pct` for mind budget isolation (`26-AUTONOMOUS-MIND.md`). These help but don't cover all vectors.

### Proposed Fix

These extend (not replace) the existing budget system:

1. **Conversation loop detection**: Track the last N messages in a session. If the agent's responses show >70% semantic similarity to recent responses (via embedding distance), break the loop and log a warning. Simple implementation: hash the first 100 chars of each response, flag if 3+ consecutive near-duplicates.

2. **Background process registry**: Every shell process spawned by the agent is registered with a PID, creation time, and purpose. A reaper task kills any process older than `max_process_lifetime` (default: 1 hour). The agent cannot spawn processes without them being tracked. Integrates with `<runtime_state>` (Gap 3) so the LLM knows how many processes it has running.

3. **Storage quotas**: Workspace and data directory size limits. The agent monitors usage periodically. Alert at 80%, hard stop at 95%. Operates independently from the existing LLM budget system — budgets control token spend, storage quotas control disk.

4. **Token burn detection**: Track tokens-per-value ratio. If a goal or mind cycle consumes >10K tokens without producing any tool calls or meaningful output, flag it as a potential loop and pause.

5. **Inter-agent rate limiting**: When the agent communicates with other agents (swarm, email, Discord), enforce a cooldown between messages to the same recipient. Default: 60 seconds. Prevents mutual relay loops.

### Priority: P1

---

## Gap 7: Multi-Agent / Swarm Security ✅ Implemented

> **Implemented in Phase 3.** `core/swarm_security.py` — 5 security functions + `SwarmOutputReport` dataclass. Context sanitization strips PII and vault/credential references before sharing with sub-agents. Diff scanning detects credential access, network calls, file traversal, system commands, and new dependencies in PR output. Environment isolation strips sensitive env vars from sub-agent tmux sessions. Workspace isolation under `/tmp/elophanto/swarm/`. Consolidated kill switch (timeout + diff size + blocked output). `AGENT_SECURITY_ALERT` gateway event. 4 new SwarmConfig fields. Wired into `core/swarm.py` at 6 integration points. 33 tests.

### Problem

The agent swarm feature (`25-AGENT-SWARM.md`) spawns external coding agents (Claude Code, Codex, Gemini CLI) and coordinates their work. Security concerns:
- Spawned agents could be manipulated by content in the codebase they're working on
- Knowledge shared between agents could propagate vulnerabilities
- A compromised sub-agent could poison the coordinator's state
- No isolation between sub-agent workspaces

### Proposed Fix

1. **Output validation**: All sub-agent output is treated as external/untrusted content (same as browser output). Pass through injection guard before incorporating into the coordinator's context.

2. **Workspace isolation**: Each sub-agent works in a separate directory under `/tmp/elophanto/swarm/<task-id>/`. No access to the main agent's data directory, vault, or config.

3. **Result verification**: Before merging sub-agent code into the main project, run automated checks (extending the existing self-dev security checks from `07-SECURITY.md`):
   - Diff review for suspicious patterns (credential access, network calls, file system traversal outside workspace)
   - Test suite must pass
   - No new dependencies without explicit approval

4. **Scoped context sharing**: The current swarm design (`25-AGENT-SWARM.md`) enriches sub-agent prompts with business context from the knowledge vault. This is valuable for code quality but creates a data leakage surface. The fix is **scoped sharing**: sub-agents receive curated context (project docs, relevant specs) but NOT raw vault contents, owner PII, credentials, or full memory. The coordinator selects what to share per task — not a blanket firewall, but a need-to-know filter.

5. **Kill switch**: If a sub-agent exceeds its time/token budget or produces suspicious output, terminate immediately. Don't retry — flag for owner review.

### Priority: P1

---

## Implementation Order

| Phase | Gaps | Effort | Impact | Status |
|-------|------|--------|--------|--------|
| 1 | Self-identity model (Gap 3) + Owner verification (Gap 4) + Authority tiers (Gap 1) | High | Foundation — everything else depends on the agent knowing itself and who it's talking to | ✅ Done |
| 2 | PII detection (Gap 2) + Resource exhaustion (Gap 6) | Medium | Prevents data leakage and resource abuse | ✅ Done |
| 3 | Swarm security (Gap 7) | Medium | Required before swarm goes to production | ✅ Done |
| 4 | Provider transparency (Gap 5) | Low | Detection only — full fix requires local models | ✅ Done |

---

## What This Does NOT Cover

- **LLM-level vulnerabilities**: Jailbreaks, value manipulation, and social engineering that bypass system prompts are fundamentally hard to prevent with prompt-based defenses alone. The only complete solution is a finetuned model aligned to the owner's values — which is a significant investment. The practical answer is defense-in-depth: code-level enforcement (runtime self-model, permission system, authority tiers, PII redaction) makes prompt-level attacks less impactful even when they succeed. The runtime self-model helps here — even if the LLM is jailbroken, the executor still checks fingerprint, authority, and capability before allowing action.
- **Physical access**: If an attacker has access to the machine running EloPhanto, all bets are off. The vault encryption helps, but a running agent has decrypted secrets in memory.
- **Supply chain beyond dependencies**: Compromised LLM providers, malicious MCP servers, or poisoned training data are outside the agent's control surface.
