"""Executive deck rendering for the competitive-intelligence organ.

The scorecard workbook is for the analyst and the board report is for the
reader; this is for the room. Twelve 16:9 slides in a fixed house style,
built from the *same* stored evidence as the other deliverables — nothing
here is computed differently, it is only said the way a room hears it.

Design doctrine (adapted from a sister deck pipeline that ships to
executives daily):

* **One idea per slide, action titles.** Every heading is a sentence someone
  could disagree with ("High 5 leads a thin field"), never a label. The
  model writes titles and one-line commentary from the factual record; the
  numbers themselves are computed, never generated.
* **Numbers pulled forward.** The headline figures get a metrics slide with
  display-size values, before any chart.
* **Restraint.** White content slides, ink type, one short accent rule under
  each heading, dark bookends (title and closing). En dashes, never em.
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
_INK = "111827"        # near-black: headings, display numbers, dark canvases
_BODY = "4B5563"       # body copy
_MUTED = "9CA3AF"      # eyebrows, footers, labels
_HAIR = "E5E7EB"       # hairlines
_CARD = "F9FAFB"       # zebra rows / note cards
_GAP_BG = "F3F4F6"     # heatmap: not observed
_ACCENT = "D97706"     # amber: the accent rule, and *our* brand everywhere
_PEER = "64748B"       # slate: peer brands
_DARK_BODY = "D1D5DB"  # body copy on dark canvases
_SELF_ROW = "FDF6EC"   # our row in the heatmap
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


def _fmt(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}"


# ── drawing primitives ───────────────────────────────────────────────


def _rgb(hexstr: str) -> Any:
    from pptx.dml.color import RGBColor

    return RGBColor.from_string(hexstr)


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
) -> Any:
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    box = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
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
) -> Any:
    from pptx.util import Inches, Pt

    box = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    tf = box.text_frame
    tf.word_wrap = True
    first = True
    for item in items[:6]:
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

    ln = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Pt(2.6)
    )
    ln.fill.solid()
    ln.fill.fore_color.rgb = _rgb(_ACCENT)
    ln.line.fill.background()
    ln.shadow.inherit = False


def _eyebrow(
    slide: Any, text: str, *, y: float, x: float = 0.7, color: str = _MUTED
) -> None:
    # Width fits the remaining canvas — an eyebrow placed in a right-hand
    # column must not spill past the slide edge.
    width = max(1.0, 13.333 - x - 0.73)
    _text(
        slide, x, y, width, 0.3, _clean(text, 60).upper(),
        size=10.5, bold=True, color=color, spacing=3,
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
        slide, 0.7, 0.72, 11.9, 0.85, _clean(title, 110),
        size=23, bold=True, line=1.08,
    )
    _rule(slide, 1.62)
    if commentary:
        _text(
            slide, 0.7, 1.78, 11.9, 0.4, _clean(commentary, 170),
            size=12.5, italic=True, color=_BODY,
        )
        return 2.3
    return 2.0


def _judgement_note(slide: Any, source: str, *, dark: bool = False) -> None:
    msg = (
        "Narrative and commentary written by the model from the factual record "
        "– verify before presenting."
        if source == "model"
        else "Facts only – no model was available, so no narrative judgement "
        "has been applied."
    )
    _text(slide, 0.7, 6.72, 11.9, 0.3, msg, size=9,
          color="6B7280" if dark else _MUTED)


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


# ── narrative fallback (no model) ────────────────────────────────────


def factual_narrative(
    card: dict[str, Any],
    diff: dict[str, Any] | None,
    judged: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    """The deck's words when no model is available: numbers only, no claims.

    Deliberately dull — a dull true summary beats a sharp invented one. Same
    shape as the model's narrative, so the renderer never branches.
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
            f"{len(rows)} brands tracked; none yet scored on enough of the "
            "model to rank."
        )
    if us is not None:
        if us.get("rank") is not None:
            bullets.append(
                f"{us['name']} ranks #{us['rank']} at "
                f"{_fmt(us['overall']['normalized_pct'])}."
            )
        elif us["overall"]["normalized_pct"] is not None:
            bullets.append(
                f"{us['name']} scores {_fmt(us['overall']['normalized_pct'])} "
                "but is provisional – not enough of the model measured to rank."
            )
        else:
            bullets.append(f"{us['name']} is not yet scored on any dimension.")
    if diff is None:
        bullets.append(
            "First cycle: this pack sets the baseline; change appears next cycle."
        )
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
        f"{len(never)} brand × dimension pairs never observed; "
        f"{len(stale)} overdue a refresh."
    )
    asks = [
        j for j in judged
        if str(j.get("decision_required", "none")).strip().lower() not in ("", "none")
    ]

    never_brands = sorted({g["subject"] for g in never})
    next_steps: list[str] = []
    if never_brands:
        more = " and others" if len(never_brands) > 3 else ""
        next_steps.append(
            "Collect the unobserved brands – " + ", ".join(never_brands[:3]) + more
        )
    if stale:
        next_steps.append(
            f"Refresh the {len(stale)} pairs overdue against their cadence"
        )
    if asks:
        plural = "s" if len(asks) != 1 else ""
        next_steps.append(
            f"Decide the {len(asks)} board ask{plural} on the decisions slide"
        )
    if not next_steps:
        next_steps.append("Hold the cadence – re-observe on schedule and diff next cycle")

    return {
        "headline": "",
        "bullets": bullets[:5],
        "titles": {},
        "commentary": {},
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
        s, 0.7, 1.55, 11.9, 1.9, _clean(title, 90),
        size=40, bold=True, color=_WHITE, line=1.06,
    )
    _text(s, 0.7, 3.55, 11.0, 0.5, _clean(period, 120), size=15, color=_MUTED)
    _rule(s, 4.35)
    _text(s, 0.7, 4.6, 11.9, 0.4, _clean(basis, 160), size=11, color=_MUTED)
    try:
        month = datetime.fromisoformat(generated).strftime("%B %Y")
    except Exception:
        month = datetime.now(UTC).strftime("%B %Y")
    _text(s, 0.7, 6.75, 5.0, 0.3, month, size=10, color=_MUTED)


