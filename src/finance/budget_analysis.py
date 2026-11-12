"""Budget analysis: category and monthly summaries, transaction flags,
financial status rules and reconciliation checks.

All functions take a ``ProjectData`` (amounts already in base currency) and an
``as_of`` month ('YYYY-MM'). "To date" always means: budget months up to and
including ``as_of``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.data.preprocessing import ProjectData
from src.finance import calculations as calc
from src.finance import forecasting as fc
from src.utils.config import anomaly_rules, categories, status_rules, uncategorised_label


# --------------------------------------------------------------------------- headline KPIs

def headline_kpis(data: ProjectData, as_of: str, scenario_pct: float = 0.0) -> dict[str, float]:
    """The six landing-page KPIs plus the phased budget to date."""
    elapsed = fc.elapsed_periods(data, as_of)
    approved = calc.total_approved_budget(data.budgets)
    budget_to_date = calc.total_approved_budget(data.budgets, elapsed)
    actual = calc.total_actual_expenditure(data.transactions, elapsed)
    totals = fc.forecast_totals(data, as_of, scenario_pct)
    return {
        "approved_budget": approved,
        "budget_to_date": budget_to_date,
        "actual_to_date": actual,
        "remaining_budget": calc.remaining_budget(approved, actual),
        "forecast_remaining": totals["forecast_remaining"],
        "forecast_at_completion": totals["forecast_at_completion"],
        "forecast_variance": totals["forecast_variance"],
        "forecast_variance_pct": totals["forecast_variance_pct"],
        "utilisation_pct": calc.budget_utilisation(actual, approved),
        "variance_to_date": calc.budget_variance(actual, budget_to_date),
        "variance_to_date_pct": calc.variance_percentage(calc.budget_variance(actual, budget_to_date),
                                                         budget_to_date),
    }


# --------------------------------------------------------------------------- category summary

def category_summary(data: ProjectData, as_of: str, transactions: pd.DataFrame | None = None,
                     scenario_pct: float = 0.0) -> pd.DataFrame:
    """Budget vs actual per category.

    Columns
    -------
    approved_budget     full approved budget for the phase
    budget_to_date      approved budget phased to months <= as_of
    actual_to_date      recorded spend in months <= as_of
    remaining_budget    approved_budget - actual_to_date
    variance_to_date    actual_to_date - budget_to_date   (positive = overspend)
    variance_pct        variance_to_date / budget_to_date x 100
    utilisation_pct     actual_to_date / approved_budget x 100
    forecast_at_completion, forecast_variance, forecast_variance_pct (base case)

    ``transactions`` may be passed pre-filtered (e.g. by supplier or status);
    by default all transactions are used.
    """
    elapsed = fc.elapsed_periods(data, as_of)
    tx = data.transactions if transactions is None else transactions
    tx = tx[tx["period"].isin(elapsed)]
    approved = data.budgets.groupby("category")["amount_base"].sum()
    phased = data.budgets[data.budgets["financial_period"].isin(elapsed)].groupby("category")["amount_base"].sum()
    actual = calc.category_expenditure(tx)
    fcast = fc.forecast_by_category(data, as_of, scenario_pct).set_index("category")

    order = categories() + sorted(set(actual.index) - set(categories()))
    rows = []
    for c in order:
        if c not in approved.index and c not in actual.index:
            continue
        bud = float(approved.get(c, 0.0))
        btd = float(phased.get(c, 0.0))
        act = float(actual.get(c, 0.0))
        var = calc.budget_variance(act, btd)
        rows.append({
            "category": c, "approved_budget": round(bud, 2), "budget_to_date": round(btd, 2),
            "actual_to_date": round(act, 2), "remaining_budget": calc.remaining_budget(bud, act),
            "variance_to_date": var, "variance_pct": calc.variance_percentage(var, btd),
            "utilisation_pct": calc.budget_utilisation(act, bud),
            "forecast_at_completion": float(fcast["forecast_at_completion"].get(c, act)),
            "forecast_variance": float(fcast["forecast_variance"].get(c, act - bud)),
            "forecast_variance_pct": float(fcast["forecast_variance_pct"].get(c, np.nan)),
            "budgeted": c in approved.index,
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- monthly summary

def monthly_summary(data: ProjectData, as_of: str, scenario_pct: float = 0.0) -> pd.DataFrame:
    """One row per budget month: budget, actual (closed months), forecast (future months) and cumulatives.

    ``outturn`` = actual for closed months, forecast for future months.
    """
    periods = data.fy_periods
    budget = data.budgets.groupby("financial_period")["amount_base"].sum().reindex(periods, fill_value=0.0)
    actual = calc.monthly_expenditure(data.transactions).reindex(periods, fill_value=0.0)
    detail = fc.forecast_remaining_detail(data, as_of, scenario_pct)
    forecast = detail.groupby("period")["forecast_amount"].sum().reindex(periods, fill_value=0.0)
    closed = pd.Series([p <= as_of for p in periods], index=periods)

    df = pd.DataFrame({"period": periods, "budget": budget.values,
                       "actual": actual.where(closed, np.nan).values,
                       "forecast": forecast.where(~closed, np.nan).values, "closed": closed.values})
    df["outturn"] = df["actual"].fillna(0) + df["forecast"].fillna(0)
    df["variance"] = df["actual"] - df["budget"]
    df["cumulative_budget"] = df["budget"].cumsum().round(2)
    df["cumulative_actual"] = df["actual"].cumsum().where(df["closed"]).round(2)
    df["cumulative_outturn"] = df["outturn"].cumsum().round(2)
    return df


# --------------------------------------------------------------------------- transaction flags

FLAG_LABELS = {
    "flag_duplicate_id": "Duplicate transaction ID",
    "flag_duplicate_invoice": "Duplicate invoice reference",
    "flag_missing_values": "Missing values",
    "flag_uncategorised": "Uncategorised",
    "flag_category_over_budget": "Category budget exceeded",
    "flag_unusual_amount": "Unusually large",
    "flag_credit_note": "Credit note",
    "flag_fx_missing": "No FX rate",
    "flag_outside_phase": "Outside budget phase",
}


def transaction_flags(data: ProjectData) -> pd.DataFrame:
    """Return the transaction register with boolean flag columns and a readable ``flags`` text.

    Rules (all transparent):
    * duplicate ID / invoice: the value appears more than once (all occurrences flagged)
    * missing values: any of supplier, description, invoice_id, document_reference is blank
    * uncategorised: category is blank, 'Uncategorised', or not a recognised category
    * category budget exceeded: running total of the category (by date) exceeds its full approved budget
    * unusually large: amount > N x category median AND >= minimum amount (config)
    """
    rules = anomaly_rules()
    tx = data.transactions.copy()
    if tx.empty:
        for col in FLAG_LABELS:
            tx[col] = pd.Series(dtype=bool)
        tx["flags"] = pd.Series(dtype=str)
        return tx

    tx["flag_duplicate_id"] = tx["transaction_id"].duplicated(keep=False)
    inv = tx["invoice_id"].fillna("").astype(str).str.strip()
    tx["flag_duplicate_invoice"] = inv.ne("") & inv.duplicated(keep=False)
    required_text = ["supplier", "description", "invoice_id", "document_reference"]
    blank = tx[required_text].isna() | tx[required_text].astype(str).apply(lambda s: s.str.strip().eq(""))
    tx["missing_fields"] = blank.apply(lambda r: ", ".join(c for c, v in r.items() if v), axis=1)
    tx["flag_missing_values"] = tx["missing_fields"].ne("")
    tx["flag_uncategorised"] = ~tx["category"].isin(categories())

    budget_by_cat = data.budgets.groupby("category")["amount_base"].sum()
    tx = tx.sort_values(["transaction_date", "transaction_id"])
    tx["category_running_total"] = tx.groupby("category")["amount_base"].cumsum()
    cat_budget = tx["category"].map(budget_by_cat)
    tx["flag_category_over_budget"] = cat_budget.notna() & (tx["category_running_total"] > cat_budget)

    median = tx.groupby("category")["amount_base"].transform("median")
    tx["flag_unusual_amount"] = (tx["amount_base"] > rules["large_vs_category_median_multiple"] * median) & \
                                (tx["amount_base"] >= rules["large_min_amount"])
    tx["flag_credit_note"] = tx["amount"] < 0
    tx["flag_fx_missing"] = tx["fx_missing"]
    tx["flag_outside_phase"] = ~tx["period"].isin(data.fy_periods)

    flag_cols = list(FLAG_LABELS)
    tx["flags"] = tx[flag_cols].apply(lambda r: "; ".join(FLAG_LABELS[c] for c in flag_cols if r[c]), axis=1)
    tx["flag_count"] = tx[flag_cols].sum(axis=1)
    return tx.sort_values(["transaction_date", "transaction_id"]).reset_index(drop=True)


def data_quality_summary(flagged: pd.DataFrame) -> pd.DataFrame:
    """Count of transactions per flag, plus amount affected."""
    rows = []
    for col, label in FLAG_LABELS.items():
        if col in flagged:
            sub = flagged[flagged[col]]
            rows.append({"check": label, "transactions": int(len(sub)),
                         "amount_affected": round(float(sub["amount_base"].sum(skipna=True)), 2)})
    for status in ("Pending Review", "Queried"):
        sub = flagged[flagged["status"] == status]
        rows.append({"check": f"Status: {status}", "transactions": int(len(sub)),
                     "amount_affected": round(float(sub["amount_base"].sum(skipna=True)), 2)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- financial status

@dataclass
class StatusResult:
    status: str                                   # Within Budget | Watchlist | Potential Overspend
    reasons: list[str] = field(default_factory=list)
    rules: pd.DataFrame = field(default_factory=pd.DataFrame)


def determine_financial_status(kpis: dict[str, float], cat_summary: pd.DataFrame) -> StatusResult:
    """Apply the transparent status rules from config/settings.yaml.

    Potential Overspend  if forecast variance % >  overspend threshold (default 5%)
                         or actual to date already exceeds the full approved budget
    Watchlist            if forecast variance % >  watchlist threshold (default 0%)
                         or any category forecast variance % > category threshold (default 10%)
                         or spend to date exceeds phased budget to date by > YTD threshold (default 5%)
    Within Budget        otherwise
    """
    r = status_rules()
    fvp = kpis["forecast_variance_pct"]
    ytd = kpis["variance_to_date_pct"]
    budgeted = cat_summary[cat_summary["budgeted"]]
    over_cats = budgeted[budgeted["forecast_variance_pct"] > r["watchlist_category_variance_pct"]]
    unbudgeted = cat_summary[~cat_summary["budgeted"] & (cat_summary["actual_to_date"] != 0)]

    checks = [
        ("Potential Overspend", f"Forecast at completion more than {r['overspend_forecast_variance_pct']:.1f}% "
                                "above approved budget", not calc.is_missing(fvp) and fvp > r["overspend_forecast_variance_pct"],
         f"{fvp:+.1f}%" if not calc.is_missing(fvp) else "n/a"),
        ("Potential Overspend", "Actual expenditure already exceeds the full approved budget",
         kpis["actual_to_date"] > kpis["approved_budget"] > 0,
         f"{kpis['utilisation_pct']:.1f}% used" if not calc.is_missing(kpis['utilisation_pct']) else "n/a"),
        ("Watchlist", f"Forecast at completion above approved budget (> {r['watchlist_forecast_variance_pct']:.1f}%)",
         not calc.is_missing(fvp) and fvp > r["watchlist_forecast_variance_pct"],
         f"{fvp:+.1f}%" if not calc.is_missing(fvp) else "n/a"),
        ("Watchlist", f"A category is forecast more than {r['watchlist_category_variance_pct']:.0f}% over its budget",
         len(over_cats) > 0, ", ".join(f"{c} ({v:+.1f}%)" for c, v in
                                       zip(over_cats["category"], over_cats["forecast_variance_pct"])) or "none"),
        ("Watchlist", f"Spend to date more than {r['watchlist_ytd_variance_pct']:.0f}% above budget phased to date",
         not calc.is_missing(ytd) and ytd > r["watchlist_ytd_variance_pct"],
         f"{ytd:+.1f}%" if not calc.is_missing(ytd) else "n/a"),
        ("Watchlist", "Spending recorded against an unbudgeted / unrecognised category",
         len(unbudgeted) > 0, ", ".join(unbudgeted["category"]) or "none"),
    ]
    rules_df = pd.DataFrame(checks, columns=["leads_to", "rule", "triggered", "observed"])
    if rules_df[(rules_df.leads_to == "Potential Overspend") & rules_df.triggered].shape[0]:
        status = "Potential Overspend"
    elif rules_df[(rules_df.leads_to == "Watchlist") & rules_df.triggered].shape[0]:
        status = "Watchlist"
    else:
        status = "Within Budget"
    reasons = [f"{row.rule} — observed {row.observed}" for row in rules_df.itertuples() if row.triggered]
    if not reasons:
        reasons = ["No status rule triggered: forecast and spend to date are within approved budget."]
    return StatusResult(status=status, reasons=reasons, rules=rules_df)


# --------------------------------------------------------------------------- reconciliation

def reconciliation_checks(data: ProjectData, as_of: str, tolerance: float = 0.01) -> pd.DataFrame:
    """Integrity checks that the figures shown on screen agree with each other.

    1. Sum of category budgets == total approved budget
    2. Sum of monthly budgets == total approved budget
    3. Sum of category actuals == transaction register total (to date)
    4. Sum of monthly actuals == transaction register total (to date)
    5. FAC == actual to date + forecast remaining
    """
    elapsed = fc.elapsed_periods(data, as_of)
    total_budget = calc.total_approved_budget(data.budgets)
    cat_budget = round(float(data.budgets.groupby("category")["amount_base"].sum().sum()), 2)
    month_budget = round(float(data.budgets.groupby("financial_period")["amount_base"].sum().sum()), 2)
    tx = data.transactions[data.transactions["period"].isin(elapsed)]
    register_total = round(float(tx["amount_base"].sum(skipna=True)), 2)
    cat_actual = round(float(calc.category_expenditure(tx).sum()), 2)
    month_actual = round(float(calc.monthly_expenditure(tx).sum()), 2)
    t = fc.forecast_totals(data, as_of)
    checks = [
        ("Category budgets reconcile to total approved budget", total_budget, cat_budget),
        ("Monthly budgets reconcile to total approved budget", total_budget, month_budget),
        ("Category actuals reconcile to transaction register", register_total, cat_actual),
        ("Monthly actuals reconcile to transaction register", register_total, month_actual),
        ("Forecast at completion = actual to date + forecast remaining",
         round(t["actual_to_date"] + t["forecast_remaining"], 2), t["forecast_at_completion"]),
    ]
    df = pd.DataFrame(checks, columns=["check", "expected", "calculated"])
    df["difference"] = (df["calculated"] - df["expected"]).round(2)
    df["passed"] = df["difference"].abs() <= tolerance
    return df


def is_known_category(category: str) -> bool:
    return category in categories() or category == uncategorised_label()


# --------------------------------------------------------------------------- filtered views

def category_table_for_periods(data: ProjectData, periods: list[str],
                               transactions: pd.DataFrame | None = None) -> pd.DataFrame:
    """Budget vs actual per category for an arbitrary window of months.

    budget_for_period = approved budget phased to the same months
    variance          = actual - budget_for_period (positive = overspend)
    remaining_budget / utilisation_pct are measured against the FULL approved budget.
    ``transactions`` may be pre-filtered (supplier, status); the budget is not.
    """
    tx = data.transactions if transactions is None else transactions
    tx = tx[tx["period"].isin(periods)]
    approved = data.budgets.groupby("category")["amount_base"].sum()
    budget_sel = data.budgets[data.budgets["financial_period"].isin(periods)].groupby("category")["amount_base"].sum()
    actual = calc.category_expenditure(tx)
    order = categories() + sorted(set(data.transactions["category"].dropna()) - set(categories()))
    rows = []
    for c in order:
        if c not in approved.index and c not in actual.index:
            continue
        bud, bsel, act = float(approved.get(c, 0.0)), float(budget_sel.get(c, 0.0)), float(actual.get(c, 0.0))
        var = calc.budget_variance(act, bsel)
        rows.append({"category": c, "approved_budget": round(bud, 2), "budget_for_period": round(bsel, 2),
                     "actual": round(act, 2), "remaining_budget": calc.remaining_budget(bud, act),
                     "variance": var, "variance_pct": calc.variance_percentage(var, bsel),
                     "utilisation_pct": calc.budget_utilisation(act, bud), "budgeted": c in approved.index})
    return pd.DataFrame(rows)


def totals_row(table: pd.DataFrame) -> dict:
    """Total line for ``category_table_for_periods`` (ratios recomputed from totals, never summed)."""
    s = table[["approved_budget", "budget_for_period", "actual", "remaining_budget", "variance"]].sum()
    return {"category": "Total", **{k: round(float(v), 2) for k, v in s.items()},
            "variance_pct": calc.variance_percentage(float(s["variance"]), float(s["budget_for_period"])),
            "utilisation_pct": calc.budget_utilisation(float(s["actual"]), float(s["approved_budget"])),
            "budgeted": True}


def monthly_budget_vs_actual(data: ProjectData, periods: list[str], transactions: pd.DataFrame | None = None,
                             categories_filter: list[str] | None = None) -> pd.DataFrame:
    """Phased budget and actual spend per month for a window of closed months.

    variance = actual - budget (positive = overspend). ``transactions`` may be pre-filtered (e.g. supplier);
    ``categories_filter`` restricts BOTH budget and actuals to the same categories so they stay comparable.
    """
    tx = data.transactions if transactions is None else transactions
    bud = data.budgets
    if categories_filter:
        bud = bud[bud["category"].isin(categories_filter)]
        tx = tx[tx["category"].isin(categories_filter)]
    budget = bud[bud["financial_period"].isin(periods)] \
        .groupby("financial_period")["amount_base"].sum().reindex(periods, fill_value=0.0)
    actual = calc.monthly_expenditure(tx[tx["period"].isin(periods)]).reindex(periods, fill_value=0.0)
    df = pd.DataFrame({"period": periods, "budget": budget.round(2).values, "actual": actual.round(2).values})
    df["variance"] = (df["actual"] - df["budget"]).round(2)
    return df


def monthly_by_category(transactions: pd.DataFrame, top_n: int = 5,
                        other_label: str = "All other categories") -> pd.DataFrame:
    """Monthly spend for the ``top_n`` largest categories; the rest are folded into one group."""
    if transactions.empty:
        return pd.DataFrame(columns=["period", "group", "amount_base"])
    top = transactions.groupby("category")["amount_base"].sum().sort_values(ascending=False)
    keep = list(top.index[:top_n])
    df = transactions.assign(group=transactions["category"].where(transactions["category"].isin(keep), other_label))
    out = df.groupby(["period", "group"], as_index=False)["amount_base"].sum()
    out["group"] = pd.Categorical(out["group"], categories=keep + [other_label], ordered=True)
    return out.sort_values(["period", "group"]).reset_index(drop=True)


# --------------------------------------------------------------------------- attention items

def attention_items(data: ProjectData, as_of: str) -> list[dict]:
    """Structured list of issues needing review, derived ONLY from existing rules and flags.

    Nothing is inferred: each item restates a triggered status rule or transaction flag,
    with the amount affected (base currency) where one exists. Each item carries a ``kind`` so a page
    can omit items it already shows elsewhere (e.g. the Overview's category table). Sorted by severity
    ('bad' > 'warn' > 'info') then amount. No new calculations are introduced here.
    """
    rules = status_rules()
    items: list[dict] = []
    cat = category_summary(data, as_of)
    budgeted = cat[cat["budgeted"]]

    for r in budgeted[budgeted["actual_to_date"] > budgeted["approved_budget"]].itertuples():
        items.append({"kind": "category_budget_exceeded", "severity": "bad",
                      "title": f"{r.category}: approved budget already exceeded",
                      "detail": f"Spent {r.utilisation_pct:.1f}% of the full approved budget. Review whether a "
                                "budget revision is required.", "amount": r.actual_to_date - r.approved_budget})
    for r in budgeted[budgeted["forecast_variance_pct"] > rules["watchlist_category_variance_pct"]].itertuples():
        items.append({"kind": "category_forecast_overrun", "severity": "bad",
                      "title": f"{r.category}: forecast {r.forecast_variance_pct:+.1f}% over budget",
                      "detail": f"Spend to date {r.variance_pct:+.1f}% vs phased budget. Forecast at completion exceeds "
                                "the approved amount — explanation and corrective action required.",
                      "amount": r.forecast_variance})
    for r in budgeted[(budgeted["variance_pct"] > rules["watchlist_ytd_variance_pct"])
                      & ~(budgeted["forecast_variance_pct"] > rules["watchlist_category_variance_pct"])].itertuples():
        items.append({"kind": "category_ytd_overspend", "severity": "warn",
                      "title": f"{r.category}: {r.variance_pct:+.1f}% above phased budget to date",
                      "detail": "Spending is running ahead of plan; forecast remains within the category threshold.",
                      "amount": r.variance_to_date})
    # Recognised categories with spend but no budget line (unrecognised ones are covered by the flag below).
    unbudgeted = cat[~cat["budgeted"] & (cat["actual_to_date"] != 0) & cat["category"].isin(categories())]
    for r in unbudgeted.itertuples():
        items.append({"kind": "unbudgeted_category", "severity": "warn",
                      "title": f"Spend recorded against '{r.category}'",
                      "detail": "No approved budget exists for this category. Re-code the transactions in the register.",
                      "amount": r.actual_to_date})

    flagged = transaction_flags(data)
    flagged = flagged[flagged["period"] <= as_of]

    def _ids(sub: pd.DataFrame, n: int = 3) -> str:
        ids = sub["transaction_id"].tolist()
        return ", ".join(ids[:n]) + (f" +{len(ids) - n} more" if len(ids) > n else "")

    checks = [
        ("flag_duplicate_id", "bad", "Duplicate transaction IDs", "Same ID recorded more than once: {ids}."),
        ("flag_duplicate_invoice", "bad", "Duplicate invoice references",
         "Possible double payment — confirm with the supplier statement: {ids}."),
        ("flag_unusual_amount", "warn", "Unusually large transactions",
         "More than {mult:.0f}× the category median: {ids}. Confirm approval and supporting documents."),
        ("flag_uncategorised", "warn", "Uncategorised expenses", "Category missing or not recognised: {ids}."),
        ("flag_missing_values", "warn", "Missing invoice or document references",
         "Incomplete supporting information: {ids}. Request the documents from the local accountant."),
        ("flag_fx_missing", "warn", "Transactions without an FX rate", "Excluded from totals until a rate is set: {ids}."),
    ]
    for col, sev, title, detail in checks:
        sub = flagged[flagged[col]]
        if len(sub):
            items.append({"kind": f"flag:{col}", "severity": sev, "title": f"{title} ({len(sub)})",
                          "detail": detail.format(ids=_ids(sub), mult=anomaly_rules()["large_vs_category_median_multiple"]),
                          "amount": float(sub["amount_base"].sum(skipna=True))})
    for status, sev in (("Queried", "warn"), ("Pending Review", "info")):
        sub = flagged[flagged["status"] == status]
        if len(sub):
            items.append({"kind": f"status:{status}", "severity": sev, "title": f"{status}: {len(sub)} transaction(s)",
                          "detail": "Not yet verified — figures may change." if status == "Pending Review"
                          else "Queried by the analyst — resolve before month-end sign-off.",
                          "amount": float(sub["amount_base"].sum(skipna=True))})
    for w in data.warnings:
        items.append({"kind": "data_warning", "severity": "warn", "title": "Data completeness", "detail": w,
                      "amount": None})

    order = {"bad": 0, "warn": 1, "info": 2}
    return sorted(items, key=lambda i: (order[i["severity"]], -abs(i["amount"] or 0)))
