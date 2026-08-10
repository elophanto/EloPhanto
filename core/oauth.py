"""User-service OAuth2 — authorization code + PKCE, with a refreshing store.

An assistant that cannot reach your inbox or your calendar is doing the job
with one hand. Reaching them means holding a *user* token — not an API key
the operator pasted, but a delegation the operator granted in a browser, on
their own account, with a scope they saw and consented to.

That token has properties an API key doesn't:

* it expires, often in an hour, so the store must refresh transparently;
* the refresh token is the real prize, so it is kept out of the model's
  reach entirely (the broker only ever hands out access tokens);
* consent is per-scope, so we ask for the narrowest set that does the job.

The flow is authorization code with PKCE (RFC 7636) against a loopback
redirect — the shape Google, Microsoft, and most providers require for a
native app, and the one that never needs a client secret to be safe.

Usage::

    store = OAuthTokenStore(project_root / "data")
    flow = OAuthFlow(provider="google", config=cfg.oauth.providers["google"])
    url, verifier, state = flow.authorization_url()
    # operator opens `url`, approves, provider redirects to loopback
    tokens = await flow.exchange(code, verifier)
    store.save("google", tokens)

    token = store.access_token("google")   # refreshes if stale

The store file is encrypted with the vault when one is unlocked, and falls
back to a ``0600`` JSON file otherwise (with a warning) so a fresh install
still works before the operator has set a master password.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

_STORE_FILE = "oauth_tokens.json"
_ENC_STORE_FILE = "oauth_tokens.enc"

# Refresh this many seconds before the token actually expires, so a call
# that takes a moment to build doesn't race the expiry.
_REFRESH_MARGIN_SECONDS = 120

# Well-known provider endpoints, so the operator only has to supply a
# client id/secret for the common cases.
WELL_KNOWN: dict[str, dict[str, Any]] = {
    "google": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
    },
    "microsoft": {
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scopes": ["offline_access", "Mail.ReadWrite", "Calendars.ReadWrite"],
    },
    "github": {
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scopes": ["repo", "read:user"],
    },
}


class OAuthError(Exception):
    """Raised when an OAuth flow or refresh fails."""


@dataclass
class TokenSet:
    """One provider's tokens plus the metadata needed to refresh them."""

    access_token: str = ""
    refresh_token: str = ""
    token_type: str = "Bearer"
    expires_at: float = 0.0  # unix seconds
    scopes: list[str] = field(default_factory=list)
    account: str = ""  # email / login, for the operator's benefit

    def is_expired(self, margin: int = _REFRESH_MARGIN_SECONDS) -> bool:
        if not self.expires_at:
            return False  # no expiry advertised — assume long-lived
        return time.time() >= (self.expires_at - margin)

    def redacted(self) -> dict[str, Any]:
        """Safe view for logs and tool results."""
        return {
            "account": self.account,
            "scopes": self.scopes,
            "expires_in": (
                max(0, int(self.expires_at - time.time())) if self.expires_at else None
            ),
            "has_refresh_token": bool(self.refresh_token),
        }


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class OAuthFlow:
    """One authorization-code + PKCE exchange against one provider."""

    def __init__(self, provider: str, config: Any) -> None:
        self.provider = provider
        self._cfg = config
        known = WELL_KNOWN.get(provider, {})
        self.auth_url = getattr(config, "auth_url", "") or known.get("auth_url", "")
        self.token_url = getattr(config, "token_url", "") or known.get("token_url", "")
        self.scopes = list(getattr(config, "scopes", None) or known.get("scopes", []))
        self.client_id = getattr(config, "client_id", "")
        self.client_secret = getattr(config, "client_secret", "")
        self.redirect_port = int(getattr(config, "redirect_port", 8765) or 8765)

        if not self.client_id:
            raise OAuthError(
                f"OAuth provider {provider!r} has no client_id. Add one under "
                f"oauth.providers.{provider} in config.yaml."
            )
        if not self.auth_url or not self.token_url:
            raise OAuthError(
                f"OAuth provider {provider!r} needs auth_url and token_url "
                "(no well-known defaults for this provider)."
            )

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.redirect_port}/oauth/callback"

    def authorization_url(self) -> tuple[str, str, str]:
        """Build the consent URL. Returns ``(url, code_verifier, state)``."""
        verifier = _b64url(secrets.token_bytes(48))
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        state = secrets.token_urlsafe(24)

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # Google needs both to actually return a refresh token.
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{self.auth_url}?{urlencode(params)}", verifier, state

    async def exchange(self, code: str, verifier: str) -> TokenSet:
        """Trade an authorization code for tokens."""
        payload = {
            "client_id": self.client_id,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }
        if self.client_secret:
            payload["client_secret"] = self.client_secret
        return await self._token_request(payload)

    async def refresh(self, refresh_token: str) -> TokenSet:
        """Exchange a refresh token for a fresh access token."""
        payload = {
            "client_id": self.client_id,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        if self.client_secret:
            payload["client_secret"] = self.client_secret
        tokens = await self._token_request(payload)
        # Providers usually omit the refresh token on refresh — keep ours.
        if not tokens.refresh_token:
            tokens.refresh_token = refresh_token
        return tokens

    async def _token_request(self, payload: dict[str, str]) -> TokenSet:
        try:
            import httpx
        except ImportError as err:  # pragma: no cover
            raise OAuthError("httpx is required for OAuth") from err

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self.token_url,
                data=payload,
                headers={"Accept": "application/json"},
            )
        if response.status_code >= 400:
            # Never echo the payload — it contains the secret.
            raise OAuthError(
                f"{self.provider} token endpoint returned "
                f"{response.status_code}: {response.text[:300]}"
            )
        try:
            data = response.json()
        except ValueError as err:
            raise OAuthError(
                f"{self.provider} token endpoint returned non-JSON"
            ) from err

        if "error" in data:
            raise OAuthError(
                f"{self.provider} OAuth error: {data.get('error')} — "
                f"{data.get('error_description', '')}"
            )

        expires_in = data.get("expires_in")
        scope_raw = data.get("scope", "")
        return TokenSet(
            access_token=str(data.get("access_token", "")),
            refresh_token=str(data.get("refresh_token", "")),
            token_type=str(data.get("token_type", "Bearer")),
            expires_at=(time.time() + float(expires_in)) if expires_in else 0.0,
            scopes=scope_raw.split() if isinstance(scope_raw, str) else list(scope_raw),
        )

    async def run_local_flow(self, timeout: float = 300.0) -> TokenSet:
        """Full interactive flow: open a browser, catch the loopback redirect.

        Blocks until the operator approves or *timeout* elapses. The local
        server binds loopback only and shuts down the moment it has the code.
        """
        import asyncio
        import webbrowser
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from urllib.parse import parse_qs, urlparse

        url, verifier, state = self.authorization_url()
        received: dict[str, str] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 — stdlib signature
                parsed = urlparse(self.path)
                if not parsed.path.startswith("/oauth/callback"):
                    self.send_response(404)
                    self.end_headers()
                    return
                qs = parse_qs(parsed.query)
                received["code"] = (qs.get("code") or [""])[0]
                received["state"] = (qs.get("state") or [""])[0]
                received["error"] = (qs.get("error") or [""])[0]
                body = (
                    b"<html><body style='font-family:system-ui;padding:40px'>"
                    b"<h2>Authorization received</h2>"
                    b"<p>You can close this tab and return to the terminal.</p>"
                    b"</body></html>"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: Any) -> None:
                pass  # keep the redirect out of stdout

        server = HTTPServer(("127.0.0.1", self.redirect_port), Handler)
        server.timeout = 1.0

        logger.info("Opening browser for %s authorization", self.provider)
        print(f"\nAuthorize EloPhanto for {self.provider}:\n  {url}\n")
        try:
            webbrowser.open(url)
        except Exception:
            pass  # headless host — the printed URL is the fallback

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        try:
            while not received and loop.time() < deadline:
                await loop.run_in_executor(None, server.handle_request)
        finally:
            server.server_close()

        if not received:
            raise OAuthError(
                f"Timed out after {timeout:.0f}s waiting for {self.provider} "
                "authorization."
            )
        if received.get("error"):
            raise OAuthError(
                f"{self.provider} denied authorization: {received['error']}"
            )
        if received.get("state") != state:
            # A mismatched state means the response didn't come from the
            # request we made — treat it as hostile, not as a glitch.
            raise OAuthError(
                "OAuth state mismatch — discarding the response. Try again."
            )
        if not received.get("code"):
            raise OAuthError("No authorization code in the callback.")

        return await self.exchange(received["code"], verifier)


