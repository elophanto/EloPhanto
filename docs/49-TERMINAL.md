# Phase 16 — Terminal CLI Improvements

## Overview

Two improvements to the terminal (gateway mode) CLI: input protection that prevents autonomous mind output from clobbering in-progress user input, and cosmetic enhancements to the mind cycle display.

## Problem: Input Clobbering

The CLI REPL ran `Prompt.ask()` (Rich) in a thread executor to unblock the asyncio event loop while waiting for user input. The autonomous mind runs asynchronously in the same process and calls `console.print()` when it wakes, uses a tool, or sleeps.

Both paths share `sys.stdout`. When the mind printed during user input, terminal output was written directly to the same line as the user's typing:

```
  ❯ tell me abou──────────── MIND  cycle #12 ─────────────
  Budget: [██████░░░░]  $2.10 / $4.00
  ● web_search   trending topics
t the weather
```

The prompt line was corrupted and the user had to re-type.

## Fix: `prompt_toolkit` + `patch_stdout`

Replaced `Prompt.ask()` in executor with `prompt_toolkit`'s `PromptSession.prompt_async()`, wrapped in `patch_stdout(raw=True)`.

```python
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout as pt_patch_stdout

session = PromptSession()
_prompt = FormattedText([("bold", "  ❯ ")])

with pt_patch_stdout(raw=True):
    while self._running:
        user_input = await session.prompt_async(_prompt)
```

### How it works

`patch_stdout(raw=True)` replaces `sys.stdout` with a proxy (`_StdoutProxy`) that intercepts every write. When a write arrives while the user is typing, the proxy:

1. Temporarily hides the prompt line
2. Writes the content above it
3. Redraws the prompt with the user's partial input intact

Rich's `Console.file` property evaluates `sys.stdout` at call time (not at construction time), so all `console.print()` calls automatically route through the proxy — no manual patching required.

### Result

Mind cycles, tool use, goal events, and all other async output appear above the input line. The user's in-progress text is never touched.

## Beautification: Mind Cycle Timestamp

The mind wakeup separator now shows wall-clock time:

```
──────── MIND  cycle #12 · 8 today · 14:37 ────────
```

Previously it was `cycle #12 · 8 today` with no timestamp. The addition makes it easy to correlate mind cycles with real time without checking logs.

## Dependency

`prompt-toolkit>=3.0` added to `pyproject.toml` (installed: 3.0.52 + wcwidth 0.6.0).

## Files Changed

| File | Change |
|------|--------|
| `channels/cli_adapter.py` | `PromptSession`, `patch_stdout`, timestamp on mind wakeup Rule |
| `pyproject.toml` | `prompt-toolkit>=3.0` dependency |
