"""Export the monthly report to Excel (.xlsx) and PDF.

Both exporters return ``bytes`` so the UI can offer them as downloads without
writing temporary files.
"""
from __future__ import annotations

import io

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

from src.reporting.monthly_report import MonthlyReport
from src.utils.formatting import fmt_money, fmt_pct, period_label

FOREST = "136C69"   # Hummingbirds teal (dark) — matches the dashboard theme
GREY = "737B78"
RED = "B23C3C"


# --------------------------------------------------------------------------- shared tables

def category_export_table(report: MonthlyReport) -> pd.DataFrame:
    c = report.category_table
    return pd.DataFrame({
        "Category": c["category"],
        "Approved budget": c["approved_budget"],
        "Budget to date": c["budget_to_date"],
        "Actual to date": c["actual_to_date"],
        "Remaining budget": c["remaining_budget"],
        "Variance to date (+ = over)": c["variance_to_date"],
        "Variance to date %": c["variance_pct"].round(1),
        "Budget utilised %": c["utilisation_pct"].round(1),
        "Forecast at completion": c["forecast_at_completion"],
        "Forecast variance (+ = over)": c["forecast_variance"],
        "Forecast variance %": c["forecast_variance_pct"].round(1),
    })


def kpi_rows(report: MonthlyReport) -> list[tuple[str, str]]:
    k, cur = report.kpis, report.currency
    return [
        ("Total approved budget", fmt_money(k["approved_budget"], cur)),
        ("Budget phased to date", fmt_money(k["budget_to_date"], cur)),
        ("Actual expenditure to date", fmt_money(k["actual_to_date"], cur)),
        ("Remaining approved budget", fmt_money(k["remaining_budget"], cur)),
        ("Forecast remaining expenditure", fmt_money(k["forecast_remaining"], cur)),
        ("Forecast at completion", fmt_money(k["forecast_at_completion"], cur)),
        ("Forecast budget variance (+ = overspend)",
         f"{fmt_money(k['forecast_variance'], cur)} ({fmt_pct(k['forecast_variance_pct'], signed=True)})"),
        ("Budget utilised", fmt_pct(k["utilisation_pct"])),
        (f"{period_label(report.report_month)} spend vs phased budget",
         f"{fmt_money(report.month_figures['actual'], cur)} vs {fmt_money(report.month_figures['budget'], cur)}"),
    ]


# --------------------------------------------------------------------------- Excel

def _style_sheet(ws, money_cols: set[int] | None = None) -> None:
    head_fill = PatternFill("solid", fgColor=FOREST)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for idx, col in enumerate(ws.columns, start=1):
        width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
        ws.column_dimensions[get_column_letter(idx)].width = min(max(12, width + 2), 60)
        if money_cols and idx in money_cols:
            for c in col[1:]:
                c.number_format = '#,##0.00;[Red]-#,##0.00'
    ws.freeze_panes = "A2"


