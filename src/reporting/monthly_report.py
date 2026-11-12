"""Monthly financial report builder.

The report separates three kinds of content:

1. FACTS            — numbers calculated by ``src/finance`` from stored records.
2. OBSERVATIONS     — rule-based statements generated deterministically from those
                      numbers (e.g. "Transport is 29.5% over its phased budget").
                      They never contain a cause/explanation, because the records do
                      not contain one.
3. ANALYST COMMENTARY — free text typed by the analyst. Only a human supplies
                      explanations for variances.

An optional AI drafting step could be added later (see ARCHITECTURE.md §14); it would
only receive the FACTS and must be labelled as a draft for human review.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

from src.data.preprocessing import ProjectData
from src.finance import budget_analysis as ba
from src.finance import calculations as calc
from src.utils.config import illustrative_label, reporting_rules
from src.utils.formatting import fmt_money, fmt_pct, period_label


@dataclass
class MonthlyReport:
    project: dict
    report_month: str
    generated_at: str
    kpis: dict[str, float]
    month_figures: dict[str, float]
    status: ba.StatusResult
    category_table: pd.DataFrame
    monthly_table: pd.DataFrame
    deviations: pd.DataFrame
    data_quality: pd.DataFrame
    flagged_transactions: pd.DataFrame
    reconciliation: pd.DataFrame
    observations: list[str] = field(default_factory=list)
    attention_items: list[str] = field(default_factory=list)
    data_warnings: list[str] = field(default_factory=list)
    analyst_commentary: str = ""
    currency: str = "EUR"
    disclaimer: str = illustrative_label()


def significant_deviations(cat_table: pd.DataFrame) -> pd.DataFrame:
    """Categories where BOTH |variance %| and |variance amount| exceed the configured thresholds,
    measured to date (vs phased budget) or at completion (forecast)."""
    r = reporting_rules()
    pct, absv = r["significant_variance_pct"], r["significant_variance_abs"]
    rows = []
    for row in cat_table.itertuples():
        for basis, var, vpct in (("To date vs phased budget", row.variance_to_date, row.variance_pct),
                                 ("Forecast at completion vs budget", row.forecast_variance,
                                  row.forecast_variance_pct)):
            if not row.budgeted:
                continue
            if not calc.is_missing(vpct) and abs(vpct) > pct and abs(var) > absv:
                rows.append({"category": row.category, "basis": basis, "variance": var, "variance_pct": vpct,
                             "direction": "Overspend" if var > 0 else "Underspend"})
    return pd.DataFrame(rows, columns=["category", "basis", "variance", "variance_pct", "direction"])


def build_monthly_report(data: ProjectData, report_month: str, analyst_commentary: str = "") -> MonthlyReport:
    """Assemble every section of the monthly report for ``report_month`` ('YYYY-MM')."""
    cur = data.base_currency
    kpis = ba.headline_kpis(data, report_month)
    cat = ba.category_summary(data, report_month)
    status = ba.determine_financial_status(kpis, cat)
    monthly = ba.monthly_summary(data, report_month)
    m = monthly[monthly["period"] == report_month]
    month_budget = float(m["budget"].iloc[0]) if not m.empty else 0.0
    month_actual = float(m["actual"].iloc[0]) if not m.empty and pd.notna(m["actual"].iloc[0]) else 0.0
    month_var = calc.budget_variance(month_actual, month_budget)
    month_figures = {"budget": month_budget, "actual": month_actual, "variance": month_var,
                     "variance_pct": calc.variance_percentage(month_var, month_budget)}

    flagged = ba.transaction_flags(data)
    flagged_in_scope = flagged[flagged["period"] <= report_month]
    dq = ba.data_quality_summary(flagged_in_scope)
    deviations = significant_deviations(cat)
    recon = ba.reconciliation_checks(data, report_month)

    # ---------------- deterministic observations (facts restated, no causes) ----------------
    obs: list[str] = []
    obs.append(f"Spend in {period_label(report_month)} was {fmt_money(month_actual, cur)} against a phased budget "
               f"of {fmt_money(month_budget, cur)} ({fmt_pct(month_figures['variance_pct'], signed=True)}).")
    obs.append(f"Spend to date is {fmt_money(kpis['actual_to_date'], cur)}, "
               f"{fmt_pct(kpis['utilisation_pct'])} of the approved budget of {fmt_money(kpis['approved_budget'], cur)}, "
               f"and {fmt_pct(kpis['variance_to_date_pct'], signed=True)} versus the budget phased to date.")
    obs.append(f"Forecast at completion is {fmt_money(kpis['forecast_at_completion'], cur)}, "
               f"a forecast variance of {fmt_money(kpis['forecast_variance'], cur)} "
               f"({fmt_pct(kpis['forecast_variance_pct'], signed=True)}; positive = overspend).")
    budgeted = cat[cat["budgeted"]]
    if not budgeted.empty:
        top_over = budgeted.sort_values("variance_to_date", ascending=False).iloc[0]
        top_under = budgeted.sort_values("variance_to_date").iloc[0]
        if top_over["variance_to_date"] > 0:
            obs.append(f"Largest overspend to date: {top_over['category']} "
                       f"({fmt_money(top_over['variance_to_date'], cur)}, {fmt_pct(top_over['variance_pct'], signed=True)}).")
        if top_under["variance_to_date"] < 0:
            obs.append(f"Largest underspend to date: {top_under['category']} "
                       f"({fmt_money(top_under['variance_to_date'], cur)}, {fmt_pct(top_under['variance_pct'], signed=True)}).")

    # ---------------- items requiring management attention ----------------
    attention: list[str] = []
    if status.status != "Within Budget":
        attention.append(f"Financial status is {status.status.upper()}: " + "; ".join(status.reasons))
    for row in deviations[deviations["direction"] == "Overspend"].itertuples():
        attention.append(f"{row.category}: {row.basis.lower()} {fmt_money(row.variance, cur)} "
                         f"({fmt_pct(row.variance_pct, signed=True)}) — explanation required from project team.")
    for check in ("Duplicate invoice reference", "Uncategorised", "Status: Queried", "Unusually large"):
        hit = dq[dq["check"] == check]
        if not hit.empty and hit["transactions"].iloc[0] > 0:
            attention.append(f"{check}: {int(hit['transactions'].iloc[0])} transaction(s), "
                             f"{fmt_money(hit['amount_affected'].iloc[0], cur)} — review before month-end sign-off.")
    pending = dq[dq["check"] == "Status: Pending Review"]
    if not pending.empty and pending["transactions"].iloc[0] > 0:
        attention.append(f"{int(pending['transactions'].iloc[0])} transaction(s) totalling "
                         f"{fmt_money(pending['amount_affected'].iloc[0], cur)} are still pending verification; "
                         "figures may change.")
    if not recon["passed"].all():
        attention.append("One or more reconciliation checks FAILED — do not distribute until resolved.")

    return MonthlyReport(
        project=data.project, report_month=report_month,
        generated_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), kpis=kpis, month_figures=month_figures,
        status=status, category_table=cat, monthly_table=monthly, deviations=deviations, data_quality=dq,
        flagged_transactions=flagged_in_scope[flagged_in_scope["flag_count"] > 0], reconciliation=recon,
        observations=obs, attention_items=attention, data_warnings=list(data.warnings),
        analyst_commentary=analyst_commentary, currency=cur,
    )
