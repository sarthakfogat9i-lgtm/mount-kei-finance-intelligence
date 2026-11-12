"""Tests for the monthly report and its Excel/PDF exports."""
from __future__ import annotations

import io

import pandas as pd

from src.reporting.exports import to_excel, to_pdf
from src.reporting.monthly_report import build_monthly_report


def test_report_contents(project_data):
    r = build_monthly_report(project_data, "2026-10", "Analyst note")
    assert r.status.status == "Watchlist"
    assert r.reconciliation["passed"].all()
    assert any("Transport and Logistics" in a for a in r.attention_items)
    assert not r.deviations.empty
    # observations restate figures only — they must not contain causal language
    assert not any(w in " ".join(r.observations).lower() for w in ("because", "due to", "caused"))


def test_excel_export_has_all_sheets(project_data):
    r = build_monthly_report(project_data, "2026-10")
    xl = pd.ExcelFile(io.BytesIO(to_excel(r)))
    assert {"Summary", "Categories", "Monthly", "Deviations", "Data quality", "Flagged transactions",
            "Status rules", "Reconciliation"} <= set(xl.sheet_names)
    cats = xl.parse("Categories")
    assert abs(cats["Actual to date"].sum() - r.kpis["actual_to_date"]) < 0.05


def test_pdf_export_is_valid_pdf(project_data):
    pdf = to_pdf(build_monthly_report(project_data, "2026-06"))
    assert pdf[:4] == b"%PDF" and len(pdf) > 3000
