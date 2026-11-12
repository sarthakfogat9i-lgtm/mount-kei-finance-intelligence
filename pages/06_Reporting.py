"""Page 6 — Monthly financial report for management review, with Excel and PDF export."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from src.reporting.exports import to_excel, to_pdf
from src.reporting.monthly_report import build_monthly_report
from src.ui.components import (Col, bullet_list, card_title, chip, fact_grid, forecast_comparison, html_table,
                               verdict)
from src.ui.layout import footer, load_data, page_shell
from src.utils.formatting import fmt_money, fmt_pct, period_label

data = load_data()
as_of = page_shell(data, "reporting", "Reporting", "Monthly financial summary prepared for CFO and management review.")
cur = data.base_currency


def doc_section(no: int, title: str, tag: str = "") -> None:
    st.markdown(f'<div class="mk-doc-sec"><span class="no">{no:02d}</span><span>{html.escape(title)}</span>'
                + (f'<span class="tag">{html.escape(tag)}</span>' if tag else "") + "</div>", unsafe_allow_html=True)


# ------------------------------------------------------------------ report controls
closed = [p for p in data.fy_periods if p <= (data.latest_actual_period or data.fy_periods[0])]
with st.container(border=True):
    card_title("Prepare the report", "Choose the month, add your commentary, then export. Exports match this screen.")
    r1, r2 = st.columns([1, 3])
    month = r1.selectbox("Reporting month", closed, index=closed.index(as_of) if as_of in closed else len(closed) - 1,
                         format_func=period_label)
    commentary = r2.text_area("Analyst commentary (optional — included in exports, labelled as human-written)",
                              placeholder="Explain the main variances using information confirmed with the project team. "
                                          "The tool does not generate explanations.", height=90,
                              key=f"commentary_{month}")
    report = build_monthly_report(data, month, commentary)
    d1, d2, _ = st.columns([1.1, 1.1, 3])
    fname = f"MountKei_Monthly_Financial_Report_{month}"
    d1.download_button("Export to Excel", to_excel(report), file_name=f"{fname}.xlsx", type="primary",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    d2.download_button("Export to PDF", to_pdf(report), file_name=f"{fname}.pdf", mime="application/pdf",
                       use_container_width=True)

# ------------------------------------------------------------------ the report document
p = report.project
k = report.kpis
with st.container(border=True):
    st.markdown(f'<div class="mk-eyebrow">Monthly financial report</div>'
                f'<div class="mk-doc-h">Mount Kei — {period_label(month)}</div>'
                f'<div class="mk-doc-meta">{html.escape(str(p["project_name"]))} ({html.escape(str(p["project_id"]))}) · '
                f'{html.escape(str(p["country"]))} · FY phase {period_label(data.fy_periods[0])} – {period_label(data.fy_periods[-1])} · '
                f'reporting currency {cur} · generated {report.generated_at}</div>'
                f'<div style="margin-top:8px">{chip(report.disclaimer, "neutral", "!")}</div>', unsafe_allow_html=True)

    over_fac = k["forecast_variance"] > 0
    over_ytd = k["variance_to_date"] > 0

    doc_section(1, "Financial position", f"As at end of {period_label(month)}")
    verdict(report.status.status,
            f"Forecast to finish {fmt_money(abs(k['forecast_variance']), cur)} "
            f"({fmt_pct(abs(k['forecast_variance_pct']))}) {'over' if over_fac else 'under'} the approved budget.",
            "Status reasons: " + "; ".join(report.status.reasons))
    fact_grid([("Approved budget (full phase)", fmt_money(k["approved_budget"], cur)),
               ("Budget phased to date", fmt_money(k["budget_to_date"], cur)),
               ("Actual expenditure to date", fmt_money(k["actual_to_date"], cur)),
               ("Remaining approved budget", fmt_money(k["remaining_budget"], cur)),
               ("Forecast at completion", fmt_money(k["forecast_at_completion"], cur)),
               ("Forecast variance (+ = overspend)",
                f"{'+' if over_fac else ''}{fmt_money(k['forecast_variance'], cur)} ({fmt_pct(k['forecast_variance_pct'], signed=True)})")])

    doc_section(2, "Budget versus actual", "Phased budget for the same months · positive variance = overspend")
    m = report.month_figures
    bva = pd.DataFrame([
        {"measure": f"{period_label(month)} (month)", "budget": m["budget"], "actual": m["actual"],
         "variance": m["variance"], "variance_pct": m["variance_pct"]},
        {"measure": f"{period_label(data.fy_periods[0])} – {period_label(month)} (to date)", "budget": k["budget_to_date"],
         "actual": k["actual_to_date"], "variance": k["variance_to_date"], "variance_pct": k["variance_to_date_pct"]}])
    html_table(bva, [Col("measure", "Period"), Col("budget", "Phased budget", "money"), Col("actual", "Actual", "money"),
                     Col("variance", "Variance", "var"), Col("variance_pct", "Var %", "varpct")], currency=cur)
    bullet_list([o for o in report.observations if o.startswith("Largest")])

    doc_section(3, "Category-level deviations",
                "Significant = |variance %| > 10% and |variance| > €10,000, to date or at completion · tinted rows = overspend")
    # Direction comes from report.deviations (to-date and at-completion bases); overspend wins if both occur.
    dev = report.deviations
    sig = set(dev["category"])
    sig_over = set(dev.loc[dev["direction"] == "Overspend", "category"])
    cat_view = report.category_table.assign(
        significance=[chip("Significant overspend", "bad", "▲") if c in sig_over
                      else chip("Significant underspend", "info", "▼") if c in sig else ""
                      for c in report.category_table["category"]])
    tot = {"category": "Total", "budget_to_date": k["budget_to_date"], "actual_to_date": k["actual_to_date"],
           "variance_to_date": k["variance_to_date"], "variance_pct": k["variance_to_date_pct"],
           "forecast_variance_pct": k["forecast_variance_pct"], "significance": ""}
    html_table(cat_view, [Col("category", "Category"), Col("budget_to_date", "Phased budget", "money"),
                          Col("actual_to_date", "Actual", "money"), Col("variance_to_date", "Variance", "var"),
                          Col("variance_pct", "Var %", "varpct"), Col("forecast_variance_pct", "Forecast var %", "varpct"),
                          Col("significance", "", "html")],
               currency=cur, total=tot,
               # red row tint only for significant OVERSPENDS; significant underspends carry the ▼ chip only
               highlight=[c in sig_over for c in report.category_table["category"]])

    c1, c2 = st.columns(2, gap="large")
    with c1:
        doc_section(4, "Forecast at completion", "Base case")
        forecast_comparison(k["approved_budget"], k["actual_to_date"], k["forecast_remaining"],
                            k["forecast_at_completion"], k["forecast_variance"], k["forecast_variance_pct"], cur)
    with c2:
        doc_section(5, "Data-quality issues", f"Transactions up to {period_label(month)}")
        dq = report.data_quality[report.data_quality["transactions"] > 0].copy()
        if dq.empty:
            st.markdown('<div class="mk-empty">● No data-quality issues.</div>', unsafe_allow_html=True)
        else:
            html_table(dq, [Col("check", "Check"), Col("transactions", "Count", "text"),
                            Col("amount_affected", "Amount", "money")], currency=cur)
        for w in report.data_warnings:
            st.warning(w, icon=":material/warning:")

    doc_section(6, "Management attention items")
    bullet_list(report.attention_items or ["None."], fmt=lambda t: "▲ " + html.escape(t))
    with st.expander(f"Flagged transactions up to {period_label(month)} ({len(report.flagged_transactions)})"):
        ft = report.flagged_transactions[["transaction_id", "transaction_date", "supplier", "category", "amount",
                                          "currency", "amount_base", "status", "flags"]].copy()
        ft["transaction_date"] = ft["transaction_date"].dt.date
        st.dataframe(ft.style.format({"amount": "{:,.2f}", "amount_base": lambda v: fmt_money(v, cur, 2)}),
                     hide_index=True, use_container_width=True)

    doc_section(7, "Analyst commentary", "Human-written — not generated")
    st.markdown(f'<div style="font-size:13.5px;color:var(--ink-2);white-space:pre-wrap">'
                f'{html.escape(commentary) if commentary else "<i>No commentary entered.</i>"}</div>',
                unsafe_allow_html=True)

    with st.expander("Reconciliation checks"):
        recon = report.reconciliation.assign(passed=report.reconciliation["passed"].map({True: "● Pass", False: "■ Fail"}))
        st.dataframe(recon.style.format({c: (lambda v: fmt_money(v, cur, 2)) for c in ("expected", "calculated", "difference")}),
                     hide_index=True, use_container_width=True)
footer()
