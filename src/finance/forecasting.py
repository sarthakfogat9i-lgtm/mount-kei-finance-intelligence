"""Deterministic forecasting.

No machine learning. Every number can be traced to an input row:

    Forecast remaining (category, month m > as-of)
        = forecasts.forecast_amount            if the analyst entered a forecast for (category, m)
        = budgets.approved_amount              otherwise ("budget-as-forecast" fallback)

    Adjusted remaining = Forecast remaining x (1 + scenario % / 100) x (1 + category % / 100)

    Forecast at Completion (FAC) = Actual to date + Adjusted remaining

Actual expenditure is NEVER adjusted by a scenario — scenarios only change
money not yet spent.
"""
from __future__ import annotations

from typing import Mapping

import pandas as pd

from src.data.preprocessing import ProjectData
from src.finance import calculations as calc
from src.utils.config import base_currency


def remaining_periods(data: ProjectData, as_of: str) -> list[str]:
    """Budget months strictly after the as-of month."""
    return [p for p in data.fy_periods if p > as_of]


def elapsed_periods(data: ProjectData, as_of: str) -> list[str]:
    """Budget months up to and including the as-of month."""
    return [p for p in data.fy_periods if p <= as_of]


def forecast_remaining_detail(data: ProjectData, as_of: str, scenario_pct: float = 0.0,
                              category_pct: Mapping[str, float] | None = None) -> pd.DataFrame:
    """Month x category forecast of remaining expenditure, with its source and assumption.

    Columns: category, period, budget_amount, base_forecast, source, assumption, adjustment_pct,
    forecast_amount (adjusted).
    """
    category_pct = category_pct or {}
    future = remaining_periods(data, as_of)
    b = data.budgets[data.budgets["financial_period"].isin(future)]
    b = b.groupby(["category", "financial_period"], as_index=False)["amount_base"].sum()
    b = b.rename(columns={"financial_period": "period", "amount_base": "budget_amount"})

    f = data.forecasts[data.forecasts["forecast_period"].isin(future)]
    f = f.rename(columns={"forecast_period": "period", "amount_base": "forecast_input"})
    f = f[["category", "period", "forecast_input", "assumption"]]

    detail = b.merge(f, on=["category", "period"], how="outer")
    detail["budget_amount"] = detail["budget_amount"].fillna(0.0)
    has_fc = detail["forecast_input"].notna()
    detail["base_forecast"] = detail["forecast_input"].where(has_fc, detail["budget_amount"])
    detail["source"] = has_fc.map({True: "Analyst forecast", False: "Approved budget (no forecast entered)"})
    detail["assumption"] = detail["assumption"].where(has_fc, "No forecast entered — approved budget used.")
    detail["adjustment_pct"] = [
        round((1 + scenario_pct / 100) * (1 + category_pct.get(c, 0.0) / 100) * 100 - 100, 4)
        for c in detail["category"]
    ]
    detail["forecast_amount"] = (detail["base_forecast"] * (1 + detail["adjustment_pct"] / 100)).round(2)
    return detail.drop(columns=["forecast_input"]).sort_values(["period", "category"]).reset_index(drop=True)


def forecast_by_category(data: ProjectData, as_of: str, scenario_pct: float = 0.0,
                         category_pct: Mapping[str, float] | None = None) -> pd.DataFrame:
    """Per-category approved budget, actual to date, forecast remaining, FAC and forecast variance."""
    elapsed = elapsed_periods(data, as_of)
    approved = data.budgets.groupby("category")["amount_base"].sum()
    tx = data.transactions[data.transactions["period"].isin(elapsed)]
    actual = calc.category_expenditure(tx)
    remaining = forecast_remaining_detail(data, as_of, scenario_pct, category_pct) \
        .groupby("category")["forecast_amount"].sum()

    cats = sorted(set(approved.index) | set(actual.index) | set(remaining.index))
    rows = []
    for c in cats:
        bud = float(approved.get(c, 0.0))
        act = float(actual.get(c, 0.0))
        rem = float(remaining.get(c, 0.0))
        fac = calc.forecast_at_completion(act, rem)
        var = calc.forecast_budget_variance(fac, bud)
        rows.append({"category": c, "approved_budget": round(bud, 2), "actual_to_date": round(act, 2),
                     "forecast_remaining": round(rem, 2), "forecast_at_completion": fac,
                     "forecast_variance": var, "forecast_variance_pct": calc.variance_percentage(var, bud)})
    return pd.DataFrame(rows)