def _slide_summary(
    prs: Any, narrative: dict[str, Any], page: int, deck_title: str
) -> None:
    s = _blank(prs)
    _eyebrow(s, "Executive summary", y=0.5)
    headline = _clean(narrative.get("headline") or "", 110)
    y = 0.85
    if headline:
        _text(s, 0.7, y, 11.9, 1.15, headline, size=25, bold=True, line=1.1)
        y += 1.25
    _rule(s, y)
    y += 0.3
    _bullets(
        s, 0.7, y, 11.9, 6.4 - y,
        [str(b) for b in narrative.get("bullets") or []],
        size=15, gap_pt=12, cap=140,
    )
    _judgement_note(s, str(narrative.get("source") or "facts"))
    _footer(s, deck_title, page)
    _notes(
        s,
        "Every line traces to the scorecard, the material-change diff or the "
        "evidence register. Nothing on this slide is a new fact.",
    )


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
        1 for r in rows for d in r.get("dimensions", {}).values()
        if d.get("score") is not None
    )
    pct = (observed / pairs * 100.0) if pairs else 0.0

    tiles = [
        (
            _fmt(leader["overall"]["normalized_pct"]) if leader else "—",
            f"{leader['name']} – ranked leader" if leader else "no brand ranked yet",
        ),
        (f"{len(ranked)} / {len(rows)}", "brands ranked / tracked"),
        (f"{pct:.0f}%", f"of the model observed – {observed} of {pairs} pairs"),
        (f"{evidence_count:,}", "evidence items, each traceable to a source"),
    ]
    x = 0.7
    w = 12.0 / len(tiles)
    for value, label in tiles:
        _text(s, x, 2.6, w - 0.35, 1.0, str(value)[:14], size=34, bold=True)
        _text(s, x, 3.62, w - 0.35, 0.75, _clean(label, 70), size=10.5, color=_MUTED)
        x += w
    if commentary:
        _text(
            s, 0.7, 5.0, 11.9, 0.5, _clean(commentary, 170),
            size=12.5, italic=True, color=_BODY,
        )
    _footer(s, deck_title, page)


