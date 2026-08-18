"""Offer facts — the headline welcome offer and the ongoing proposition per
brand, read verbatim from the promotions/loyalty evidence (docs/81). Shared
by the deck's offers slide and the weekly brief's "offers that changed"."""

from __future__ import annotations

import re
from typing import Any

WELCOME_RE = re.compile(
    r"welcome|sign[- ]?up|new (player|user|customer)s?|first[- ]time|register|"
    r"joining|on registration|\d+\s*%\s*(extra|more|bonus)|no purchase",
    re.I,
)
BOILERPLATE_RE = re.compile(
    r"no purchase (is )?necessary|void where prohibited|free to play", re.I
)
QUANTITY_RE = re.compile(
    r"\d[\d,.]*\s*(%|percent|gc|sc|gold coins?|sweeps? coins?|coins?|free spins?|\$)|"
    r"\$\s*\d|\b\d{1,3}(,\d{3})+\b",
    re.I,
)


def welcome_score(claim: str, value_text: str = "") -> int:
    """How much a promotions claim reads as THE welcome offer. 0 = not a
    welcome claim at all."""
    text = f"{claim} {value_text}"
    if not WELCOME_RE.search(text):
        return 0
    score = 1
    if re.search(
        r"welcome|sign[- ]?up|new (player|user|customer)s?|first[- ]time|first purchase|"
        r"register|joining|on registration",
        text,
        re.I,
    ):
        score += 3
    if QUANTITY_RE.search(text):
        score += 3
    if re.search(r"\bfree\b|bonus|extra|bundle|gift|package", text, re.I):
        score += 1
    if BOILERPLATE_RE.search(text) and not QUANTITY_RE.search(text):
        score -= 3
    return max(score, 0)


ONGOING_RE = re.compile(
    r"daily|every day|ongoing|weekly|login|log-in|wheel|jackpot|giveaway|"
    r"tournament|leaderboard|challenge|quest|social media|refer",
    re.I,
)


def offer_facts(
    card: dict[str, Any],
    evidence: list[dict[str, Any]],
    exhibits: dict[str, list[dict[str, str]]] | None = None,
) -> list[dict[str, Any]]:
    """Per brand, the headline welcome offer and the ongoing proposition —
    verbatim claims from the promotions dimension, newest first — plus the
    promotions-page exhibit when one was captured. Ranked order, ours
    included; brands with nothing observed on promotions are listed with
    the honest blank so the table is a census, not a highlight reel."""
    rows = card.get("rows", [])
    order = sorted(
        rows,
        key=lambda r: (
            not r.get("is_self"),
            r.get("rank") if r.get("rank") is not None else 99,
            -(float(r["overall"]["normalized_pct"] or 0)),
        ),
    )
    by_brand: dict[str, list[dict[str, Any]]] = {}
    for e in evidence:  # newest first
        dim = str(e.get("dimension") or "").lower()
        if not ("promo" in dim or "loyalty" in dim or "offer" in dim or "bonus" in dim):
            continue
        claim = str(e.get("claim") or "").strip()
        if claim:
            by_brand.setdefault(str(e.get("subject") or ""), []).append(e)
    out: list[dict[str, Any]] = []
    for r in order:
        name = str(r["name"])
        rows_e = by_brand.get(name, [])
        # The headline welcome offer is the most SPECIFIC welcome claim on
        # record, not the newest regex hit: "5,000 free Gold Coins on
        # sign-up" beats "no purchase is necessary" (legal boilerplate that
        # merely mentions the funnel). Ties keep newest-first order.
        scored = sorted(
            (
                (welcome_score(str(e.get("claim") or ""), str(e.get("value_text") or "")), i, e)
                for i, e in enumerate(rows_e)
            ),
            key=lambda t: (-t[0], t[1]),
        )
        welcome = str(scored[0][2].get("claim")) if scored and scored[0][0] > 0 else ""
        ongoing = next(
            (
                str(e.get("claim"))
                for e in rows_e
                if str(e.get("claim")) != welcome
                and ONGOING_RE.search(
                    str(e.get("claim") or "") + " " + str(e.get("value_text") or "")
                )
            ),
            "",
        )
        if not welcome and rows_e:
            welcome = str(rows_e[0].get("claim"))  # newest promo claim, whatever it is
        src_row = next(
            (e for e in rows_e if str(e.get("claim")) == welcome), rows_e[0] if rows_e else {}
        )
        promo_shot = next(
            (s for s in (exhibits or {}).get(name, []) if s.get("kind") == "promo"),
            None,
        )
        out.append(
            {
                "brand": name,
                "is_self": bool(r.get("is_self")),
                "rank": r.get("rank"),
                "welcome": welcome,
                "ongoing": ongoing,
                "url": str(src_row.get("source_url") or ""),
                "observed_at": str(src_row.get("observed_at") or ""),
                "exhibit": promo_shot,
            }
        )
    return out
