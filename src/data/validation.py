"""Validation of uploaded budget, transaction and forecast files.

Principles
----------
* Nothing is silently discarded. Every problem becomes a row in ``issues`` with
  the source row number, the column, the rule broken and a plain-English fix.
* Two severities:
    ERROR   - the row cannot be imported as supplied (e.g. invalid date, unknown category).
    WARNING - the row can be imported but needs the analyst's attention
              (e.g. credit note, missing document reference, possible duplicate invoice).
* File-level problems (missing required columns, no data rows) block the whole file.
* ``clean`` holds only rows without errors, with types converted, ready to import.
  The UI requires explicit confirmation before importing, and excluded rows are
  reported and downloadable.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd

from src.utils.config import base_currency, categories, fx_rates, transaction_statuses, uncategorised_label

ERROR = "Error"
WARNING = "Warning"
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

SCHEMAS: dict[str, dict[str, list[str]]] = {
    "transactions": {
        "required": ["transaction_id", "project_id", "transaction_date", "supplier", "category",
                     "amount", "currency", "status"],
        "optional": ["invoice_id", "description", "document_reference"],
    },
    "budget": {
        "required": ["project_id", "financial_period", "category", "approved_amount", "currency"],
        "optional": ["budget_id"],
    },
    "forecast": {
        "required": ["project_id", "category", "forecast_period", "forecast_amount"],
        "optional": ["currency", "assumption"],
    },
}
DATASET_LABELS = {"transactions": "Actual expenditure transactions", "budget": "Budget",
                  "forecast": "Forecast assumptions"}


@dataclass
class ValidationResult:
    dataset_type: str
    rows_received: int
    issues: pd.DataFrame
    clean: pd.DataFrame
    excluded: pd.DataFrame
    file_errors: list[str] = field(default_factory=list)

    @property
    def n_errors(self) -> int:
        return int((self.issues["severity"] == ERROR).sum()) if not self.issues.empty else 0

    @property
    def n_warnings(self) -> int:
        return int((self.issues["severity"] == WARNING).sum()) if not self.issues.empty else 0

    @property
    def is_blocked(self) -> bool:
        """True when the file cannot be imported at all."""
        return bool(self.file_errors) or self.clean.empty

    @property
    def fully_valid(self) -> bool:
        return not self.file_errors and self.n_errors == 0

    def summary(self) -> dict[str, int | str]:
        return {"dataset": DATASET_LABELS[self.dataset_type], "rows_received": self.rows_received,
                "rows_ready": len(self.clean), "rows_with_errors": len(self.excluded),
                "errors": self.n_errors, "warnings": self.n_warnings}


class _Collector:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, source_row, column: str, severity: str, rule: str, message: str, value=None) -> None:
        self.rows.append({"source_row": source_row, "column": column, "severity": severity, "rule": rule,
                          "message": message, "value": None if value is None or pd.isna(value) else str(value)})

    def frame(self) -> pd.DataFrame:
        cols = ["source_row", "column", "severity", "rule", "message", "value"]
        return pd.DataFrame(self.rows, columns=cols)


# --------------------------------------------------------------------------- shared helpers

def check_columns(df: pd.DataFrame, dataset_type: str) -> list[str]:
    """Return file-level errors for missing required columns."""
    missing = [c for c in SCHEMAS[dataset_type]["required"] if c not in df.columns]
    if missing:
        return [f"Missing required column(s): {', '.join(missing)}. "
                f"Download the {DATASET_LABELS[dataset_type].lower()} template to see the expected layout."]
    return []


def _blank(v) -> bool:
    return v is None or (not isinstance(v, str) and pd.isna(v)) or (isinstance(v, str) and v.strip() == "")


def parse_amount(value) -> float | None:
    """Parse '1,234.50', '€1 234', '(500)' -> float. Returns None when not a number."""
    if _blank(value):
        return None
    s = str(value).strip().replace(",", "").replace(" ", "").replace("€", "").replace("$", "")
    if re.fullmatch(r"\(\d+(\.\d+)?\)", s):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(value) -> dt.date | None:
    """Accept ISO dates ('2026-10-31', '2026-10-31 00:00:00'). Anything else is invalid
    to avoid day/month ambiguity (03/04/2026 could be 3 April or 4 March)."""
    if _blank(value):
        return None
    s = str(value).strip()[:10]
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return None


def _common_checks(df: pd.DataFrame, c: _Collector, project_ids: Iterable[str], currency_col: str | None,
                   default_currency: bool = False) -> None:
    rates = fx_rates()
    pids = set(project_ids)
    for r in df.itertuples(index=False):
        row = r._asdict()
        sr = row["source_row"]
        if _blank(row.get("project_id")):
            c.add(sr, "project_id", ERROR, "required", "Project ID is missing.")
        elif pids and row["project_id"] not in pids:
            c.add(sr, "project_id", ERROR, "unknown project",
                  f"Project '{row['project_id']}' does not exist. Known: {', '.join(sorted(pids))}.",
                  row["project_id"])
        if currency_col:
            cur = row.get(currency_col)
            if _blank(cur):
                if default_currency:
                    c.add(sr, currency_col, WARNING, "default applied",
                          f"Currency missing — {base_currency()} assumed.")
                else:
                    c.add(sr, currency_col, ERROR, "required", "Currency is missing.")
            elif str(cur).upper() not in rates:
                c.add(sr, currency_col, ERROR, "unknown currency",
                      f"No conversion rate is configured for '{cur}'. Use one of: {', '.join(rates)} "
                      "or add a documented rate in config/settings.yaml.", cur)


def _finalise(dataset_type: str, df: pd.DataFrame, c: _Collector, file_errors: list[str],
              clean_builder) -> ValidationResult:
    issues = c.frame()
    error_rows = set(issues.loc[issues["severity"] == ERROR, "source_row"]) if not issues.empty else set()
    ok = df[~df["source_row"].isin(error_rows)]
    excluded = df[df["source_row"].isin(error_rows)]
    clean = clean_builder(ok) if not file_errors and not ok.empty else ok.iloc[0:0]
    return ValidationResult(dataset_type, len(df), issues.sort_values(["source_row", "severity"]),
                            clean, excluded, file_errors)


# --------------------------------------------------------------------------- transactions

def validate_transactions(df: pd.DataFrame, existing_ids: Iterable[str] = (),
                          existing_invoices: Iterable[str] = (), project_ids: Iterable[str] = (),
                          budget_periods: Iterable[str] = (), today: dt.date | None = None) -> ValidationResult:
    """Validate an actual-expenditure upload."""
    c = _Collector()
    file_errors = check_columns(df, "transactions")
    if df.empty:
        file_errors.append("The file contains no data rows.")
    if file_errors:
        return ValidationResult("transactions", len(df), c.frame(), df.iloc[0:0], df, file_errors)
    df = df.copy()
    for col in SCHEMAS["transactions"]["optional"]:
        if col not in df.columns:
            df[col] = pd.NA
            c.add(None, col, WARNING, "optional column missing", f"Column '{col}' not supplied; left blank.")

    existing_ids, existing_invoices = set(map(str, existing_ids)), set(map(str, existing_invoices))
    periods = set(budget_periods)
    today = today or dt.date.today()
    cats, statuses = set(categories()), set(transaction_statuses())
    dup_ids = df["transaction_id"].dropna()[df["transaction_id"].dropna().duplicated(keep=False)]
    inv = df["invoice_id"].dropna()
    dup_inv = set(inv[inv.duplicated(keep=False)])

    _common_checks(df, c, project_ids, "currency")
    for r in df.itertuples(index=False):
        row = r._asdict()
        sr = row["source_row"]
        tid = row["transaction_id"]
        if _blank(tid):
            c.add(sr, "transaction_id", ERROR, "required", "Transaction ID is missing.")
        else:
            if tid in set(dup_ids):
                c.add(sr, "transaction_id", ERROR, "duplicate in file",
                      f"Transaction ID '{tid}' appears more than once in this file. Give each line a unique ID.", tid)
            if tid in existing_ids:
                c.add(sr, "transaction_id", ERROR, "already imported",
                      f"Transaction ID '{tid}' already exists in the database. Remove the line or use a new ID.", tid)
        invoice = row.get("invoice_id")
        if _blank(invoice):
            c.add(sr, "invoice_id", WARNING, "missing invoice", "Invoice reference is blank — confirm the "
                  "supporting invoice with the local accountant.")
        else:
            if invoice in dup_inv:
                c.add(sr, "invoice_id", WARNING, "duplicate invoice in file",
                      f"Invoice '{invoice}' appears on more than one line. Acceptable for split lines; "
                      "otherwise possible double entry.", invoice)
            if invoice in existing_invoices:
                c.add(sr, "invoice_id", WARNING, "invoice already recorded",
                      f"Invoice '{invoice}' was already recorded in a previous upload — possible duplicate payment.",
                      invoice)
        d = parse_date(row.get("transaction_date"))
        if d is None:
            c.add(sr, "transaction_date", ERROR, "invalid date",
                  "Date missing or not a valid ISO date (YYYY-MM-DD).", row.get("transaction_date"))
        else:
            if periods and d.strftime("%Y-%m") not in periods:
                c.add(sr, "transaction_date", WARNING, "outside budget phase",
                      f"{d.isoformat()} is outside the approved budget phase; it will be stored but excluded "
                      "from budget comparisons.", d)
            if d > today:
                c.add(sr, "transaction_date", WARNING, "future date", f"{d.isoformat()} is in the future.", d)
        amt = parse_amount(row.get("amount"))
        if amt is None:
            c.add(sr, "amount", ERROR, "invalid amount", "Amount is missing or not a number.", row.get("amount"))
        elif amt == 0:
            c.add(sr, "amount", ERROR, "zero amount", "Amount is zero — remove the line or enter the correct value.")
        elif amt < 0:
            c.add(sr, "amount", WARNING, "negative amount",
                  "Negative amount — treated as a credit note/refund. Confirm this is intended.", amt)
        if _blank(row.get("supplier")):
            c.add(sr, "supplier", ERROR, "required", "Supplier is missing.")
        if _blank(row.get("description")):
            c.add(sr, "description", WARNING, "missing description", "Description is blank.")
        cat = row.get("category")
        if _blank(cat):
            c.add(sr, "category", WARNING, "uncategorised",
                  f"Category is blank — will be imported as '{uncategorised_label()}' and flagged for review.")
        elif cat not in cats and cat != uncategorised_label():
            c.add(sr, "category", ERROR, "unrecognised category",
                  f"'{cat}' is not a recognised category. Use one of: {', '.join(categories())}.", cat)
        st = row.get("status")
        if _blank(st):
            c.add(sr, "status", WARNING, "default applied", "Status is blank — 'Pending Review' assumed.")
        elif st not in statuses:
            c.add(sr, "status", ERROR, "unrecognised status",
                  f"'{st}' is not a recognised status. Use one of: {', '.join(transaction_statuses())}.", st)
        if _blank(row.get("document_reference")):
            c.add(sr, "document_reference", WARNING, "missing document",
                  "No supporting document reference — request the invoice/receipt.")

    def build(ok: pd.DataFrame) -> pd.DataFrame:
        out = ok.copy()
        out["transaction_date"] = out["transaction_date"].map(lambda v: parse_date(v).isoformat())
        out["amount"] = out["amount"].map(parse_amount).astype(float)
        out["currency"] = out["currency"].str.upper()
        out["category"] = out["category"].where(~out["category"].map(_blank), uncategorised_label())
        out["status"] = out["status"].where(~out["status"].map(_blank), "Pending Review")
        return out

    return _finalise("transactions", df, c, file_errors, build)


# --------------------------------------------------------------------------- budget

def validate_budget(df: pd.DataFrame, project_ids: Iterable[str] = ()) -> ValidationResult:
    """Validate a budget upload (monthly approved amounts by category)."""
    c = _Collector()
    file_errors = check_columns(df, "budget")
    if df.empty:
        file_errors.append("The file contains no data rows.")
    if file_errors:
        return ValidationResult("budget", len(df), c.frame(), df.iloc[0:0], df, file_errors)
    _common_checks(df, c, project_ids, "currency")
    key = df[["project_id", "financial_period", "category"]].astype(str).agg("|".join, axis=1)
    dup_keys = set(key[key.duplicated(keep=False)])
    for r, k in zip(df.itertuples(index=False), key):
        row = r._asdict()
        sr = row["source_row"]
        if _blank(row["financial_period"]) or not PERIOD_RE.match(str(row["financial_period"])):
            c.add(sr, "financial_period", ERROR, "invalid period", "Financial period must be 'YYYY-MM'.",
                  row["financial_period"])
        if _blank(row["category"]):
            c.add(sr, "category", ERROR, "required", "Budget lines must have a category.")
        elif row["category"] not in categories():
            c.add(sr, "category", ERROR, "unrecognised category",
                  f"'{row['category']}' is not a recognised category. To add a category see ARCHITECTURE.md §10.",
                  row["category"])
        amt = parse_amount(row["approved_amount"])
        if amt is None:
            c.add(sr, "approved_amount", ERROR, "invalid amount", "Approved amount is missing or not a number.",
                  row["approved_amount"])
        elif amt < 0:
            c.add(sr, "approved_amount", ERROR, "negative budget", "Approved budget cannot be negative.", amt)
        if k in dup_keys:
            c.add(sr, "financial_period", ERROR, "duplicate line",
                  "The same project/period/category appears more than once in this file.", k)

    def build(ok: pd.DataFrame) -> pd.DataFrame:
        out = ok.copy()
        out["approved_amount"] = out["approved_amount"].map(parse_amount).astype(float)
        out["currency"] = out["currency"].str.upper()
        return out

    return _finalise("budget", df, c, file_errors, build)


# --------------------------------------------------------------------------- forecast

def validate_forecast(df: pd.DataFrame, project_ids: Iterable[str] = (), budget_periods: Iterable[str] = (),
                      closed_through: str | None = None) -> ValidationResult:
    """Validate a forecast-assumptions upload."""
    c = _Collector()
    file_errors = check_columns(df, "forecast")
    if df.empty:
        file_errors.append("The file contains no data rows.")
    if file_errors:
        return ValidationResult("forecast", len(df), c.frame(), df.iloc[0:0], df, file_errors)
    df = df.copy()
    for col in ("currency", "assumption"):
        if col not in df.columns:
            df[col] = pd.NA
    _common_checks(df, c, project_ids, "currency", default_currency=True)
    periods = set(budget_periods)
    key = df[["project_id", "category", "forecast_period"]].astype(str).agg("|".join, axis=1)
    dup_keys = set(key[key.duplicated(keep=False)])
    for r, k in zip(df.itertuples(index=False), key):
        row = r._asdict()
        sr = row["source_row"]
        p = row["forecast_period"]
        if _blank(p) or not PERIOD_RE.match(str(p)):
            c.add(sr, "forecast_period", ERROR, "invalid period", "Forecast period must be 'YYYY-MM'.", p)
        else:
            if periods and p not in periods:
                c.add(sr, "forecast_period", WARNING, "outside budget phase",
                      f"{p} is outside the approved budget phase and will not affect the forecast at completion.", p)
            if closed_through and p <= closed_through:
                c.add(sr, "forecast_period", WARNING, "closed month",
                      f"{p} already has actuals (closed through {closed_through}); actuals take precedence "
                      "over forecasts for closed months.", p)
        if _blank(row["category"]) or row["category"] not in categories():
            c.add(sr, "category", ERROR, "unrecognised category",
                  f"'{row['category']}' is not a recognised category.", row["category"])
        amt = parse_amount(row["forecast_amount"])
        if amt is None:
            c.add(sr, "forecast_amount", ERROR, "invalid amount", "Forecast amount is missing or not a number.",
                  row["forecast_amount"])
        elif amt < 0:
            c.add(sr, "forecast_amount", ERROR, "negative forecast", "Forecast expenditure cannot be negative.", amt)
        if _blank(row.get("assumption")):
            c.add(sr, "assumption", WARNING, "missing assumption",
                  "No assumption given — every forecast should state its basis.")
        if k in dup_keys:
            c.add(sr, "forecast_period", ERROR, "duplicate line",
                  "The same project/category/period appears more than once in this file.", k)

    def build(ok: pd.DataFrame) -> pd.DataFrame:
        out = ok.copy()
        out["forecast_amount"] = out["forecast_amount"].map(parse_amount).astype(float)
        out["currency"] = out["currency"].where(~out["currency"].map(_blank), base_currency()).str.upper()
        return out

    return _finalise("forecast", df, c, file_errors, build)
