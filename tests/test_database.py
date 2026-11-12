"""Tests for SQLite persistence, imports and the audit trail."""
from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from src.data.preprocessing import build_project_data
from src.data.sample_data import build_valid_upload, seed_database_from_sample
from src.database import operations as ops
from src.finance import budget_analysis as ba


@pytest.fixture()
def seeded(tmp_db):
    seed_database_from_sample(tmp_db)
    return tmp_db


def _load(db):
    p = ops.get_projects(db).iloc[0].to_dict()
    pid = p["project_id"]
    return build_project_data(p, ops.get_budgets(pid, db), ops.get_transactions(pid, db), ops.get_forecasts(pid, db))


def test_seed_and_persist_across_connections(seeded, sample):
    assert not ops.is_empty(seeded)
    # a fresh connection (= application restart) sees the same data
    assert len(ops.get_transactions("MK-001", seeded)) == len(sample["transactions"])
    assert ops.get_budgets("MK-001", seeded)["approved_amount"].sum() == pytest.approx(2_400_000)


def test_db_figures_match_generated_figures(seeded, project_data):
    db_data = _load(seeded)
    a = ba.headline_kpis(db_data, "2026-10")
    b = ba.headline_kpis(project_data, "2026-10")
    for key in ("approved_budget", "actual_to_date", "forecast_at_completion"):
        assert a[key] == pytest.approx(b[key], abs=0.01)


def test_insert_transactions_is_audited_and_changes_actuals(seeded, sample):
    before = ba.headline_kpis(_load(seeded), "2026-10")["actual_to_date"]
    new = build_valid_upload(sample["transactions"])
    batch = ops.insert_transactions(new, "ok.xlsx", len(new), 0, 0, db_path=seeded)
    after = ba.headline_kpis(_load(seeded), "2026-10")["actual_to_date"]
    assert after > before
    log = ops.get_audit_log(500, seeded)
    assert (log["action"] == "insert").sum() == len(new)
    assert batch in ops.get_import_batches(seeded)["batch_id"].tolist()


def test_duplicate_transaction_id_rejected_by_database(seeded, sample):
    dup = sample["transactions"].head(1)
    with pytest.raises(sqlite3.IntegrityError):
        ops.insert_transactions(dup, "dup.csv", 1, 0, 0, db_path=seeded)
    # rollback: nothing partially written
    assert len(ops.get_transactions("MK-001", seeded)) == len(sample["transactions"])


def test_budget_revision_keeps_previous_value_in_audit(seeded):
    rev = pd.DataFrame([{"project_id": "MK-001", "financial_period": "2026-11", "category": "Administration",
                         "approved_amount": 12_345.0, "currency": "EUR"}])
    ops.upsert_budgets(rev, "rev.csv", 1, 0, 0, db_path=seeded)
    b = ops.get_budgets("MK-001", seeded)
    row = b[(b.financial_period == "2026-11") & (b.category == "Administration")]
    assert len(row) == 1 and row["approved_amount"].iloc[0] == 12_345.0
    log = ops.get_audit_log(10, seeded)
    upd = log[(log["record_type"] == "budget") & (log["action"] == "update")].iloc[0]
    assert '"approved_amount": 12345.0' in upd["new_value"]
    assert upd["previous_value"] is not None


def test_forecast_upsert_replaces_not_duplicates(seeded):
    rows = pd.DataFrame([{"project_id": "MK-001", "category": "Transport and Logistics", "forecast_period": "2026-11",
                          "forecast_amount": 20_000.0, "currency": "EUR", "assumption": "test"}])
    n_before = len(ops.get_forecasts("MK-001", seeded))
    ops.upsert_forecasts(rows, "f.csv", 1, 0, 0, db_path=seeded)
    f = ops.get_forecasts("MK-001", seeded)
    assert len(f) == n_before
    assert f[(f.category == "Transport and Logistics") & (f.forecast_period == "2026-11")]["forecast_amount"].iloc[0] == 20_000


def test_status_and_category_updates_audited(seeded):
    ops.update_transaction_status("TXN-2026-0001", "Queried", seeded)
    ops.update_transaction_category("TXN-2026-0001", "Administration", seeded)
    t = ops.get_transactions("MK-001", seeded).set_index("transaction_id").loc["TXN-2026-0001"]
    assert t["status"] == "Queried" and t["category"] == "Administration"
    assert (ops.get_audit_log(5, seeded)["record_id"] == "TXN-2026-0001").sum() == 2


def test_data_version_changes_on_write(seeded):
    v1 = ops.data_version(seeded)
    ops.update_transaction_status("TXN-2026-0002", "Queried", seeded)
    assert ops.data_version(seeded) > v1


def test_foreign_key_enforced(seeded):
    bad = pd.DataFrame([{"transaction_id": "X1", "invoice_id": "I", "project_id": "NOPE",
                         "transaction_date": "2026-10-01", "supplier": "S", "description": "d",
                         "category": "Administration", "amount": 1.0, "currency": "EUR", "status": "Verified",
                         "document_reference": "D"}])
    with pytest.raises(sqlite3.IntegrityError):
        ops.insert_transactions(bad, "x.csv", 1, 0, 0, db_path=seeded)
