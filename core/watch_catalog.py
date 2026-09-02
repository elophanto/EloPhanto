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
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CATALOG_KINDS: tuple[str, ...] = (
    "provider",
    "coin_package",
    "promotion",
    "loyalty_tier",
    "game",
)

# Which page serves which kind. A store page is where the coins are sold;
# "promotions" is where the offers live; providers and games have their own
# pages on nearly every one of these sites.
_PAGE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("coin_package", re.compile(r"store|shop|buy|coins?-?(store|shop|package)|purchase|cashier|wallet", re.I)),
    ("loyalty_tier", re.compile(r"loyalty|vip|tiers?|club|status-?levels?|rewards?-?program", re.I)),
    ("promotion", re.compile(r"promo|promotion|offer|bonus|deal|reward|daily", re.I)),
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
        # A page the agent labelled is filed as labelled; the URL/title
        # patterns are for pages nobody labelled.
        kind = str(page.get("kind") or "") or catalog_page_kind(
            str(page.get("url") or ""), str(page.get("title") or "")
        )
        if not kind and page.get("via") == "agent" and page.get("text"):
            # A page the agent read as a player, that nothing could name:
            # try it for every kind — the item-on-page check keeps the
            # wrong ones out, and a lobby lost to a bare "/" URL is worse.
            for k in CATALOG_KINDS:
                bucket = out.setdefault(k, [])
                if len(bucket) < max(per_kind, 6):
                    bucket.append(page)
            continue
        if not kind or kind not in CATALOG_KINDS:
            continue
        bucket = out.setdefault(kind, [])
        if len(bucket) < per_kind:
            bucket.append(page)
    return out


# ── Signed-in reads ───────────────────────────────────────────────────
# A session lives in the browser profile, not in an HTTP client: a
# "registered" read that fetches over plain HTTP sees the logged-out site
# (2026-09-01/02: two registered re-reads wrote nothing while Pulsz's and
# Hello Millions' lobbies were live sessions in Chrome). So a signed-in
# read goes through the browser only — the lobby first, then the pages a
# player reaches by clicking: Providers, Get Coins, Promotions, VIP.
_SIGNED_IN_NAV: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("provider", "Providers", ("Providers", "Game Providers", "Studios")),
    ("coin_package", "Store – Get Coins", ("Get Coins", "Buy Coins", "Store", "Shop", "Buy", "Cashier")),
    ("promotion", "Promotions", ("Promotions", "Promos", "Specials", "Offers", "Rewards", "Daily Bonus")),
    ("loyalty_tier", "VIP loyalty club", ("VIP", "Loyalty", "Loyalty Lounge", "VIP Club", "Status")),
)


async def _scroll_to_load(bm: Any, rounds: int = 4, wait_ms: int = 900) -> None:
    """Lobbies lazy-load their grid; scroll the page to the bottom a few
    times so the titles are in the DOM before it is read."""
    for _ in range(max(1, rounds)):
        try:
            await bm.call_tool("browser_eval", {"code": "window.scrollTo(0, document.body.scrollHeight)"})
            await bm.call_tool("browser_wait", {"ms": wait_ms})
        except Exception:
            return
    try:
        await bm.call_tool("browser_eval", {"code": "window.scrollTo(0, 0)"})
    except Exception:
        pass


async def _rendered_text(bm: Any, max_chars: int = 60000) -> str:
    from core.watch_observe import _result_text, html_to_text

    try:
        raw = _result_text(await bm.call_tool("browser_get_html", {"maxLength": 400000}))   # default cuts at 50k
    except Exception:
        return ""
    return " ".join(html_to_text(raw).split())[:max_chars]


LOBBY_GOAL = """You are signed in to {url} in the agent's own Chrome, as a player. Visit, one at a
time, by clicking what you can see on the page (menus, sidebar, header — look with
browser_get_elements or browser_screenshot first, act, then look again):
{wanted}
For EACH page you reach: scroll to the bottom a few times so lazy-loaded grids are
complete (browser_scroll), then call browser_get_html ONCE — that call is what puts
the page on record (ask for a small maxLength if you like; the record is taken in
full regardless). Prefer browser_get_elements over screenshots: it is faster and
enough to find the next control. Do not accept, agree to, buy or claim anything; if a modal asks
you to agree to terms, leave it and read the page behind it. Never guess an address:
you cannot navigate. If a page cannot be found by clicking, skip it.

Finish with EXACTLY one line per browser_get_html call you made, in order, and nothing
else:
PAGE 1: lobby|providers|store|promotions|vip|other
PAGE 2: ...
"""
_LOBBY_WANTED = {
    "game": "- the games lobby: the main grid of games (usually the home page after sign-in)",
    "provider": "- the page or filter listing the game providers / studios",
    "coin_package": "- the coin store, where a player buys coin packages (often 'Get Coins' / 'Buy' / 'Store')",
    "promotion": "- the promotions / offers / rewards page",
    "loyalty_tier": "- the loyalty / VIP club page with its tiers",
}
_LOBBY_TITLES = {
    "lobby": "Lobby games", "providers": "Providers", "store": "Store – Get Coins",
    "promotions": "Promotions", "vip": "VIP loyalty club", "other": "Other page",
}
_LOBBY_KINDS = {"lobby": "game", "providers": "provider", "store": "coin_package",
                "promotions": "promotion", "vip": "loyalty_tier"}
