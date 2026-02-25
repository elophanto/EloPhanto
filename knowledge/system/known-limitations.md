---
title: Known Limitations
created: 2026-02-17
updated: 2026-02-18
tags: limitations, todo, future
scope: system
---

# Known Limitations

## Not Yet Implemented

- **Web UI**: No web interface (planned Phase 8)
- **Voice interface**: No speech input/output
- **Visual understanding**: No image analysis (no vision model integration)
- **Multi-agent**: Cannot collaborate with other EloPhanto instances
- **Plugin marketplace**: No community skill/plugin sharing
- **Firefox support**: Browser automation only works with Chrome

## Current Constraints

- Single-task sequential execution (no parallel tool calls)
- Browser file:// URLs do not work — must use a local HTTP server for local HTML files
- Chrome cookie encryption means copied profiles don't inherit existing login sessions (sessions rebuild on first use)
- Context window limited to 20 conversation turns (configurable)
- Embedding requires Ollama running locally (or OpenRouter embedding API)
- Protected files (core/executor.py, core/vault.py, etc.) cannot be modified by any tool
- Telegram requires bot token in vault and user IDs in config

## Workarounds

- For local HTML files: start `python3 -m http.server` and navigate to localhost
- For Chrome sessions: log in once through the automated browser, sessions persist after that
- For large contexts: use /clear to reset conversation, task memory persists regardless
