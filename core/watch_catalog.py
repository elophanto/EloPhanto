"""Catalog — the raw inventory behind the scores (docs/89).

Providers, coin packages, promotions and games, as printed on the brand's
own pages: a list, not a judgement. Nothing here is scored; the value is
that a buyer can read the actual price ladder and the actual provider set
rather than a sentence about them.

Same disciplines as the rest of the organ: an item is kept only when its
name appears on the page it was read from, every row carries its URL, the
session state it was read in and the exit it was read through, and
re-collection updates an item rather than duplicating it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

CATALOG_KINDS: tuple[str, ...] = ("provider", "coin_package", "promotion", "game")

# Which page serves which kind. A store page is where the coins are sold;
# "promotions" is where the offers live; providers and games have their own
# pages on nearly every one of these sites.
_PAGE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("coin_package", re.compile(r"store|shop|buy|coins?-?(store|shop|package)|purchase|cashier|wallet", re.I)),
    ("promotion", re.compile(r"promo|promotion|offer|bonus|deal|reward|vip|loyalty|daily", re.I)),
    ("provider", re.compile(r"provider|studio|partners?|software|suppliers?", re.I)),
    ("game", re.compile(r"game|slot|casino|lobby|table|bingo|jackpot|live", re.I)),
)
_NEVER = re.compile(
    r"privacy|terms|tos\b|cookie|responsible|legal|rules|sweepstake|faq|help|"
    r"support|contact|about|careers|press|affiliate|blog|news",
    re.I,
)


def catalog_page_kind(url: str, title: str = "") -> str:
    """The kind of catalog a page most likely holds, or "" for none."""
    hay = f"{url} {title}"
    if _NEVER.search(hay):
        return ""
    for kind, rx in _PAGE_PATTERNS:
        if rx.search(hay):
            return kind
    return ""


def rank_catalog_pages(
    pages: list[dict[str, Any]], *, per_kind: int = 2
) -> dict[str, list[dict[str, Any]]]:
    """Group readable pages by the catalog kind they serve, best first."""
    out: dict[str, list[dict[str, Any]]] = {}
    for page in pages:
        kind = catalog_page_kind(str(page.get("url") or ""), str(page.get("title") or ""))
        if not kind:
            continue
        bucket = out.setdefault(kind, [])
        if len(bucket) < per_kind:
            bucket.append(page)
    return out


def dedupe_key(brand: str, kind: str, name: str) -> str:
    base = "|".join(
        [
            re.sub(r"[^a-z0-9]+", " ", (brand or "").lower()).strip(),
            kind or "",
            re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()[:60],
        ]
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]


# "$29.99", "$4,999.00", "$10" — thousands separators included, so a
# price never comes back as 4.99 when the page said $4,999.00.
_PRICE_RE = re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)")


def parse_price(text: str) -> float | None:
    """The dollar figure in a package name/detail, if there is one."""
    m = _PRICE_RE.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except Exception:
        return None


def item_is_on_page(name: str, page_text: str) -> bool:
    """An item counts only if its name is actually printed on the page —
    the list version of excerpt verification."""
    n = " ".join((name or "").lower().split())
    if len(n) < 2:
        return False
    return n in " ".join((page_text or "").lower().split())


CATALOG_SYSTEM = """You read one page from a sweepstakes / social casino site and list the
items of ONE requested kind that are printed on it. You are given the
brand, the kind, and the page text.

kind meanings and what "name" is:
- provider: a game studio / software supplier ("Pragmatic Play"). name =
  the studio name exactly as printed.
- coin_package: one purchasable package. name = the price as printed
  ("$29.99") or the package label; coins = what it grants, verbatim
  ("GC 700 + free SC 55"); detail = any extra ("first purchase only").
- promotion: one offer. name = its title as printed ("150% Extra Coins");
  detail = the terms and dates as printed.
- game: one game title. name = the title exactly as printed; detail =
  category or studio when the page states it.

RULES
- Copy names EXACTLY as printed. Do not translate, expand, tidy or invent.
- Only what is on THIS page. No brand knowledge, no guessing at a
  catalogue you cannot see.
- The item must belong to THE NAMED BRAND. Review pages, comparison
  tables and directories list several operators at once: take only what
  the page attributes to this brand, never what it attributes to another
  operator, to "similar sites", or to the site's own business.