_AGENT_LOBBY_TOOLS = frozenset({
    "browser_click", "browser_click_text", "browser_click_at", "browser_press_key",
    "browser_select_option", "browser_scroll", "browser_scroll_container", "browser_hover",
    "browser_hover_element", "browser_go_back", "browser_extract", "browser_read_semantic",
    "browser_get_elements", "browser_screenshot", "browser_get_html", "browser_get_element_html",
    "browser_get_element_box", "browser_get_meta", "browser_dom_search", "browser_wait",
    "browser_wait_for_selector",
})


class _PageRecorder:
    """Wraps the browser manager for the duration of a delegated read and
    keeps every ``browser_get_html`` result with the URL it was read at —
    the agent's tool results do not come back to the caller otherwise."""

    def __init__(self, bm: Any) -> None:
        self._bm = bm
        self._orig = bm.call_tool
        self.pages: list[dict[str, Any]] = []

    async def call_tool(self, name: str, params: dict[str, Any] | None = None) -> Any:
        res = await self._orig(name, params or {})
        if name == "browser_get_html":
            from core.watch_observe import _result_text, html_to_text

            # The agent may ask for a short maxLength to spare its context;
            # the record needs the whole DOM (2026-09-02: four pages captured,
            # nothing extracted). Capture it ourselves, return the agent its own.
            try:
                full = await self._orig("browser_get_html", {"maxLength": 400000})
            except Exception:
                full = res
            try:
                here = await self._orig("browser_eval", {"expression": "location.href", "maxLength": 2000})
                url = _result_text(here) if isinstance(here, str) else str(
                    json.loads((here or {}).get("resultJson") or '""')) if isinstance(here, dict) else ""
            except Exception:
                url = ""
            text = " ".join(html_to_text(_result_text(full)).split())[:150000]
            self.pages.append({"url": url, "text": text, "chars": len(text)})
        return res

    def __enter__(self) -> _PageRecorder:
        self._bm.call_tool = self.call_tool
        return self

    def __exit__(self, *exc: Any) -> None:
        self._bm.call_tool = self._orig


async def agent_reads_lobby(agent: Any, bm: Any, start_url: str, kinds: list[str], *, timeout: float = 900.0) -> list[dict[str, Any]]:
    """The agent visits the lobby, providers, store, promotions and VIP
    pages by clicking what it sees; every ``browser_get_html`` it makes is
    recorded here with the URL, and its final report names which page each
    capture was. Never raises; [] when the agent is missing or fails."""
    import asyncio

    if agent is None or bm is None:
        return []
    wanted = "\n".join(_LOBBY_WANTED[k] for k in ("game", "provider", "coin_package", "promotion", "loyalty_tier") if k in kinds)
    if not wanted:
        return []
    try:
        all_names = {t.name for t in agent._registry.all_tools()}
    except Exception:
        all_names = set()
    excluded = {n for n in all_names if n not in _AGENT_LOBBY_TOOLS}
    rec = _PageRecorder(bm)
    with rec:
        try:
            resp = await asyncio.wait_for(
                agent.run_isolated(LOBBY_GOAL.format(url=start_url, wanted=wanted),
                                   excluded_tool_names=excluded, max_steps_override=40),
                timeout=timeout,
            )
        except Exception as e:
            logger.warning("watch_catalog: agent lobby read stopped: %s (%d page(s) kept)",
                           f"{type(e).__name__}: {e}".strip(": "), len(rec.pages))
            resp = None
    report = str(getattr(resp, "content", "") or "")
    logger.info("watch_catalog: agent lobby report: %s", " ".join(report.split())[:400])
    labels = _page_labels(report, len(rec.pages))
    out: list[dict[str, Any]] = []
    for i, page in enumerate(rec.pages):
        label = labels[i] if i < len(labels) else ""
        kind = _LOBBY_KINDS.get(label, "") or catalog_page_kind(str(page["url"] or ""), "")
        title = _LOBBY_TITLES.get(label) or next(
            (t for lab, t in _LOBBY_TITLES.items() if _LOBBY_KINDS.get(lab) == kind), "Other page"
        )
        out.append({
            "url": page["url"] or f"{start_url.rstrip('/')}/#{label or i}", "title": title,
            "text": page["text"], "error": None if page["text"] else f"{title}: no text",
            "method": "browser_session", "via": "agent", "kind": kind,
            "chars": page.get("chars", len(page["text"])),
        })
    logger.info("watch_catalog: agent read %d page(s): %s", len(out),
                ", ".join(f"{p['title']} ({p['chars']} chars)" for p in out))
    return out