def forecast_totals(data: ProjectData, as_of: str, scenario_pct: float = 0.0,
                    category_pct: Mapping[str, float] | None = None) -> dict[str, float]:
    """Project-level FAC figures."""
    by_cat = forecast_by_category(data, as_of, scenario_pct, category_pct)
    budget = calc.total_approved_budget(data.budgets)
    actual = round(float(by_cat["actual_to_date"].sum()), 2)
    remaining = round(float(by_cat["forecast_remaining"].sum()), 2)
    fac = calc.forecast_at_completion(actual, remaining)
    var = calc.forecast_budget_variance(fac, budget)
    return {"approved_budget": budget, "actual_to_date": actual, "forecast_remaining": remaining,
            "forecast_at_completion": fac, "forecast_variance": var,
            "forecast_variance_pct": calc.variance_percentage(var, budget)}


def scenario_comparison(data: ProjectData, as_of: str, scenarios: Mapping[str, Mapping],
                        category_pct: Mapping[str, float] | None = None) -> pd.DataFrame:
    """One row per scenario (Base / Optimistic / Pessimistic) with its FAC and variance."""
    rows = []
    for name, spec in scenarios.items():
        pct = float(spec.get("adjustment_pct", 0.0))
        t = forecast_totals(data, as_of, pct, category_pct)
        rows.append({"scenario": name, "adjustment_pct": pct, "assumption": spec.get("description", ""), **t})
    return pd.DataFrame(rows)


def run_rate_forecast(data: ProjectData, as_of: str, lookback_months: int = 3) -> dict[str, float]:
    """Cross-check: remaining spend if the average of the last N months continued.

    Shown for comparison only; it ignores seasonality, so it is not used as the official forecast.
    """
    elapsed = elapsed_periods(data, as_of)
    last = elapsed[-lookback_months:]
    monthly = calc.monthly_expenditure(data.transactions[data.transactions["period"].isin(last)])
    avg = float(monthly.reindex(last, fill_value=0.0).mean()) if last else float("nan")
    n_remaining = len(remaining_periods(data, as_of))
    actual = calc.total_actual_expenditure(data.transactions, elapsed)
    remaining = round(avg * n_remaining, 2)
    fac = calc.forecast_at_completion(actual, remaining)
    budget = calc.total_approved_budget(data.budgets)
    return {"lookback_months": len(last), "average_monthly_spend": round(avg, 2),
            "remaining_months": n_remaining, "forecast_remaining": remaining, "forecast_at_completion": fac,
            "forecast_variance": calc.forecast_budget_variance(fac, budget)}


def adjusted_forecast_rows(detail: pd.DataFrame, project_id: str, note: str) -> pd.DataFrame:
    """Convert an adjusted forecast detail into rows for ``operations.upsert_forecasts``."""
    out = detail[["category", "period", "forecast_amount", "assumption", "adjustment_pct"]].copy()
    out["assumption"] = [
        f"{a} | Adjusted {p:+.1f}%: {note}" if abs(p) > 1e-9 else a
        for a, p in zip(out["assumption"], out["adjustment_pct"])
    ]
    out = out.rename(columns={"period": "forecast_period"})
    out["project_id"] = project_id
    out["currency"] = base_currency()
    return out[["project_id", "category", "forecast_period", "forecast_amount", "currency", "assumption"]]
