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

_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript|svg)\b[^>]*>.*?</\1>", re.I | re.S)
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
- MARKET EVENTS ARE NEVER DROPPED. If the page announces that the brand is
  closing, exiting a state or country, being acquired, merging, rebranding,
  launching in a new state, or under a regulatory notice, file it as a
  claim under the closest dimension (usually the availability / market
  dimension, else the marketing one) with the date in value_text — even if
  it fits no sub-criterion. A shutdown notice is the most material fact a
  page can carry; a register that misses it because it "fits no dimension"
  has failed (LuckyLand, 2026-08-16: "closing September 14, 2026" was on
  the homepage and the register recorded nothing).

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
            {"name": d["name"], "subcriteria": d.get("subcriteria", [])} for d in dimensions
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
        return [c for c in claims if isinstance(c, dict) and c.get("dimension") in valid_names][
            :max_claims
        ]
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

    # Link discovery needs markup, not stripped text. Raw HTTP first —
    # cheap, and for a server-rendered site it carries the whole nav.
    raw = await _fetch_raw_html(start_url, proxy_url=proxy_url)
    links = discover_links(raw, start_url, limit=max_pages - 1)

    # A JS-app site serves an empty shell to a plain client: big HTML, no
    # anchors. That is precisely the site the real browser exists for — the
    # rendered DOM knows the nav the shell hides — so when raw discovery
    # finds nothing and Chrome is available, discover from what Chrome
    # actually renders instead of concluding the site has one page.
    if not links and browser_manager is not None:
        rendered = await _browser_html(browser_manager, start_url)
        if rendered:
            links = discover_links(rendered, start_url, limit=max_pages - 1)

    for link in links:
        t, e, m = await fetch_page_best_effort(
            link, browser_manager=browser_manager, proxy_url=proxy_url
        )
        pages.append({"url": link, "text": t, "error": e, "method": m})
    return pages


async def _fetch_raw_html(url: str, *, proxy_url: str | None = None) -> str:
    """The unstripped homepage markup, for link discovery. '' on failure."""
    try:
        import httpx

        kwargs: dict[str, Any] = {"timeout": 15.0, "follow_redirects": True}
        if proxy_url:
            kwargs["proxy"] = proxy_url
        async with httpx.AsyncClient(**kwargs) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            return r.text if r.status_code < 400 else ""
    except Exception:
        return ""


async def _browser_html(browser_manager: Any, url: str) -> str:
    """Navigate the real browser to ``url`` and return the rendered HTML."""
    if browser_manager is None:
        return ""
    try:
        await browser_manager.call_tool("browser_navigate", {"url": url})
        payload = await browser_manager.call_tool("browser_get_html", {})
        return _result_text(payload)
    except Exception as e:
        logger.debug("watch: browser html for %s failed: %s", url, e)
        return ""


# ── Which pages deserve to be exhibits ─────────────────────────────────────
# A storefront pack shows the storefront. In the run of 2026-08-16 four of
# fourteen exhibits were a privacy policy, terms of service, a responsible-
# play page or a deep slot-game URL — the picker took "the first readable
# pages" instead of "the pages a visitor sees". Rank instead: the homepage,
# then the promotions/offers page (what the market is actually selling),
# then other product pages; legal and account pages are never exhibits.
_LEGAL_RE = re.compile(
    r"privacy|terms|tos\b|conditions|cookie|responsible|legal|rules|sweeps|"
    r"sweepstake|policy|faq|help|support|contact|about|login|log-in|signin|"
    r"sign-in|register|signup|sign-up|account|careers|press|affiliate",
    re.I,
)
_PROMO_RE = re.compile(
    r"promo|promotion|offer|bonus|welcome|reward|loyalty|vip|deal|free-coins|"
    r"daily|jackpot|giveaway|sale",
    re.I,
)


def exhibit_kind(url: str, title: str = "") -> str:
    """'home' | 'promo' | 'legal' | 'other' — the exhibit picker's ranking."""
    from urllib.parse import urlparse

    try:
        path = (urlparse(url).path or "/").rstrip("/") or "/"
    except Exception:
        path = "/"
    hay = f"{path} {title or ''}"
    if path == "/" or path.lower() in ("/home", "/index.html", "/index"):
        return "home"
    if _LEGAL_RE.search(hay):
        return "legal"
    if _PROMO_RE.search(hay):
        return "promo"
    return "other"


