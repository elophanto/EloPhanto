# 54 — Recursive Language Model (RLM) Architecture

> **Status: Planned** — Inference-time recursive self-invocation for unbounded context processing.

## What Is RLM?

Recursive Language Models (RLM) treat the LLM as a **function that can call itself**. Instead of cramming everything into a single context window, the agent writes code that slices, transforms, and recursively processes context — calling sub-instances of itself on focused sub-problems, then aggregating results.

The key insight: **context is a variable, not a constraint**. The agent operates on an external context store via code, pulling in only the slices it needs for each sub-task. This turns fixed-window LLMs into systems that can reason over arbitrarily large inputs.

```
Traditional:    User → [giant prompt + all context] → LLM → answer
RLM:            User → LLM writes code → code queries context slices
                     → code calls LLM on each slice → aggregates → answer
```

## Why This Matters for EloPhanto

EloPhanto already hits context limits on:
- Large codebase analysis (100+ files)
- Multi-session research synthesis
- Knowledge base queries spanning dozens of documents
- Long autonomous experiment chains

RLM removes the context ceiling. The agent can process a 500-file codebase by writing a script that indexes files, classifies them, deep-dives into relevant ones via recursive sub-calls, and synthesizes findings — all in a single high-level turn.

## Architecture

### Phase 1: RLM-Lite (Recursive Sub-Cognition via Sandbox)

Build on the existing [Code Execution Sandbox](39-CODE-EXECUTION-SANDBOX.md) by adding `agent_call` to the sandbox's allowed tools.

**New sandbox function:**

```python
def agent_call(prompt: str, context: str = "", model: str = "auto") -> str:
    """Invoke a sub-instance of the agent on a focused prompt.

    Args:
        prompt: What to analyze/answer/do.
        context: Text context to include (file contents, search results, etc.).
        model: LLM to use — "auto" lets the router pick.

    Returns:
        The agent's text response.
    """
    return _rpc_call("agent_call", {
        "prompt": prompt,
        "context": context,
        "model": model,
    })
```

**Example — Recursive codebase analysis:**

```python
from elophanto_tools import file_list, file_read, agent_call

# Step 1: Get all Python files
files = file_list(".", pattern="**/*.py")["files"]

# Step 2: Classify each file (cheap model, parallel-safe)
summaries = []
for f in files:
    content = file_read(f)["content"]
    summary = agent_call(
        prompt=f"Summarize this file in 2 lines: purpose, key exports.",
        context=content,
        model="fast",  # cheap model for classification
    )
    summaries.append({"file": f, "summary": summary})

# Step 3: Build an index, find relevant files
index = "\n".join(f"{s['file']}: {s['summary']}" for s in summaries)
relevant = agent_call(
    prompt="Which files handle authentication? Return file paths only.",
    context=index,
)

# Step 4: Deep analysis on relevant files only
for path in relevant.strip().split("\n"):
    content = file_read(path.strip())["content"]
    analysis = agent_call(
        prompt="Analyze this auth module: security issues, missing edge cases, suggestions.",
        context=content,
        model="strong",  # best model for security analysis
    )
    print(f"\n## {path}\n{analysis}")
```

One `execute_code` call. The agent wrote a program that recursively invoked itself on focused slices. No context window was exceeded.

**Implementation:**

| Component | Change |
|-----------|--------|
| `tools/selfdev/rpc_server.py` | Add `agent_call` to RPC dispatch |
| `core/agent.py` | New `_handle_sub_cognition()` — creates a minimal agent turn with injected context |
| `tools/selfdev/stub_generator.py` | Generate `agent_call` stub |
| Sandbox allowlist | Add `agent_call` (with recursion depth limit) |

**Safety constraints:**
- **Recursion depth limit**: Max 3 levels (configurable). `agent_call` inside an `agent_call` script counts as depth +1. Prevents infinite loops.
- **Total sub-call budget**: Max 50 agent_calls per execute_code invocation (shared with the existing 50 tool-call limit).
- **Model cost cap**: Sub-calls inherit the parent session's spending limit. The agent can't burn unlimited tokens via recursive calls.
- **No tool escalation**: Sub-cognition calls get the same tool allowlist as the sandbox — no vault, no self-modify, no identity changes.
- **Timeout inheritance**: The 5-minute sandbox timeout covers the entire execution including all sub-calls.

### Phase 2: Context-as-Variable (Full RLM)

Replace "dump everything into messages" with a **ContextStore** — an indexed, queryable, sliceable context layer.

**Core concept:**

```
Current:    agent.run(messages=[...all history...])
RLM:        agent.run(messages=[task], context_id="ctx_abc123")
            ↓
            Agent prompt includes context INDEX (table of contents, not full content)
            ↓
            Agent uses context_query() to pull specific slices on demand
```

**ContextStore API:**

