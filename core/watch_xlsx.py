"""XLSX rendering for the competitive-intelligence scorecard.

The client-facing deliverable. Four sheets so a reader can go from the headline
ranking all the way down to the source URL behind any single score:

    Scorecard  — brands x dimensions, weighted totals, both alternative views
    Weights    — the scoring frame: weight, cadence, sub-criteria
    Evidence   — the full register with provenance (the audit trail)
    Gaps       — what is unscored, thin, or overdue for a refresh

One rendering rule matters more than any formatting choice: **an unscored
dimension is a blank cell, never a zero.** A zero would read as "terrible" when
it means "not yet observed", which is exactly the misreading the whole design
exists to prevent. The Gaps sheet says so in words.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_HEADER_BG = "1F2937"  # slate-800
_HEADER_FG = "FFFFFF"
_SELF_BG = "FEF3C7"  # amber-100 — our own brands
_GAP_BG = "F3F4F6"  # gray-100 — no evidence
_BORDER = "D1D5DB"


def _style_header(ws: Any, row: int, ncols: int) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill

    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = Font(bold=True, color=_HEADER_FG, size=10)
        cell.fill = PatternFill("solid", fgColor=_HEADER_BG)
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )


def _autosize(ws: Any, widths: dict[str, int]) -> None:
    for col, w in widths.items():
        ws.column_dimensions[col].width = w


def render_scorecard_xlsx(
    card: dict[str, Any],
    *,
    dimensions: list[Any],
    evidence: list[Any],
    staleness: list[dict[str, Any]],
    path: str | Path,
    title: str = "Competitive Scorecard",
    voice_rows: list[dict[str, Any]] | None = None,
    comms_rows: list[dict[str, Any]] | None = None,
    catalog_rows: list[dict[str, Any]] | None = None,
    provider_universe: dict[str, Any] | None = None,
) -> str:
    """Write the four-sheet workbook — plus a Voice sheet when ``voice_rows``
    (what players say, docs/87) and a Comms sheet when ``comms_rows`` (what
    brands send players, docs/88) are given. Returns the path written."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()

    # ── Sheet 1: Scorecard ──────────────────────────────────────────
    ws = wb.active
    ws.title = "Scorecard"
    dim_names = [d.name for d in dimensions]

    ws.append([title])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(
        [
            f"Generated {card.get('generated_at', '')} · scores 1-5 "
            "· blank = no evidence yet (never a low score)"
        ]
    )
    ws["A2"].font = Font(italic=True, size=9, color="6B7280")
    ws.append([])

    header = (
        ["#", "Brand", "Group"]
        + dim_names
        + [
            "Overall",
            "Customer proposition",
            "Transition priority",
            "Coverage %",
            "Confidence",
            "Scored weight %",
            "Status",
        ]
    )
    ws.append(header)
    _style_header(ws, 4, len(header))
    ws.freeze_panes = "D5"

    for r in card.get("rows", []):
        overall = r.get("overall", {})
        views = r.get("views", {})
        row = [
            r.get("rank") or "—",
            r.get("name", ""),
            r.get("group", ""),
        ]
        for dn in dim_names:
            d = r.get("dimensions", {}).get(dn, {})
            # Blank, not zero — the entire point.
            row.append(d.get("score") if d.get("score") is not None else None)
        row += [
            overall.get("normalized_pct"),
            views.get("customer_proposition", {}).get("normalized_pct"),
            views.get("transition_priority", {}).get("normalized_pct"),
            overall.get("coverage_pct"),
            overall.get("confidence", ""),
            overall.get("scored_weight_pct"),
            # Spelled out in the sheet itself. A client filters and sorts
            # this file; a caveat that lives only in the notes row travels
            # nowhere once a column is sorted or a row is copied out.
            (
                "Provisional — not ranked"
                if r.get("provisional") and overall.get("normalized_pct") is not None
                else (
                    "No evidence" if overall.get("normalized_pct") is None else "Ranked"
                )
            ),
        ]
        ws.append(row)
        if r.get("is_self"):
            for c in range(1, len(header) + 1):
                ws.cell(row=ws.max_row, column=c).fill = PatternFill(
                    "solid", fgColor=_SELF_BG
                )
        # Shade the dimension cells that have no score.
        for i, dn in enumerate(dim_names):
            d = r.get("dimensions", {}).get(dn, {})
            if d.get("score") is None:
                ws.cell(row=ws.max_row, column=4 + i).fill = PatternFill(
                    "solid", fgColor=_GAP_BG
                )

    _autosize(ws, {"A": 5, "B": 24, "C": 18})
    for i in range(len(dim_names)):
        ws.column_dimensions[get_column_letter(4 + i)].width = 14
    for i in range(6):
        ws.column_dimensions[get_column_letter(4 + len(dim_names) + i)].width = 16

    note_row = ws.max_row + 2
    ws.cell(row=note_row, column=1).value = (
        "Overall / view figures are normalised to the weight actually scored, so "
        "brands with different evidence coverage remain comparable. A blank "
        "dimension means no evidence has been collected — it is NOT a low score. "
        "Read Coverage % and the Gaps sheet alongside every ranking."
    )
    ws.cell(row=note_row, column=1).font = Font(italic=True, size=9, color="6B7280")
    ws.cell(row=note_row, column=1).alignment = Alignment(wrap_text=True)
    ws.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=8)

    # ── Sheet 2: Weights ────────────────────────────────────────────
    ws2 = wb.create_sheet("Weights")
    hdr2 = [
        "Dimension",
        "Weight %",
        "Customer proposition %",
        "Transition priority %",
        "Refresh cadence",
        "Sub-criteria (weight %)",
        "Description",
    ]
    ws2.append(hdr2)
    _style_header(ws2, 1, len(hdr2))
    ws2.freeze_panes = "A2"
    for d in dimensions:
        subs = "; ".join(
            f"{s.get('name')} ({s.get('weight_pct')}%)" for s in (d.subcriteria or [])
        )
        ws2.append(
            [
                d.name,
                d.weight_pct,
                d.view_weights.get("customer_proposition"),
                d.view_weights.get("transition_priority"),
                d.refresh_cadence,
                subs,
                d.description,
            ]
        )
    total = round(sum(float(d.weight_pct) for d in dimensions), 2)
    ws2.append([])
    ws2.append(["TOTAL", total, "", "", "", "", "must equal 100"])
    ws2.cell(row=ws2.max_row, column=1).font = Font(bold=True)
    ws2.cell(row=ws2.max_row, column=2).font = Font(
        bold=True, color="B91C1C" if abs(total - 100) > 0.01 else "047857"
    )
    _autosize(
        ws2,
        {"A": 34, "B": 10, "C": 20, "D": 20, "E": 15, "F": 62, "G": 50},
    )

    # ── Sheet 3: Evidence register ──────────────────────────────────
    ws3 = wb.create_sheet("Evidence")
    hdr3 = [
        "Brand",
        "Dimension",
        "Sub-criterion",
        "Claim",
        "Value",
        "Source URL",
        "Source type",
        "Geo / state",
        "Customer state",
        "Observed at",
        "Confidence",
        "Collector",
        "Excerpt",
        "Screenshot",
        "Exit IP",
    ]
    ws3.append(hdr3)
    _style_header(ws3, 1, len(hdr3))
    ws3.freeze_panes = "A2"
    for e in evidence:
        ws3.append(
            [
                e.get("subject", ""),
                e.get("dimension", ""),
                e.get("subcriterion", ""),
                e.get("claim", ""),
                e.get("value_text", ""),
                e.get("source_url", ""),
                e.get("source_type", ""),
                e.get("geo_state", ""),
                e.get("customer_state", ""),
                e.get("observed_at", ""),
                e.get("confidence", ""),
                e.get("collector", ""),
                (e.get("excerpt", "") or "")[:500],
                e.get("screenshot_path", ""),
                e.get("exit_ip", ""),
            ]
        )
    _autosize(
        ws3,
        {
            "A": 20,
            "B": 30,
            "C": 24,
            "D": 52,
            "E": 18,
            "F": 44,
            "G": 13,
            "H": 12,
            "I": 15,
            "J": 22,
            "K": 12,
            "L": 11,
            "M": 60,
        },
    )

    # ── Sheet 4: Gaps ───────────────────────────────────────────────
    ws4 = wb.create_sheet("Gaps")
    ws4.append(["Evidence gaps and refresh status"])
    ws4["A1"].font = Font(bold=True, size=12)
    ws4.append(
        [
            "A gap is an absence of evidence, not a weakness. These entries "
            "explain every blank cell on the Scorecard sheet."
        ]
    )
    ws4["A2"].font = Font(italic=True, size=9, color="6B7280")
    ws4.append([])
    hdr4 = ["Brand", "Dimension", "Cadence", "Last observed", "Age (days)", "Status"]
    ws4.append(hdr4)
    _style_header(ws4, 4, len(hdr4))
    ws4.freeze_panes = "A5"
    for g in staleness:
        ws4.append(
            [
                g.get("subject", ""),
                g.get("dimension", ""),
                g.get("cadence", ""),
                g.get("last_observed") or "—",
                g.get("age_days") if g.get("age_days") is not None else "—",
                g.get("status", ""),
            ]
        )
    _autosize(ws4, {"A": 22, "B": 34, "C": 12, "D": 24, "E": 12, "F": 16})

    if voice_rows:
        write_voice_sheet(wb, voice_rows)
    if comms_rows:
        write_comms_sheet(wb, comms_rows)
    if catalog_rows:
        write_catalog_sheets(wb, catalog_rows, provider_universe)

    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out))
    logger.info("watch: scorecard workbook written to %s", out)
    return str(out)