def to_excel(report: MonthlyReport) -> bytes:
    """Multi-sheet workbook: Summary, Categories, Monthly, Deviations, Data quality, Flagged, Status, Reconciliation."""
    buf = io.BytesIO()
    cur = report.currency
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        summary = [("Report", f"Monthly Financial Report — {period_label(report.report_month)}"),
                   ("Project", f"{report.project.get('project_name')} ({report.project.get('project_id')})"),
                   ("Country", report.project.get("country")),
                   ("Reporting currency", cur),
                   ("Generated", report.generated_at),
                   ("NOTICE", report.disclaimer),
                   ("", ""),
                   ("FINANCIAL STATUS", report.status.status)]
        summary += [("Status reason", r) for r in report.status.reasons]
        summary += [("", ""), ("KEY FIGURES", "")] + kpi_rows(report)
        summary += [("", ""), ("OBSERVATIONS (calculated from records)", "")] + [("", o) for o in report.observations]
        summary += [("", ""), ("ITEMS REQUIRING MANAGEMENT ATTENTION", "")] + \
                   [("", a) for a in (report.attention_items or ["None"])]
        summary += [("", ""), ("ANALYST COMMENTARY (human-written)", ""),
                    ("", report.analyst_commentary or "No commentary entered.")]
        if report.data_warnings:
            summary += [("", ""), ("DATA WARNINGS", "")] + [("", w) for w in report.data_warnings]
        pd.DataFrame(summary, columns=["Item", "Value"]).to_excel(xw, sheet_name="Summary", index=False)

        cat = category_export_table(report)
        cat.to_excel(xw, sheet_name="Categories", index=False)
        m = report.monthly_table[["period", "budget", "actual", "forecast", "variance",
                                  "cumulative_budget", "cumulative_actual", "cumulative_outturn"]].copy()
        m.columns = ["Period", "Budget", "Actual", "Forecast", "Variance (actual - budget)",
                     "Cumulative budget", "Cumulative actual", "Cumulative actual + forecast"]
        m.to_excel(xw, sheet_name="Monthly", index=False)
        report.deviations.rename(columns=str.title).to_excel(xw, sheet_name="Deviations", index=False)
        report.data_quality.rename(columns=lambda s: s.replace("_", " ").title()).to_excel(
            xw, sheet_name="Data quality", index=False)
        ft = report.flagged_transactions[["transaction_id", "invoice_id", "transaction_date", "supplier",
                                          "description", "category", "amount", "currency", "amount_base",
                                          "status", "document_reference", "flags"]].copy()
        ft["transaction_date"] = pd.to_datetime(ft["transaction_date"]).dt.date
        ft.rename(columns={"amount_base": f"amount_{cur}"}).to_excel(xw, sheet_name="Flagged transactions",
                                                                      index=False)
        report.status.rules.to_excel(xw, sheet_name="Status rules", index=False)
        report.reconciliation.to_excel(xw, sheet_name="Reconciliation", index=False)

        wb = xw.book
        _style_sheet(wb["Summary"])
        wb["Summary"].column_dimensions["B"].width = 110
        for row in wb["Summary"].iter_rows(min_row=2):
            if row[0].value and str(row[0].value).isupper():
                row[0].font = Font(bold=True, color=FOREST)
        _style_sheet(wb["Categories"], {2, 3, 4, 5, 6, 9, 10})
        _style_sheet(wb["Monthly"], {2, 3, 4, 5, 6, 7, 8})
        _style_sheet(wb["Deviations"], {3})
        _style_sheet(wb["Data quality"], {3})
        _style_sheet(wb["Flagged transactions"], {7, 9})
        _style_sheet(wb["Status rules"])
        _style_sheet(wb["Reconciliation"], {2, 3, 4})
    return buf.getvalue()


# --------------------------------------------------------------------------- PDF

def _p(text: str, style) -> Paragraph:
    return Paragraph(str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)


