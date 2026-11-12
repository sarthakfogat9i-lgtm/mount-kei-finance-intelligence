"""Page 3 — Transaction Register: search, filter, sort and investigate every transaction."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.database import operations as ops
from src.finance import budget_analysis as ba
from src.ui.components import kpi_card, kpi_row, section
from src.ui.layout import download_df, eur2, footer, load_data, page_shell
from src.utils.config import categories, transaction_statuses, uncategorised_label
from src.utils.formatting import fmt_money

data = load_data()
as_of = page_shell(data, "transactions", "Transaction Register",
                   "Every recorded expense, with automatic data-quality and anomaly flags.")
cur = data.base_currency
flagged = ba.transaction_flags(data)
dq = ba.data_quality_summary(flagged).set_index("check")


def _n(check: str) -> int:
    return int(dq.loc[check, "transactions"]) if check in dq.index else 0


n_flag = int((flagged["flag_count"] > 0).sum())
n_unverified = _n("Status: Pending Review") + _n("Status: Queried")
# Four review counts only (breakdown by flag type is in the "Flag" filter and the data-quality expander).
kpi_row([
    kpi_card("Transactions", f"{len(flagged):,}", f"Total {fmt_money(flagged['amount_base'].sum(), cur)}",
             tip="All recorded transactions in the register (all periods), converted to EUR."),
    kpi_card("Flagged for review", f"{n_flag:,}", "At least one data-quality or anomaly rule", tone="neg" if n_flag else "",
             tip="Filter by flag type below; rule definitions are under 'What do the flags mean?'."),
    kpi_card("Possible duplicates", f"{_n('Duplicate transaction ID') + _n('Duplicate invoice reference')}",
             "Same transaction ID or invoice reference", tone="neg" if _n("Duplicate invoice reference") else ""),
    kpi_card("Not yet verified", f"{n_unverified}",
             f"{_n('Status: Pending Review')} pending review · {_n('Status: Queried')} queried"),
])

# ------------------------------------------------------------------ filters
section("Register", "Search, filter and sort. Click a column header to re-sort; flagged rows are tinted.")
with st.container(border=True):
    s1, s2, s3, s4, s5 = st.columns([2.2, 1.4, 1.2, 1.5, 1.1])
    query = s1.text_input("Search", placeholder="ID, invoice, supplier, description, document…")
    f_cat = s2.multiselect("Category", sorted(flagged["category"].dropna().unique()), placeholder="All")
    f_status = s3.multiselect("Status", transaction_statuses(), placeholder="All")
    f_flags = s4.multiselect("Flag", list(ba.FLAG_LABELS.values()), placeholder="Any / none")
    sort_by = s5.selectbox("Sort by", ["Date (newest)", "Date (oldest)", "Amount (largest)", "Amount (smallest)"])
    only_flagged = st.toggle("Show only flagged transactions", value=False)

view = flagged.copy()
if query:
    q = query.lower()
    hay = view[["transaction_id", "invoice_id", "supplier", "description", "document_reference", "category"]] \
        .fillna("").astype(str).agg(" ".join, axis=1).str.lower()
    view = view[hay.str.contains(q, regex=False)]
if f_cat:
    view = view[view["category"].isin(f_cat)]
if f_status:
    view = view[view["status"].isin(f_status)]
if f_flags:
    inv = {v: k for k, v in ba.FLAG_LABELS.items()}
    mask = pd.Series(False, index=view.index)
    for label in f_flags:
        mask |= view[inv[label]]
    view = view[mask]
if only_flagged:
    view = view[view["flag_count"] > 0]
sort_map = {"Date (newest)": ("transaction_date", False), "Date (oldest)": ("transaction_date", True),
            "Amount (largest)": ("amount_base", False), "Amount (smallest)": ("amount_base", True)}
col, asc = sort_map[sort_by]
view = view.sort_values(col, ascending=asc)

table = pd.DataFrame({
    "Transaction ID": view["transaction_id"], "Flags": view["flags"], "Invoice ID": view["invoice_id"],
    "Date": view["transaction_date"].dt.date, "Supplier": view["supplier"], "Description": view["description"],
    "Category": view["category"], "Amount": view["amount"], "Currency": view["currency"],
    f"Amount ({cur})": view["amount_base"], "Project": view["project_id"], "Status": view["status"],
    "Document Reference": view["document_reference"],
})
st.caption(f"Showing {len(table):,} of {len(flagged):,} transactions · "
           f"{fmt_money(view['amount_base'].sum(), cur)}. Amounts in other currencies are converted at the "
           "configured illustrative planning rates. Document references beginning ‘SYN-DOC’ are synthetic "
           "placeholders: no real invoice exists.")


# Restrained status badges: icon + text (never colour alone). Display only — data is unchanged.
STATUS_BADGE = {"Verified": "● Verified", "Pending Review": "◐ Pending review", "Queried": "▲ Queried"}
display = table.assign(Status=table["Status"].map(lambda s_: STATUS_BADGE.get(s_, s_)),
                       Flags=table["Flags"].map(lambda f: f"⚑ {f}" if f else ""))


def _row_style(row: pd.Series) -> list[str]:
    return ["background-color: #FDF6F5" if row["Flags"] else "" for _ in row]


st.dataframe(display.style.apply(_row_style, axis=1).format({"Amount": "{:,.2f}", f"Amount ({cur})": eur2},
                                                            na_rep="—"),
             hide_index=True, use_container_width=True, height=520,
             column_config={"Flags": st.column_config.TextColumn(width="medium"),
                            "Description": st.column_config.TextColumn(width="medium")})
download_df(table, "Download filtered register (CSV)", "transaction_register.csv")

with st.expander("What do the flags mean?"):
    st.markdown(f"""
