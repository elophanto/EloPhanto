"""Executive deck rendering for the competitive-intelligence organ.

The scorecard workbook is for the analyst and the board report is for the
reader; this is for the room. ~16 slides in a fixed house style, built from
the *same* stored evidence as the other deliverables — nothing here is
computed differently, it is only said the way a room hears it.

Design doctrine (adapted from decks that ship to steering committees):

* **The room hears about the market, not the machinery.** The front half of
  the deck is competitors: an executive summary in findings / threats /
  watch-next columns, standings, us-versus-the-leader, one deep-dive slide
  per key competitor (observations → implications), their storefronts as
  photographed exhibits, and the moves this period. Evidence coverage and
  method exist — in the appendix, where an analyst looks for them.
* **One idea per slide, action titles.** Every heading is a sentence someone
  could disagree with ("High 5 leads a thin field"), never a label. The
  model writes titles and commentary from the factual record; the numbers
  themselves are computed, never generated.
* **Exhibits are captures, not mockups.** A storefront screenshot on a slide
  was taken by the browser through a state-verified network exit, and is
  filed in the evidence register beside the claims from that page.
* **Restraint.** White content slides, ink type, one short accent rule under
  each heading, dark bookends. En dashes, never em.
* **No internal bookkeeping.** Hashes, file paths, manifests, run IDs and
  checkpoint numbers never reach a slide — enforced by prompt *and* by a
  scrubber here, because a deck once shipped with a SHA-256 on it.

And the organ's honesty rules survive the trip onto slides, where they are
most easily lost:

* unscored is blank, never zero — no bar, an empty heatmap cell;
* provisional brands are listed beside the chart, never ranked in it;
* model-written narrative is labelled as such, and when no model is
  available the deck says *facts only* — "could not evaluate" is never
  dressed as "nothing to report".
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── house tokens ─────────────────────────────────────────────────────
_INK = "111827"  # near-black: headings, display numbers, dark canvases
_BODY = "4B5563"  # body copy
_MUTED = "9CA3AF"  # eyebrows, footers, labels
_HAIR = "E5E7EB"  # hairlines
_CARD = "F9FAFB"  # zebra rows / note cards
_GAP_BG = "F3F4F6"  # heatmap: not observed
_ACCENT = "D97706"  # amber: the accent rule, and *our* brand everywhere
_PEER = "64748B"  # slate: peer brands
_DARK_BODY = "D1D5DB"  # body copy on dark canvases
_SELF_ROW = "FDF6EC"  # our row in the heatmap
_WHITE = "FFFFFF"

_CLASS_LABEL = {
    "no_regret": "No-regret",
    "transition_requirement": "Transition requirement",
    "post_transition": "Post-transition",
    "monitor": "Monitor",
}
_CLASS_ORDER = ["no_regret", "transition_requirement", "post_transition", "monitor"]

# Internal-bookkeeping tokens that must never reach a slide. The narrative
# prompt bans them; this scrubs whatever slips through. Hex runs need at
# least one letter so ordinary numbers ("1000000") survive.
_HEX_RE = re.compile(r"\b(?=[0-9a-f]*[a-f])[0-9a-f]{7,64}\b", re.I)
_BOOKKEEPING_RE = re.compile(
    r"\b(sha-?\d{0,3}|checksum|manifest|freeze receipt|run.id|checkpoint \d+)\b",
    re.I,
)


def _clean(text: Any, cap: int = 300) -> str:
    """House copy rules: en dashes, no bookkeeping tokens, collapsed, capped."""
    s = str(text or "")
    s = s.replace("—", "–")
    s = _HEX_RE.sub("", s)
    s = _BOOKKEEPING_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" -–,;")
    return s[:cap]


def _trim_words(text: str, cap: int) -> str:
    """Cap at a word boundary — a slide once shipped reading '…FLORI'."""
    if len(text) <= cap:
        return text
    cut = text[:cap]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ·-–,;")


def _fmt(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}"


# ── drawing primitives ───────────────────────────────────────────────


def _rgb(hexstr: str) -> Any:
    from pptx.dml.color import RGBColor

    return RGBColor.from_string(hexstr)


def _chars_per_line(width_in: float, size_pt: float) -> int:
    """How many characters a line of ``size_pt`` text holds in a box
    ``width_in`` wide (Calibri-ish, 0.52em average glyph), never below 6."""
    return max(6, int(max(0.3, width_in - 0.2) * 72 / (size_pt * 0.52)))


def _lines_needed(text: str, width_in: float, size_pt: float) -> int:
    import math

    cpl = _chars_per_line(width_in, size_pt)
    return sum(max(1, math.ceil(len(par) / cpl)) for par in (text or "").split("\n"))


def _block_height(text: str, width_in: float, size_pt: float, line: float = 1.2) -> float:
    """Inches a block of text needs, with the frame's own margins."""
    return _lines_needed(text, width_in, size_pt) * size_pt * line / 72 + 0.1


def _fit_text(text: str, width_in: float, height_in: float, size_pt: float, *, min_size: float, line: float = 1.2) -> tuple[str, float]:
    """The largest size down to ``min_size`` at which ``text`` fits the box;
    when even ``min_size`` does not fit, the text is cut to what does, with
    an ellipsis. A box never overflows its neighbours (2026-09-02: a deck
    of fifteen brands put panels on headings and footnotes on the footer)."""
    size = size_pt
    while size > min_size and _block_height(text, width_in, size, line) > height_in + 0.02:
        size = round(size - 0.5, 1)
    if _block_height(text, width_in, size, line) <= height_in + 0.02:
        return text, size
    lines_fit = max(1, int((height_in - 0.1) / (size * line / 72)))
    keep = _chars_per_line(width_in, size) * lines_fit - 2
    return _clean(text, max(12, keep)), size


def _text(
    slide: Any,
    left: float,
    top: float,
    width: float,
    height: float,
    text: str,
    *,
    size: float = 14,
    bold: bool = False,
    italic: bool = False,
    color: str = _INK,
    align: str = "left",
    spacing: float | None = None,
    line: float | None = None,
    wrap: bool = True,
    fit: bool = True,
) -> Any:
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    if fit and wrap and text and "\n" not in text and len(text) > 8:
        text, size = _fit_text(text, width, height, size, min_size=max(6.5, size * 0.6), line=line or 1.2)
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = box.text_frame
    tf.word_wrap = wrap
    p = tf.paragraphs[0]
    p.text = text
    p.alignment = {
        "left": PP_ALIGN.LEFT,
        "center": PP_ALIGN.CENTER,
        "right": PP_ALIGN.RIGHT,
    }[align]
    if line:
        p.line_spacing = line
    for r in p.runs:
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.italic = italic
        r.font.color.rgb = _rgb(color)
        if spacing is not None:
            rpr = r._r.get_or_add_rPr()
            rpr.set("spc", str(int(spacing * 100)))
    return box


def _bullets(
    slide: Any,
    left: float,
    top: float,
    width: float,
    height: float,
    items: list[str],
    *,
    size: float = 15,
    color: str = _BODY,
    gap_pt: int = 10,
    cap: int = 220,
    accent_bullet: bool = True,
    max_items: int = 6,
) -> Any:
    from pptx.util import Inches, Pt

    items = [str(i) for i in items[:max_items] if str(i).strip()]
    # Fit the block to its box: smaller type first, shorter items next,
    # fewer items last — never text over whatever sits below.
    def need(sz: float, cp: int, its: list[str]) -> float:
        return sum(_block_height(("•  " if accent_bullet else "") + _clean(i, cp), width, sz) - 0.1 + gap_pt / 72
                   for i in its) + 0.1

    size_eff, cap_eff = float(size), int(cap)
    while items and need(size_eff, cap_eff, items) > height + 0.02:
        if size_eff > max(7.0, size * 0.7):
            size_eff = round(size_eff - 0.5, 1)
        elif cap_eff > 60:
            cap_eff = int(cap_eff * 0.8)
        elif len(items) > 2:
            items = items[:-1]
        else:
            break
    size, cap = size_eff, cap_eff
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = box.text_frame
    tf.word_wrap = True
    first = True
    for item in items:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        if accent_bullet:
            r0 = p.add_run()
            r0.text = "•  "
            r0.font.size = Pt(size)
            r0.font.bold = True
            r0.font.color.rgb = _rgb(_ACCENT)
        r = p.add_run()
        r.text = _clean(item, cap)
        r.font.size = Pt(size)
        r.font.color.rgb = _rgb(color)
        p.space_after = Pt(gap_pt)
    return box


def _rule(slide: Any, y: float, *, x: float = 0.7, w: float = 0.7) -> None:
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    ln = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Pt(2.6))
    ln.fill.solid()
    ln.fill.fore_color.rgb = _rgb(_ACCENT)
    ln.line.fill.background()
    ln.shadow.inherit = False


def _eyebrow(slide: Any, text: str, *, y: float, x: float = 0.7, color: str = _MUTED) -> None:
    # Width fits the remaining canvas — an eyebrow placed in a right-hand
    # column must not spill past the slide edge — and the text is cut at a
    # word boundary, never mid-word.
    width = max(1.0, 13.333 - x - 0.73)
    _text(
        slide,
        x,
        y,
        width,
        0.3,
        _trim_words(_clean(text, 90), 60).upper(),
        size=10.5,
        bold=True,
        color=color,
        spacing=3,
    )


def _footer(slide: Any, deck_title: str, page: int) -> None:
    _text(slide, 0.7, 7.08, 8.5, 0.3, _clean(deck_title, 70), size=8.5, color=_MUTED)
    _text(slide, 12.0, 7.08, 0.7, 0.3, str(page), size=8.5, color=_MUTED, align="right")


def _header(slide: Any, eyebrow: str, title: str, commentary: str = "") -> float:
    """Eyebrow, action title, accent rule, optional one-line takeaway.

    Returns the y where slide content should start.
    """
    _eyebrow(slide, eyebrow, y=0.42)
    _text(
        slide,
        0.7,
        0.72,
        11.9,
        0.85,
        _clean(title, 110),
        size=23,
        bold=True,
        line=1.08,
    )
    _rule(slide, 1.62)
    if commentary:
        _text(
            slide,
            0.7,
            1.78,
            11.9,
            0.4,
            _clean(commentary, 170),
            size=12.5,
            italic=True,
            color=_BODY,
        )
        return 2.3
    return 2.0


def _judgement_note(slide: Any, source: str, *, dark: bool = False) -> None:
    msg = (
        "Narrative and commentary written by the model from the factual record "
        "– verify before presenting."
        if source == "model"
        else "Facts only – no model was available, so no narrative judgement has been applied."
    )
    # On the footer line, centred between the deck title and the page
    # number — the footnote band above is the slides' own.
    _text(slide, 4.4, 7.08, 6.9, 0.3, msg, size=7.5, color="6B7280" if dark else _MUTED, align="center")


def _notes(slide: Any, text: str) -> None:
    slide.notes_slide.notes_text_frame.text = text[:1000]


def _blank(prs: Any) -> Any:
    return prs.slides.add_slide(prs.slide_layouts[6])


def _dark(slide: Any) -> None:
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches

    bg = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(7.5)
    )
    bg.fill.solid()
    bg.fill.fore_color.rgb = _rgb(_INK)
    bg.line.fill.background()
    bg.shadow.inherit = False


def _picture(slide: Any, path: str, x: float, y: float, w: float, max_h: float) -> Any | None:
    """Place an image fitted to ``w`` wide, capped at ``max_h`` tall, with a
    hairline border. Returns the picture shape, or None if the file is
    unreadable — a missing exhibit never breaks the deck."""
    from pptx.util import Inches, Pt

    try:
        pic = slide.shapes.add_picture(path, Inches(x), Inches(y), width=Inches(w))
    except Exception as e:
        logger.debug("deck: could not place exhibit %s: %s", path, e)
        return None
    if pic.height > Inches(max_h):
        ratio = Inches(max_h) / pic.height
        pic.height = Inches(max_h)
        pic.width = int(pic.width * ratio)
    pic.line.color.rgb = _rgb(_HAIR)
    pic.line.width = Pt(1.0)
    pic.shadow.inherit = False
    return pic


# ── narrative fallback (no model) ────────────────────────────────────


def _sidebar(
    slide: Any,
    observations: list[str],
    implications: list[str],
    *,
    top: float,
    x: float = 9.1,
    w: float = 3.55,
    bottom: float = 6.55,
) -> float:
    """The right-hand reading panel every analytical slide carries: *Key
    observations* (what the chart shows) and *Key implications* (what it
    means for us). Executives read this column and skip the chart; the
    reference decks the customer benchmarks against carry it on every
    slide, and a slide without it makes the room guess. Returns the y where
    the panel ends. Draws nothing when both lists are empty."""
    obs = [str(o).strip() for o in observations if str(o).strip()][:4]
    imp = [str(i).strip() for i in implications if str(i).strip()][:3]
    if not obs and not imp:
        return top
    from pptx.util import Inches

    h = bottom - top
    card = slide.shapes.add_shape(
        1, Inches(x - 0.15), Inches(top - 0.1), Inches(w + 0.3), Inches(h)
    )
    card.fill.solid()
    card.fill.fore_color.rgb = _rgb(_CARD)
    card.line.fill.background()
    card.shadow.inherit = False
    y = top + 0.05
    if obs:
        _text(slide, x, y, w, 0.3, "Key observations", size=11, bold=True, color=_INK)
        y += 0.36
        # Reserve the implications' room first; the observations get the
        # rest and shrink into it (2026-09-02: they used to keep flowing
        # under the "Key implications" heading).
        imp_need = (0.36 + sum(_block_height("•  " + _clean(i, 120), w, 9.0) for i in imp) + 0.1) if imp else 0.2
        avail = bottom - y - imp_need
        obs_size, obs_cap = 9.5, 150
        obs_need = sum(_block_height(_clean(o, obs_cap), w, obs_size) - 0.04 for o in obs) + 0.1
        while obs_need > avail and (obs_size > 8.0 or obs_cap > 90):
            if obs_size > 8.0:
                obs_size -= 0.5
            else:
                obs_cap -= 20
            obs_need = sum(_block_height(_clean(o, obs_cap), w, obs_size) - 0.04 for o in obs) + 0.1
        block_h = max(0.4, min(obs_need, avail))
        _bullets(
            slide,
            x,
            y,
            w,
            block_h,
            obs,
            size=obs_size,
            color=_BODY,
            gap_pt=5,
            cap=obs_cap,
            accent_bullet=False,
            max_items=4,
        )
        y += block_h + 0.18
    if imp and y < bottom - 0.8:
        _text(slide, x, y, w, 0.3, "Key implications", size=11, bold=True, color=_ACCENT)
        y += 0.36
        _bullets(
            slide,
            x,
            y,
            w,
            max(0.5, bottom - y - 0.1),
            imp,
            size=9.5,
            color=_BODY,
            gap_pt=5,
            cap=150,
            accent_bullet=True,
            max_items=3,
        )
    return bottom


def _chip(slide: Any, x: float, y: float, n: int, *, color: str = _PEER) -> None:
    """A small numbered circle — the reference decks number each executive
    observation and repeat the number where the evidence lives."""
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    d = 0.26
    c = slide.shapes.add_shape(9, Inches(x), Inches(y), Inches(d), Inches(d))  # 9 = oval
    c.fill.solid()
    c.fill.fore_color.rgb = _rgb(color)
    c.line.fill.background()
    c.shadow.inherit = False
    tf = c.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.text = str(n)
    p.alignment = PP_ALIGN.CENTER
    for r in p.runs:
        r.font.size = Pt(8.5)
        r.font.bold = True
        r.font.color.rgb = _rgb(_WHITE)