```python
class ContextStore:
    """External context that the agent can query during inference."""

    def ingest(self, source: str, content: str, metadata: dict) -> str:
        """Add content to the store. Returns chunk IDs."""
        # Chunks content, generates embeddings, stores in SQLite + FAISS

    def index(self, context_id: str) -> str:
        """Return a table of contents / summary of all chunks."""
        # Used in system prompt so agent knows what's available

    def query(self, context_id: str, query: str, max_chunks: int = 5) -> list[str]:
        """Semantic search over stored context."""

    def slice(self, context_id: str, source: str, lines: str = None) -> str:
        """Get exact content by source path and optional line range."""

    def transform(self, context_id: str, operation: str, params: dict) -> str:
        """Apply transformations: filter, group, summarize, diff."""
```

**New tools:**

| Tool | Permission | Description |
|------|-----------|-------------|
| `context_ingest` | MODERATE | Add files/text/URLs to the context store |
| `context_query` | SAFE | Semantic search over context |
| `context_slice` | SAFE | Get exact content by path + line range |
| `context_transform` | SAFE | Filter, group, summarize, diff context |
| `context_index` | SAFE | Get table of contents for a context |

**How it changes the agent loop:**

1. **Task arrives** — agent creates a ContextStore, ingests relevant sources (files, KB entries, session history).
2. **System prompt** includes the context *index* (TOC), not the full content. Prompt stays small.
3. **During execution** — agent queries/slices context as needed. Each tool call or `agent_call` gets exactly the context it needs.
4. **Recursive calls** — sub-instances share the same ContextStore (read-only) or create child stores for sub-problems.
5. **Result synthesis** — parent aggregates sub-results, queries the store for any missing pieces, produces final output.

## Comparison: Before and After

| Dimension | Current | Phase 1 (RLM-Lite) | Phase 2 (Full RLM) |
|-----------|---------|---------------------|---------------------|
| Context handling | Stuff into messages | Agent writes code to slice context | Indexed ContextStore with query tools |
| Max effective context | ~200K tokens | Unbounded (via recursion) | Unbounded (via store) |
| Sub-task delegation | Sequential tool calls | `agent_call()` in sandbox scripts | `agent_call()` + `context_query()` |
| Cost per large task | High (full context every turn) | Medium (focused sub-calls) | Low (only relevant slices loaded) |
| Agent writes code to think | No | Yes (sandbox scripts) | Yes (sandbox + context queries) |
| Recursion | Not possible | 3-level depth limit | N-level with budget control |

## Integration with Existing Systems

RLM builds on and enhances several existing EloPhanto capabilities:

- **[Code Execution Sandbox](39-CODE-EXECUTION-SANDBOX.md)** — Phase 1 is a direct extension. Adding `agent_call` to the sandbox turns it into an RLM runtime.
- **[LLM Routing](../docs/06-LLM-ROUTING.md)** — Sub-calls use the router. Classification tasks go to cheap models, deep analysis to strong models. RLM makes routing more impactful.
- **[Agent Organization](29-AGENT-ORGANIZATION.md)** — Persistent specialist agents can maintain their own ContextStores, becoming domain experts that the parent queries.
- **[Cross-Session Search](38-SESSION-SEARCH.md)** — Past sessions become ingestible context. "Analyze everything I discussed about authentication last week" becomes a ContextStore query + recursive analysis.
- **[Knowledge System](05-KNOWLEDGE-SYSTEM.md)** — KB entries are natural context sources. Phase 2 unifies KB search and context queries.
- **[Agent Swarm](25-AGENT-SWARM.md)** — Swarm agents can share ContextStores for coordinated work on large problems.

## Implementation Priority

| Task | Phase | Effort | Priority |
|------|-------|--------|----------|
| `agent_call` RPC handler | 1 | Medium | P0 |
| Sub-cognition in agent.py | 1 | Medium | P0 |
| Recursion depth tracking + limits | 1 | Low | P0 |
| Cost tracking for sub-calls | 1 | Low | P0 |
| Stub generation for agent_call | 1 | Low | P1 |
| ContextStore (SQLite + embeddings) | 2 | High | P1 |
| context_query / context_slice tools | 2 | Medium | P1 |
| context_ingest (files, URLs, sessions) | 2 | Medium | P1 |
| Context index in system prompt | 2 | Medium | P2 |
| Shared context across organization agents | 2 | High | P2 |

## References

- [Recursive Language Models (RLM)](https://github.com/mattshax/rlm) — Original concept by Matt Shaxted
- [Code Execution Sandbox](39-CODE-EXECUTION-SANDBOX.md) — EloPhanto's existing sandbox architecture (Phase 1 foundation)
- [Autonomous Experimentation](37-AUTONOMOUS-EXPERIMENTATION.md) — Another use case for RLM: recursive analysis of experiment results
