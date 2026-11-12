"""Database schema (DDL).

Design notes
------------
* Every monetary row stores its own ``currency``. Aggregation always happens in
  the base currency after explicit conversion (see ``src/data/preprocessing.py``).
* ``project_id`` is a foreign key on every financial table so additional projects
  can be added without schema changes.
* ``financial_period`` / ``forecast_period`` are 'YYYY-MM' text values.
* ``audit_log`` records every insert/update made through the application,
  including the previous and new values (JSON text).
* ``import_batches`` records each confirmed upload for traceability.
"""
from __future__ import annotations

import sqlite3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    project_id          TEXT PRIMARY KEY,
    project_name        TEXT NOT NULL,
    country             TEXT NOT NULL,
    currency            TEXT NOT NULL,              -- reporting currency of the project
    project_start_date  TEXT NOT NULL,              -- ISO date, start of monitored budget phase
    project_end_date    TEXT NOT NULL,              -- ISO date, end of monitored budget phase
    description         TEXT
);

CREATE TABLE IF NOT EXISTS budgets (
    budget_id           TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES projects(project_id),
    financial_period    TEXT NOT NULL,              -- 'YYYY-MM'
    category            TEXT NOT NULL,
    approved_amount     REAL NOT NULL CHECK (approved_amount >= 0),
    currency            TEXT NOT NULL,
    UNIQUE (project_id, financial_period, category)
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id      TEXT PRIMARY KEY,
    invoice_id          TEXT,
    project_id          TEXT NOT NULL REFERENCES projects(project_id),
    transaction_date    TEXT NOT NULL,              -- ISO date
    supplier            TEXT NOT NULL,
    description         TEXT,
    category            TEXT NOT NULL,
    amount              REAL NOT NULL,              -- in `currency`; negative = credit note
    currency            TEXT NOT NULL,
    status              TEXT NOT NULL,
    document_reference  TEXT,
    import_batch_id     TEXT REFERENCES import_batches(batch_id)
);

CREATE TABLE IF NOT EXISTS forecasts (
    forecast_id         TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES projects(project_id),
    category            TEXT NOT NULL,
    forecast_period     TEXT NOT NULL,              -- 'YYYY-MM'
    forecast_amount     REAL NOT NULL CHECK (forecast_amount >= 0),
    currency            TEXT NOT NULL DEFAULT 'EUR',
    assumption          TEXT,
    updated_at          TEXT NOT NULL,
    UNIQUE (project_id, category, forecast_period)
);

CREATE TABLE IF NOT EXISTS audit_log (
    log_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type         TEXT NOT NULL,              -- budget | transaction | forecast | project
    record_id           TEXT NOT NULL,
    action              TEXT NOT NULL,              -- insert | update | delete | seed
    previous_value      TEXT,                       -- JSON
    new_value           TEXT,                       -- JSON
    timestamp           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_batches (
    batch_id            TEXT PRIMARY KEY,
    dataset_type        TEXT NOT NULL,              -- budget | transactions | forecast
    file_name           TEXT NOT NULL,
    rows_received       INTEGER NOT NULL,
    rows_imported       INTEGER NOT NULL,
    rows_excluded       INTEGER NOT NULL,
    warnings            INTEGER NOT NULL,
    imported_at         TEXT NOT NULL,
    note                TEXT
);

CREATE INDEX IF NOT EXISTS ix_txn_project_date ON transactions(project_id, transaction_date);
CREATE INDEX IF NOT EXISTS ix_txn_invoice ON transactions(invoice_id);
CREATE INDEX IF NOT EXISTS ix_budget_project ON budgets(project_id, financial_period);
CREATE INDEX IF NOT EXISTS ix_forecast_project ON forecasts(project_id, forecast_period);
"""

# Columns per table, in canonical order (used by operations and validation).
TABLE_COLUMNS: dict[str, list[str]] = {
    "projects": ["project_id", "project_name", "country", "currency",
                 "project_start_date", "project_end_date", "description"],
    "budgets": ["budget_id", "project_id", "financial_period", "category",
                "approved_amount", "currency"],
    "transactions": ["transaction_id", "invoice_id", "project_id", "transaction_date",
                     "supplier", "description", "category", "amount", "currency",
                     "status", "document_reference"],
    "forecasts": ["forecast_id", "project_id", "category", "forecast_period",
                  "forecast_amount", "currency", "assumption", "updated_at"],
}


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes if they do not exist (idempotent)."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()