def _slides_facts(
    card: dict[str, Any], offers: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Computed, model-free observations/implications per slide — the
    reading panel's fallback so a facts-only deck still tells the room what
    each slide shows. Numbers only, no claims about intent."""
    rows = card.get("rows", [])
    ranked = [r for r in rows if r.get("rank") is not None]
    us_rows = [r for r in rows if r.get("is_self")]
    us = us_rows[0] if us_rows else None
    leader = next((r for r in ranked if not r.get("is_self")), None)
    dims = card.get("dimensions", [])
    out: dict[str, dict[str, list[str]]] = {}

    st_obs: list[str] = []
    st_imp: list[str] = []
    if leader:
        st_obs.append(
            f"{leader['name']} leads the ranked field at {_fmt(leader['overall']['normalized_pct'])}."
        )
    if len(ranked) >= 3:
        spread = float(ranked[0]["overall"]["normalized_pct"]) - float(
            ranked[-1]["overall"]["normalized_pct"]
        )
        st_obs.append(f"{len(ranked)} brands ranked; {spread:.0f} points separate first from last.")
    for u in us_rows[:2]:
        if u.get("rank") is not None:
            st_obs.append(
                f"{u['name']} ranks #{u['rank']} at {_fmt(u['overall']['normalized_pct'])}."
            )
            if leader is not None:
                gap = float(leader["overall"]["normalized_pct"]) - float(
                    u["overall"]["normalized_pct"]
                )
                st_imp.append(f"{u['name']} sits {gap:.1f} points behind the leader.")
        elif u["overall"]["normalized_pct"] is not None:
            st_obs.append(f"{u['name']} is scored but not yet ranked.")
    if card.get("comparability_note"):
        st_imp.append("Ranks are withheld until the field is measured to comparable depth.")
    out["standings"] = {"observations": st_obs, "implications": st_imp}

    # dimensions: where we lead / trail
    lead, trail = [], []
    if us is not None:
        for d in dims:
            dn = d["name"]
            mine = us.get("dimensions", {}).get(dn, {}).get("score")
            scored = [
                float(r["dimensions"][dn]["score"])
                for r in rows
                if r.get("dimensions", {}).get(dn, {}).get("score") is not None
            ]
            if mine is None or not scored:
                continue
            best = max(scored)
            if float(mine) >= best:
                lead.append(dn)
            elif best - float(mine) >= 2:
                trail.append(dn)
    d_obs = []
    if lead:
        d_obs.append(
            f"We hold the top score on {len(lead)} dimension{'s' if len(lead) != 1 else ''}: "
            + ", ".join(lead[:3])
            + "."
        )
    if trail:
        d_obs.append("We trail by two or more points on: " + ", ".join(trail[:3]) + ".")
    out["dimensions"] = {"observations": d_obs, "implications": []}
    out["versus"] = {"observations": [], "implications": []}

    o_obs = []
    if offers:
        with_welcome = [o for o in offers if o.get("welcome")]
        o_obs.append(
            f"{len(with_welcome)} of {len(offers)} brands lead with a stated welcome offer."
        )
    out["offers"] = {"observations": o_obs, "implications": []}
    out["exhibits"] = {"observations": [], "implications": []}
    out["coverage"] = {"observations": [], "implications": []}
    return out


def _voice_facts(voice: dict[str, Any] | None) -> dict[str, list[str]]:
    """Computed reading of the voice summary — the 'What players say'
    panel's fallback. Shares with n; opinion, never fact."""
    if not voice or not voice.get("mentions"):
        return {"observations": [], "implications": []}
    brands = [b for b in voice.get("brands", []) if not b.get("too_few")]
    obs: list[str] = []
    imps: list[str] = []
    obs.append(
        f"{voice['mentions']} public mentions across {len(voice.get('sources') or [])} source"
        f"{'s' if len(voice.get('sources') or []) != 1 else ''} in {voice.get('window_days', 30)} days; "
        f"{len(brands)} of {len(voice.get('brands', []))} brands have enough to read."
    )
    field = voice.get("field_themes") or {}
    if field:
        top = max(field.items(), key=lambda kv: kv[1]["share"] * kv[1]["neg_share"])
        obs.append(
            f"Field-wide, the loudest complaint theme is {top[0].replace('_', ' ')} "
            f"({int(round(top[1]['share'] * 100))}% of mentions, {int(round(top[1]['neg_share'] * 100))}% negative)."
        )
    worst = max(brands, key=lambda b: b.get("neg_share", 0.0), default=None)
    if worst:
        obs.append(
            f"{worst['name']} draws the most negative sentiment "
            f"({int(round(worst['neg_share'] * 100))}% of {worst['n']} mentions)"
            + (f", mostly {worst['top_complaint'].replace('_', ' ')}." if worst.get("top_complaint") else ".")
        )
    us = next((b for b in brands if b.get("is_self")), None)
    if us:
        obs.append(
            f"We sit at {int(round(us['neg_share'] * 100))}% negative on {us['n']} mentions"
            + (f"; top complaint {us['top_complaint'].replace('_', ' ')}." if us.get("top_complaint") else ".")
        )
        if us.get("flags"):
            imps.append("Players flag " + ", ".join(us["flags"][:2]) + " for us — read those deep dives.")
    imps.append("Sentiment, not fact: verify a theme on the page before acting on it.")
    return {"observations": obs[:4], "implications": imps[:3]}


_EVENT_RE = re.compile(
    r"\b(is closing|will close|closing on|closes on|shut(?:ting)? down|ceas(?:e|es|ing) "
    r"operations|exit(?:s|ed|ing)? (?:the )?(?:market|state)|leav(?:es|ing) (?:the )?"
    r"(?:market|state)|acquired by|acquisition of|merg(?:es|ed|ing) with|rebrand(?:s|ed|ing)?"
    r"(?: to| as)|now available in|launch(?:es|ed|ing)? in|cease[- ]and[- ]desist|"
    r"regulator|banned in|no longer (?:available|accept))\b",
    re.I,
)


_STRONG_EVENT_RE = re.compile(
    r"\b(is closing|will close|closing on|closes on|shut(?:ting)? down|ceas(?:e|es|ing) "
    r"operations|exit(?:s|ed|ing)? (?:the )?(?:market|state)|leav(?:es|ing) (?:the )?"
    r"(?:market|state)|acquired by|acquisition of|merg(?:es|ed|ing) with|cease[- ]and[- ]desist|"
    r"banned in|no longer (?:available|accept))\b",
    re.I,
)


def market_events(
    evidence: list[dict[str, Any]], *, limit: int = 4
) -> list[dict[str, Any]]:
    """Corporate / market events on record — closures, exits, acquisitions,
    rebrands, launches, regulatory notices — read straight from the claims.
    A baseline pack has no diff to surface them through, and a competitor
    closing (LuckyLand, 2026-08-16: "closing September 14, 2026" on the
    homepage) is the most material fact in the room; it must not sit in an
    appendix row while the market-moves slide says "no material change".
    Newest first, one per brand × claim."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for e in evidence:  # newest first
        claim = str(e.get("claim") or "").strip()
        if not claim or not _EVENT_RE.search(claim):
            continue
        # Third-party pages carry the whole industry's news; only the
        # strong verbs (closing, shutting down, ceasing, exiting, acquired,
        # cease-and-desist, banned) count there. Launches, rebrands and
        # 'now available in' count only when the brand's own page says so
        # (2026-08-18: a High 5 news mention of another operator's launch
        # was read as a High 5 market event).
        if str(e.get("source_type") or "") == "third_party" and not _STRONG_EVENT_RE.search(claim):
            continue
        brand = str(e.get("subject") or "").strip()
        # Two phrasings of one event ("…is closing on September 14, 2026" and
        # the same with a trailing clause) are one event: key on the opening.
        key = (brand, re.sub(r"[^a-z0-9]+", " ", claim.lower()).strip()[:44])
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "brand": brand,
                "claim": claim,
                "when": str(e.get("value_text") or ""),
                "observed_at": str(e.get("observed_at") or "")[:10],
                "url": str(e.get("source_url") or ""),
            }
        )
        if len(out) >= limit:
            break
    return out


def _events_banner(s: Any, events: list[dict[str, Any]], y: float) -> float:
    """A red-eyebrow strip under the headline: 'MARKET EVENT · <claim>'.
    Returns the y below the strip."""
    if not events:
        return y
    from pptx.util import Pt

    for ev in events[:2]:
        box = s.shapes.add_shape(1, _in(0.7), _in(y), _in(11.9), _in(0.36))
        box.fill.solid()
        box.fill.fore_color.rgb = _rgb(_CARD)
        box.line.color.rgb = _rgb(_ACCENT)
        box.line.width = Pt(0.75)
        box.shadow.inherit = False
        _text(s, 0.82, y + 0.05, 1.5, 0.28, "MARKET EVENT", size=8.5, bold=True, color=_ACCENT)
        line = f"{ev['brand']} – {ev['claim']}"
        if ev.get("observed_at"):
            line += f"  (observed {ev['observed_at']})"
        _text(s, 2.3, y + 0.05, 10.2, 0.28, _clean(line, 150), size=10, bold=True, color=_INK)
        y += 0.44
    return y


def factual_narrative(
    card: dict[str, Any],
    diff: dict[str, Any] | None,
    judged: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    *,
    voice: dict[str, Any] | None = None,
    comms: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The deck's words when no model is available: numbers only, no claims.

    Deliberately dull — a dull true summary beats a sharp invented one. Same
    shape as the model's narrative, so the renderer never branches; the
    model-only sections (exec zones, competitor profiles) stay empty and
    their slides are skipped rather than faked.
    """
    rows = card.get("rows", [])
    ranked = [r for r in rows if r.get("rank") is not None]
    us = next((r for r in rows if r.get("is_self")), None)
    leader = ranked[0] if ranked else None

    bullets: list[str] = []
    if leader:
        bullets.append(
            f"{leader['name']} leads the ranked field at "
            f"{_fmt(leader['overall']['normalized_pct'])} across {len(ranked)} "
            f"ranked brands ({len(rows)} tracked)."
        )
    else:
        bullets.append(
            f"{len(rows)} brands tracked; none yet scored on enough of the model to rank."
        )
    if us is not None:
        if us.get("rank") is not None:
            bullets.append(
                f"{us['name']} ranks #{us['rank']} at {_fmt(us['overall']['normalized_pct'])}."
            )
        elif us["overall"]["normalized_pct"] is not None:
            bullets.append(
                f"{us['name']} scores {_fmt(us['overall']['normalized_pct'])} "
                "but is provisional – not enough of the model measured to rank."
            )
        else:
            bullets.append(f"{us['name']} is not yet scored on any dimension.")
    if diff is None:
        bullets.append("First cycle: this pack sets the baseline; change appears next cycle.")
    else:
        n = int(diff.get("material_count", 0))
        bullets.append(
            f"{n} material change{'s' if n != 1 else ''} since the last snapshot."
            if n
            else "No material change since the last snapshot."
        )
    never = [g for g in gaps if g.get("status") == "never_observed"]
    stale = [g for g in gaps if g.get("status") == "stale"]
    bullets.append(
        f"{len(never)} brand × dimension pairs never observed; {len(stale)} overdue a refresh."
    )
    asks = [
        j
        for j in judged
        if str(j.get("decision_required", "none")).strip().lower() not in ("", "none")
    ]

    never_brands = sorted({g["subject"] for g in never})
    next_steps: list[str] = []
    if never_brands:
        more = " and others" if len(never_brands) > 3 else ""
        next_steps.append("Collect the unobserved brands – " + ", ".join(never_brands[:3]) + more)
    if stale:
        next_steps.append(f"Refresh the {len(stale)} pairs overdue against their cadence")
    if asks:
        plural = "s" if len(asks) != 1 else ""
        next_steps.append(f"Decide the {len(asks)} board ask{plural} on the decisions slide")
    if not next_steps:
        next_steps.append("Hold the cadence – re-observe on schedule and diff next cycle")

    # Executive-summary columns, computed: per top-weight dimension, who
    # holds the top score and where we stand. Dull but true.
    by_dim: list[dict[str, Any]] = []
    for d in sorted(card.get("dimensions", []), key=lambda d: -float(d.get("weight_pct") or 0))[:6]:
        dn = d["name"]
        scored = [
            (r, float(r["dimensions"][dn]["score"]))
            for r in rows
            if r.get("dimensions", {}).get(dn, {}).get("score") is not None
        ]
        obs: list[str] = []
        if scored:
            best = max(sc for _, sc in scored)
            names = [r["name"] for r, sc in scored if sc == best][:2]
            verb = "holds" if len(names) == 1 else "hold"
            obs.append(f"{' and '.join(names)} {verb} the top score ({best:g}/5).")
            if us is not None:
                mine = us.get("dimensions", {}).get(dn, {}).get("score")
                if mine is not None:
                    obs.append(f"{us['name']} scores {float(mine):g}/5.")
        else:
            obs.append("Not yet observed for any brand.")
        by_dim.append({"dimension": dn, "observations": obs})

    slides = _slides_facts(card)
    if voice and voice.get("mentions"):
        slides["voice"] = _voice_facts(voice)
    if comms and comms.get("emails"):
        slides["comms"] = _comms_facts(comms)
    return {
        "headline": "",
        "bullets": bullets[:5],
        "exec": {"by_dimension": by_dim, "recommendation": "", "actions": []},
        "profiles": [],
        "titles": {},
        "commentary": {},
        "slides": slides,
        "next_steps": next_steps[:4],
        "source": "facts",
    }


# Back-compat alias for older callers.
factual_summary = factual_narrative


# ── slide builders ───────────────────────────────────────────────────


def _slide_title(
    prs: Any, *, title: str, market: str, period: str, basis: str, generated: str
) -> None:
    s = _blank(prs)
    _dark(s)
    _eyebrow(s, market or "Competitive intelligence", y=1.05)
    _text(
        s,
        0.7,
        1.55,
        11.9,
        1.9,
        _clean(title, 90),
        size=40,
        bold=True,
        color=_WHITE,
        line=1.06,
    )
    _text(s, 0.7, 3.55, 11.0, 0.5, _clean(period, 120), size=15, color=_MUTED)
    _rule(s, 4.35)
    _text(s, 0.7, 4.6, 11.9, 0.4, _clean(basis, 160), size=11, color=_MUTED)
    try:
        month = datetime.fromisoformat(generated).strftime("%B %Y")
    except Exception:
        month = datetime.now(UTC).strftime("%B %Y")
    _text(s, 0.7, 6.75, 5.0, 0.3, month, size=10, color=_MUTED)


def _slide_reading_guide(
    prs: Any,
    card: dict[str, Any],
    evidence_count: int,
    page: int,
    deck_title: str,
    *,
    voice: dict[str, Any] | None = None,
    catalog: dict[str, Any] | None = None,
    trends: dict[str, Any] | None = None,
) -> None:
    """Slide 2: what a first-time reader must know before the numbers —
    where the facts come from, what a score is, what † means, what a run
    is, that 'what players say' is opinion, and where the raw data lives.
    Written after a client read the 2026-08-30 pack cold and asked what
    'pairs', 'cycles' and 'read from: review site' meant."""
    s = _blank(prs)
    top = _header(s, "How to read this deck", "Six things to know before the numbers")
    rows = card.get("rows", [])
    dims = card.get("dimensions", [])
    generated = str(card.get("generated_at") or "")[:10]
    items = [
        f"Where the facts come from – the agent read each of the {len(rows)} brands' public pages"
        + (f" (latest {generated})" if generated else "")
        + f"; {evidence_count:,} facts, each quoted from a page and linked to it in the workbook.",
        f"Scores – each brand is scored 1–5 on {len(dims)} dimensions, weighted by what matters to us; "
        "Overall is 0–100 and counts only what was actually seen, never padded.",
        "† Provisional – we have not yet seen enough of that brand to rank it fairly. Its score is shown, "
        "its rank is withheld until it can be compared like for like.",
        "Logged-out vs signed-in – pages read logged-out show what a visitor sees. A brand's coin store and "
        "full game lobby sit behind a login, so those sections say 'not read yet' until a signed-in read.",
    ]
    if trends and int(trends.get("cycles", 0)) >= 2:
        items.append(
            "A run is one date on which every brand was read; trend lines join runs. Flat lines mean the "
            "pages did not change; a jump usually means we read more of a brand that run."
        )
    if voice and voice.get("mentions"):
        items.append(
            f"'What players say' is opinion – posts on {_voice_sources(voice)} from the last "
            f"{voice.get('window_days', 30)} days. It flags what to look at and never moves a score."
        )
    if catalog and catalog.get("items"):
        items.append(
            "The appendix is the raw inventory – game providers, coin packages, promotions, games and loyalty "
            "tiers per brand, as printed. Click a name to open the page it was read from; the workbook holds every row."
        )
    _bullets(s, 0.7, top + 0.1, 11.9, 6.5 - top, items[:7], size=12.5, gap_pt=8, cap=300,
             accent_bullet=False, max_items=7)
    _footer(s, deck_title, page)


def _slide_summary(
    prs: Any,
    card: dict[str, Any],
    narrative: dict[str, Any],
    page: int,
    deck_title: str,
    events: list[dict[str, Any]] | None = None,
) -> None:
    """The executive summary a steering committee reads first, in the shape
    of the reference decks: one column per battleground with numbered
    observations, then a recommendation strip — recommendation, where we
    stand, decisions. Nothing on this slide is a new fact; every line is a
    reading of the scorecard, the offers table or the material-change diff.

    Falls back to the three-zone findings/threats/watch layout when the
    narrative carries no per-dimension observations."""
    s = _blank(prs)
    _eyebrow(s, "Executive summary", y=0.42)
    headline = _clean(narrative.get("headline") or "", 120)
    y = 0.72
    if headline:
        _text(s, 0.7, y, 11.9, 0.9, headline, size=21, bold=True, line=1.08)
        y += 0.9
    else:
        y += 0.2
    y = _events_banner(s, events or [], y)
    _rule(s, y)
    y += 0.22

    exec_zone = narrative.get("exec") or {}
    by_dim = [
        d
        for d in (exec_zone.get("by_dimension") or [])
        if isinstance(d, dict) and str(d.get("dimension") or "").strip()
    ][:6]
    rows = card.get("rows", [])
    us_rows = [r for r in rows if r.get("is_self")]
    ranked = [r for r in rows if r.get("rank") is not None]
    leader = next((r for r in ranked if not r.get("is_self")), None)

    if by_dim:
        # ── dimension columns ──
        n = len(by_dim)
        gutter = 0.18
        col_w = (11.9 - gutter * (n - 1)) / n
        band_top = y
        band_bottom = 4.55
        counter = 0
        for ci, d in enumerate(by_dim):
            x = 0.7 + ci * (col_w + gutter)
            # column header
            hdr = s.shapes.add_shape(1, _in(x), _in(band_top), _in(col_w), _in(0.5))
            hdr.fill.solid()
            hdr.fill.fore_color.rgb = _rgb(_CARD)
            hdr.line.fill.background()
            hdr.shadow.inherit = False
            _text(
                s,
                x + 0.08,
                band_top + 0.06,
                col_w - 0.16,
                0.42,
                _clean(str(d.get("dimension")), 46),
                size=9.5,
                bold=True,
                color=_INK,
                line=1.0,
            )
            oy = band_top + 0.62
            for obs in [str(o) for o in (d.get("observations") or []) if str(o).strip()][:3]:
                if oy > band_bottom - 0.4:
                    break
                counter += 1
                _chip(
                    s,
                    x,
                    oy + 0.02,
                    counter,
                    color=_ACCENT if any(u["name"] in obs for u in us_rows) else _PEER,
                )
                text = _clean(obs, 130)
                lines = 1 + len(text) // max(18, int(col_w * 9.5))
                h = min(0.22 * lines + 0.1, band_bottom - oy)
                _text(s, x + 0.34, oy, col_w - 0.36, h, text, size=9, color=_BODY, line=1.05)
                oy += h + 0.1
        # ── recommendation strip ──
        y = band_bottom + 0.2
        _rule(s, y)
        y += 0.2
        strip_h = 6.5 - y
        boxes = [
            ("Recommendation", 0.7, 4.7),
            ("Where we stand", 5.55, 3.55),
            ("Decisions / next steps", 9.25, 3.35),
        ]
        rec = _clean(exec_zone.get("recommendation") or headline or "", 260)
        stand: list[str] = []
        for u in us_rows[:2]:
            if u.get("rank") is not None:
                line = f"{u['name']} – #{u['rank']} at {_fmt(u['overall']['normalized_pct'])}"
                if leader is not None:
                    gap = float(leader["overall"]["normalized_pct"]) - float(
                        u["overall"]["normalized_pct"]
                    )
                    line += f", {gap:.1f} behind {leader['name']}"
                stand.append(line)
            elif u["overall"]["normalized_pct"] is not None:
                stand.append(
                    f"{u['name']} – scores {_fmt(u['overall']['normalized_pct'])}, not yet ranked"
                )
            else:
                stand.append(f"{u['name']} – not yet scored")
        if leader is not None:
            stand.append(f"Leader: {leader['name']} at {_fmt(leader['overall']['normalized_pct'])}")
        if card.get("comparability_note"):
            stand.append("Ranks withheld until coverage is comparable")
        actions = [str(a) for a in (exec_zone.get("actions") or []) if str(a).strip()][:3] or [
            str(a) for a in (narrative.get("next_steps") or [])
        ][:3]
        for label, x, _w in boxes:
            _eyebrow(s, label, y=y, x=x, color=_ACCENT if label == "Recommendation" else _MUTED)
        if rec:
            _text(
                s, 0.7, y + 0.35, 4.7, strip_h - 0.4, rec, size=11, bold=True, color=_INK, line=1.12
            )
        _bullets(
            s,
            5.55,
            y + 0.35,
            3.55,
            strip_h - 0.4,
            stand or ["No brand marked as ours."],
            size=9.5,
            color=_BODY,
            gap_pt=5,
            cap=110,
            accent_bullet=False,
            max_items=4,
        )
        _bullets(
            s,
            9.25,
            y + 0.35,
            3.35,
            strip_h - 0.4,
            actions or ["Hold the cadence; diff next cycle."],
            size=9.5,
            color=_BODY,
            gap_pt=5,
            cap=110,
            accent_bullet=True,
            max_items=3,
        )
    else:
        findings = [str(x) for x in exec_zone.get("findings") or []]
        threats = [str(x) for x in exec_zone.get("threats") or []]
        watch = [str(x) for x in exec_zone.get("watch") or []]
        if findings or threats or watch:
            cols = [
                ("Key findings", _PEER, findings, 0.7, 3.9),
                ("Key threats", _ACCENT, threats, 4.95, 3.9),
                ("Watch next", _MUTED, watch, 9.2, 3.4),
            ]
            for label, label_color, items, x, w in cols:
                _eyebrow(s, label, y=y, x=x, color=label_color)
                _bullets(
                    s,
                    x,
                    y + 0.38,
                    w,
                    6.35 - y,
                    items or ["Nothing this period."],
                    size=12,
                    gap_pt=9,
                    cap=140,
                    accent_bullet=False,
                    max_items=4,
                )
        else:
            _bullets(
                s,
                0.7,
                y,
                11.9,
                6.4 - y,
                [str(b) for b in narrative.get("bullets") or []],
                size=15,
                gap_pt=12,
                cap=140,
            )
    _judgement_note(s, str(narrative.get("source") or "facts"))
    _footer(s, deck_title, page)
    _notes(
        s,
        "Every line traces to the scorecard, the offers table, the material-change "
        "diff or the evidence register. Nothing on this slide is a new fact. Numbers "
        "run across the columns in reading order.",
    )


def _in(v: float) -> Any:
    from pptx.util import Inches

    return Inches(v)


def _slide_glance(
    prs: Any,
    card: dict[str, Any],
    evidence_count: int,
    gaps: list[dict[str, Any]],
    commentary: str,
    page: int,
    deck_title: str,
) -> None:
    s = _blank(prs)
    _header(s, "The market at a glance", "The numbers under everything else")
    rows = card.get("rows", [])
    dims = card.get("dimensions", [])
    ranked = [r for r in rows if r.get("rank") is not None]
    leader = ranked[0] if ranked else None
    pairs = len(rows) * len(dims)
    observed = sum(
        1 for r in rows for d in r.get("dimensions", {}).values() if d.get("score") is not None
    )
    pct = (observed / pairs * 100.0) if pairs else 0.0

    scored = sorted(
        (r for r in rows if r["overall"]["normalized_pct"] is not None),
        key=lambda r: -float(r["overall"]["normalized_pct"]),
    )
    # Ranks withheld (comparability) or nothing ranked yet: the scores are
    # still the numbers under everything else — show the highest and say it
    # is unranked, rather than a dash and "0 / 14 ranked" (2026-08-16 pack).
    if leader is not None:
        first = (
            _fmt(leader["overall"]["normalized_pct"]),
            f"{leader['name']} – ranked leader",
        )
        second = (f"{len(ranked)} / {len(rows)}", "brands ranked / tracked")
    elif scored:
        first = (
            _fmt(scored[0]["overall"]["normalized_pct"]),
            f"{scored[0]['name']} – highest score, ranks withheld"
            if card.get("comparability_note")
            else f"{scored[0]['name']} – highest score, provisional",
        )
        second = (f"{len(scored)} / {len(rows)}", "brands scored / tracked – none ranked yet")
    else:
        first = ("—", "no brand scored yet")
        second = (f"0 / {len(rows)}", "brands scored / tracked")
    tiles = [
        first,
        second,
        (f"{pct:.0f}%", f"of the scorecard filled in – {observed} of {pairs} brand × dimension cells"),
        (f"{evidence_count:,}", "observed facts, each quoted from a page and linked to it"),
    ]
    x = 0.7
    w = 12.0 / len(tiles)
    for value, label in tiles:
        _text(s, x, 2.6, w - 0.35, 1.0, str(value)[:14], size=34, bold=True)
        _text(s, x, 3.62, w - 0.35, 0.75, _clean(label, 70), size=10.5, color=_MUTED)
        x += w
    if commentary:
        _text(
            s,
            0.7,
            5.0,
            11.9,
            0.5,
            _clean(commentary, 170),
            size=12.5,
            italic=True,
            color=_BODY,
        )
    _footer(s, deck_title, page)


def _slide_standings(
    prs: Any,
    card: dict[str, Any],
    narrative: dict[str, Any],
    page: int,
    deck_title: str,
) -> None:
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
    from pptx.util import Inches, Pt

    s = _blank(prs)
    title = (narrative.get("titles") or {}).get("standings") or "Where the market stands"
    top = _header(
        s,
        "Standings",
        title,
        (narrative.get("commentary") or {}).get("standings", ""),
    )

    rows = card.get("rows", [])
    ranked = [r for r in rows if r.get("rank") is not None]
    provisional = [
        r for r in rows if r.get("provisional") and r["overall"]["normalized_pct"] is not None
    ]
    unscored = [r for r in rows if r["overall"]["normalized_pct"] is None]

    if ranked:
        shown = ranked[:12]
        cd = CategoryChartData()
        cd.categories = [
            f"{r['name']}{'  (us)' if r.get('is_self') else ''}" for r in reversed(shown)
        ]
        cd.add_series(
            "Overall (normalized %)",
            [round(float(r["overall"]["normalized_pct"]), 1) for r in reversed(shown)],
        )
        gf = s.shapes.add_chart(
            XL_CHART_TYPE.BAR_CLUSTERED,
            Inches(0.7),
            Inches(top),
            Inches(8.1),
            Inches(6.6 - top),
            cd,
        )
        ch = gf.chart
        ch.has_legend = False
        ch.has_title = False
        va = ch.value_axis
        va.minimum_scale = 0
        va.maximum_scale = 100
        va.has_major_gridlines = False
        va.tick_labels.font.size = Pt(9)
        va.tick_labels.font.color.rgb = _rgb(_MUTED)
        ca = ch.category_axis
        ca.tick_labels.font.size = Pt(11)
        ca.tick_labels.font.color.rgb = _rgb(_INK)
        plot = ch.plots[0]
        plot.gap_width = 55
        plot.has_data_labels = True
        dl = plot.data_labels
        dl.font.size = Pt(10)
        dl.font.bold = True
        dl.font.color.rgb = _rgb(_INK)
        dl.number_format = "0.0"
        dl.number_format_is_linked = False
        dl.position = XL_LABEL_POSITION.OUTSIDE_END
        ser = plot.series[0]
        ser.format.fill.solid()
        ser.format.fill.fore_color.rgb = _rgb(_PEER)
        for idx, r in enumerate(reversed(shown)):
            if r.get("is_self"):
                pt = ser.points[idx]
                pt.format.fill.solid()
                pt.format.fill.fore_color.rgb = _rgb(_ACCENT)
        if len(ranked) > len(shown):
            _text(
                s,
                0.7,
                6.62,
                8.1,
                0.3,
                f"Top {len(shown)} of {len(ranked)} ranked brands shown.",
                size=9,
                color=_MUTED,
            )
    elif card.get("comparability_note") and provisional:
        # Ranks withheld, scores real: say so in one line, then chart the
        # scores unranked — the room still needs to see the numbers.
        _text(
            s,
            0.7,
            top,
            8.1,
            0.55,
            "Not yet a league table – " + _clean(card["comparability_note"], 150) + ".",
            size=9.5,
            italic=True,
            color=_ACCENT,
        )
        shown = sorted(provisional, key=lambda r: -float(r["overall"]["normalized_pct"]))[:14]
        cd = CategoryChartData()
        cd.categories = [
            f"{r['name']}{'  (us)' if r.get('is_self') else ''}" for r in reversed(shown)
        ]
        cd.add_series(
            "Score (unranked)",
            [round(float(r["overall"]["normalized_pct"]), 1) for r in reversed(shown)],
        )
        gf = s.shapes.add_chart(
            XL_CHART_TYPE.BAR_CLUSTERED,
            Inches(0.7),
            Inches(top + 0.55),
            Inches(8.1),
            Inches(6.6 - top - 0.55),
            cd,
        )
        ch = gf.chart
        ch.has_legend = False
        ch.has_title = False
        va = ch.value_axis
        va.minimum_scale = 0
        va.maximum_scale = 100
        va.has_major_gridlines = False
        va.tick_labels.font.size = Pt(9)
        va.tick_labels.font.color.rgb = _rgb(_MUTED)
        ca = ch.category_axis
        ca.tick_labels.font.size = Pt(10)
        ca.tick_labels.font.color.rgb = _rgb(_INK)
        plot = ch.plots[0]
        plot.gap_width = 55
        plot.has_data_labels = True
        plot.data_labels.font.size = Pt(9)
        plot.data_labels.font.color.rgb = _rgb(_BODY)
        plot.data_labels.number_format = "0.0"
        plot.data_labels.number_format_is_linked = False
        plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
        ser = plot.series[0]
        for i, r in enumerate(reversed(shown)):
            pt = ser.points[i]
            pt.format.fill.solid()
            pt.format.fill.fore_color.rgb = _rgb(_ACCENT if r.get("is_self") else _PEER)
        provisional = []  # charted; do not repeat them in the side notes
    else:
        _text(
            s,
            0.7,
            top + 0.2,
            8.1,
            1.0,
            "No brand has yet been scored on enough of the model to hold a rank.",
            size=15,
            color=_BODY,
        )

    x = 9.1
    panel = (narrative.get("slides") or {}).get("standings") or {}
    y = _sidebar(
        s,
        panel.get("observations") or [],
        panel.get("implications") or [],
        top=top,
        x=x,
        w=3.5,
        bottom=(
            min(6.55, top + 2.3)
            if (provisional and unscored)
            else min(6.55, top + 3.0)
            if (provisional or unscored)
            else 6.55
        ),
    )
    y += 0.25 if y > top else 0.0
    if y > 6.3:
        y = 6.72  # sidebar used the column; the note shares the footnote line
    _text(
        s,
        x,
        y,
        3.5,
        0.3 if y >= 6.7 else 0.5,
        "Overall score, normalized to the weight actually measured. Amber – our brand.",
        size=8 if y >= 6.7 else 8.5,
        color=_MUTED,
    )
    y += 0.55
    if provisional and y < 6.0:
        _eyebrow(s, "Scored, not ranked †", y=y, x=x)
        y += 0.32
        lines = [
            f"{r['name']}: {_fmt(r['overall']['normalized_pct'])} – "
            f"{r.get('provisional_reason', 'thin evidence')}"
            for r in provisional[: (2 if unscored else 4)]
        ]
        block_h = min(0.5 * len(lines) + 0.1, 6.55 - y - (0.7 if unscored else 0))
        _bullets(
            s,
            x,
            y,
            3.5,
            max(0.3, block_h),
            lines,
            size=9,
            color=_MUTED,
            gap_pt=5,
            cap=120,
            accent_bullet=False,
        )
        y += max(0.3, block_h) + 0.15
    if unscored and y < 6.4:
        _eyebrow(s, "Not yet observed", y=y, x=x)
        names = ", ".join(r["name"] for r in unscored[:8])
        if len(unscored) > 8:
            names += f" +{len(unscored) - 8} more"
        _text(s, x, y + 0.32, 3.5, min(1.4, 6.7 - y), names, size=9.5, color=_MUTED)
    _footer(s, deck_title, page)
    _notes(
        s,
        "Provisional brands are omitted from the chart on purpose: a bar is "
        "trusted without its footnote. Their scores are real; the standing is "
        "not yet earned. Unscored brands are never drawn as 0.",
    )


def _slide_versus(
    prs: Any,
    card: dict[str, Any],
    narrative: dict[str, Any],
    page: int,
    deck_title: str,
) -> None:
    s = _blank(prs)
    rows = card.get("rows", [])
    us = next((r for r in rows if r.get("is_self")), None)
    leader = next(
        (r for r in rows if r.get("rank") is not None and not r.get("is_self")),
        None,
    )
    if leader is None:
        # Ranks withheld (field not comparable) — compare against the
        # highest-scoring peer; dimension scores are still real.
        peers = [
            r for r in rows if not r.get("is_self") and r["overall"]["normalized_pct"] is not None
        ]
        leader = max(peers, key=lambda r: float(r["overall"]["normalized_pct"])) if peers else None
    title = (narrative.get("titles") or {}).get("versus") or "Where we win, where we lose"
    top = _header(
        s,
        "Versus the leader",
        title,
        (narrative.get("commentary") or {}).get("versus", ""),
    )

    if us is None:
        _text(
            s,
            0.7,
            top + 0.2,
            11.9,
            1.0,
            "No brand is marked as ours, so there is nothing to compare. Mark "
            "one with watch_subject is_self=true and this slide fills in.",
            size=14,
            color=_BODY,
        )
        _footer(s, deck_title, page)
        return
    if leader is None:
        _text(
            s,
            0.7,
            top + 0.2,
            11.9,
            1.0,
            f"{us['name']} is the only ranked brand so far – no peer holds a "
            "rank yet to compare against.",
            size=14,
            color=_BODY,
        )
        _footer(s, deck_title, page)
        return

    _text(
        s,
        0.7,
        top,
        11.9,
        0.45,
        f"{us['name']}  {_fmt(us['overall']['normalized_pct'])}   vs   "
        f"{leader['name']} "
        f"({'#' + str(leader['rank']) if leader.get('rank') is not None else 'highest-scoring peer'})  "
        f"{_fmt(leader['overall']['normalized_pct'])}",
        size=15,
        bold=True,
    )
    top += 0.6

    weights = {d["name"]: d["weight_pct"] for d in card.get("dimensions", [])}
    ahead: list[tuple[float, str]] = []
    behind: list[tuple[float, str]] = []
    unmeasured: list[str] = []
    for dname, ours in us.get("dimensions", {}).items():
        theirs = leader.get("dimensions", {}).get(dname, {})
        a, b = ours.get("score"), theirs.get("score")
        if a is None or b is None:
            unmeasured.append(dname)
            continue
        delta = float(a) - float(b)
        entry = f"{dname}  ({a:g} vs {b:g}, weight {weights.get(dname, 0):g}%)"
        if delta > 0:
            ahead.append((delta, entry))
        elif delta < 0:
            behind.append((-delta, entry))
    ahead.sort(key=lambda t: -t[0])
    behind.sort(key=lambda t: -t[0])

    cols = [
        (
            "Ahead",
            _ACCENT,
            [entry for _, entry in ahead[:5]] or ["Nowhere yet, on measured dimensions."],
            0.7,
            3.9,
            _BODY,
        ),
        (
            "Behind",
            _PEER,
            [entry for _, entry in behind[:5]] or ["Nowhere, on measured dimensions."],
            4.85,
            3.9,
            _BODY,
        ),
    ]
    for label, label_color, items, x, w, body_color in cols:
        _eyebrow(s, label, y=top, x=x, color=label_color)
        _bullets(
            s,
            x,
            top + 0.35,
            w,
            6.2 - top,
            items,
            size=10.5,
            color=body_color,
            gap_pt=6,
            cap=110,
            accent_bullet=False,
            max_items=7,
        )
    panel = (narrative.get("slides") or {}).get("versus") or {}
    _sidebar(
        s,
        panel.get("observations") or [],
        panel.get("implications") or [],
        top=top,
        x=9.1,
        w=3.5,
    )
    note = (
        "A dimension unscored on either side is listed as not comparable – never counted as a loss."
    )
    if unmeasured:
        note = (
            "Not comparable yet: "
            + ", ".join(unmeasured[:5])
            + (f" +{len(unmeasured) - 5}" if len(unmeasured) > 5 else "")
            + ". "
            + note
        )
    _text(s, 0.7, 6.58, 11.9, 0.46, _clean(note, 220), size=8.5, color=_MUTED)
    _footer(s, deck_title, page)


def _slide_dimension_leaders(
    prs: Any,
    card: dict[str, Any],
    narrative: dict[str, Any],
    page: int,
    deck_title: str,
) -> None:
    """Who leads each battleground: per weighted dimension, the top observed
    score, our score, and the gap — the per-area breakout a steering
    committee expects after the overall standings."""
    from pptx.util import Inches, Pt

    s = _blank(prs)
    title = (narrative.get("titles") or {}).get("dimensions") or "Who leads each dimension"
    top = _header(
        s,
        "The battlegrounds",
        title,
        (narrative.get("commentary") or {}).get("dimensions", ""),
    )
    rows = card.get("rows", [])
    dims = card.get("dimensions", [])[:12]
    us = next((r for r in rows if r.get("is_self")), None)
    if not dims or not rows:
        _text(
            s,
            0.7,
            top + 0.2,
            11.9,
            1.0,
            "Nothing scored yet.",
            size=15,
            color=_BODY,
        )
        _footer(s, deck_title, page)
        return

    def brand_label(r: dict[str, Any]) -> str:
        name = str(r["name"])
        if r.get("is_self"):
            name += " (us)"
        if r.get("provisional") and r["overall"]["normalized_pct"] is not None:
            name += " †"
        return name

    cols = ["Dimension", "Market leader", "Theirs", "Us", "Gap"]
    widths = [2.75, 3.05, 0.65, 0.65, 1.1]
    shape = s.shapes.add_table(
        len(dims) + 1,
        len(cols),
        Inches(0.7),
        Inches(top),
        Inches(sum(widths)),
        Inches(min(0.34 * (len(dims) + 1), 6.55 - top)),
    )
    tbl = shape.table
    for ci, w in enumerate(widths):
        tbl.columns[ci].width = Inches(w)
    # Twelve dimensions and a wide field wrap the leaders cell; the rows
    # fit under the footnote and the long cells are cut to two lines.
    for r_ in tbl.rows:
        r_.height = Inches(min(0.34, (6.2 - top) / (len(dims) + 1)))

    def cell_write(
        r: int,
        c: int,
        text: str,
        *,
        bg: str,
        fg: str = _INK,
        bold: bool = False,
        size: float = 9.5,
    ) -> None:
        cell = tbl.cell(r, c)
        cell.text = text
        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(bg)
        cell.margin_left = cell.margin_right = Inches(0.06)
        cell.margin_top = cell.margin_bottom = Inches(0.02)
        for p_ in cell.text_frame.paragraphs:
            for run in p_.runs:
                run.font.size = Pt(size)
                run.font.bold = bold
                run.font.color.rgb = _rgb(fg)

    for ci, name in enumerate(cols):
        cell_write(0, ci, name, bg=_INK, fg=_WHITE, bold=True, size=10)
    for ri, d in enumerate(dims, start=1):
        dname = d["name"]
        bg = _WHITE if ri % 2 else _CARD
        scored = [
            (r, float(r["dimensions"][dname]["score"]))
            for r in rows
            if r.get("dimensions", {}).get(dname, {}).get("score") is not None
        ]
        cell_write(
            ri,
            0,
            f"{_clean(dname, 40)}  ·  {d.get('weight_pct', 0):g}%",
            bg=bg,
            bold=True,
            size=9,
        )
        if not scored:
            cell_write(ri, 1, "not yet observed", bg=bg, fg=_MUTED)
            cell_write(ri, 2, "", bg=_GAP_BG)
            cell_write(ri, 3, "", bg=_GAP_BG)
            cell_write(ri, 4, "", bg=_GAP_BG)
            continue
        best = max(sc for _, sc in scored)
        leaders = [r for r, sc in scored if sc == best]
        names = ", ".join(brand_label(r) for r in leaders[:2])
        if len(leaders) > 2:
            names += f" +{len(leaders) - 2}"
        we_lead = us is not None and any(r.get("is_self") for r in leaders)
        cell_write(
            ri,
            1,
            _clean(names, 42),
            bg=bg,
            fg=_ACCENT if we_lead else _INK,
            bold=we_lead,
            size=9,
        )
        cell_write(ri, 2, f"{best:g}", bg=bg)
        ours = us.get("dimensions", {}).get(dname, {}).get("score") if us is not None else None
        if us is None:
            cell_write(ri, 3, "—", bg=bg, fg=_MUTED)
            cell_write(ri, 4, "—", bg=bg, fg=_MUTED)
        elif ours is None:
            cell_write(ri, 3, "", bg=_GAP_BG)
            cell_write(ri, 4, "not measured", bg=bg, fg=_MUTED, size=8.5)
        elif we_lead:
            cell_write(ri, 3, f"{float(ours):g}", bg=bg, bold=True)
            others = [sc for r, sc in scored if not r.get("is_self")]
            margin = float(ours) - max(others) if others else None
            label = "we lead" if margin is None or margin > 0 else "we co-lead"
            cell_write(ri, 4, label, bg=bg, fg=_ACCENT, bold=True, size=8.5)
        else:
            delta = float(ours) - best
            cell_write(ri, 3, f"{float(ours):g}", bg=bg)
            cell_write(ri, 4, f"▼ {abs(delta):g} behind", bg=bg, size=8.5)
    panel = (narrative.get("slides") or {}).get("dimensions") or {}
    _sidebar(
        s,
        panel.get("observations") or [],
        panel.get("implications") or [],
        top=top,
        x=9.1,
        w=3.5,
    )
    if len(card.get("dimensions", [])) > len(dims):
        _text(
            s,
            0.7,
            6.6,
            8.2,
            0.3,
            f"First {len(dims)} of {len(card.get('dimensions', []))} dimensions "
            "shown — the rest are in the workbook.",
            size=9,
            color=_MUTED,
        )
    _text(
        s,
        0.7,
        6.85,
        11.9,
        0.25,
        "Top observed score per dimension. † overall standing provisional. "
        "A blank cell is unmeasured – never counted as a loss.",
        size=9,
        color=_MUTED,
    )
    _footer(s, deck_title, page)
    _notes(
        s,
        "Per-dimension leaders use dimension scores directly; a brand whose "
        "OVERALL is provisional can still hold a real top score on one "
        "dimension it was actually measured on — the dagger carries that "
        "context onto the slide.",
    )


def _slide_profile(
    prs: Any,
    row: dict[str, Any],
    profile: dict[str, Any],
    weights: dict[str, float],
    exhibits: list[dict[str, str]],
    page: int,
    deck_title: str,
    voice_brand: dict[str, Any] | None = None,
) -> None:
    """One competitor, one slide: their scores and storefront on the left,
    what they are doing and what it means for us on the right — the
    steering-committee deep-dive pattern."""
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    s = _blank(prs)
    name = row["name"]
    rank = row.get("rank")
    overall = row["overall"]["normalized_pct"]
    standing = f"#{rank}" if rank is not None else "provisional †"
    eyebrow = f"Competitor deep dive · {standing} · overall {_fmt(overall)}"
    title = profile.get("title") or f"{name}"
    top = _header(s, eyebrow, f"{name} – {title}" if title != name else name)

    # Left: the brand's strongest-weighted scored dimensions as 1-5 bars.
    scored = [
        (dname, float(d["score"]))
        for dname, d in row.get("dimensions", {}).items()
        if d.get("score") is not None
    ]
    scored.sort(key=lambda t: -weights.get(t[0], 0.0))
    shown = scored[:5]
    not_observed = [
        dname for dname, d in row.get("dimensions", {}).items() if d.get("score") is None
    ]
    bar_x, bar_w = 0.7, 4.4
    y = top + 0.1
    for dname, score in shown:
        _text(s, bar_x, y, bar_w, 0.26, _clean(dname, 44), size=9.5, color=_BODY)
        track = s.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(bar_x),
            Inches(y + 0.26),
            Inches(bar_w),
            Pt(6),
        )
        track.fill.solid()
        track.fill.fore_color.rgb = _rgb(_GAP_BG)
        track.line.fill.background()
        track.shadow.inherit = False
        fill = s.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(bar_x),
            Inches(y + 0.26),
            Inches(bar_w * max(0.0, min(score, 5.0)) / 5.0),
            Pt(6),
        )
        fill.fill.solid()
        fill.fill.fore_color.rgb = _rgb(_ACCENT if row.get("is_self") else _PEER)
        fill.line.fill.background()
        fill.shadow.inherit = False
        _text(
            s,
            bar_x + bar_w + 0.08,
            y + 0.1,
            0.5,
            0.26,
            f"{score:g}",
            size=9.5,
            bold=True,
        )
        y += 0.52
    if not shown:
        _text(
            s,
            bar_x,
            y,
            bar_w,
            0.8,
            "No dimension scored yet – observations pending.",
            size=11,
            color=_MUTED,
        )
        y += 0.9
    extras: list[str] = []
    if len(scored) > len(shown):
        extras.append(f"+{len(scored) - len(shown)} more scored – see appendix")
    if not_observed:
        more = f" +{len(not_observed) - 3} more" if len(not_observed) > 3 else ""
        extras.append("not observed: " + ", ".join(not_observed[:3]) + more)
    if extras:
        _text(
            s,
            bar_x,
            y + 0.02,
            bar_w + 0.6,
            0.45,
            " · ".join(extras),
            size=8.5,
            color=_MUTED,
        )
        y += 0.45

    # Storefront capture under the bars — fixed slot so it always fits.
    if exhibits:
        shot = exhibits[0]
        shot_y = max(y + 0.15, 4.75)
        max_h = 6.6 - shot_y
        if max_h > 0.7:
            pic = _picture(s, shot["path"], bar_x, shot_y, 2.9, max_h)
            if pic is not None:
                cap = "Storefront capture"
                if shot.get("observed_at"):
                    cap += f" · {str(shot['observed_at'])[:10]}"
                _text(
                    s,
                    bar_x + 3.0,
                    shot_y + 0.05,
                    2.2,
                    0.8,
                    cap,
                    size=8.5,
                    color=_MUTED,
                )

    # Right: observations → implications, model-written from filed facts —
    # and, when players have said enough about this brand, what they say.
    x = 6.1
    has_voice = bool(voice_brand) and not voice_brand.get("too_few") and (voice_brand.get("quotes") or [])
    _eyebrow(s, "Observations", y=top + 0.1, x=x, color=_PEER)
    _bullets(
        s,
        x,
        top + 0.45,
        6.4,
        1.9 if has_voice else 2.9,
        [str(o) for o in profile.get("observations") or []]
        or ["No narrative available – see the workbook for this brand's facts."],
        size=11.5,
        gap_pt=8,
        cap=150,
        accent_bullet=False,
        max_items=3 if has_voice else 4,
    )
    if has_voice:
        _voice_strip(s, voice_brand, x=x, y=top + 2.4, w=6.4)
    imp_y = top + (3.7 if has_voice else 3.3)   # the quote strip is ~1.2in; it used to sit on the heading
    _eyebrow(s, "Implications for us", y=imp_y, x=x, color=_ACCENT)
    _bullets(
        s,
        x,
        imp_y + 0.35,
        6.4,
        6.55 - imp_y - 0.4,
        [str(i) for i in profile.get("implications") or []] or ["Not yet judged."],
        size=11.5,
        gap_pt=8,
        cap=150,
        accent_bullet=False,
        max_items=2,
    )
    _judgement_note(s, "model")
    _footer(s, deck_title, page)
    _notes(
        s,
        "Bars are computed scores (1-5) on the weighted dimensions; blank "
        "means not observed, never zero. Observations and implications are "
        "model-written from this brand's filed facts.",
    )


