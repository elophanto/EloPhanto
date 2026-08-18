"""Demand calendar — the next eight weeks of dates that move play
(docs/88 §E), and message categories read from promotions claims.

Deterministic. Holidays, paydays, benefit dates and tax season are
computed; sports and other market events are SUPPLIED by the operator (a
list of {date, label}) — never guessed. Message categories are a fixed
regex vocabulary over promotions claims so week-to-week mixes compare.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

MESSAGE_CATEGORIES: tuple[str, ...] = (
    "welcome_offer",
    "purchase_bonus",
    "free_coins",
    "daily_login",
    "tournament_race",
    "referral",
    "vip_loyalty",
    "holiday_seasonal",
    "new_game",
    "other",
)

_CAT_RES: list[tuple[str, re.Pattern[str]]] = [
    ("welcome_offer", re.compile(r"welcome|sign[- ]?up|new (player|user|customer)|first[- ]time|registration", re.I)),
    ("purchase_bonus", re.compile(r"\d+\s*%\s*(extra|more|bonus)|first purchase|on (your )?(next )?purchase|coin package|bundle", re.I)),
    ("free_coins", re.compile(r"free (gold |sweeps? )?coins?|no purchase|free (gc|sc)\b|free play", re.I)),
    ("daily_login", re.compile(r"daily|every day|log[- ]?in|wheel|streak", re.I)),
    ("tournament_race", re.compile(r"tournament|race|leaderboard|challenge|quest|jackpot drop", re.I)),
    ("referral", re.compile(r"refer|referral|invite (a )?friend", re.I)),
    ("vip_loyalty", re.compile(r"\bvip\b|loyalty|tier|status level|reward(s)? cent(er|re)|points", re.I)),
    ("holiday_seasonal", re.compile(r"halloween|thanksgiving|christmas|holiday|new year|valentine|easter|4th of july|labor day|memorial day|summer|black friday|cyber monday|st\.? patrick", re.I)),
    ("new_game", re.compile(r"new (game|slot|release|title)s?|now live|just launched|exclusive game", re.I)),
]


def message_category(text: str) -> str:
    """The first vocabulary category a promotions claim matches, in a
    fixed priority order; 'other' when none."""
    for cat, rx in _CAT_RES:
        if rx.search(text or ""):
            return cat
    return "other"


def message_categories(
    evidence: list[dict[str, Any]], *, since: str = "", subjects: list[str] | None = None
) -> dict[str, Any]:
    """Per brand: category counts over promotions/loyalty claims observed
    since ``since`` (all when empty). Evidence rows are export dicts."""
    per: dict[str, dict[str, int]] = {}
    for e in evidence:
        dim = str(e.get("dimension") or "").lower()
        if not ("promo" in dim or "loyalty" in dim or "offer" in dim or "bonus" in dim):
            continue
        if since and str(e.get("observed_at") or "") < since:
            continue
        brand = str(e.get("subject") or "")
        if subjects and brand not in subjects:
            continue
        cat = message_category(f"{e.get('claim') or ''} {e.get('value_text') or ''}")
        per.setdefault(brand, {})[cat] = per.setdefault(brand, {}).get(cat, 0) + 1
    field: dict[str, int] = {}
    for cats in per.values():
        for c, n in cats.items():
            field[c] = field.get(c, 0) + n
    return {
        "since": since,
        "brands": {b: dict(sorted(c.items(), key=lambda kv: -kv[1])) for b, c in per.items()},
        "field": dict(sorted(field.items(), key=lambda kv: -kv[1])),
        "vocabulary": list(MESSAGE_CATEGORIES),
    }


# ── Demand calendar ────────────────────────────────────────────────────


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th weekday (0=Mon) of a month; n=-1 for the last."""
    if n > 0:
        d = date(year, month, 1)
        off = (weekday - d.weekday()) % 7
        return d + timedelta(days=off + 7 * (n - 1))
    d = date(year + (month // 12), month % 12 + 1, 1) - timedelta(days=1)
    off = (d.weekday() - weekday) % 7
    return d - timedelta(days=off)


def us_holidays(year: int) -> list[tuple[date, str]]:
    return [
        (date(year, 1, 1), "New Year's Day"),
        (_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day"),
        (date(year, 2, 14), "Valentine's Day"),
        (_nth_weekday(year, 2, 0, 3), "Presidents' Day"),
        (date(year, 3, 17), "St. Patrick's Day"),
        (_nth_weekday(year, 5, 0, -1), "Memorial Day"),
        (date(year, 7, 4), "Independence Day"),
        (_nth_weekday(year, 9, 0, 1), "Labor Day"),
        (date(year, 10, 31), "Halloween"),
        (date(year, 11, 11), "Veterans Day"),
        (_nth_weekday(year, 11, 3, 4), "Thanksgiving"),
        (_nth_weekday(year, 11, 3, 4) + timedelta(days=1), "Black Friday"),
        (_nth_weekday(year, 11, 3, 4) + timedelta(days=4), "Cyber Monday"),
        (date(year, 12, 24), "Christmas Eve"),
        (date(year, 12, 25), "Christmas Day"),
        (date(year, 12, 31), "New Year's Eve"),
    ]


def _last_business_day(year: int, month: int) -> date:
    d = date(year + (month // 12), month % 12 + 1, 1) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _prev_business_day(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def payday_dates(year: int, month: int) -> list[tuple[date, str]]:
    """Common US pay rhythms: 1st and 15th (moved back off weekends), last
    business day."""
    out = [
        (_prev_business_day(date(year, month, 1)), "Payday (1st)"),
        (_prev_business_day(date(year, month, 15)), "Payday (15th)"),
        (_last_business_day(year, month), "Payday (month end)"),
    ]
    return out


def benefit_dates(year: int, month: int) -> list[tuple[date, str]]:
    """SSI on the 1st (moved back off weekends/holidays), Social Security
    on the 2nd/3rd/4th Wednesdays (by birth date), SSA pre-1997 on the
    3rd — published SSA rhythm."""
    out = [(_prev_business_day(date(year, month, 1)), "SSI payment")]
    out.append((_prev_business_day(date(year, month, 3)), "Social Security (pre-1997 / SSI+SS)"))
    for n, lab in ((2, "Social Security (birth 1st–10th)"), (3, "Social Security (birth 11th–20th)"), (4, "Social Security (birth 21st–31st)")):
        out.append((_nth_weekday(year, month, 2, n), lab))
    return out


def tax_dates(year: int) -> list[tuple[date, str]]:
    return [
        (date(year, 1, 27), "IRS filing season opens (approx.)"),
        (date(year, 2, 15), "Peak refund weeks begin (approx.)"),
        (date(year, 4, 15), "Tax Day"),
    ]


def demand_calendar(
    *,
    weeks: int = 8,
    now: str = "",
    events: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """The next ``weeks`` weeks: holidays, paydays, benefit dates, tax
    dates (computed) plus supplied events (sports etc.), grouped by week."""
    now_dt = datetime.fromisoformat(now) if now else datetime.now(UTC)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=UTC)
    start = now_dt.date()
    end = start + timedelta(days=7 * int(weeks))
    items: list[dict[str, str]] = []
    years = {start.year, end.year}
    months = set()
    d = start.replace(day=1)
    while d <= end:
        months.add((d.year, d.month))
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    for y in years:
        for dt, lab in us_holidays(y) + tax_dates(y):
            if start <= dt <= end:
                items.append({"date": dt.isoformat(), "label": lab, "kind": "holiday" if "Tax" not in lab and "IRS" not in lab and "refund" not in lab else "tax"})
    for y, m in months:
        for dt, lab in payday_dates(y, m):
            if start <= dt <= end:
                items.append({"date": dt.isoformat(), "label": lab, "kind": "payday"})
        for dt, lab in benefit_dates(y, m):
            if start <= dt <= end:
                items.append({"date": dt.isoformat(), "label": lab, "kind": "benefit"})
    for ev in events or []:
        dt = str(ev.get("date") or "")[:10]
        if dt and start.isoformat() <= dt <= end.isoformat():
            items.append({"date": dt, "label": str(ev.get("label") or ""), "kind": str(ev.get("kind") or "event")})
    items.sort(key=lambda i: (i["date"], i["kind"], i["label"]))
    weeks_out: list[dict[str, Any]] = []
    for w in range(int(weeks)):
        ws = start + timedelta(days=7 * w)
        we = ws + timedelta(days=6)
        weeks_out.append(
            {
                "week_of": ws.isoformat(),
                "through": we.isoformat(),
                "items": [i for i in items if ws.isoformat() <= i["date"] <= we.isoformat()],
            }
        )
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "weeks": weeks_out,
        "items": items,
        "note": (
            "Holidays, paydays, SSA/SSI and tax dates are computed from the published rhythms; "
            "sports and other events are supplied by the operator, never guessed."
        ),
    }
