"""Player comms — what brands SEND players (docs/88 §C).

Each tracked brand gets an inbox of the agent's own (AgentMail), signed up
once in the real browser with the playbook; from then on every marketing
e-mail the brand sends lands there and is read into ``watch_comms``: a
fixed category, the offer it carries, a verified excerpt, the send day and
hour. That is the week-to-week view of acquisition and retention messaging
the pack never had — first-party, dated, and diffable. Same disciplines as
voice: the model classifies, quotes must be verbatim, nothing here touches
a score.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

COMMS_CATEGORIES: tuple[str, ...] = (
    "welcome",
    "promo_offer",
    "daily_bonus",
    "reactivation",
    "vip_loyalty",
    "tournament_event",
    "product_news",
    "transactional",
    "other",
)

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", (s or "").lower()).strip()


def excerpt_is_verbatim(excerpt: str, text: str) -> bool:
    e, t = _norm(excerpt), _norm(text)
    return bool(e) and len(e) >= 10 and e in t


def inbox_username(brand: str) -> str:
    """A per-brand inbox name that does not advertise what it is:
    ``<slug>-<4 hex>``."""
    slug = re.sub(r"[^a-z0-9]+", "-", brand.lower()).strip("-")[:20] or "brand"
    return f"{slug}-{secrets.token_hex(2)}"


def signup_password() -> str:
    return secrets.token_urlsafe(12)


def message_text(msg: Any) -> str:
    """Best text of a fetched message: extracted_text > text > preview."""
    for attr in ("extracted_text", "text", "preview"):
        v = getattr(msg, attr, None)
        if v:
            return str(v)
    return ""


def message_time(msg: Any) -> str:
    for attr in ("timestamp", "created_at", "received_at"):
        v = getattr(msg, attr, None)
        if v:
            if isinstance(v, datetime):
                return (v if v.tzinfo else v.replace(tzinfo=UTC)).isoformat()
            return str(v)
    return ""


COMMS_READ_SYSTEM = """You read marketing e-mails a sweepstakes / social casino brand sent to a
player and classify each. You are given the brand, the fixed category
vocabulary and a list of e-mails (id, subject, text). Rules:
- category: exactly one from the vocabulary. 'welcome' = onboarding series;
  'promo_offer' = a purchase offer / bonus coins; 'daily_bonus' = free daily
  rewards / login; 'reactivation' = we-miss-you / come back; 'vip_loyalty' =
  tier, VIP, loyalty points; 'tournament_event' = races, leaderboards,
  events; 'product_news' = new games / features; 'transactional' = receipts,
  verification, account notices; else 'other'.
- offer: the concrete offer in ≤ 120 characters ("200% extra GC + 20 SC on
  first purchase, 24h"), or "" when there is none.
- excerpt: a SHORT VERBATIM span (≤ 160 chars) copied exactly from the
  e-mail text that carries the offer or the message. Do not paraphrase.
- Never infer facts about the product; you are classifying messages.
Return STRICT JSON: {"items":[{"id":str,"category":str,"offer":str,"excerpt":str}]}"""


async def read_comms(
    router: Any, *, brand: str, messages: list[dict[str, Any]], batch: int = 12
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Classify e-mails. ``messages`` are dicts {id, subject, text, ...}.
    Returns validated items and drop counts. [] without a router."""
    dropped = {"no_router": 0, "model_skip": 0, "bad_category": 0, "unverified_excerpt": 0, "error": 0}
    if router is None:
        dropped["no_router"] = len(messages)
        return [], dropped
    by_id = {m["id"]: m for m in messages}
    items: list[dict[str, Any]] = []
    for i in range(0, len(messages), max(1, batch)):
        chunk = messages[i : i + batch]
        user = json.dumps(
            {
                "brand": brand,
                "categories": list(COMMS_CATEGORIES),
                "emails": [
                    {"id": m["id"], "subject": m.get("subject", ""), "text": str(m.get("text", ""))[:2500]}
                    for m in chunk
                ],
            }
        )
        try:
            resp = await router.complete(
                messages=[
                    {"role": "system", "content": COMMS_READ_SYSTEM},
                    {"role": "user", "content": user},
                ],
                task_type="analysis",
                temperature=0.0,
                max_tokens=2500,
            )
            text = (resp.content or "").strip()
            if text.startswith("```"):
                parts = text.split("```")
                text = parts[1] if len(parts) > 1 else text
                text = text[4:] if text.startswith("json") else text
            data = json.loads(text)
            raw = data.get("items", []) if isinstance(data, dict) else []
        except Exception as e:
            logger.warning("watch_comms: reading failed: %s", e)
            dropped["error"] += len(chunk)
            continue
        got: set[str] = set()
        for it in raw:
            if not isinstance(it, dict):
                continue
            m = by_id.get(str(it.get("id") or ""))
            if m is None:
                continue
            got.add(m["id"])
            cat = str(it.get("category") or "").strip()
            if cat not in COMMS_CATEGORIES:
                dropped["bad_category"] += 1
                continue
            excerpt = " ".join(str(it.get("excerpt") or "").split())[:200]
            hay = f"{m.get('subject', '')} {m.get('text', '')}"
            if excerpt and not excerpt_is_verbatim(excerpt, hay):
                dropped["unverified_excerpt"] += 1
                excerpt = ""  # keep the row (category is still a reading), drop the quote
            items.append(
                {
                    "message": m,
                    "category": cat,
                    "offer": " ".join(str(it.get("offer") or "").split())[:160],
                    "excerpt": excerpt,
                }
            )
        dropped["model_skip"] += len([m for m in chunk if m["id"] not in got])
    return items, dropped


def summarize_comms(
    rows: list[Any], subjects: list[Any], *, window_days: int = 30, now: str = ""
) -> dict[str, Any]:
    """Per brand: e-mails in the window, per-week cadence, category counts,
    send-hour mode, the latest offer lines. Pure computation."""
    from datetime import timedelta

    now_dt = datetime.fromisoformat(now) if now else datetime.now(UTC)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=UTC)
    since = (now_dt - timedelta(days=int(window_days))).isoformat()
    per: list[dict[str, Any]] = []
    total = 0
    for s in subjects:
        rs = [r for r in rows if r.subject_id == s.subject_id and (r.received_at or "") >= since]
        rs.sort(key=lambda r: r.received_at, reverse=True)
        n = len(rs)
        total += n
        cats: dict[str, int] = {}
        hours: dict[int, int] = {}
        for r in rs:
            cats[r.category] = cats.get(r.category, 0) + 1
            if r.hour is not None:
                hours[int(r.hour)] = hours.get(int(r.hour), 0) + 1
        offers = [
            {"received_at": r.received_at[:10], "category": r.category, "offer": r.offer_text, "subject": r.subject_line}
            for r in rs
            if r.offer_text
        ][:3]
        per.append(
            {
                "subject_id": s.subject_id,
                "name": s.name,
                "is_self": bool(s.is_self),
                "inbox": next((t.split(":", 1)[1] for t in (s.tags or []) if str(t).startswith("inbox:")), ""),
                "n": n,
                "per_week": round(n / max(1.0, window_days / 7.0), 1),
                "categories": cats,
                "peak_hour_utc": max(hours.items(), key=lambda kv: kv[1])[0] if hours else None,
                "latest_offers": offers,
                "latest_subjects": [r.subject_line for r in rs[:3]],
            }
        )
    return {
        "window_days": int(window_days),
        "since": since,
        "emails": total,
        "brands": per,
        "label": "What brands send players — marketing e-mail received in the organ's own inboxes.",
    }