def to_pdf(report: MonthlyReport) -> bytes:
    """A concise, management-style PDF (A4 portrait)."""
    buf = io.BytesIO()
    cur = report.currency
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm,
                            bottomMargin=18 * mm, title=f"Mount Kei Monthly Financial Report {report.report_month}")
    ss = getSampleStyleSheet()
    forest = colors.HexColor(f"#{FOREST}")
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=16, textColor=forest, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=11.5, textColor=forest, spaceBefore=8, spaceAfter=4,
                        keepWithNext=1)
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=8.8, leading=11.5, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=7.6, leading=9.5, textColor=colors.HexColor(f"#{GREY}"))
    cell = ParagraphStyle("cell", parent=body, fontSize=7.4, leading=9)
    notice = ParagraphStyle("notice", parent=body, textColor=colors.HexColor(f"#{RED}"), fontSize=8.2)

    status_color = {"Within Budget": "#27845A", "Watchlist": "#B7791F", "Potential Overspend": f"#{RED}"}[
        report.status.status]

    story = [
        _p("Mount Kei Finance Intelligence", small),
        _p(f"Monthly Financial Report — {period_label(report.report_month)}", h1),
        _p(f"{report.project.get('project_name')} ({report.project.get('project_id')}) · "
           f"{report.project.get('country')} · Reporting currency {cur} · Generated {report.generated_at}", small),
        Spacer(1, 3),
        _p(f"NOTICE: {report.disclaimer}", notice),
        Spacer(1, 6),
    ]
    st = Table([[Paragraph(f"<b>Financial status: {report.status.status}</b>",
                           ParagraphStyle("s", parent=body, textColor=colors.white, fontSize=10))]],
               colWidths=[178 * mm])
    st.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(status_color)),
                            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [st, Spacer(1, 3)]
    story += [_p(f"• {r}", small) for r in report.status.reasons]

    story.append(_p("1. Key figures", h2))
    kt = Table([[_p(a, cell), _p(b, cell)] for a, b in kpi_rows(report)], colWidths=[85 * mm, 93 * mm])
    kt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D5DBD8")),
                            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F6F4"))]))
    story.append(kt)

    story.append(_p("2. Observations (calculated from records)", h2))
    story += [_p(f"• {o}", body) for o in report.observations]

    story.append(_p("3. Spending by category (to date vs budget phased to date)", h2))
    cats = report.category_table
    head = ["Category", "Approved", "Budget to date", "Actual to date", "Variance", "Var %", "Used %", "FAC", "FAC var %"]
    rows = [head] + [[r.category, fmt_money(r.approved_budget, cur), fmt_money(r.budget_to_date, cur),
                      fmt_money(r.actual_to_date, cur), fmt_money(r.variance_to_date, cur),
                      fmt_pct(r.variance_pct, signed=True), fmt_pct(r.utilisation_pct),
                      fmt_money(r.forecast_at_completion, cur), fmt_pct(r.forecast_variance_pct, signed=True)]
                     for r in cats.itertuples()]
    tot = report.kpis
    rows.append(["Total", fmt_money(tot["approved_budget"], cur), fmt_money(tot["budget_to_date"], cur),
                 fmt_money(tot["actual_to_date"], cur), fmt_money(tot["variance_to_date"], cur),
                 fmt_pct(tot["variance_to_date_pct"], signed=True), fmt_pct(tot["utilisation_pct"]),
                 fmt_money(tot["forecast_at_completion"], cur), fmt_pct(tot["forecast_variance_pct"], signed=True)])
    cell_head = ParagraphStyle("cell_head", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")
    ct = Table([[_p(c, cell_head) for c in rows[0]]] + [[_p(c, cell) for c in r] for r in rows[1:]],
               colWidths=[36 * mm, 19 * mm, 19 * mm, 19 * mm, 18 * mm, 15 * mm, 13 * mm, 20 * mm, 19 * mm],
               repeatRows=1)
    tstyle = [("BACKGROUND", (0, 0), (-1, 0), forest), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
              ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D5DBD8")),
              ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F3F6F4")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    ct.setStyle(TableStyle(tstyle))
    story.append(ct)
    story.append(_p("Variance = actual − budget; positive = overspend. FAC = forecast at completion "
                    "(actual to date + forecast remaining).", small))

    story.append(_p("4. Significant deviations", h2))
    if report.deviations.empty:
        story.append(_p("No category exceeds the significance thresholds.", body))
    else:
        story += [_p(f"• {d.category} — {d.basis}: {fmt_money(d.variance, cur)} "
                     f"({fmt_pct(d.variance_pct, signed=True)}, {d.direction.lower()})", body)
                  for d in report.deviations.itertuples()]

    story.append(_p("5. Items requiring management attention", h2))
    story += [_p(f"• {a}", body) for a in (report.attention_items or ["None."])]

    story.append(_p("6. Data quality", h2))
    dq = [["Check", "Transactions", f"Amount ({cur})"]] + [
        [d.check, str(d.transactions), fmt_money(d.amount_affected, cur)] for d in report.data_quality.itertuples()]
    dt_ = Table([[_p(c, cell) for c in r] for r in dq], colWidths=[80 * mm, 30 * mm, 40 * mm])
    dt_.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D5DBD8")),
                             ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F6F4"))]))
    story.append(dt_)
    if report.data_warnings:
        story += [_p(f"⚠ {w}", small) for w in report.data_warnings]

    story.append(KeepTogether([_p("7. Analyst commentary (human-written; not generated)", h2),
                               _p(report.analyst_commentary or "No commentary entered.", body)]))

    story.append(_p("8. Reconciliation checks", h2))
    story += [_p(f"{'PASS' if r.passed else 'FAIL'} — {r.check} (difference {fmt_money(r.difference, cur, 2)})", small)
              for r in report.reconciliation.itertuples()]

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor(f"#{GREY}"))
        canvas.drawString(16 * mm, 10 * mm, "Illustrative prototype — synthetic data, not Hummingbirds financial information.")
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
