"""Voice of customer — collectors and the reading contract (docs/87).

What PLAYERS say about a tracked brand, from public sources, filed as the
organ's second evidence class (``watch_voice``). Opinion, never fact: the
collectors here never write to ``watch_evidence`` and nothing they produce is
read by scoring. Same disciplines as ``watch_observe``:

* the model classifies, it does not invent — every quote must appear
  verbatim in the post it came from or the row is dropped;
* usernames, handles, emails and links are stripped BEFORE the model sees
  the text, so nothing personal can be stored;
* affiliate / referral posts are dropped, cross-posts count once, and every
  row carries its source URL and the exit IP it was read through.

Sources in order of build: Reddit (public JSON), App Store (customer-reviews
RSS). Google Play, Trustpilot/BBB and X come later behind the same shape:
``collect_<source>(...) -> list[VoicePost]``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from core.watch import VOICE_SENTIMENTS, VOICE_THEMES

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

# Reddit refuses unauthenticated JSON from scripts (HTTP 403, verified
# 2026-08-17 direct and through the residential exit). The supported route
# is the OAuth API with an app-only token: a free "script" app registered
# at reddit.com/prefs/apps, its client id/secret in the vault as
# reddit_client_id / reddit_client_secret. Read-only, ~100 req/min; one
# request a second is the polite ceiling and never trips it.
REDDIT_PAUSE_S = 1.1
REDDIT_UA = "python:elophanto.watch:v1.0 (competitive intelligence, voice of customer)"
DEFAULT_REDDIT_SUBS: tuple[str, ...] = ("sweepstakescasinos", "SweepstakesCasinos")


async def reddit_app_token(
    client_id: str, client_secret: str, *, proxy_url: str | None = None, timeout: float = 20.0
) -> tuple[str, str | None]:
    """An application-only OAuth token (client_credentials). ``(token, error)``."""
    import httpx

    kwargs: dict[str, Any] = {"timeout": timeout, "headers": {"User-Agent": REDDIT_UA}}
    if proxy_url:
        kwargs["proxy"] = proxy_url
    try:
        async with httpx.AsyncClient(**kwargs) as client:
            resp = await client.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
            )
            if resp.status_code >= 400:
                return "", f"HTTP {resp.status_code}"
            tok = str((resp.json() or {}).get("access_token") or "")
            return tok, None if tok else "no access_token in response"
    except Exception as e:
        return "", f"{type(e).__name__}: {e}"


@dataclass(slots=True)
class VoicePost:
    """One public post/review as fetched, before reading. ``text`` is
    already stripped of usernames, handles, emails and links."""

    post_id: str
    source: str
    url: str
    text: str
    posted_at: str = ""
    rating: float | None = None
    weight: float = 1.0
    meta: dict[str, Any] = field(default_factory=dict)


# ── Hygiene ────────────────────────────────────────────────────────────

_PII_RES = (
    re.compile(r"\bu/[A-Za-z0-9_\-]+", re.I),  # reddit usernames
    re.compile(r"(?<![\w.])@[A-Za-z0-9_]{2,}"),  # handles
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),  # emails
    re.compile(r"https?://\S+|www\.\S+", re.I),  # links
)
_AFFILIATE_RE = re.compile(
    r"\bref(?:erral)?=|\bref\b.*\bcode\b|use my (?:code|link)|my referral|"
    r"referral link|promo code[:\s]+[A-Z0-9]{4,}|sign ?up (?:with|using) my|"
    r"\baffiliate\b|dm me for|click my",
    re.I,
)
_STAFF_RE = re.compile(r"\b(developer response|response from|the .{0,40} team)\b", re.I)


def strip_pii(text: str) -> str:
    """Remove usernames, handles, emails and links; collapse whitespace."""
    out = text or ""
    for rx in _PII_RES:
        out = rx.sub(" ", out)
    return " ".join(out.split())


def is_affiliate(text: str) -> bool:
    return bool(_AFFILIATE_RE.search(text or ""))


def mentions_brand(text: str, aliases: list[str]) -> bool:
    low = (text or "").lower()
    return any(a and a.lower() in low for a in aliases)


def brand_aliases(name: str, url: str = "") -> list[str]:
    """Names a player would use: the brand name, its host without TLD, the
    name without spaces/'casino'."""
    out = [name]
    bare = re.sub(r"\b(casino|slots|social)\b", "", name, flags=re.I).strip()
    if bare and bare.lower() != name.lower():
        out.append(bare)
    nospace = name.replace(" ", "")
    if nospace.lower() != name.lower():
        out.append(nospace)
    host = re.sub(r"^https?://(www\.)?", "", url or "").split("/")[0]
    host = host.split(".")[0] if host else ""
    if host and len(host) > 3 and host.lower() not in {a.lower() for a in out}:
        out.append(host)
    return out


def quote_is_verbatim(quote: str, text: str) -> bool:
    """A quote counts only if it appears in the post — same rule as evidence
    excerpts (whitespace/case-insensitive)."""
    q = " ".join((quote or "").lower().split())
    t = " ".join((text or "").lower().split())
    return bool(q) and len(q) >= 12 and q in t


# ── Reddit ─────────────────────────────────────────────────────────────


async def _get_json(
    url: str, *, proxy_url: str | None, timeout: float = 20.0, bearer: str = ""
) -> tuple[Any, str | None]:
    import httpx

    headers = {"User-Agent": REDDIT_UA if bearer else _UA, "Accept": "application/json"}
    if bearer:
        headers["Authorization"] = f"bearer {bearer}"
    kwargs: dict[str, Any] = {
        "timeout": timeout,
        "follow_redirects": True,
        "headers": headers,
    }
    if proxy_url:
        kwargs["proxy"] = proxy_url
    try:
        async with httpx.AsyncClient(**kwargs) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                return None, f"HTTP {resp.status_code}"
            return resp.json(), None
    except Exception as e:  # network, JSON, proxy — all "nothing fetched"
        return None, f"{type(e).__name__}: {e}"


def _reddit_weight(score: int, num_comments: int, is_comment: bool) -> float:
    base = 0.6 if is_comment else 0.7
    if score >= 5:
        base += 0.15
    if score >= 25:
        base += 0.15
    if not is_comment and num_comments >= 10:
        base += 0.05
    return min(1.0, base)


def parse_reddit_listing(
    payload: Any, *, aliases: list[str], since_utc: float
) -> list[VoicePost]:
    """Posts from a search/listing JSON that mention the brand and are newer
    than ``since_utc``. Text = title + selftext, stripped."""
    out: list[VoicePost] = []
    try:
        children = payload["data"]["children"]
    except Exception:
        return out
    for ch in children:
        d = ch.get("data") if isinstance(ch, dict) else None
        if not isinstance(d, dict):
            continue
        created = float(d.get("created_utc") or 0)
        if created and created < since_utc:
            continue
        raw = f"{d.get('title') or ''}. {d.get('selftext') or ''}".strip(". ")
        text = strip_pii(raw)
        if not text or not mentions_brand(text, aliases) or is_affiliate(raw):
            continue
        permalink = str(d.get("permalink") or "")
        out.append(
            VoicePost(
                post_id=str(d.get("name") or d.get("id") or permalink),
                source="reddit",
                url=f"https://www.reddit.com{permalink}" if permalink else "",
                text=text[:2000],
                posted_at=(
                    datetime.fromtimestamp(created, tz=UTC).isoformat()
                    if created
                    else ""
                ),
                weight=_reddit_weight(
                    int(d.get("score") or 0), int(d.get("num_comments") or 0), False
                ),
                meta={"subreddit": str(d.get("subreddit") or ""), "kind": "post"},
            )
        )
    return out


def parse_reddit_comments(
    payload: Any, *, aliases: list[str], post_url: str, since_utc: float
) -> list[VoicePost]:
    """Top-level comments of a thread that mention the brand (or the whole
    thread is about it: the post itself mentioned the brand, so comments
    are on-topic and are kept when they carry an opinion)."""
    out: list[VoicePost] = []
    try:
        listing = payload[1]["data"]["children"]
    except Exception:
        return out
    for ch in listing:
        d = ch.get("data") if isinstance(ch, dict) else None
        if not isinstance(d, dict) or ch.get("kind") != "t1":
            continue
        created = float(d.get("created_utc") or 0)
        if created and created < since_utc:
            continue
        raw = str(d.get("body") or "")
        text = strip_pii(raw)
        if len(text) < 30 or is_affiliate(raw):
            continue
        cid = str(d.get("id") or "")
        out.append(
            VoicePost(
                post_id=f"t1_{cid}",
                source="reddit",
                url=f"{post_url.rstrip('/')}/comment/{cid}/" if post_url else "",
                text=text[:1500],
                posted_at=(
                    datetime.fromtimestamp(created, tz=UTC).isoformat()
                    if created
                    else ""
                ),
                weight=_reddit_weight(int(d.get("score") or 0), 0, True),
                meta={"kind": "comment"},
            )
        )
    return out


async def collect_reddit(
    brand: str,
    aliases: list[str],
    *,
    subs: tuple[str, ...] | list[str] = DEFAULT_REDDIT_SUBS,
    window_days: int = 30,
    proxy_url: str | None = None,
    max_posts: int = 200,
    with_comments: bool = True,
    pause_s: float = REDDIT_PAUSE_S,
    token: str = "",
) -> tuple[list[VoicePost], list[str]]:
    """Reddit posts (and top-level comments of brand threads) mentioning the
    brand in the window, via the OAuth API when ``token`` is given — the
    only route Reddit still serves to scripts. Returns ``(posts, errors)``;
    never raises."""
    since_utc = (datetime.now(UTC) - timedelta(days=int(window_days))).timestamp()
    t = "month" if window_days <= 31 else ("year" if window_days <= 366 else "all")
    q = f'"{brand}"'
    host = "https://oauth.reddit.com" if token else "https://www.reddit.com"
    suffix = "" if token else ".json"
    urls = [f"{host}/search{suffix}?q={_q(q)}&sort=new&limit=100&t={t}"]
    for sub in subs:
        urls.append(
            f"{host}/r/{sub}/search{suffix}?q={_q(q)}&restrict_sr=1&sort=new&limit=100&t={t}"
        )
    posts: list[VoicePost] = []
    errors: list[str] = []
    seen: set[str] = set()
    if not token:
        errors.append(
            "no Reddit OAuth token — Reddit refuses unauthenticated requests; store "
            "reddit_client_id / reddit_client_secret in the vault"
        )
    for u in urls:
        payload, err = await _get_json(u, proxy_url=proxy_url, bearer=token)
        if err:
            errors.append(f"{u.split('?')[0]}: {err}")
        for p in parse_reddit_listing(payload, aliases=aliases, since_utc=since_utc):
            if p.post_id not in seen:
                seen.add(p.post_id)
                posts.append(p)
        await asyncio.sleep(pause_s)
        if len(posts) >= max_posts:
            break
    if with_comments:
        # Comments of the most-discussed brand threads, newest first.
        threads = sorted(
            [p for p in posts if p.url and p.meta.get("kind") == "post"],
            key=lambda p: p.posted_at,
            reverse=True,
        )[:12]
        for th in threads:
            if len(posts) >= max_posts:
                break
            th_api = (
                th.url.replace("https://www.reddit.com", "https://oauth.reddit.com").rstrip("/")
                + "?limit=60"
                if token
                else f"{th.url.rstrip('/')}.json?limit=60"
            )
            payload, err = await _get_json(th_api, proxy_url=proxy_url, bearer=token)
            if err:
                errors.append(f"comments {th.post_id}: {err}")
            for c in parse_reddit_comments(
                payload, aliases=aliases, post_url=th.url, since_utc=since_utc
            ):
                if c.post_id not in seen:
                    seen.add(c.post_id)
                    posts.append(c)
            await asyncio.sleep(pause_s)
    return posts[:max_posts], errors


def _q(s: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(s)


# ── App Store ──────────────────────────────────────────────────────────


async def find_app_store_id(
    brand: str, aliases: list[str], *, proxy_url: str | None = None, country: str = "us"
) -> str | None:
    """The brand's iOS app id via the iTunes search API — the first result
    whose name carries the brand. Cached by the caller on the subject."""
    payload, err = await _get_json(
        f"https://itunes.apple.com/search?term={_q(brand)}&entity=software&country={country}&limit=10",
        proxy_url=proxy_url,
    )
    if err or not isinstance(payload, dict):
        return None
    for r in payload.get("results") or []:
        name = str(r.get("trackName") or "")
        seller = str(r.get("sellerName") or "")
        if mentions_brand(name, aliases) or mentions_brand(seller, aliases):
            tid = r.get("trackId")
            return str(tid) if tid else None
    return None


def parse_app_store_feed(
    payload: Any, *, app_id: str, since_iso: str
) -> list[VoicePost]:
    """Reviews from the customer-reviews RSS (JSON flavour)."""
    out: list[VoicePost] = []
    try:
        entries = payload["feed"]["entry"]
    except Exception:
        return out
    if isinstance(entries, dict):
        entries = [entries]
    for e in entries:
        if not isinstance(e, dict) or "im:rating" not in e:
            continue  # the first entry is the app itself
        title = str((e.get("title") or {}).get("label") or "")
        body = str((e.get("content") or {}).get("label") or "")
        raw = f"{title}. {body}".strip(". ")
        if _STAFF_RE.search(title):
            continue
        updated = str((e.get("updated") or {}).get("label") or "")
        if since_iso and updated and updated < since_iso:
            continue
        rid = str((e.get("id") or {}).get("label") or "")
        try:
            rating: float | None = float((e.get("im:rating") or {}).get("label"))
        except Exception:
            rating = None
        text = strip_pii(raw)
        if len(text) < 15 or is_affiliate(raw):
            continue
        out.append(
            VoicePost(
                post_id=f"as_{rid or abs(hash(raw))}",
                source="app_store",
                url=f"https://apps.apple.com/us/app/id{app_id}?see-all=reviews",
                text=text[:1500],
                posted_at=updated,
                rating=rating,
                weight=0.8,
                meta={
                    "app_id": app_id,
                    "version": str((e.get("im:version") or {}).get("label") or ""),
                },
            )
        )
    return out


async def collect_app_store(
    app_id: str,
    *,
    window_days: int = 30,
    proxy_url: str | None = None,
    pages: int = 3,
    country: str = "us",
) -> tuple[list[VoicePost], list[str]]:
    """Recent App Store reviews for an app id. ``(posts, errors)``."""
    since_iso = (datetime.now(UTC) - timedelta(days=int(window_days))).isoformat()
    posts: list[VoicePost] = []
    errors: list[str] = []
    for page in range(1, max(1, pages) + 1):
        url = (
            f"https://itunes.apple.com/{country}/rss/customerreviews/page={page}/"
            f"id={app_id}/sortby=mostrecent/json"
        )
        payload, err = await _get_json(url, proxy_url=proxy_url)
        if err:
            errors.append(f"app_store page {page}: {err}")
            break
        got = parse_app_store_feed(payload, app_id=app_id, since_iso=since_iso)
        posts.extend(got)
        if not got:
            break
    return posts, errors


# ── Reading: the model classifies, it does not invent ─────────────────

VOICE_READ_SYSTEM = """You read what players say about a sweepstakes / social casino brand and
classify each post. You are given the brand, the fixed theme vocabulary, the
sentiment vocabulary, the model's dimension names, and a list of posts
(id, source, text, rating). Text has already had usernames and links removed.

