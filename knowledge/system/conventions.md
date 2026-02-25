---
title: Coding Conventions
created: 2026-02-17
updated: 2026-02-17
tags: conventions, patterns, coding, standards
scope: system
---

# Coding Conventions

## Language & Runtime

- Python 3.12+ with `from __future__ import annotations`
- Package manager: uv with hatchling build backend
- Dependencies kept minimal — stdlib preferred where possible

## Code Patterns

- **Dataclasses** over Pydantic for configuration and data structures
- **BaseTool ABC** for all tool implementations (name, description, input_schema, permission_level, async execute)
- **Async/await** throughout — all tool execution is async
- **ToolResult** dataclass for standardized return values (success, data, error)
- **Dependency injection** for tools needing runtime state (router injected into llm_call, db/embedder into knowledge tools)

## Testing

- pytest + pytest-asyncio with `asyncio_mode = "auto"`
- Fixtures in `tests/conftest.py` for shared config
- `tmp_path` for filesystem isolation
- Mock external services (LLM calls, Ollama API) — never call real services in tests
- One test file per module, grouped in test classes

## Style

- ruff for linting (rules: E, F, I, UP, B)
- mypy for type checking (non-strict)
- Line length: 100 characters
