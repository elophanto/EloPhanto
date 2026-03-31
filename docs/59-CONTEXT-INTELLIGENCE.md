# 59 — Context Intelligence

> Smarter context management, deferred tool loading, memory consolidation,
> verification prompts, coordinator synthesis, and proactive communication.

**Status:** Complete
**Priority:** P0 — Core agent efficiency
**Inspiration:** Analysis of production agent frameworks at scale

---

## Overview

Six targeted improvements to make EloPhanto dramatically more efficient with
its context window, smarter about memory hygiene, and better at multi-agent
coordination.

---

## 1. Deferred Tool Loading

### Problem
We load all 173+ tool schemas into every context window — massive token waste.
Most tasks use 5-12 tools. The rest are dead weight consuming prompt budget.

### Solution
Lazy tool registry that injects only relevant tools per task, with on-demand
discovery for the rest.

### Design

**Tool Tiers:**
- **Tier 0 (Always loaded):** Core tools used in >80% of tasks — `shell_execute`,
  `file_read`, `file_write`, `file_patch`, `knowledge_search`, `goal_manage`,
  `browser_navigate` (~10-15 tools)
- **Tier 1 (Profile-loaded):** Tools matching task profile — e.g., coding tasks
  load `git_*` tools, social tasks load `twitter_*`, `commune_*`
- **Tier 2 (On-demand):** Everything else — loaded only when agent requests via
  `tool_discover` action

**New Tool: `tool_discover`**
```
Action: tool_discover
Params: { query: "send email" }
Returns: Matching tool schemas injected into next turn
```

**Implementation:**
- `core/registry.py` — Add `ToolTier` enum, `get_tools_for_context(task_type)`
- `core/planner.py` — Inject tier 0 + tier 1 schemas, add discovery prompt section
- `core/agent.py` — Handle dynamic tool injection mid-conversation
- `tools/system/discover_tool.py` — New tool for on-demand discovery

**Token Savings:** ~60-70% reduction in tool schema tokens per call.

### Files
| File | Change |
|------|--------|
| `core/registry.py` | Add `ToolTier`, `get_tools_for_context()`, tier assignment |
| `core/planner.py` | Dynamic tool section, discovery prompt |
| `core/agent.py` | Mid-conversation tool injection |
| `tools/system/discover_tool.py` | New — on-demand tool discovery |

---

## 2. Auto-Dream Memory Consolidation

### Problem
Knowledge base grows without pruning. Stale lessons, duplicate entries, and
outdated knowledge accumulate. No index cap enforcement.

### Solution
Background consolidation cycle that prunes, merges, and maintains knowledge
hygiene during autonomous mind dream phases.

### Design

**Consolidation Actions:**
1. **Prune stale entries** — Remove knowledge older than N days with no references
2. **Merge duplicates** — Detect similar lessons (embedding cosine > 0.92) and merge
3. **Cap enforcement** — Keep knowledge index under 500 entries, archive excess
4. **Date normalization** — Convert relative dates to absolute in all entries
5. **Contradiction resolution** — When newer knowledge contradicts older, keep newer

**Trigger:** Runs during autonomous mind dream phase when:
- 24+ hours since last consolidation
- 10+ new knowledge entries since last run
- Manual trigger via `goal_manage` dream action

**Implementation:**
- `core/knowledge_consolidator.py` — New module, consolidation logic
- `core/autonomous_mind.py` — Hook consolidation into dream cycle
- `core/database.py` — Add `consolidation_log` table

### Files
| File | Change |
|------|--------|
| `core/knowledge_consolidator.py` | New — prune, merge, cap, normalize |
| `core/autonomous_mind.py` | Hook consolidation into dream phase |
| `core/database.py` | Add `consolidation_log` schema |

---

## 3. Budget-Aware Auto-Compact with Circuit Breaker

### Problem
Current compression fires at 50% threshold with no escalation. No microcompact
(clearing stale tool outputs). No circuit breaker — if compression fails, it
keeps retrying forever.

### Solution
Three-tier threshold system with microcompact pass and circuit breaker.

### Design

**Tier System:**
- **Tier 1 — Microcompact (70% capacity):** Clear old tool results, keep last 5.
  No LLM call needed — pure text manipulation. Fast, cheap.
- **Tier 2 — Smart Compact (85% capacity):** LLM-based summarization of middle
  turns. Current compression logic, improved.
- **Tier 3 — Emergency Trim (95% capacity):** Aggressive truncation. Drop oldest
  turns, keep first 2 + last 5.

**Circuit Breaker:**
- Track consecutive compression failures
- After 3 failures: stop auto-compact, surface warning to user
- Reset counter on success
- Prevents: infinite retry loops burning API credits

**Microcompact Logic:**
```python
def microcompact(messages: list[dict]) -> list[dict]:
    """Clear tool results older than last 5 tool calls."""
    tool_results = [m for m in messages if m["role"] == "tool"]
    if len(tool_results) <= 5:
        return messages
    stale = tool_results[:-5]
    for msg in stale:
        msg["content"] = "[result cleared — context optimization]"
    return messages
```

### Files
| File | Change |
|------|--------|
| `core/context_compressor.py` | Add tiered thresholds, microcompact, circuit breaker |
| `core/agent.py` | Wire new threshold checks into main loop |

---

## 4. Verification Agent Prompt Pattern

### Problem
Swarm specialist agents have generic prompts. No failure-mode awareness.
When an agent hits an error, it doesn't know common failure patterns or
recovery strategies.