_VOICE_LABEL = "What players say — sentiment from public posts, not observed product fact."


def _voice_sources(voice: dict[str, Any]) -> str:
    names = {"reddit": "Reddit (r/sweepstakescasinos)", "app_store": "Apple App Store reviews",
             "google_play": "Google Play reviews", "trustpilot": "Trustpilot", "bbb": "BBB", "x": "X", "web": "web"}
    srcs = [names.get(str(x), str(x)) for x in (voice.get("sources") or [])]
    return ", ".join(srcs) if srcs else "none collected"


def _theme_label(theme: str) -> str:
    return {
        "redemption_speed": "Redemption speed",
        "kyc_friction": "KYC friction",
        "support": "Support",
        "fairness_rtp": "Fairness / RTP",
        "promo_value": "Promo value",
        "app_stability": "App stability",
        "account_bans": "Account bans",
        "vip_treatment": "VIP treatment",
        "game_selection": "Game selection",
        "payments": "Payments",
        "other": "Other",
    }.get(theme, theme.replace("_", " ").title())


def _neg_bg(share: float, neg: float) -> str:
    """Cell colour: intensity by share, hue by negative share."""
    if share <= 0:
        return _WHITE
    if neg >= 0.6:
        return "FDE2E2" if share < 0.25 else "F9B4B4"
    if neg <= 0.3:
        return "E3F4E8" if share < 0.25 else "B9E4C7"
    return "F3F4F6" if share < 0.25 else "E5E7EB"


