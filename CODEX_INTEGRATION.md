# ChatGPT Codex Subscription Integration Guide

How to use a ChatGPT Plus / Pro subscription's **Codex** auth as a programmatic
LLM backend — endpoints, auth flow, request shape, quirks, and copy-paste
Python.

This is the same mechanism the [openai/codex](https://github.com/openai/codex)
CLI uses internally. We reuse the credentials it stores (`~/.codex/auth.json`)
to call the Codex backend from our own scripts.

---

## ⚠️ ToS caveat — read first

OpenAI sells ChatGPT Plus / Pro as a UI product, not as an API. Their terms
say the ChatGPT subscription does **not** include API access, and the Codex
auth path is intended for the Codex CLI agent itself. Repurposing it for
arbitrary scripted calls (dataset generation, batch inference, etc.) is a
**grey area** — it works technically, it isn't officially sanctioned, and
OpenAI could change/break it at any time. Use at your own risk.

For ToS-clean programmatic access, get a separate API key at
[platform.openai.com](https://platform.openai.com).

---

## What you get

A **multimodal** chat backend that accepts text and images, runs reasoning
models (`gpt-5.5`, `gpt-5.5-mini`, `gpt-5.3-codex`, etc.) with configurable
thinking effort, and is billed against your existing ChatGPT subscription
rather than the platform API.

---

## Endpoint

| What | Value |
|---|---|
| Base URL | `https://chatgpt.com/backend-api/codex` |
| Chat endpoint | `POST https://chatgpt.com/backend-api/codex/responses` |
| Wire protocol | OpenAI **Responses API** (NOT chat/completions) |
| Streaming | **Mandatory** — `stream: true` is required |
| Token URL | `https://auth.openai.com/oauth/token` |

---

## Auth flow

### 1. Bootstrap once with the Codex CLI

```bash
npm i -g @openai/codex
codex login    # opens browser → OAuth flow → writes ~/.codex/auth.json
```

This is a one-time step. After that you can read the credentials directly.

### 2. Read `~/.codex/auth.json`

Schema:
```json
{
  "auth_mode": "chatgpt",
  "tokens": {
    "access_token":  "eyJhbGc...",     // short-lived JWT
    "refresh_token": "...",             // long-lived
    "account_id":    "<uuid>"           // may be missing — extract from JWT instead
  }
}
```

**Important**: only proceed if `auth_mode == "chatgpt"`. If the user logged
in with an API key, `auth_mode` will be `"apikey"` — that path uses
`api.openai.com/v1`, not `chatgpt.com/backend-api/codex`.

### 3. Extract `chatgpt_account_id` from the JWT (if not in auth.json)

The access token is a JWT. Base64url-decode the middle segment and read:

```python
import base64, json

def extract_account_id(access_token: str) -> str:
    _, payload_b64, _ = access_token.split(".", 2)
    pad = "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode((payload_b64 + pad).encode()))
    return payload["https://api.openai.com/auth"]["chatgpt_account_id"]
```

### 4. Refresh when expired

The access token is short-lived (~30 min). Check `exp` in the JWT, refresh if
near expiry:

```python
import httpx

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"   # from openai/codex source
TOKEN_URL = "https://auth.openai.com/oauth/token"

def refresh(refresh_token: str) -> dict:
    r = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=60.0,
    )
    r.raise_for_status()
    return r.json()   # → {access_token, refresh_token, expires_in, ...}
```

The refresh response sometimes includes a rotated `refresh_token` — persist
both back to `~/.codex/auth.json` so the next process benefits.

---

## Required request headers

```
Authorization:        Bearer <access_token>
chatgpt-account-id:   <account_id from JWT>
Content-Type:         application/json
Accept:               text/event-stream
OpenAI-Beta:          responses=experimental
originator:           codex_cli_rs
User-Agent:           <whatever you want>
```

The `chatgpt-account-id` and `originator` headers are required — the backend
rejects calls without them. `OpenAI-Beta: responses=experimental` enables the
Responses API path.

---

## Request body — Responses API shape

This is **NOT** the chat/completions schema. Critical differences:

| chat/completions | Codex Responses API |
|---|---|
| `messages: [{role, content}, ...]` | `input: [{type: "message", role, content: [...]}]` |
| System message via `role: "system"` | `instructions: "..."` (top-level field) |
| `temperature` accepted | **Rejected** — omit |
| `max_tokens` accepted | **Rejected** — omit |
| Streaming optional | **Required** (`stream: true`) |

### Minimal payload

```json
{
  "model": "gpt-5.5",
  "instructions": "You are a helpful assistant.",
  "input": [
    {
      "type": "message",
      "role": "user",
      "content": [{"type": "input_text", "text": "Hello"}]
    }
  ],
  "stream": true,
  "store": false,
  "parallel_tool_calls": false,
  "tool_choice": "none",
  "tools": [],
  "reasoning": {"effort": "medium", "summary": "auto"},
  "include": [],
  "text": {"verbosity": "medium"}
}
```

### Multimodal input — images

Append image content parts to the last user message. PNG bytes go in
base64-encoded data URLs:

```json
{
  "type": "message",
  "role": "user",
  "content": [
    {"type": "input_text", "text": "Transcribe this page."},
    {"type": "input_image",
     "image_url": "data:image/png;base64,iVBORw0KGgo..."}
  ]
}
```

### Multi-turn input

Past assistant turns use `output_text` content type:

```json
"input": [
  {"type": "message", "role": "user",
   "content": [{"type": "input_text", "text": "What is X?"}]},
  {"type": "message", "role": "assistant",
   "content": [{"type": "output_text", "text": "X is ..."}]},
  {"type": "message", "role": "user",
   "content": [{"type": "input_text", "text": "And how does it relate to Y?"}]}
]
```

---

## Reasoning effort (thinking mode)

Pass via `reasoning.effort`. Valid values: `none`, `minimal`, `low`,
`medium`, `high`, `xhigh`.

**Per-model clamping** — different models accept different ranges (rules
extracted from openclaw). Apply client-side before sending:

| Model | Clamping rule |
|---|---|
| `gpt-5.5`, `gpt-5.5-mini` | accepts all; `minimal` → `low` |
| `gpt-5.3-codex`, `gpt-5.2-codex` | accepts all; `minimal` → `low` |
| `gpt-5.1-codex-mini` | high/xhigh → `high`, others → `medium` |
| `gpt-5.1`, `gpt-5.1-codex` | `xhigh` → `high` |
| Older models | `xhigh` → `high` |

`reasoning.summary` controls reasoning trace visibility: `auto` / `concise` /
`detailed` / `none`.

---

## Streaming response — SSE parsing

Response is an SSE (`text/event-stream`). Each line is either empty, a
heartbeat comment (`:` prefix), or `data: <json>`. Accumulate `delta` fields
from `response.output_text.delta` events; finalize on `response.completed`.

Event types you'll see:

| Event type | What to do |
|---|---|
| `response.output_text.delta` | Append `delta` to running text buffer |
| `response.reasoning_summary_text.delta` | Append `delta` to reasoning buffer (optional) |
| `response.completed` / `response.done` | Finalize; pull `usage`, final `model` |
| `response.failed` / `response.error` / `error` | Bail with error |
| Anything else | Ignore |

Safety net: if you get NO `output_text.delta` events but `response.completed`
arrives with a populated `response.output[]`, walk that array's `message`
items and pull `output_text` content parts.

---

## Available models (Pro tier, April 2026)

From the Codex CLI's bundled `models.json`. The server has the final say on
what's actually allowed for your subscription — try and see.

| Slug | Notes |
|---|---|
| `gpt-5.5` | Top model, ~1M context, multimodal |
| `gpt-5.5-mini` | Cheaper variant, ~272K context |
| `gpt-5.3-codex` | Previous Codex default |
| `gpt-5.3-codex-spark` | Reasoning-only, free tier |
| `gpt-5.2-codex` | |
| `gpt-5.1-codex-max` | |
| `gpt-5.1-codex-mini` | |

---

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `400 Unsupported parameter: temperature` | `temperature` in payload | Remove it |
| `400 Unsupported parameter: max_output_tokens` | `max_output_tokens` in payload | Remove it |
| `400 Unsupported parameter: max_tokens` | `max_tokens` in payload | Remove it |
| `401 Unauthorized` | Expired / rotated access token | Refresh and retry once |
| `403 Forbidden` | `chatgpt-account-id` missing or wrong | Re-extract from JWT |
| `404` on the model | Model not enabled for your plan tier | Try `gpt-5.3-codex` instead of `gpt-5.5` |
| Stream never produces deltas | Often a model that returned only via `response.output[]` | Use the safety-net extractor |

---

## Minimal Python client (drop-in)

```python
import asyncio
import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
TOKEN_URL = "https://auth.openai.com/oauth/token"
BASE_URL = "https://chatgpt.com/backend-api/codex"
RESPONSES_URL = f"{BASE_URL}/responses"


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode((s + "=" * (-len(s) % 4)).encode())


def _jwt_payload(token: str) -> dict:
    _, payload_b64, _ = token.split(".", 2)
    return json.loads(_b64url_decode(payload_b64))


def _jwt_exp(token: str) -> float:
    try:
        return float(_jwt_payload(token).get("exp") or 0)
    except Exception:
        return 0.0


def _account_id_from_jwt(token: str) -> str:
    return _jwt_payload(token)["https://api.openai.com/auth"]["chatgpt_account_id"]


class CodexClient:
    def __init__(self, model: str = "gpt-5.5", reasoning_effort: str = "medium"):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.auth_path = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "auth.json"
        self._auth = self._load_auth()
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))

    def _load_auth(self) -> dict:
        data = json.loads(self.auth_path.read_text("utf-8"))
        if data.get("auth_mode") != "chatgpt":
            raise RuntimeError(
                f"{self.auth_path} auth_mode is {data.get('auth_mode')!r}, "
                "expected 'chatgpt'. Run `codex login` with a ChatGPT account."
            )
        tokens = data["tokens"]
        return {
            "access": tokens["access_token"],
            "refresh": tokens["refresh_token"],
            "account_id": tokens.get("account_id") or _account_id_from_jwt(tokens["access_token"]),
            "exp": _jwt_exp(tokens["access_token"]),
        }

    async def _refresh(self) -> None:
        r = await self._http.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._auth["refresh"],
                "client_id": CLIENT_ID,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=60.0,
        )
        r.raise_for_status()
        body = r.json()
        self._auth["access"] = body["access_token"]
        if body.get("refresh_token"):
            self._auth["refresh"] = body["refresh_token"]
        self._auth["account_id"] = (
            body.get("account_id") or _account_id_from_jwt(self._auth["access"])
        )
        self._auth["exp"] = _jwt_exp(self._auth["access"]) or (
            time.time() + float(body.get("expires_in") or 1800)
        )
        # Persist back to disk so the next process benefits
        try:
            raw = json.loads(self.auth_path.read_text("utf-8"))
            raw["tokens"] = {
                "access_token": self._auth["access"],
                "refresh_token": self._auth["refresh"],
                "account_id": self._auth["account_id"],
            }
            self.auth_path.write_text(json.dumps(raw, indent=2), "utf-8")
        except Exception:
            pass

    async def _ensure_fresh(self) -> None:
        if time.time() + 60 >= self._auth["exp"]:
            await self._refresh()

    def _build_input(
        self, messages: list[dict], images: list[bytes] | None = None
    ) -> tuple[str | None, list[dict]]:
        """Convert chat-style messages → (instructions, input_blocks)."""
        instructions_parts, blocks = [], []
        for m in messages:
            role = m.get("role")
            content = m.get("content")
            if role == "system":
                if isinstance(content, str) and content.strip():
                    instructions_parts.append(content)
                continue
            if role not in ("user", "assistant"):
                continue
            if not isinstance(content, str) or not content:
                continue
            part_type = "input_text" if role == "user" else "output_text"
            blocks.append({
                "type": "message",
                "role": role,
                "content": [{"type": part_type, "text": content}],
            })
        # Attach images to the last user block
        if images:
            for i in range(len(blocks) - 1, -1, -1):
                if blocks[i]["role"] == "user":
                    for img in images:
                        b64 = base64.b64encode(img).decode("ascii")
                        blocks[i]["content"].append({
                            "type": "input_image",
                            "image_url": f"data:image/png;base64,{b64}",
                        })
                    break
        instructions = "\n\n".join(instructions_parts) if instructions_parts else None
        return instructions, blocks

    async def chat(
        self, messages: list[dict], *, images: list[bytes] | None = None
    ) -> str:
        await self._ensure_fresh()
        instructions, inp = self._build_input(messages, images)
        payload: dict[str, Any] = {
            "model": self.model,
            "input": inp,
            "stream": True,
            "store": False,
            "parallel_tool_calls": False,
            "tool_choice": "none",
            "tools": [],
            "reasoning": {"effort": self.reasoning_effort, "summary": "auto"},
            "include": [],
            "text": {"verbosity": "medium"},
        }
        if instructions:
            payload["instructions"] = instructions

        headers = {
            "Authorization": f"Bearer {self._auth['access']}",
            "chatgpt-account-id": self._auth["account_id"],
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "OpenAI-Beta": "responses=experimental",
            "originator": "codex_cli_rs",
            "User-Agent": "my-app/1.0",
        }

        text_parts: list[str] = []
        async with self._http.stream("POST", RESPONSES_URL, headers=headers, json=payload) as r:
            if r.status_code == 401:
                # one-shot retry on token rotation
                await self._refresh()
                return await self.chat(messages, images=images)
            if r.status_code >= 400:
                body = (await r.aread()).decode("utf-8", "ignore")
                raise RuntimeError(f"Codex {r.status_code}: {body[:500]}")
            async for line in r.aiter_lines():
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    evt = json.loads(data)
                except json.JSONDecodeError:
                    continue
                etype = evt.get("type", "")
                if etype == "response.output_text.delta":
                    d = evt.get("delta")
                    if isinstance(d, str):
                        text_parts.append(d)
                elif etype in ("response.completed", "response.done"):
                    if not text_parts:
                        # safety net: pull from final response object
                        for item in (evt.get("response") or {}).get("output") or []:
                            if item.get("type") != "message":
                                continue
                            for c in item.get("content") or []:
                                if c.get("type") in ("output_text", "text"):
                                    text_parts.append(c.get("text") or "")
                elif etype in ("response.failed", "response.error", "error"):
                    raise RuntimeError(f"Codex stream error: {json.dumps(evt)[:500]}")
        return "".join(text_parts).strip()

    async def aclose(self):
        await self._http.aclose()


# Usage
async def main():
    client = CodexClient(model="gpt-5.5", reasoning_effort="medium")
    try:
        out = await client.chat([
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "Define entropy in one sentence."},
        ])
        print(out)
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Things that took us a while to figure out

1. **The endpoint speaks Responses API, not chat/completions.** Pointing the
   `openai` Python SDK at the base URL won't work for `client.chat.completions.create()`.
2. **Streaming is mandatory.** No way to get a non-streamed response.
3. **`temperature` and `max_tokens` are 400-rejected.** Reasoning models don't
   accept them. Variability comes from `reasoning.effort` and prompt design.
4. **The `chatgpt-account-id` header is required**, and it's NOT necessarily
   the `account_id` field in `auth.json` — extract it from the JWT to be safe.
5. **The `originator` header is required.** We use `codex_cli_rs` (matches what
   the official CLI sends). Other values may or may not work.
6. **Image input works** via `input_image` content parts on user messages,
   even though the openclaw reference (where we pulled the wire format from)
   only documented text. Tested working on `gpt-5.5`.
7. **Token rotation**: refresh responses sometimes include a new
   `refresh_token`. Persist it back to `auth.json` or you'll lose the chain.
8. **5-min cache miss**: the access token's JWT exp is short. Check `exp`
   before every call rather than relying on a long-running cached value.

---

## References

- [openai/codex](https://github.com/openai/codex) — official Codex CLI source. Read
  `codex-rs/backend-client/`, `codex-rs/login/`, `codex-rs/model-provider-info/`.
- [openclaw/openclaw](https://github.com/openclaw/openclaw) — TypeScript client
  that already wraps this auth path; see also its `pi-ai` dependency.
- [OpenAI Responses API docs](https://platform.openai.com/docs/api-reference/responses) —
  the wire format reference (the platform endpoint is `api.openai.com/v1/responses`,
  but the schema is the same).
