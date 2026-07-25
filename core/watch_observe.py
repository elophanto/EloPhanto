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


# Below this many characters, a "successful" fetch didn't really get the page —
# modern casino/marketing sites are JS apps that serve an empty shell to a
# plain HTTP client. That's the trigger to spend a real browser on it.
THIN_PAGE_CHARS = 600


def _result_text(payload: Any) -> str:
    """Pull page text out of a browser bridge result of unknown shape."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("text", "content", "extracted", "result", "html", "data"):
            v = payload.get(key)
            if isinstance(v, str) and v.strip():
                return v
            if isinstance(v, dict):
                inner = _result_text(v)
                if inner:
                    return inner
    return ""


async def fetch_page_via_browser(
    browser_manager: Any, url: str, *, max_chars: int = 40000
) -> tuple[str, str | None]:
    """Render a page in the agent's real Chrome and return ``(text, error)``.

    This is the answer to JS shells and bot blocks: a real browser executes the
    app and carries a real fingerprint, so pages a plain client cannot read
    become readable. The verification guarantee is unchanged — claims are still
    checked against whatever text actually came back.
    """
    if browser_manager is None:
        return "", "browser unavailable"
    try:
        await browser_manager.call_tool("browser_navigate", {"url": url})
        payload = await browser_manager.call_tool("browser_extract", {})
        text = _result_text(payload)
        if not text.strip():
            # Fall back to raw HTML and strip it ourselves.
            payload = await browser_manager.call_tool("browser_get_html", {})
            text = html_to_text(_result_text(payload))
        text = _WS_RE.sub(" ", text).strip()
        if not text:
            return "", "browser returned no readable text"
        return text[:max_chars], None
    except Exception as e:
        return "", f"browser: {type(e).__name__}: {e}"


async def fetch_page_best_effort(
    url: str,
    *,
    browser_manager: Any = None,
    proxy_url: str | None = None,
    timeout: float = 20.0,
) -> tuple[str, str | None, str]:
    """Fetch a page the cheap way, escalating to the browser when needed.

    Returns ``(text, error, method)``. Plain HTTP is tried first because it is
    fast and contention-free; the browser is reserved for the pages that
    actually need it (empty shells, 403s), since it is a shared, slow resource.
    """
    text, err = await fetch_page(url, proxy_url=proxy_url, timeout=timeout)
    if not err and len(text) >= THIN_PAGE_CHARS:
        return text, None, "http"
    if browser_manager is None:
        # No browser to escalate to. Whatever text we did get is still worth
        # reading — extraction plus excerpt verification already protect
        # against garbage, and discarding a sparse but real page loses genuine
        # evidence. Only a truly empty result is an error.
        if text:
            return text, None, "http_thin"
        return "", err or "page unreadable (likely a JS app)", "http"
    b_text, b_err = await fetch_page_via_browser(browser_manager, url)
    if b_err and not text:
        return "", b_err, "browser"
    if len(b_text) > len(text):
        return b_text, None, "browser"
    return text, None if text else err, "http"


# Link text / hrefs worth following from a homepage: the pages where the
# commercially interesting facts actually live (terms carry AMOE, KYC and
# redemption rules; promo pages carry offers; help pages carry payments).
_LINK_RE = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
_INTERESTING = (
    "terms",
    "promotion",
    "promo",
    "offer",
    "bonus",
    "payment",
    "banking",
    "redeem",
    "redemption",
    "sweepstakes",
    "rules",
    "vip",
    "reward",
    "loyalty",
    "faq",
    "help",
    "support",
    "responsible",
    "coin",
    "shop",
    "store",
    "price",
)


def discover_links(raw_html: str, base_url: str, *, limit: int = 6) -> list[str]:
    """Find the sub-pages of a site most likely to carry scoreable facts."""
    from urllib.parse import urljoin, urlparse

    base_host = urlparse(base_url).netloc.lower()
    seen: set[str] = set()
    out: list[str] = []
    for href, label in _LINK_RE.findall(raw_html or ""):
        text = html_to_text(label).lower()
        target = (href or "").strip()
        if not target or target.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base_url, target)
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https"):
            continue
        # Same site only — we are profiling this brand, not the whole web.
        if parsed.netloc.lower() != base_host:
            continue
        haystack = f"{text} {parsed.path.lower()}"
        if not any(word in haystack for word in _INTERESTING):
            continue
        norm = full.split("#")[0].rstrip("/")
        if norm in seen or norm.rstrip("/") == base_url.rstrip("/"):
            continue
        seen.add(norm)
        out.append(norm)
        if len(out) >= limit:
            break
    return out


EXTRACT_MULTI_SYSTEM = """You extract competitor facts from a web page for a \
competitive-intelligence register.

You are given the visible text of ONE page and a list of dimensions we score
brands on, each with its sub-criteria. Pull out every fact the page supports,
tagging each with the dimension it belongs to.

For each fact:
- dimension:    the exact dimension name from the list
- subcriterion: the closest sub-criterion of that dimension, or ""
- claim:        the fact in one plain sentence
- value_text:   the specific value if there is one (price, count, %, duration)
- excerpt:      a VERBATIM span copied from the page text that proves the claim

Hard rules:
- The excerpt MUST be copied character-for-character from the page text. Do not
  paraphrase, summarise or tidy it. It is checked against the source and the
  fact is DISCARDED if it does not match.
- Quote at least a full clause (20+ characters).
- Only use dimension names from the provided list, spelled exactly.
- Most pages support only a few dimensions. Omit the rest. Returning fewer,
  solid facts is correct; padding is a failure.
- Never infer from brand knowledge, only from this page.