def _slide_voice(
    prs: Any,
    voice: dict[str, Any],
    narrative: dict[str, Any],
    page: int,
    deck_title: str,
) -> None:
    """Brands × themes: the share of each brand's mentions on a theme,
    coloured by how negative they are, with n — and the reading panel.
    Opinion, labelled as such on the slide."""
    from pptx.util import Inches, Pt

    s = _blank(prs)
    title = (narrative.get("titles") or {}).get("voice") or "What players say about the field"
    top = _header(
        s,
        f"What players say · {voice.get('window_days', 30)}-day window",
        title,
        (narrative.get("commentary") or {}).get("voice", ""),
    )
    brands = sorted(
        voice.get("brands", []),
        key=lambda b: (not b.get("is_self"), b.get("too_few", False), -b.get("n", 0)),
    )[:14]
    themes = [
        t
        for t, v in sorted(
            (voice.get("field_themes") or {}).items(), key=lambda kv: -kv[1]["share"]
        )
        if t != "other"
    ][:8]
    if not brands or not themes:
        _text(s, 0.7, top + 0.2, 8.0, 1.0, "Nothing collected yet.", size=15, color=_BODY)
        _footer(s, deck_title, page)
        return
    total_w = 8.2
    first_w = 1.9
    n_w = 0.75
    th_w = (total_w - first_w - n_w) / len(themes)
    # The legend under the table is what makes it readable; with fifteen
    # brands the rows shrink so the table ends above it (2026-08-30 pack:
    # the table ran over the legend and the reader asked for the source).
    row_h = min(0.3, (6.15 - top) / (len(brands) + 1))
    shape = s.shapes.add_table(
        len(brands) + 1,
        2 + len(themes),
        Inches(0.7),
        Inches(top),
        Inches(total_w),
        Inches(row_h * (len(brands) + 1)),
    )
    tbl = shape.table
    for r_ in tbl.rows:
        r_.height = Inches(row_h)
    tbl.columns[0].width = Inches(first_w)
    tbl.columns[1].width = Inches(n_w)
    for ci in range(len(themes)):
        tbl.columns[2 + ci].width = Inches(th_w)

    def cell_write(r: int, c: int, text: str, *, bg: str, fg: str = _INK, bold: bool = False, size: int = 8) -> None:
        cell = tbl.cell(r, c)
        cell.text = text
        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(bg)
        cell.margin_left = cell.margin_right = Inches(0.03)
        cell.margin_top = cell.margin_bottom = Inches(0.01)
        for p in cell.text_frame.paragraphs:
            for run in p.runs:
                run.font.size = Pt(size)
                run.font.bold = bold
                run.font.color.rgb = _rgb(fg)

    cell_write(0, 0, "Brand", bg=_INK, fg=_WHITE, bold=True)
    cell_write(0, 1, "n", bg=_INK, fg=_WHITE, bold=True)
    for ci, t in enumerate(themes):
        cell_write(0, 2 + ci, _theme_label(t), bg=_INK, fg=_WHITE, bold=True, size=7)
    for ri, b in enumerate(brands, start=1):
        bg = _SELF_ROW if b.get("is_self") else _WHITE
        cell_write(ri, 0, f"{b['name']}{'  (us)' if b.get('is_self') else ''}", bg=bg, bold=bool(b.get("is_self")))
        cell_write(ri, 1, str(b.get("n", 0)), bg=bg)
        if b.get("too_few"):
            # short, so a 0.7in column keeps the row to one line (15 brands, 2026-09-02)
            cell_write(ri, 2, f"too few (n<{voice.get('min_mentions', 15)})", bg=_GAP_BG, fg=_MUTED, size=7)
            for ci in range(1, len(themes)):
                cell_write(ri, 2 + ci, "", bg=_GAP_BG)
            continue
        for ci, t in enumerate(themes):
            cell = (b.get("themes") or {}).get(t)
            if not cell:
                cell_write(ri, 2 + ci, "", bg=bg)
                continue
            share = float(cell.get("share", 0.0))
            neg = float(cell.get("neg_share", 0.0))
            n_t = cell.get("n")
            cell_write(
                ri, 2 + ci, f"{int(round(share * 100))}%" + (f" ({int(n_t)})" if n_t else ""),
                bg=_neg_bg(share, neg), fg=_INK, bold=share >= 0.25, size=7 if len(brands) > 10 else 8,
            )
    panel = (narrative.get("slides") or {}).get("voice") or _voice_facts(voice)
    _sidebar(
        s,
        [str(o) for o in panel.get("observations") or []],
        [str(i) for i in panel.get("implications") or []],
        top=top,
    )
    _text(
        s, 0.7, 6.22, 11.9, 0.5,
        f"How to read: n = public posts about the brand in the last {voice.get('window_days', 30)} days; a cell is "
        "the share of those posts about that theme, with the count in brackets; red = mostly negative, green = "
        f"mostly positive, grey = fewer than {voice.get('min_mentions', 15)} posts, too few to read. "
        f"Sources: {_voice_sources(voice)}. {_VOICE_LABEL}",
        size=8, italic=True, color=_MUTED,
    )
    _judgement_note(s, str(narrative.get("source") or "facts"))
    _footer(s, deck_title, page)


def _slide_voice_changes(
    prs: Any,
    vdiff: dict[str, Any] | None,
    narrative: dict[str, Any],
    page: int,
    deck_title: str,
) -> None:
    """Rising and falling themes since the last cycle."""
    s = _blank(prs)
    commentary = (narrative.get("commentary") or {}).get("voice_changes", "")
    if not vdiff or vdiff.get("baseline"):
        top = _header(s, "What players say · movement", "Sentiment baseline set", commentary)
        _text(
            s, 0.7, top, 11.9, 0.9,
            "First cycle with voice of customer collected. There is no prior reading to compare "
            "against; the next cycle shows which themes rose and fell.",
            size=13, color=_BODY,
        )
        _footer(s, deck_title, page)
        return
    n = int(vdiff.get("material_count", 0))
    title = (narrative.get("titles") or {}).get("voice_changes") or (
        f"{n} theme{'s' if n != 1 else ''} moved this cycle" if n else "No theme moved materially"
    )
    top = _header(s, "What players say · movement", title, commentary)
    lines = []
    for c in vdiff.get("changed", [])[:8]:
        arrow = "▲" if c["direction"] == "rising" else "▼"
        lines.append(
            f"{arrow} {c['brand']}{'  (us)' if c.get('is_self') else ''} – {_theme_label(c['theme'])}: "
            f"{int(round(c['share_from'] * 100))}% → {int(round(c['share_to'] * 100))}% of mentions, "
            f"{int(round(c['neg_from'] * 100))}% → {int(round(c['neg_to'] * 100))}% negative "
            f"(n {c['n_from']} → {c['n_to']})"
        )
    _bullets(s, 0.7, top, 11.9, 6.2 - top, lines or ["Nothing moved past the reporting threshold."],
             size=11.5, color=_INK, gap_pt=7, cap=200, accent_bullet=True, max_items=8)
    _text(s, 0.7, 6.32, 11.9, 0.3, _VOICE_LABEL, size=8, italic=True, color=_MUTED)
    _footer(s, deck_title, page)


def _voice_strip(slide: Any, vb: dict[str, Any], *, x: float, y: float, w: float) -> None:
    """Three lines under a deep dive: what players say about this brand."""
    _eyebrow(slide, f"What players say · n={vb.get('n', 0)}", y=y, x=x, color=_PEER)
    quotes = vb.get("quotes") or []
    lines = []
    for q in quotes[:2]:
        lines.append(f"“{_clean(q.get('quote', ''), 120)}” — {q.get('source', '')}, {q.get('posted_at', '')}")
    meta = []
    if vb.get("top_complaint"):
        meta.append(f"top complaint {_theme_label(vb['top_complaint']).lower()}")
    if vb.get("top_praise"):
        meta.append(f"top praise {_theme_label(vb['top_praise']).lower()}")
    if vb.get("flags"):
        meta.append("players flag " + ", ".join(vb["flags"][:2]))
    if meta:
        lines.append(" · ".join(meta))
    _bullets(slide, x, y + 0.3, w, 0.95, lines, size=9.5, color=_BODY, gap_pt=3, cap=170,
             accent_bullet=False, max_items=3)


_COMMS_LABEL = "What brands send players — marketing e-mail received in the organ's own inboxes."


def _cat_label(c: str) -> str:
    return {
        "welcome": "Welcome",
        "promo_offer": "Promo offer",
        "daily_bonus": "Daily bonus",
        "reactivation": "Reactivation",
        "vip_loyalty": "VIP / loyalty",
        "tournament_event": "Tournament / event",
        "product_news": "Product news",
        "transactional": "Transactional",
        "other": "Other",
    }.get(c, c.replace("_", " ").title())


