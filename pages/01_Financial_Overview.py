"""Page 1 — Financial Overview (CFO / CEO landing page).

Answers four questions in ~30 seconds, top to bottom:
  1. What is the approved budget?          -> KPI card
  2. How much has been spent?              -> KPI card + spend-to-date chart (vs budget phased to date)
  3. What do we expect to spend in total?  -> KPI card + forecast comparison
  4. Are we likely to exceed the budget?   -> verdict line + forecast variance card
Then: which categories and issues need attention (one table, one list).
Every figure comes from src/finance; nothing is calculated here.
"""
from __future__ import annotations

import streamlit as st

from src.finance import budget_analysis as ba
from src.finance import forecasting as fc
from src.ui import charts
from src.ui.components import (Col, attention_panel, card_title, category_status, chart_card, chip, forecast_comparison,
                               html_table, kpi_card, kpi_row, verdict)
from src.ui.layout import eur2, footer, load_data, page_shell
from src.utils.config import reporting_rules
from src.utils.formatting import fmt_money, fmt_money_short, fmt_pct, period_label

data = load_data()
cur = data.base_currency
as_of = page_shell(data, "overview", "Financial Overview", "Project-level financial performance and budget monitoring.")

k = ba.headline_kpis(data, as_of)
cat = ba.category_summary(data, as_of)
status = ba.determine_financial_status(k, cat)
n_elapsed, n_total = len(fc.elapsed_periods(data, as_of)), len(data.fy_periods)
period_txt = f"{period_label(data.fy_periods[0])} – {period_label(as_of)}"
over_fac = k["forecast_variance"] > 0
over_ytd = k["variance_to_date"] > 0

# ------------------------------------------------------------------ Q4 first: are we on track? (one sentence)
verdict(
    status.status,
    f"Forecast to finish {fmt_money(abs(k['forecast_variance']), cur)} "
    f"({fmt_pct(abs(k['forecast_variance_pct']))}) {'over' if over_fac else 'under'} the approved budget.",
    f"Position at end of {period_label(as_of)}: spend to date is {fmt_pct(abs(k['variance_to_date_pct']))} "
    f"{'above' if over_ytd else 'below'} the budget phased to the same months. "
    "Status is set by fixed rules — see “Why this status?” below.")

