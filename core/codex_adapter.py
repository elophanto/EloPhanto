"""ChatGPT Codex subscription adapter.

Uses the Codex CLI's OAuth credentials (~/.codex/auth.json) to call
ChatGPT's Responses API backend. This is the same mechanism the
openai/codex CLI uses internally — we reuse the stored tokens.

Key differences from OpenAI API:
- Endpoint: ``https://chatgpt.com/backend-api/codex/responses``
- Wire protocol: **Responses API** (NOT chat/completions)
- Streaming is mandatory (``stream: true`` required)
- ``temperature`` and ``max_tokens`` are rejected (400 errors)
- Requires ``chatgpt-account-id`` header from JWT payload
- Requires ``originator: codex_cli_rs`` header
- Messages use ``input`` blocks with ``input_text`` / ``output_text``
  content types, not ``messages: [{role, content}]``.

ToS caveat: ChatGPT subscription is sold as a UI product, not an API.
This path is grey-area — it works technically but isn't officially
sanctioned. For ToS-clean access use the OpenAI API directly.

See ``CODEX_INTEGRATION.md`` for the full integration reference.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

from core.config import Config

logger = logging.getLogger(__name__)

# OAuth client used by the Codex CLI — lifted from openai/codex source
_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_TOKEN_URL = "https://auth.openai.com/oauth/token"
_BASE_URL = "https://chatgpt.com/backend-api/codex"
_RESPONSES_URL = f"{_BASE_URL}/responses"

# Refresh access token when within this many seconds of expiry
_REFRESH_BUFFER_SECONDS = 60

# Reasoning effort clamping per model family (from openai/codex source).
# Different models reject different effort values — clamp before sending.
_EFFORT_CLAMP: dict[str, dict[str, str]] = {
    # gpt-5.5 family rejects "minimal" (only accepts none/low/medium/high/xhigh)
    "gpt-5.5": {"minimal": "low"},
    "gpt-5.5-mini": {"minimal": "low"},
    "gpt-5.5-codex": {"minimal": "low"},
    "gpt-5.5": {"minimal": "low"},
    "gpt-5.5-mini": {"minimal": "low"},
    "gpt-5.3-codex": {"minimal": "low"},
    "gpt-5.2-codex": {"minimal": "low"},
    "gpt-5.1-codex-mini": {
        "high": "medium",
        "xhigh": "medium",
        "minimal": "medium",
        "low": "medium",
    },
    "gpt-5.1": {"xhigh": "high"},
    "gpt-5.1-codex": {"xhigh": "high"},
}

# Approximate costs for reporting only — ChatGPT subscription is flat-rate,
# but we still track token usage for observability. Values from platform
# API pricing as a proxy.
_COSTS = {
    # gpt-5.5 pricing not yet published; using gpt-5.5 rates as a proxy
    "gpt-5.5": {"input": 0.003, "output": 0.015},
    "gpt-5.5-mini": {"input": 0.0008, "output": 0.004},
    "gpt-5.5-codex": {"input": 0.002, "output": 0.010},
    "gpt-5.5": {"input": 0.003, "output": 0.015},
    "gpt-5.5-mini": {"input": 0.0008, "output": 0.004},
    "gpt-5.3-codex": {"input": 0.002, "output": 0.010},
    "gpt-5.2-codex": {"input": 0.002, "output": 0.010},
    "gpt-5.1-codex-max": {"input": 0.002, "output": 0.010},
    "gpt-5.1-codex": {"input": 0.002, "output": 0.010},
    "gpt-5.1-codex-mini": {"input": 0.0005, "output": 0.002},
    "gpt-5.1": {"input": 0.002, "output": 0.010},
}


class CodexAuthError(RuntimeError):
    """Raised when Codex auth is missing, invalid, or wrong mode."""


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode())


def _jwt_payload(token: str) -> dict[str, Any]:
    """Decode a JWT's middle (payload) segment without verification."""
    parts = token.split(".", 2)
    if len(parts) < 2:
        raise CodexAuthError("Malformed access token — not a JWT")
    return json.loads(_b64url_decode(parts[1]))


def _jwt_exp(token: str) -> float:
    try:
        return float(_jwt_payload(token).get("exp") or 0)
    except Exception:
        return 0.0


def _account_id_from_jwt(token: str) -> str:
    payload = _jwt_payload(token)
    auth = payload.get("https://api.openai.com/auth") or {}
    acc = auth.get("chatgpt_account_id")
    if not acc:
        raise CodexAuthError(
            "JWT missing chatgpt_account_id — is this a ChatGPT subscription token?"
        )
    return str(acc)