def _slide_comms(
    prs: Any,
    comms: dict[str, Any],
    narrative: dict[str, Any],
    page: int,
    deck_title: str,
) -> None:
    """Brands × categories: e-mails sent in the window, cadence per week,
    the latest offer line — first-party, dated, from our own inboxes."""
    from pptx.util import Inches, Pt

    s = _blank(prs)
    title = (narrative.get("titles") or {}).get("comms") or "What they send players"
    top = _header(
        s,
        f"Player comms · {comms.get('window_days', 30)}-day window",
        title,
        (narrative.get("commentary") or {}).get("comms", ""),
    )
    brands = sorted(
        [b for b in comms.get("brands", []) if b.get("inbox")],
        key=lambda b: (not b.get("is_self"), -b.get("n", 0)),
    )[:14]
    cats = [c for c in ("welcome", "promo_offer", "daily_bonus", "reactivation", "vip_loyalty",
                        "tournament_event", "product_news")]
    if not brands:
        _text(s, 0.7, top + 0.2, 8.0, 1.0, "No inbox linked yet.", size=15, color=_BODY)
        _footer(s, deck_title, page)
        return
    total_w = 8.2
    first_w, n_w, wk_w = 1.9, 0.6, 0.7
    c_w = (total_w - first_w - n_w - wk_w) / len(cats)
    shape = s.shapes.add_table(len(brands) + 1, 3 + len(cats), Inches(0.7), Inches(top), Inches(total_w),
                               Inches(min(0.3 * (len(brands) + 1), 6.2 - top)))
    tbl = shape.table
    tbl.columns[0].width = Inches(first_w)
    tbl.columns[1].width = Inches(n_w)
    tbl.columns[2].width = Inches(wk_w)
    for ci in range(len(cats)):
        tbl.columns[3 + ci].width = Inches(c_w)

    def cw(r: int, c: int, text: str, *, bg: str, fg: str = _INK, bold: bool = False, size: int = 8) -> None:
        cell = tbl.cell(r, c)
        cell.text = text
        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(bg)
        cell.margin_left = cell.margin_right = Inches(0.03)
        cell.margin_top = cell.margin_bottom = Inches(0.01)
        for p in cell.text_frame.paragraphs:
            for run in p.runs:
                run.font.size = Pt(size)
                run.font.bold = bold
                run.font.color.rgb = _rgb(fg)

    cw(0, 0, "Brand", bg=_INK, fg=_WHITE, bold=True)
    cw(0, 1, "n", bg=_INK, fg=_WHITE, bold=True)
    cw(0, 2, "/week", bg=_INK, fg=_WHITE, bold=True)
    for ci, c in enumerate(cats):
        cw(0, 3 + ci, _cat_label(c), bg=_INK, fg=_WHITE, bold=True, size=7)
    for ri, b in enumerate(brands, start=1):
        bg = _SELF_ROW if b.get("is_self") else _WHITE
        cw(ri, 0, f"{b['name']}{'  (us)' if b.get('is_self') else ''}", bg=bg, bold=bool(b.get("is_self")))
        cw(ri, 1, str(b.get("n", 0)), bg=bg)
        cw(ri, 2, f"{b.get('per_week', 0):g}", bg=bg)
        for ci, c in enumerate(cats):
            n = int((b.get("categories") or {}).get(c, 0))
            cw(ri, 3 + ci, str(n) if n else "", bg=("E5E7EB" if n >= 4 else bg))
    panel = (narrative.get("slides") or {}).get("comms") or _comms_facts(comms)
    _sidebar(s, [str(o) for o in panel.get("observations") or []],
             [str(i) for i in panel.get("implications") or []], top=top)
    _text(s, 0.7, 6.32, 11.9, 0.3,
          f"{_COMMS_LABEL} Counts are e-mails received in the window; /week is the cadence. "
          "Brands without a linked inbox are not shown.", size=8, italic=True, color=_MUTED)
    _judgement_note(s, str(narrative.get("source") or "facts"))
    _footer(s, deck_title, page)


def _comms_facts(comms: dict[str, Any] | None) -> dict[str, list[str]]:
    if not comms or not comms.get("emails"):
        return {"observations": [], "implications": []}
    brands = [b for b in comms.get("brands", []) if b.get("inbox") and b.get("n")]
    obs: list[str] = []
    imps: list[str] = []
    obs.append(
        f"{comms['emails']} marketing e-mails received from {len(brands)} brands in "
        f"{comms.get('window_days', 30)} days."
    )
    if brands:
        busiest = max(brands, key=lambda b: b.get("per_week", 0))
        obs.append(f"{busiest['name']} sends most: {busiest['per_week']:g} e-mails a week.")
        cat_tot: dict[str, int] = {}
        for b in brands:
            for c, n in (b.get("categories") or {}).items():
                cat_tot[c] = cat_tot.get(c, 0) + n
        if cat_tot:
            top = max(cat_tot.items(), key=lambda kv: kv[1])
            obs.append(f"Most common message type field-wide: {_cat_label(top[0]).lower()} ({top[1]}).")
        us = next((b for b in brands if b.get("is_self")), None)
        if us:
            obs.append(f"We send {us['per_week']:g} a week; peak hour {us.get('peak_hour_utc')} UTC.")
        with_offers = [b for b in brands if b.get("latest_offers")]
        if with_offers:
            b0 = with_offers[0]
            imps.append(f"Latest offer seen — {b0['name']}: {b0['latest_offers'][0]['offer']}.")
    imps.append("Cadence and mix are what players actually receive; compare against our own send plan.")
    return {"observations": obs[:4], "implications": imps[:3]}
def _slide_regulatory(
    prs: Any,
    cal: dict[str, Any],
    narrative: dict[str, Any],
    page: int,
    deck_title: str,
) -> None:
    """The regulatory calendar: dated items ahead, recent actions, operator
    responses. Third-party items with verified excerpts; not legal advice."""
    from pptx.util import Inches, Pt

    s = _blank(prs)
    title = (narrative.get("titles") or {}).get("regulatory") or (
        f"{len(cal.get('ahead') or [])} regulatory date{'s' if len(cal.get('ahead') or []) != 1 else ''} "
        f"in the next {cal.get('horizon_days', 90)} days"
    )
    top = _header(s, "Regulatory calendar", title, (narrative.get("commentary") or {}).get("regulatory", ""))
    ahead = (cal.get("ahead") or [])[:9]
    if ahead:
        shape = s.shapes.add_table(len(ahead) + 1, 5, Inches(0.7), Inches(top), Inches(8.2),
                                   Inches(min(0.32 * (len(ahead) + 1), 3.6)))
        tbl = shape.table
        for ci, w in enumerate((1.0, 0.8, 1.2, 4.0, 1.2)):
            tbl.columns[ci].width = Inches(w)

        def cw(r: int, c: int, text: str, *, bg: str, fg: str = _INK, bold: bool = False, size: int = 8) -> None:
            cell = tbl.cell(r, c)
            cell.text = text
            cell.fill.solid()
            cell.fill.fore_color.rgb = _rgb(bg)
            cell.margin_left = cell.margin_right = Inches(0.03)
            cell.margin_top = cell.margin_bottom = Inches(0.01)
            for p in cell.text_frame.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(size)
                    run.font.bold = bold
                    run.font.color.rgb = _rgb(fg)

        for ci, h in enumerate(("Date", "Where", "Kind", "Item", "Status")):
            cw(0, ci, h, bg=_INK, fg=_WHITE, bold=True)
        for ri, i in enumerate(ahead, start=1):
            bg = _CARD if ri % 2 else _WHITE
            cw(ri, 0, i.get("event_date", ""), bg=bg, bold=True)
            cw(ri, 1, i.get("jurisdiction", ""), bg=bg)
            cw(ri, 2, str(i.get("kind", "")).replace("_", " "), bg=bg)
            cw(ri, 3, _clean(i.get("title", ""), 90), bg=bg)
            cw(ri, 4, i.get("status", ""), bg=bg)
        y = top + min(0.32 * (len(ahead) + 1), 3.6) + 0.2
    else:
        _text(s, 0.7, top, 8.2, 0.5, "No dated item inside the horizon.", size=12, color=_BODY)
        y = top + 0.7
    acts = (cal.get("recent_actions") or [])[:4]
    if acts:
        _eyebrow(s, "Enforcement and lawsuits · last 30 days", y=y, x=0.7, color=_ACCENT)
        _bullets(s, 0.7, y + 0.32, 8.2, max(0.6, 6.2 - (y + 0.32)),
                 [f"{a['jurisdiction']} · {a['kind']}: {_clean(a['title'], 110)}" for a in acts],
                 size=10, color=_BODY, gap_pt=4, cap=150, accent_bullet=True, max_items=4)
    panel = (narrative.get("slides") or {}).get("regulatory") or _regulatory_facts(cal)
    _sidebar(s, [str(o) for o in panel.get("observations") or []],
             [str(i) for i in panel.get("implications") or []], top=top)
    _text(s, 0.7, 6.32, 11.9, 0.3,
          f"{cal.get('label', '')} Every item carries a source URL and a verified excerpt.",
          size=8, italic=True, color=_MUTED)
    _judgement_note(s, str(narrative.get("source") or "facts"))
    _footer(s, deck_title, page)


def _regulatory_facts(cal: dict[str, Any] | None) -> dict[str, list[str]]:
    if not cal or not cal.get("total"):
        return {"observations": [], "implications": []}
    obs: list[str] = []
    imps: list[str] = []
    ahead = cal.get("ahead") or []
    obs.append(f"{cal['total']} regulatory items on record across {len(cal.get('by_jurisdiction') or {})} jurisdictions.")
    if ahead:
        n0 = ahead[0]
        obs.append(f"Next dated item: {n0['jurisdiction']} {n0['kind'].replace('_', ' ')} on {n0['event_date']} — {n0['title']}.")
        imps.append(f"Decide the {n0['jurisdiction']} plan before {n0['event_date']}.")
    acts = cal.get("recent_actions") or []
    if acts:
        obs.append(f"{len(acts)} enforcement/lawsuit item{'s' if len(acts) != 1 else ''} observed in the last 30 days.")
    resp = cal.get("operator_responses") or []
    if resp:
        obs.append(f"{len(resp)} operator response{'s' if len(resp) != 1 else ''} on record (who left which state, when).")
    imps.append("Third-party items with verified excerpts — route legal interpretation to counsel.")
    return {"observations": obs[:4], "implications": imps[:3]}


def _slide_trends(
    prs: Any,
    trends: dict[str, Any],
    card: dict[str, Any],
    narrative: dict[str, Any],
    page: int,
    deck_title: str,
) -> None:
    """Overall score per brand across the stored cycles — a line chart, our
    brands in the accent colour, the leader and top peers in slate."""
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
    from pptx.util import Inches, Pt

    s = _blank(prs)
    pts = trends.get("points") or []
    title = (narrative.get("titles") or {}).get("trends") or f"Scores over {len(pts)} collection runs"
    top = _header(s, "Trends", title, (narrative.get("commentary") or {}).get("trends", ""))
    rows = card.get("rows", [])
    us = [r["name"] for r in rows if r.get("is_self")]
    ranked = sorted(
        [r for r in rows if r["overall"]["normalized_pct"] is not None and not r.get("is_self")],
        key=lambda r: -float(r["overall"]["normalized_pct"]),
    )
    shown = us + [r["name"] for r in ranked[:5]]
    cd = CategoryChartData()
    cd.categories = [pt["taken_at"] for pt in pts]
    for name in shown:
        cd.add_series(name, [pt["scores"].get(name) for pt in pts])
    gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(0.7), Inches(top), Inches(8.2), Inches(6.2 - top), cd)
    ch = gf.chart
    ch.has_legend = True
    ch.legend.position = XL_LEGEND_POSITION.BOTTOM
    ch.legend.include_in_layout = False
    ch.legend.font.size = Pt(9)
    ch.value_axis.maximum_scale = 100
    ch.value_axis.minimum_scale = 0
    ch.value_axis.tick_labels.font.size = Pt(9)
    ch.category_axis.tick_labels.font.size = Pt(9)
    for i, name in enumerate(shown):
        ser = ch.series[i]
        ser.smooth = False
        ser.format.line.color.rgb = _rgb(_ACCENT if name in us else _PEER)
        ser.format.line.width = Pt(2.25 if name in us else 1.25)
    panel = (narrative.get("slides") or {}).get("trends") or _trends_facts(trends, us)
    _sidebar(s, [str(o) for o in panel.get("observations") or []],
             [str(i) for i in panel.get("implications") or []], top=top)
    _text(s, 0.7, 6.32, 11.9, 0.3,
          "Each point is one run – a date on which every brand's pages were read. The line is the brand's "
          "overall score (0–100) that day; a gap means the brand was not read that run.",
          size=8, italic=True, color=_MUTED)
    _footer(s, deck_title, page)


def _trends_facts(trends: dict[str, Any], us: list[str]) -> dict[str, list[str]]:
    """Plain reading of the trend lines. A brand's move is from its first
    scored run to its latest — many brands are not scored at the first
    run at all — and one mover is reported as one mover, not as both the
    biggest riser and the biggest faller (2026-08-30 pack)."""
    pts = trends.get("points") or []
    if len(pts) < 2:
        return {"observations": [], "implications": []}
    obs: list[str] = [f"{len(pts)} collection runs from {pts[0]['taken_at']} to {pts[-1]['taken_at']}."]
    moves: list[tuple[str, float, float, float, int]] = []
    for b in trends.get("brands", []):
        scored = [float(pt["scores"][b]) for pt in pts if pt.get("scores", {}).get(b) is not None]
        if len(scored) >= 2:
            moves.append((b, scored[0], scored[-1], scored[-1] - scored[0], len(scored)))

    def fmt(m: tuple[str, float, float, float, int]) -> str:
        return f"{m[0]}: {m[1]:.1f} → {m[2]:.1f} ({m[3]:+.1f})"

    if not moves:
        obs.append("No brand has a score at two different runs yet, so nothing has moved.")
    elif len(moves) == 1:
        obs.append(f"Only one brand was scored at two runs – {fmt(moves[0])}.")
    else:
        up = max(moves, key=lambda m: m[3])
        down = min(moves, key=lambda m: m[3])
        obs.append(f"Largest rise – {fmt(up)}." if up[3] > 0 else "No brand rose between its first and latest score.")
        if down is not up:
            obs.append(f"Largest fall – {fmt(down)}." if down[3] < 0 else "No brand fell.")
    for u in us:
        m = next((x for x in moves if x[0] == u), None)
        if m:
            obs.append(f"{u}: {m[1]:.1f} → {m[2]:.1f} ({m[3]:+.1f}) across {m[4]} runs.")
    return {
        "observations": obs[:4],
        "implications": [
            "A jump usually means we read more of a brand's pages that run, not that the brand changed; "
            "flat lines mean its pages did not change.",
        ],
    }

def _slide_calendar(prs: Any, cal: dict[str, Any], page: int, deck_title: str) -> None:
    """The next eight weeks of dates that move play, week by week."""
    from pptx.util import Inches, Pt

    s = _blank(prs)
    top = _header(s, "Demand calendar", f"The next {len(cal.get('weeks') or [])} weeks")
    weeks = (cal.get("weeks") or [])[:8]
    if not weeks:
        _footer(s, deck_title, page)
        return
    shape = s.shapes.add_table(len(weeks) + 1, 2, Inches(0.7), Inches(top), Inches(11.9), Inches(min(0.5 * (len(weeks) + 1), 6.2 - top)))
    tbl = shape.table
    tbl.columns[0].width = Inches(2.2)
    tbl.columns[1].width = Inches(9.7)

    def cw(r: int, c: int, text: str, *, bg: str, fg: str = _INK, bold: bool = False, size: int = 9) -> None:
        cell = tbl.cell(r, c)
        cell.text = text
        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(bg)
        cell.margin_left = cell.margin_right = Inches(0.05)
        cell.margin_top = cell.margin_bottom = Inches(0.02)
        for p in cell.text_frame.paragraphs:
            for run in p.runs:
                run.font.size = Pt(size)
                run.font.bold = bold
                run.font.color.rgb = _rgb(fg)

    cw(0, 0, "Week of", bg=_INK, fg=_WHITE, bold=True)
    cw(0, 1, "Dates that move play", bg=_INK, fg=_WHITE, bold=True)
    for ri, w in enumerate(weeks, start=1):
        bg = _CARD if ri % 2 else _WHITE
        cw(ri, 0, w["week_of"], bg=bg, bold=True)
        cw(ri, 1, " · ".join(f"{i['date'][5:]} {i['label']}" for i in w["items"]) or "—", bg=bg)
    _text(s, 0.7, 6.32, 11.9, 0.3, _clean(cal.get("note", ""), 200), size=8, italic=True, color=_MUTED)
    _footer(s, deck_title, page)


def _slide_tone(prs: Any, tone: dict[str, Any], narrative: dict[str, Any], page: int, deck_title: str) -> None:
    """How each brand talks to players: measured habits, then the voice,
    with a line of its own to prove it."""
    from pptx.util import Inches, Pt

    s = _blank(prs)
    rows = tone.get("brands", [])[:14]
    title = (narrative.get("titles") or {}).get("tone") or (
        f"{tone.get('loudest', '')} shouts loudest; {tone.get('most_urgent', '')} pushes hardest"
        if tone.get("loudest") and tone.get("most_urgent")
        else "How the field talks to players"
    )
    top = _header(s, "Tone of voice", title, (narrative.get("commentary") or {}).get("tone", ""))
    if not rows:
        _footer(s, deck_title, page)
        return
    shape = s.shapes.add_table(
        len(rows) + 1, 6, Inches(0.7), Inches(top), Inches(11.9),
        Inches(min(0.34 * (len(rows) + 1), 5.9 - top)),
    )
    tbl = shape.table
    for ci, w in enumerate((1.9, 1.9, 0.8, 0.9, 0.9, 5.5)):
        tbl.columns[ci].width = Inches(w)

    def cw(r: int, c: int, text: str, *, bg: str, fg: str = _INK, bold: bool = False, size: int = 8) -> None:
        cell = tbl.cell(r, c)
        cell.text = text
        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(bg)
        cell.margin_left = cell.margin_right = Inches(0.04)
        cell.margin_top = cell.margin_bottom = Inches(0.01)
        for p in cell.text_frame.paragraphs:
            for run in p.runs:
                run.font.size = Pt(size)
                run.font.bold = bold
                run.font.color.rgb = _rgb(fg)

    for ci, h in enumerate(("Brand", "Voice", "CAPS", "!/line", "Urgency", "In its own words")):
        cw(0, ci, h, bg=_INK, fg=_WHITE, bold=True)
    for ri, b in enumerate(rows, start=1):
        bg = _SELF_ROW if b["is_self"] else (_CARD if ri % 2 else _WHITE)
        f = b["features"]
        cw(ri, 0, f"{b['name']}{'  (us)' if b['is_self'] else ''}", bg=bg, bold=b["is_self"])
        cw(ri, 1, _clean(b.get("register") or "—", 26), bg=bg)
        cw(ri, 2, f"{f.get('caps_pct', 0):g}%", bg=bg)
        cw(ri, 3, f"{f.get('exclaims_per_line', 0):g}", bg=bg)
        cw(ri, 4, f"{f.get('urgency_per_100w', 0):g}", bg=bg)
        line = b.get("signature") or (b["quotes"][0]["text"] if b.get("quotes") else "")
        cw(ri, 5, f"“{_clean(line, 90)}”" if line else "", bg=bg, size=7.5)
    _text(
        s, 0.7, 6.32, 11.9, 0.32,
        f"{tone.get('label', '')} CAPS = share of words in capitals, Urgency = urgency words per "
        "100 words; both measured, not judged. Quotes are verbatim from the brand's own pages "
        "and e-mails.",
        size=8, italic=True, color=_MUTED,
    )
    _judgement_note(s, str(tone.get("source") or "facts"))
    _footer(s, deck_title, page)