_LABEL_WORDS = {
    "lobby": ("lobby", "home", "games grid", "game grid", "main grid"),
    "providers": ("provider", "studio"),
    "store": ("store", "get coins", "buy coins", "coin package", "shop", "purchase"),
    "promotions": ("promotion", "promo", "offer", "reward"),
    "vip": ("vip", "loyalty"),
}


def _page_labels(report: str, n_pages: int) -> list[str]:
    """The agent's report, read loosely: 'PAGE 1: lobby' is the asked-for
    form, but 'Page 1 – the store (Get Coins)' and a plain numbered list
    happen too (2026-09-02: three pages, all 'other'). One label per
    numbered line, in order; '' where nothing recognisable is said."""
    labels: list[str] = []
    for m in re.finditer(r"(?im)^\W*(?:page\s*)?(\d+)\s*[:.)\-–]\s*(.+)$", report):
        line = m.group(2).lower()
        found = ""
        for label, words in _LABEL_WORDS.items():
            if any(w in line for w in words):
                found = label
                break
        labels.append(found)
    return labels[:n_pages]


async def read_signed_in_pages(
    bm: Any, start_url: str, kinds: list[str], *, scroll_rounds: int = 4, agent: Any = None,
) -> list[dict[str, Any]]:
    """Read a brand as the signed-in player the browser already is. Returns
    pages shaped like ``collect_pages`` (url, title, text, error, method)
    with ``method="browser_session"``; titles name the kind so
    :func:`rank_catalog_pages` files them. A modal (an updated Terms of
    Use, a promo) does not stop the read — the DOM behind it is read, and
    nothing is accepted on the player's behalf."""
    from core.watch_login import _click_text
    from core.watch_observe import dismiss_consent

    pages: list[dict[str, Any]] = []
    if bm is None or not start_url:
        return pages
    if agent is not None:
        # The agent drives (docs/90); the label loop below is the fallback
        # when no agent is wired in, and its labels are only hints.
        await bm.call_tool("browser_navigate", {"url": start_url})
        await bm.call_tool("browser_wait", {"ms": 3500})
        await dismiss_consent(bm)
        got = await agent_reads_lobby(agent, bm, start_url, kinds)
        if got:
            return got

    async def open_home() -> None:
        await bm.call_tool("browser_navigate", {"url": start_url})
        await bm.call_tool("browser_wait", {"ms": 3500})
        await dismiss_consent(bm)

    try:
        await open_home()
        await _scroll_to_load(bm, scroll_rounds)
        text = await _rendered_text(bm)
        pages.append({"url": start_url, "title": "Lobby games", "text": text,
                      "error": None if text else "lobby returned no text", "method": "browser_session"})
    except Exception as e:
        return [{"url": start_url, "title": "Lobby games", "text": "", "error": f"browser: {e}",
                 "method": "browser_session"}]
    for kind, title, labels in _SIGNED_IN_NAV:
        if kind not in kinds:
            continue
        hit = ""
        for label in labels:
            try:
                hit = await _click_text(bm, label, exact=False)
            except Exception:
                hit = ""
            if hit:
                break
        if not hit:
            continue
        try:
            await bm.call_tool("browser_wait", {"ms": 2500})
            await _scroll_to_load(bm, scroll_rounds)
            text = await _rendered_text(bm)
            pages.append({"url": f"{start_url.rstrip('/')}/#{kind}", "title": title, "text": text,
                          "error": None if text else f"{title}: no text", "method": "browser_session",
                          "via": hit})
            await open_home()
        except Exception as e:
            pages.append({"url": f"{start_url.rstrip('/')}/#{kind}", "title": title, "text": "",
                          "error": f"browser: {e}", "method": "browser_session"})
            try:
                await open_home()
            except Exception:
                break
    return pages


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


# A magnitude letter only counts when it is not the start of a word —
# "25 Mystery Coins" is 25, not 25 million.
_NUM = r"(\d[\d,]*(?:\.\d+)?)\s*([kKmM](?![A-Za-z]))?"
# "CC" (Crown Coins) and "WC" (WOW Coins) are brands' own abbreviations for
# their gold coin — as much "gold" as "GC" is.
_GC_RE = re.compile(
    _NUM + r"\s*(?:gold coins?|gc\b|cc\b|wc\b|[A-Za-z]+ coins?(?!\s*(?:sc|sweeps)))"
    r"|(?:gc|cc|wc|gold coins?)\s*[:=]?\s*" + _NUM,
    re.I,
)
_SC_RE = re.compile(
    _NUM + r"\s*(?:free\s+)?(?:sweeps?\s*coins?|sc\b|sweepstakes coins?)"
    r"|(?:sc|sweeps?\s*coins?)\s*[:=]?\s*" + _NUM,
    re.I,
)


