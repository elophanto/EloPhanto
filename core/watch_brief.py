"""The weekly executive brief — one page, every Friday (docs/88 §A).

A reading of the registers over the last week: which fields changed per
brand (newest claim inside the window vs the newest before it), which
offers changed, market events, score movement against the last snapshot,
voice movement, and — when the executive asked one — the week's request
and its answer. Nothing here is a new fact; every line points back to a
row in the evidence, voice or snapshot registers. Rendered as markdown
(channels, e-mail) and a one-slide deck in the pack's style.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from core.watch_deck import _clean, market_events
from core.watch_offers import offer_facts

_WS_RE = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip().lower())


def field_changes(
    evidence: list[dict[str, Any]], *, since: str, max_per_brand: int = 6
) -> list[dict[str, Any]]:
    """Per brand: (dimension, sub-criterion) whose newest claim in the window
    differs from the newest claim before it. Evidence rows are the export
    dicts (subject, dimension, subcriterion, claim, value_text, observed_at,
    source_url), newest first. A first-ever observation of a pair is
    reported as ``before=None`` — new coverage, not a change."""
    latest_in: dict[tuple[str, str, str], dict[str, Any]] = {}
    latest_before: dict[tuple[str, str, str], dict[str, Any]] = {}
    for e in evidence:  # newest first
        key = (
            str(e.get("subject")),
            str(e.get("dimension")),
            str(e.get("subcriterion") or ""),
        )
        when = str(e.get("observed_at") or "")
        if when >= since:
            latest_in.setdefault(key, e)
        else:
            latest_before.setdefault(key, e)
    out: dict[str, list[dict[str, Any]]] = {}
    for key, cur in latest_in.items():
        prev = latest_before.get(key)
        cur_sig = _norm(str(cur.get("value_text") or "")) or _norm(
            str(cur.get("claim") or "")
        )
        prev_sig = (
            (
                _norm(str(prev.get("value_text") or ""))
                or _norm(str(prev.get("claim") or ""))
            )
            if prev
            else None
        )
        if prev is not None and cur_sig == prev_sig:
            continue
        brand = key[0]
        out.setdefault(brand, []).append(
            {
                "brand": brand,
                "dimension": key[1],
                "subcriterion": key[2],
                "before": (
                    (str(prev.get("value_text") or prev.get("claim") or "")[:160])
                    if prev
                    else None
                ),
                "after": str(cur.get("value_text") or cur.get("claim") or "")[:160],
                "url": str(cur.get("source_url") or ""),
                "observed_at": str(cur.get("observed_at") or "")[:10],
                "new_coverage": prev is None,
            }
        )
    rows: list[dict[str, Any]] = []
    for items in out.values():
        # real changes before new coverage; then by dimension for stable reading
        items.sort(key=lambda c: (c["new_coverage"], c["dimension"], c["subcriterion"]))
        rows.extend(items[:max_per_brand])
    return rows


def offer_changes(
    card: dict[str, Any], evidence: list[dict[str, Any]], *, since: str
) -> list[dict[str, Any]]:
    """Welcome / ongoing offer text per brand: as of ``since`` vs now."""
    before_rows = [e for e in evidence if str(e.get("observed_at") or "") < since]
    now = {o["brand"]: o for o in offer_facts(card, evidence, {})}
    then = {o["brand"]: o for o in offer_facts(card, before_rows, {})}
    out: list[dict[str, Any]] = []
    for brand, cur in now.items():
        prev = then.get(brand, {})
        for field in ("welcome", "ongoing"):
            a, b = _norm(str(prev.get(field) or "")), _norm(str(cur.get(field) or ""))
            if b and a != b:
                out.append(
                    {
                        "brand": brand,
                        "is_self": bool(cur.get("is_self")),
                        "field": field,
                        "before": str(prev.get(field) or "") or None,
                        "after": str(cur.get(field) or ""),
                        "url": str(cur.get("url") or ""),
                    }
                )
    out.sort(key=lambda o: (not o["is_self"], o["brand"], o["field"]))
    return out


async def build_weekly_brief(
    wm: Any,
    company_id: str,
    *,
    days: int = 7,
    request: str = "",
    answer: str = "",
    now: str = "",
) -> dict[str, Any]:
    """Assemble the brief's facts from the registers. Pure reading."""
    now_dt = datetime.fromisoformat(now) if now else datetime.now(UTC)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=UTC)
    since = (now_dt - timedelta(days=int(days))).isoformat()
    card = await wm.scorecard(company_id)
    evidence = await wm.evidence_with_names(company_id)
    week_rows = [e for e in evidence if str(e.get("observed_at") or "") >= since]
    changes = field_changes(evidence, since=since)
    offers = offer_changes(card, evidence, since=since)
    events = market_events(week_rows, limit=6)
    try:
        score_diff = await wm.diff_since_snapshot(company_id)
    except Exception:
        score_diff = None
    try:
        voice = await wm.voice_summary(company_id, window_days=days)
        voice_diff = (
            await wm.diff_voice_since_snapshot(company_id)
            if voice.get("mentions")
            else None
        )
    except Exception:
        voice, voice_diff = None, None
    try:
        comms = await wm.comms_summary(company_id, window_days=days)
    except Exception:
        comms = None
    per_brand: dict[str, int] = {}
    for e in week_rows:
        per_brand[str(e.get("subject"))] = per_brand.get(str(e.get("subject")), 0) + 1
    rows = card.get("rows", [])
    return {
        "company_id": company_id,
        "period": {
            "since": since[:10],
            "until": now_dt.isoformat()[:10],
            "days": int(days),
        },
        "brands_tracked": len(rows),
        "brands_touched": len(per_brand),
        "new_facts": len(week_rows),
        "facts_per_brand": per_brand,
        "field_changes": changes,
        "offer_changes": offers,
        "market_events": events,
        "score_moves": (
            [
                c
                for c in (score_diff or {}).get("changed", [])
                if c.get("kind") in ("score", "rank", "newly_scored", "score_withdrawn")
            ][:6]
            if score_diff
            else []
        ),
        "voice": (
            {
                "mentions": (voice or {}).get("mentions", 0),
                "moves": (
                    (voice_diff or {}).get("changed", [])[:4] if voice_diff else []
                ),
                "top_complaints": [
                    {
                        "brand": b["name"],
                        "theme": b["top_complaint"],
                        "n": b["n"],
                        "neg_share": b["neg_share"],
                    }
                    for b in (voice or {}).get("brands", [])
                    if not b.get("too_few") and b.get("top_complaint")
                ][:4],
            }
            if voice
            else None
        ),
        "comms": (
            {
                "emails": comms.get("emails", 0),
                "brands": [
                    {
                        "brand": b["name"],
                        "is_self": b["is_self"],
                        "n": b["n"],
                        "top_category": (
                            max(b["categories"].items(), key=lambda kv: kv[1])[0]
                            if b.get("categories")
                            else None
                        ),
                        "latest_offer": (
                            (b.get("latest_offers") or [{}])[0].get("offer", "")
                            if b.get("latest_offers")
                            else ""
                        ),
                    }
                    for b in comms.get("brands", [])
                    if b.get("inbox") and b.get("n")
                ][:6],
            }
            if comms and comms.get("emails")
            else None
        ),
        "request": {"question": request, "answer": answer} if request else None,
        "us": [r["name"] for r in rows if r.get("is_self")],
    }


