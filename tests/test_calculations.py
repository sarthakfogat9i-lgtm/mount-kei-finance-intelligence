"""Tests for financial calculations, forecasting, status rules and reconciliation."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from src.data.preprocessing import convert_to_base
from src.data.sample_data import TOTAL_APPROVED_BUDGET
from src.finance import budget_analysis as ba
from src.finance import calculations as calc
from src.finance import forecasting as fc


# ------------------------------------------------------------------ the specification's known example

def test_known_example_pure_functions():
    budget, actual, remaining = 2_000_000, 900_000, 1_300_000
    fac = calc.forecast_at_completion(actual, remaining)
    assert fac == 2_200_000
    assert calc.forecast_budget_variance(fac, budget) == 200_000          # positive = overspend
    assert calc.forecast_variance_percentage(fac, budget) == pytest.approx(10.0)
    assert calc.remaining_budget(budget, actual) == 1_100_000
    assert calc.budget_utilisation(actual, budget) == pytest.approx(45.0)
    assert calc.budget_variance(actual, budget) == -1_100_000              # negative = underspend


def test_known_example_end_to_end(known_example):
    t = fc.forecast_totals(known_example, as_of="2026-02")
    assert t["approved_budget"] == 2_000_000
    assert t["actual_to_date"] == 900_000
    assert t["forecast_remaining"] == 1_300_000
    assert t["forecast_at_completion"] == 2_200_000
    assert t["forecast_variance"] == 200_000
    assert t["forecast_variance_pct"] == pytest.approx(10.0)
    k = ba.headline_kpis(known_example, "2026-02")
    assert k["remaining_budget"] == 1_100_000
    status = ba.determine_financial_status(k, ba.category_summary(known_example, "2026-02"))
    assert status.status == "Potential Overspend"   # 10% > 5% threshold


# ------------------------------------------------------------------ edge cases

def test_division_by_zero_returns_nan_not_zero():
    assert math.isnan(calc.safe_divide(10, 0))
    assert math.isnan(calc.variance_percentage(100, 0))
    assert math.isnan(calc.budget_utilisation(100, 0))


def test_missing_values_propagate_as_nan():
    assert math.isnan(calc.forecast_at_completion(float("nan"), 100))
    assert math.isnan(calc.budget_variance(None, 100))
    assert math.isnan(calc.remaining_budget(100, None))


def test_empty_frames_total_zero():
    assert calc.total_actual_expenditure(pd.DataFrame()) == 0.0
    assert calc.total_approved_budget(pd.DataFrame()) == 0.0


def test_currency_conversion_never_mixes_currencies():
    amounts = pd.Series([4_100.0, 10.0, 5.0])
    cur = pd.Series(["UGX", "EUR", "XYZ"])
    out = convert_to_base(amounts, cur, {"EUR": 1.0, "UGX": 4100.0})
    assert out.iloc[0] == pytest.approx(1.0)
    assert out.iloc[1] == pytest.approx(10.0)
    assert math.isnan(out.iloc[2])        # unknown currency is NOT treated as EUR


def test_credit_notes_reduce_actuals():
    tx = pd.DataFrame({"period": ["2026-04", "2026-04"], "category": ["A", "A"], "amount_base": [100.0, -40.0]})
    assert calc.total_actual_expenditure(tx) == 60.0


# ------------------------------------------------------------------ forecasting rules

def test_scenarios_only_adjust_remaining_spend(project_data):
    base = fc.forecast_totals(project_data, "2026-10", 0.0)
    pess = fc.forecast_totals(project_data, "2026-10", 12.5)
    assert pess["actual_to_date"] == base["actual_to_date"]
    assert pess["forecast_remaining"] == pytest.approx(base["forecast_remaining"] * 1.125, abs=0.05)


def test_budget_used_when_no_forecast_entered(known_example):
    detail = fc.forecast_remaining_detail(known_example, "2026-01")   # Feb has no forecast row
    feb = detail[detail["period"] == "2026-02"].iloc[0]
    assert feb["base_forecast"] == 500_000
    assert feb["source"].startswith("Approved budget")


def test_fac_equals_actual_at_last_month(project_data):
    last = project_data.fy_periods[-1]
    t = fc.forecast_totals(project_data, last)
    assert t["forecast_remaining"] == 0
    assert t["forecast_at_completion"] == t["actual_to_date"]


def test_category_adjustment(project_data):
    base = fc.forecast_by_category(project_data, "2026-10").set_index("category")
    adj = fc.forecast_by_category(project_data, "2026-10", 0.0, {"Transport and Logistics": 10}).set_index("category")
    cat = "Transport and Logistics"
    assert adj.loc[cat, "forecast_remaining"] == pytest.approx(base.loc[cat, "forecast_remaining"] * 1.1, abs=0.05)
    assert adj.loc["Administration", "forecast_remaining"] == base.loc["Administration", "forecast_remaining"]


# ------------------------------------------------------------------ reconciliation of the sample dataset

def test_category_budgets_reconcile_to_total(sample):
    assert sample["budgets"]["approved_amount"].sum() == pytest.approx(TOTAL_APPROVED_BUDGET, abs=0.01)


def test_monthly_budgets_reconcile_to_annual(sample):
    b = sample["budgets"]
    by_cat_month = b.groupby("category")["approved_amount"].sum()
    by_month = b.groupby("financial_period")["approved_amount"].sum()
    assert by_cat_month.sum() == pytest.approx(by_month.sum(), abs=0.01)
    assert len(by_month) == 12


def test_all_reconciliation_checks_pass(project_data):
    for as_of in project_data.fy_periods:
        recon = ba.reconciliation_checks(project_data, as_of)
        assert recon["passed"].all(), recon


def test_monthly_summary_cumulative_matches_totals(project_data):
    m = ba.monthly_summary(project_data, "2026-10")
    k = ba.headline_kpis(project_data, "2026-10")
    assert m["cumulative_budget"].iloc[-1] == pytest.approx(k["approved_budget"], abs=0.01)
    assert m["cumulative_outturn"].iloc[-1] == pytest.approx(k["forecast_at_completion"], abs=0.05)
    assert m.loc[m["closed"], "actual"].sum() == pytest.approx(k["actual_to_date"], abs=0.05)


def test_sample_dataset_size_and_labels(sample):
    assert len(sample["transactions"]) >= 100
    assert sample["transactions"]["supplier"].nunique() >= 8
    assert sample["transactions"]["currency"].nunique() >= 2
    assert sample["transactions"]["supplier"].str.contains("synthetic").all()


# ------------------------------------------------------------------ status & flags

def test_status_within_budget_when_no_rule_triggers(known_example):
    k = ba.headline_kpis(known_example, "2026-02")
    k.update(forecast_variance_pct=-1.0, variance_to_date_pct=0.0, actual_to_date=0.0)
    cat = pd.DataFrame({"category": ["Land Preparation"], "budgeted": [True], "forecast_variance_pct": [-1.0],
                        "actual_to_date": [0.0]})
    assert ba.determine_financial_status(k, cat).status == "Within Budget"


def test_sample_status_is_watchlist(project_data):
    k = ba.headline_kpis(project_data, "2026-10")
    s = ba.determine_financial_status(k, ba.category_summary(project_data, "2026-10"))
    assert s.status == "Watchlist"
    assert any("Transport and Logistics" in r for r in s.reasons)


def test_planted_data_quality_issues_are_flagged(project_data):
    f = ba.transaction_flags(project_data)
    assert f["flag_duplicate_invoice"].sum() == 2
    assert f["flag_uncategorised"].sum() == 1
    assert f["flag_credit_note"].sum() == 1
    assert f["flag_missing_values"].sum() >= 2
    assert f.loc[f["amount_base"] == 24_500, "flag_unusual_amount"].all()


def test_attention_items_only_from_triggered_rules(project_data):
    items = ba.attention_items(project_data, "2026-10")
    titles = " ".join(i["title"] for i in items)
    assert "Transport and Logistics" in titles and "Duplicate invoice" in titles
    order = {"bad": 0, "warn": 1, "info": 2}
    assert [order[i["severity"]] for i in items] == sorted(order[i["severity"]] for i in items)
    # A clean dataset (known example) produces no transaction-flag items.
    assert ba.attention_items(project_data, "2026-04") is not None


def test_attention_items_empty_for_clean_project(known_example):
    titles = [i["title"] for i in ba.attention_items(known_example, "2026-02")]
    assert not any("Duplicate" in t or "Uncategorised" in t or "Missing" in t for t in titles)