Return STRICT JSON: {"claims":[{"dimension":str,"subcriterion":str,"claim":str,\
"value_text":str,"excerpt":str}]}"""


async def extract_claims_multi(
    router: Any,
    *,
    page_text: str,
    dimensions: list[dict[str, Any]],
    max_claims: int = 25,
) -> list[dict[str, Any]]:
    """Extract facts for MANY dimensions from one page in a single call.

    A full analysis reads a handful of pages against a dozen dimensions; doing
    that as one call per pair is a dozen times the cost for no extra signal,
    since the page text is the same every time. Returns [] on any failure.
    """
    import json as _json

    if router is None or not page_text.strip() or not dimensions:
        return []
    payload = {
        "dimensions": [
            {"name": d["name"], "subcriteria": d.get("subcriteria", [])}
            for d in dimensions
        ],
        "max_claims": max_claims,
        "page_text": page_text[:24000],
    }
    try:
        resp = await router.complete(
            messages=[
                {"role": "system", "content": EXTRACT_MULTI_SYSTEM},
                {"role": "user", "content": _json.dumps(payload)},
            ],
            task_type="analysis",
            temperature=0.0,
            max_tokens=4000,
        )
        text = (resp.content or "").strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            text = text[4:] if text.startswith("json") else text
        data = _json.loads(text)
        claims = data.get("claims", []) if isinstance(data, dict) else []
        valid_names = {d["name"] for d in dimensions}
        return [
            c
            for c in claims
            if isinstance(c, dict) and c.get("dimension") in valid_names
        ][:max_claims]
    except Exception as e:
        logger.warning("watch: multi-dimension extraction failed: %s", e)
        return []


async def collect_pages(
    start_url: str,
    *,
    browser_manager: Any = None,
    proxy_url: str | None = None,
    max_pages: int = 4,
) -> list[dict[str, Any]]:
    """Read a brand's site: the landing page plus the sub-pages that matter.

    Terms, promotions and payment pages carry most of the scoreable detail, so
    a homepage-only read badly under-covers the frame. Each page escalates to
    the browser independently — a site may serve a static terms page but a JS
    lobby.
    """
    pages: list[dict[str, Any]] = []
    text, err, method = await fetch_page_best_effort(
        start_url, browser_manager=browser_manager, proxy_url=proxy_url
    )
    pages.append({"url": start_url, "text": text, "error": err, "method": method})

    if max_pages <= 1:
        return pages

    # Link discovery needs markup, not stripped text.
    raw = ""
    try:
        import httpx

        kwargs: dict[str, Any] = {"timeout": 15.0, "follow_redirects": True}
        if proxy_url:
            kwargs["proxy"] = proxy_url
        async with httpx.AsyncClient(**kwargs) as client:
            r = await client.get(start_url, headers={"User-Agent": "Mozilla/5.0"})
            raw = r.text if r.status_code < 400 else ""
    except Exception:
        raw = ""
    if len(raw) < 2000 and browser_manager is not None:
        try:
            payload = await browser_manager.call_tool("browser_get_html", {})
            raw = _result_text(payload) or raw
        except Exception:
            pass

    for link in discover_links(raw, start_url, limit=max_pages - 1):
        t, e, m = await fetch_page_best_effort(
            link, browser_manager=browser_manager, proxy_url=proxy_url
        )
        pages.append({"url": link, "text": t, "error": e, "method": m})
    return pages


SCORE_SYSTEM = """You score one brand on one dimension of a competitive analysis.

Scale:
  1 materially behind the market; a clear disadvantage
  2 below market; several meaningful weaknesses
  3 market parity; credible but undifferentiated
  4 above market; a demonstrable competitive strength
  5 market-leading; distinctive, valuable and hard to match

You are given the evidence collected for this brand, and (where available) the
evidence collected for its peers on the same dimension.

Rules:
- Score ONLY from the evidence given. Do not use outside knowledge of the brand.
- Judge relative to the peer evidence when it exists. When it does not, say so in
  the rationale and score conservatively — an unbenchmarked score is provisional.
- If the evidence is too thin to support any judgement, return score: null. A
  blank score is a correct answer; a guessed one is not.
- The rationale must cite what in the evidence drove the score, in 1-2 sentences.

Return STRICT JSON: {"score": number|null, "rationale": str, "provisional": bool}"""


async def score_dimension(
    router: Any,
    *,
    dimension_name: str,
    subcriteria: list[str],
    own_claims: list[str],
    peer_claims: dict[str, list[str]] | None = None,
) -> dict[str, Any] | None:
    """Judge a 1-5 score from collected evidence. ``None`` on failure."""
    import json as _json

    if router is None or not own_claims:
        return None
    payload = {
        "dimension": dimension_name,
        "subcriteria": subcriteria,
        "evidence_for_this_brand": own_claims[:40],
        "evidence_for_peers": {k: v[:10] for k, v in (peer_claims or {}).items()},
    }
    try:
        resp = await router.complete(
            messages=[
                {"role": "system", "content": SCORE_SYSTEM},
                {"role": "user", "content": _json.dumps(payload)},
            ],
            task_type="analysis",
            temperature=0.1,
            max_tokens=500,
        )
        text = (resp.content or "").strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            text = text[4:] if text.startswith("json") else text
        data = _json.loads(text)
        if not isinstance(data, dict):
            return None
        raw = data.get("score")
        score = None if raw is None else float(raw)
        if score is not None and not (1 <= score <= 5):
            return None
        return {
            "score": score,
            "rationale": str(data.get("rationale") or "")[:1000],
            "provisional": bool(data.get("provisional")),
        }
    except Exception as e:
        logger.warning("watch: scoring failed for %s: %s", dimension_name, e)
        return None


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
