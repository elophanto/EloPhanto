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
        out.append(
            {
                "name": name,
                "detail": detail,
                "coins_text": coins,
                "sort_index": index,
                "price_usd": parse_price(f"{name} {detail}") if kind == "coin_package" else None,
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
        per.append(
            {
                "subject_id": s.subject_id,
                "name": s.name,
                "is_self": bool(s.is_self),
                "counts": counts,
                "providers": [r.name for r in mine if r.kind == "provider"][:40],
                "packages": [
                    {"name": r.name, "price_usd": r.price_usd, "coins": r.coins_text,
                     "detail": r.detail, "url": r.source_url}
                    for r in ladder
                ],
                "promotions": [
                    {"name": r.name, "detail": r.detail, "image": r.image_path, "url": r.source_url}
                    for r in mine if r.kind == "promotion"
                ][:12],
                "games_sample": [r.name for r in mine if r.kind == "game"][:12],
                "customer_states": sorted({r.customer_state for r in mine}),
                "observed_at": max((r.observed_at for r in mine), default="")[:10],
            }
        )
    per.sort(key=lambda b: (not b["is_self"], b["name"]))
    return {
        "brands": per,
        "totals": totals,
        "items": sum(totals.values()),
        "kinds": list(CATALOG_KINDS),
        "label": "Raw inventory as printed on each brand's own pages — not scored.",
    }
