"""Core financial calculations.

These are small, pure functions with no Streamlit dependency so they can be unit
tested and reused by the dashboard, the reporting module and any future API.

Sign convention (used everywhere in the application)
-----------------------------------------------------
    Actual Variance   = Actual Expenditure    - Approved Budget
    Forecast Variance = Forecast at Completion - Approved Budget

    positive variance -> OVERSPEND
    negative variance -> UNDERSPEND

All amounts passed to these functions must already be in ONE currency
(the base currency, see ``src/data/preprocessing.py``).
"""
from __future__ import annotations

import math
from typing import Iterable

import pandas as pd

NAN = float("nan")


def is_missing(x: float | None) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def safe_divide(numerator: float | None, denominator: float | None) -> float:
    """Division that returns NaN (not an error, not zero) for missing values or a zero denominator.

    NaN is deliberately used so that the UI shows 'n/a' rather than a misleading 0%.
    """
    if is_missing(numerator) or is_missing(denominator) or denominator == 0:
        return NAN
    return float(numerator) / float(denominator)


# --------------------------------------------------------------------------- totals

def total_approved_budget(budgets: pd.DataFrame, periods: Iterable[str] | None = None,
                          amount_col: str = "amount_base") -> float:
    """Sum of approved budget lines (optionally restricted to a set of periods)."""
    if budgets is None or budgets.empty:
        return 0.0
    df = budgets if periods is None else budgets[budgets["financial_period"].isin(list(periods))]
    return round(float(df[amount_col].sum(skipna=True)), 2)


def total_actual_expenditure(transactions: pd.DataFrame, periods: Iterable[str] | None = None,
                             amount_col: str = "amount_base") -> float:
    """Sum of recorded transactions (credit notes reduce the total)."""
    if transactions is None or transactions.empty:
        return 0.0
    df = transactions if periods is None else transactions[transactions["period"].isin(list(periods))]
    return round(float(df[amount_col].sum(skipna=True)), 2)


def remaining_budget(approved_budget: float, actual_expenditure: float) -> float:
    """Approved budget not yet spent. Negative when the budget is already exceeded."""
    if is_missing(approved_budget) or is_missing(actual_expenditure):
        return NAN
    return round(approved_budget - actual_expenditure, 2)


def budget_variance(actual_expenditure: float, approved_budget: float) -> float:
    """Actual - Budget. Positive = overspend."""
    if is_missing(actual_expenditure) or is_missing(approved_budget):
        return NAN
    return round(actual_expenditure - approved_budget, 2)


def variance_percentage(variance: float, approved_budget: float) -> float:
    """Variance as % of the budget it is measured against. NaN when the budget is zero."""
    r = safe_divide(variance, approved_budget)
    return NAN if is_missing(r) else round(r * 100, 4)


def budget_utilisation(actual_expenditure: float, approved_budget: float) -> float:
    """Share of the approved budget already spent, in %."""
    r = safe_divide(actual_expenditure, approved_budget)
    return NAN if is_missing(r) else round(r * 100, 4)


# --------------------------------------------------------------------------- breakdowns

def category_expenditure(transactions: pd.DataFrame, amount_col: str = "amount_base") -> pd.Series:
    """Actual expenditure by category."""
    if transactions is None or transactions.empty:
        return pd.Series(dtype=float)
    return transactions.groupby("category")[amount_col].sum().round(2)


def monthly_expenditure(transactions: pd.DataFrame, amount_col: str = "amount_base") -> pd.Series:
    """Actual expenditure by 'YYYY-MM' period."""
    if transactions is None or transactions.empty:
        return pd.Series(dtype=float)
    return transactions.groupby("period")[amount_col].sum().sort_index().round(2)


# --------------------------------------------------------------------------- forecast

def forecast_at_completion(actual_to_date: float, forecast_remaining: float) -> float:
    """FAC = Actual Expenditure to Date + Forecast Remaining Expenditure."""
    if is_missing(actual_to_date) or is_missing(forecast_remaining):
        return NAN
    return round(actual_to_date + forecast_remaining, 2)


def forecast_budget_variance(fac: float, approved_budget: float) -> float:
    """FAC - Approved Budget. Positive = forecast overspend."""
    return budget_variance(fac, approved_budget)


def forecast_variance_percentage(fac: float, approved_budget: float) -> float:
    """(FAC - Budget) / Budget x 100."""
    return variance_percentage(forecast_budget_variance(fac, approved_budget), approved_budget)