def _to_number(num: str, mag: str | None) -> float | None:
    try:
        v = float(num.replace(",", ""))
    except Exception:
        return None
    if mag and mag.lower() == "k":
        v *= 1_000
    elif mag and mag.lower() == "m":
        v *= 1_000_000
    return v


def parse_coins(text: str) -> tuple[float | None, float | None]:
    """Gold coins and sweeps coins out of a grant line, as printed:
    '800,000 GC 50 SC' → (800000, 50); '120K Gold Coins + 60 SC FREE' →
    (120000, 60); '1,500,000 Crown Coins, 75 SC' → (1500000, 75). A brand's
    own name for gold coins ("Crown Coins", "WOW Coins") counts as gold;
    anything that is not a number stays None — never guessed."""
    t = text or ""
    gc = sc = None
    m = _SC_RE.search(t)
    if m:
        num = m.group(1) or m.group(3)
        mag = m.group(2) or m.group(4)
        sc = _to_number(num, mag) if num else None
        t_no_sc = t[: m.start()] + " " + t[m.end() :]
    else:
        t_no_sc = t
    m = _GC_RE.search(t_no_sc)
    if m:
        num = m.group(1) or m.group(3)
        mag = m.group(2) or m.group(4)
        gc = _to_number(num, mag) if num else None
    return gc, sc


def item_is_on_page(name: str, page_text: str) -> bool:
    """An item counts only if its name is actually printed on the page —
    the list version of excerpt verification."""
    n = " ".join((name or "").lower().split())
    if len(n) < 2:
        return False
    return n in " ".join((page_text or "").lower().split())



def format_coins(gc: float | None, sc: float | None) -> str:
    """"1,500,000 GC + 75 SC" from the two numbers; '' when neither is known."""
    def one(v: float) -> str:
        return f"{int(v):,}" if v == int(v) else f"{v:,.2f}"
    parts = []
    if gc is not None:
        parts.append(f"{one(gc)} GC")
    if sc is not None:
        parts.append(f"{one(sc)} SC")
    return " + ".join(parts)


# Frequency and claim route read off a promotion's own words. The model is
# asked for both; these fill the blanks it leaves and the rows collected
# before the columns existed. First match wins, so the order is the
# precedence: a stated cadence beats a trigger, an end date beats a
# sign-up trigger (a dated welcome offer is a limited-time offer).
_FREQ_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(rx, re.I)) for label, rx in (
        ("Daily", r"\bdaily\b|every\s+24\s*hours|every\s+day\b|each\s+day\b|\bnightly\b|per\s+day\b"),
        ("Weekly", r"\bweekly\b|every\s+week\b|each\s+week\b|per\s+week\b"
                   r"|every\s+(?:mon|tues|wednes|thurs|fri|satur|sun)day"),
        ("Monthly", r"\bmonthly\b|every\s+month\b|each\s+month\b|per\s+month\b"),
        ("Per referral", r"\brefer(?:ral|-a-friend|\s+a\s+friend)?\b"),
        ("Limited time", r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
                         r"|\d{1,2}/\d{1,2}/\d{4}|\bexpires?\b|limited[\s-]time|\bseasonal\b"),
        ("One-time", r"sign[\s-]?up|\bwelcome\b|no[\s-]deposit|first[\s-]purchase"
                     r"|new\s+(?:users?|players?)\b|\bregister"),
        ("Ongoing", r"\bongoing\b|\bcontinuous\b"),
    )
)
_NO_CODE = re.compile(
    r"\b(?:no|not)\s+(?:\w+\s+){0,5}codes?\b"                                     # "no Crown Coins Casino promo code"
    r"|\b(?:don.?t\s+need|without|doesn.?t\s+require|isn.?t\s+required)\b[^.;]{0,40}\bcodes?\b"
    r"|\bcodes?\s+(?:is\s+)?not\s+(?:needed|required)\b"                          # "code not required"
    r"|\bcodes?\s+required\s*:?\s*no\b",                                          # "Promo code required No"
    re.I,
)
# The code itself is case-sensitive: an all-caps token with a digit or at
# least four letters, so "Promo Code Required" and "code 2026" are not codes.
_CODE = re.compile(
    r"(?i:(?:bonus|promo|coupon|referral)\s+code)\s*[:\-]?\s*(?:(?i:use)\s+)?[\'\"“‘]?\s*([A-Z][A-Z0-9]{3,})?"
)
_NOT_A_CODE = frozenset({"REQUIRED", "NEEDED", "EARN", "FREE", "BONUS", "ONLY", "HERE", "BELOW", "ABOVE"})
_CODE_CHECK = "__code__"
_CLAIM_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(rx, re.I)) for label, rx in (
        ("Mail-in request", r"mail[\s-]?in|\bamoe\b|postcard|handwritten|alternative method of entry"),
        ("Share referral link", r"\brefer(?:ral|-a-friend|\s+a\s+friend)?\b"),
        ("Follow social channels", r"social\s+media|facebook|instagram|\btwitter\b|\btiktok\b"),
        (_CODE_CHECK, r"$^"),        # promo codes are read here, after the routes that hand one out
        ("Opt in", r"\bopt(?:ing|ed)?[\s-]in\b"),
        ("First purchase", r"first[\s-]purchase|first\s+(?:deposit|buy)\b"),
        ("Sign up", r"sign[\s-]?up|\bregister|creat(?:e|ing)\s+(?:an?\s+|your\s+)?(?:\w+\s+)?account"
                    r"|new\s+(?:users?|players?)\b"),
        ("Log in", r"\blog[\s-]?(?:in|into)\b|\bsign(?:ed)?[\s-]?(?:in|into)\b"),
        ("Watch inbox", r"\binbox\b|\be-?mails?\b"),
        ("Play qualifying games", r"tournament|qualifying|\bplay(?:ing)?\b|\bspins?\b|\bwager|\bslots?\b"),
        ("Purchase", r"(?<!no )purchase|\bbuy\b|\bbundle\b|coin\s+package|\bdiscount"),
    )
)
_BOILERPLATE = re.compile(
    r"^\s*(?:t&cs?\b|terms\b|18\+|21\+|last verified|upon sign|no purchase necessary|void where|see (?:terms|rules))",
    re.I,
)


