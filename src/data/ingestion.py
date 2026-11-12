"""File ingestion: read an uploaded Excel/CSV file into a raw DataFrame.

Ingestion does NOT judge the data — it only reads it faithfully (everything as
text) and normalises column names. Judgement happens in ``validation.py``.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import BinaryIO

import pandas as pd

SUPPORTED_EXTENSIONS = (".csv", ".xlsx", ".xls")

# Common header variants accountants use -> canonical column name.
COLUMN_ALIASES: dict[str, str] = {
    "txn_id": "transaction_id", "transaction_no": "transaction_id", "id": "transaction_id",
    "invoice": "invoice_id", "invoice_no": "invoice_id", "invoice_number": "invoice_id",
    "invoice_reference": "invoice_id",
    "date": "transaction_date", "posting_date": "transaction_date",
    "vendor": "supplier", "supplier_name": "supplier",
    "expense_category": "category", "cost_category": "category",
    "value": "amount", "amount_local": "amount",
    "ccy": "currency", "currency_code": "currency",
    "verification_status": "status",
    "document": "document_reference", "doc_ref": "document_reference", "document_ref": "document_reference",
    "period": "financial_period", "month": "financial_period",
    "budget": "approved_amount", "approved_budget": "approved_amount",
    "forecast": "forecast_amount", "forecast_month": "forecast_period",
    "assumptions": "assumption", "project": "project_id",
}


class IngestionError(Exception):
    """Raised when a file cannot be read at all (wrong type, corrupt, empty)."""


def normalise_column(name: str) -> str:
    """'Invoice No.' -> 'invoice_no' -> alias lookup."""
    key = re.sub(r"[^0-9a-z]+", "_", str(name).strip().lower()).strip("_")
    return COLUMN_ALIASES.get(key, key)


def read_upload(file: BinaryIO | bytes | str | Path, file_name: str | None = None,
                sheet_name: str | int = 0) -> pd.DataFrame:
    """Read CSV or Excel as text (dtype=str) so that validation sees exactly what was supplied.

    Leading/trailing whitespace is stripped; fully empty rows are dropped (they carry no data)
    and empty strings become NaN.
    """
    if isinstance(file, (str, Path)):
        file_name = file_name or str(file)
        raw = Path(file).read_bytes()
    elif isinstance(file, bytes):
        raw = file
    else:
        raw = file.read()
        file_name = file_name or getattr(file, "name", "upload")
    if not raw:
        raise IngestionError("The file is empty.")
    ext = Path(file_name or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise IngestionError(f"Unsupported file type '{ext or 'unknown'}'. Upload a .csv or .xlsx file.")
    try:
        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
        else:
            df = pd.read_excel(io.BytesIO(raw), dtype=str, sheet_name=sheet_name, keep_default_na=False)
    except Exception as exc:  # noqa: BLE001 — surface any parser error to the user
        raise IngestionError(f"The file could not be read: {exc}") from exc
    if df.empty and len(df.columns) == 0:
        raise IngestionError("The file contains no columns.")
    df.columns = [normalise_column(c) for c in df.columns]
    df = df.apply(lambda s: s.str.strip() if s.dtype == object else s)
    df = df.replace({"": pd.NA, "nan": pd.NA, "NaN": pd.NA, "None": pd.NA})
    # Excel/CSV row number as the accountant sees it (header is row 1), kept before
    # blank rows are dropped so error messages point at the right line.
    data_cols = list(df.columns)
    df.insert(0, "source_row", df.index + 2)
    df = df.dropna(how="all", subset=data_cols).reset_index(drop=True)
    return df