# ── Reading (computed "so what" fallback) ────────────────────────────


def brief_facts(brief: dict[str, Any]) -> dict[str, list[str]]:
    """Computed lines for the three columns when no model writes them."""
    changed: list[str] = []
    market: list[str] = []
    decisions: list[str] = []
    real = [c for c in brief["field_changes"] if not c["new_coverage"]]
    by_brand: dict[str, int] = {}
    for c in real:
        by_brand[c["brand"]] = by_brand.get(c["brand"], 0) + 1
    if real:
        top = sorted(by_brand.items(), key=lambda kv: -kv[1])[:3]
        changed.append(
            f"{len(real)} field change{'s' if len(real) != 1 else ''} across {len(by_brand)} brands; most at "
            + ", ".join(f"{b} ({n})" for b, n in top)
            + "."
        )
    else:
        changed.append(
            f"No field changed on the pages read this week ({brief['new_facts']} facts re-observed "
            f"across {brief['brands_touched']} brands)."
        )
    for o in brief["offer_changes"][:3]:
        changed.append(
            f"{o['brand']} {o['field']} offer now: “{_clean(o['after'], 90)}”"
            + (f" (was “{_clean(o['before'], 60)}”)" if o["before"] else " (new)")
        )
    for ev in brief["market_events"][:3]:
        market.append(f"{ev['brand']} – {_clean(ev['claim'], 110)}")
    v = brief.get("voice")
    if v and v.get("mentions"):
        for m in v["moves"][:2]:
            arrow = "▲" if m["direction"] == "rising" else "▼"
            market.append(
                f"{arrow} Players on {m['brand']}: {m['theme'].replace('_', ' ')} "
                f"{int(round(m['neg_from'] * 100))}% → {int(round(m['neg_to'] * 100))}% negative (n {m['n_to']})"
            )
        if not v["moves"] and v["top_complaints"]:
            tc = v["top_complaints"][0]
            market.append(
                f"Loudest complaint this week: {tc['brand']} – {tc['theme'].replace('_', ' ')} "
                f"({int(round(tc['neg_share'] * 100))}% negative of {tc['n']} mentions)"
            )
    c = brief.get("comms")
    if c and c.get("emails"):
        top = sorted(c["brands"], key=lambda b: -b["n"])[:2]
        market.append(
            f"Player e-mail this week: {c['emails']} received; "
            + ", ".join(
                f"{b['brand']} {b['n']}"
                + (f" ({b['top_category'].replace('_', ' ')})" if b.get("top_category") else "")
                for b in top
            )
            + (
                f". Latest offer — {top[0]['brand']}: {_clean(top[0]['latest_offer'], 80)}"
                if top and top[0].get("latest_offer")
                else ""
            )
        )
    if not market:
        market.append("No market event or player-sentiment move this week.")
    for ev in brief["market_events"][:1]:
        decisions.append(
            f"Decide the response to {ev['brand']}'s move before next Friday."
        )
    us = set(brief.get("us") or [])
    ours = [o for o in brief["offer_changes"] if o["brand"] in us]
    theirs = [o for o in brief["offer_changes"] if o["brand"] not in us]
    if theirs and not ours:
        decisions.append(
            f"Peers changed offers ({', '.join(sorted({o['brand'] for o in theirs})[:3])}); ours did not — confirm that is intended."
        )
    if brief.get("request"):
        decisions.append(
            f"Requested: {_clean(brief['request']['question'], 90)} — answer below."
        )
    if not decisions:
        decisions.append("Hold course; nothing this week needs a decision.")
    return {"changed": changed[:4], "market": market[:4], "decisions": decisions[:3]}


