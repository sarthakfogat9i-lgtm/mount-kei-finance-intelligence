"""Tests for file ingestion and validation."""
from __future__ import annotations

import io

import pandas as pd
import pytest

from src.data import validation as val
from src.data.ingestion import IngestionError, read_upload
from src.data.sample_data import build_problem_upload, build_valid_upload
from src.utils.config import sample_dir

PROJECTS = ["MK-001"]


def _csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


def _xlsx_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def _rules(result, severity=None) -> set[str]:
    i = result.issues
    if severity:
        i = i[i["severity"] == severity]
    return set(i["rule"])


@pytest.fixture()
def problem_result(sample, project_data):
    raw = read_upload(_csv_bytes(build_problem_upload(sample["transactions"])), "errors.csv")
    return val.validate_transactions(raw, set(sample["transactions"]["transaction_id"]),
                                     set(sample["transactions"]["invoice_id"]), PROJECTS, project_data.fy_periods)


# ------------------------------------------------------------------ ingestion

def test_read_excel_and_csv_identically(sample):
    df = build_valid_upload(sample["transactions"])
    a = read_upload(_csv_bytes(df), "x.csv")
    b = read_upload(_xlsx_bytes(df), "x.xlsx")
    assert list(a.columns) == list(b.columns)
    assert len(a) == len(b) == len(df)


def test_unsupported_and_empty_files_rejected():
    with pytest.raises(IngestionError):
        read_upload(b"hello", "notes.txt")
    with pytest.raises(IngestionError):
        read_upload(b"", "empty.csv")


def test_header_aliases_normalised():
    raw = read_upload(b"Txn ID,Invoice No,Date,Vendor\nA,B,2026-10-01,S\n", "x.csv")
    assert {"transaction_id", "invoice_id", "transaction_date", "supplier"} <= set(raw.columns)


def test_source_row_numbers_survive_blank_rows():
    raw = read_upload(b"transaction_id,amount\nA,1\n,\nB,2\n", "x.csv")
    assert raw["source_row"].tolist() == [2, 4]


# ------------------------------------------------------------------ transactions

def test_valid_upload_passes(sample, project_data):
    raw = read_upload(_xlsx_bytes(build_valid_upload(sample["transactions"])), "ok.xlsx")
    r = val.validate_transactions(raw, set(sample["transactions"]["transaction_id"]),
                                  set(sample["transactions"]["invoice_id"]), PROJECTS, project_data.fy_periods)
    assert r.fully_valid
    assert len(r.clean) == 5
    assert r.clean["amount"].dtype == float


def test_problem_file_detects_every_error(problem_result):
    errors = _rules(problem_result, val.ERROR)
    assert {"duplicate in file", "already imported", "invalid date", "invalid amount", "zero amount",
            "unrecognised category", "required", "unknown currency", "unrecognised status"} <= errors


def test_problem_file_detects_warnings(problem_result):
    warnings = _rules(problem_result, val.WARNING)
    assert {"invoice already recorded", "negative amount", "uncategorised", "missing document",
            "outside budget phase", "missing invoice"} <= warnings


def test_no_rows_silently_discarded(problem_result):
    r = problem_result
    assert len(r.clean) + len(r.excluded) == r.rows_received
    # every excluded row has at least one error explaining why
    err_rows = set(r.issues.loc[r.issues["severity"] == val.ERROR, "source_row"])
    assert set(r.excluded["source_row"]) == err_rows


def test_both_duplicate_id_rows_excluded(problem_result):
    dup = problem_result.excluded[problem_result.excluded["transaction_id"] == "TXN-2026-E002"]
    assert len(dup) == 2


def test_blank_category_imported_as_uncategorised(problem_result):
    row = problem_result.clean[problem_result.clean["transaction_id"] == "TXN-2026-E014"]
    assert row["category"].iloc[0] == "Uncategorised"


def test_missing_required_column_blocks_file():
    raw = read_upload(b"transaction_id,amount\nA,1\n", "x.csv")
    r = val.validate_transactions(raw, project_ids=PROJECTS)
    assert r.is_blocked and r.file_errors
    assert "Missing required column" in r.file_errors[0]


@pytest.mark.parametrize("value,expected", [("1,234.50", 1234.5), ("(500)", -500.0), ("€2 000", 2000.0),
                                            ("abc", None), ("", None)])
def test_parse_amount(value, expected):
    assert val.parse_amount(value) == expected


def test_ambiguous_dates_rejected():
    assert val.parse_date("03/04/2026") is None
    assert val.parse_date("2026-04-03").isoformat() == "2026-04-03"


# ------------------------------------------------------------------ budget & forecast

def test_budget_validation():
    df = pd.DataFrame([
        {"project_id": "MK-001", "financial_period": "2026-04", "category": "Administration", "approved_amount": "100", "currency": "EUR"},
        {"project_id": "MK-001", "financial_period": "2026-4", "category": "Administration", "approved_amount": "100", "currency": "EUR"},
        {"project_id": "MK-001", "financial_period": "2026-05", "category": "Catering", "approved_amount": "100", "currency": "EUR"},
        {"project_id": "MK-001", "financial_period": "2026-06", "category": "Administration", "approved_amount": "-5", "currency": "EUR"},
        {"project_id": "ZZ", "financial_period": "2026-07", "category": "Administration", "approved_amount": "5", "currency": "EUR"},
    ])
    r = val.validate_budget(read_upload(_csv_bytes(df), "b.csv"), PROJECTS)
    assert len(r.clean) == 1
    assert {"invalid period", "unrecognised category", "negative budget", "unknown project"} <= _rules(r, val.ERROR)


def test_forecast_validation(project_data):
    path = sample_dir() / "upload_example_forecast_revision.csv"
    if not path.exists():
        pytest.skip("sample files not generated")
    r = val.validate_forecast(read_upload(path), PROJECTS, project_data.fy_periods, "2026-10")
    assert r.fully_valid and len(r.clean) == 5
    bad = pd.DataFrame([{"project_id": "MK-001", "category": "Administration", "forecast_period": "2026-09",
                         "forecast_amount": "10", "currency": "", "assumption": ""}])
    r2 = val.validate_forecast(read_upload(_csv_bytes(bad), "f.csv"), PROJECTS, project_data.fy_periods, "2026-10")
    assert {"closed month", "missing assumption", "default applied"} <= _rules(r2, val.WARNING)
