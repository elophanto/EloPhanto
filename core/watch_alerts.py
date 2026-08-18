"""Alerts — what wakes an executive mid-week (docs/88 §B).

Three kinds, all read from registers that already exist: a market event on
a brand's own pages (closure, exit, acquisition, rebrand, launch, regulatory
notice) observed in the last 48 hours; a regulatory item with an effective
date inside 30 days or newly observed enforcement (once the regulatory
register exists); a player-sentiment spike — a brand × theme with enough
mentions, mostly negative, and clearly up on the last snapshot. Each alert
is stored once (dedupe key) so a re-check never re-notifies, and pushed as
a gateway NOTIFICATION of type "watch" when asked.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from core.watch_deck import market_events

VOICE_SPIKE_MIN_N = 10
VOICE_SPIKE_NEG = 0.6
VOICE_SPIKE_RISE = 0.2


def _key(*parts: str) -> str:
    base = "|".join(re.sub(r"[^a-z0-9]+", " ", (p or "").lower()).strip()[:80] for p in parts)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]


def alerts_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Market events → alert candidates."""
    out = []
    for ev in events:
        out.append(
            {
                "kind": "market_event",
                "subject_name": ev.get("brand", ""),
                "title": f"{ev.get('brand', '')}: market event",
                "detail": str(ev.get("claim") or ""),
                "source_url": str(ev.get("url") or ""),
                "dedupe_key": _key("event", str(ev.get("brand")), str(ev.get("claim"))[:44]),
            }
        )
    return out


def alerts_from_voice(voice: dict[str, Any], voice_diff: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Player-sentiment spikes → alert candidates. Needs n ≥ 10 on the
    theme, ≥ 60% negative, and a rise ≥ 0.2 in negative share vs the last
    snapshot (or a first reading that is already that negative)."""
    out = []
    moves = {(c["brand"], c["theme"]): c for c in (voice_diff or {}).get("changed", [])}
    for b in voice.get("brands", []):
        if b.get("too_few"):
            continue
        for theme, cell in (b.get("themes") or {}).items():
            n, neg = int(cell.get("n", 0)), float(cell.get("neg_share", 0.0))
            if n < VOICE_SPIKE_MIN_N or neg < VOICE_SPIKE_NEG:
                continue
            mv = moves.get((b["name"], theme))
            rose = mv is not None and (float(mv["neg_to"]) - float(mv["neg_from"])) >= VOICE_SPIKE_RISE
            first = voice_diff is not None and voice_diff.get("baseline")
            if not (rose or first):
                continue
            week = str(voice.get("since") or "")[:10]
            out.append(
                {
                    "kind": "voice_spike",
                    "subject_name": b["name"],
                    "title": f"{b['name']}: players on {theme.replace('_', ' ')}",
                    "detail": (
                        f"{int(round(neg * 100))}% negative of {n} mentions in {voice.get('window_days', 7)} days"
                        + (
                            f" (was {int(round(float(mv['neg_from']) * 100))}%)"
                            if mv
                            else " (first reading)"
                        )
                        + " — sentiment, not fact"
                    ),
                    "source_url": "",
                    "dedupe_key": _key("voice", b["name"], theme, week),
                }
            )
    return out


def alerts_from_regulatory(items: list[dict[str, Any]], *, horizon_days: int = 30, now: str = "") -> list[dict[str, Any]]:
    """Regulatory items → alerts: effective dates inside the horizon, and
    enforcement / lawsuits observed in the last 48h."""
    now_dt = datetime.fromisoformat(now) if now else datetime.now(UTC)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=UTC)
    horizon = (now_dt + timedelta(days=horizon_days)).isoformat()[:10]
    recent = (now_dt - timedelta(hours=48)).isoformat()
    out = []
    for it in items:
        kind = str(it.get("kind") or "")
        date = str(it.get("event_date") or "")[:10]
        observed = str(it.get("observed_at") or "")
        if kind in ("effective_date", "bill") and date and now_dt.isoformat()[:10] <= date <= horizon:
            out.append(
                {
                    "kind": "regulatory",
                    "subject_name": str(it.get("jurisdiction") or ""),
                    "title": f"{it.get('jurisdiction', '')}: {kind.replace('_', ' ')} on {date}",
                    "detail": str(it.get("title") or ""),
                    "source_url": str(it.get("source_url") or ""),
                    "dedupe_key": _key("reg", str(it.get("jurisdiction")), str(it.get("title"))[:44], date),
                }
            )
        elif kind in ("enforcement", "lawsuit") and observed >= recent:
            out.append(
                {
                    "kind": "regulatory",
                    "subject_name": str(it.get("jurisdiction") or ""),
                    "title": f"{it.get('jurisdiction', '')}: {kind}",
                    "detail": str(it.get("title") or ""),
                    "source_url": str(it.get("source_url") or ""),
                    "dedupe_key": _key("reg", str(it.get("jurisdiction")), str(it.get("title"))[:44]),
                }
            )
    return out


async def detect_alerts(wm: Any, company_id: str, *, hours: int = 48) -> list[dict[str, Any]]:
    """Read the registers and return alert candidates (not yet stored)."""
    since = (datetime.now(UTC) - timedelta(hours=int(hours))).isoformat()
    evidence = await wm.evidence_with_names(company_id)
    recent = [e for e in evidence if str(e.get("observed_at") or "") >= since]
    cands = alerts_from_events(market_events(recent, limit=10))
    try:
        voice = await wm.voice_summary(company_id, window_days=7)
        if voice.get("mentions"):
            vdiff = await wm.diff_voice_since_snapshot(company_id)
            cands += alerts_from_voice(voice, vdiff)
    except Exception:
        pass
    if hasattr(wm, "list_regulatory"):
        try:
            items = await wm.list_regulatory(company_id, limit=500)
            cands += alerts_from_regulatory([r if isinstance(r, dict) else r.__dict__ for r in items])
        except Exception:
            pass
    return cands


def format_alert(a: dict[str, Any]) -> str:
    line = f"• {a['title']} — {a['detail']}"
    if a.get("source_url"):
        line += f"\n  {a['source_url']}"
    return line