# ── Renderers ─────────────────────────────────────────────────────────


def render_brief_markdown(
    brief: dict[str, Any], narrative: dict[str, Any] | None = None
) -> str:
    n = narrative or {}
    facts = brief_facts(brief)
    p = brief["period"]
    lines = [
        f"# Weekly competitive brief — {p['since']} → {p['until']}",
        "",
        f"_{brief['new_facts']} facts observed across {brief['brands_touched']} of {brief['brands_tracked']} brands "
        f"this week; every line below points to a source._",
        "",
    ]
    if n.get("headline"):
        lines += [f"**{n['headline']}**", ""]
    lines += ["## What changed", ""]
    for line in n.get("changed") or facts["changed"]:
        lines.append(f"- {line}")
    real = [c for c in brief["field_changes"] if not c["new_coverage"]][:10]
    if real:
        lines += [
            "",
            "| Brand | Dimension · field | Before | After |",
            "|---|---|---|---|",
        ]
        for c in real:
            lines.append(
                f"| {c['brand']} | {c['dimension']} · {c['subcriterion'] or '—'} | "
                f"{_clean(c['before'] or '—', 70)} | {_clean(c['after'], 70)} |"
            )
    lines += ["", "## Market and players", ""]
    for line in n.get("market") or facts["market"]:
        lines.append(f"- {line}")
    lines += ["", "## Decisions", ""]
    for line in n.get("decisions") or facts["decisions"]:
        lines.append(f"- {line}")
    if brief.get("request"):
        lines += [
            "",
            "## This week's request",
            "",
            f"**{brief['request']['question']}**",
            "",
            brief["request"]["answer"] or "_(answer pending)_",
        ]
    lines += [
        "",
        f"_Sources: evidence register (URL, quote, date, exit IP on every row); "
        f"voice of customer {brief['voice']['mentions'] if brief.get('voice') else 0} mentions; "
        f"snapshots for movement. Field changes compare the newest claim this week with the newest before it._",
    ]
    return "\n".join(lines)