def parse_frequency(name: str, detail: str = "") -> str:
    """How often the offer recurs, from its own words — '' when it never says."""
    text = f"{name} {detail}"
    for label, rx in _FREQ_RULES:
        if rx.search(text):
            return label
    return ""


def parse_claim(name: str, detail: str = "") -> str:
    """The claiming mechanic, from the offer's own words — '' when it never says."""
    text = f"{name} {detail}"
    for label, rx in _CLAIM_RULES:
        if label == _CODE_CHECK:
            if _NO_CODE.search(text):
                continue
            m = _CODE.search(text)
            if not m:
                continue
            code = m.group(1) or ""
            if code and code not in _NOT_A_CODE and not code.isdigit():
                return f"Use code {code}"
            return "Enter promo code"
        if rx.search(text):
            if label == "Sign up" and re.search(r"verif", text, re.I):
                return "Sign up + verify"
            return label
    return ""


def promo_fields(name: str, detail: str, meta: dict[str, Any] | None) -> dict[str, str]:
    """Benefit · how to claim · frequency for one promotion row. What the
    model read wins; the readers above fill what it left blank, so a row
    collected before these columns existed still fills the table."""
    meta = meta or {}
    detail = (detail or "").strip()
    benefit = (meta.get("benefit") or "").strip()
    if not benefit:
        gc, sc = parse_coins(detail)
        if detail and (gc is not None or sc is not None or not _BOILERPLATE.match(detail)):
            benefit = detail
        else:
            gc, sc = parse_coins(name)      # "Get 1.5M CC + 75 FREE SC" — the grant is in the title
            benefit = format_coins(gc, sc) or detail
    return {
        "benefit": benefit,
        "how_to_claim": (meta.get("how_to_claim") or "").strip() or parse_claim(name, detail),
        "frequency": (meta.get("frequency") or "").strip() or parse_frequency(name, detail),
    }


CATALOG_SYSTEM = """You read one page from a sweepstakes / social casino site and list the
items of ONE requested kind that are printed on it. You are given the
brand, the kind, and the page text.

kind meanings and what "name" is:
- provider: a game studio / software supplier ("Pragmatic Play"). name =
  the studio name exactly as printed.
- coin_package: one purchasable package. name = the price as printed
  ("$29.99") or the package label; coins = what it grants, verbatim
  ("GC 700 + free SC 55"); detail = any extra ("first purchase only");
  gold_coins / sweeps_coins = the two numbers when the page states them.
- promotion: one offer. name = its title as printed ("Daily Login Bonus");
  benefit = what the player gets, as printed ("1500GC + 0.2SC, rising to
  2500GC and 0.25SC after 3 consecutive days"); how_to_claim = the
  mechanic ("Login daily", "Share a referral link"); frequency = one of
  daily / weekly / monthly / one-time / continuous / ad hoc when stated;
  detail = remaining terms and dates.
- loyalty_tier: one tier of the loyalty / VIP club. name = the tier as
  printed ("Bronze"); qualification = what earns it, as printed ("500,000
  GC purchased per month"); reward = what it gives ("25% weekly coin
  boost"); index = the tier's order, lowest first.
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

Return STRICT JSON — omit fields that do not apply to the kind:
{"items":[{"name":str,"detail":str,"coins":str,"gold_coins":number,"sweeps_coins":number,
"benefit":str,"how_to_claim":str,"frequency":str,"qualification":str,"reward":str,"index":int}]}"""


