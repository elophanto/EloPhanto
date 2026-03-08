# EloPhanto — Proactive Nudging

> **Status: Planned** — Periodic system prompt augmentation to drive self-improvement behavior.

## Why This Matters

EloPhanto has powerful self-improvement capabilities — memory, knowledge writing, skill creation, self-modification — but the agent only uses them when explicitly asked or when it happens to recognize an opportunity. Most valuable learning moments pass without being captured.

Proactive nudging adds periodic reminders to the system prompt that encourage the agent to:
1. Save important learnings to memory/knowledge
2. Create reusable skills from successful multi-step approaches
3. Reflect on what worked and what didn't

This is a simple mechanism with outsized impact — it turns passive tool availability into active self-improvement behavior.

## How It Works

### Nudge Injection

Every N conversation turns (configurable), append a nudge block to the system prompt. The nudge is **additive** — it doesn't replace any existing prompt content.

```python
# In core/planner.py — build_system_prompt()
if turn_count > 0 and turn_count % nudge_interval == 0:
    prompt += _build_nudge(turn_count, nudge_type)
```

### Nudge Types

Two nudge types alternate based on context:

**Memory nudge** (after information-heavy exchanges):
```xml
<nudge type="memory">
You've been working for a while. Before continuing, consider:
- Did you learn something new about the user's preferences or environment?
- Did you discover a useful pattern, shortcut, or workaround?
- Did something unexpected happen that's worth remembering?

If yes, save it now with knowledge_write. Don't wait — you'll forget next session.
</nudge>
```

**Skill nudge** (after complex multi-tool sequences):
```xml
<nudge type="skill">
You just completed a multi-step task. Consider:
- Could this approach be reused for similar tasks?
- Would a skill make this faster next time?
- Is there a pattern here worth capturing?

If yes, think about creating a skill. Search existing skills first to avoid duplicates.
</nudge>
```

### Nudge Selection Logic

```python
def _select_nudge_type(messages: list[dict], turn_count: int) -> str:
    """Choose which nudge to show based on recent conversation."""
    # Count tool calls in last N messages
    recent_tool_calls = sum(
        1 for msg in messages[-10:]
        if msg.get("role") == "assistant" and msg.get("tool_calls")
    )

    # If 5+ tool calls recently, suggest skill creation
    if recent_tool_calls >= 5:
        return "skill"

    # Default to memory nudge
    return "memory"
```

### Configuration

```yaml
# In config.yaml
nudging:
  enabled: true
  interval: 15          # Nudge every N turns (default: 15)
  memory_interval: 15   # Memory nudge frequency
  skill_interval: 30    # Skill nudge frequency (less frequent — skills are heavier)
  skill_threshold: 5    # Min tool calls before suggesting skill creation
```

### Nudge Suppression

Nudges are suppressed when:
- The agent is in autonomous mind mode (has its own reflection cycles)
- The agent is executing a goal (don't interrupt focused work)
- The last nudge was less than 5 turns ago (prevent nudge fatigue)
- The conversation is a simple Q&A (< 3 turns total)

## Integration Points

| Component | Change |
|-----------|--------|
| `core/planner.py` | Add nudge injection in `build_system_prompt()` |
| `core/agent.py` | Track turn count per session, pass to planner |
| `config.yaml` | Add `nudging` section |

## Why Not a Separate Tool?

Nudges are prompt-level, not tool-level, because:
1. Tools require the LLM to decide to call them — the whole point is the LLM doesn't think to save learnings
2. System prompt nudges are "free" — no extra inference turn needed
3. The agent can ignore the nudge if it's not relevant (it's a suggestion, not a command)

## Implementation Priority

| Task | Effort | Priority |
|------|--------|----------|
| Nudge injection in planner | Low | P0 |
| Turn counting in agent | Low | P0 |
| Nudge type selection | Low | P0 |
| Configuration support | Low | P1 |
| Suppression logic | Low | P1 |