class OAuthTokenStore:
    """Persists token sets and refreshes them on demand.

    Encrypted with the vault when one is available; a ``0600`` JSON file
    otherwise. Refresh tokens never leave this object — :meth:`access_token`
    is the only accessor the broker and tools use.
    """

    def __init__(
        self,
        data_dir: str | Path,
        *,
        vault: Any = None,
        providers: dict[str, Any] | None = None,
    ) -> None:
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._vault = vault
        self._providers = providers or {}
        self._tokens: dict[str, TokenSet] = {}
        self._load()

    # ── persistence ─────────────────────────────────────────────────

    @property
    def _plain_path(self) -> Path:
        return self._dir / _STORE_FILE

    def _load(self) -> None:
        if self._vault is not None:
            try:
                blob = self._vault.get("__oauth_tokens__")
                if blob:
                    self._tokens = {
                        name: TokenSet(**payload) for name, payload in blob.items()
                    }
                    return
            except Exception as exc:
                logger.warning("Could not read OAuth tokens from vault: %s", exc)

        if self._plain_path.exists():
            try:
                raw = json.loads(self._plain_path.read_text(encoding="utf-8"))
                self._tokens = {
                    name: TokenSet(**payload) for name, payload in raw.items()
                }
            except Exception as exc:
                logger.error("OAuth token store is unreadable (%s)", exc)

    def _persist(self) -> None:
        payload = {name: asdict(t) for name, t in self._tokens.items()}
        if self._vault is not None:
            try:
                self._vault.set("__oauth_tokens__", payload)
                # Remove any earlier plaintext copy now that the vault has it.
                if self._plain_path.exists():
                    self._plain_path.unlink()
                return
            except Exception as exc:
                logger.warning(
                    "Could not write OAuth tokens to vault (%s) — "
                    "falling back to a 0600 file",
                    exc,
                )
        self._plain_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(self._plain_path, 0o600)
        except OSError:  # pragma: no cover — non-POSIX
            pass
        logger.warning(
            "OAuth refresh tokens are stored unencrypted at %s. Unlock the "
            "vault (`elophanto vault unlock`) to have them encrypted at rest.",
            self._plain_path,
        )

    def set_vault(self, vault: Any) -> None:
        """Attach a vault and migrate any plaintext store into it."""
        self._vault = vault
        if self._tokens:
            self._persist()

    # ── access ──────────────────────────────────────────────────────

    def save(self, provider: str, tokens: TokenSet) -> None:
        self._tokens[provider] = tokens
        self._persist()

    def get(self, provider: str) -> TokenSet | None:
        return self._tokens.get(provider)

    def forget(self, provider: str) -> bool:
        existed = self._tokens.pop(provider, None) is not None
        if existed:
            self._persist()
        return existed

    def list_providers(self) -> dict[str, dict[str, Any]]:
        """Redacted summary of every connected account."""
        return {name: t.redacted() for name, t in self._tokens.items()}

    def access_token(self, provider: str) -> str | None:
        """Return a valid access token, refreshing synchronously if needed.

        Returns ``None`` when the provider was never connected — callers
        turn that into "run `elophanto oauth login <provider>`".
        """
        tokens = self._tokens.get(provider)
        if tokens is None:
            return None
        if not tokens.is_expired():
            return tokens.access_token
        if not tokens.refresh_token:
            logger.warning(
                "%s access token expired and there is no refresh token — "
                "re-authorization needed",
                provider,
            )
            return None
        try:
            refreshed = self._refresh_sync(provider, tokens.refresh_token)
        except OAuthError as exc:
            logger.error("Refreshing %s failed: %s", provider, exc)
            return None
        refreshed.account = tokens.account or refreshed.account
        self.save(provider, refreshed)
        return refreshed.access_token

    def _refresh_sync(self, provider: str, refresh_token: str) -> TokenSet:
        """Refresh from sync code, whether or not a loop is already running."""
        import asyncio

        cfg = self._providers.get(provider)
        if cfg is None:
            raise OAuthError(
                f"No config for OAuth provider {provider!r}; cannot refresh."
            )
        flow = OAuthFlow(provider, cfg)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(flow.refresh(refresh_token))

        # Already inside an event loop: run the refresh on its own loop in a
        # worker thread. Blocking here is deliberate — callers of
        # access_token() are synchronous by design (the broker resolves
        # inside a tool call), and the refresh is a single sub-second POST.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, flow.refresh(refresh_token)).result(
                timeout=60
            )


def store_from_config(config: Any, vault: Any = None) -> OAuthTokenStore:
    """Build a token store wired to the ``oauth:`` config section."""
    providers = dict(getattr(getattr(config, "oauth", None), "providers", {}) or {})
    return OAuthTokenStore(
        Path(config.project_root) / "data", vault=vault, providers=providers
    )
