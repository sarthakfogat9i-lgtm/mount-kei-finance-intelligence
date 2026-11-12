"""Page 4 — Forecasting: expected cost at completion and scenarios."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.database import operations as ops
from src.finance import forecasting as fc
from src.ui import charts
from src.ui.components import Col, card_title, chart_card, chip, html_table, kpi_card, kpi_row, section
from src.ui.layout import footer, load_data, page_shell, styled_table
from src.utils.config import scenarios
from src.utils.formatting import fmt_money, fmt_money_short, fmt_pct, period_label

data = load_data()
as_of = page_shell(data, "forecasting", "Forecasting",
                   "Forecast at Completion = Actual expenditure to date + Forecast remaining expenditure. "
                   "Forecasts are projections from stated assumptions, not guaranteed outcomes.")
cur = data.base_currency
remaining_months = fc.remaining_periods(data, as_of)

if not remaining_months:
    st.info(f"{period_label(as_of)} is the last month of the budget phase — there is no remaining expenditure "
            "to forecast. Forecast at completion equals actual expenditure.", icon=":material/info:")

# ------------------------------------------------------------------ assumptions
scen_cfg = {k: dict(v) for k, v in scenarios().items()}
with st.container(border=True):
    card_title("Forecast assumptions",
               "Adjustments apply only to remaining (future) expenditure — actual spend is never changed.")
    a1, a2, a3 = st.columns([1.3, 1, 1])
    scenario = a1.radio("Scenario shown in detail", list(scen_cfg), horizontal=True)
    scen_cfg["Optimistic"]["adjustment_pct"] = a2.number_input(
        "Optimistic adjustment to remaining (%)", value=float(scen_cfg["Optimistic"]["adjustment_pct"]), step=0.5,
        help="Applied to base-case remaining expenditure. Negative = lower cost.")
    scen_cfg["Pessimistic"]["adjustment_pct"] = a3.number_input(
        "Pessimistic adjustment to remaining (%)", value=float(scen_cfg["Pessimistic"]["adjustment_pct"]), step=0.5)
    with st.expander("Category-level adjustments to the base case (optional)"):
        st.caption("Enter a % change for any category, e.g. +10 if remaining transport costs are expected to be "
                   "10% higher than currently forecast. Applies to all scenarios.")
        base_cat = fc.forecast_by_category(data, as_of)
        editor = pd.DataFrame({"Category": base_cat["category"], "Adjustment %": 0.0})
        edited = st.data_editor(editor, hide_index=True, use_container_width=True, disabled=["Category"],
                                column_config={"Adjustment %": st.column_config.NumberColumn(step=1.0, format="%.1f")},
                                key="cat_adj")
        category_pct = {r["Category"]: float(r["Adjustment %"]) for _, r in edited.iterrows()
                        if r["Adjustment %"] not in (None, 0.0) and r["Adjustment %"] == r["Adjustment %"]}

scen_pct = float(scen_cfg[scenario]["adjustment_pct"])
totals = fc.forecast_totals(data, as_of, scen_pct, category_pct)
over = totals["forecast_variance"] > 0

# ------------------------------------------------------------------ the four building blocks, clearly separated
section(f"Forecast position — {scenario}",
        "Actual and approved budget are recorded facts; remaining spend and completion are forecasts.")
kpi_row([
    kpi_card("Actual expenditure", fmt_money_short(totals["actual_to_date"], cur),
             f"Recorded · to end {period_label(as_of)}", role="actual",
             tip="Cash already spent / invoiced. Scenarios never change this figure."),
    kpi_card("Forecast remaining", fmt_money_short(totals["forecast_remaining"], cur),
             f"Forecast · {len(remaining_months)} month(s) · {scenario}", role="forecast",
             tip="Analyst forecast for future months (approved budget where no forecast exists), adjusted by the scenario."),
    kpi_card("Forecast at completion", fmt_money_short(totals["forecast_at_completion"], cur),
             "Actual + forecast remaining", role="forecast",
             tip="Actual expenditure to date + forecast remaining expenditure."),
    kpi_card("Approved budget", fmt_money_short(totals["approved_budget"], cur), "Recorded · fixed, not a forecast",
             role="budget", tip="Sum of approved budget lines for the phase."),
    kpi_card("Forecast variance", ("+" if over else "") + fmt_money_short(totals["forecast_variance"], cur),
             "Forecast at completion − approved budget", tone="neg" if over else "pos",
             badge=chip(fmt_pct(totals["forecast_variance_pct"], signed=True) + (" overspend" if over else " underspend"),
                        "bad" if over else "ok", "▲" if over else "▼"),
             tip="Positive = forecast overspend; negative = forecast underspend."),
])

# ------------------------------------------------------------------ one scenario visual + its assumptions
scen = fc.scenario_comparison(data, as_of, scen_cfg, category_pct)
section("Scenario comparison",
        "Only remaining spend differs between scenarios — actual to date is identical in all three.")
chart_card("Where would the project finish under each scenario?",
           "Teal = actual to date · hatched = forecast remaining · vertical line = approved budget.",
           charts.scenario_comparison(scen, totals["approved_budget"]))
scen_view = scen.assign(scenario=[f"{n} · selected" if n == scenario else n for n in scen["scenario"]])
html_table(scen_view, [Col("scenario", "Scenario"), Col("adjustment_pct", "Adj. to remaining", "spct"),
                       Col("forecast_remaining", "Remaining", "money"),
                       Col("forecast_at_completion", "Forecast at completion", "money"),
                       Col("forecast_variance", "Variance", "var"), Col("forecast_variance_pct", "Var %", "varpct"),
                       Col("assumption", "Assumption", "wrap")], currency=cur)

# ------------------------------------------------------------------ by category
fcat = fc.forecast_by_category(data, as_of, scen_pct, category_pct)
section(f"Forecast by category — {scenario}", "Variance = forecast at completion − approved budget (positive = overspend).")
# Table full width with the chart below, so every column stays readable on laptop screens.
tot = {k: fcat[k].sum() for k in ("approved_budget", "actual_to_date", "forecast_remaining", "forecast_at_completion",
                                  "forecast_variance")}
tot.update(category="Total", forecast_variance_pct=totals["forecast_variance_pct"])
html_table(fcat, [Col("category", "Category"), Col("approved_budget", "Approved", "money"),
                  Col("actual_to_date", "Actual", "money"), Col("forecast_remaining", "Remaining", "money"),
                  Col("forecast_at_completion", "Forecast at completion", "money"),
                  Col("forecast_variance", "Variance", "var"), Col("forecast_variance_pct", "Var %", "varpct")],
           currency=cur, total=tot)

rr = fc.run_rate_forecast(data, as_of)
st.info(f"**Cross-check (run-rate method, not used for the official forecast):** if the average spend of the last "
        f"{rr['lookback_months']} months ({fmt_money(rr['average_monthly_spend'], cur)}/month) continued for the "
        f"remaining {rr['remaining_months']} month(s), forecast at completion would be "
        f"{fmt_money(rr['forecast_at_completion'], cur)} (variance {fmt_money(rr['forecast_variance'], cur)}). "
        "This ignores seasonality — the main forecast uses month-by-month analyst forecasts instead.",
        icon=":material/troubleshoot:")

with st.expander("Monthly forecast detail and assumptions (traceable to source)"):
    detail = fc.forecast_remaining_detail(data, as_of, scen_pct, category_pct)
    dview = detail.assign(period=detail["period"].map(period_label)).rename(columns={
        "category": "Category", "period": "Month", "budget_amount": "Phased budget",
        "base_forecast": "Base forecast", "source": "Source", "assumption": "Assumption",
        "adjustment_pct": "Adjustment %", "forecast_amount": "Forecast used"})
    st.dataframe(styled_table(dview, money=["Phased budget", "Base forecast", "Forecast used"],
                              pct=["Adjustment %"]), hide_index=True, use_container_width=True, height=380)

    st.markdown("**Save the adjusted base case** — writes the adjusted monthly amounts to the forecasts table "
                "(previous values kept in the audit log). Use this once adjustments are agreed.")
    note = st.text_input("Reason for the adjustment (required)", placeholder="e.g. Site manager fuel price update, Nov-26")
    if st.button("Save adjusted base case to database", disabled=not (note and category_pct)):
        base_detail = fc.forecast_remaining_detail(data, as_of, 0.0, category_pct)
        rows = fc.adjusted_forecast_rows(base_detail, data.project["project_id"], note)
        ops.upsert_forecasts(rows, "forecasting page (manual adjustment)", len(rows), 0, 0, note)
        st.success(f"Saved {len(rows)} forecast lines.")
        st.rerun()
    if not category_pct:
        st.caption("Enter at least one category-level adjustment to enable saving. Scenario percentages are "
                   "what-if views and are not saved.")
footer()