def rank_exhibit_pages(
    pages: list[dict[str, Any]], *, home_url: str = "", limit: int = 3
) -> list[str]:
    """Order candidate URLs for capture: home, best promo page, then other
    product pages — never a legal page. ``pages`` are ``{url, title?}``."""
    _order = {"home": 0, "promo": 1, "other": 2}
    seen: set[str] = set()
    cands: list[tuple[int, int, str]] = []
    if home_url:
        cands.append((0, -1, home_url))
        seen.add(home_url)
    for i, p in enumerate(pages):
        u = str(p.get("url") or "")
        if not u or u in seen:
            continue
        kind = exhibit_kind(u, str(p.get("title") or ""))
        if kind == "legal":
            continue
        seen.add(u)
        cands.append((_order[kind], i, u))
    cands.sort()
    out: list[str] = []
    kinds_taken: set[str] = set()
    for rank, _, u in cands:
        # one home, one promo, then others — a pack wants variety, not three
        # promo pages
        kind = {0: "home", 1: "promo", 2: "other"}[rank]
        if kind in ("home", "promo") and kind in kinds_taken:
            continue
        kinds_taken.add(kind)
        out.append(u)
        if len(out) >= limit:
            break
    return out


# The browser-automation playbook's own recipe for consent banners, verbatim:
# browser_click_text("Accept All") / ("Accept"), then fall back to
# browser_get_elements to find the consent button. Two rounds, because some
# storefronts stack a bar and a modal (LuckyLand). Best-effort throughout —
# a banner that will not close is still a capturable page.
_CONSENT_LABELS = ("Accept All", "Accept all cookies", "Allow all", "Accept", "I agree", "Got it")
_CONSENT_WORDS = ("accept", "agree", "allow all", "got it", "consent")


def _consent_click_landed(res: Any, wanted: str) -> bool:
    """``browser_click_text`` reports success even when it fell through to an
    unrelated element (High 5, 2026-08-16: asked for "Accept All", clicked
    "Home", success=true). Trust ``matchedText``, not the flag."""
    data = res if isinstance(res, dict) else {}
    if not data.get("success") and isinstance(data.get("result"), dict):
        data = data["result"]
    if not data.get("success"):
        return False
    matched = str(data.get("matchedText") or "").strip().lower()
    return bool(matched) and wanted.lower() in matched


async def dismiss_consent(
    browser_manager: Any, *, rounds: int = 2, settle_ms: tuple[int, ...] = (1500, 2500)
) -> int:
    """Click through cookie-consent / privacy-choice overlays before an
    exhibit is captured, exactly the way the browser skill does it by hand.
    Returns the number of overlays clicked; never raises."""
    if browser_manager is None:
        return 0
    clicked = 0
    settles = list(settle_ms if isinstance(settle_ms, (tuple, list)) else [int(settle_ms)])
    for _ in range(max(1, rounds) + len(settles)):
        hit = False
        for label in _CONSENT_LABELS:
            try:
                res = await browser_manager.call_tool(
                    "browser_click_text", {"text": label, "exact": True}
                )
            except Exception:
                continue
            if _consent_click_landed(res, label):
                hit = True
                clicked += 1
                break
        if not hit:
            # Playbook fallback: look at what is actually clickable, then
            # try the consent words as substrings — accepting only a click
            # that landed on an element carrying that word.
            try:
                els = await browser_manager.call_tool("browser_get_elements", {})
            except Exception:
                els = None
            text = _result_text(els).lower()
            for word in _CONSENT_WORDS:
                if word not in text:
                    continue
                try:
                    res = await browser_manager.call_tool(
                        "browser_click_text", {"text": word, "exact": False}
                    )
                except Exception:
                    continue
                if _consent_click_landed(res, word):
                    hit = True
                    clicked += 1
                    break
        if not hit:
            # Consent overlays often render a beat after load (Pulsz Bingo,
            # 2026-08-16: nothing to click at t=0, modal on screen by the
            # capture; High 5 the same day needed longer still). A miss
            # earns a few more looks with growing waits — not a retry loop.
            if clicked or not settles:
                break
            try:
                await browser_manager.call_tool("browser_wait", {"ms": settles.pop(0)})
            except Exception:
                pass
            continue
        try:
            await browser_manager.call_tool("browser_wait", {"ms": 600})
        except Exception:
            pass
    return clicked