# What a kind looks like on a page, for choosing the window the model
# reads when the page is longer than the window. A store opened as a
# modal sits at the END of the DOM, behind the whole lobby (Pulsz,
# 2026-09-02: 60,000 characters captured, the first 22,000 read, no
# packages found).
_FOCUS_MARKS: dict[str, re.Pattern[str]] = {
    "coin_package": re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?|\b\d[\d,]{2,}\s*(?:GC|SC|gold coins|sweeps coins)\b", re.I),
    "loyalty_tier": re.compile(r"\b(?:bronze|silver|gold|platinum|diamond|emerald|ruby|sapphire|elite|royal|"
                               r"tier|level|status)\b", re.I),
    "promotion": re.compile(r"\b(?:bonus|offer|promo|promotion|reward|free spins?|daily|weekly)\b", re.I),
    "provider": re.compile(r"\b(?:provider|studio|gaming|games|play)\b", re.I),
    "game": re.compile(r"\b(?:slots?|jackpot|hold and win|megaways|bonanza|fortune|gold|wild)\b", re.I),
}


def focus_text(kind: str, text: str, limit: int = 22000, step: int = 2000) -> str:
    """The ``limit`` characters of ``text`` densest in the marks of ``kind``,
    so a long capture is read where the kind actually is. Short text is
    returned whole; a page with no marks reads from the top."""
    text = text or ""
    if len(text) <= limit:
        return text
    rx = _FOCUS_MARKS.get(kind)
    if rx is None:
        return text[:limit]
    positions = [m.start() for m in rx.finditer(text)]
    if not positions:
        return text[:limit]
    best_start, best_n = 0, -1
    last = max(0, len(text) - limit)
    for start in [*range(0, last, step), last]:      # the tail is always a candidate — modals live there
        n = sum(1 for p in positions if start <= p < start + limit)
        if n > best_n:
            best_start, best_n = start, n
    return text[best_start:best_start + limit]


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
        {"brand": brand, "kind": kind, "max_items": max_items, "page_text": focus_text(kind, page_text)}
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
        meta: dict[str, Any] = {}
        if kind == "coin_package":
            gc, sc = parse_coins(coins or detail)
            for key, model_val, parsed in (("gold_coins", it.get("gold_coins"), gc),
                                            ("sweeps_coins", it.get("sweeps_coins"), sc)):
                val = parsed if parsed is not None else model_val
                if isinstance(val, int | float):
                    meta[key] = float(val)
        elif kind == "promotion":
            for key in ("benefit", "how_to_claim", "frequency"):
                val = " ".join(str(it.get(key) or "").split())
                if val:
                    meta[key] = val[:300]
            for key, val in promo_fields(name, detail, meta).items():
                if val and not meta.get(key):
                    meta[key] = val          # read off the row's own words
        elif kind == "loyalty_tier":
            for key in ("qualification", "reward"):
                val = " ".join(str(it.get(key) or "").split())
                if val:
                    meta[key] = val[:300]
        out.append(
            {
                "name": name,
                "detail": detail,
                "coins_text": coins,
                "sort_index": index,
                "price_usd": price,
                "meta": meta,
            }
        )
        if len(out) >= max_items:
            break
    return out


# ── Game portfolio: Provider × Brand ─────────────────────────────────
# The client's own sheet is a matrix — one row per studio, one column per
# brand — and its column A is their list of studios. Brands and review
# sites print the same studio five ways ("BGaming", "B Gaming", "BGAMING",
# "Relax", "Relax Gaming"), so the matrix works on a canonical key and
# shows one printed form; the rows stay as printed in the register.
_PROVIDER_SUFFIX = re.compile(
    r"\s*\b(?:gaming|games|game|studios?|entertainment|interactive|slots|software|ltd|inc|limited|group)\b\.?\s*$",
    re.I,
)
_PROVIDER_ALIASES = {
    "b": "bgaming", "4tp": "4theplayer", "gamzik": "gamzix", "btg": "bigtime",
    "vgw": "virtualgamingworlds", "1x2network": "1x2", "1x2gaming": "1x2",
    "n2": "n2live", "peterandsons": "petersons", "m2playmicrogaming": "m2play",
}


def canonical_provider(name: str) -> str:
    """One key for every way a studio gets printed. Never shown — the
    printed form is; this only decides which printed forms are one studio."""
    n = re.sub(r"\(.*?\)", "", name or "")             # "4TP (is this 4 the player?)"
    n = re.sub(r"(\d)\s*[x×]\s*(\d)", r"\1by\2", n)      # "2×2", "2 By 2", "2By2"
    prev = None
    while prev != n:                                     # "Evoplay Entertainment Games"
        prev, n = n, _PROVIDER_SUFFIX.sub("", n).strip()
    key = re.sub(r"[^a-z0-9]", "", n.lower())
    if not key:                                          # the whole name was a suffix word
        key = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    m = re.match(r"^(.{3,}?)(games|gaming|studios?)$", key)   # "ElaGames", "FantasmaGames"
    if m:
        key = m.group(1)
    return _PROVIDER_ALIASES.get(key, key)


