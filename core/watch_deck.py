"""Executive deck rendering for the competitive-intelligence organ.

The scorecard workbook is for the analyst and the board report is for the
reader; this is for the room. Ten-odd 16:9 slides, one message each, built
from the *same* stored evidence as the other deliverables — nothing here is
computed differently, it is only said more briefly.

Three rules the rest of the organ enforces survive the trip onto a slide,
because a slide is where they are most easily lost:

* **Unscored is blank, never zero.** A brand with no evidence on a dimension
  gets an empty cell in the heatmap and no bar in the standings chart. A zero
  bar reads as "worst"; the truth is "not yet observed".
* **Provisional brands are not ranked.** A brand scored on too little of the
  model sits below the chart with a dagger and its reason, not in it. The
  standings chart is the one picture in the pack that gets trusted without
  reading the footnote.
* **Facts and judgement are labelled.** The executive summary and the
  implications are written by a model from the factual record, and each of
  those slides says so. When no model is available the summary is built from
  the numbers alone and says *that*.

Charts are native PowerPoint charts, not images, so the customer can restyle
or lift them into their own template.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Slate / amber / grey — the same palette as the workbook so the pack reads
# as one thing.
_INK = (0x1F, 0x29, 0x37)  # slate-800
_MUTED = (0x6B, 0x72, 0x80)  # gray-500
_RULE = (0xD1, 0xD5, 0xDB)  # gray-300
_SELF = (0xD9, 0x77, 0x06)  # amber-600 — our own brands
_PEER = (0x64, 0x74, 0x8B)  # slate-500 — everyone else
_GAP_BG = (0xF3, 0xF4, 0xF6)  # gray-100 — no evidence
_SELF_BG = (0xFE, 0xF3, 0xC7)  # amber-100
_HEAD_BG = (0x1F, 0x29, 0x37)
_WHITE = (0xFF, 0xFF, 0xFF)

_CLASS_LABEL = {
    "no_regret": "No-regret",
    "transition_requirement": "Transition requirement",
    "post_transition": "Post-transition",
    "monitor": "Monitor",
}
_CLASS_ORDER = ["no_regret", "transition_requirement", "post_transition", "monitor"]


# ── tiny drawing helpers ─────────────────────────────────────────────


def _rgb(t: tuple[int, int, int]) -> Any:
    from pptx.dml.color import RGBColor

    return RGBColor(*t)


def _text(
    slide: Any,
    left: float,
    top: float,
    width: float,
    height: float,
    text: str,
    *,
    size: int = 14,
    bold: bool = False,
    color: tuple[int, int, int] = _INK,
    align: str = "left",
    wrap: bool = True,
) -> Any:
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = box.text_frame
    tf.word_wrap = wrap
    p = tf.paragraphs[0]
    p.text = text
    p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}[align]
    for r in p.runs:
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = _rgb(color)
    return box


def _bullets(
    slide: Any,
    left: float,
    top: float,
    width: float,
    height: float,
    items: list[str],
    *,
    size: int = 16,
    color: tuple[int, int, int] = _INK,
    gap_pt: int = 8,
) -> Any:
    from pptx.util import Inches, Pt

    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = box.text_frame
    tf.word_wrap = True
    first = True
    for item in items:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.text = f"•  {item}"
        p.space_after = Pt(gap_pt)
        for r in p.runs:
            r.font.size = Pt(size)
            r.font.color.rgb = _rgb(color)
    return box


def _rule(slide: Any, top: float, *, left: float = 0.6, width: float = 12.1) -> None:
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    ln = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(left), Inches(top), Inches(width), Pt(1.2)
    )
    ln.fill.solid()
    ln.fill.fore_color.rgb = _rgb(_RULE)
    ln.line.fill.background()


def _header(slide: Any, title: str, *, kicker: str = "") -> None:
    if kicker:
        _text(slide, 0.6, 0.35, 12.0, 0.3, kicker.upper(), size=10, color=_MUTED)
    _text(slide, 0.6, 0.6, 12.0, 0.8, title, size=28, bold=True)
    _rule(slide, 1.45)


def _footer(slide: Any, text: str, page: int) -> None:
    _text(slide, 0.6, 7.05, 10.5, 0.3, text, size=9, color=_MUTED)
    _text(slide, 11.6, 7.05, 1.1, 0.3, str(page), size=9, color=_MUTED, align="right")


def _judgement_note(slide: Any, source: str) -> None:
    """The label that keeps fact and judgement apart on the slide itself."""
    msg = (
        "Judgement written by the model from the factual record — verify before presenting."
        if source == "model"
        else "Facts only — no model was available, so no judgement has been applied."
    )
    _text(slide, 0.6, 6.7, 12.0, 0.3, msg, size=9, color=_MUTED)


def _notes(slide: Any, text: str) -> None:
    slide.notes_slide.notes_text_frame.text = text


def _fmt(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}"


# ── slide builders ───────────────────────────────────────────────────


def _blank(prs: Any) -> Any:
    return prs.slides.add_slide(prs.slide_layouts[6])


def _slide_title(prs: Any, *, title: str, market: str, period: str, basis: str) -> None:
    s = _blank(prs)
    _text(s, 0.8, 2.2, 11.5, 1.2, title, size=36, bold=True)
    if market:
        _text(s, 0.8, 3.3, 11.5, 0.6, market, size=20, color=_MUTED)
    _rule(s, 4.05, left=0.8, width=11.5)
    _text(s, 0.8, 4.2, 11.5, 0.4, period, size=14, color=_MUTED)
    _text(s, 0.8, 6.3, 11.5, 0.6, basis, size=11, color=_MUTED)


def _slide_summary(prs: Any, summary: dict[str, Any], page: int, foot: str) -> None:
    s = _blank(prs)
    _header(s, "Executive summary")
    headline = str(summary.get("headline") or "").strip()
    if headline:
        _text(s, 0.6, 1.7, 12.0, 0.9, headline, size=20, bold=True)
    bullets = [str(b) for b in summary.get("bullets") or [] if str(b).strip()]
    _bullets(s, 0.6, 2.7 if headline else 1.7, 12.0, 3.8, bullets, size=16)
    _judgement_note(s, str(summary.get("source") or "facts"))
    _footer(s, foot, page)
    _notes(
        s,
        "Every bullet traces to the scorecard, the material-change diff "
        "or the evidence register. Nothing on this slide is a new fact.",
    )


def _slide_standings(prs: Any, card: dict[str, Any], page: int, foot: str) -> None:
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
    from pptx.util import Inches, Pt

    s = _blank(prs)
    _header(s, "Where the market stands", kicker="Standings")

    rows = card.get("rows", [])
    ranked = [r for r in rows if r.get("rank") is not None]
    provisional = [
        r for r in rows if r.get("provisional") and r["overall"]["normalized_pct"] is not None
    ]
    unscored = [r for r in rows if r["overall"]["normalized_pct"] is None]

    if ranked:
        # Bars run top-to-bottom in rank order; python-pptx plots categories
        # bottom-up, so feed them reversed.
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
            Inches(0.6),
            Inches(1.7),
            Inches(8.2),
            Inches(4.9),
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
        plot.gap_width = 60
        plot.has_data_labels = True
        dl = plot.data_labels
        dl.font.size = Pt(10)
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
                pt.format.fill.fore_color.rgb = _rgb(_SELF)
        if len(ranked) > len(shown):
            _text(
                s,
                0.6,
                6.55,
                8.2,
                0.3,
                f"Top {len(shown)} of {len(ranked)} ranked brands shown.",
                size=9,
                color=_MUTED,
            )
    else:
        _text(
            s,
            0.6,
            1.8,
            8.2,
            1.0,
            "No brand has yet been scored on enough of the model to hold a rank.",
            size=16,
            color=_MUTED,
        )

    # Right-hand column: what the chart deliberately leaves out.
    y = 1.7
    _text(
        s,
        9.1,
        y,
        3.6,
        0.3,
        "Overall score, normalized to the weight actually measured. Amber = our brand.",
        size=10,
        color=_MUTED,
    )
    y += 0.75
    if provisional:
        _text(s, 9.1, y, 3.6, 0.3, "† Provisional — scored, not ranked", size=11, bold=True)
        y += 0.35
        lines = [
            f"{r['name']}: {_fmt(r['overall']['normalized_pct'])} — "
            f"{r.get('provisional_reason', 'thin evidence')}"
            for r in provisional[:4]
        ]
        _bullets(s, 9.1, y, 3.6, 2.2, lines, size=9, color=_MUTED, gap_pt=4)
        y += 0.5 * len(lines) + 0.4
    if unscored:
        _text(s, 9.1, y, 3.6, 0.3, "Not yet observed", size=11, bold=True)
        y += 0.35
        names = ", ".join(r["name"] for r in unscored[:8])
        if len(unscored) > 8:
            names += f" +{len(unscored) - 8} more"
        _text(s, 9.1, y, 3.6, 1.2, names, size=9, color=_MUTED)

    _footer(s, foot, page)
    _notes(
        s,
        "Provisional brands are omitted from the chart on purpose: a bar "
        "is trusted without its footnote. Their scores are real; the "
        "standing is not yet earned. Unscored brands are not drawn as 0.",
    )


def _slide_versus(prs: Any, card: dict[str, Any], page: int, foot: str) -> None:
    """Our brand against the ranked leader, dimension by dimension."""
    s = _blank(prs)
    rows = card.get("rows", [])
    us = next((r for r in rows if r.get("is_self")), None)
    leader = next((r for r in rows if r.get("rank") is not None and not r.get("is_self")), None)
    _header(s, "Where we win, where we lose", kicker="Versus the leader")

    if us is None:
        _text(
            s,
            0.6,
            1.8,
            12.0,
            1.0,
            "No brand is marked as ours, so there is nothing to compare. "
            "Mark one with `watch_subject is_self=true` and this slide fills in.",
            size=16,
            color=_MUTED,
        )
        _footer(s, foot, page)
        return
    if leader is None:
        _text(
            s,
            0.6,
            1.8,
            12.0,
            1.0,
            f"{us['name']} is the only ranked brand so far — no peer holds a "
            "rank yet to compare against.",
            size=16,
            color=_MUTED,
        )
        _footer(s, foot, page)
        return

    _text(
        s,
        0.6,
        1.65,
        12.0,
        0.4,
        f"{us['name']}  {_fmt(us['overall']['normalized_pct'])}   vs   "
        f"{leader['name']} (#{leader['rank']})  "
        f"{_fmt(leader['overall']['normalized_pct'])}",
        size=16,
        bold=True,
    )

    ahead: list[tuple[float, str]] = []
    behind: list[tuple[float, str]] = []
    unmeasured: list[str] = []
    weights = {d["name"]: d["weight_pct"] for d in card.get("dimensions", [])}
    for dname, ours in us.get("dimensions", {}).items():
        theirs = leader.get("dimensions", {}).get(dname, {})
        a, b = ours.get("score"), theirs.get("score")
        if a is None or b is None:
            unmeasured.append(dname)
            continue
        delta = float(a) - float(b)
        line = f"{dname}  ({a:g} vs {b:g}, weight {weights.get(dname, 0):g}%)"
        if delta > 0:
            ahead.append((delta, line))
        elif delta < 0:
            behind.append((-delta, line))
    ahead.sort(key=lambda t: -t[0])
    behind.sort(key=lambda t: -t[0])

    _text(s, 0.6, 2.3, 4.0, 0.3, "Ahead", size=13, bold=True, color=_SELF)
    _bullets(
        s,
        0.6,
        2.65,
        4.0,
        3.9,
        [line for _, line in ahead[:5]] or ["Nowhere yet, on measured dimensions."],
        size=11,
        gap_pt=5,
    )
    _text(s, 4.9, 2.3, 4.0, 0.3, "Behind", size=13, bold=True, color=_PEER)
    _bullets(
        s,
        4.9,
        2.65,
        4.0,
        3.9,
        [line for _, line in behind[:5]] or ["Nowhere, on measured dimensions."],
        size=11,
        gap_pt=5,
    )
    _text(s, 9.2, 2.3, 3.5, 0.3, "Not comparable yet", size=13, bold=True, color=_MUTED)
    _bullets(
        s,
        9.2,
        2.65,
        3.5,
        3.9,
        unmeasured[:8] or ["Every dimension is measured on both."],
        size=11,
        color=_MUTED,
        gap_pt=5,
    )
    if len(unmeasured) > 8:
        _text(s, 9.2, 6.4, 3.5, 0.3, f"+{len(unmeasured) - 8} more", size=9, color=_MUTED)
    _text(
        s,
        0.6,
        6.7,
        12.0,
        0.3,
        "A dimension unscored on either side is listed as not comparable — "
        "never counted as a loss.",
        size=9,
        color=_MUTED,
    )
    _footer(s, foot, page)


def _slide_changes(prs: Any, diff: dict[str, Any] | None, page: int, foot: str) -> None:
    s = _blank(prs)
    if diff is None:
        _header(s, "Baseline established", kicker="Material changes")
        _text(
            s,
            0.6,
            1.8,
            12.0,
            1.4,
            "First reporting cycle. There is no prior snapshot to compare "
            "against, so this pack sets the baseline; the next cycle shows "
            "what moved.",
            size=16,
            color=_MUTED,
        )
        _footer(s, foot, page)
        return
    n = int(diff.get("material_count", 0))
    _header(s, f"{n} material change{'s' if n != 1 else ''} this period", kicker="Material changes")
    _text(
        s,
        0.6,
        1.6,
        12.0,
        0.3,
        f"{diff.get('from_generated_at', '?')[:10]} → {diff.get('to_generated_at', '?')[:10]}",
        size=10,
        color=_MUTED,
    )
    if n == 0:
        th = diff.get("thresholds", {})
        _text(
            s,
            0.6,
            2.1,
            12.0,
            1.4,
            "Nothing moved above the materiality threshold "
            f"(score move ≥ {th.get('min_score_delta', 1.0)}, coverage shift ≥ "
            f"{th.get('min_coverage_delta', 0)}%). Sub-threshold wobble is "
            "suppressed on purpose.",
            size=16,
            color=_MUTED,
        )
        _footer(s, foot, page)
        return
    lines: list[str] = []
    for c in diff.get("changed", []):
        for item in c.get("items", []):
            lines.append(f"{c['subject']} — {item.get('detail', '')}")
    if diff.get("added_subjects"):
        lines.append("New in the analysis: " + ", ".join(diff["added_subjects"]))
    if diff.get("removed_subjects"):
        lines.append("Removed: " + ", ".join(diff["removed_subjects"]))
    _bullets(s, 0.6, 2.0, 12.0, 4.6, lines[:12], size=13, gap_pt=6)
    if len(lines) > 12:
        _text(
            s,
            0.6,
            6.5,
            12.0,
            0.3,
            f"+{len(lines) - 12} more in the board report.",
            size=9,
            color=_MUTED,
        )
    _footer(s, foot, page)


def _slide_implications(
    prs: Any, judged: list[dict[str, Any]], material_count: int, source: str, page: int, foot: str
) -> int:
    """One or more slides; returns the number added."""
    from pptx.util import Inches, Pt

    if not judged:
        s = _blank(prs)
        _header(s, "Implications and recommendations", kicker="Judgement")
        if material_count:
            _text(
                s,
                0.6,
                1.8,
                12.0,
                1.4,
                "Implications were not generated — no model was available. "
                "The material changes are the factual record; judgement "
                "still needs to be applied.",
                size=16,
                color=_MUTED,
            )
        else:
            _text(
                s,
                0.6,
                1.8,
                12.0,
                1.4,
                "No material change this period, so there is nothing new to act on.",
                size=16,
                color=_MUTED,
            )
        _footer(s, foot, page)
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
    pages = [ordered[i : i + per] for i in range(0, len(ordered), per)]
    for pi, chunk in enumerate(pages):
        s = _blank(prs)
        suffix = f" ({pi + 1}/{len(pages)})" if len(pages) > 1 else ""
        _header(s, f"Implications and recommendations{suffix}", kicker="Judgement")
        cols = ["Subject", "Change", "Implication", "Recommendation", "Class"]
        widths = [1.6, 2.6, 3.2, 3.2, 1.5]
        shape = s.shapes.add_table(
            len(chunk) + 1,
            len(cols),
            Inches(0.6),
            Inches(1.7),
            Inches(sum(widths)),
            Inches(0.4 * (len(chunk) + 1)),
        )
        tbl = shape.table
        for ci, w in enumerate(widths):
            tbl.columns[ci].width = Inches(w)
        for ci, name in enumerate(cols):
            cell = tbl.cell(0, ci)
            cell.text = name
            cell.fill.solid()
            cell.fill.fore_color.rgb = _rgb(_HEAD_BG)
            for p in cell.text_frame.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(10)
                    r.font.bold = True
                    r.font.color.rgb = _rgb(_WHITE)
        for ri, j in enumerate(chunk, start=1):
            vals = [
                str(j.get("subject", "")),
                str(j.get("change", "")),
                str(j.get("implication", "")),
                str(j.get("recommendation", "")),
                _CLASS_LABEL.get(str(j.get("classification", "monitor")), "Monitor"),
            ]
            for ci, v in enumerate(vals):
                cell = tbl.cell(ri, ci)
                cell.text = v
                cell.fill.solid()
                cell.fill.fore_color.rgb = _rgb(_WHITE if ri % 2 else _GAP_BG)
                for p in cell.text_frame.paragraphs:
                    for r in p.runs:
                        r.font.size = Pt(9)
                        r.font.color.rgb = _rgb(_INK)
        _judgement_note(s, source)
        _footer(s, foot, page + pi)
        _notes(
            s,
            "Classification uses the no-regret test: would we still be "
            "pleased we did this if the transition plan, rankings or "
            "priorities changed next month?",
        )
    return len(pages)


def _slide_decisions(
    prs: Any, judged: list[dict[str, Any]], source: str, material_count: int, page: int, foot: str
) -> None:
    s = _blank(prs)
    _header(s, "Decisions required", kicker="The ask")
    asks = [
        f"{j.get('subject', '')}: {j.get('decision_required', '')}"
        for j in judged
        if str(j.get("decision_required", "none")).strip().lower() not in ("", "none")
    ]
    if asks:
        _bullets(s, 0.6, 1.8, 12.0, 4.6, asks[:8], size=15, gap_pt=8)
        _judgement_note(s, source)
    elif judged:
        _text(
            s,
            0.6,
            1.8,
            12.0,
            1.0,
            "No board decision is required this period.",
            size=18,
            color=_MUTED,
        )
        _judgement_note(s, source)
    elif material_count:
        # "None required" and "not evaluated" must never look alike.
        _text(
            s,
            0.6,
            1.8,
            12.0,
            1.4,
            f"Not yet evaluated — {material_count} material change"
            f"{'s' if material_count != 1 else ''} recorded, but no model was "
            "available to judge what they require of the board.",
            size=18,
            color=_MUTED,
        )
    else:
        _text(
            s,
            0.6,
            1.8,
            12.0,
            1.0,
            "No material change this period, so nothing new to decide.",
            size=18,
            color=_MUTED,
        )
    _footer(s, foot, page)


def _slide_evidence(
    prs: Any,
    card: dict[str, Any],
    gaps: list[dict[str, Any]],
    evidence_count: int,
    page: int,
    foot: str,
) -> None:
    from pptx.util import Inches, Pt

    s = _blank(prs)
    _header(s, "How much of this is measured", kicker="Evidence and confidence")
    rows = card.get("rows", [])
    dims = card.get("dimensions", [])
    pairs = len(rows) * len(dims)
    observed = sum(
        1 for r in rows for d in r.get("dimensions", {}).values() if d.get("score") is not None
    )
    never = [g for g in gaps if g.get("status") == "never_observed"]
    stale = [g for g in gaps if g.get("status") == "stale"]
    pct = (observed / pairs * 100.0) if pairs else 0.0
    conf: dict[str, int] = {}
    for r in rows:
        c = str(r["overall"].get("confidence") or "low")
        conf[c] = conf.get(c, 0) + 1

    tiles = [
        (f"{pct:.0f}%", "of the model observed", f"{observed} of {pairs} brand × dimension pairs"),
        (f"{evidence_count:,}", "evidence items on file", "each quoting a source URL"),
        (f"{len(never)}", "pairs never observed", "no score, no penalty"),
        (f"{len(stale)}", "overdue a refresh", "against their cadence"),
    ]
    x = 0.6
    for big, label, sub in tiles:
        _text(s, x, 1.8, 2.9, 0.9, big, size=40, bold=True)
        _text(s, x, 2.7, 2.9, 0.4, label, size=12, bold=True)
        _text(s, x, 3.05, 2.9, 0.4, sub, size=10, color=_MUTED)
        x += 3.05

    _rule(s, 3.7)
    conf_line = "   ".join(f"{k}: {v}" for k, v in sorted(conf.items()))
    _text(s, 0.6, 3.85, 12.0, 0.35, f"Confidence roll-up across brands — {conf_line}", size=12)
    if never:
        ex = ", ".join(f"{g['subject']} / {g['dimension']}" for g in never[:5])
        _text(s, 0.6, 4.3, 12.0, 0.6, f"Not yet observed, e.g. {ex}", size=11, color=_MUTED)
    if stale:
        ex = ", ".join(f"{g['subject']} / {g['dimension']}" for g in stale[:5])
        _text(s, 0.6, 4.85, 12.0, 0.6, f"Overdue, e.g. {ex}", size=11, color=_MUTED)

    from pptx.enum.shapes import MSO_SHAPE

    box = s.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(5.6), Inches(12.1), Inches(0.9)
    )
    box.fill.solid()
    box.fill.fore_color.rgb = _rgb(_SELF_BG)
    box.line.fill.background()
    tf = box.text_frame
    tf.word_wrap = True
    tf.paragraphs[0].text = (
        "Gaps are absences of evidence, not weaknesses. No brand is scored down "
        "for being opaque, and no score on any slide exists without a source "
        "behind it."
    )
    for r in tf.paragraphs[0].runs:
        r.font.size = Pt(12)
        r.font.color.rgb = _rgb(_INK)
    _footer(s, foot, page)


def _slide_heatmap(prs: Any, card: dict[str, Any], page: int, foot: str) -> None:
    from pptx.util import Inches, Pt

    s = _blank(prs)
    _header(s, "Scores by dimension", kicker="Appendix")
    rows = card.get("rows", [])[:14]
    dims = [d["name"] for d in card.get("dimensions", [])][:12]
    if not rows or not dims:
        _text(s, 0.6, 1.8, 12.0, 1.0, "Nothing scored yet.", size=16, color=_MUTED)
        _footer(s, foot, page)
        return
    ncols = 2 + len(dims)
    total_w = 12.1
    first_w = 2.0
    dim_w = (total_w - first_w - 0.9) / len(dims)
    shape = s.shapes.add_table(
        len(rows) + 1,
        ncols,
        Inches(0.6),
        Inches(1.65),
        Inches(total_w),
        Inches(0.32 * (len(rows) + 1)),
    )
    tbl = shape.table
    tbl.columns[0].width = Inches(first_w)
    tbl.columns[1].width = Inches(0.9)
    for ci in range(len(dims)):
        tbl.columns[2 + ci].width = Inches(dim_w)

    def _cell(
        r: int,
        c: int,
        text: str,
        *,
        bg: tuple[int, int, int],
        fg: tuple[int, int, int] = _INK,
        bold: bool = False,
        size: int = 8,
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

    _cell(0, 0, "Brand", bg=_HEAD_BG, fg=_WHITE, bold=True)
    _cell(0, 1, "Overall", bg=_HEAD_BG, fg=_WHITE, bold=True)
    for ci, d in enumerate(dims):
        _cell(0, 2 + ci, d, bg=_HEAD_BG, fg=_WHITE, bold=True, size=7)
    for ri, r in enumerate(rows, start=1):
        bg = _SELF_BG if r.get("is_self") else _WHITE
        mark = "†" if r.get("provisional") and r["overall"]["normalized_pct"] is not None else ""
        _cell(
            ri,
            0,
            f"{r['name']}{'  (us)' if r.get('is_self') else ''}",
            bg=bg,
            bold=bool(r.get("is_self")),
        )
        _cell(ri, 1, f"{_fmt(r['overall']['normalized_pct'])}{mark}", bg=bg)
        for ci, d in enumerate(dims):
            sc = r.get("dimensions", {}).get(d, {}).get("score")
            # The rule: unscored is a blank grey cell, never a zero.
            if sc is None:
                _cell(ri, 2 + ci, "", bg=_GAP_BG)
            else:
                _cell(ri, 2 + ci, f"{float(sc):g}", bg=bg)
    _text(
        s,
        0.6,
        6.55,
        12.0,
        0.3,
        "1–5 per dimension. Blank = not yet observed (never a zero). "
        "† provisional. Amber = our brand.",
        size=9,
        color=_MUTED,
    )
    _footer(s, foot, page)


def _slide_method(
    prs: Any, card: dict[str, Any], diff: dict[str, Any] | None, page: int, foot: str
) -> None:
    s = _blank(prs)
    _header(s, "How to read these numbers", kicker="Appendix — method")
    dims = card.get("dimensions", [])
    th = (diff or {}).get("thresholds", {})
    items = [
        f"{len(dims)} weighted dimensions (weights sum to "
        f"{card.get('weight_total_pct', 0):g}%); each scored 1–5 from filed evidence.",
        "Overall = weighted score normalized to the weight actually measured, so a "
        "brand with partial evidence is compared on what was seen — never padded "
        "with zeros.",
        "A brand ranks only once enough of the model is scored; below that it is "
        "provisional (†) — its figure is shown, its standing withheld.",
        "Every evidence item quotes its source and was verified against the live "
        "page before it was saved. Unverifiable claims were discarded, not scored.",
        (
            "Material change = score move ≥ "
            f"{th.get('min_score_delta', 1.0)}, a rank change, a dimension newly "
            f"scored or withdrawn, or a coverage shift ≥ {th.get('min_coverage_delta', 0)}%. "
            "Smaller moves are suppressed."
            if th
            else "Material change = a full-point score move, a rank change, a dimension "
            "newly scored or withdrawn, or a large coverage shift. Smaller moves are "
            "suppressed."
        ),
        "Recommendations are classified no-regret / transition requirement / "
        "post-transition / monitor. No-regret test: would we still be pleased we "
        "did this if strategy, rankings or priorities changed next month?",
        "Summary and implications are written by a model from the factual record "
        "and are labelled as such. Standings, scores and gaps are computed.",
    ]
    _bullets(s, 0.6, 1.7, 12.0, 5.0, items, size=12, gap_pt=7)
    _footer(s, foot, page)


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
    title: str = "Competitive Intelligence — Executive Briefing",
    market_label: str = "",
) -> str:
    """Write the deck. Returns the path written.

    ``summary`` is ``{"headline", "bullets", "source"}`` where ``source`` is
    ``"model"`` or ``"facts"``; the deck labels the slide accordingly.
    """
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    rows = card.get("rows", [])
    dims = card.get("dimensions", [])
    generated = str(card.get("generated_at") or datetime.now(UTC).isoformat())[:10]
    if diff:
        period = (
            f"Period {str(diff.get('from_generated_at', '?'))[:10]} → "
            f"{str(diff.get('to_generated_at', '?'))[:10]}"
        )
    else:
        period = f"Baseline · generated {generated}"
    basis = (
        f"{len(rows)} brands · {len(dims)} dimensions · {evidence_count:,} evidence "
        "items · every score traceable to a source URL"
    )
    foot = f"{title.split(' — ')[0]} · {generated} · scores from stored evidence only"
    src = str(summary.get("source") or "facts")

    _slide_title(prs, title=title, market=market_label, period=period, basis=basis)
    page = 2
    _slide_summary(prs, summary, page, foot)
    page += 1
    _slide_standings(prs, card, page, foot)
    page += 1
    _slide_versus(prs, card, page, foot)
    page += 1
    _slide_changes(prs, diff, page, foot)
    page += 1
    page += _slide_implications(
        prs, judged, int((diff or {}).get("material_count", 0)), src, page, foot
    )
    _slide_decisions(prs, judged, src, int((diff or {}).get("material_count", 0)), page, foot)
    page += 1
    _slide_evidence(prs, card, gaps, evidence_count, page, foot)
    page += 1
    _slide_heatmap(prs, card, page, foot)
    page += 1
    _slide_method(prs, card, diff, page, foot)

    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    logger.info("Executive deck written: %s (%d slides)", out, len(prs.slides))
    return str(out)


def factual_summary(
    card: dict[str, Any],
    diff: dict[str, Any] | None,
    judged: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    """The summary slide when no model is available: numbers only, no claims.

    Everything here is read straight off the scorecard and the diff. It is
    deliberately dull — a dull true summary beats a sharp invented one.
    """
    rows = card.get("rows", [])
    ranked = [r for r in rows if r.get("rank") is not None]
    us = next((r for r in rows if r.get("is_self")), None)
    bullets: list[str] = []
    if ranked:
        top = ranked[0]
        bullets.append(
            f"{top['name']} leads the ranked field at "
            f"{_fmt(top['overall']['normalized_pct'])} across {len(ranked)} ranked "
            f"brands ({len(rows)} tracked)."
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
                f"{us['name']} scores {_fmt(us['overall']['normalized_pct'])} but is "
                "provisional — not enough of the model measured to rank."
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
    asks = [
        j
        for j in judged
        if str(j.get("decision_required", "none")).strip().lower() not in ("", "none")
    ]
    if asks:
        bullets.append(
            f"{len(asks)} decision{'s' if len(asks) != 1 else ''} required of the board."
        )
    never = sum(1 for g in gaps if g.get("status") == "never_observed")
    stale = sum(1 for g in gaps if g.get("status") == "stale")
    bullets.append(f"{never} brand × dimension pairs never observed; {stale} overdue a refresh.")
    return {"headline": "", "bullets": bullets, "source": "facts"}
