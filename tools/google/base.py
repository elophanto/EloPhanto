"""Shared plumbing for Google Workspace tools.

Both Gmail and Calendar are ordinary REST APIs behind one OAuth token, so
the interesting part is not the HTTP — it is making sure the token is fresh,
the error messages tell the operator what to actually do, and a Google
outage reads differently from a missing consent.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0


class GoogleAuthMissing(Exception):
    """Raised when the operator has not connected their Google account."""


async def google_request(
    token_store: Any,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    provider: str = "google",
) -> dict[str, Any]:
    """Make one authenticated Google API call and return parsed JSON.

    Raises :class:`GoogleAuthMissing` when there is no usable token, so the
    caller can render the one-line fix instead of a stack trace.
    """
    try:
        import httpx
    except ImportError as err:  # pragma: no cover
        raise RuntimeError("httpx is required for Google tools") from err

    if token_store is None:
        raise GoogleAuthMissing(
            "OAuth is not configured. Add a `oauth.providers.google` section "
            "with your client_id to config.yaml, then run "
            "`elophanto oauth login google`."
        )

    token = token_store.access_token(provider)
    if not token:
        raise GoogleAuthMissing(
            "Google account is not connected (or the grant expired). Run "
            "`elophanto oauth login google` to connect it."
        )

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.request(
            method,
            url,
            params=params,
            json=json_body,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

    if response.status_code == 401:
        raise GoogleAuthMissing(
            "Google rejected the token (401). The grant was probably revoked "
            "— run `elophanto oauth login google` to reconnect."
        )
    if response.status_code == 403:
        detail = _error_detail(response)
        raise GoogleAuthMissing(
            f"Google refused the request (403): {detail}. This usually means "
            "the connected account lacks the scope for this action — "
            "reconnect with `elophanto oauth login google` after widening "
            "`oauth.providers.google.scopes`."
        )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Google API {response.status_code}: {_error_detail(response)}"
        )

    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text[:2000]}


def _error_detail(response: Any) -> str:
    try:
        payload = response.json()
    except Exception:
        return response.text[:200]
    err = payload.get("error")
    if isinstance(err, dict):
        return str(err.get("message", ""))[:300] or str(err)[:300]
    return str(err or payload)[:300]
