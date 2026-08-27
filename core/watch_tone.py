"""Tone of voice — how each brand talks to players (docs/89 §tone).

No new collection: the words are already in the registers. Promotions and
marketing claims are what the brand says on its own pages; comms subject
lines and offers are what it says in a player's inbox. This reads those
side by side — measurable habits first (shouting, urgency, emoji, sentence
length, how it names the player), then a short characterisation with
verbatim lines to back it.

The measurements are deterministic and the samples are quoted, so a
reader can disagree with the characterisation and still trust the page.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_URGENCY = re.compile(
    r"\b(now|today|hurry|last chance|ends?\s|expires?|don'?t miss|limited|only|"
    r"final|tonight|24 ?hours?|while (it|they) last|act fast|instantly)\b",
    re.I,
)
_REWARD = re.compile(
    r"\b(free|bonus|extra|win|prize|reward|jackpot|gift|treat|boost|double|"
    r"exclusive|vip)\b",
    re.I,
)
_SECOND_PERSON = re.compile(r"\b(you|your|you're|yours)\b", re.I)
_EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")
_WORD = re.compile(r"[A-Za-z']+")


def tone_features(texts: list[str]) -> dict[str, Any]:
    """Habits anyone can check: shouting, urgency, reward words, emoji,
    second person, and how long a line runs."""
    lines = [t for t in (texts or []) if t and t.strip()]
    if not lines:
        return {"samples": 0}
    words: list[str] = []
    caps_words = 0
    exclaims = 0
    emoji = 0
    urgency_hits = 0
    reward_hits = 0
    second_hits = 0
    for line in lines:
        ws = _WORD.findall(line)
        words.extend(ws)
        caps_words += sum(1 for w in ws if len(w) > 2 and w.isupper())
        exclaims += line.count("!")
        emoji += len(_EMOJI.findall(line))
        urgency_hits += len(_URGENCY.findall(line))
        reward_hits += len(_REWARD.findall(line))
        second_hits += len(_SECOND_PERSON.findall(line))
    n_words = max(1, len(words))
    return {
        "samples": len(lines),
        "words": len(words),
        "avg_words_per_line": round(len(words) / len(lines), 1),
        "caps_pct": round(100 * caps_words / n_words, 1),
        "exclaims_per_line": round(exclaims / len(lines), 2),
        "emoji_per_line": round(emoji / len(lines), 2),
        "urgency_per_100w": round(100 * urgency_hits / n_words, 1),
        "reward_per_100w": round(100 * reward_hits / n_words, 1),
        "second_person_per_100w": round(100 * second_hits / n_words, 1),
    }


def copy_samples(
    *,
    brand: str,
    evidence: list[dict[str, Any]] | None = None,
    catalog: list[Any] | None = None,
    comms: list[Any] | None = None,
    limit: int = 24,
) -> list[dict[str, str]]:
    """The brand's own words, newest first, with where each came from."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(text: str, source: str, url: str = "", when: str = "") -> None:
        line = " ".join((text or "").split())
        key = line.lower()[:80]
        if len(line) < 8 or key in seen:
            return
        seen.add(key)
        out.append({"text": line[:220], "source": source, "url": url, "observed_at": when[:10]})

    for row in catalog or []:
        if getattr(row, "kind", "") != "promotion":
            continue
        add(getattr(row, "name", ""), "promotion", getattr(row, "source_url", ""),
            getattr(row, "observed_at", ""))
        add(getattr(row, "detail", ""), "promotion terms", getattr(row, "source_url", ""),
            getattr(row, "observed_at", ""))
    for row in comms or []:
        add(getattr(row, "subject_line", ""), "e-mail subject", "", getattr(row, "received_at", ""))
        add(getattr(row, "offer_text", ""), "e-mail offer", "", getattr(row, "received_at", ""))
    for e in evidence or []:
        dim = str(e.get("dimension") or "").lower()
        if "marketing" not in dim and "promo" not in dim:
            continue
        add(str(e.get("value_text") or ""), "site copy", str(e.get("source_url") or ""),
            str(e.get("observed_at") or ""))
        add(str(e.get("excerpt") or ""), "site copy", str(e.get("source_url") or ""),
            str(e.get("observed_at") or ""))
    return out[:limit]