def brand_key(name: str) -> str:
    """'LuckyLand Casino', 'LuckyLand Slots' and 'High5 Casino' vs 'High 5
    Casino' are the same brands under different labels."""
    n = re.sub(r"\b(?:casino|slots|social|sweepstakes)\b", "", name or "", flags=re.I)
    return re.sub(r"[^a-z0-9]", "", n.lower())


def read_provider_universe(path: str | Path) -> dict[str, Any]:
    """The client's game-portfolio sheet: column A is their studio list, the
    header row's other cells are their brand columns. Semicolon or comma
    separated; a count row ("155") and blank rows are skipped."""
    import csv

    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    head = "\n".join(text.splitlines()[:5])
    delim = ";" if head.count(";") > head.count(",") else ","
    providers: list[str] = []
    brands: list[str] = []
    seen_header = False
    for row in csv.reader(text.splitlines(), delimiter=delim):
        if not row:
            continue
        first = row[0].strip()
        if not seen_header:
            if "provider" in first.lower() or "studio" in first.lower():
                seen_header = True
                brands = [c.strip() for c in row[1:] if c.strip()]
            continue
        if not first or first.isdigit() or first.lower() in {"total", "count"}:
            continue
        providers.append(" ".join(first.split()))
    if not seen_header:      # no header row: every non-empty first cell is a studio
        providers = [
            " ".join(r[0].split()) for r in csv.reader(text.splitlines(), delimiter=delim)
            if r and r[0].strip() and not r[0].strip().isdigit()
        ]
    return {"providers": providers, "brands": brands, "path": str(path)}


def provider_matrix(
    items: list[dict[str, Any]],
    brands: list[dict[str, Any]],
    universe: list[str] | None = None,
    universe_brands: list[str] | None = None,
) -> dict[str, Any]:
    """Provider × Brand. ``items`` are catalog rows as dicts (brand, kind,
    name, detail, source_type); ``brands`` the register's order ({name,
    is_self}). With ``universe`` (the client's list) the rows follow that
    list first, and studios we observed that are not on it come after,
    marked; a studio on the list that nothing has shown yet stays a row
    with empty cells — the client can see the gap, not just our answer."""
    order = [b["name"] for b in brands]
    forms: dict[str, dict[str, int]] = {}
    carried: dict[str, dict[str, str]] = {}
    for it in items:
        if it.get("kind") != "provider":
            continue
        key = canonical_provider(it.get("name", ""))
        if not key:
            continue
        forms.setdefault(key, {})
        forms[key][it["name"]] = forms[key].get(it["name"], 0) + 1
        src = it.get("source_type") or "site"
        prev = carried.setdefault(key, {}).get(it["brand"])
        if prev is None or (src == "site" and prev != "site"):
            carried[key][it["brand"]] = src
    games: dict[str, dict[str, int]] = {}
    known = set(carried) | {canonical_provider(u) for u in (universe or [])}
    for it in items:
        if it.get("kind") != "game" or not it.get("detail"):
            continue
        key = canonical_provider(it["detail"])
        if key in known:     # "Jackpot Slots" / "TABLE GAMES" are categories, not studios
            games.setdefault(key, {})
            games[key][it["brand"]] = games[key].get(it["brand"], 0) + 1

    def display(key: str, fallback: str = "") -> str:
        printed = forms.get(key)
        if printed:
            return max(printed.items(), key=lambda kv: (kv[1], -len(kv[0])))[0]
        return re.sub(r"\s*\(.*?\)", "", fallback).strip() or key

    rows: list[dict[str, Any]] = []
    listed: set[str] = set()
    for label in universe or []:
        key = canonical_provider(label)
        if not key or key in listed:
            continue
        listed.add(key)
        rows.append({"key": key, "name": display(key, label), "on_client_list": True})
    for key in sorted(set(carried) - listed,
                      key=lambda k: (-len(carried[k]), display(k).lower())):
        rows.append({"key": key, "name": display(key), "on_client_list": not universe})
    for row in rows:
        key = row["key"]
        cells = {}
        for b in order:
            src = carried.get(key, {}).get(b)
            cells[b] = {"carried": src is not None, "source": src or "",
                        "games": games.get(key, {}).get(b, 0)}
        row["brands"] = cells
        row["brand_count"] = sum(1 for c in cells.values() if c["carried"])
        row["observed"] = row["brand_count"] > 0
    ours = {brand_key(b): b for b in order}
    theirs = [brand_key(b) for b in (universe_brands or [])]
    return {
        "providers": rows,
        "brands": order,
        "counts": {
            "observed": len(carried),
            "on_client_list": len(listed),
            "both": sum(1 for r in rows if r["on_client_list"] and r["observed"]),
            "list_only": sum(1 for r in rows if r["on_client_list"] and not r["observed"]),
            "observed_only": sum(1 for r in rows if not r["on_client_list"]),
        },
        "brands_only_on_client_list": [
            b for b in (universe_brands or []) if brand_key(b) not in ours
        ],
        "brands_only_in_register": [b for k, b in ours.items() if theirs and k not in theirs],
    }


