# EloPhanto — Code Execution Sandbox

> **Status: Planned** — Sandboxed Python execution environment for multi-step tool orchestration.

## Why This Matters

Complex tasks often require chaining 5-10+ tool calls sequentially — search the web, extract content, process data, write a file. Each step costs an LLM inference turn. A code execution sandbox lets the agent write a Python script that orchestrates multiple tools in a single turn, dramatically reducing latency and token cost.

This is NOT about running arbitrary user code. It's about giving the agent a structured way to compose its own tools programmatically when the task is too complex for sequential tool calling.

## Architecture

### Execution Model

```
Agent writes Python script
    ↓
Script runs in child process (sanitized env)
    ↓
Script calls tools via Unix domain socket RPC
    ↓
Tool results returned to script
    ↓
Script output returned to agent
```

### Tool: `execute_code`

Group: `selfdev`. Permission: `DESTRUCTIVE`.

```python
{
    "name": "execute_code",
    "description": "Execute a Python script in a sandboxed environment with access to a curated set of tools via RPC. Use for complex multi-step tasks that would require many sequential tool calls.",
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python script to execute. Import 'elophanto_tools' for tool access."
            },
            "description": {
                "type": "string",
                "description": "What this script does (logged for audit)."
            }
        },
        "required": ["code", "description"]
    }
}
```

### Sandbox Security

**Environment sanitization**: The child process inherits only safe environment variables:
```python
SAFE_ENV_KEYS = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "SHELL"}
# All *_KEY, *_TOKEN, *_SECRET, *_PASSWORD vars are stripped
```

**Tool allowlist**: The script can only call a curated subset of tools via RPC:
- `web_search` — search the web
- `web_extract` — extract content from a URL
- `file_read` — read files (within workspace only)
- `file_write` — write files (within workspace only)
- `file_list` — list directory contents
- `knowledge_search` — search the knowledge base
- `shell_execute` — run shell commands (inherits sandbox restrictions)

Tools NOT available in sandbox (prevents privilege escalation):
- `vault_*` — no credential access
- `self_modify_*` — no self-modification
- `execute_code` — no recursive execution
- `identity_*` — no identity changes
- `config_*` — no config changes

**Resource limits**:
- Timeout: 5 minutes (configurable)
- Stdout cap: 50KB
- Max tool calls per script: 50
- Workspace isolation: scripts run in a temp directory, file operations scoped to workspace

### Auto-Generated Tool Stubs

When `execute_code` runs, it generates a `elophanto_tools.py` module in the script's working directory with typed function signatures:

```python
# Auto-generated — do not edit
"""Tool stubs for sandboxed code execution."""

def web_search(query: str, max_results: int = 5) -> dict:
    """Search the web. Returns {"results": [{"title": ..., "url": ..., "snippet": ...}]}"""
    return _rpc_call("web_search", {"query": query, "max_results": max_results})

def file_read(path: str) -> dict:
    """Read a file. Returns {"content": "..."}"""
    return _rpc_call("file_read", {"path": path})

# ... etc for each allowed tool
```

This gives the agent IDE-quality hints about what's available without needing to remember tool schemas.

### RPC Protocol

Communication via Unix domain socket (`/tmp/elophanto_rpc_{pid}.sock`):

```json
// Request
{"id": 1, "tool": "web_search", "params": {"query": "python asyncio patterns"}}

// Response
{"id": 1, "success": true, "data": {"results": [...]}}
```

The RPC server runs in the parent process (the agent), so tool execution goes through the normal permission/approval flow. The sandbox can't bypass permissions.

## Example Usage

Agent receives: "Research the top 5 Python web frameworks, compare their GitHub stars, and write a summary."

Instead of 10+ sequential tool calls, the agent writes:

```python
from elophanto_tools import web_search, web_extract, file_write

frameworks = ["Django", "Flask", "FastAPI", "Tornado", "Starlette"]
results = []

for fw in frameworks:
    search = web_search(f"{fw} Python framework GitHub stars 2026")
    if search["results"]:
        page = web_extract(search["results"][0]["url"])
        results.append({"name": fw, "info": page.get("content", "")[:500]})

summary = "# Python Web Framework Comparison\n\n"
for r in results:
    summary += f"## {r['name']}\n{r['info']}\n\n"

file_write("research/framework_comparison.md", summary)
print(f"Wrote comparison of {len(results)} frameworks")
```

One inference turn instead of 15+.

## Integration Points

| Component | Change |
|-----------|--------|
| `tools/selfdev/execute_code.py` | New tool — sandbox orchestrator |
| `tools/selfdev/rpc_server.py` | Unix socket RPC server for tool dispatch |
| `tools/selfdev/stub_generator.py` | Auto-generates `elophanto_tools.py` from allowed tool schemas |
| `core/registry.py` | Register `execute_code` tool |

## Implementation Priority

| Task | Effort | Priority |
|------|--------|----------|
| RPC server (Unix socket) | Medium | P0 |
| Sandbox execution (env sanitization, limits) | Medium | P0 |
| Stub generator | Low | P0 |
| `execute_code` tool | Medium | P0 |
| Workspace isolation | Low | P1 |
