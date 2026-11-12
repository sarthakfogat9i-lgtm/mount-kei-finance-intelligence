"""v0.3 visual layer: each remaining chart is built only from engine output and reconciles to it."""
from __future__ import annotations

import pytest

from src.finance import budget_analysis as ba
from src.finance import forecasting as fc
from src.ui import charts
from src.utils.config import scenarios


def test_only_three_chart_builders_remain():
    public = sorted(n for n in dir(charts) if callable(getattr(charts, n)) and not n.startswith("_")
                    and getattr(getattr(charts, n), "__module__", "") == charts.__name__)
    assert public == ["monthly_actual_vs_budget", "scenario_comparison", "spend_to_date"]


def test_monthly_budget_vs_actual_reconciles(project_data):
    periods = fc.elapsed_periods(project_data, "2026-10")
    m = ba.monthly_budget_vs_actual(project_data, periods)
    k = ba.headline_kpis(project_data, "2026-10")
    assert m["budget"].sum() == pytest.approx(k["budget_to_date"], abs=0.05)
    assert m["actual"].sum() == pytest.approx(k["actual_to_date"], abs=0.05)
    assert (m["variance"] == (m["actual"] - m["budget"]).round(2)).all()      # positive = overspend


def test_monthly_budget_vs_actual_category_filter_applies_to_both(project_data):
    periods = fc.elapsed_periods(project_data, "2026-10")
    cat = ba.category_table_for_periods(project_data, periods).set_index("category")
    m = ba.monthly_budget_vs_actual(project_data, periods, categories_filter=["Transport and Logistics"])
    assert m["budget"].sum() == pytest.approx(cat.loc["Transport and Logistics", "budget_for_period"], abs=0.05)
    assert m["actual"].sum() == pytest.approx(cat.loc["Transport and Logistics", "actual"], abs=0.05)


def test_spend_to_date_uses_closed_months_only(project_data):
    monthly = ba.monthly_summary(project_data, "2026-10")
    fig = charts.spend_to_date(monthly)
    budget_trace, actual_trace = fig.data[0], fig.data[1]
    assert len(budget_trace.y) == 7                                          # Apr–Oct, no forecast months
    assert budget_trace.y[-1] == pytest.approx(ba.headline_kpis(project_data, "2026-10")["budget_to_date"], abs=0.05)
    assert actual_trace.y[-1] == pytest.approx(ba.headline_kpis(project_data, "2026-10")["actual_to_date"], abs=0.05)


def test_scenario_chart_actual_identical_and_fac_matches_engine(project_data):
    scen = fc.scenario_comparison(project_data, "2026-10", scenarios())
    fig = charts.scenario_comparison(scen, 2_400_000)
    actual_bars = list(fig.data[0].x)
    assert len(set(actual_bars)) == 1                                       # actual never changes by scenario
    totals = [a + r for a, r in zip(fig.data[0].x, fig.data[1].x)]
    assert sorted(totals) == pytest.approx(sorted(scen["forecast_at_completion"]), abs=0.05)


def test_overview_attention_kinds_present(project_data):
    kinds = {i["kind"] for i in ba.attention_items(project_data, "2026-10")}
    assert "category_forecast_overrun" in kinds and "flag:flag_duplicate_invoice" in kinds