def _table(
    slide: Any, x: float, y: float, widths: list[float], header: list[str],
    rows: list[list[str]], *, size: float = 8, highlight_first_col: bool = False,
    max_h: float = 4.6, links: list[str] | None = None,
) -> float:
    """A plain, readable table in the deck's style. Returns the y below it.
    The client's reference pages are exactly this: bordered cells, one
    fact per cell, nothing decorative."""
    from pptx.util import Inches, Pt

    if not rows:
        return y
    row_h = 0.34 if size >= 9 else 0.3
    h = min(row_h * (len(rows) + 1), max_h)
    shape = slide.shapes.add_table(len(rows) + 1, len(header), Inches(x), Inches(y),
                                   Inches(sum(widths)), Inches(h))
    tbl = shape.table
    for ci, w in enumerate(widths):
        tbl.columns[ci].width = Inches(w)

    def cw(r: int, c: int, text: str, *, bg: str, fg: str = _INK, bold: bool = False) -> None:
        cell = tbl.cell(r, c)
        cell.text = text
        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(bg)
        cell.margin_left = cell.margin_right = Inches(0.05)
        cell.margin_top = cell.margin_bottom = Inches(0.02)
        for p_ in cell.text_frame.paragraphs:
            for run in p_.runs:
                run.font.size = Pt(size)
                run.font.bold = bold
                run.font.color.rgb = _rgb(fg)

    for ci, htxt in enumerate(header):
        cw(0, ci, htxt, bg=_INK, fg=_WHITE, bold=True)
    for ri, row in enumerate(rows, start=1):
        bg = _CARD if ri % 2 else _WHITE
        for ci, txt in enumerate(row):
            cw(ri, ci, txt, bg=bg, bold=(highlight_first_col and ci == 0))
        url = (links[ri - 1] if links and ri - 1 < len(links) else "") or ""
        if url.startswith("http"):
            # "add a link" (client, 2026-08-31): the name opens the page it was read from
            try:
                tbl.cell(ri, 0).text_frame.paragraphs[0].runs[0].hyperlink.address = url
            except Exception:
                pass
    return y + h + 0.15


def _fmt_coins(v: Any) -> str:
    if v is None:
        return "–"
    try:
        f = float(v)
    except Exception:
        return str(v)
    return f"{int(f):,}" if f == int(f) else f"{f:,.2f}"


def _slide_brand_coins_promos(prs: Any, brand: dict[str, Any], page: int, deck_title: str) -> None:
    """'<Brand> – Coins / Promotions': the ladder as Package · Gold coins ·
    Sweeps coins · Description on the left, promotions as Promotion ·
    Benefit · How to claim · Frequency on the right — the client's own
    reference layout. Names link to the page they were read from."""
    s = _blank(prs)
    c = brand["counts"]
    top = _header(
        s, "Raw data",
        f"{brand['name']}{'  (us)' if brand.get('is_self') else ''} – Coins / Promotions",
    )
    pkgs = brand.get("packages") or []
    pkg_rows: list[list[str]] = []
    pkg_links: list[str] = []
    for pkg in pkgs[:10]:
        price = f"${pkg['price_usd']:.2f}" if pkg.get("price_usd") is not None else str(pkg["name"])
        gc, sc = pkg.get("gold_coins"), pkg.get("sweeps_coins")
        if gc is None and sc is None and pkg.get("coins"):
            gc_txt, sc_txt = _clean(pkg["coins"], 30), "–"   # unparsed grant, shown as printed
        else:
            gc_txt, sc_txt = _fmt_coins(gc), _fmt_coins(sc)
        pkg_rows.append([price, gc_txt, sc_txt, _clean((pkg.get("detail") or "").strip(), 44) or "–"])
        pkg_links.append(str(pkg.get("url") or ""))
    if pkg_rows:
        _table(s, 0.7, top, [0.95, 1.0, 0.9, 1.55],
               ["Coin package", "Gold coins", "Sweeps coins", "Description"],
               pkg_rows, size=8, highlight_first_col=True, links=pkg_links)
    else:
        _text(s, 0.7, top, 4.4, 1.0,
              "Coin store not read yet – it sits behind a login and nothing public lists this brand's "
              "packages. A signed-in read is the next step.",
              size=9, color=_MUTED, line=1.15)

    promos = brand.get("promotions_full") or brand.get("promotions") or []
    promo_rows: list[list[str]] = []
    promo_links: list[str] = []
    for p_ in promos[:9]:
        benefit = p_.get("benefit") or p_.get("detail") or ""
        promo_rows.append([
            _clean(p_["name"], 48),      # the cell wraps; a title cut mid-word reads worse than two lines
            _clean(benefit, 95) or "–",
            _clean(p_.get("how_to_claim") or "", 60) or "–",
            _clean(p_.get("frequency") or "", 16) or "–",
        ])
        promo_links.append(str(p_.get("url") or ""))
    if promo_rows:
        _table(s, 5.3, top, [1.55, 3.05, 1.75, 0.85],
               ["Promotion", "Benefit", "How to claim", "Frequency"], promo_rows, size=7.5, links=promo_links)
    else:
        _text(s, 5.3, top, 7.2, 0.5, "No promotions on record.", size=9, color=_MUTED)
    extra = max(0, len(pkgs) - 10) + max(0, len(promos) - 9)
    pkg_src = (brand.get("sources") or {}).get("coin_package") or []
    if pkg_rows and pkg_src == ["third_party"]:
        # a ladder read off a review site is a weaker fact than one read off the store — say so
        provenance = "Packages as reported by public reviews, not read off the store (it sits behind a login). "
    elif pkg_rows and "third_party" in pkg_src:
        provenance = "Packages read off the store and from public reviews; the workbook says which. "
    elif pkg_rows:
        provenance = "Packages as priced on the store. "
    else:
        provenance = ""
    _text(s, 0.7, 6.6, 11.9, 0.44,
        f"{c.get('coin_package', 0)} packages and {c.get('promotion', 0)} promotions on record"
        + (f"; {extra} more in the workbook" if extra else "")
        + f". {provenance}As printed; click a name to open the page it was read from. Read "
        f"{', '.join(brand.get('customer_states') or ['logged_out'])}, latest {brand.get('observed_at', '')}.",
        size=7.5, italic=True, color=_MUTED,
    )
    _footer(s, deck_title, page)


def _slide_brand_loyalty(prs: Any, brand: dict[str, Any], page: int, deck_title: str) -> None:
    """'<Brand> – Loyalty Club': Tier · Qualification · Reward."""
    s = _blank(prs)
    tiers = brand.get("tiers") or []
    top = _header(
        s, "Raw data",
        f"{brand['name']}{'  (us)' if brand.get('is_self') else ''} – Loyalty Club",
    )
    rows = [[_clean(t["name"], 22), _clean(t.get("qualification") or "–", 60),
             _clean(t.get("reward") or "–", 90)] for t in tiers[:12]]
    _table(s, 0.7, top, [2.2, 4.2, 5.5], ["Loyalty Club tier", "Qualification", "Reward"],
           rows, size=8.5, highlight_first_col=True, max_h=5.0)
    _text(s, 0.7, 6.6, 11.9, 0.44,
          f"{len(tiers)} tiers as printed; latest {brand.get('observed_at', '')}.",
          size=7.5, italic=True, color=_MUTED)
    _footer(s, deck_title, page)


def _slide_brand_library(prs: Any, brand: dict[str, Any], page: int, deck_title: str) -> None:
    """'<Brand> – Providers / Games': every studio carried and the titles read."""
    s = _blank(prs)
    c = brand["counts"]
    top = _header(
        s, "Raw data",
        f"{brand['name']}{'  (us)' if brand.get('is_self') else ''} – Providers / Games",
    )

    def more(items: list[Any], shown: int) -> str:
        extra = len(items) - shown
        return f"  (+{extra} more in the workbook)" if extra > 0 else ""

    provs = [str(p_) for p_ in brand.get("providers") or []]
    _eyebrow(s, f"Game providers carried · {c.get('provider', 0)}", y=top, x=0.7, color=_PEER)
    _text(s, 0.7, top + 0.26, 11.9, 1.9,
          (", ".join(provs[:60]) + more(provs, 60)) if provs else "—", size=8, color=_BODY, line=1.15)
    games = [str(g) for g in brand.get("games_full") or brand.get("games_sample") or []]
    _eyebrow(s, f"Games read · {c.get('game', 0)}", y=top + 2.35, x=0.7, color=_PEER)
    games_h = 6.5 - (top + 2.61) - (0.45 if len(games) < 10 else 0.05)
    if games:
        _text(s, 0.7, top + 2.61, 11.9, games_h,
              ", ".join(games[:110]) + more(games, 110), size=7.5, color=_BODY, line=1.12)
    if len(games) < 10:
        # "the games lists are too short" (client, 2026-08-31): say why, not just how many
        _text(s, 0.7, top + 2.61 + (games_h if games else 0.0), 11.9, 0.42,
              (f"Only {len(games)} title{'s' if len(games) != 1 else ''} appeared" if games
               else "No titles appeared") + " on the public pages and reviews. "
              "The full lobby sits behind a login and has not been read as a signed-in player yet.",
              size=8, italic=True, color=_MUTED)
    _text(s, 0.7, 6.6, 11.9, 0.44,
          "As printed on the brand's pages and public reviews; the source of every item is in the workbook.",
          size=7.5, italic=True, color=_MUTED)
    _footer(s, deck_title, page)


def _slides_portfolio(prs: Any, catalog: dict[str, Any], page: int, deck_title: str) -> int:
    """The client's own game-portfolio layout — one row per studio, one
    column per brand, ● where carried — paginated so every studio is on a
    page, not the twelve most common. Returns the next page number."""
    from pptx.util import Inches, Pt

    matrix = catalog.get("matrix")
    if not matrix:
        # A summary without the matrix (an older caller) still gets the
        # page: the per-brand provider lists are enough to build it.
        from core.watch_catalog import provider_matrix

        matrix = provider_matrix(
            [{"brand": b["name"], "kind": "provider", "name": p, "detail": "", "source_type": "site"}
             for b in catalog.get("brands", []) for p in (b.get("providers") or [])],
            [{"name": b["name"], "is_self": bool(b.get("is_self"))} for b in catalog.get("brands", [])],
        )
    rows = matrix.get("providers") or []
    brands = matrix.get("brands") or []
    if not rows or not brands:
        return page
    per_page = 26
    pages = [rows[i:i + per_page] for i in range(0, len(rows), per_page)]
    self_names = {b["name"] for b in catalog.get("brands", []) if b.get("is_self")}
    c = matrix.get("counts", {})
    listed = c.get("on_client_list", 0)

    def short(name: str) -> str:
        n = re.sub(r"\s+(?:Casino|Slots)$", "", name, flags=re.I)
        return _clean(n, 14)

    for pi, chunk in enumerate(pages, start=1):
        s = _blank(prs)
        top = _header(
            s, "Appendix · raw data",
            f"Game portfolio – {c.get('observed', len(rows))} studios × {len(brands)} brands"
            + (f"  ({pi} of {len(pages)})" if len(pages) > 1 else ""),
        )
        prov_w = 2.3
        col_w = (11.9 - prov_w - 0.45) / max(1, len(brands))
        shape = s.shapes.add_table(
            len(chunk) + 1, 2 + len(brands), Inches(0.7), Inches(top), Inches(11.9),
            Inches(0.16 * (len(chunk) + 1)),
        )
        tbl = shape.table
        tbl.columns[0].width = Inches(prov_w)
        for ci in range(len(brands)):
            tbl.columns[1 + ci].width = Inches(col_w)
        tbl.columns[1 + len(brands)].width = Inches(0.45)
        for r_ in tbl.rows:
            r_.height = Inches(0.16)   # 27 rows end at 6.32in, clear of the footnote at 6.6

        def cw(r: int, col: int, text: str, *, bg: str, fg: str = _INK, bold: bool = False,
               size: float = 6.5, center: bool = False, tbl: Any = tbl) -> None:
            from pptx.enum.text import PP_ALIGN

            cell = tbl.cell(r, col)
            cell.text = text
            cell.fill.solid()
            cell.fill.fore_color.rgb = _rgb(bg)
            cell.margin_left = cell.margin_right = Inches(0.03)
            cell.margin_top = cell.margin_bottom = Inches(0.0)
            for p_ in cell.text_frame.paragraphs:
                if center:
                    p_.alignment = PP_ALIGN.CENTER
                for run in p_.runs:
                    run.font.size = Pt(size)
                    run.font.bold = bold
                    run.font.color.rgb = _rgb(fg)

        cw(0, 0, "Game provider", bg=_INK, fg=_WHITE, bold=True, size=7)
        for ci, b in enumerate(brands):
            cw(0, 1 + ci, short(b) + ("  (us)" if b in self_names else ""),
               bg=_ACCENT if b in self_names else _INK, fg=_WHITE, bold=True, size=6, center=True)
        cw(0, 1 + len(brands), "n", bg=_INK, fg=_WHITE, bold=True, size=6.5, center=True)
        for ri, row in enumerate(chunk, start=1):
            bg = _CARD if ri % 2 else _WHITE
            cw(ri, 0, _clean(row["name"], 30) + ("" if row.get("on_client_list", True) else " *"),
               bg=bg, size=6.5, fg=_INK if row.get("observed") else _MUTED)
            for ci, b in enumerate(brands):
                cell = row["brands"].get(b) or {}
                mark = ("●" + (f" {cell['games']}" if cell.get("games") else "")) if cell.get("carried") else ""
                cw(ri, 1 + ci, mark, bg=(_SELF_ROW if (b in self_names and cell.get("carried")) else bg),
                   size=6.5, center=True)
            cw(ri, 1 + len(brands), str(row.get("brand_count", 0)), bg=bg, size=6.5, center=True)
        _text(s, 0.7, 6.6, 11.9, 0.44,
            "● carried, as printed on the brand's pages or public reviews (the workbook says which); "
            "a number is that studio's titles read; n = brands carrying it."
            + (f" Rows follow the client's list of {listed}; * = observed, not on their list; "
               "a grey row is on their list and not yet seen." if listed else
               " Sorted by how many brands carry the studio."),
            size=7, italic=True, color=_MUTED,
        )
        _footer(s, deck_title, page)
        page += 1
    return page


def _slide_packages(prs: Any, catalog: dict[str, Any], page: int, deck_title: str) -> None:
    """The coin-package price ladder, brand by brand."""
    from pptx.util import Inches, Pt

    s = _blank(prs)
    brands = [b for b in catalog.get("brands", []) if b["packages"]]
    third_pkg = [t for t in (catalog.get("third_party_only") or []) if t.endswith("coin_package")]
    all_reported = len(third_pkg) >= len(brands) and brands
    top = _header(
        s, "Appendix · raw data",
        "Coin packages, as reported by public sources"
        if all_reported
        else "Coin packages, as priced on each store",
    )
    if not brands:
        _footer(s, deck_title, page)
        return
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for b in brands:
        for pkg in b["packages"][:6]:
            rows.append((b, pkg))
    rows = rows[:16]
    shape = s.shapes.add_table(
        len(rows) + 1, 5, Inches(0.7), Inches(top), Inches(11.9),
        Inches(min(0.32 * (len(rows) + 1), 6.1 - top)),
    )
    tbl = shape.table
    for ci, w in enumerate((2.1, 1.2, 3.3, 4.0, 1.3)):
        tbl.columns[ci].width = Inches(w)

    def cw(r: int, c: int, text: str, *, bg: str, fg: str = _INK, bold: bool = False, size: int = 8) -> None:
        cell = tbl.cell(r, c)
        cell.text = text
        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(bg)
        cell.margin_left = cell.margin_right = Inches(0.04)
        cell.margin_top = cell.margin_bottom = Inches(0.01)
        for p in cell.text_frame.paragraphs:
            for run in p.runs:
                run.font.size = Pt(size)
                run.font.bold = bold
                run.font.color.rgb = _rgb(fg)

    for ci, h in enumerate(("Brand", "Price", "What it grants", "Notes", "Read from")):
        cw(0, ci, h, bg=_INK, fg=_WHITE, bold=True)
    for ri, (b, pkg) in enumerate(rows, start=1):
        bg = _SELF_ROW if b["is_self"] else (_CARD if ri % 2 else _WHITE)
        cw(ri, 0, f"{b['name']}{'  (us)' if b['is_self'] else ''}", bg=bg, bold=b["is_self"])
        price = f"${pkg['price_usd']:.2f}" if pkg.get("price_usd") is not None else _clean(pkg["name"], 14)
        cw(ri, 1, price, bg=bg, bold=True)
        grant = pkg.get("coins") or ""
        if not grant or grant.strip().lower() == str(pkg["name"]).strip().lower():
            grant = pkg.get("detail") or "—"   # never restate the price as its own grant
        cw(ri, 2, _clean(grant, 60), bg=bg)
        cw(ri, 3, _clean(pkg.get("detail") or "", 70), bg=bg, size=7.5)
        cw(ri, 4, "the brand" if pkg.get("source_type") == "site" else "review site",
           bg=bg, size=7.5, fg=_INK if pkg.get("source_type") == "site" else _MUTED)
    third = third_pkg
    _text(
        s, 0.7, 6.28, 11.9, 0.4,
        "Prices and grants exactly as printed, with the source of each row. "
        + (
            f"{len(third)} brand{'s' if len(third) != 1 else ''} could only be read from "
            "review sites — those stores are behind a login, so treat those ladders as "
            "reported, not observed. "
            if third
            else ""
        )
        + "Every package observed is in the workbook with its URL and date.",
        size=8, italic=True, color=_MUTED,
    )
    _footer(s, deck_title, page)


def _slide_promotions_raw(prs: Any, catalog: dict[str, Any], page: int, deck_title: str) -> None:
    """Live promotions as listed, with the page they were read from."""
    s = _blank(prs)
    rows: list[tuple[str, dict[str, Any]]] = []
    for b in catalog.get("brands", []):
        for promo in b["promotions"][:4]:
            rows.append((b["name"], promo))
    total = int((catalog.get("totals") or {}).get("promotion", len(rows)))
    top = _header(
        s, "Appendix · raw data",
        f"{total} promotions on record"
        + (f" — {min(len(rows), 12)} shown" if total > min(len(rows), 12) else ", as listed"),
    )
    if not rows:
        _footer(s, deck_title, page)
        return
    _bullets(
        s, 0.7, top, 11.9, 6.1 - top,
        [f"{brand} — {_clean(p['name'], 70)}" + (f": {_clean(p['detail'], 110)}" if p.get("detail") else "")
         for brand, p in rows[:12]],
        size=10.5, color=_INK, gap_pt=6, cap=200, accent_bullet=True, max_items=12,
    )
    _text(s, 0.7, 6.32, 11.9, 0.3,
          "Promotion titles and terms as printed; the pages themselves follow as exhibits.",
          size=8, italic=True, color=_MUTED)
    _footer(s, deck_title, page)


def _slide_games(prs: Any, catalog: dict[str, Any], page: int, deck_title: str) -> None:
    """How big each library is, and what is on the front of it."""
    s = _blank(prs)
    brands = [b for b in catalog.get("brands", []) if b["counts"].get("game")]
    top = _header(s, "Appendix · raw data", "Game libraries observed")
    if not brands:
        _footer(s, deck_title, page)
        return
    _bullets(
        s, 0.7, top, 11.9, 6.1 - top,
        [f"{b['name']}{'  (us)' if b['is_self'] else ''} — {b['counts']['game']} titles read"
         + (f"; e.g. {', '.join(b['games_sample'][:5])}" if b.get("games_sample") else "")
         for b in brands[:12]],
        size=10.5, color=_INK, gap_pt=6, cap=220, accent_bullet=False, max_items=12,
    )
    _text(s, 0.7, 6.32, 11.9, 0.3,
          "Counts are titles READ from the pages collected, not the operator's claimed "
          "catalogue size — the full list is in the workbook.",
          size=8, italic=True, color=_MUTED)
    _footer(s, deck_title, page)