def render_brief_slide(
    brief: dict[str, Any],
    narrative: dict[str, Any] | None,
    *,
    path: str | Path,
    title: str = "Weekly Competitive Brief",
) -> str:
    """One slide, the deck's style: three columns and a footer of counts."""
    from pptx import Presentation
    from pptx.util import Inches

    from core.watch_deck import (
        _ACCENT,
        _BODY,
        _MUTED,
        _PEER,
        _blank,
        _bullets,
        _eyebrow,
        _footer,
        _rule,
        _text,
    )

    n = narrative or {}
    facts = brief_facts(brief)
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    s = _blank(prs)
    p = brief["period"]
    _eyebrow(s, f"Weekly competitive brief · {p['since']} → {p['until']}", y=0.42)
    headline = _clean(
        n.get("headline")
        or (
            f"{len([c for c in brief['field_changes'] if not c['new_coverage']])} field changes, "
            f"{len(brief['offer_changes'])} offer changes, {len(brief['market_events'])} market events this week"
        ),
        120,
    )
    _text(s, 0.7, 0.72, 11.9, 0.9, headline, size=21, bold=True, line=1.08)
    _rule(s, 1.62)
    cols = [
        ("What changed", _PEER, n.get("changed") or facts["changed"], 0.7),
        ("Market & players", _PEER, n.get("market") or facts["market"], 4.95),
        ("Decisions", _ACCENT, n.get("decisions") or facts["decisions"], 9.2),
    ]
    for label, color, items, x in cols:
        w = 3.9 if x < 9 else 3.4
        _eyebrow(s, label, y=1.85, x=x, color=color)
        _bullets(
            s,
            x,
            2.2,
            w,
            3.4,
            [str(i) for i in items],
            size=10.5,
            color=_BODY,
            gap_pt=6,
            cap=170,
            accent_bullet=(label == "Decisions"),
            max_items=4,
        )
    if brief.get("request"):
        _eyebrow(s, "This week's request", y=5.75, x=0.7, color=_ACCENT)
        _text(
            s,
            0.7,
            6.05,
            11.9,
            0.55,
            _clean(
                f"{brief['request']['question']} — {brief['request']['answer'] or 'answer pending'}",
                260,
            ),
            size=10,
            color=_BODY,
        )
    v = brief.get("voice") or {}
    _text(
        s,
        0.7,
        6.65,
        11.9,
        0.3,
        f"{brief['new_facts']} facts · {brief['brands_touched']}/{brief['brands_tracked']} brands read · "
        f"{len(brief['field_changes'])} field observations ({len([c for c in brief['field_changes'] if not c['new_coverage']])} changes) · "
        f"{v.get('mentions', 0)} player mentions · every line traceable to a source",
        size=8,
        italic=True,
        color=_MUTED,
    )
    _footer(s, _clean(title, 70), 1)
    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    return str(out)


BRIEF_NARRATIVE_SYSTEM = """You write the one-page weekly competitive brief for a steering committee
from a JSON of facts read from an evidence register (field changes with
before/after, offer changes, market events, score and player-sentiment
movement, an optional executive request with its answer). Rules:
- Say what changed and what it means for US (the brands marked ours);
  never invent a fact not in the JSON; keep numbers as given.
- headline: one sentence, max 18 words, the week's most material point.
- changed: 2-4 lines (max 22 words each) on fields/offers that moved.
- market: 2-4 lines on market events and what players say (sentiment is
  opinion — say "players complain", never state it as product fact).
- decisions: 1-3 lines, each a decision the room can take or refuse.
Return STRICT JSON: {"headline":str,"changed":[str],"market":[str],"decisions":[str]}"""


async def narrate_brief(router: Any, brief: dict[str, Any]) -> dict[str, Any]:
    """Model-written lines when a router exists; {} otherwise. The renderer
    falls back to computed lines per column."""
    import json as _json

    if router is None:
        return {}
    facts = {
        k: brief.get(k)
        for k in (
            "period",
            "us",
            "field_changes",
            "offer_changes",
            "market_events",
            "score_moves",
            "voice",
            "comms",
            "request",
        )
    }
    try:
        resp = await router.complete(
            messages=[
                {"role": "system", "content": BRIEF_NARRATIVE_SYSTEM},
                {"role": "user", "content": _json.dumps(facts)[:24000]},
            ],
            task_type="analysis",
            temperature=0.2,
            max_tokens=900,
        )
        text = (resp.content or "").strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            text = text[4:] if text.startswith("json") else text
        data = _json.loads(text)
        if not isinstance(data, dict):
            return {}
        out: dict[str, Any] = {}
        if str(data.get("headline") or "").strip():
            out["headline"] = str(data["headline"]).strip()
        for k in ("changed", "market", "decisions"):
            items = [str(x).strip() for x in (data.get(k) or []) if str(x).strip()]
            if items:
                out[k] = items[:4]
        return out
    except Exception:
        return {}