def _slide_standings(
    prs: Any, card: dict[str, Any], narrative: dict[str, Any], page: int,
    deck_title: str,
) -> None:
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
    from pptx.util import Inches, Pt

    s = _blank(prs)
    title = (narrative.get("titles") or {}).get("standings") or "Where the market stands"
    top = _header(
        s, "Standings", title,
        (narrative.get("commentary") or {}).get("standings", ""),
    )

    rows = card.get("rows", [])
    ranked = [r for r in rows if r.get("rank") is not None]
    provisional = [
        r for r in rows
        if r.get("provisional") and r["overall"]["normalized_pct"] is not None
    ]
    unscored = [r for r in rows if r["overall"]["normalized_pct"] is None]

    if ranked:
        shown = ranked[:12]
        cd = CategoryChartData()
        cd.categories = [
            f"{r['name']}{'  (us)' if r.get('is_self') else ''}"
            for r in reversed(shown)
        ]
        cd.add_series(
            "Overall (normalized %)",
            [round(float(r["overall"]["normalized_pct"]), 1) for r in reversed(shown)],
        )
        gf = s.shapes.add_chart(
            XL_CHART_TYPE.BAR_CLUSTERED, Inches(0.7), Inches(top),
            Inches(8.1), Inches(6.6 - top), cd,
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
                s, 0.7, 6.62, 8.1, 0.3,
                f"Top {len(shown)} of {len(ranked)} ranked brands shown.",
                size=9, color=_MUTED,
            )
    else:
        _text(
            s, 0.7, top + 0.2, 8.1, 1.0,
            "No brand has yet been scored on enough of the model to hold a rank.",
            size=15, color=_BODY,
        )

    x = 9.1
    _text(
        s, x, top, 3.5, 0.55,
        "Overall score, normalized to the weight actually measured. "
        "Amber – our brand.",
        size=9.5, color=_MUTED,
    )
    y = top + 0.75
    if provisional:
        _eyebrow(s, "Scored, not ranked †", y=y, x=x)
        y += 0.32
        lines = [
            f"{r['name']}: {_fmt(r['overall']['normalized_pct'])} – "
            f"{r.get('provisional_reason', 'thin evidence')}"
            for r in provisional[:4]
        ]
        _bullets(
            s, x, y, 3.5, 2.6, lines,
            size=9, color=_MUTED, gap_pt=5, cap=120, accent_bullet=False,
        )
        y += min(2.6, 0.55 * len(lines)) + 0.25
    if unscored and y < 6.2:
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
    prs: Any, card: dict[str, Any], narrative: dict[str, Any], page: int,
    deck_title: str,
) -> None:
    s = _blank(prs)
    rows = card.get("rows", [])
    us = next((r for r in rows if r.get("is_self")), None)
    leader = next(
        (r for r in rows if r.get("rank") is not None and not r.get("is_self")),
        None,
    )
    title = (narrative.get("titles") or {}).get("versus") or "Where we win, where we lose"
    top = _header(
        s, "Versus the leader", title,
        (narrative.get("commentary") or {}).get("versus", ""),
    )

    if us is None:
        _text(
            s, 0.7, top + 0.2, 11.9, 1.0,
            "No brand is marked as ours, so there is nothing to compare. Mark "
            "one with watch_subject is_self=true and this slide fills in.",
            size=14, color=_BODY,
        )
        _footer(s, deck_title, page)
        return
    if leader is None:
        _text(
            s, 0.7, top + 0.2, 11.9, 1.0,
            f"{us['name']} is the only ranked brand so far – no peer holds a "
            "rank yet to compare against.",
            size=14, color=_BODY,
        )
        _footer(s, deck_title, page)
        return

    _text(
        s, 0.7, top, 11.9, 0.45,
        f"{us['name']}  {_fmt(us['overall']['normalized_pct'])}   vs   "
        f"{leader['name']} (#{leader['rank']})  "
        f"{_fmt(leader['overall']['normalized_pct'])}",
        size=15, bold=True,
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
        ("Ahead", _ACCENT,
         [entry for _, entry in ahead[:5]] or ["Nowhere yet, on measured dimensions."],
         0.7, 3.9, _BODY),
        ("Behind", _PEER,
         [entry for _, entry in behind[:5]] or ["Nowhere, on measured dimensions."],
         4.95, 3.9, _BODY),
        ("Not comparable yet", _MUTED,
         unmeasured[:7] or ["Every dimension is measured on both."],
         9.2, 3.4, _MUTED),
    ]
    for label, label_color, items, x, w, body_color in cols:
        _eyebrow(s, label, y=top, x=x, color=label_color)
        _bullets(
            s, x, top + 0.35, w, 6.2 - top, items,
            size=10.5, color=body_color, gap_pt=6, cap=110, accent_bullet=False,
        )
    _text(
        s, 0.7, 6.72, 11.9, 0.3,
        "A dimension unscored on either side is listed as not comparable – "
        "never counted as a loss.",
        size=9, color=_MUTED,
    )
    _footer(s, deck_title, page)