def _slide_offers(
    prs: Any,
    offers: list[dict[str, Any]],
    narrative: dict[str, Any],
    page: int,
    deck_title: str,
) -> int:
    """The offers on the table: per brand, the headline welcome offer and
    the ongoing promotion, verbatim from the evidence register — what the
    market is actually selling to a new visitor this cycle. Executives ask
    for this first; it is the most comparable fact in the whole pack."""

    # Nine brands a page: two wrapped lines a row at 8.5pt is ~0.32in, and
    # fifteen rows ran past the slide (2026-09-02, the register at 15 brands).
    per_page = 9
    pages = [offers[i:i + per_page] for i in range(0, len(offers), per_page)] or [[]]
    for pi, shown in enumerate(pages, start=1):
        _slide_offers_page(prs, shown, narrative, page, deck_title, pi, len(pages))
        page += 1
    return page


def _slide_offers_page(
    prs: Any,
    shown: list[dict[str, Any]],
    narrative: dict[str, Any],
    page: int,
    deck_title: str,
    pi: int,
    n_pages: int,
) -> None:
    from pptx.util import Inches, Pt

    s = _blank(prs)
    title = (narrative.get("titles") or {}).get("offers") or "The offers on the table"
    if n_pages > 1:
        title = f"{title}  ({pi} of {n_pages})"
    top = _header(
        s,
        "Offers and promotions",
        title,
        (narrative.get("commentary") or {}).get("offers", "") if pi == 1 else "",
    )
    cols = ["Brand", "Headline welcome offer", "Ongoing / daily proposition"]
    widths = [1.9, 3.35, 2.95]
    tbl_h = min(0.36 * (len(shown) + 1), 6.5 - top)
    shape = s.shapes.add_table(
        len(shown) + 1, len(cols), Inches(0.7), Inches(top), Inches(sum(widths)), Inches(tbl_h)
    )
    tbl = shape.table
    for ci, w in enumerate(widths):
        tbl.columns[ci].width = Inches(w)

    def cell_write(
        r: int, c: int, text: str, *, bg: str, fg: str = _INK, bold: bool = False, size: float = 8.5
    ) -> None:
        cell = tbl.cell(r, c)
        cell.text = text
        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(bg)
        cell.margin_left = cell.margin_right = Inches(0.05)
        cell.margin_top = cell.margin_bottom = Inches(0.02)
        for p_ in cell.text_frame.paragraphs:
            for run in p_.runs:
                run.font.size = Pt(size)
                run.font.bold = bold
                run.font.color.rgb = _rgb(fg)

    for ci, name in enumerate(cols):
        cell_write(0, ci, name, bg=_INK, fg=_WHITE, bold=True, size=9.5)
    for ri, o in enumerate(shown, start=1):
        is_self = bool(o.get("is_self"))
        bg = _SELF_ROW if is_self else (_WHITE if ri % 2 else _CARD)
        name = str(o.get("brand") or "") + ("  (us)" if is_self else "")
        cell_write(ri, 0, name, bg=bg, fg=_ACCENT if is_self else _INK, bold=True, size=8.5)
        cell_write(
            ri,
            1,
            _clean(o.get("welcome") or "not stated on the pages read", 95),
            bg=bg,
            fg=_INK if o.get("welcome") else _MUTED,
        )
        cell_write(
            ri,
            2,
            _clean(o.get("ongoing") or "—", 95),
            bg=bg,
            fg=_INK if o.get("ongoing") else _MUTED,
        )

    panel = (narrative.get("slides") or {}).get("offers") or {}
    _sidebar(
        s, panel.get("observations") or [], panel.get("implications") or [], top=top, x=9.1, w=3.5
    )
    _text(s, 0.7, 6.6, 11.9, 0.44,
        "Offer text as published on each brand's own pages at capture; amounts and "
        'conditions verified against the page excerpt. "Not stated" means the pages '
        "read carried no welcome offer, not that none exists.",
        size=8.5,
        color=_MUTED,
    )
    _footer(s, deck_title, page)
    _notes(
        s,
        "Every cell is a claim from the evidence register with a source URL and an "
        "excerpt; nothing here is paraphrased from memory.",
    )


def _slide_exhibits(
    prs: Any,
    batch: list[tuple[str, dict[str, str], bool]],
    idx: int,
    total: int,
    page: int,
    deck_title: str,
    *,
    eyebrow: str = "Exhibits",
    title: str = "The storefronts as a visitor sees them",
    captions: dict[str, str] | None = None,
    commentary: str = "",
) -> None:
    """Two captures per slide, photographed by the browser — the market as a
    visitor sees it, filed beside the claims it supports. ``captions`` adds
    a one-line reading under a brand's exhibit (e.g. the offer it shows)."""
    s = _blank(prs)
    suffix = f" ({idx}/{total})" if total > 1 else ""
    top = _header(s, eyebrow, f"{title}{suffix}", commentary)
    slots = [(0.7, 5.9), (6.85, 5.9)]
    max_h = 3.0 if captions else 3.4
    for (x, w), (brand, shot, is_self) in zip(slots, batch, strict=False):
        pic = _picture(s, shot["path"], x, top + 0.15, w, max_h)
        label = f"{brand}{'  (us)' if is_self else ''}"
        pic_h = (pic.height / 914400.0) if pic is not None else max_h
        cap_y = top + 0.15 + min(pic_h, max_h) + 0.12
        _text(s, x, cap_y, w, 0.3, label, size=12, bold=True, color=_ACCENT if is_self else _INK)
        line_y = cap_y + 0.3
        cap = (captions or {}).get(brand, "")
        if cap:
            _text(s, x, line_y, w, 0.45, _clean(cap, 140), size=9.5, color=_BODY)
            line_y += 0.42
        detail = []
        if shot.get("url"):
            detail.append(_clean(shot["url"], 70))
        if shot.get("observed_at"):
            detail.append(f"captured {str(shot['observed_at'])[:10]}")
        if detail:
            _text(s, x, line_y, w, 0.3, " · ".join(detail), size=8.5, color=_MUTED)
        if pic is None:
            _text(s, x, top + 1.5, w, 0.5, "exhibit unavailable", size=10, color=_MUTED)
    _text(s, 0.7, 6.6, 11.9, 0.44,
        "Captured by the browser through a state-verified network exit, cookie "
        "consent dismissed; each capture is filed in the evidence register beside its claims.",
        size=9,
        color=_MUTED,
    )
    _footer(s, deck_title, page)


def _slide_changes(
    prs: Any,
    diff: dict[str, Any] | None,
    narrative: dict[str, Any],
    page: int,
    deck_title: str,
    events: list[dict[str, Any]] | None = None,
) -> None:
    s = _blank(prs)
    commentary = (narrative.get("commentary") or {}).get("changes", "")
    events = events or []
    if diff is None:
        n = len(events)
        title = (
            f"Baseline established – {n} market event{'s' if n != 1 else ''} on record"
            if n
            else "Baseline established"
        )
        top = _header(s, "Market moves", title, commentary)
        _text(
            s,
            0.7,
            top,
            11.9,
            0.8,
            "First reporting cycle. There is no prior snapshot to compare "
            "against, so this pack sets the baseline; the next cycle shows "
            "what moved."
            + (
                " The events below were read from the brands' own pages during "
                "this cycle and need no prior snapshot."
                if events
                else ""
            ),
            size=13,
            color=_BODY,
        )
        if events:
            _eyebrow(s, "Market events on record", y=top + 0.95, color=_ACCENT)
            _bullets(
                s,
                0.7,
                top + 1.3,
                11.9,
                6.4 - (top + 1.3),
                [
                    f"{ev['brand']} – {ev['claim']}"
                    + (f" (observed {ev['observed_at']})" if ev.get("observed_at") else "")
                    for ev in events
                ],
                size=12,
                color=_INK,
                gap_pt=8,
                cap=200,
                accent_bullet=True,
                max_items=4,
            )
        _footer(s, deck_title, page)
        return
    n = int(diff.get("material_count", 0))
    title = (narrative.get("titles") or {}).get(
        "changes"
    ) or f"{n} material move{'s' if n != 1 else ''} this period"
    top = _header(s, "Market moves", title, commentary)
    _text(
        s,
        0.7,
        top - 0.05,
        11.9,
        0.3,
        f"{str(diff.get('from_generated_at', '?'))[:10]} → "
        f"{str(diff.get('to_generated_at', '?'))[:10]}",
        size=10,
        color=_MUTED,
    )
    top += 0.3
    if n == 0:
        th = diff.get("thresholds", {})
        _text(
            s,
            0.7,
            top + 0.2,
            11.9,
            1.2,
            "Nothing moved above the materiality threshold "
            f"(score move ≥ {th.get('min_score_delta', 1.0)}, coverage shift ≥ "
            f"{th.get('min_coverage_delta', 0)}%). Sub-threshold wobble is "
            "suppressed on purpose.",
            size=15,
            color=_BODY,
        )
        _footer(s, deck_title, page)
        return
    lines: list[str] = []
    for c in diff.get("changed", []):
        for item in c.get("items", []):
            lines.append(f"{c['subject']} – {item.get('detail', '')}")
    if diff.get("added_subjects"):
        lines.append("New in the analysis: " + ", ".join(diff["added_subjects"]))
    if diff.get("removed_subjects"):
        lines.append("Removed: " + ", ".join(diff["removed_subjects"]))
    shown = lines[:11]
    half = (len(shown) + 1) // 2
    _bullets(
        s,
        0.7,
        top,
        5.9,
        6.5 - top,
        shown[:half],
        size=11.5,
        gap_pt=7,
        cap=120,
        accent_bullet=False,
        max_items=6,
    )
    _bullets(
        s,
        6.85,
        top,
        5.8,
        6.5 - top,
        shown[half:],
        size=11.5,
        gap_pt=7,
        cap=120,
        accent_bullet=False,
        max_items=6,
    )
    if len(lines) > len(shown):
        _text(
            s,
            0.7,
            6.55,
            11.9,
            0.3,
            f"+{len(lines) - len(shown)} more in the board report.",
            size=9,
            color=_MUTED,
        )
    _footer(s, deck_title, page)


def _slide_implications(
    prs: Any,
    judged: list[dict[str, Any]],
    material_count: int,
    source: str,
    page: int,
    deck_title: str,
) -> int:
    from pptx.util import Inches, Pt

    if not judged:
        s = _blank(prs)
        _header(s, "Judgement", "Implications and recommendations")
        msg = (
            "Implications were not generated – no model was available. The "
            "material changes are the factual record; judgement still needs "
            "to be applied."
            if material_count
            else "No material change this period, so there is nothing new to act on."
        )
        _text(s, 0.7, 2.4, 11.9, 1.2, msg, size=15, color=_BODY)
        _footer(s, deck_title, page)
        return 1

    ordered = sorted(
        judged,
        key=lambda j: (
            _CLASS_ORDER.index(j.get("classification", "monitor"))
            if j.get("classification") in _CLASS_ORDER
            else len(_CLASS_ORDER)
        ),
    )
    per = 5
    batches = [ordered[i : i + per] for i in range(0, len(ordered), per)]
    for pi, chunk in enumerate(batches):
        s = _blank(prs)
        suffix = f" ({pi + 1}/{len(batches)})" if len(batches) > 1 else ""
        top = _header(s, "Judgement", f"Implications and recommendations{suffix}")
        cols = ["Subject", "Change", "Implication", "Recommendation", "Class"]
        widths = [1.7, 2.7, 3.3, 3.3, 1.6]
        shape = s.shapes.add_table(
            len(chunk) + 1,
            len(cols),
            Inches(0.7),
            Inches(top),
            Inches(sum(widths)),
            Inches(0.42 * (len(chunk) + 1)),
        )
        tbl = shape.table
        for ci, w in enumerate(widths):
            tbl.columns[ci].width = Inches(w)
        for ci, name in enumerate(cols):
            cell = tbl.cell(0, ci)
            cell.text = name
            cell.fill.solid()
            cell.fill.fore_color.rgb = _rgb(_INK)
            for p in cell.text_frame.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(10)
                    r.font.bold = True
                    r.font.color.rgb = _rgb(_WHITE)
        for ri, j in enumerate(chunk, start=1):
            vals = [
                _clean(j.get("subject", ""), 40),
                _clean(j.get("change", ""), 90),
                _clean(j.get("implication", ""), 110),
                _clean(j.get("recommendation", ""), 110),
                _CLASS_LABEL.get(str(j.get("classification", "monitor")), "Monitor"),
            ]
            for ci, v in enumerate(vals):
                cell = tbl.cell(ri, ci)
                cell.text = v
                cell.fill.solid()
                cell.fill.fore_color.rgb = _rgb(_WHITE if ri % 2 else _CARD)
                for p in cell.text_frame.paragraphs:
                    for r in p.runs:
                        r.font.size = Pt(9)
                        r.font.color.rgb = _rgb(_INK)
        _judgement_note(s, source)
        _footer(s, deck_title, page + pi)
        _notes(
            s,
            "Classification uses the no-regret test: would we still be pleased "
            "we did this if the transition plan, rankings or priorities "
            "changed next month?",
        )
    return len(batches)


def _slide_decisions(
    prs: Any,
    judged: list[dict[str, Any]],
    source: str,
    material_count: int,
    page: int,
    deck_title: str,
) -> None:
    s = _blank(prs)
    top = _header(s, "The ask", "Decisions required")
    asks = [
        f"{j.get('subject', '')}: {j.get('decision_required', '')}"
        for j in judged
        if str(j.get("decision_required", "none")).strip().lower() not in ("", "none")
    ]
    if asks:
        _bullets(s, 0.7, top + 0.2, 11.9, 6.4 - top, asks[:6], size=15, gap_pt=12, cap=140)
        _judgement_note(s, source)
    elif judged:
        _text(
            s,
            0.7,
            top + 0.3,
            11.9,
            1.0,
            "No board decision is required this period.",
            size=17,
            color=_BODY,
        )
        _judgement_note(s, source)
    elif material_count:
        _text(
            s,
            0.7,
            top + 0.3,
            11.9,
            1.4,
            f"Not yet evaluated – {material_count} material change"
            f"{'s' if material_count != 1 else ''} recorded, but no model was "
            "available to judge what they require of the board.",
            size=17,
            color=_BODY,
        )
    else:
        _text(
            s,
            0.7,
            top + 0.3,
            11.9,
            1.0,
            "No material change this period, so nothing new to decide.",
            size=17,
            color=_BODY,
        )
    _footer(s, deck_title, page)


def _slide_evidence(
    prs: Any,
    card: dict[str, Any],
    gaps: list[dict[str, Any]],
    evidence_count: int,
    narrative: dict[str, Any],
    page: int,
    deck_title: str,
) -> None:
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    s = _blank(prs)
    title = (narrative.get("titles") or {}).get("coverage") or "How much of this is measured"
    top = _header(
        s,
        "Appendix – evidence and confidence",
        title,
        (narrative.get("commentary") or {}).get("coverage", ""),
    )
    rows = card.get("rows", [])
    dims = card.get("dimensions", [])
    pairs = len(rows) * len(dims)
    observed = sum(
        1 for r in rows for d in r.get("dimensions", {}).values() if d.get("score") is not None
    )
    never = [g for g in gaps if g.get("status") == "never_observed"]
    stale = [g for g in gaps if g.get("status") == "stale"]
    pct = (observed / pairs * 100.0) if pairs else 0.0

    tiles = [
        (f"{pct:.0f}%", f"of the scorecard filled in – {observed} of {pairs} brand × dimension cells"),
        (f"{evidence_count:,}", "evidence items on file, each quoting a source URL"),
        (f"{len(never)}", "cells never observed – no score, no penalty"),
        (f"{len(stale)}", "overdue a refresh against their cadence"),
    ]
    x = 0.7
    for big, label in tiles:
        _text(s, x, top + 0.15, 2.85, 0.9, big, size=32, bold=True)
        _text(s, x, top + 1.05, 2.85, 0.8, _clean(label, 80), size=10, color=_MUTED)
        x += 3.05

    y = top + 2.15
    never_brands = sorted({g["subject"] for g in never})
    if never_brands:
        more = f" +{len(never_brands) - 6} more" if len(never_brands) > 6 else ""
        _text(
            s,
            0.7,
            y,
            11.9,
            0.35,
            "Not yet observed: " + ", ".join(never_brands[:6]) + more,
            size=11.5,
            color=_BODY,
        )
        y += 0.45
    if stale:
        ex = ", ".join(f"{g['subject']} / {g['dimension']}" for g in stale[:4])
        _text(s, 0.7, y, 11.9, 0.35, f"Overdue: {ex}", size=11.5, color=_BODY)
        y += 0.45

    card_y = max(y + 0.15, 5.5)
    box = s.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.7), Inches(card_y), Inches(11.9), Inches(0.85)
    )
    box.fill.solid()
    box.fill.fore_color.rgb = _rgb(_CARD)
    box.line.color.rgb = _rgb(_HAIR)
    box.line.width = Pt(0.75)
    box.shadow.inherit = False
    bar = s.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.7), Inches(card_y), Inches(0.06), Inches(0.85)
    )
    bar.fill.solid()
    bar.fill.fore_color.rgb = _rgb(_ACCENT)
    bar.line.fill.background()
    bar.shadow.inherit = False
    _text(
        s,
        0.95,
        card_y + 0.12,
        11.4,
        0.65,
        "Gaps are absences of evidence, not weaknesses. No brand is scored "
        "down for being opaque, and no score on any slide exists without a "
        "source behind it.",
        size=11.5,
        color=_INK,
    )
    _footer(s, deck_title, page)


