"""Regulatory register — what regulators and courts do to the market
(docs/88 §D).

Bills, effective dates, enforcement actions, lawsuits, guidance, and what
each operator did when a state closed. Read from public sources: a web
search per priority jurisdiction and per tracked brand, the pages fetched
the organ's way, and one extraction contract whose excerpts must appear
verbatim on the page or the item is dropped. Everything is third-party
provenance with URL, date observed and exit IP; nothing here is legal
advice — the register says what was published and where.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

REG_KINDS: tuple[str, ...] = (
    "bill",
    "effective_date",
    "enforcement",
    "lawsuit",
    "guidance",
    "operator_response",
)

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia",
}


def state_name(code_or_name: str) -> str:
    c = (code_or_name or "").strip()
    return US_STATES.get(c.upper(), c)


def regulatory_queries(states: list[str], brands: list[str], *, year: int) -> list[str]:
    """The search queries for one collection: per state and per brand."""
    qs: list[str] = []
    for st in states:
        name = state_name(st)
        qs.append(f"{name} sweepstakes casino bill {year} effective date")
        qs.append(f"{name} attorney general sweepstakes casino cease and desist {year}")
        qs.append(f"{name} social casino sweepstakes ban law signed {year}")
    for b in brands:
        qs.append(f'"{b}" lawsuit OR "cease and desist" OR "exits" state sweepstakes {year}')
    return qs


def dedupe_key(jurisdiction: str, kind: str, title: str, event_date: str = "") -> str:
    base = "|".join(
        [
            re.sub(r"[^a-z0-9]+", " ", (jurisdiction or "").lower()).strip(),
            kind or "",
            re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()[:60],
            (event_date or "")[:10],
        ]
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]


REG_EXTRACT_SYSTEM = """You read a web page about sweepstakes / social casino regulation in the
United States and list the concrete regulatory ITEMS on it. You are given
the tracked brand names, the priority jurisdictions, and the page text.

RULES
- One item per distinct fact: a bill (with number when stated), an
  effective date, an enforcement action (cease-and-desist, fine, order),
  a lawsuit (who sued whom), official guidance, or an operator response
  (a named brand leaving/blocking a state, with the date).
- kind: exactly one of bill, effective_date, enforcement, lawsuit,
  guidance, operator_response.
- jurisdiction: the US state's two-letter code, or "US" for federal.
- title: ≤ 120 characters, factual ("SB 5935 bans dual-currency
  sweepstakes; signed", "AG cease-and-desist to 9 operators").
- status: e.g. introduced / passed / signed / effective / filed / settled /
  announced — as the page says, else "".
- event_date: YYYY-MM-DD when the page states a date for THIS item
  (effective date, filing date, signing date), else "".
- subjects: the tracked brand names the item names, else [].
- excerpt: a SHORT VERBATIM span (≤ 200 chars) copied exactly from the
  page that supports the item. No paraphrase, no merging.
- Skip anything not about sweepstakes / social casino regulation, opinion
  pieces, and items with no supporting span. Never infer beyond the page.

Return STRICT JSON:
{"items":[{"kind":str,"jurisdiction":str,"title":str,"status":str,"event_date":str,
"subjects":[str],"excerpt":str}]}"""


async def extract_regulatory(
    router: Any,
    *,
    page_text: str,
    brands: list[str],
    states: list[str],
    max_items: int = 8,
) -> list[dict[str, Any]]:
    """Ask the model for items; validate kind/jurisdiction/date and drop any
    item whose excerpt is not on the page. [] on failure."""
    from core.watch_observe import verify_excerpt

    if router is None or not page_text.strip():
        return []
    user = json.dumps(
        {
            "brands": brands,
            "priority_jurisdictions": states,
            "page_text": page_text[:20000],
            "max_items": max_items,
        }
    )
    try:
        resp = await router.complete(
            messages=[
                {"role": "system", "content": REG_EXTRACT_SYSTEM},
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
        data = json.loads(text)
        raw = data.get("items", []) if isinstance(data, dict) else []
    except Exception as e:
        logger.warning("watch_regulatory: extraction failed: %s", e)
        return []
    out: list[dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind") or "").strip()
        if kind not in REG_KINDS:
            continue
        juris = str(it.get("jurisdiction") or "").strip().upper()
        if juris != "US" and juris not in US_STATES:
            # accept a full state name too
            code = next((c for c, n in US_STATES.items() if n.lower() == juris.lower()), "")
            if not code:
                continue
            juris = code
        date = str(it.get("event_date") or "").strip()[:10]
        if date and not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            date = ""
        excerpt = " ".join(str(it.get("excerpt") or "").split())[:240]
        if not verify_excerpt(excerpt, page_text):
            continue
        title = " ".join(str(it.get("title") or "").split())[:160]
        if not title:
            continue
        subjects = [str(b) for b in (it.get("subjects") or []) if str(b) in brands]
        out.append(
            {
                "kind": kind,
                "jurisdiction": juris,
                "title": title,
                "status": str(it.get("status") or "")[:40],
                "event_date": date,
                "subjects": subjects,
                "excerpt": excerpt,
            }
        )
        if len(out) >= max_items:
            break
    return out


def regulatory_calendar(
    items: list[dict[str, Any]], *, now: str = "", horizon_days: int = 90
) -> dict[str, Any]:
    """The reading: dated items ahead (soonest first), recent enforcement /
    lawsuits, operator responses per jurisdiction."""
    now_dt = datetime.fromisoformat(now) if now else datetime.now(UTC)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=UTC)
    today = now_dt.isoformat()[:10]
    horizon = (now_dt + timedelta(days=horizon_days)).isoformat()[:10]
    recent = (now_dt - timedelta(days=30)).isoformat()
    ahead = sorted(
        [i for i in items if i.get("event_date") and today <= i["event_date"] <= horizon],
        key=lambda i: i["event_date"],
    )
    past_dated = sorted(
        [i for i in items if i.get("event_date") and i["event_date"] < today],
        key=lambda i: i["event_date"],
        reverse=True,
    )[:6]
    actions = sorted(
        [i for i in items if i.get("kind") in ("enforcement", "lawsuit") and str(i.get("observed_at") or "") >= recent],
        key=lambda i: str(i.get("observed_at") or ""),
        reverse=True,
    )
    responses = [i for i in items if i.get("kind") == "operator_response"]
    by_juris: dict[str, int] = {}
    for i in items:
        by_juris[i.get("jurisdiction", "")] = by_juris.get(i.get("jurisdiction", ""), 0) + 1
    return {
        "today": today,
        "horizon_days": horizon_days,
        "ahead": ahead,
        "recent_actions": actions,
        "past_dated": past_dated,
        "operator_responses": responses,
        "by_jurisdiction": dict(sorted(by_juris.items(), key=lambda kv: -kv[1])),
        "total": len(items),
        "label": "Regulatory items as published by their sources; not legal advice.",
    }