async def capture_page_screenshot(
    browser_manager: Any,
    url: str,
    out_path: str,
    *,
    navigate: bool = True,
) -> str:
    """File a clean storefront screenshot beside the claims it supports.

    Navigates the real browser to ``url`` (unless the page is already open
    and ``navigate=False``) and saves an unannotated JPEG to ``out_path``
    via the bridge's ``browser_capture`` — no element boxes, no vision
    pass. Returns the path written, or "" on any failure: a missing
    exhibit is a gap, never an error that stops collection.
    """
    if browser_manager is None or not out_path:
        return ""
    try:
        if navigate:
            await browser_manager.call_tool("browser_navigate", {"url": url})
        await dismiss_consent(browser_manager)
        from pathlib import Path as _Path

        # One retry after a settle: heavy storefronts stall Playwright's
        # screenshot on "waiting for fonts to load" (High 5, 2026-08-16:
        # 30s timeout on the only exhibit page, and the brand went into
        # the deck with a stale capture). A second shot a moment later
        # usually lands; a second failure is a gap, logged, not an error.
        last_err = ""
        for attempt in range(2):
            if attempt:
                try:
                    await browser_manager.call_tool("browser_wait", {"ms": 2500})
                except Exception:
                    pass
                # The stall was 30s of page time — a consent bar that slid in
                # meanwhile would be in the retry shot (High 5, 2026-08-16).
                await dismiss_consent(browser_manager, settle_ms=(500,))
            payload = await browser_manager.call_tool("browser_capture", {"path": out_path})
            data = payload if isinstance(payload, dict) else {}
            # Bridge results sometimes arrive wrapped ({"result": {...}}) or
            # as JSON text; be liberal in what we accept.
            if not data.get("success") and isinstance(data.get("result"), dict):
                data = data["result"]
            ok = bool(data.get("success"))
            if not ok:
                text = _result_text(payload)
                ok = '"success": true' in text or '"success":true' in text
                last_err = str(data.get("error") or text)[:200]
            if ok and _Path(out_path).exists():
                return out_path
        logger.debug("watch: screenshot of %s failed twice: %s", url, last_err)
        return ""
    except Exception as e:
        logger.debug("watch: screenshot of %s failed: %s", url, e)
        return ""


def screenshot_filename(page_url: str, *, when: str = "") -> str:
    """A stable, readable exhibit filename: ``YYYYMMDD-<page-slug>.jpg``."""
    from datetime import UTC, datetime
    from urllib.parse import urlparse

    day = (when or datetime.now(UTC).strftime("%Y%m%d"))[:8]
    parsed = urlparse(page_url)
    slug_src = (parsed.path or "/").strip("/") or "home"
    slug = re.sub(r"[^a-z0-9]+", "-", slug_src.lower()).strip("-")[:40] or "home"
    return f"{day}-{slug}.jpg"


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


# ── Exit verification: a state stamp is proven, not assumed ──────────
#
# `geo_state` on an evidence row means "this is what a customer in that state
# sees". Routing through a state-targeted proxy *asks* for that; it does not
# prove it. Residential targeting is best-effort — sampled live on
# 2026-08-15, `_state-texas` exited in Virginia half the time — and a
# rotating pool can hand every request a different city. So before anything
# is stamped, the exit is pinned to one IP (a sticky session) and that IP's
# geolocation is checked against the claimed state. No verified exit, no
# state stamp: the observation is refused, never silently downgraded.

US_STATES = {
    "AL": "alabama",
    "AK": "alaska",
    "AZ": "arizona",
    "AR": "arkansas",
    "CA": "california",
    "CO": "colorado",
    "CT": "connecticut",
    "DE": "delaware",
    "FL": "florida",
    "GA": "georgia",
    "HI": "hawaii",
    "ID": "idaho",
    "IL": "illinois",
    "IN": "indiana",
    "IA": "iowa",
    "KS": "kansas",
    "KY": "kentucky",
    "LA": "louisiana",
    "ME": "maine",
    "MD": "maryland",
    "MA": "massachusetts",
    "MI": "michigan",
    "MN": "minnesota",
    "MS": "mississippi",
    "MO": "missouri",
    "MT": "montana",
    "NE": "nebraska",
    "NV": "nevada",
    "NH": "new hampshire",
    "NJ": "new jersey",
    "NM": "new mexico",
    "NY": "new york",
    "NC": "north carolina",
    "ND": "north dakota",
    "OH": "ohio",
    "OK": "oklahoma",
    "OR": "oregon",
    "PA": "pennsylvania",
    "RI": "rhode island",
    "SC": "south carolina",
    "SD": "south dakota",
    "TN": "tennessee",
    "TX": "texas",
    "UT": "utah",
    "VT": "vermont",
    "VA": "virginia",
    "WA": "washington",
    "WV": "west virginia",
    "WI": "wisconsin",
    "WY": "wyoming",
    "DC": "district of columbia",
}
_STATE_BY_NAME = {v: k for k, v in US_STATES.items()}