def _slide_changes(
    prs: Any, diff: dict[str, Any] | None, narrative: dict[str, Any], page: int,
    deck_title: str,
) -> None:
    s = _blank(prs)
    commentary = (narrative.get("commentary") or {}).get("changes", "")
    if diff is None:
        _header(s, "Material changes", "Baseline established", commentary)
        _text(
            s, 0.7, 2.5, 11.9, 1.2,
            "First reporting cycle. There is no prior snapshot to compare "
            "against, so this pack sets the baseline; the next cycle shows "
            "what moved.",
            size=15, color=_BODY,
        )
        _footer(s, deck_title, page)
        return
    n = int(diff.get("material_count", 0))
    title = (
        (narrative.get("titles") or {}).get("changes")
        or f"{n} material change{'s' if n != 1 else ''} this period"
    )
    top = _header(s, "Material changes", title, commentary)
    _text(
        s, 0.7, top - 0.05, 11.9, 0.3,
        f"{str(diff.get('from_generated_at', '?'))[:10]} → "
        f"{str(diff.get('to_generated_at', '?'))[:10]}",
        size=10, color=_MUTED,
    )
    top += 0.3
    if n == 0:
        th = diff.get("thresholds", {})
        _text(
            s, 0.7, top + 0.2, 11.9, 1.2,
            "Nothing moved above the materiality threshold "
            f"(score move ≥ {th.get('min_score_delta', 1.0)}, coverage shift ≥ "
            f"{th.get('min_coverage_delta', 0)}%). Sub-threshold wobble is "
            "suppressed on purpose.",
            size=15, color=_BODY,
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
        s, 0.7, top, 5.9, 6.5 - top, shown[:half],
        size=11.5, gap_pt=7, cap=120, accent_bullet=False,
    )
    _bullets(
        s, 6.85, top, 5.8, 6.5 - top, shown[half:],
        size=11.5, gap_pt=7, cap=120, accent_bullet=False,
    )
    if len(lines) > len(shown):
        _text(
            s, 0.7, 6.55, 11.9, 0.3,
            f"+{len(lines) - len(shown)} more in the board report.",
            size=9, color=_MUTED,
        )
    _footer(s, deck_title, page)