| Flag | Rule |
|---|---|
| Duplicate transaction ID | The same transaction ID appears more than once. |
| Duplicate invoice reference | The same invoice ID appears on more than one transaction — possible double payment. |
| Missing values | Supplier, description, invoice ID or document reference is blank. |
| Uncategorised | Category is blank/‘{uncategorised_label()}’ or not one of the recognised categories. |
| Category budget exceeded | The running total for the category (by date) has passed its full approved budget. |
| Unusually large | Amount > {ba.anomaly_rules()['large_vs_category_median_multiple']:.0f}× the category median and ≥ €{ba.anomaly_rules()['large_min_amount']:,.0f}. |
| Credit note | Negative amount (refund/credit). Reduces spend. |
| No FX rate | Currency has no configured conversion rate; excluded from totals. |
| Outside budget phase | Date falls outside the approved budget months; excluded from budget comparisons. |
""")

with st.expander("Data-quality summary"):
    st.dataframe(ba.data_quality_summary(flagged).style.format({"amount_affected": eur2}),
                 hide_index=True, use_container_width=True)

# ------------------------------------------------------------------ review action (audited)
section("Review a transaction", "Analyst actions update the database and are written to the audit log with the previous value.")
review = st.container(border=True)
r1, r2, r3, r4 = review.columns([1.6, 1.3, 1.8, 0.9])
ids = view["transaction_id"].tolist() or flagged["transaction_id"].tolist()
tid = r1.selectbox("Transaction", ids)
current = flagged[flagged["transaction_id"] == tid].iloc[0]
new_status = r2.selectbox("Status", transaction_statuses(),
                          index=transaction_statuses().index(current["status"])
                          if current["status"] in transaction_statuses() else 0)
cat_options = categories() + [uncategorised_label()]
new_cat = r3.selectbox("Category", cat_options,
                       index=cat_options.index(current["category"]) if current["category"] in cat_options else 0)
r4.write("")
r4.write("")
if r4.button("Save", type="primary", use_container_width=True):
    changed = False
    if new_status != current["status"]:
        ops.update_transaction_status(tid, new_status)
        changed = True
    if new_cat != current["category"]:
        ops.update_transaction_category(tid, new_cat)
        changed = True
    if changed:
        st.success(f"{tid} updated and logged.")
        st.rerun()
    else:
        st.info("No change to save.")
review.caption(f"Selected: {current['description']} · {current['supplier']} · "
           f"{current['amount']:,.2f} {current['currency']} · flags: {current['flags'] or 'none'}")

with st.expander("Audit log (latest 100 changes)"):
    st.dataframe(ops.get_audit_log(100), hide_index=True, use_container_width=True)
footer()