TONE_SYSTEM = """You characterise how sweepstakes / social casino brands TALK to players.
For each brand you are given measured habits (shouting, urgency, reward
words, emoji, second person, line length) and up to two dozen verbatim
lines from its own pages and e-mails.

RULES
- register: two or three words for the voice ("loud and urgent",
  "warm and premium", "plain and functional").
- traits: 2-3 short observations, each tied to what is measurable or
  quotable — never a guess about intent or strategy.
- signature: ONE verbatim line from the samples that best shows the
  voice. Copy it exactly; do not edit it.
- avoid: what this brand never does that others do, when the samples
  show it ("no emoji, no exclamation marks"), else "".
- Never invent a line. Never describe a brand you were given no samples
  for. Numbers stay as given.

Return STRICT JSON:
{"brands":[{"brand":str,"register":str,"traits":[str],"signature":str,"avoid":str}]}"""


async def read_tone(
    router: Any, brands: list[dict[str, Any]], *, max_brands: int = 14
) -> dict[str, dict[str, Any]]:
    """Characterise each brand's voice. {} without a router — the slide
    then shows the measurements alone, which still say plenty."""
    if router is None or not brands:
        return {}
    payload = [
        {
            "brand": b["name"],
            "features": b["features"],
            "lines": [s["text"] for s in b["samples"][:16]],
        }
        for b in brands[:max_brands]
        if b.get("samples")
    ]
    if not payload:
        return {}
    try:
        resp = await router.complete(
            messages=[
                {"role": "system", "content": TONE_SYSTEM},
                {"role": "user", "content": json.dumps({"brands": payload})[:24000]},
            ],
            task_type="analysis",
            temperature=0.1,
            max_tokens=2000,
        )
        text = (resp.content or "").strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            text = text[4:] if text.startswith("json") else text
        data = json.loads(text)
    except Exception as e:
        logger.warning("watch_tone: reading failed: %s", e)
        return {}
    known = {b["name"] for b in brands}
    said: dict[str, dict[str, Any]] = {}
    for item in (data.get("brands") or []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("brand") or "")
        if name not in known:
            continue
        lines = {s["text"].lower() for b in brands if b["name"] == name for s in b["samples"]}
        signature = " ".join(str(item.get("signature") or "").split())
        if signature and signature.lower() not in lines:
            signature = ""  # a line it did not actually say is no signature
        said[name] = {
            "register": " ".join(str(item.get("register") or "").split())[:40],
            "traits": [" ".join(str(t).split())[:120] for t in (item.get("traits") or [])][:3],
            "signature": signature[:200],
            "avoid": " ".join(str(item.get("avoid") or "").split())[:100],
        }
    return said


def summarize_tone(brands: list[dict[str, Any]], read: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """The reading of how the field talks, ours included."""
    read = read or {}
    rows = []
    for b in brands:
        if not b.get("samples"):
            continue
        f = b["features"]
        rows.append({
            "name": b["name"],
            "is_self": b.get("is_self", False),
            "samples": f.get("samples", 0),
            "features": f,
            **read.get(b["name"], {"register": "", "traits": [], "signature": "", "avoid": ""}),
            "quotes": b["samples"][:3],
        })
    rows.sort(key=lambda r: (not r["is_self"], r["name"]))
    loudest = max(rows, key=lambda r: r["features"].get("caps_pct", 0), default=None)
    most_urgent = max(rows, key=lambda r: r["features"].get("urgency_per_100w", 0), default=None)
    return {
        "brands": rows,
        "loudest": loudest["name"] if loudest else "",
        "most_urgent": most_urgent["name"] if most_urgent else "",
        "source": "model" if read else "measurements",
        "label": "Tone of voice read from each brand's own copy — promotions, site lines and e-mails.",
    }