def _slide_heatmap(prs: Any, card: dict[str, Any], page: int, deck_title: str) -> None:
    from pptx.util import Inches, Pt

    s = _blank(prs)
    top = _header(s, "Appendix", "Scores by dimension")
    rows = card.get("rows", [])[:14]
    dims = [d["name"] for d in card.get("dimensions", [])][:12]
    if not rows or not dims:
        _text(s, 0.7, top + 0.2, 11.9, 1.0, "Nothing scored yet.", size=15, color=_BODY)
        _footer(s, deck_title, page)
        return
    ncols = 2 + len(dims)
    total_w = 11.9
    first_w = 2.0
    dim_w = (total_w - first_w - 0.9) / len(dims)
    shape = s.shapes.add_table(
        len(rows) + 1,
        ncols,
        Inches(0.7),
        Inches(top),
        Inches(total_w),
        Inches(min(0.32 * (len(rows) + 1), 6.6 - top)),
    )
    tbl = shape.table
    # Fifteen brands and a header of long dimension names ran past the
    # footnote (2026-09-02): rows shrink to fit under it, the header is
    # short, the body a touch smaller when the field is wide.
    row_h = min(0.32, (5.95 - top) / (len(rows) + 1))
    for r_ in tbl.rows:
        r_.height = Inches(row_h)
    tbl.columns[0].width = Inches(first_w)
    tbl.columns[1].width = Inches(0.9)
    for ci in range(len(dims)):
        tbl.columns[2 + ci].width = Inches(dim_w)

    def cell_write(
        r: int, c: int, text: str, *, bg: str, fg: str = _INK, bold: bool = False, size: int = 8
    ) -> None:
        cell = tbl.cell(r, c)
        cell.text = text
        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(bg)
        cell.margin_left = cell.margin_right = Inches(0.03)
        cell.margin_top = cell.margin_bottom = Inches(0.01)
        for p in cell.text_frame.paragraphs:
            for run in p.runs:
                run.font.size = Pt(size)
                run.font.bold = bold
                run.font.color.rgb = _rgb(fg)

    cell_write(0, 0, "Brand", bg=_INK, fg=_WHITE, bold=True)
    cell_write(0, 1, "Overall", bg=_INK, fg=_WHITE, bold=True)
    for ci, d in enumerate(dims):
        cell_write(0, 2 + ci, _clean(d, 26), bg=_INK, fg=_WHITE, bold=True, size=6.5)
    for ri, r in enumerate(rows, start=1):
        bg = _SELF_ROW if r.get("is_self") else _WHITE
        mark = "†" if r.get("provisional") and r["overall"]["normalized_pct"] is not None else ""
        cell_write(
            ri,
            0,
            f"{r['name']}{'  (us)' if r.get('is_self') else ''}",
            bg=bg,
            bold=bool(r.get("is_self")),
        )
        cell_write(ri, 1, f"{_fmt(r['overall']['normalized_pct'])}{mark}", bg=bg)
        for ci, d in enumerate(dims):
            sc = r.get("dimensions", {}).get(d, {}).get("score")
            if sc is None:
                cell_write(ri, 2 + ci, "", bg=_GAP_BG)  # blank, never a zero
            else:
                cell_write(ri, 2 + ci, f"{float(sc):g}", bg=bg)
    _text(
        s,
        0.7,
        6.62,
        11.9,
        0.3,
        "1–5 per dimension. Blank – not yet observed (never a zero). "
        "† provisional. Amber row – our brand.",
        size=9,
        color=_MUTED,
    )
    _footer(s, deck_title, page)


def _slide_method(
    prs: Any,
    card: dict[str, Any],
    diff: dict[str, Any] | None,
    page: int,
    deck_title: str,
) -> None:
    s = _blank(prs)
    top = _header(s, "Appendix – method", "How to read these numbers")
    dims = card.get("dimensions", [])
    th = (diff or {}).get("thresholds", {})
    if th:
        change_rule = (
            f"Material change – score move ≥ {th.get('min_score_delta', 1.0)}, "
            f"a rank change, a dimension newly scored or withdrawn, or a "
            f"coverage shift ≥ {th.get('min_coverage_delta', 0)}%. Smaller "
            "moves are suppressed."
        )
    else:
        change_rule = (
            "Material change – a full-point score move, a rank change, a "
            "dimension newly scored or withdrawn, or a large coverage shift. "
            "Smaller moves are suppressed."
        )
    items = [
        f"{len(dims)} weighted dimensions (weights sum to "
        f"{card.get('weight_total_pct', 0):g}%); each scored 1–5 from filed evidence.",
        "Overall – weighted score normalized to the weight actually measured, "
        "so a brand with partial evidence is compared on what was seen, never "
        "padded with zeros.",
        "A brand ranks only once enough of the model is scored; below that it "
        "is provisional (†) – its figure is shown, its standing withheld.",
        "Every evidence item quotes its source verbatim and was verified "
        "against the live page before it was saved; per-state evidence "
        "carries the network exit that was proven to be in that state, and "
        "storefront exhibits were captured through that same verified exit.",
        change_rule,
        "Narrative, titles, competitor observations and implications are "
        "model-written from the factual record and labelled; standings, "
        "scores and gaps are computed.",
    ]
    _bullets(
        s,
        0.7,
        top + 0.1,
        11.9,
        6.5 - top,
        items[:6],
        size=11.5,
        gap_pt=7,
        cap=260,
        accent_bullet=False,
    )
    _footer(s, deck_title, page)


def _slide_closing(prs: Any, narrative: dict[str, Any], deck_title: str) -> None:
    s = _blank(prs)
    _dark(s)
    _eyebrow(s, "Next steps", y=1.0)
    _text(s, 0.7, 1.4, 11.9, 1.0, "Where this goes next", size=30, bold=True, color=_WHITE)
    _rule(s, 2.5)
    steps = [str(b) for b in narrative.get("next_steps") or []][:4]
    if not steps:
        steps = ["Hold the cadence – re-observe on schedule and diff next cycle"]
    _bullets(s, 0.7, 2.85, 11.4, 3.4, steps, size=15, color=_DARK_BODY, gap_pt=14, cap=120)
    _judgement_note(s, str(narrative.get("source") or "facts"), dark=True)


# ── entry point ──────────────────────────────────────────────────────


def render_executive_deck(
    card: dict[str, Any],
    *,
    diff: dict[str, Any] | None,
    judged: list[dict[str, Any]],
    summary: dict[str, Any],
    gaps: list[dict[str, Any]],
    evidence_count: int,
    path: str | Path,
    screenshots: dict[str, list[dict[str, str]]] | None = None,
    offers: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    voice: dict[str, Any] | None = None,
    voice_diff: dict[str, Any] | None = None,
    comms: dict[str, Any] | None = None,
    regulatory: dict[str, Any] | None = None,
    catalog: dict[str, Any] | None = None,
    tone: dict[str, Any] | None = None,
    trends: dict[str, Any] | None = None,
    calendar: dict[str, Any] | None = None,
    title: str = "Competitive Intelligence – Executive Briefing",
    market_label: str = "",
) -> str:
    """Write the deck. Returns the path written.

    ``voice`` (a voice summary) and ``voice_diff`` add the 'What players
    say' slides and the quote strips on deep dives; absent, the deck is
    exactly the pack it always was.

    ``summary`` is the narrative dict — ``{headline, bullets, exec, profiles,
    titles, commentary, next_steps, source}`` — model-written when a router
    exists, otherwise :func:`factual_narrative`'s computed fallback. The
    renderer treats every narrative string as untrusted copy: capped,
    en-dashed and scrubbed of internal bookkeeping. ``screenshots`` maps
    brand name → storefront exhibits ``[{path, url, observed_at}]``; slides
    that need them are skipped when they are absent, never faked.
    """
    from pptx import Presentation
    from pptx.util import Inches

    narrative = summary or {}
    shots = screenshots or {}
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    rows = card.get("rows", [])
    dims = card.get("dimensions", [])
    weights = {d["name"]: float(d.get("weight_pct") or 0.0) for d in dims}
    generated = str(card.get("generated_at") or datetime.now(UTC).isoformat())
    if diff:
        period = (
            f"Period {str(diff.get('from_generated_at', '?'))[:10]} → "
            f"{str(diff.get('to_generated_at', '?'))[:10]}"
        )
    else:
        period = f"Baseline · generated {generated[:10]}"
    basis = (
        f"{len(rows)} brands · {len(dims)} dimensions · {evidence_count:,} "
        "observed facts · every score traceable to a source URL"
    )
    deck_title = _clean(title, 70)
    src = str(narrative.get("source") or "facts")

    _slide_title(
        prs,
        title=title,
        market=market_label,
        period=period,
        basis=basis,
        generated=generated,
    )
    page = 2
    _slide_reading_guide(prs, card, evidence_count, page, deck_title, voice=voice, catalog=catalog, trends=trends)
    page += 1
    _slide_summary(prs, card, narrative, page, deck_title, events=events)
    page += 1
    _slide_glance(
        prs,
        card,
        evidence_count,
        gaps,
        (narrative.get("commentary") or {}).get("glance", ""),
        page,
        deck_title,
    )
    page += 1
    _slide_standings(prs, card, narrative, page, deck_title)
    page += 1
    _slide_versus(prs, card, narrative, page, deck_title)
    page += 1
    _slide_dimension_leaders(prs, card, narrative, page, deck_title)
    page += 1

    # The offers on the table — one row per brand, then the promotions pages
    # photographed, captioned with the offer they show.
    offer_rows = [o for o in (offers or []) if o.get("welcome") or o.get("ongoing")]
    if offer_rows:
        page = _slide_offers(prs, offer_rows, narrative, page, deck_title)
        promo_items: list[tuple[str, dict[str, str], bool]] = []
        captions: dict[str, str] = {}
        for o in offer_rows:
            promo_shot = o.get("exhibit")
            if isinstance(promo_shot, dict) and promo_shot.get("path"):
                promo_items.append((str(o["brand"]), promo_shot, bool(o.get("is_self"))))
                captions[str(o["brand"])] = str(o.get("welcome") or o.get("ongoing") or "")
        promo_items = promo_items[:8]
        pbatches = [promo_items[i : i + 2] for i in range(0, len(promo_items), 2)]
        exhibits_panel = (narrative.get("slides") or {}).get("offers") or {}
        for bi, batch in enumerate(pbatches):
            _slide_exhibits(
                prs,
                batch,
                bi + 1,
                len(pbatches),
                page,
                deck_title,
                eyebrow="Offers and promotions – exhibits",
                title="The offers as the visitor sees them",
                captions=captions,
                commentary=(exhibits_panel.get("observations") or [""])[0] if bi == 0 else "",
            )
            page += 1

    # Trends — only once three or more scored cycles exist.
    if trends and int(trends.get("cycles", 0)) >= 3:
        _slide_trends(prs, trends, card, narrative, page, deck_title)
        page += 1

    # Regulatory calendar — only when the register has items.
    if regulatory and regulatory.get("total"):
        _slide_regulatory(prs, regulatory, narrative, page, deck_title)
        page += 1

    # Demand calendar — opt-in (an operator aid, not evidence).
    if calendar and calendar.get("weeks"):
        _slide_calendar(prs, calendar, page, deck_title)
        page += 1

    # What they send players — first-party marketing e-mail, only when an
    # inbox is linked and something arrived.
    if comms and comms.get("emails"):
        _slide_comms(prs, comms, narrative, page, deck_title)
        page += 1

    # What players say — the second evidence class, on top of the pack and
    # only when something was collected. Opinion, labelled as such.
    voice_by_brand: dict[str, dict[str, Any]] = {}
    if voice and voice.get("mentions"):
        _slide_voice(prs, voice, narrative, page, deck_title)
        page += 1
        _slide_voice_changes(prs, voice_diff, narrative, page, deck_title)
        page += 1
        voice_by_brand = {str(b.get("name")): b for b in voice.get("brands", [])}

    # Competitor deep dives — one slide per profiled brand, in the model's
    # order (the ranked leader first). Only brands that exist in the card.
    by_name = {r["name"]: r for r in rows}
    for profile in (narrative.get("profiles") or [])[:8]:
        row = by_name.get(str(profile.get("brand") or ""))
        if row is None:
            continue
        _slide_profile(
            prs,
            row,
            profile,
            weights,
            shots.get(row["name"], []),
            page,
            deck_title,
            voice_brand=voice_by_brand.get(row["name"]),
        )
        page += 1

    # Storefront exhibits — ranked order, our brand first when captured.
    exhibit_items: list[tuple[str, dict[str, str], bool]] = []
    ordered_rows = sorted(
        rows,
        key=lambda r: (
            not r.get("is_self"),
            r.get("rank") if r.get("rank") is not None else 99,
        ),
    )
    for r in ordered_rows:
        for shot in shots.get(r["name"], [])[:1]:
            exhibit_items.append((r["name"], shot, bool(r.get("is_self"))))
    exhibit_items = exhibit_items[:14]
    batches = [exhibit_items[i : i + 2] for i in range(0, len(exhibit_items), 2)]
    store_panel = (narrative.get("slides") or {}).get("exhibits") or {}
    store_obs = [str(o) for o in (store_panel.get("observations") or []) if str(o).strip()]
    for bi, batch in enumerate(batches):
        _slide_exhibits(
            prs,
            batch,
            bi + 1,
            len(batches),
            page,
            deck_title,
            commentary=store_obs[bi] if bi < len(store_obs) else "",
        )
        page += 1

    _slide_changes(prs, diff, narrative, page, deck_title, events=events)
    page += 1
    page += _slide_implications(
        prs,
        judged,
        int((diff or {}).get("material_count", 0)),
        src,
        page,
        deck_title,
    )
    _slide_decisions(
        prs,
        judged,
        src,
        int((diff or {}).get("material_count", 0)),
        page,
        deck_title,
    )
    page += 1
    _slide_evidence(prs, card, gaps, evidence_count, narrative, page, deck_title)
    page += 1
    _slide_heatmap(prs, card, page, deck_title)
    page += 1
    # How they talk to players — from their own copy, when there is any.
    if tone and tone.get("brands"):
        _slide_tone(prs, tone, narrative, page, deck_title)
        page += 1

    # Appendix · raw data (docs/89) — the inventory behind the scores.
    if catalog and catalog.get("items"):
        if catalog["totals"].get("provider"):
            page = _slides_portfolio(prs, catalog, page, deck_title)
        # The cross-brand summaries (top-12 studios, one ladder, twelve
        # promotions, "e.g." titles) are gone: the client asked for the
        # data, and the per-brand pages below carry all of it.
        # …then the detail itself, per brand, in the client's own layout:
        # Coins / Promotions, Loyalty Club (when tiers are held), Providers / Games.
        for brand_row in catalog.get("brands", [])[:16]:
            cnt = brand_row["counts"]
            if cnt.get("coin_package") or cnt.get("promotion"):
                _slide_brand_coins_promos(prs, brand_row, page, deck_title)
                page += 1
            if brand_row.get("tiers"):
                _slide_brand_loyalty(prs, brand_row, page, deck_title)
                page += 1
            if cnt.get("provider") or cnt.get("game"):
                _slide_brand_library(prs, brand_row, page, deck_title)
                page += 1

    _slide_method(prs, card, diff, page, deck_title)
    page += 1
    _slide_closing(prs, narrative, deck_title)

    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    logger.info("Executive deck written: %s (%d slides)", out, len(prs.slides))
    return str(out)


def render_voice_deck(
    voice: dict[str, Any],
    *,
    voice_diff: dict[str, Any] | None,
    narrative: dict[str, Any] | None,
    path: str | Path,
    title: str = "Voice of Customer – What Players Say",
    market_label: str = "",
) -> str:
    """The standalone voice-of-customer deck: the same components as the
    pack's voice slides, on their own — title, the field heatmap, movement,
    one slide per brand with enough mentions, method, closing."""
    from pptx import Presentation
    from pptx.util import Inches

    narrative = narrative or {}
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    generated = datetime.now(UTC).isoformat()
    deck_title = _clean(title, 70)
    brands = voice.get("brands", [])
    readable = [b for b in brands if not b.get("too_few")]
    _slide_title(
        prs,
        title=title,
        market=market_label or "Voice of customer",
        period=f"{voice.get('window_days', 30)}-day window · generated {generated[:10]}",
        basis=(
            f"{voice.get('mentions', 0):,} public mentions · {len(brands)} brands tracked · "
            f"{len(readable)} with enough to read · sources: {', '.join(voice.get('sources') or []) or '—'}"
        ),
        generated=generated,
    )
    page = 2
    _slide_voice(prs, voice, narrative, page, deck_title)
    page += 1
    _slide_voice_changes(prs, voice_diff, narrative, page, deck_title)
    page += 1
    for b in sorted(readable, key=lambda b: (not b.get("is_self"), -b.get("n", 0)))[:12]:
        s = _blank(prs)
        top = _header(
            s,
            f"{b['name']}{'  (us)' if b.get('is_self') else ''} · n={b.get('n', 0)}",
            f"{b['name']} – "
            + (
                f"players complain about {_theme_label(b['top_complaint']).lower()}"
                if b.get("top_complaint") and b.get("neg_share", 0) >= 0.4
                else f"players mostly praise {_theme_label(b['top_praise']).lower()}"
                if b.get("top_praise")
                else "what players say"
            ),
        )
        # left: theme shares as bars
        y = top + 0.1
        themes = sorted((b.get("themes") or {}).items(), key=lambda kv: -kv[1]["share"])[:8]
        for t, v in themes:
            _text(s, 0.7, y, 2.2, 0.26, _theme_label(t), size=9.5, color=_BODY)
            bar = s.shapes.add_shape(1, Inches(2.95), Inches(y + 0.05), Inches(max(0.05, 2.9 * v["share"])), Inches(0.16))
            bar.fill.solid()
            bar.fill.fore_color.rgb = _rgb("DC2626" if v["neg_share"] >= 0.6 else ("16A34A" if v["neg_share"] <= 0.3 else _PEER))
            bar.line.fill.background()
            bar.shadow.inherit = False
            _text(s, 5.9, y, 1.0, 0.26, f"{int(round(v['share'] * 100))}% · n{v['n']}", size=8.5, color=_MUTED)
            y += 0.34
        _text(
            s, 0.7, y + 0.15, 5.4, 0.6,
            f"{int(round(b.get('neg_share', 0) * 100))}% negative · {int(round(b.get('pos_share', 0) * 100))}% positive"
            + (f" · avg rating {b['avg_rating']}" if b.get("avg_rating") is not None else "")
            + f" · sources: {', '.join(b.get('sources') or [])}",
            size=9.5, color=_BODY,
        )
        # right: quotes + flags
        x = 6.9
        _eyebrow(s, "In their words", y=top + 0.1, x=x, color=_PEER)
        _bullets(
            s, x, top + 0.45, 5.7, 2.9,
            [f"“{_clean(q.get('quote', ''), 200)}” — {q.get('source', '')}, {q.get('posted_at', '')}" for q in (b.get("quotes") or [])[:3]]
            or ["No quotable mention in the window."],
            size=11, color=_INK, gap_pt=8, cap=260, accent_bullet=False, max_items=3,
        )
        if b.get("flags"):
            _eyebrow(s, "Players flag", y=top + 3.45, x=x, color=_ACCENT)
            _bullets(s, x, top + 3.8, 5.7, min(0.8, 6.25 - (top + 3.8)), [str(f) for f in b["flags"][:2]],
                     size=10.5, color=_BODY, gap_pt=4, cap=100, accent_bullet=True, max_items=2)
        _text(s, 0.7, 6.32, 11.9, 0.3, _VOICE_LABEL, size=8, italic=True, color=_MUTED)
        _footer(s, deck_title, page)
        page += 1
    # method
    s = _blank(prs)
    top = _header(s, "Method", "How to read these numbers")
    _bullets(
        s, 0.7, top, 11.9, 5.5,
        [
            "Sources are public posts and reviews (Reddit posts and comments, App Store reviews); "
            "each post is read for one theme from a fixed vocabulary and a sentiment, and a short "
            "verbatim quote is kept with its URL and date.",
            "Numbers are shares of a brand's own mentions, always with n. Volume differs a hundredfold "
            "between brands, so absolutes are never compared; brands under "
            f"{voice.get('min_mentions', 15)} mentions are shown as 'too few to read'.",
            "Usernames, handles, emails and links are stripped before reading; affiliate and referral "
            "posts are dropped; cross-posts count once; posts are weighted by visible credibility.",
            "This is what players SAY. It never moves a scorecard number; a theme may flag a "
            "dimension for the reader to check on the page.",
        ],
        size=11.5, color=_BODY, gap_pt=8, cap=320, accent_bullet=True, max_items=4,
    )
    _footer(s, deck_title, page)
    page += 1
    _slide_closing(prs, narrative, deck_title)
    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    return str(out)