# ------------------------------------------------------------------ four headline KPIs
kpi_row([
    kpi_card("Approved Budget", fmt_money_short(k["approved_budget"], cur),
             f"{period_label(data.fy_periods[0])} – {period_label(data.fy_periods[-1])} (full phase)", role="budget",
             tip=f"Sum of approved budget lines for the phase. Remaining approved budget: "
                 f"{fmt_money(k['remaining_budget'], cur)}."),
    kpi_card("Actual Expenditure", fmt_money_short(k["actual_to_date"], cur),
             f"to end {period_label(as_of)} · phased budget {fmt_money_short(k['budget_to_date'], cur)}", role="actual",
             badge=chip(f"{fmt_pct(k['variance_to_date_pct'], signed=True)} vs phased budget",
                        "bad" if over_ytd else "ok", "▲" if over_ytd else "▼"),
             tip=f"Recorded transactions to the end of {period_label(as_of)}, in EUR. Budget utilised: "
                 f"{fmt_pct(k['utilisation_pct'])} of the approved budget."),
    kpi_card("Forecast at Completion", fmt_money_short(k["forecast_at_completion"], cur),
             f"Actual + {fmt_money_short(k['forecast_remaining'], cur)} forecast remaining (base case)", role="forecast",
             tip="Actual expenditure to date + forecast remaining expenditure. A projection, not a commitment."),
    kpi_card("Forecast Budget Variance", ("+" if over_fac else "") + fmt_money_short(k["forecast_variance"], cur),
             "Forecast at completion − approved budget", tone="neg" if over_fac else "pos",
             badge=chip(f"{fmt_pct(k['forecast_variance_pct'], signed=True)} {'overspend' if over_fac else 'underspend'}",
                        "bad" if over_fac else "ok", "▲" if over_fac else "▼"),
             tip="Positive = forecast overspend; negative = forecast underspend."),
])
st.markdown(f'<div class="mk-secondary">Remaining approved budget <b>{fmt_money(k["remaining_budget"], cur)}</b> · '
            f'Budget utilised <b>{fmt_pct(k["utilisation_pct"])}</b> after <b>{n_elapsed} of {n_total}</b> months '
            f'({n_elapsed / n_total * 100:.0f}% of the phase)</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------ spend to date (main visual) + forecast summary
left, right = st.columns([7, 5], gap="medium")
with left:
    chart_card(f"Spend to date vs budget phased to date · {period_txt}",
               "Cumulative, closed months only. The gap at the last month is the variance to date "
               f"({'+' if over_ytd else ''}{fmt_money(k['variance_to_date'], cur)}).",
               charts.spend_to_date(ba.monthly_summary(data, as_of)))
with right:
    with st.container(border=True):
        card_title("Forecast at completion vs approved budget",
                   f"Base case · actuals to {period_label(as_of)} + {len(fc.remaining_periods(data, as_of))} "
                   "forecast month(s). Scenarios on the Forecasting page.")
        forecast_comparison(k["approved_budget"], k["actual_to_date"], k["forecast_remaining"],
                            k["forecast_at_completion"], k["forecast_variance"], k["forecast_variance_pct"], cur)

# ------------------------------------------------------------------ categories + issues
c1, c2 = st.columns([7.4, 4.6], gap="medium")
thr = reporting_rules()["significant_variance_pct"]
with c1:
    with st.container(border=True):
        card_title(f"Spending by category · {period_txt}",
                   f"Against the budget phased to date. Highlighted rows exceed plan by more than {thr:.0f}%. "
                   f"Status: ■ Over > +{thr:.0f}% · ▲ Above 0 to +{thr:.0f}% · ● On track · ▼ Under < −{thr:.0f}%.")
        view = cat.copy()
        view["status"] = [category_status(v, b, compact=True) for v, b in zip(view["variance_pct"], view["budgeted"])]
        needs = [bool(b and v == v and v > thr) for v, b in zip(view["variance_pct"], view["budgeted"])]
        tot = {"category": "Total", "budget_to_date": k["budget_to_date"], "actual_to_date": k["actual_to_date"],
               "variance_to_date": k["variance_to_date"], "variance_pct": k["variance_to_date_pct"], "status": ""}
        html_table(view, [Col("category", "Category"), Col("budget_to_date", "Phased budget", "money"),
                          Col("actual_to_date", "Actual", "money"), Col("variance_to_date", "Variance", "var"),
                          Col("variance_pct", "Var %", "varpct"), Col("status", "Status", "html")],
                   currency=cur, total=tot, highlight=needs)
with c2:
    with st.container(border=True):
        # Category to-date overspends are already visible in the table, so they are not repeated here.
        items = [i for i in ba.attention_items(data, as_of) if i["kind"] != "category_ytd_overspend"]
        n_bad = sum(i["severity"] == "bad" for i in items)
        card_title("Items requiring attention",
                   f"{len(items)} item(s), {n_bad} high priority · from monitoring rules and transaction flags only.")
        attention_panel(items, cur)

# ------------------------------------------------------------------ transparency (collapsed)
e1, e2 = st.columns(2, gap="medium")
with e1.expander("Why this status?"):
    rules = status.rules.assign(triggered=status.rules["triggered"].map({True: "▲ Triggered", False: "— Not triggered"}))
    st.dataframe(rules.rename(columns={"leads_to": "Leads to", "rule": "Rule", "triggered": "Result",
                                       "observed": "Observed"}),
                 hide_index=True, use_container_width=True,
                 column_config={"Rule": st.column_config.TextColumn(width="large")})
with e2.expander("Data integrity — reconciliation checks"):
    recon = ba.reconciliation_checks(data, as_of)
    st.dataframe(recon.assign(passed=recon["passed"].map({True: "● Pass", False: "■ Fail"}))
                 .style.format({"expected": eur2, "calculated": eur2, "difference": eur2}),
                 hide_index=True, use_container_width=True)
footer()
