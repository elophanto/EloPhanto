# 55 — Session Hardening

> **Status: Complete** — Context compression, memory injection scanning, user modeling, and skill capture nudge activation.

## Overview

Four improvements to session resilience, security, and personalization:

1. **Context Compression** — LLM-based mid-conversation summarization to prevent context overflow
2. **Memory Injection Scanning** — Block prompt injection via poisoned memories/knowledge
3. **User Modeling** — Build evolving user profiles from conversation observation
4. **Skill Capture Nudge** — Wire up existing nudge infrastructure to activate skill creation prompts

## 1. Context Compression

### Problem

Long conversations hit context limits. Current mitigations are destructive:
- Browser screenshots: keep last 3, placeholder the rest (`_compress_browser_context`)
- Emergency trim: strip ALL images, truncate tool results to 500 chars, keep last 20 messages (`_emergency_trim_messages`)
- Conversation history: hard FIFO cap at 20 messages (`_MAX_CONVERSATION_HISTORY`)

None of these **summarize** — they discard. The agent loses important context from earlier in the conversation.

### Solution

Add `ContextCompressor` that triggers at a configurable token threshold and replaces middle conversation turns with an LLM-generated summary.

**Algorithm:**
1. After each planning turn, estimate total message tokens
2. If tokens exceed `compression_threshold` (default: 50% of model context window), trigger compression
3. Protect first `keep_first` (3) and last `keep_last` (4) turns
4. Send middle turns to a cheap/fast model with a summarization prompt
5. Replace middle turns with a single summary message
6. Handle orphaned tool calls — if a tool_call message is removed but its result survives (or vice versa), insert a stub: `[Result from earlier — see summary above]`
7. Maintain proper role alternation after replacement

**Location:** `core/context_compressor.py` (new file)

**Integration:** Called from `core/agent.py` in the planning loop, after each LLM response, before the next turn.

**Config:**
```yaml
context_compression:
  enabled: true
  threshold_pct: 50          # Trigger at N% of context window
  keep_first: 3              # Protected early turns
  keep_last: 4               # Protected recent turns
  model: "fast"              # Task type for router (cheap model)
```

## 2. Memory Injection Scanning

### Problem

`core/injection_guard.py` has comprehensive injection patterns (9 categories) but is only applied to **external tool results** via `wrap_tool_result()`. Memory and knowledge writes are unscanned:

- `core/learner.py` — lessons written without injection scanning
- `tools/knowledge/writer.py` — knowledge writes unscanned
- `core/agent.py` — directive auto-detection stores unscanned content

A malicious or compromised input could persist prompt injection across sessions via the knowledge base.

### Solution

Apply `scan_for_injection()` at every persistence boundary:

| Write Path | File | Action |
|-----------|------|--------|
| Lesson extraction | `core/learner.py:_write_lesson()` | Scan before write, skip + log warning if flagged |
| Knowledge write tool | `tools/knowledge/writer.py:execute()` | Scan content, reject with explanation if flagged |
| Directive storage | `core/agent.py` directive block | Scan before knowledge_write call |

Additionally, add `redact_pii()` to `core/learner.py` which currently lacks it.

## 3. User Modeling

### Problem

EloPhanto builds a rich self-model (identity, beliefs, personality) but knows nothing structured about the **user**. Session metadata only stores `authority_level`. The agent can't adapt its communication style, technical depth, or workflow to individual users.

### Solution

Add a `UserProfile` system that observes conversations and builds evolving user profiles.

**Data model:**
```python
@dataclass
class UserProfile:
    user_id: str
    channel: str
    display_name: str = ""
    role: str = ""                    # "developer", "designer", "founder", etc.
    expertise: list[str] = []         # ["python", "solana", "react"]
    preferences: dict[str, str] = {}  # {"verbosity": "concise", "code_style": "functional"}
    observations: list[str] = []      # Free-form notes from conversation
    interaction_count: int = 0
    created_at: datetime
    updated_at: datetime
```

**Storage:** New `user_profiles` table in SQLite.

**Profile building:**
- After each completed task, fire-and-forget a cheap LLM call to extract user signals from the conversation
- Merge observations into the profile (deduplicate, update counts)
- Cap observations at 20 entries (LRU by relevance)

**Injection into system prompt:**
- Load user profile at task start (alongside identity context)
- Format as `<user_context>` XML block: role, expertise, preferences
- Frozen per session (same pattern as identity context)

**New tool:** `user_profile_view` (SAFE) — lets the agent check what it knows about the current user.

**Location:** `core/user_model.py` (new file), `tools/user/profile_tool.py` (new file)

## 4. Skill Capture Nudge Activation

### Problem

The nudge infrastructure exists in `core/planner.py` (lines 1631-1853):
- `_NUDGE_MEMORY` and `_NUDGE_SKILL` blocks defined
- `_build_nudge()` function counts tool calls and selects the right nudge
- `build_system_prompt()` accepts nudge parameters and injects them

But `core/agent.py` never passes these parameters to `build_system_prompt()`. The wiring is missing.

### Solution

Wire up the existing nudge system:

1. Add turn counter to the agent loop
2. Pass `nudge_turn_count`, `nudge_interval`, `nudge_messages`, `is_mind_mode`, `is_goal_active` to `build_system_prompt()`
3. Read nudge config from `config.yaml` (interval, skill_threshold already defined in doc 41)

**No new code needed** — just parameter passing and config reading in `core/agent.py`.

## Implementation Priority

| # | Feature | Effort | Files Changed |
|---|---------|--------|---------------|
| 1 | Context Compression | Medium | New `core/context_compressor.py`, edit `core/agent.py` |
| 2 | Memory Injection Scanning | Low | Edit `core/learner.py`, `tools/knowledge/writer.py`, `core/agent.py` |
| 3 | Skill Capture Nudge | Low | Edit `core/agent.py` (parameter wiring only) |
| 4 | User Modeling | High | New `core/user_model.py`, `tools/user/profile_tool.py`, edit `core/database.py`, `core/agent.py`, `core/planner.py`, `core/registry.py` |

## Integration with Existing Systems

- **[LLM Routing](06-LLM-ROUTING.md)** — Compression uses `task_type="fast"` for cheap summarization
- **[Security Architecture](07-SECURITY.md)** — Memory scanning extends the existing injection guard
- **[Identity System](17-IDENTITY.md)** — User modeling complements agent self-model
- **[Proactive Nudging](41-PROACTIVE-NUDGING.md)** — Skill capture nudge activates the planned system
- **[Learning Engine](48-LEARNING-ENGINE.md)** — Memory scanning hardens lesson extraction
- **[RLM Architecture](54-RLM.md)** — Context compression reduces need for RLM on medium-length conversations