def _clamp_effort(model: str, effort: str) -> str:
    """Clamp reasoning effort to a value the model accepts."""
    if not effort:
        return effort
    rules = _EFFORT_CLAMP.get(model, {})
    return rules.get(effort, effort)


class CodexAdapter:
    """Client for ChatGPT Codex subscription backend (Responses API)."""

    def __init__(self, config: Config) -> None:
        self._config = config
        codex_cfg = config.llm.providers.get("codex")
        if not codex_cfg:
            raise ValueError("Codex provider not configured")

        # Auth file location — defaults to ~/.codex/auth.json, can be
        # overridden via CODEX_HOME env var or provider config api_key path.
        auth_path_env = os.environ.get("CODEX_HOME")
        if auth_path_env:
            self._auth_path = Path(auth_path_env) / "auth.json"
        elif codex_cfg.api_key and codex_cfg.api_key.endswith(".json"):
            # Allow pointing api_key at a custom auth.json location
            self._auth_path = Path(codex_cfg.api_key).expanduser()
        else:
            self._auth_path = Path.home() / ".codex" / "auth.json"

        self._default_model = codex_cfg.default_model or "gpt-5.5"
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))
        self._auth: dict[str, Any] = {}
        self._load_auth()

    def _load_auth(self) -> None:
        """Read credentials from auth.json and validate."""
        if not self._auth_path.exists():
            raise CodexAuthError(
                f"Codex auth file not found at {self._auth_path}. "
                f"Run 'npm i -g @openai/codex && codex login' first."
            )
        try:
            data = json.loads(self._auth_path.read_text("utf-8"))
        except Exception as e:
            raise CodexAuthError(f"Failed to parse {self._auth_path}: {e}") from e

        mode = data.get("auth_mode")
        if mode != "chatgpt":
            raise CodexAuthError(
                f"{self._auth_path} auth_mode is {mode!r}, expected 'chatgpt'. "
                "Run 'codex login' with a ChatGPT account."
            )

        tokens = data.get("tokens") or {}
        access = tokens.get("access_token")
        refresh = tokens.get("refresh_token")
        if not access or not refresh:
            raise CodexAuthError("auth.json missing access_token or refresh_token")

        account_id = tokens.get("account_id") or _account_id_from_jwt(access)

        self._auth = {
            "access": access,
            "refresh": refresh,
            "account_id": account_id,
            "exp": _jwt_exp(access),
        }

    def _persist_auth(self) -> None:
        """Write updated tokens back to auth.json so other processes benefit."""
        try:
            raw = json.loads(self._auth_path.read_text("utf-8"))
            raw["tokens"] = {
                "access_token": self._auth["access"],
                "refresh_token": self._auth["refresh"],
                "account_id": self._auth["account_id"],
            }
            self._auth_path.write_text(json.dumps(raw, indent=2), "utf-8")
        except Exception as e:
            logger.warning("Failed to persist refreshed Codex tokens: %s", e)

    async def _refresh_tokens(self) -> None:
        """Exchange refresh_token for a new access_token."""
        response = await self._client.post(
            _TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._auth["refresh"],
                "client_id": _CLIENT_ID,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=60.0,
        )
        if response.status_code != 200:
            raise CodexAuthError(
                f"Token refresh failed ({response.status_code}): "
                f"{response.text[:200]}"
            )
        body = response.json()
        self._auth["access"] = body["access_token"]
        if body.get("refresh_token"):
            self._auth["refresh"] = body["refresh_token"]
        # account_id may rotate — re-extract from new JWT
        try:
            self._auth["account_id"] = _account_id_from_jwt(self._auth["access"])
        except CodexAuthError:
            pass
        self._auth["exp"] = _jwt_exp(self._auth["access"]) or (
            time.time() + float(body.get("expires_in") or 1800)
        )
        self._persist_auth()
        logger.info(
            "Refreshed Codex access token (exp in %ds)",
            int(self._auth["exp"] - time.time()),
        )

    async def _ensure_fresh(self) -> None:
        """Refresh access token if expired or near expiry."""
        if time.time() + _REFRESH_BUFFER_SECONDS >= self._auth["exp"]:
            await self._refresh_tokens()

    def _build_input(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Convert chat-style messages to (instructions, input_blocks).

        - System messages collapse into top-level ``instructions`` field.
        - User messages use ``input_text`` content parts.
        - Assistant messages use ``output_text`` content parts.
        - Image blocks (list-typed content with ``image_url``) are passed
          through as ``input_image`` parts on user messages.
        - Assistant ``tool_calls`` become Responses API ``function_call``
          items so the model has the correct prior-action context.
        - ``role: tool`` messages become ``function_call_output`` items
          referencing the ``tool_call_id`` (mapped to ``call_id``).
        """
        instructions_parts: list[str] = []
        blocks: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "system":
                if isinstance(content, str) and content.strip():
                    instructions_parts.append(content)
                continue

            # Tool/function results from the agent loop
            if role == "tool":
                call_id = msg.get("tool_call_id") or ""
                output = content if isinstance(content, str) else json.dumps(content)
                if call_id:
                    blocks.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": output or "",
                        }
                    )
                continue

            if role not in ("user", "assistant"):
                continue

            # Normalize content into a list of parts
            parts: list[dict[str, Any]] = []
            part_type = "input_text" if role == "user" else "output_text"

            if isinstance(content, str):
                if content:
                    parts.append({"type": part_type, "text": content})
            elif isinstance(content, list):
                for p in content:
                    if not isinstance(p, dict):
                        continue
                    ptype = p.get("type")
                    if ptype == "text":
                        txt = p.get("text", "")
                        if txt:
                            parts.append({"type": part_type, "text": txt})
                    elif ptype == "image_url" and role == "user":
                        url_val = p.get("image_url")
                        if isinstance(url_val, dict):
                            url = url_val.get("url", "")
                        else:
                            url = url_val or ""
                        if url:
                            parts.append({"type": "input_image", "image_url": url})

            if parts:
                blocks.append({"type": "message", "role": role, "content": parts})

            # Preserve assistant tool calls as function_call items so the
            # model knows what it previously called when a tool result follows.
            if role == "assistant":
                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    blocks.append(
                        {
                            "type": "function_call",
                            "call_id": tc.get("id", ""),
                            "name": fn.get("name", ""),
                            "arguments": fn.get("arguments", "") or "",
                        }
                    )

        instructions = "\n\n".join(instructions_parts) if instructions_parts else None
        return instructions, blocks

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert chat/completions tool schemas to Responses API shape.

        chat/completions: ``{type: "function", function: {name, description, parameters}}``
        Responses API:    ``{type: "function", name, description, parameters}``
        """
        converted: list[dict[str, Any]] = []
        for t in tools:
            if not isinstance(t, dict):
                continue
            if t.get("type") == "function" and "function" in t:
                fn = t["function"] or {}
                converted.append(
                    {
                        "type": "function",
                        "name": fn.get("name", ""),
                        "description": fn.get("description", ""),
                        "parameters": fn.get("parameters") or {"type": "object"},
                    }
                )
            else:
                # Already in Responses API shape — pass through
                converted.append(t)
        return converted

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,  # noqa: ARG002 — accepted for API parity, not sent
        max_tokens: (
            int | None
        ) = None,  # noqa: ARG002 — accepted for API parity, not sent
        reasoning_effort: str = "medium",
    ) -> Any:
        """Make a Responses API streaming call, return aggregated text."""
        from core.router import LLMResponse

        await self._ensure_fresh()

        instructions, input_blocks = self._build_input(messages)
        if not input_blocks:
            # Codex rejects empty input arrays — stub a user message.
            input_blocks = [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Please proceed."}],
                }
            ]

        effort = _clamp_effort(model, reasoning_effort or "medium")

        converted_tools = self._convert_tools(tools or [])

        payload: dict[str, Any] = {
            "model": model,
            "input": input_blocks,
            "stream": True,
            "store": False,
            "parallel_tool_calls": bool(converted_tools),
            "tool_choice": "auto" if converted_tools else "none",
            "tools": converted_tools,
            "reasoning": {"effort": effort, "summary": "auto"},
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
            "User-Agent": "elophanto-codex/1.0",
        }

        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        # function_call items in progress — keyed by item index in the output.
        # Each value: {"id", "name", "args_parts": [str]}.
        fn_calls_by_index: dict[int, dict[str, Any]] = {}
        input_tokens = 0
        output_tokens = 0
        finish_reason = "stop"
        final_model = model

        async with self._client.stream(
            "POST", _RESPONSES_URL, headers=headers, json=payload
        ) as response:
            if response.status_code == 401:
                # One-shot retry on token rotation
                await self._refresh_tokens()
                return await self.complete(
                    messages, model, tools, 0.0, None, reasoning_effort
                )
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", "ignore")
                raise RuntimeError(f"Codex {response.status_code}: {body[:500]}")

            async for line in response.aiter_lines():
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
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
                elif etype == "response.reasoning_summary_text.delta":
                    d = evt.get("delta")
                    if isinstance(d, str):
                        reasoning_parts.append(d)
                elif etype == "response.output_item.added":
                    item = evt.get("item") or {}
                    if item.get("type") == "function_call":
                        idx = evt.get("output_index", len(fn_calls_by_index))
                        fn_calls_by_index[idx] = {
                            "id": item.get("call_id") or item.get("id") or "",
                            "name": item.get("name") or "",
                            "args_parts": [],
                        }
                elif etype == "response.function_call_arguments.delta":
                    idx = evt.get("output_index")
                    d = evt.get("delta")
                    if (
                        isinstance(idx, int)
                        and isinstance(d, str)
                        and idx in fn_calls_by_index
                    ):
                        fn_calls_by_index[idx]["args_parts"].append(d)
                elif etype == "response.output_item.done":
                    item = evt.get("item") or {}
                    if item.get("type") == "function_call":
                        idx = evt.get("output_index", -1)
                        # Finalize: prefer the server's complete arguments string
                        args_full = item.get("arguments")
                        if isinstance(idx, int) and idx in fn_calls_by_index:
                            if isinstance(args_full, str) and args_full:
                                fn_calls_by_index[idx]["args_parts"] = [args_full]
                            # Also refresh name/id in case they arrived late
                            if item.get("call_id"):
                                fn_calls_by_index[idx]["id"] = item["call_id"]
                            if item.get("name"):
                                fn_calls_by_index[idx]["name"] = item["name"]
                elif etype in ("response.completed", "response.done"):
                    resp_obj = evt.get("response") or {}
                    # Safety net: walk final output[] for any missed content
                    for out_idx, item in enumerate(resp_obj.get("output") or []):
                        itype = item.get("type")
                        if itype == "message" and not text_parts:
                            for c in item.get("content") or []:
                                if c.get("type") in ("output_text", "text"):
                                    text_parts.append(c.get("text") or "")
                        elif itype == "function_call":
                            # Pick up any function calls not seen during streaming
                            if out_idx not in fn_calls_by_index:
                                fn_calls_by_index[out_idx] = {
                                    "id": item.get("call_id") or item.get("id") or "",
                                    "name": item.get("name") or "",
                                    "args_parts": [item.get("arguments") or ""],
                                }
                    usage = resp_obj.get("usage") or {}
                    input_tokens = int(usage.get("input_tokens") or 0)
                    output_tokens = int(usage.get("output_tokens") or 0)
                    final_model = resp_obj.get("model") or model
                    status = resp_obj.get("status") or "completed"
                    finish_reason = "stop" if status == "completed" else str(status)
                elif etype in ("response.failed", "response.error", "error"):
                    raise RuntimeError(f"Codex stream error: {json.dumps(evt)[:500]}")

        content_text = "".join(text_parts).strip()

        # Assemble tool_calls in the shape downstream code expects
        # (matches chat/completions: {id, type: "function", function: {name, arguments}}).
        tool_calls_out: list[dict[str, Any]] | None = None
        if fn_calls_by_index:
            tool_calls_out = []
            for idx in sorted(fn_calls_by_index.keys()):
                fc = fn_calls_by_index[idx]
                tool_calls_out.append(
                    {
                        "id": fc["id"],
                        "type": "function",
                        "function": {
                            "name": fc["name"],
                            "arguments": "".join(fc["args_parts"]),
                        },
                    }
                )
            finish_reason = "tool_calls"

        # Match chat/completions convention: content is None when the
        # assistant produced only tool calls (no text) — downstream code
        # uses `content is None` to detect pure tool-call turns.
        content: str | None = content_text if content_text else None
        if tool_calls_out and not content_text:
            content = None

        # Surface the reasoning trace at debug level (captured but not
        # persisted — helps debug why models picked a particular tool).
        if reasoning_parts and logger.isEnabledFor(logging.DEBUG):
            logger.debug("[codex reasoning] %s", "".join(reasoning_parts)[:500])

        # Heuristic truncation detection — matches ZaiAdapter / KimiAdapter
        # so the provider_tracker can surface stealth-censoring / cutoffs.
        from core.provider_tracker import detect_truncation

        truncated = detect_truncation(finish_reason, output_tokens, content)

        costs = _COSTS.get(model, {"input": 0.002, "output": 0.010})
        cost_estimate = (
            input_tokens * costs["input"] / 1_000_000
            + output_tokens * costs["output"] / 1_000_000
        )

        return LLMResponse(
            content=content,
            model_used=final_model,
            provider="codex",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_estimate=cost_estimate,
            tool_calls=tool_calls_out,
            finish_reason=finish_reason,
            suspected_truncated=truncated,
        )

    async def health_check(self) -> bool:
        """Verify Codex auth works — refresh tokens and confirm JWT valid."""
        try:
            await self._ensure_fresh()
            # Basic sanity: we have a valid account_id and non-expired token
            return bool(self._auth.get("access")) and self._auth["exp"] > time.time()
        except Exception as e:
            logger.warning(f"Codex health check failed: {e}")
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