RULES
- One item per post that actually expresses an opinion or experience about
  THE BRAND. Skip posts that only mention it in passing, ask a question with
  no experience, or are about another brand.
- theme: exactly one from the vocabulary. 'other' only when nothing fits.
- sentiment: negative / neutral / positive — about the brand, from the
  poster's point of view.
- quote: a SHORT VERBATIM span (max 200 characters) copied exactly from
  that post's text, carrying the opinion. Do not paraphrase, do not merge
  spans, do not add words. If no such span exists, skip the post.
- dimension: the model dimension the theme speaks to, copied exactly from
  the given names, or "" when none does. This is a flag for a reader, not a
  score.
- geo_hint: a US state or country the poster names about themselves
  ("here in Florida"), else "".
- Never infer facts about the product; you are classifying opinions.

Return STRICT JSON:
{"items":[{"id":str,"theme":str,"sentiment":str,"quote":str,"dimension":str,"geo_hint":str}]}"""

_THEME_DIMENSION_HINTS: dict[str, tuple[str, ...]] = {
    "redemption_speed": ("kyc", "redemption", "journey", "payment"),
    "kyc_friction": ("kyc", "journey", "onboarding"),
    "support": ("support", "service", "trust"),
    "fairness_rtp": ("rtp", "fairness", "sc "),
    "promo_value": ("promo", "generosity", "offer"),
    "app_stability": ("product", "app", "platform", "game"),
    "account_bans": ("trust", "kyc", "terms"),
    "vip_treatment": ("loyalty", "vip"),
    "game_selection": ("game", "portfolio", "content"),
    "payments": ("purchase", "package", "payment", "coin"),
}


def dimension_for_theme(theme: str, dimension_names: list[str]) -> str:
    """Deterministic fallback when the model leaves ``dimension`` empty."""
    hints = _THEME_DIMENSION_HINTS.get(theme, ())
    for name in dimension_names:
        low = name.lower()
        if any(h in low for h in hints):
            return name
    return ""


async def read_posts(
    router: Any,
    *,
    brand: str,
    posts: list[VoicePost],
    dimension_names: list[str],
    batch: int = 15,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Classify posts in batches. Returns ``(items, dropped)`` where each item
    is a validated ``{post, theme, sentiment, quote, dimension, geo_hint}``
    and ``dropped`` counts why posts fell out. [] on no router."""
    dropped = {
        "no_router": 0,
        "model_skip": 0,
        "bad_theme": 0,
        "unverified_quote": 0,
        "error": 0,
    }
    if router is None:
        dropped["no_router"] = len(posts)
        return [], dropped
    by_id = {p.post_id: p for p in posts}
    items: list[dict[str, Any]] = []
    for i in range(0, len(posts), max(1, batch)):
        chunk = posts[i : i + batch]
        user = json.dumps(
            {
                "brand": brand,
                "themes": list(VOICE_THEMES),
                "sentiments": list(VOICE_SENTIMENTS),
                "dimensions": dimension_names,
                "posts": [
                    {
                        "id": p.post_id,
                        "source": p.source,
                        "text": p.text[:1500],
                        "rating": p.rating,
                    }
                    for p in chunk
                ],
            }
        )
        try:
            resp = await router.complete(
                messages=[
                    {"role": "system", "content": VOICE_READ_SYSTEM},
                    {"role": "user", "content": user},
                ],
                task_type="analysis",
                temperature=0.0,
                max_tokens=3000,
            )
            text = (resp.content or "").strip()
            if text.startswith("```"):
                parts = text.split("```")
                text = parts[1] if len(parts) > 1 else text
                text = text[4:] if text.startswith("json") else text
            data = json.loads(text)
            raw_items = data.get("items", []) if isinstance(data, dict) else []
        except Exception as e:
            logger.warning("watch_voice: reading failed: %s", e)
            dropped["error"] += len(chunk)
            continue
        got_ids: set[str] = set()
        for it in raw_items:
            if not isinstance(it, dict):
                continue
            p = by_id.get(str(it.get("id") or ""))
            if p is None:
                continue
            got_ids.add(p.post_id)
            theme = str(it.get("theme") or "").strip()
            sentiment = str(it.get("sentiment") or "").strip()
            if theme not in VOICE_THEMES or sentiment not in VOICE_SENTIMENTS:
                dropped["bad_theme"] += 1
                continue
            quote = " ".join(str(it.get("quote") or "").split())[:240]
            if not quote_is_verbatim(quote, p.text):
                dropped["unverified_quote"] += 1
                continue
            dim = str(it.get("dimension") or "").strip()
            if dim and dim not in dimension_names:
                dim = ""
            if not dim:
                dim = dimension_for_theme(theme, dimension_names)
            items.append(
                {
                    "post": p,
                    "theme": theme,
                    "sentiment": sentiment,
                    "quote": quote,
                    "dimension": dim,
                    "geo_hint": str(it.get("geo_hint") or "")[:40],
                }
            )
        dropped["model_skip"] += len([p for p in chunk if p.post_id not in got_ids])
    return items, dropped


async def fetch_app_meta(
    app_id: str, *, proxy_url: str | None = None, country: str = "us"
) -> dict[str, Any] | None:
    """The store listing via the iTunes lookup: version, rating, rating
    count, release notes, release date. None on any failure."""
    payload, err = await _get_json(
        f"https://itunes.apple.com/lookup?id={_q(app_id)}&country={country}", proxy_url=proxy_url
    )
    if err or not isinstance(payload, dict):
        return None
    results = payload.get("results") or []
    if not results:
        return None
    r = results[0]
    return {
        "app_id": str(app_id),
        "store": "app_store",
        "version": str(r.get("version") or ""),
        "rating": float(r["averageUserRating"]) if r.get("averageUserRating") is not None else None,
        "rating_count": int(r["userRatingCount"]) if r.get("userRatingCount") is not None else None,
        "release_notes": str(r.get("releaseNotes") or "")[:600],
        "released_at": str(r.get("currentVersionReleaseDate") or "")[:19],
        "name": str(r.get("trackName") or ""),
    }
