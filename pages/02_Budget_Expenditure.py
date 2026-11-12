"""Page 2 — Budget & Expenditure: where is the money going?"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.finance import budget_analysis as ba
from src.finance import forecasting as fc
from src.ui import charts
from src.ui.components import Col, category_status, chart_card, chip, html_table, section
from src.ui.layout import download_df, eur2, footer, load_data, page_shell
from src.utils.config import reporting_rules
from src.utils.formatting import fmt_money, fmt_pct, period_label

data = load_data()
as_of = page_shell(data, "budget", "Budget & Expenditure",
                   "Approved budget, actual spend and variance by expense category — investigate where the money is going.")
cur = data.base_currency
tx = data.transactions

# ------------------------------------------------------------------ filters (one row, in a card)
elapsed = fc.elapsed_periods(data, as_of)
all_cats = [c for c in pd.unique(pd.concat([data.budgets["category"], tx["category"]]))]
with st.container(border=True):
    f1, f2, f3, f4 = st.columns([1.4, 1.6, 1.6, 1.2])
    period_range = f1.select_slider("Financial period", options=elapsed, value=(elapsed[0], elapsed[-1]),
                                    format_func=period_label)
    sel_cats = f2.multiselect("Expense category", all_cats, placeholder="All categories")
    sel_supp = f3.multiselect("Supplier", sorted(tx["supplier"].dropna().unique()), placeholder="All suppliers")
    sel_status = f4.multiselect("Transaction status", sorted(tx["status"].dropna().unique()), placeholder="All statuses")

periods = [p for p in elapsed if period_range[0] <= p <= period_range[1]]
ftx = tx[tx["period"].isin(periods)]
if sel_supp:
    ftx = ftx[ftx["supplier"].isin(sel_supp)]
if sel_status:
    ftx = ftx[ftx["status"].isin(sel_status)]
if sel_cats:
    ftx = ftx[ftx["category"].isin(sel_cats)]
cat_table = ba.category_table_for_periods(data, periods, ftx)
if sel_cats:
    cat_table = cat_table[cat_table["category"].isin(sel_cats)]
total = ba.totals_row(cat_table)

if sel_supp or sel_status:
    st.warning("Supplier/status filters are applied: actual expenditure shows only matching transactions, while "
               "budgets are not split by supplier or status. Variances in this view are partial and should not be "
               "read as category performance.", icon=":material/filter_alt:")

# ------------------------------------------------------------------ window summary
thr = reporting_rules()["significant_variance_pct"]
n_over = int(((cat_table["variance_pct"] > thr) & cat_table["budgeted"]).sum())
over = total["variance"] > 0
# One summary line instead of KPI cards: these totals are also the table's total row.
st.markdown(f'<div class="mk-secondary">Selected window <b>{period_label(periods[0])} – {period_label(periods[-1])}</b> · '
            f'budget <b>{fmt_money(total["budget_for_period"], cur)}</b> · actual <b>{fmt_money(total["actual"], cur)}</b> '
            f'({len(ftx):,} transactions) · variance {chip(("+" if over else "") + fmt_money(total["variance"], cur) + " (" + fmt_pct(total["variance_pct"], signed=True) + ")", "bad" if over else "ok", "▲" if over else "▼")} · '
            f'<b>{n_over}</b> categor{"y" if n_over == 1 else "ies"} over plan by more than {thr:.0f}%</div>',
            unsafe_allow_html=True)

# ------------------------------------------------------------------ comparison table
section("Budget vs actual by category",
        "Variance = Actual − Budget for period (positive = overspend). Remaining budget and utilisation are measured "
        "against the full approved budget.")
view = cat_table.copy()
view["status"] = [category_status(v, b) for v, b in zip(view["variance_pct"], view["budgeted"])]
html_table(view, [
    Col("category", "Category"), Col("approved_budget", "Approved", "money"),
    Col("budget_for_period", "Budget (period)", "money"), Col("actual", "Actual", "money"),
    Col("remaining_budget", "Remaining", "money"), Col("variance", "Variance", "var"),
    Col("variance_pct", "Var %", "varpct"), Col("utilisation_pct", "Utilised", "bar"), Col("status", "Status", "html"),
], currency=cur, total={**total, "status": ""},
   highlight=[bool(b and v == v and v > thr) for v, b in zip(view["variance_pct"], view["budgeted"])])
st.caption("Status: ■ Overspend > +10% · ▲ Above plan 0 to +10% · ● On track 0 to −10% · ▼ Underspend below −10% · "
           "■ Unbudgeted = spend with no approved budget (re-code in the Transaction Register).")
export = pd.concat([cat_table, pd.DataFrame([total])], ignore_index=True).drop(columns=["budgeted"])
download_df(export, "Download table (CSV)", f"category_summary_{periods[0]}_{periods[-1]}.csv")

# ------------------------------------------------------------------ one trend chart: when did spending deviate?
chart_card(f"Monthly spend vs phased budget · {period_label(periods[0])} – {period_label(periods[-1])}",
           "Answers: in which months did spending run above or below plan? Hover for the monthly variance."
           + (" Supplier/status filters apply to actuals only." if (sel_supp or sel_status) else ""),
           charts.monthly_actual_vs_budget(ba.monthly_budget_vs_actual(data, periods, ftx, sel_cats or None)))

# ------------------------------------------------------------------ drill-down
section("Inspect transactions", "Largest first. Amounts converted to EUR at the configured planning rates.")
d1, d2 = st.columns([1.4, 3])
drill_cat = d1.selectbox("Category to inspect", ["All"] + list(cat_table["category"]))
dtx = ftx if drill_cat == "All" else ftx[ftx["category"] == drill_cat]
d2.markdown(f'<div style="padding-top:1.9rem;font-size:13px;color:var(--muted)">{len(dtx)} transaction(s) · total '
            f'<b style="color:var(--ink)">{fmt_money(dtx["amount_base"].sum(), cur)}</b></div>', unsafe_allow_html=True)
dview = dtx[["transaction_id", "transaction_date", "supplier", "description", "category", "amount", "currency",
             "amount_base", "status", "invoice_id", "document_reference"]].copy()
dview["transaction_date"] = dview["transaction_date"].dt.date
dview = dview.sort_values("amount_base", ascending=False).rename(columns={
    "transaction_id": "Transaction ID", "transaction_date": "Date", "supplier": "Supplier", "description": "Description",
    "category": "Category", "amount": "Amount", "currency": "Ccy", "amount_base": f"Amount ({cur})", "status": "Status",
    "invoice_id": "Invoice", "document_reference": "Document"})
st.dataframe(dview.style.format({"Amount": "{:,.2f}", f"Amount ({cur})": eur2}), hide_index=True,
             use_container_width=True, height=380)
footer()