# IPRoyal-style geo tokens in the proxy password. Their presence is what makes
# a password sticky-session capable (same token grammar), and is the gate for
# appending one — another provider's password must never be rewritten.
_GEO_TOKEN_RE = re.compile(r"_(?:country|state|region|city)-[a-z0-9-]+", re.I)
_SESSION_TOKEN_RE = re.compile(r"_session-[a-z0-9]+", re.I)


def pin_password(password: str, *, session: str | None = None, lifetime: str = "30m") -> str:
    """Append a sticky-session token to a geo-targeted proxy password.

    The password-level primitive under :func:`pin_session`, exposed on its
    own because Chrome takes credentials, not a URL. Non-geo passwords are
    returned unchanged; already-pinned ones too.
    """
    if not _GEO_TOKEN_RE.search(password or "") or _SESSION_TOKEN_RE.search(password or ""):
        return password
    import secrets as _secrets

    sid = session or _secrets.token_hex(4)
    return f"{password}_session-{sid}_lifetime-{lifetime}"


def pin_session(proxy_url: str, *, session: str | None = None, lifetime: str = "30m") -> str:
    """Pin a geo-targeted proxy URL to one exit via a sticky-session token.

    Without this, every request may exit from a different address, and a geo
    check on request 1 proves nothing about request 2 — verification would be
    theatre. With ``_session-…_lifetime-…`` appended to the password, the
    provider holds one exit for the session's lifetime, so the IP that passes
    verification is the IP that fetches the pages.

    Only applied to passwords already carrying geo tokens (IPRoyal grammar);
    anything else is returned unchanged. Idempotent.
    """
    from urllib.parse import urlsplit, urlunsplit

    try:
        parts = urlsplit(proxy_url)
        password = parts.password or ""
        new_password = pin_password(password, session=session, lifetime=lifetime)
        if new_password == password:
            return proxy_url
        username = parts.username or ""
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        netloc = f"{username}:{new_password}@{host}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return proxy_url


def is_session_pinnable(proxy_url: str) -> bool:
    """True when the URL's password carries geo tokens (sticky grammar)."""
    from urllib.parse import urlsplit

    try:
        return bool(_GEO_TOKEN_RE.search(urlsplit(proxy_url).password or ""))
    except Exception:
        return False


def _parse_geo_fields(
    ip: str, state_code: str, state_name: str, service: str
) -> dict[str, Any] | None:
    code = (state_code or "").strip().upper()
    name = (state_name or "").strip().lower()
    if not code and name in _STATE_BY_NAME:
        code = _STATE_BY_NAME[name]
    if not ip or not code:
        return None
    return {
        "ip": ip,
        "state_code": code,
        "state_name": US_STATES.get(code, name),
        "service": service,
    }


