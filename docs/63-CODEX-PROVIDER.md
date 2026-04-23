# 63 — Codex Subscription Provider

> Use your ChatGPT Plus/Pro subscription as EloPhanto's LLM backend.
> Default model: **gpt-5.4**.

**Status:** Complete
**Priority:** P2 — Alternative LLM provider

---

## ⚠️ ToS caveat — read first

OpenAI sells ChatGPT Plus/Pro as a UI product, not as an API. Their terms
say the ChatGPT subscription does **not** include API access, and the
Codex auth path is intended for the Codex CLI agent itself. Repurposing
it for arbitrary scripted calls is a **grey area** — it works technically,
it isn't officially sanctioned, and OpenAI could change/break it at any
time.

**For ToS-clean programmatic access, use the OpenAI API directly** (set
`openai` provider with an API key from [platform.openai.com](https://platform.openai.com)).

See `CODEX_INTEGRATION.md` in the project root for the full integration
reference (endpoints, wire protocol, auth flow, quirks).

---

## Setup

### 1. Install the Codex CLI and log in once

```bash
npm install -g @openai/codex
codex login   # opens browser → OAuth → writes ~/.codex/auth.json
```

### 2. Enable the provider

Codex auto-detects on startup — if `~/.codex/auth.json` exists with
`auth_mode: chatgpt`, the provider auto-enables with `gpt-5.4` as the
default model.

To enable explicitly in `config.yaml`:

```yaml
llm:
  providers:
    codex:
      enabled: true
      base_url: "https://chatgpt.com/backend-api/codex"
      default_model: "gpt-5.4"
```

To route specific tasks to Codex:

```yaml
llm:
  routing:
    planning:
      preferred_provider: codex
      reasoning_effort: high
      models:
        codex: gpt-5.4
```

---

## Available Models

| Model | Context | Notes |
|---|---|---|
| `gpt-5.4` | ~1M tokens | Top model, multimodal, **default** |
| `gpt-5.4-mini` | ~272K | Cheaper variant |
| `gpt-5.3-codex` | | Previous Codex default |
| `gpt-5.3-codex-spark` | | Reasoning-only, free tier |
| `gpt-5.2-codex` | | |
| `gpt-5.1-codex-max` | | |
| `gpt-5.1-codex-mini` | | Smallest |

Availability depends on your ChatGPT subscription tier. The server has
the final say — try and see.

---

## Reasoning Effort

Pass `reasoning_effort` in routing config: `none`, `minimal`, `low`,
`medium`, `high`, `xhigh`.

The adapter clamps per-model automatically (different models accept
different ranges). Examples:

| Model | Clamping |
|---|---|
| `gpt-5.4`, `gpt-5.4-mini` | `minimal` → `low` |
| `gpt-5.1-codex-mini` | `high`/`xhigh` → `medium` |
| `gpt-5.1`, `gpt-5.1-codex` | `xhigh` → `high` |

---

## Limitations

1. **No tool calling.** The Responses API backend uses a different tool
   schema than chat/completions. Use `openai`, `openrouter`, or `zai` for
   tool-heavy work.
2. **Streaming only.** All responses come in as SSE deltas — there's no
   way to get a non-streamed response.
3. **No `temperature` / `max_tokens`.** Reasoning models reject these.
   Variability comes from `reasoning.effort` and prompt design.
4. **Short access token lifetime.** JWT expires every ~30 min. The
   adapter auto-refreshes via the OAuth refresh token.
5. **Token rotation.** Refreshed tokens are persisted back to
   `~/.codex/auth.json` so other processes benefit.

---

## Files

| File | Description |
|---|---|
| `core/codex_adapter.py` | Adapter implementation |
| `CODEX_INTEGRATION.md` | Full integration reference |
| `tests/test_core/test_codex_adapter.py` | 28 unit tests |

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `CodexAuthError: auth file not found` | No `~/.codex/auth.json` | Run `codex login` |
| `CodexAuthError: auth_mode is 'apikey'` | Logged in with API key, not ChatGPT | Run `codex logout && codex login` with ChatGPT account |
| `Codex 400: Unsupported parameter: temperature` | Shouldn't happen (adapter strips) | Report bug |
| `Codex 401` | Token rotation; adapter retries once | Next call should succeed |
| `Codex 404: model not found` | Model not enabled for your tier | Try `gpt-5.3-codex` instead |
| `Codex stream error` | Server-side issue | Retry; fall back to another provider |
