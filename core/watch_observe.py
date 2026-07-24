"""Autonomous evidence collection for the competitive-intelligence organ.

The hard problem with an agent that fills its own evidence register is that a
language model will happily produce a plausible competitor fact that appears
nowhere on the page it just read. A register full of confident fiction is worse
than an empty one, because it *looks* like diligence.

So collection here is built around one checkable guarantee: **every claim must
carry a verbatim excerpt, and the excerpt is verified against the fetched page
before the claim is persisted.** Claims whose excerpt cannot be found in the
source are dropped and counted, not written. That turns "trust the model" into
"trust the substring check".

Fetching is plain HTTP with an optional per-state proxy. Only public,
logged-out pages are collected — authenticated states are operator-entered by
policy (see ``AGENT_SAFE_STATES`` in ``core/watch.py``).
"""

from __future__ import annotations

import html as _html
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Minimum excerpt length. A very short excerpt ("SC") would match almost any
# page by chance and prove nothing.
MIN_EXCERPT_CHARS = 20

_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript|svg)\b[^>]*>.*?</\1>", re.I | re.S
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def html_to_text(raw: str) -> str:
    """Strip HTML to readable text.

    Deliberately dependency-free and conservative: drop script/style bodies,
    turn every remaining tag into whitespace, unescape entities, collapse runs
    of whitespace. Good enough to read prices, offer terms and payment lists
    off a marketing page — and, crucially, good enough to verify an excerpt
    against.
    """
    if not raw:
        return ""
    txt = _SCRIPT_STYLE_RE.sub(" ", raw)
    txt = _TAG_RE.sub(" ", txt)
    txt = _html.unescape(txt)
    return _WS_RE.sub(" ", txt).strip()


def _norm(s: str) -> str:
    """Normalise for comparison: case- and whitespace-insensitive.

    A model may re-wrap or re-case what it quotes; it must not be able to
    invent words. Normalising these two axes keeps the check fair without
    making it toothless.
    """
    return _WS_RE.sub(" ", (s or "").replace(" ", " ")).strip().lower()


def verify_excerpt(excerpt: str, page_text: str) -> bool:
    """True when ``excerpt`` genuinely appears in ``page_text``."""
    e = _norm(excerpt)
    if len(e) < MIN_EXCERPT_CHARS:
        return False
    return e in _norm(page_text)


def filter_verified_claims(
    claims: list[dict[str, Any]], page_text: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split model-proposed claims into (verified, rejected).

    A claim survives only if it carries an excerpt that is actually present in
    the fetched page. Rejections are returned rather than swallowed so the
    caller can report how much was discarded — a high rejection rate is a
    signal worth surfacing, not hiding.
    """
    verified: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for c in claims:
        if not isinstance(c, dict):
            continue
        claim_text = str(c.get("claim") or "").strip()
        excerpt = str(c.get("excerpt") or "").strip()
        if not claim_text:
            continue
        if verify_excerpt(excerpt, page_text):
            verified.append(c)
        else:
            rejected.append(
                {
                    "claim": claim_text,
                    "excerpt": excerpt,
                    "reason": (
                        "excerpt too short"
                        if len(_norm(excerpt)) < MIN_EXCERPT_CHARS
                        else "excerpt not found in source"
                    ),
                }
            )
    return verified, rejected


EXTRACT_SYSTEM = """You extract competitor facts from a web page for a \
competitive-intelligence register.

You are given the visible text of ONE page and the sub-criteria we care about.
Return only facts that are STATED ON THE PAGE.

For each fact:
- subcriterion: the closest match from the provided list, or "" if none fits
- claim:        the fact in one plain sentence
- value_text:   the specific value if there is one (price, count, %, duration)
- excerpt:      a VERBATIM span copied from the page text that proves the claim

Hard rules:
- The excerpt MUST be copied character-for-character from the page text. Do not
  paraphrase, summarise, translate or tidy it. It is checked against the source
  and the fact is DISCARDED if it does not match.
- Quote at least a full clause (20+ characters) so the excerpt actually proves
  something.
- If the page does not support a sub-criterion, omit it. Returning fewer, solid
  facts is correct; padding the list is a failure.
- Never infer from brand knowledge, only from this page.

Return STRICT JSON: {"claims":[{"subcriterion":str,"claim":str,"value_text":str,\
"excerpt":str}]}"""


async def fetch_page(
    url: str,
    *,
    proxy_url: str | None = None,
    timeout: float = 20.0,
    max_chars: int = 40000,
) -> tuple[str, str | None]:
    """Fetch a URL and return ``(text, error)``. Never raises."""
    import httpx

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        kwargs: dict[str, Any] = {
            "timeout": timeout,
            "follow_redirects": True,
            "headers": headers,
        }
        if proxy_url:
            kwargs["proxy"] = proxy_url
        async with httpx.AsyncClient(**kwargs) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                return "", f"HTTP {resp.status_code}"
            return html_to_text(resp.text)[:max_chars], None
    except Exception as e:
        return "", f"{type(e).__name__}: {e}"


async def extract_claims(
    router: Any,
    *,
    page_text: str,
    dimension_name: str,
    subcriteria: list[str],
    max_claims: int = 8,
) -> list[dict[str, Any]]:
    """Ask the model for candidate claims. Returns [] on any failure —
    collection degrades to 'found nothing', never to 'invented something'."""
    import json as _json

    if router is None or not page_text.strip():
        return []
    user = _json.dumps(
        {
            "dimension": dimension_name,
            "subcriteria": subcriteria,
            "max_claims": max_claims,
            "page_text": page_text[:24000],
        }
    )
    try:
        resp = await router.complete(
            messages=[
                {"role": "system", "content": EXTRACT_SYSTEM},
                {"role": "user", "content": user},
            ],
            task_type="analysis",
            temperature=0.0,
            max_tokens=2000,
        )
        text = (resp.content or "").strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            text = text[4:] if text.startswith("json") else text
        data = _json.loads(text)
        claims = data.get("claims", []) if isinstance(data, dict) else []
        return [c for c in claims if isinstance(c, dict)][:max_claims]
    except Exception as e:
        logger.warning("watch_observe: claim extraction failed: %s", e)
        return []