def _slide_implications(
    prs: Any, judged: list[dict[str, Any]], material_count: int, source: str,
    page: int, deck_title: str,
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
        key=lambda j: _CLASS_ORDER.index(j.get("classification", "monitor"))
        if j.get("classification") in _CLASS_ORDER
        else len(_CLASS_ORDER),
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
            len(chunk) + 1, len(cols), Inches(0.7), Inches(top),
            Inches(sum(widths)), Inches(0.42 * (len(chunk) + 1)),
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
    prs: Any, judged: list[dict[str, Any]], source: str, material_count: int,
    page: int, deck_title: str,
) -> None:
    s = _blank(prs)
    top = _header(s, "The ask", "Decisions required")
    asks = [
        f"{j.get('subject', '')}: {j.get('decision_required', '')}"
        for j in judged
        if str(j.get("decision_required", "none")).strip().lower() not in ("", "none")
    ]
    if asks:
        _bullets(s, 0.7, top + 0.2, 11.9, 6.4 - top, asks[:6], size=15,
                 gap_pt=12, cap=140)
        _judgement_note(s, source)
    elif judged:
        _text(
            s, 0.7, top + 0.3, 11.9, 1.0,
            "No board decision is required this period.", size=17, color=_BODY,
        )
        _judgement_note(s, source)
    elif material_count:
        _text(
            s, 0.7, top + 0.3, 11.9, 1.4,
            f"Not yet evaluated – {material_count} material change"
            f"{'s' if material_count != 1 else ''} recorded, but no model was "
            "available to judge what they require of the board.",
            size=17, color=_BODY,
        )
    else:
        _text(
            s, 0.7, top + 0.3, 11.9, 1.0,
            "No material change this period, so nothing new to decide.",
            size=17, color=_BODY,
        )
    _footer(s, deck_title, page)


def _slide_evidence(
    prs: Any, card: dict[str, Any], gaps: list[dict[str, Any]],
    evidence_count: int, narrative: dict[str, Any], page: int, deck_title: str,
) -> None:
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    s = _blank(prs)
    title = (narrative.get("titles") or {}).get("coverage") or "How much of this is measured"
    top = _header(
        s, "Evidence and confidence", title,
        (narrative.get("commentary") or {}).get("coverage", ""),
    )
    rows = card.get("rows", [])
    dims = card.get("dimensions", [])
    pairs = len(rows) * len(dims)
    observed = sum(
        1 for r in rows for d in r.get("dimensions", {}).values()
        if d.get("score") is not None
    )
    never = [g for g in gaps if g.get("status") == "never_observed"]
    stale = [g for g in gaps if g.get("status") == "stale"]
    pct = (observed / pairs * 100.0) if pairs else 0.0

    tiles = [
        (f"{pct:.0f}%", f"of the model observed – {observed} of {pairs} "
                        "brand × dimension pairs"),
        (f"{evidence_count:,}", "evidence items on file, each quoting a source URL"),
        (f"{len(never)}", "pairs never observed – no score, no penalty"),
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
            s, 0.7, y, 11.9, 0.35,
            "Not yet observed: " + ", ".join(never_brands[:6]) + more,
            size=11.5, color=_BODY,
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
        s, 0.95, card_y + 0.12, 11.4, 0.65,
        "Gaps are absences of evidence, not weaknesses. No brand is scored "
        "down for being opaque, and no score on any slide exists without a "
        "source behind it.",
        size=11.5, color=_INK,
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
        len(rows) + 1, ncols, Inches(0.7), Inches(top), Inches(total_w),
        Inches(min(0.32 * (len(rows) + 1), 6.6 - top)),
    )
    tbl = shape.table
    tbl.columns[0].width = Inches(first_w)
    tbl.columns[1].width = Inches(0.9)
    for ci in range(len(dims)):
        tbl.columns[2 + ci].width = Inches(dim_w)

    def cell_write(r: int, c: int, text: str, *, bg: str, fg: str = _INK,
                   bold: bool = False, size: int = 8) -> None:
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
        cell_write(0, 2 + ci, d, bg=_INK, fg=_WHITE, bold=True, size=7)
    for ri, r in enumerate(rows, start=1):
        bg = _SELF_ROW if r.get("is_self") else _WHITE
        mark = (
            "†"
            if r.get("provisional") and r["overall"]["normalized_pct"] is not None
            else ""
        )
        cell_write(
            ri, 0, f"{r['name']}{'  (us)' if r.get('is_self') else ''}",
            bg=bg, bold=bool(r.get("is_self")),
        )
        cell_write(ri, 1, f"{_fmt(r['overall']['normalized_pct'])}{mark}", bg=bg)
        for ci, d in enumerate(dims):
            sc = r.get("dimensions", {}).get(d, {}).get("score")
            if sc is None:
                cell_write(ri, 2 + ci, "", bg=_GAP_BG)  # blank, never a zero
            else:
                cell_write(ri, 2 + ci, f"{float(sc):g}", bg=bg)
    _text(
        s, 0.7, 6.62, 11.9, 0.3,
        "1–5 per dimension. Blank – not yet observed (never a zero). "
        "† provisional. Amber row – our brand.",
        size=9, color=_MUTED,
    )
    _footer(s, deck_title, page)


