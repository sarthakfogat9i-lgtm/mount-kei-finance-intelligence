"""Preprocessing: currency conversion and derived columns.

Rule: amounts in different currencies are NEVER added together directly.
Every monetary table gets an ``amount_base`` column (base currency, EUR by default)
computed with the documented rates in ``config/settings.yaml``:

    amount_base = amount / rate[currency]     (rate = units of currency per 1 EUR)

Rows whose currency has no configured rate get ``amount_base = NaN`` and
``fx_missing = True``; downstream calculations surface them as warnings rather
than silently treating them as zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.utils.config import base_currency, fx_rates


def convert_to_base(amounts: pd.Series, currencies: pd.Series,
                    rates: dict[str, float] | None = None) -> pd.Series:
    """Convert amounts to the base currency. Unknown currency -> NaN."""
    rates = rates or fx_rates()
    rate = currencies.map(rates).astype(float)
    return pd.to_numeric(amounts, errors="coerce") / rate


def prepare_transactions(df: pd.DataFrame, rates: dict[str, float] | None = None) -> pd.DataFrame:
    """Add period, base-currency amount and FX flag to a transactions frame."""
    out = df.copy()
    out["transaction_date"] = pd.to_datetime(out["transaction_date"], errors="coerce")
    out["period"] = out["transaction_date"].dt.strftime("%Y-%m")
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce")
    out["amount_base"] = convert_to_base(out["amount"], out["currency"], rates).round(2)
    out["fx_missing"] = out["amount_base"].isna() & out["amount"].notna()
    return out


def prepare_budgets(df: pd.DataFrame, rates: dict[str, float] | None = None) -> pd.DataFrame:
    out = df.copy()
    out["approved_amount"] = pd.to_numeric(out["approved_amount"], errors="coerce")
    out["amount_base"] = convert_to_base(out["approved_amount"], out["currency"], rates).round(2)
    return out


def prepare_forecasts(df: pd.DataFrame, rates: dict[str, float] | None = None) -> pd.DataFrame:
    out = df.copy()
    if "currency" not in out.columns:
        out["currency"] = base_currency()
    out["forecast_amount"] = pd.to_numeric(out["forecast_amount"], errors="coerce")
    out["amount_base"] = convert_to_base(out["forecast_amount"], out["currency"], rates).round(2)
    return out


@dataclass
class ProjectData:
    """Everything the dashboard needs for one project, already converted to base currency."""

    project: dict
    budgets: pd.DataFrame
    transactions: pd.DataFrame
    forecasts: pd.DataFrame
    base_currency: str = "EUR"
    warnings: list[str] = field(default_factory=list)

    @property
    def fy_periods(self) -> list[str]:
        """All months covered by the approved budget, sorted."""
        return sorted(self.budgets["financial_period"].unique().tolist())

    @property
    def actual_periods(self) -> list[str]:
        return sorted(self.transactions["period"].dropna().unique().tolist())

    @property
    def latest_actual_period(self) -> str | None:
        in_scope = [p for p in self.actual_periods if p in self.fy_periods]
        return in_scope[-1] if in_scope else (self.actual_periods[-1] if self.actual_periods else None)


def build_project_data(project: dict, budgets: pd.DataFrame, transactions: pd.DataFrame,
                       forecasts: pd.DataFrame, rates: dict[str, float] | None = None) -> ProjectData:
    """Assemble a ``ProjectData`` and collect data-completeness warnings."""
    b = prepare_budgets(budgets, rates)
    t = prepare_transactions(transactions, rates)
    f = prepare_forecasts(forecasts, rates)
    warnings: list[str] = []
    if b.empty:
        warnings.append("No approved budget loaded — budget ratios cannot be calculated.")
    if b["amount_base"].isna().any():
        warnings.append(f"{int(b['amount_base'].isna().sum())} budget line(s) have a currency without an FX rate "
                        "and are excluded from totals.")
    if t["fx_missing"].any():
        warnings.append(f"{int(t['fx_missing'].sum())} transaction(s) have a currency without an FX rate "
                        "and are excluded from totals.")
    if t["transaction_date"].isna().any():
        warnings.append(f"{int(t['transaction_date'].isna().sum())} transaction(s) have no valid date.")
    if not b.empty and not t.empty:
        outside = ~t["period"].isin(b["financial_period"].unique()) & t["period"].notna()
        if outside.any():
            warnings.append(f"{int(outside.sum())} transaction(s) fall outside the budget phase "
                            "and are excluded from budget comparisons.")
    return ProjectData(project=project, budgets=b, transactions=t, forecasts=f,
                       base_currency=base_currency(), warnings=warnings)

