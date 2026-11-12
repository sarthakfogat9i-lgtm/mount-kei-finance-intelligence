"""Database read/write operations.

All writes go through functions in this module so that every change is recorded
in ``audit_log``. The UI never writes SQL directly.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from src.database.connection import db_session, get_connection
from src.database.models import TABLE_COLUMNS, init_db


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _json(row: dict[str, Any] | None) -> str | None:
    if row is None:
        return None
    return json.dumps({k: (None if pd.isna(v) else v) if not isinstance(v, (list, dict)) else v
                       for k, v in row.items()}, default=str)


def _audit(conn: sqlite3.Connection, record_type: str, record_id: str, action: str,
           previous: dict | None, new: dict | None) -> None:
    conn.execute(
        "INSERT INTO audit_log (record_type, record_id, action, previous_value, new_value, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (record_type, record_id, action, _json(previous), _json(new), _now()),
    )


# --------------------------------------------------------------------------- setup

def initialise_database(db_path: str | Path | None = None) -> None:
    """Create the schema if needed."""
    conn = get_connection(db_path)
    try:
        init_db(conn)
    finally:
        conn.close()


def is_empty(db_path: str | Path | None = None) -> bool:
    """True when no project has been loaded yet."""
    initialise_database(db_path)
    conn = get_connection(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
    finally:
        conn.close()


def seed_database(projects: pd.DataFrame, budgets: pd.DataFrame, transactions: pd.DataFrame,
                  forecasts: pd.DataFrame, db_path: str | Path | None = None) -> None:
    """Load a complete dataset into an EMPTY database (used for the sample data).

    One 'seed' audit entry is written per table rather than one per row.
    """
    initialise_database(db_path)
    with db_session(db_path) as conn:
        for table, df in (("projects", projects), ("budgets", budgets),
                          ("transactions", transactions), ("forecasts", forecasts)):
            cols = TABLE_COLUMNS[table]
            data = df[cols].astype(object).where(df[cols].notna(), None)
            placeholders = ",".join("?" * len(cols))
            conn.executemany(
                f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
                data.itertuples(index=False, name=None),
            )
            _audit(conn, table, "*", "seed", None, {"rows": len(df), "source": "sample_data"})


# --------------------------------------------------------------------------- reads

def _read(sql: str, params: tuple = (), db_path: str | Path | None = None) -> pd.DataFrame:
    initialise_database(db_path)
    conn = get_connection(db_path)
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def get_projects(db_path: str | Path | None = None) -> pd.DataFrame:
    return _read("SELECT * FROM projects ORDER BY project_id", db_path=db_path)


def get_budgets(project_id: str, db_path: str | Path | None = None) -> pd.DataFrame:
    return _read("SELECT * FROM budgets WHERE project_id = ? ORDER BY financial_period, category",
                 (project_id,), db_path)


def get_transactions(project_id: str, db_path: str | Path | None = None) -> pd.DataFrame:
    return _read("SELECT * FROM transactions WHERE project_id = ? ORDER BY transaction_date, transaction_id",
                 (project_id,), db_path)


def get_forecasts(project_id: str, db_path: str | Path | None = None) -> pd.DataFrame:
    return _read("SELECT * FROM forecasts WHERE project_id = ? ORDER BY forecast_period, category",
                 (project_id,), db_path)


def get_audit_log(limit: int = 200, db_path: str | Path | None = None) -> pd.DataFrame:
    return _read("SELECT * FROM audit_log ORDER BY log_id DESC LIMIT ?", (limit,), db_path)


def get_import_batches(db_path: str | Path | None = None) -> pd.DataFrame:
    return _read("SELECT * FROM import_batches ORDER BY imported_at DESC", db_path=db_path)


def existing_transaction_ids(project_id: str | None = None,
                             db_path: str | Path | None = None) -> set[str]:
    sql = "SELECT transaction_id FROM transactions"
    params: tuple = ()
    if project_id:
        sql += " WHERE project_id = ?"
        params = (project_id,)
    return set(_read(sql, params, db_path)["transaction_id"].astype(str))


def existing_invoice_ids(project_id: str | None = None,
                         db_path: str | Path | None = None) -> set[str]:
    sql = "SELECT invoice_id FROM transactions WHERE invoice_id IS NOT NULL"
    params: tuple = ()
    if project_id:
        sql += " AND project_id = ?"
        params = (project_id,)
    return set(_read(sql, params, db_path)["invoice_id"].astype(str))


def data_version(db_path: str | Path | None = None) -> int:
    """Monotonic number that changes whenever data changes (used as a cache key)."""
    df = _read("SELECT COALESCE(MAX(log_id), 0) AS v FROM audit_log", db_path=db_path)
    return int(df["v"].iloc[0])


# --------------------------------------------------------------------------- writes

def _record_batch(conn: sqlite3.Connection, dataset_type: str, file_name: str, received: int,
                  imported: int, excluded: int, warnings: int, note: str | None) -> str:
    batch_id = f"IMP-{dt.datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
    conn.execute(
        "INSERT INTO import_batches VALUES (?,?,?,?,?,?,?,?,?)",
        (batch_id, dataset_type, file_name, received, imported, excluded, warnings, _now(), note),
    )
    return batch_id


def insert_transactions(df: pd.DataFrame, file_name: str, rows_received: int, rows_excluded: int,
                        warnings: int, note: str | None = None,
                        db_path: str | Path | None = None) -> str:
    """Insert NEW transactions. Raises if any transaction_id already exists (no silent overwrite)."""
    cols = TABLE_COLUMNS["transactions"]
    with db_session(db_path) as conn:
        batch_id = _record_batch(conn, "transactions", file_name, rows_received, len(df),
                                 rows_excluded, warnings, note)
        for row in df[cols].to_dict("records"):
            clean = {k: (None if pd.isna(v) else v) for k, v in row.items()}
            conn.execute(
                f"INSERT INTO transactions ({','.join(cols)}, import_batch_id) "
                f"VALUES ({','.join('?' * len(cols))}, ?)",
                [clean[c] for c in cols] + [batch_id],
            )
            _audit(conn, "transaction", clean["transaction_id"], "insert", None, clean)
    return batch_id


def upsert_budgets(df: pd.DataFrame, file_name: str, rows_received: int, rows_excluded: int,
                   warnings: int, note: str | None = None,
                   db_path: str | Path | None = None) -> str:
    """Insert or update budget lines keyed on (project_id, financial_period, category).

    Updated lines keep their budget_id; the previous approved amount is written
    to the audit log so budget revisions are traceable.
    """
    with db_session(db_path) as conn:
        batch_id = _record_batch(conn, "budget", file_name, rows_received, len(df),
                                 rows_excluded, warnings, note)
        for row in df.to_dict("records"):
            existing = conn.execute(
                "SELECT * FROM budgets WHERE project_id=? AND financial_period=? AND category=?",
                (row["project_id"], row["financial_period"], row["category"]),
            ).fetchone()
            if existing:
                prev = dict(existing)
                conn.execute("UPDATE budgets SET approved_amount=?, currency=? WHERE budget_id=?",
                             (float(row["approved_amount"]), row["currency"], prev["budget_id"]))
                new = {**prev, "approved_amount": float(row["approved_amount"]), "currency": row["currency"]}
                _audit(conn, "budget", prev["budget_id"], "update", prev, new)
            else:
                bid = row.get("budget_id") or f"BUD-{row['project_id']}-{row['financial_period']}-{uuid.uuid4().hex[:6]}"
                if pd.isna(bid):
                    bid = f"BUD-{row['project_id']}-{row['financial_period']}-{uuid.uuid4().hex[:6]}"
                new = {"budget_id": bid, "project_id": row["project_id"],
                       "financial_period": row["financial_period"], "category": row["category"],
                       "approved_amount": float(row["approved_amount"]), "currency": row["currency"]}
                conn.execute("INSERT INTO budgets VALUES (?,?,?,?,?,?)", tuple(new.values()))
                _audit(conn, "budget", bid, "insert", None, new)
    return batch_id


def upsert_forecasts(df: pd.DataFrame, file_name: str, rows_received: int, rows_excluded: int,
                     warnings: int, note: str | None = None,
                     db_path: str | Path | None = None) -> str:
    """Insert or update forecast lines keyed on (project_id, category, forecast_period)."""
    with db_session(db_path) as conn:
        batch_id = _record_batch(conn, "forecast", file_name, rows_received, len(df),
                                 rows_excluded, warnings, note)
        ts = _now()
        for row in df.to_dict("records"):
            assumption = None if pd.isna(row.get("assumption")) else row.get("assumption")
            currency = row.get("currency") or "EUR"
            existing = conn.execute(
                "SELECT * FROM forecasts WHERE project_id=? AND category=? AND forecast_period=?",
                (row["project_id"], row["category"], row["forecast_period"]),
            ).fetchone()
            if existing:
                prev = dict(existing)
                conn.execute(
                    "UPDATE forecasts SET forecast_amount=?, currency=?, assumption=?, updated_at=? "
                    "WHERE forecast_id=?",
                    (float(row["forecast_amount"]), currency, assumption, ts, prev["forecast_id"]),
                )
                new = {**prev, "forecast_amount": float(row["forecast_amount"]), "currency": currency,
                       "assumption": assumption, "updated_at": ts}
                _audit(conn, "forecast", prev["forecast_id"], "update", prev, new)
            else:
                fid = f"FC-{row['project_id']}-{row['forecast_period']}-{uuid.uuid4().hex[:6]}"
                new = {"forecast_id": fid, "project_id": row["project_id"], "category": row["category"],
                       "forecast_period": row["forecast_period"],
                       "forecast_amount": float(row["forecast_amount"]), "currency": currency,
                       "assumption": assumption, "updated_at": ts}
                conn.execute("INSERT INTO forecasts VALUES (?,?,?,?,?,?,?,?)", tuple(new.values()))
                _audit(conn, "forecast", fid, "insert", None, new)
    return batch_id


def update_transaction_status(transaction_id: str, new_status: str,
                              db_path: str | Path | None = None) -> None:
    """Change the verification status of one transaction (audited)."""
    with db_session(db_path) as conn:
        row = conn.execute("SELECT * FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone()
        if row is None:
            raise KeyError(transaction_id)
        prev = dict(row)
        conn.execute("UPDATE transactions SET status=? WHERE transaction_id=?", (new_status, transaction_id))
        _audit(conn, "transaction", transaction_id, "update", {"status": prev["status"]}, {"status": new_status})


def update_transaction_category(transaction_id: str, new_category: str,
                                db_path: str | Path | None = None) -> None:
    """Re-code the category of one transaction (audited). Amounts are never edited in the UI."""
    with db_session(db_path) as conn:
        row = conn.execute("SELECT * FROM transactions WHERE transaction_id=?", (transaction_id,)).fetchone()
        if row is None:
            raise KeyError(transaction_id)
        conn.execute("UPDATE transactions SET category=? WHERE transaction_id=?", (new_category, transaction_id))
        _audit(conn, "transaction", transaction_id, "update", {"category": row["category"]},
               {"category": new_category})


def reset_database(db_path: str | Path | None = None) -> None:
    """Delete the database file (used by 'reset to sample data')."""
    from src.utils.config import database_path

    path = Path(db_path) if db_path else database_path()
    if path.exists():
        path.unlink()


def last_updated(db_path: str | Path | None = None) -> str | None:
    """Timestamp of the most recent change recorded in the audit log (seed, import or edit)."""
    df = _read("SELECT MAX(timestamp) AS ts FROM audit_log", db_path=db_path)
    return None if df.empty else df["ts"].iloc[0]
