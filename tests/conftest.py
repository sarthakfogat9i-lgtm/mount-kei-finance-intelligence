"""Shared pytest fixtures."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.preprocessing import build_project_data  # noqa: E402
from src.data.sample_data import generate_all  # noqa: E402


@pytest.fixture(scope="session")
def sample() -> dict[str, pd.DataFrame]:
    return generate_all(write_files=False)


@pytest.fixture(scope="session")
def project_data(sample):
    return build_project_data(sample["projects"].iloc[0].to_dict(), sample["budgets"], sample["transactions"],
                              sample["forecasts"])


@pytest.fixture()
def tmp_db(tmp_path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture()
def known_example():
    """The specification's worked example: budget 2.0m, actual 0.9m, remaining forecast 1.3m."""
    project = {"project_id": "T-1", "project_name": "Test", "country": "X", "currency": "EUR",
               "project_start_date": "2026-01-01", "project_end_date": "2026-04-30", "description": ""}
    budgets = pd.DataFrame([
        {"budget_id": f"B{i}", "project_id": "T-1", "financial_period": p, "category": "Land Preparation",
         "approved_amount": 500_000.0, "currency": "EUR"}
        for i, p in enumerate(["2026-01", "2026-02", "2026-03", "2026-04"])])
    transactions = pd.DataFrame([
        {"transaction_id": "T1", "invoice_id": "I1", "project_id": "T-1", "transaction_date": "2026-01-15",
         "supplier": "S", "description": "d", "category": "Land Preparation", "amount": 400_000.0,
         "currency": "EUR", "status": "Verified", "document_reference": "D1"},
        {"transaction_id": "T2", "invoice_id": "I2", "project_id": "T-1", "transaction_date": "2026-02-15",
         "supplier": "S", "description": "d", "category": "Land Preparation", "amount": 500_000.0,
         "currency": "EUR", "status": "Verified", "document_reference": "D2"},
    ])
    forecasts = pd.DataFrame([
        {"forecast_id": "F1", "project_id": "T-1", "category": "Land Preparation", "forecast_period": "2026-03",
         "forecast_amount": 650_000.0, "currency": "EUR", "assumption": "a", "updated_at": "2026-02-28"},
        {"forecast_id": "F2", "project_id": "T-1", "category": "Land Preparation", "forecast_period": "2026-04",
         "forecast_amount": 650_000.0, "currency": "EUR", "assumption": "a", "updated_at": "2026-02-28"},
    ])
    return build_project_data(project, budgets, transactions, forecasts)