def write_voice_sheet(wb: Any, voice_rows: list[dict[str, Any]]) -> None:
    """The 'Voice' sheet: what players said, one row per quote — opinion,
    kept on its own sheet, never mixed into Evidence."""
    from openpyxl.styles import Font

    ws = wb.create_sheet("Voice")
    ws.append(["What players say — sentiment from public posts, not observed product fact"])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append(
        [
            "One row per quote. Usernames stripped, affiliate posts dropped, cross-posts once. "
            "Weight = visible credibility (0-1). Dimension = the model dimension the theme flags "
            "for a reader; it never moves a score."
        ]
    )
    ws["A2"].font = Font(italic=True, size=9, color="6B7280")
    ws.append([])
    hdr = [
        "Brand", "Source", "Posted", "Theme", "Sentiment", "Rating", "Quote", "Flags dimension",
        "Geo hint", "Weight", "URL",
    ]
    ws.append(hdr)
    _style_header(ws, 4, len(hdr))
    ws.freeze_panes = "A5"
    for r in voice_rows:
        ws.append(
            [
                r.get("brand", ""),
                r.get("source", ""),
                str(r.get("posted_at", ""))[:10],
                r.get("theme", ""),
                r.get("sentiment", ""),
                r.get("rating") if r.get("rating") is not None else "",
                r.get("quote", ""),
                r.get("dimension", ""),
                r.get("geo_hint", ""),
                r.get("weight", ""),
                r.get("url", ""),
            ]
        )
    _autosize(ws, {"A": 22, "B": 11, "C": 12, "D": 18, "E": 11, "F": 8, "G": 70, "H": 32, "I": 10, "J": 8, "K": 50})