def catalog_items(rows: list[Any], subjects: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Register rows → the plain dicts the matrix reads, and the brand order
    (ours first, then the register's alphabetical)."""
    names = {s.subject_id: s.name for s in subjects}
    items = [
        {"brand": names.get(r.subject_id, r.subject_id), "kind": r.kind, "name": r.name,
         "detail": r.detail, "source_type": getattr(r, "source_type", "site")}
        for r in rows if r.subject_id in names
    ]
    brands = sorted(({"name": s.name, "is_self": bool(s.is_self)} for s in subjects
                     if any(r.subject_id == s.subject_id for r in rows)),
                    key=lambda b: (not b["is_self"], b["name"]))
    return items, brands


def summarize_catalog(
    rows: list[Any], subjects: list[Any], universe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Counts per brand × kind, each brand's price ladder, the promotions
    that carry a picture, and the Provider × Brand matrix (following the
    client's own studio list when ``universe`` is given). Pure computation."""
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
                "providers": [r.name for r in mine if r.kind == "provider"][:200],   # raw data: all of them
                "sources": sources,
                "packages": [
                    {"name": r.name, "price_usd": r.price_usd, "coins": r.coins_text,
                     "detail": r.detail, "url": r.source_url, "source_type": r.source_type,
                     "gold_coins": (r.meta or {}).get("gold_coins"),
                     "sweeps_coins": (r.meta or {}).get("sweeps_coins")}
                    for r in ladder
                ],
                "tiers": [
                    {"name": r.name, "qualification": (r.meta or {}).get("qualification", ""),
                     "reward": (r.meta or {}).get("reward", "") or r.detail, "url": r.source_url}
                    for r in sorted((x for x in mine if x.kind == "loyalty_tier"),
                                    key=lambda x: x.sort_index)
                ],
                "promotions": [
                    {"name": r.name, "detail": r.detail, "image": r.image_path, "url": r.source_url}
                    for r in mine if r.kind == "promotion"
                ],
                "games_sample": [r.name for r in mine if r.kind == "game"][:12],
                "games_full": [r.name for r in mine if r.kind == "game"],
                "promotions_full": [
                    {"name": r.name, "detail": r.detail, "image": r.image_path, "url": r.source_url,
                     **promo_fields(r.name, r.detail, r.meta)}
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
    items, order = catalog_items(rows, subjects)
    matrix = provider_matrix(
        items, order,
        universe=(universe or {}).get("providers"),
        universe_brands=(universe or {}).get("brands"),
    ) if totals.get("provider") else None
    return {
        "brands": per,
        "totals": totals,
        "third_party_only": third_party_only,
        "matrix": matrix,
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
    "loyalty_tier": (
        '"{brand}" loyalty club tiers VIP levels rewards',
        '"{brand}" VIP program tiers bronze silver gold platinum',
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
_LEGAL_ONLY = re.compile(r"privacy|terms|tos\b|cookie|responsible|/rules|faq|/help|/support", re.I)
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


# Review sites whose per-brand page is at a predictable address, and whose
# pages are written per brand (so attribution is not in doubt). Endorsed by
# the operator 2026-09-01: igamingfuture. Tried before any search.
KNOWN_REVIEW_URLS: tuple[str, ...] = (
    "https://igamingfuture.com/sweepstakes-casinos/reviews/{slug}/",
)
_TRUSTED_HOSTS = re.compile(r"igamingfuture\.com", re.I)


def brand_slug(brand: str) -> str:
    """'Crown Coins Casino' → 'crown-coins' — the way review sites name them."""
    bare = re.sub(r"\b(casino|slots|social)\b", "", brand, flags=re.I)
    return re.sub(r"[^a-z0-9]+", "-", bare.lower()).strip("-")


def known_review_urls(brand: str) -> list[str]:
    slug = brand_slug(brand)
    return [t.format(slug=slug) for t in KNOWN_REVIEW_URLS if slug]


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
        if _TRUSTED_HOSTS.search(url):
            score += 2
        if _LOW_TRUST.search(url):
            score -= 2
        # Only genuinely legal pages are refused here; review sites file
        # brands under paths like /sweepstakes-casinos/reviews/…, and the
        # brand-page filter's "sweepstake" word would throw those away.
        if _LEGAL_ONLY.search(url):
            continue
        scored.append((score, url))
    scored.sort(key=lambda t: -t[0])
    return [u for _, u in scored[:limit]]