async def _egress_geo(proxy_url: str, *, timeout: float = 15.0) -> dict[str, Any] | None:
    """Where does this proxy URL actually come out? None when unknowable.

    One request *through the proxy* to a geolocation echo — the reply
    describes whichever exit served it, which (session-pinned) is the exit
    the page fetches will use. Two independent services, first answer wins.
    """
    import httpx

    for url, kind in (("https://ipwho.is/", "ipwho.is"), ("https://ipinfo.io/json", "ipinfo.io")):
        try:
            async with httpx.AsyncClient(
                proxy=proxy_url,
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0"},
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if kind == "ipwho.is":
                    if data.get("success") is False:
                        continue
                    parsed = _parse_geo_fields(
                        str(data.get("ip") or ""),
                        str(data.get("region_code") or ""),
                        str(data.get("region") or ""),
                        kind,
                    )
                else:
                    parsed = _parse_geo_fields(
                        str(data.get("ip") or ""), "", str(data.get("region") or ""), kind
                    )
                if parsed:
                    return parsed
        except Exception as e:
            logger.debug("watch: egress geo via %s failed: %s", kind, e)
    return None


# One verification covers a sweep, not one per brand. A 14-brand run through
# the same exit does not need 14 proofs — and to an operator who has watched
# an agent loop on IP-checker pages, a geo check before every brand is
# indistinguishable from that loop. Successful verdicts are cached against
# (proxy_url, state) for less than the sticky session's lifetime, so every
# brand in the sweep fetches through the SAME verified session — which is
# also stronger provenance: one exit IP across the whole register, not
# fourteen. Failures are never cached on the HTTP path (each retry re-rolls
# the exit, so the next attempt may legitimately land).
_VERIFY_TTL_SECONDS = 900.0  # 15 min, safely under the 30m session lifetime
_BROWSER_FAIL_TTL_SECONDS = 120.0  # brief: rotation may fix a wrong exit
_exit_verify_cache: dict[tuple[str, str], tuple[float, str, dict[str, Any]]] = {}
_browser_exit_cache: dict[str, tuple[float, bool, dict[str, Any]]] = {}


def clear_exit_verification_cache() -> None:
    """Drop all cached verdicts (tests, or an operator-forced re-check)."""
    _exit_verify_cache.clear()
    _browser_exit_cache.clear()


async def verify_exit_state(
    proxy_url: str,
    state: str,
    *,
    attempts: int = 3,
) -> tuple[bool, str, dict[str, Any]]:
    """Prove the exit is in ``state`` before anything gets stamped with it.

    Returns ``(ok, url_to_use, detail)``. On success ``url_to_use`` is the
    session-pinned URL whose exit passed the check — callers MUST fetch
    through it, not the original, or the proof binds nothing. Targeting being
    best-effort, a miss retries with a fresh session (a re-roll of the exit);
    a non-pinnable URL gets one attempt, since retrying the same URL would
    check a different exit than the fetches use anyway.
    """
    import time as _time

    want = (state or "").strip().upper()
    cached = _exit_verify_cache.get((proxy_url, want))
    if cached is not None:
        expires, pinned_url, detail = cached
        if _time.monotonic() < expires:
            return True, pinned_url, {**detail, "cached": True}
        del _exit_verify_cache[(proxy_url, want)]

    pinnable = is_session_pinnable(proxy_url)
    landed: list[dict[str, Any]] = []
    for attempt in range(attempts if pinnable else 1):
        candidate = pin_session(proxy_url) if pinnable else proxy_url
        geo = await _egress_geo(candidate)
        if geo is None:
            landed.append({"error": "geolocation unreachable"})
            continue
        if geo["state_code"] == want:
            detail = {
                **geo,
                "verified": True,
                "session_pinned": pinnable,
                "attempts": attempt + 1,
            }
            if pinnable:
                # Only a pinned session outlives this call, so only a pinned
                # verdict is worth reusing.
                _exit_verify_cache[(proxy_url, want)] = (
                    _time.monotonic() + _VERIFY_TTL_SECONDS,
                    candidate,
                    detail,
                )
            return True, candidate, detail
        landed.append(geo)
        logger.info(
            "watch: exit verification miss %d/%d — asked %s, landed %s (%s)",
            attempt + 1,
            attempts if pinnable else 1,
            want,
            geo.get("state_code"),
            geo.get("ip"),
        )
    return (
        False,
        proxy_url,
        {
            "verified": False,
            "session_pinned": pinnable,
            "wanted": want,
            "landed": landed,
        },
    )


async def verify_browser_exit(
    browser_manager: Any,
    state: str,
) -> tuple[bool, dict[str, Any]]:
    """Check where the agent's Chrome actually exits, for escalated pages.

    Browser-escalated fetches ride Chrome's own proxy credentials, not the
    verified HTTP session — a different exit. Before claims from a
    browser-fetched page get a state stamp, Chrome's exit has to pass the
    same check. One echo page, parsed from the rendered text.
    """
    if browser_manager is None:
        return False, {"error": "browser unavailable"}
    import time as _time

    want = (state or "").strip().upper()
    cached = _browser_exit_cache.get(want)
    if cached is not None:
        expires, ok, detail = cached
        if _time.monotonic() < expires:
            return ok, {**detail, "cached": True}
        del _browser_exit_cache[want]
    text, err = await fetch_page_via_browser(browser_manager, "https://ipwho.is/", max_chars=4000)
    if err or not text:
        return False, {"error": err or "no response from geolocation echo"}
    ip_m = re.search(r'"ip"\s*:?\s*"?((?:\d{1,3}\.){3}\d{1,3})', text)
    code_m = re.search(r'"region_code"\s*:?\s*"?([A-Za-z]{2})', text)
    name_m = re.search(r'"region"\s*:?\s*"?([A-Za-z ]{3,30}?)"', text)
    parsed = _parse_geo_fields(
        ip_m.group(1) if ip_m else "",
        code_m.group(1) if code_m else "",
        name_m.group(1) if name_m else "",
        "ipwho.is (browser)",
    )
    if parsed is None:
        return False, {"error": "could not parse geolocation from browser page"}
    ok = parsed["state_code"] == want
    if not ok:
        logger.info(
            "watch: browser exit is %s (%s), not %s — browser-fetched pages will not be stamped",
            parsed["state_code"],
            parsed["ip"],
            want,
        )
    # Cache both verdicts: a pass for the sweep, a fail briefly — otherwise a
    # wrong exit means one visible ipwho.is visit per brand, which is exactly
    # the checker-loop optics this cache exists to end.
    ttl = _VERIFY_TTL_SECONDS if ok else _BROWSER_FAIL_TTL_SECONDS
    _browser_exit_cache[want] = (
        _time.monotonic() + ttl,
        ok,
        {**parsed, "verified": ok},
    )
    return ok, {**parsed, "verified": ok}


# ── source expansion: research beyond the brand's own site ───────────
#
# A brand's site is the primary source, and for some brands it is nearly
# useless — a JS shell behind a bot wall, or a lobby that says nothing about
# payments, AMOE or loyalty. The organ used to stop there, which left whole
# brands at "not publicly observable" while reviews, help centers and app
# stores carried the facts in plain text. Expansion finds those pages with
# web search and reads them through the SAME verified exit, so the excerpt
# guarantee and the geo stamp both survive: a claim still only exists if its
# verbatim quote is on a page we actually fetched.

_SEARCH_URL = "https://search.sh/api/search"


async def search_web(
    query: str,
    *,
    api_key: str,
    max_results: int = 8,
    timeout: float = 30.0,
) -> list[dict[str, str]]:
    """Plain web search → [{title, url, snippet}]. Empty on any failure."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                _SEARCH_URL,
                json={
                    "query": query[:500],
                    "mode": "fast",
                    "region": "us",
                    "max_results": max_results,
                },
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            )
        if resp.status_code != 200:
            logger.warning("watch: search failed (%s): %s", resp.status_code, resp.text[:120])
            return []
        return [
            {
                "title": str(s.get("title") or ""),
                "url": str(s.get("url") or ""),
                "snippet": str(s.get("snippet") or ""),
            }
            for s in (resp.json().get("sources") or [])
            if isinstance(s, dict) and str(s.get("url") or "").startswith("http")
        ]
    except Exception as e:
        logger.warning("watch: search failed: %s", e)
        return []


def expansion_queries(brand: str, missing_dimensions: list[str], *, limit: int = 3) -> list[str]:
    """A few targeted queries for what the brand's own site would not say."""
    if not missing_dimensions:
        return []
    queries: list[str] = []
    chunk = 3
    for i in range(0, len(missing_dimensions), chunk):
        group = " ".join(w for d in missing_dimensions[i : i + chunk] for w in d.split()[:3])
        queries.append(f'"{brand}" {group}'[:200])
        if len(queries) >= limit:
            break
    return queries


def pick_expansion_urls(
    results: list[dict[str, str]],
    *,
    already_fetched: set[str],
    limit: int = 4,
) -> list[str]:
    """Choose distinct, unread hosts from search results, best-first."""
    from urllib.parse import urlparse

    fetched_keys = set()
    for u in already_fetched:
        try:
            pu = urlparse(u)
            fetched_keys.add((pu.netloc.lower(), pu.path.rstrip("/")))
        except Exception:
            continue
    seen_hosts: set[str] = set()
    out: list[str] = []
    for r in results:
        url = r.get("url") or ""
        try:
            pu = urlparse(url)
        except Exception:
            continue
        if pu.scheme not in ("http", "https"):
            continue
        key = (pu.netloc.lower(), pu.path.rstrip("/"))
        if key in fetched_keys or pu.netloc.lower() in seen_hosts:
            continue
        seen_hosts.add(pu.netloc.lower())
        out.append(url.split("#")[0])
        if len(out) >= limit:
            break
    return out