def render_voice_xlsx(
    voice_rows: list[dict[str, Any]], *, path: str | Path, summary: dict[str, Any] | None = None
) -> str:
    """Standalone voice workbook: a Summary sheet (per brand) and the Voice rows."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Voice of customer — what players say"])
    ws["A1"].font = Font(bold=True, size=13)
    if summary:
        ws.append([f"{summary.get('window_days', 30)}-day window · {summary.get('mentions', 0)} mentions · "
                   f"sources: {', '.join(summary.get('sources') or [])}"])
        ws["A2"].font = Font(italic=True, size=9, color="6B7280")
    ws.append([])
    hdr = ["Brand", "Mentions", "Readable", "Negative %", "Positive %", "Avg rating", "Top complaint",
           "Top praise", "Flags", "Sources"]
    ws.append(hdr)
    _style_header(ws, 4, len(hdr))
    for b in (summary or {}).get("brands", []):
        ws.append(
            [
                f"{b.get('name', '')}{' (us)' if b.get('is_self') else ''}",
                b.get("n", 0),
                "no — too few" if b.get("too_few") else "yes",
                round(float(b.get("neg_share", 0.0)) * 100),
                round(float(b.get("pos_share", 0.0)) * 100),
                b.get("avg_rating") if b.get("avg_rating") is not None else "",
                b.get("top_complaint") or "",
                b.get("top_praise") or "",
                ", ".join(b.get("flags") or []),
                ", ".join(b.get("sources") or []),
            ]
        )
    _autosize(ws, {"A": 24, "B": 10, "C": 14, "D": 11, "E": 11, "F": 11, "G": 20, "H": 20, "I": 40, "J": 20})
    write_voice_sheet(wb, voice_rows)
    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out))
    return str(out)


def write_comms_sheet(wb: Any, comms_rows: list[dict[str, Any]]) -> None:
    """The 'Comms' sheet: one row per marketing e-mail a brand sent us."""
    from openpyxl.styles import Font

    ws = wb.create_sheet("Comms")
    ws.append(["What brands send players — marketing e-mail received in the organ's own inboxes"])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append(["One row per e-mail. Category from a fixed vocabulary; excerpt verified against the mail."])
    ws["A2"].font = Font(italic=True, size=9, color="6B7280")
    ws.append([])
    hdr = ["Brand", "Received", "Category", "Subject line", "Offer", "Excerpt", "Sender", "Inbox"]
    ws.append(hdr)
    _style_header(ws, 4, len(hdr))
    ws.freeze_panes = "A5"
    for r in comms_rows:
        ws.append([
            r.get("brand", ""), str(r.get("received_at", ""))[:16], r.get("category", ""),
            r.get("subject", ""), r.get("offer", ""), r.get("excerpt", ""), r.get("sender", ""), r.get("inbox", ""),
        ])
    _autosize(ws, {"A": 22, "B": 17, "C": 16, "D": 50, "E": 40, "F": 60, "G": 30, "H": 30})


_CATALOG_SHEETS = (
    ("provider", "Providers", ["Brand", "Provider", "Detail", "Source", "Read as", "Observed"]),
    ("coin_package", "Coin packages",
     ["Brand", "Price USD", "Gold coins", "Sweeps coins", "As printed", "Notes",
      "Read from", "Source", "Read as", "Observed"]),
    ("promotion", "Promotions",
     ["Brand", "Promotion", "Benefit", "How to claim", "Frequency", "Terms", "Image",
      "Source", "Read as", "Observed"]),
    ("loyalty_tier", "Loyalty tiers",
     ["Brand", "Tier", "Qualification", "Reward", "Source", "Read as", "Observed"]),
    ("game", "Games", ["Brand", "Game", "Category / studio", "Source", "Read as", "Observed"]),
)


def write_portfolio_sheet(wb: Any, catalog_rows: list[dict[str, Any]],
                          universe: dict[str, Any] | None = None) -> None:
    """The client's own game-portfolio layout: one row per studio, one
    column per brand, ● where the brand carries it (with the number of that
    studio's titles read, when any). Rows follow the client's list when one
    is given; studios observed that are not on it are marked."""
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    from core.watch_catalog import provider_matrix

    if not any(r.get("kind") == "provider" for r in catalog_rows):
        return
    seen: dict[str, bool] = {}
    for r in catalog_rows:
        seen.setdefault(str(r.get("brand", "")), bool(r.get("is_self")))
    brands = sorted(({"name": n, "is_self": v} for n, v in seen.items()),
                    key=lambda b: (not b["is_self"], b["name"]))
    matrix = provider_matrix(
        catalog_rows, brands,
        universe=(universe or {}).get("providers"),
        universe_brands=(universe or {}).get("brands"),
    )
    ws = wb.create_sheet("Game portfolio")
    c = matrix["counts"]
    ws.append([
        f"Game portfolio — {c['observed']} studios observed across {len(matrix['brands'])} brands"
        + (f"; {c['both']} of the {c['on_client_list']} on the client's list seen, "
           f"{c['list_only']} not yet, {c['observed_only']} observed that are not on the list"
           if universe else "")
        + ". ● carried, as printed on the brand's pages or public reviews (Providers sheet says which); "
          "a number is that studio's titles read; ○ reported only — by a page older than six months, or by "
          "a review the brand's signed-in lobby read did not confirm — and not counted."
    ])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append([])
    hdr = ["Game provider", *matrix["brands"], "Brands"] + (["On client list"] if universe else [])
    ws.append(hdr)
    _style_header(ws, 3, len(hdr))
    ws.freeze_panes = "B4"
    for row in matrix["providers"]:
        cells = []
        for b in matrix["brands"]:
            cell = row["brands"][b]
            cells.append(("●" + (f" {cell['games']}" if cell["games"] else "")) if cell["carried"]
                         else "○" if cell.get("reported") else "")
        ws.append([row["name"] + ("" if row["on_client_list"] else " *"), *cells, row["brand_count"]]
                  + (["yes" if row["on_client_list"] else "no"] if universe else []))
    for i in range(2, len(hdr) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 14
        for r_ in range(4, ws.max_row + 1):
            ws.cell(row=r_, column=i).alignment = Alignment(horizontal="center")
    ws.column_dimensions["A"].width = 30
    if universe:
        ws.append([])
        ws.append(["* observed by us, not on the client's list"])
        if matrix["brands_only_on_client_list"]:
            ws.append(["Brands on the client's sheet not in the register: "
                       + ", ".join(matrix["brands_only_on_client_list"])])
        if matrix["brands_only_in_register"]:
            ws.append(["Brands in the register not on the client's sheet: "
                       + ", ".join(matrix["brands_only_in_register"])])


def write_catalog_sheets(wb: Any, catalog_rows: list[dict[str, Any]],
                         universe: dict[str, Any] | None = None) -> None:
    """One sheet per catalog kind — the raw data itself (docs/89): every
    provider, every price point, every promotion, every game title, each
    with the page it was read from and the session it was read in. The
    Game portfolio matrix comes first — it is the client's own layout."""
    from openpyxl.styles import Font

    write_portfolio_sheet(wb, catalog_rows, universe)

    for kind, title, hdr in _CATALOG_SHEETS:
        rows = [r for r in catalog_rows if r.get("kind") == kind]
        if not rows:
            continue
        ws = wb.create_sheet(title)
        ws.append([f"{title} — as printed on each brand's own pages (not scored)"])
        ws["A1"].font = Font(bold=True, size=12)
        ws.append([])
        ws.append(hdr)
        _style_header(ws, 3, len(hdr))
        ws.freeze_panes = "A4"
        for r in sorted(rows, key=lambda x: (str(x.get("brand", "")), x.get("sort_index", 0))):
            common_tail = [
                r.get("url", ""), r.get("session", "logged_out"), str(r.get("observed_at", ""))[:10],
            ]
            if kind == "coin_package":
                ws.append([
                    r.get("brand", ""), r.get("price_usd", ""),
                    r.get("gold_coins", ""), r.get("sweeps_coins", ""),
                    r.get("coins", ""), r.get("detail", ""),
                    "the brand" if r.get("source_type") == "site" else "public review",
                    *common_tail,
                ])
            elif kind == "promotion":
                ws.append([
                    r.get("brand", ""), r.get("name", ""),
                    r.get("benefit", "") or r.get("detail", ""),
                    r.get("how_to_claim", ""), r.get("frequency", ""),
                    r.get("detail", ""), r.get("image", ""), *common_tail,
                ])
            elif kind == "loyalty_tier":
                ws.append([
                    r.get("brand", ""), r.get("name", ""), r.get("qualification", ""),
                    r.get("reward", "") or r.get("detail", ""), *common_tail,
                ])
            else:
                ws.append([
                    r.get("brand", ""), r.get("name", ""), r.get("detail", ""), *common_tail,
                ])
        widths = {"A": 22, "B": 30, "C": 36, "D": 34, "E": 28, "F": 40, "G": 22, "H": 46, "I": 14, "J": 12}
        _autosize(ws, {k: v for k, v in widths.items() if k <= chr(ord("A") + len(hdr) - 1)})