- Keep the page's own order (index 0, 1, 2 …) — a price ladder is
  meaningless out of order.
- Navigation labels, categories and headings are not items: "Slots",
  "Table Games", "Popular" are sections, not games.
- If the page holds none of this kind, return an empty list. Padding is a
  failure.

Return STRICT JSON:
{"items":[{"name":str,"detail":str,"coins":str,"index":int}]}"""


async def extract_catalog(
    router: Any,
    *,
    kind: str,
    brand: str,
    page_text: str,
    max_items: int = 60,
) -> list[dict[str, Any]]:
    """Ask the model for the items of one kind on one page, keep only the
    ones actually printed there. [] on any failure."""
    if router is None or kind not in CATALOG_KINDS or not page_text.strip():
        return []
    user = json.dumps(
        {"brand": brand, "kind": kind, "max_items": max_items, "page_text": page_text[:22000]}
    )
    try:
        resp = await router.complete(
            messages=[
                {"role": "system", "content": CATALOG_SYSTEM},
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
        raw = json.loads(text)
        items = raw.get("items", []) if isinstance(raw, dict) else []
    except Exception as e:
        logger.warning("watch_catalog: %s extraction failed: %s", kind, e)
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        name = " ".join(str(it.get("name") or "").split())[:120]
        if not name or not item_is_on_page(name, page_text):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        detail = " ".join(str(it.get("detail") or "").split())[:300]
        coins = " ".join(str(it.get("coins") or "").split())[:160]
        try:
            index = int(it.get("index", i))
        except Exception:
            index = i
        price = parse_price(f"{name} {detail} {coins}") if kind == "coin_package" else None
        if kind == "coin_package" and price is None:
            # Review-site prose yields lines like "30$ … like 12 coins";
            # a ladder rung without a readable price is not a rung.
            continue
        if kind == "coin_package" and coins.strip().lower() == name.strip().lower():
            coins = ""  # "$1.99 grants $1.99" says nothing — leave it blank
        out.append(
            {
                "name": name,
                "detail": detail,
                "coins_text": coins,
                "sort_index": index,
                "price_usd": price,
            }
        )
        if len(out) >= max_items:
            break
    return out


def summarize_catalog(rows: list[Any], subjects: list[Any]) -> dict[str, Any]:
    """Counts per brand × kind, each brand's price ladder, and the promotions
    that carry a picture. Pure computation."""
    per: list[dict[str, Any]] = []
    totals: dict[str, int] = {}
    for s in subjects:
        mine = [r for r in rows if r.subject_id == s.subject_id]
        if not mine:
            continue
        counts = {k: len([r for r in mine if r.kind == k]) for k in CATALOG_KINDS}
        for k, n in counts.items():
            totals[k] = totals.get(k, 0) + n
        ladder = sorted(
            [r for r in mine if r.kind == "coin_package"],
            key=lambda r: (r.price_usd if r.price_usd is not None else 9e9, r.sort_index),
        )
        # Where each kind came from — a ladder read off a review site is a
        # weaker fact than one read off the store, and the deck says so.
        sources = {
            k: sorted({r.source_type for r in mine if r.kind == k})
            for k in CATALOG_KINDS
            if any(r.kind == k for r in mine)
        }
        per.append(
            {
                "subject_id": s.subject_id,
                "name": s.name,
                "is_self": bool(s.is_self),
                "counts": counts,
                "providers": [r.name for r in mine if r.kind == "provider"][:40],
                "sources": sources,
                "packages": [
                    {"name": r.name, "price_usd": r.price_usd, "coins": r.coins_text,
                     "detail": r.detail, "url": r.source_url, "source_type": r.source_type}
                    for r in ladder
                ],
                "promotions": [
                    {"name": r.name, "detail": r.detail, "image": r.image_path, "url": r.source_url}
                    for r in mine if r.kind == "promotion"
                ],
                "games_sample": [r.name for r in mine if r.kind == "game"][:12],
                "games_full": [r.name for r in mine if r.kind == "game"],
                "promotions_full": [
                    {"name": r.name, "detail": r.detail, "image": r.image_path, "url": r.source_url}
                    for r in mine if r.kind == "promotion"
                ],
                "customer_states": sorted({r.customer_state for r in mine}),
                "observed_at": max((r.observed_at for r in mine), default="")[:10],
            }
        )
    per.sort(key=lambda b: (not b["is_self"], b["name"]))
    third_party_only = [
        f"{b['name']} {k}"
        for b in per
        for k, srcs in b.get("sources", {}).items()
        if srcs == ["third_party"]
    ]
    return {
        "brands": per,
        "totals": totals,
        "third_party_only": third_party_only,
        "items": sum(totals.values()),
        "kinds": list(CATALOG_KINDS),
        "label": "Raw inventory as printed on each brand's own pages — not scored.",
    }


# ── Public research: most of this is on the open internet ──────────────
#
# Providers, price ladders, promotions and game lists are published by the
# brands themselves and repeated by review sites and aggregators. Reading
# those costs nothing and needs no session; a login is worth spending only
# on what public pages do not answer, and the state-pinned exit is worth
# spending only where a geo claim is actually made.

_RESEARCH_QUERIES: dict[str, tuple[str, ...]] = {
    "provider": (
        '"{brand}" game providers list software studios',
        '"{brand}" casino games by provider Pragmatic Hacksaw',
    ),
    "coin_package": (
        '"{brand}" coin packages price gold coins sweeps coins',
        '"{brand}" purchase price list $ package review',
    ),
    "promotion": (
        '"{brand}" promotions current offers bonus {year}',
        '"{brand}" promo daily bonus welcome offer {year}',
    ),
    "game": (
        '"{brand}" game list slots titles available',
        '"{brand}" popular games catalogue',
    ),
}

# Sites that mostly resell affiliate links carry stale ladders; the brand's
# own domain and known trackers come first.
_LOW_TRUST = re.compile(r"coupon|promo-?code|deal|bonus-?code|casino-?bonus", re.I)
# Pages that exist to list OTHER operators: whatever they enumerate mostly
# belongs to somebody else (2026-08-27: a "sites-like/luckyland" page gave
# LuckyLand a provider it does not carry, and a game studio's own services
# page gave it another).
_COMPARISON = re.compile(
    r"sites?-like|alternatives?|similar-?(to|sites)|vs-|versus|competitors?|"
    r"best-\d|top-\d|-vs-",
    re.I,
)


def research_page_ok(url: str, text: str, brand: str, aliases: list[str] | None = None) -> bool:
    """Is this public page actually ABOUT the brand?

    A page reached by searching the brand's name may still be about ten
    other operators, or about the search engine's idea of a related
    business. Require the brand in the URL, or named repeatedly in the
    text; and never read a comparison/alternatives page for inventory —
    everything it lists belongs to someone."""
    hay_url = (url or "").lower()
    if _COMPARISON.search(hay_url):
        return False
    names = [brand, *(aliases or [])]
    url_slug = re.sub(r"[^a-z0-9]+", "", hay_url)
    # The brand in the address, under any of the names players use —
    # "time2play.com/casinos/reviews/modo/" is about Modo Casino.
    for candidate in names:
        slug = re.sub(r"[^a-z0-9]+", "", (candidate or "").lower())
        if len(slug) >= 4 and slug in url_slug:
            return True
    low = (text or "").lower()
    mentions = sum(low.count(n.lower()) for n in names if n)
    return mentions >= 3


def research_queries(brand: str, kinds: list[str], *, year: int) -> list[tuple[str, str]]:
    """(kind, query) pairs for the public web, in build order."""
    out: list[tuple[str, str]] = []
    for kind in kinds:
        for template in _RESEARCH_QUERIES.get(kind, ()):
            out.append((kind, template.format(brand=brand, year=year)))
    return out


def rank_research_urls(
    results: list[dict[str, str]], *, brand_host: str = "", limit: int = 3
) -> list[str]:
    """Best public pages to read: the brand's own domain first, then
    ordinary editorial, coupon farms last."""
    scored: list[tuple[float, str]] = []
    seen: set[str] = set()
    for r in results:
        url = str(r.get("url") or "")
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        score = 0.0
        if brand_host and brand_host in url:
            score += 3
        if _LOW_TRUST.search(url):
            score -= 2
        if _NEVER.search(url):
            continue
        scored.append((score, url))
    scored.sort(key=lambda t: -t[0])
    return [u for _, u in scored[:limit]]
