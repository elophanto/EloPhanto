"""``http_request`` — call any third-party REST API, authenticated, safely.

This is the tool that turns "the agent can browse" into "the agent can act".
Booking a class, filing a ticket, updating a record: all of it is one
authenticated HTTP call, and before this tool the only routes were driving a
browser through the UI or shelling out to ``curl`` (which puts the secret on
a command line, in the process table, and in the transcript).

Three layers stand between the model and the socket:

1. **Network policy** (``core/net_policy``) — no loopback, no RFC1918, no
   cloud metadata, no odd ports; re-checked on every redirect hop.
2. **Scope guard** (``core/scope_guard``) — is this target the operator's to
   change? Destructive calls against systems they have not declared as
   theirs are refused, not merely prompted.
3. **Credential broker** (``core/credentials``) — the secret is resolved
   under policy, travels as an opaque sentinel through params and logs, and
   is substituted in only at the moment the request is built.

The model never receives the credential. It names a slug; the broker does
the rest.
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any
from urllib.parse import urljoin, urlparse

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)

_MAX_BODY_CHARS = 200_000
_DEFAULT_MAX_BODY_CHARS = 40_000

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_ALL_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"})

# Response headers worth showing the model. Everything else is noise, and
# Set-Cookie in particular should not land in a transcript.
_INTERESTING_HEADERS = frozenset(
    {
        "content-type",
        "content-length",
        "location",
        "retry-after",
        "x-request-id",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
    }
)


class HttpRequestTool(BaseTool):
    """Make an authenticated HTTP request to a third-party API."""

    def __init__(self) -> None:
        # All injected by Agent._inject_http_deps().
        self._broker: Any = None
        self._scope_guard: Any = None
        self._net_policy: Any = None
        self._bindings: dict[str, str] = {}

    @property
    def name(self) -> str:
        return "http_request"

    @property
    def group(self) -> str:
        return "http"

    @property
    def description(self) -> str:
        return (
            "Call any HTTP/REST API, optionally authenticated. Use this to take "
            "real actions on external services (book, create, update, fetch data) "
            "instead of driving a browser. Authenticate by naming a credential "
            "slug in `credential` — you never see or handle the secret itself; it "
            "is injected at send time. Reads are unrestricted; writes to systems "
            "the operator has not declared as theirs require confirmation, and "
            "destructive calls against other people's systems are refused."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL including scheme, e.g. https://api.example.com/v1/bookings",
                },
                "method": {
                    "type": "string",
                    "description": "HTTP method (GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS). Default GET.",
                },
                "headers": {
                    "type": "object",
                    "description": "Extra request headers as a flat object.",
                },
                "query": {
                    "type": "object",
                    "description": "Query-string parameters as a flat object.",
                },
                "json": {
                    "type": "object",
                    "description": "JSON request body. Sets Content-Type: application/json.",
                },
                "body": {
                    "type": "string",
                    "description": "Raw string body. Ignored when `json` is given.",
                },
                "credential": {
                    "type": "string",
                    "description": (
                        "Credential slug to authenticate with (e.g. 'trello', "
                        "'gym'). Resolved through the broker under operator "
                        "policy. Omit for unauthenticated calls."
                    ),
                },
                "auth_style": {
                    "type": "string",
                    "description": (
                        "How to present the credential: 'bearer' (default, "
                        "Authorization: Bearer <token>), 'header' (custom header, "
                        "see auth_header), 'query' (query parameter, see "
                        "auth_param), or 'basic' (HTTP Basic; credential must "
                        "hold 'user:pass')."
                    ),
                },
                "auth_header": {
                    "type": "string",
                    "description": "Header name when auth_style='header' (e.g. X-Api-Key).",
                },
                "auth_param": {
                    "type": "string",
                    "description": "Query parameter name when auth_style='query' (e.g. api_key).",
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Why this call is being made. Shown to the operator on "
                        "any approval prompt and recorded in the credential "
                        "audit log. Required when using a credential."
                    ),
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Request timeout. Default 30, max 120.",
                },
                "max_bytes": {
                    "type": "integer",
                    "description": f"Truncate the response body to this many characters (default {_DEFAULT_MAX_BODY_CHARS}).",
                },
            },
            "required": ["url"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        # Static floor. execute() and dynamic_permission_level() escalate
        # per-call based on method and target ownership.
        return PermissionLevel.MODERATE

    def dynamic_permission_level(
        self, params: dict[str, Any]
    ) -> PermissionLevel | None:
        """Escalate by what the call actually does.

        A GET against a public API and a DELETE against an undeclared host
        are the same tool but not the same risk, and the executor gates on
        permission level — so the level has to move with the params.
        """
        method = str(params.get("method", "GET") or "GET").upper()
        if method in _SAFE_METHODS:
            return PermissionLevel.SAFE

        if self._scope_guard is None:
            return PermissionLevel.MODERATE

        try:
            url = str(params.get("url", ""))
            path = urlparse(url).path or "/"
            verdict = self._scope_guard.assess(url, method, path)
        except Exception:  # pragma: no cover — never block on classification
            return PermissionLevel.MODERATE

        if verdict.action == "destructive" or verdict.requires_approval:
            return PermissionLevel.CRITICAL
        if verdict.scope == "owned":
            return PermissionLevel.MODERATE
        return PermissionLevel.DESTRUCTIVE

    # ── execution ───────────────────────────────────────────────────

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        try:
            import httpx
        except ImportError:
            return ToolResult(
                success=False,
                error="httpx is required for http_request (pip install httpx).",
            )

        url = str(params.get("url", "")).strip()
        method = str(params.get("method", "GET") or "GET").upper()
        if method not in _ALL_METHODS:
            return ToolResult(
                success=False,
                error=(
                    f"Unsupported method {method!r}. "
                    f"Use one of: {', '.join(sorted(_ALL_METHODS))}."
                ),
            )

        # ── layer 2: is this the operator's to change? ──────────────
        path = urlparse(url).path or "/"
        verdict = None
        if self._scope_guard is not None:
            try:
                verdict = self._scope_guard.assess(url, method, path)
            except Exception as exc:  # pragma: no cover — defensive
                logger.debug("scope assessment failed: %s", exc)
            if verdict is not None and not verdict.allowed:
                return ToolResult(
                    success=False,
                    error=verdict.reason,
                    data={"scope": verdict.to_dict()},
                )

        # ── layer 1: may we talk to this host at all? ───────────────
        from core.net_policy import NetPolicy, NetPolicyError, check_url

        policy = self._net_policy or NetPolicy()
        try:
            url = check_url(url, policy)
        except NetPolicyError as exc:
            return ToolResult(success=False, error=str(exc))

        # ── layer 3: credential, as a sentinel ──────────────────────
        headers: dict[str, Any] = {
            str(k): str(v) for k, v in (params.get("headers") or {}).items()
        }
        query: dict[str, Any] = dict(params.get("query") or {})
        credential_slug = str(params.get("credential", "") or "").strip()
        sentinel: str | None = None

        if credential_slug:
            if self._broker is None:
                return ToolResult(
                    success=False,
                    error=(
                        "No credential broker is wired, so authenticated "
                        "requests are unavailable. Unlock the vault or "
                        "configure the credentials section."
                    ),
                )
            reason = str(params.get("reason", "") or "").strip()
            if not reason:
                return ToolResult(
                    success=False,
                    error=(
                        "A `reason` is required when using a credential — the "
                        "operator sees it on the approval prompt and it is "
                        "recorded in the audit log."
                    ),
                )
            ref = self._bindings.get(credential_slug, "")
            if not ref:
                # Allow a fully-qualified ref inline, e.g. "env:GYM_TOKEN".
                ref = credential_slug if ":" in credential_slug else ""
            if not ref:
                return ToolResult(
                    success=False,
                    error=(
                        f"Unknown credential slug {credential_slug!r}. Declare it "
                        "under `credentials.bindings` in config.yaml (e.g. "
                        f"{credential_slug}: 'vault:{credential_slug}#token'), or "
                        "pass a full reference like 'env:MY_TOKEN'."
                    ),
                )
            try:
                from core.credentials import CredentialError

                secret = await self._broker.resolve(
                    credential_slug, ref, reason=reason, caller="http_request"
                )
            except CredentialError as exc:
                return ToolResult(success=False, error=str(exc))
            except Exception as exc:  # pragma: no cover — defensive
                return ToolResult(
                    success=False, error=f"Credential resolution failed: {exc}"
                )

            sentinel = self._broker.issue_sentinel(secret)
            style = str(params.get("auth_style", "bearer") or "bearer").lower()
            if style == "bearer":
                headers.setdefault("Authorization", f"Bearer {sentinel}")
            elif style == "header":
                header_name = str(params.get("auth_header", "") or "").strip()
                if not header_name:
                    return ToolResult(
                        success=False,
                        error="auth_style='header' requires `auth_header`.",
                    )
                headers[header_name] = sentinel
            elif style == "query":
                param_name = str(params.get("auth_param", "") or "").strip()
                if not param_name:
                    return ToolResult(
                        success=False,
                        error="auth_style='query' requires `auth_param`.",
                    )
                query[param_name] = sentinel
            elif style == "basic":
                headers.setdefault("Authorization", f"Basic-Plain {sentinel}")
            else:
                return ToolResult(
                    success=False,
                    error=(
                        f"Unknown auth_style {style!r}. Use bearer, header, "
                        "query, or basic."
                    ),
                )

        # Body.
        content: bytes | None = None
        json_body = params.get("json")
        if json_body is not None:
            headers.setdefault("Content-Type", "application/json")
            content = _json.dumps(json_body).encode("utf-8")
        elif params.get("body"):
            content = str(params["body"]).encode("utf-8")

        headers.setdefault("User-Agent", "EloPhanto/1.0 (+https://elophanto.com)")
        headers.setdefault("Accept", "application/json, text/*;q=0.8, */*;q=0.5")

        timeout = min(float(params.get("timeout_seconds") or 30.0), 120.0)
        max_bytes = min(
            int(params.get("max_bytes") or _DEFAULT_MAX_BODY_CHARS), _MAX_BODY_CHARS
        )

        # Materialize sentinels only now, into local structures that never
        # leave this frame.
        real_headers = self._materialize(headers)
        real_query = self._materialize(query)
        real_content = self._materialize_bytes(content)
        real_headers = _fix_basic_auth(real_headers)

        try:
            status, resp_headers, text, final_url, hops = await self._send(
                httpx,
                method=method,
                url=url,
                headers=real_headers,
                query=real_query,
                content=real_content,
                timeout=timeout,
                policy=policy,
                max_bytes=max_bytes,
            )
        except NetPolicyError as exc:
            return ToolResult(success=False, error=f"Redirect refused: {exc}")
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Request failed: {type(exc).__name__}: {self._redact(str(exc))}",
            )
        finally:
            if sentinel is not None:
                # The value is no longer needed; drop it so a later
                # unrelated tool result cannot resurrect it.
                self._broker.forget_sentinels()

        body_text = self._redact(text)
        parsed_json: Any = None
        ctype = str(resp_headers.get("content-type", "")).lower()
        if "json" in ctype or body_text.lstrip()[:1] in "[{":
            try:
                parsed_json = _json.loads(body_text)
            except ValueError:
                parsed_json = None

        data: dict[str, Any] = {
            "status": status,
            "ok": 200 <= status < 300,
            "url": final_url,
            "headers": {
                k: v
                for k, v in resp_headers.items()
                if k.lower() in _INTERESTING_HEADERS
            },
            "body": body_text,
            "truncated": len(text) >= max_bytes,
        }
        if parsed_json is not None:
            data["json"] = self._redact(parsed_json)
        if hops:
            data["redirects"] = hops
        if verdict is not None:
            data["scope"] = verdict.to_dict()

        if not (200 <= status < 300):
            return ToolResult(
                success=False,
                data=data,
                error=f"HTTP {status} from {urlparse(final_url).hostname}",
            )
        return ToolResult(success=True, data=data)

    # ── helpers ─────────────────────────────────────────────────────

    async def _send(
        self,
        httpx: Any,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        query: dict[str, Any],
        content: bytes | None,
        timeout: float,
        policy: Any,
        max_bytes: int,
    ) -> tuple[int, dict[str, str], str, str, list[str]]:
        """Send the request, following redirects with per-hop re-validation.

        httpx's own redirect handling would resolve the next hop without
        consulting network policy, which is precisely the hole an SSRF
        chain walks through — so redirects are followed by hand.
        """
        from core.net_policy import check_url

        hops: list[str] = []
        current = url
        current_method = method
        current_content = content
        current_headers = dict(headers)

        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
            for _ in range(max(policy.max_redirects, 0) + 1):
                response = await client.request(
                    current_method,
                    current,
                    headers=current_headers,
                    params=query or None,
                    content=current_content,
                )
                if response.status_code not in (301, 302, 303, 307, 308):
                    text = response.text
                    return (
                        response.status_code,
                        dict(response.headers),
                        text[:max_bytes],
                        str(response.url),
                        hops,
                    )

                location = response.headers.get("location", "")
                if not location:
                    text = response.text
                    return (
                        response.status_code,
                        dict(response.headers),
                        text[:max_bytes],
                        str(response.url),
                        hops,
                    )

                nxt = urljoin(str(response.url), location)
                nxt = check_url(nxt, policy)  # re-validate every hop
                hops.append(nxt)

                # Never carry credentials across an origin change.
                if _origin(nxt) != _origin(current):
                    current_headers.pop("Authorization", None)
                    current_headers = {
                        k: v
                        for k, v in current_headers.items()
                        if k.lower() not in {"authorization", "cookie"}
                    }

                # 303, and 301/302 on POST, become GET per the spec.
                if response.status_code == 303 or (
                    response.status_code in (301, 302) and current_method == "POST"
                ):
                    current_method = "GET"
                    current_content = None
                current = nxt

        raise RuntimeError(f"Too many redirects (limit {policy.max_redirects})")

    def _materialize(self, obj: Any) -> Any:
        return self._broker.materialize(obj) if self._broker is not None else obj

    def _materialize_bytes(self, content: bytes | None) -> bytes | None:
        if content is None or self._broker is None:
            return content
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return content
        return self._broker.materialize(text).encode("utf-8")

    def _redact(self, obj: Any) -> Any:
        return self._broker.redact(obj) if self._broker is not None else obj


def _origin(url: str) -> tuple[str, str, int]:
    p = urlparse(url)
    return (p.scheme, p.hostname or "", p.port or (443 if p.scheme == "https" else 80))


def _fix_basic_auth(headers: dict[str, str]) -> dict[str, str]:
    """Convert the placeholder Basic header into a real one.

    Basic auth needs the credential base64-encoded, which can only happen
    after the sentinel is materialized — hence the two-step.
    """
    value = headers.get("Authorization", "")
    if not value.startswith("Basic-Plain "):
        return headers
    import base64

    raw = value[len("Basic-Plain ") :]
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    out = dict(headers)
    out["Authorization"] = f"Basic {encoded}"
    return out
