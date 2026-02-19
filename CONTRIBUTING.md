# Contributing to EloPhanto

Thanks for your interest in contributing! This guide covers setup, code style, and the PR process.

## Development Setup

```bash
git clone https://github.com/elophanto/EloPhanto.git
cd EloPhanto
./setup.sh                         # Install deps + build browser bridge
source .venv/bin/activate          # Activate venv
uv sync --all-extras               # Install with dev dependencies
```

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Node.js 18+ (for the browser bridge)

## Running Tests

```bash
pytest tests/ -v                   # Full test suite
pytest tests/test_core/ -v         # Core tests only
pytest tests/test_tools/ -v        # Tool tests only
pytest tests/ -k "test_protocol"   # Run specific tests by name
```

## Code Style

We use **ruff** for linting/formatting and **mypy** for type checking:

```bash
ruff check .                       # Lint
ruff format .                      # Auto-format
mypy core/ tools/ cli/             # Type check
```

Key conventions:
- Type hints on all function signatures
- `from __future__ import annotations` at the top of every module
- Async-first — use `async def` for any I/O operations
- Tests use `pytest-asyncio` with `asyncio_mode = "auto"`

## Project Structure

```
core/           # Agent brain — loop, routing, sessions, gateway
channels/       # Channel adapters (CLI, Telegram, Discord, Slack)
tools/          # Built-in tools organized by category
  system/       # Shell, filesystem
  browser/      # 47 browser tools via Node.js bridge
  knowledge/    # Search, write, index, skills, hub
  documents/    # Document analysis, query, collections
  self_dev/     # Plugin creation, source modification, rollback
  scheduling/   # Cron-based task scheduling
  data/         # LLM calls
skills/         # Best-practice guides (SKILL.md files)
plugins/        # Agent-created tools (grows over time)
cli/            # CLI commands (click)
tests/          # Test suite
```

## Adding a New Tool

1. Create a new file in the appropriate `tools/` subdirectory
2. Extend `BaseTool` from `tools/base.py`
3. Implement the required properties: `name`, `description`, `input_schema`, `permission_level`
4. Implement `async execute(self, params: dict) -> ToolResult`
5. Register the tool in `core/registry.py` → `load_builtin_tools()`
6. Add tests in `tests/test_tools/`
7. Update `tests/test_tools/test_tool_interface.py` (add to `_make_tools()` and update count)

## Pull Request Process

1. Fork the repo and create a branch from `main`
2. Make your changes with tests
3. Ensure all checks pass: `ruff check . && mypy core/ tools/ cli/ && pytest tests/ -v`
4. Open a PR against `main` with a clear description of what changed and why
5. Link any related issues

## Reporting Issues

Use the GitHub issue templates for bug reports and feature requests. Include:
- Steps to reproduce (for bugs)
- Expected vs actual behavior
- Environment details (OS, Python version, relevant config)

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
