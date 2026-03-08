# EloPhanto — Cross-Session Search

> **Status: Planned** — SQLite FTS5-based search across past conversation sessions.

## Why This Matters

EloPhanto persists conversation history per channel/user in `core/session.py`, but sessions are isolated — the agent cannot search or recall what happened in previous conversations. When a user asks "remember when we debugged that API issue last week?" or the agent needs to recall a past approach, it has no mechanism to look back.

This is distinct from the knowledge system (`05-KNOWLEDGE-SYSTEM.md`) which stores curated information. Session search provides access to raw conversational history — the full context of past interactions including tool calls, results, reasoning, and user feedback.

## Architecture

### Storage Layer

Extend the existing `sessions` SQLite database with a FTS5 virtual table for full-text search:

```sql
-- New FTS5 index alongside existing sessions table
CREATE VIRTUAL TABLE IF NOT EXISTS session_messages_fts USING fts5(
    session_id,
    role,
    content,
    tool_name,
    timestamp,
    content='session_messages',
    tokenize='porter unicode61'
);

-- Backing content table
CREATE TABLE IF NOT EXISTS session_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,          -- user/assistant/tool
    content TEXT NOT NULL,
    tool_name TEXT,              -- populated for tool calls/results
    timestamp TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);
```

Messages are logged individually as they're appended to a session (not batch-written at session end). This ensures conversations are searchable even if the agent crashes mid-session.

### Search Tool

New tool: `session_search` in group `data`.

```python
{
    "name": "session_search",
    "description": "Search past conversation sessions. Returns matching excerpts grouped by session with surrounding context.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (supports FTS5 syntax: AND, OR, NOT, phrases)"
            },
            "channel": {
                "type": "string",
                "description": "Filter by channel (cli, telegram, discord, slack). Optional."
            },
            "limit": {
                "type": "integer",
                "description": "Max sessions to return (default: 5)"
            },
            "days_back": {
                "type": "integer",
                "description": "Only search sessions from the last N days (default: 30)"
            }
        },
        "required": ["query"]
    }
}
```

### Search Flow

1. Run FTS5 query against `session_messages_fts`
2. Group results by `session_id`
3. For each matching session, load a truncated window around matches (5 messages before, 5 after)
4. Return structured results with session metadata (channel, date, message count)

No LLM summarization step — return raw excerpts. The calling agent can summarize if needed. Keeps the tool fast and avoids recursive LLM calls.

### PII Protection

Session messages may contain sensitive data. The search tool:
- Passes results through `core/pii_guard.py` before returning
- Respects authority tiers — non-owner users cannot search sessions they didn't participate in

## Integration Points

| Component | Change |
|-----------|--------|
| `core/session.py` | Add `log_message()` method to write individual messages to `session_messages` table |
| `core/agent.py` | Call `session.log_message()` on each conversation turn |
| `tools/data/session_search.py` | New search tool |
| `core/registry.py` | Register `session_search` tool |

## Implementation Priority

| Task | Effort | Priority |
|------|--------|----------|
| `session_messages` table + FTS5 index | Low | P0 |
| Per-message logging in session manager | Low | P0 |
| `session_search` tool | Medium | P0 |
| PII redaction on results | Low | P0 |
| Channel/date filtering | Low | P1 |