### Solution
Failure-mode-aware enriched prompts for specialist agents with documented
failure patterns and recovery instructions.

### Design

**Prompt Template Addition:**
```
## Failure Modes

Your job is to try to BREAK your own work, not just confirm it works.

Common failure patterns for {agent_type}:
1. {pattern_1} — Recovery: {recovery_1}
2. {pattern_2} — Recovery: {recovery_2}

Before reporting success:
- Run the verification command, read the output, THEN claim the result
- If you hit an error, diagnose root cause before retrying
- If 3 consecutive attempts fail, report the failure with diagnostics
```

**Agent-Specific Failure Libraries:**
- **Coding agents:** Import errors, type mismatches, test failures, lint violations
- **Browser agents:** Element not found, iframe context, navigation timeout, stale DOM
- **Research agents:** Empty results, rate limits, paywall hits, redirect loops
- **Deploy agents:** Build failures, env var missing, port conflicts, permission denied

**Implementation:**
- `core/swarm.py` — Extend `_build_enriched_prompt()` with failure-mode section
- `core/config.py` — Add `failure_patterns` field to `AgentProfileConfig`
- `data/failure_modes/` — Per-agent-type failure pattern libraries (YAML)

### Files
| File | Change |
|------|--------|
| `core/swarm.py` | Extend enriched prompts with failure modes |
| `core/config.py` | Add `failure_patterns` to agent profile |
| `data/failure_modes/*.yaml` | New — failure pattern libraries |

---

## 5. Coordinator Synthesis

### Problem
Swarm orchestrator dispatches tasks and collects results individually.
No synthesis step — doesn't read/understand results before dispatching
follow-up work. Leads to lazy delegation.

### Solution
Add synthesis step to swarm coordinator that reads all agent results,
identifies conflicts/gaps, and crafts specific follow-up specs.

### Design

**Synthesis Pipeline:**
```
1. Collect: Gather all completed agent results
2. Analyze: LLM call to identify:
   - Conflicts between agents
   - Gaps in coverage
   - Actionable findings vs noise
3. Synthesize: Build unified understanding
4. Dispatch: Craft specific follow-up specs with:
   - Exact file paths and line numbers
   - Exact changes needed
   - Context from synthesis (not "based on your findings")
```

**Anti-Pattern Guard:**
The synthesis prompt explicitly forbids lazy delegation:
```
NEVER say "based on the findings" or "as discussed".
Include the specific file path, line number, and exact change.
If you don't know the specifics, you haven't done synthesis yet.
```

**Implementation:**
- `core/swarm.py` — Add `_synthesize_results()` after agent completion
- `core/swarm.py` — Modify dispatch to use synthesized specs
- `core/planner.py` — Add synthesis prompt template

### Files
| File | Change |
|------|--------|
| `core/swarm.py` | Add `_synthesize_results()`, modify dispatch pipeline |
| `core/planner.py` | Add synthesis prompt template |

---

## 6. BriefTool — Proactive Communication

### Problem
The autonomous mind runs silently. It discovers insights, completes goals,
and notices patterns — but never proactively tells the user. User must ask.

### Solution
A dedicated `brief` tool that lets the agent surface insights proactively
through any connected channel.

### Design

**Tool: `agent_brief`**
```
Permission: SAFE
Group: communication
Params:
  summary: str       — 1-2 sentence insight
  details: str       — Optional expanded context
  priority: str      — "info" | "warning" | "actionable"
  channel: str       — Target channel (default: active session)
```

**When to Brief:**
- Goal completed or failed
- Pattern detected in data (e.g., engagement spike, cost anomaly)
- Scheduled task result worth noting
- Knowledge contradiction discovered during consolidation
- Security event detected

**Delivery:**
- CLI: Print to terminal with priority-colored prefix
- Dashboard: Add to BRIEFS panel (new panel)
- Telegram/Discord/Slack: Send as message to user
- Gateway: Broadcast via `event` protocol message type

**Rate Limiting:**
- Max 3 briefs per hour (prevent spam)
- Priority "actionable" bypasses rate limit
- Dedup: Don't brief the same insight twice

### Files
| File | Change |
|------|--------|
| `tools/communication/brief_tool.py` | New — proactive brief tool |
| `core/autonomous_mind.py` | Use brief tool for insight surfacing |
| `cli/dashboard/widgets/briefs.py` | New — BRIEFS panel widget |
| `core/protocol.py` | Add `brief` message type |

---

## Implementation Priority

| # | Feature | Impact | Effort | Dependencies |
|---|---------|--------|--------|--------------|
| 1 | Deferred Tool Loading | Highest — 60-70% token savings | Medium | registry.py refactor |
| 2 | Auto-Compact Circuit Breaker | High — prevents context overflow | Low | context_compressor.py |
| 3 | Auto-Dream Consolidation | High — long-term knowledge health | Medium | autonomous_mind.py |
| 4 | BriefTool | Medium — user experience | Low | protocol.py |
| 5 | Verification Agent Prompt | Medium — swarm quality | Low | swarm.py |
| 6 | Coordinator Synthesis | Medium — swarm intelligence | Medium | swarm.py |

---

## What NOT to Copy

- Feature flag hell (GrowthBook, dozens of conditional requires)
- Anthropic SDK coupling (we're provider-agnostic, stay that way)
- React/Ink terminal UI (irrelevant for headless agent)
- 4,683-line main.tsx monolith (our agent.py is already too long at 3K)