def _slide_method(
    prs: Any, card: dict[str, Any], diff: dict[str, Any] | None, page: int,
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
        "carries the network exit that was proven to be in that state.",
        change_rule,
        "Narrative, titles and commentary are model-written from the factual "
        "record and labelled; standings, scores and gaps are computed.",
    ]
    _bullets(
        s, 0.7, top + 0.1, 11.9, 6.5 - top, items[:6],
        size=11.5, gap_pt=7, cap=220, accent_bullet=False,
    )
    _footer(s, deck_title, page)


def _slide_closing(prs: Any, narrative: dict[str, Any], deck_title: str) -> None:
    s = _blank(prs)
    _dark(s)
    _eyebrow(s, "Next steps", y=1.0)
    _text(s, 0.7, 1.4, 11.9, 1.0, "Where this goes next", size=30, bold=True,
          color=_WHITE)
    _rule(s, 2.5)
    steps = [str(b) for b in narrative.get("next_steps") or []][:4]
    if not steps:
        steps = ["Hold the cadence – re-observe on schedule and diff next cycle"]
    _bullets(s, 0.7, 2.85, 11.4, 3.4, steps, size=15, color=_DARK_BODY,
             gap_pt=14, cap=120)
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
    title: str = "Competitive Intelligence – Executive Briefing",
    market_label: str = "",
) -> str:
    """Write the deck. Returns the path written.

    ``summary`` is the narrative dict — ``{headline, bullets, titles,
    commentary, next_steps, source}`` — model-written when a router exists,
    otherwise :func:`factual_narrative`'s computed fallback. The renderer
    treats every narrative string as untrusted copy: capped, en-dashed and
    scrubbed of internal bookkeeping.
    """
    from pptx import Presentation
    from pptx.util import Inches

    narrative = summary or {}
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    rows = card.get("rows", [])
    dims = card.get("dimensions", [])
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
        "evidence items · every score traceable to a source URL"
    )
    deck_title = _clean(title, 70)
    src = str(narrative.get("source") or "facts")

    _slide_title(
        prs, title=title, market=market_label, period=period, basis=basis,
        generated=generated,
    )
    page = 2
    _slide_summary(prs, narrative, page, deck_title)
    page += 1
    _slide_glance(
        prs, card, evidence_count, gaps,
        (narrative.get("commentary") or {}).get("glance", ""), page, deck_title,
    )
    page += 1
    _slide_standings(prs, card, narrative, page, deck_title)
    page += 1
    _slide_versus(prs, card, narrative, page, deck_title)
    page += 1
    _slide_changes(prs, diff, narrative, page, deck_title)
    page += 1
    page += _slide_implications(
        prs, judged, int((diff or {}).get("material_count", 0)), src, page,
        deck_title,
    )
    _slide_decisions(
        prs, judged, src, int((diff or {}).get("material_count", 0)), page,
        deck_title,
    )
    page += 1
    _slide_evidence(prs, card, gaps, evidence_count, narrative, page, deck_title)
    page += 1
    _slide_heatmap(prs, card, page, deck_title)
    page += 1
    _slide_method(prs, card, diff, page, deck_title)
    page += 1
    _slide_closing(prs, narrative, deck_title)

    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    logger.info("Executive deck written: %s (%d slides)", out, len(prs.slides))
    return str(out)
