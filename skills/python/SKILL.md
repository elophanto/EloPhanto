# Python Development

## Description

Python coding guide for EloPhanto — covers plugin development, async patterns, error handling, testing with pytest, and the BaseTool interface.

## Triggers

- python
- build plugin
- create plugin
- create tool
- modify source
- pytest
- async
- pip
- pyproject

## Instructions

### 1. Before Writing Code

1. Read existing code in the target area (self_read_source or file_read).
2. Match the patterns already in use — naming, error handling, imports.
3. Check if something similar exists (self_list_capabilities for tools,
   file_list with `*.py` pattern for general code).
4. Identify edge cases upfront: empty input, missing params, file not found,
   permission denied, timeouts.

### 2. Style

- Python 3.12+ — use `str | None` not `Optional[str]`
- `from __future__ import annotations` at the top of every file
- Type hints on ALL function signatures (parameters AND return types)
- Import order: stdlib → third-party → project (ruff enforces this)
- Use `pathlib.Path` instead of `os.path`
- Use f-strings for formatting
- Line length: 100 characters max
- No dead code — remove commented-out blocks and unused imports

### 3. EloPhanto Plugin Interface

Every tool must implement the BaseTool abstract class:

```python
from __future__ import annotations
from typing import Any
from tools.base import BaseTool, PermissionLevel, ToolResult

class MyTool(BaseTool):
    @property
    def name(self) -> str:
        return "my_tool"  # snake_case, unique across all tools

    @property
    def description(self) -> str:
        return "Clear, actionable description the LLM reads to decide when to use this tool."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "param": {"type": "string", "description": "What this does"},
            },
            "required": ["param"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.MODERATE  # SAFE | MODERATE | DESTRUCTIVE | CRITICAL

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        try:
            result = await do_something(params["param"])
            return ToolResult(success=True, data={"output": result})
        except Exception as e:
            return ToolResult(success=False, error=f"Failed: {e}")
```

**Critical rules:**
- NEVER raise from `execute()` — catch all exceptions, return `ToolResult(success=False, error=...)`
- Use `async`/`await` for ALL I/O (file, network, subprocess)
- `description` is what the LLM reads — write it like a help string, not a code comment
- `input_schema` must be valid JSON Schema with descriptions per property
- Keep dependencies minimal — prefer stdlib over external packages

### 4. Error Handling

```python
# Specific exceptions with informative messages
try:
    data = json.loads(response)
except json.JSONDecodeError as e:
    return ToolResult(success=False, error=f"Invalid JSON: {e}")

# Early returns for validation (guard clauses)
async def execute(self, params):
    path = Path(params["path"])
    if not path.exists():
        return ToolResult(success=False, error=f"Not found: {path}")
    if not path.is_file():
        return ToolResult(success=False, error=f"Not a file: {path}")
    # main logic after guards pass
```

**Anti-patterns:**
- Bare `except:` — always catch specific exceptions
- Swallowing errors silently — always log or return the error
- Raising from execute() — the agent loop expects ToolResult, not exceptions

### 5. Async Patterns

```python
import asyncio

# Subprocess with timeout
proc = await asyncio.create_subprocess_exec(
    "command", "arg1",
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
try:
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
except asyncio.TimeoutError:
    proc.kill()
    await proc.communicate()
    return ToolResult(success=False, error="Command timed out")

# Parallel operations
results = await asyncio.gather(task_a(), task_b(), return_exceptions=True)

# File I/O (sync is fine for small files in asyncio context)
content = Path("file.txt").read_text(encoding="utf-8")
```

### 6. Testing

- Framework: pytest with `pytest-asyncio` (asyncio_mode="auto")
- `@pytest.mark.asyncio` on async test functions
- Test structure: interface properties → happy path → error cases
- Run: `self_run_tests` or `python -m pytest tests/ -v --tb=short`
- Keep tests isolated — no external service dependencies

```python
import pytest
from plugins.my_tool.plugin import MyTool

@pytest.mark.asyncio
async def test_execute_success():
    tool = MyTool()
    result = await tool.execute({"param": "valid_input"})
    assert result.success
    assert "output" in result.data

@pytest.mark.asyncio
async def test_execute_missing_param():
    tool = MyTool()
    result = await tool.execute({})
    assert not result.success
```

### 7. Code Review Checklist

- **Security**: Input validation, no credential leaks, path traversal checks
- **Resources**: Files/connections closed (use `with` or try/finally)
- **Edge cases**: Empty input, missing params, timeouts, large files
- **Error handling**: Graceful failures, informative error messages
- **Types**: All signatures typed, mypy passes
- **Tests**: New code has test coverage

### 8. Tooling

- **ruff** for linting (rules: E, F, I, UP, B) — run with `ruff check .`
- **mypy** for type checking (Python 3.12 target, strict=false)
- **pytest** for testing (asyncio_mode="auto")
- **uv** for package management

## Notes

EloPhanto plugins live in `plugins/<name>/plugin.py`. They are registered in
`core/registry.py` and their dependencies injected in `core/agent.py`. Use
self_read_source to study existing tools before creating new ones.
