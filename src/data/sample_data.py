"""Synthetic (ILLUSTRATIVE) dataset generator for Mount Kei.

Run:
    python -m src.data.sample_data            # writes CSV/XLSX + templates
    python -m src.data.sample_data --reset-db # also rebuilds the SQLite database

IMPORTANT
---------
Every number produced here is fictional. It is NOT Hummingbirds financial
information, NOT derived from Hummingbirds accounts, and suppliers are invented.
The dataset only resembles what a project financial analyst might receive in a
monthly reporting cycle.

Model of the illustrative scenario
----------------------------------
* Monitored scope: a 12-month implementation budget, FY2026/27
  (April 2026 - March 2027). Approved budget EUR 2,400,000.
* Actuals: April - October 2026 (7 closed months) in a transaction register,
  partly in UGX (local suppliers) and partly in EUR.
* Forecasts: November 2026 - March 2027 by category, each with a written assumption.
* Some deliberate data-quality issues are planted (documented in
  docs/FINANCIAL_LOGIC.md §8) so the register and report have something to flag.

The generator is deterministic (fixed random seed) so the dataset can be
reproduced exactly and the reconciliation tests are stable.
"""
from __future__ import annotations

import argparse
import datetime as dt

import numpy as np
import pandas as pd

from src.utils.config import (categories, default_project_id, fx_rates, sample_dir,
                              templates_dir, uncategorised_label)

SEED = 20260411
PROJECT_ID = default_project_id()
FY_MONTHS = [f"{y}-{m:02d}" for y, m in
             [(2026, m) for m in range(4, 13)] + [(2027, m) for m in range(1, 4)]]
ACTUAL_MONTHS = FY_MONTHS[:7]        # Apr - Oct 2026
FORECAST_MONTHS = FY_MONTHS[7:]      # Nov 2026 - Mar 2027
TOTAL_APPROVED_BUDGET = 2_400_000.0

# Annual approved budget per category (EUR). Sums to TOTAL_APPROVED_BUDGET.
ANNUAL_BUDGET: dict[str, float] = {
    "Seedling Procurement": 260_000,
    "Nursery Operations": 210_000,
    "Land Preparation": 330_000,
    "Plantation and Restoration": 390_000,
    "Personnel and Labour": 520_000,
    "Transport and Logistics": 150_000,
    "Equipment and Machinery": 180_000,
    "Community Development": 120_000,
    "Monitoring and Verification": 95_000,
    "Administration": 110_000,
    "Other Project Costs": 35_000,
}

# Monthly phasing weights Apr..Mar. Reflect an illustrative seasonal pattern:
# seedling purchase and land preparation ahead of / early in the rains,
# planting through the rainy season, monitoring and verification later in the year.
PHASING: dict[str, list[int]] = {
    "Seedling Procurement":        [14, 14, 12, 10, 8, 6, 4, 4, 6, 8, 8, 6],
    "Nursery Operations":          [10, 10, 9, 8, 8, 7, 7, 7, 8, 9, 9, 8],
    "Land Preparation":            [14, 13, 11, 8, 6, 5, 4, 5, 8, 9, 9, 8],
    "Plantation and Restoration":  [8, 12, 14, 13, 12, 10, 8, 5, 4, 4, 5, 5],
    "Personnel and Labour":        [8, 9, 9, 9, 9, 8, 8, 8, 8, 8, 8, 8],
    "Transport and Logistics":     [9, 10, 10, 9, 9, 8, 8, 7, 7, 8, 8, 7],
    "Equipment and Machinery":     [20, 10, 8, 6, 6, 6, 6, 6, 8, 8, 8, 8],
    "Community Development":       [6, 6, 8, 8, 10, 10, 10, 10, 8, 8, 8, 8],
    "Monitoring and Verification": [5, 5, 5, 6, 6, 8, 10, 10, 10, 10, 12, 13],
    "Administration":              [8, 8, 8, 8, 8, 8, 9, 9, 8, 8, 9, 9],
    "Other Project Costs":         [8, 8, 8, 8, 8, 8, 9, 9, 8, 8, 9, 9],
}

# Illustrative spending behaviour vs phased budget, Apr - Oct.
ACTUAL_FACTOR: dict[str, float] = {
    "Seedling Procurement": 0.97, "Nursery Operations": 1.00, "Land Preparation": 1.03,
    "Plantation and Restoration": 0.95, "Personnel and Labour": 1.06,
    "Transport and Logistics": 1.22, "Equipment and Machinery": 0.98,
    "Community Development": 0.85, "Monitoring and Verification": 0.72,
    "Administration": 1.02, "Other Project Costs": 0.90,
}

# Base-case forecast factor vs remaining phased budget, Nov - Mar, with assumption text.
FORECAST_FACTOR: dict[str, tuple[float, str]] = {
    "Seedling Procurement": (1.00, "Remaining seedling orders as per approved phasing."),
    "Nursery Operations": (1.00, "Nursery running costs in line with approved phasing."),
    "Land Preparation": (1.03, "Labour day-rates observed Apr-Oct ~3% above budget assumed to persist."),
    "Plantation and Restoration": (1.00, "Dry-season maintenance programme per approved plan."),
    "Personnel and Labour": (1.05, "Casual labour headcount ~5% above plan expected to continue to March."),
    "Transport and Logistics": (1.15, "Fuel cost ~15% above budget assumption expected to persist (observed Apr-Oct)."),
    "Equipment and Machinery": (1.00, "No further unplanned equipment replacement assumed."),
    "Community Development": (1.00, "Community programme continues per plan; Apr-Oct shortfall not caught up this year."),
    "Monitoring and Verification": (0.95, "Field survey contract agreed ~5% below budget."),
    "Administration": (1.00, "Office and overhead costs per approved phasing."),
    "Other Project Costs": (1.00, "Contingency items per approved phasing."),
}

# Fictional suppliers: (name, currency, categories they serve)
SUPPLIERS: list[tuple[str, str, list[str]]] = [
    ("Kei Highlands Nurseries Ltd (synthetic)", "UGX", ["Seedling Procurement", "Nursery Operations"]),
    ("West Nile Seed & Seedling Co. (synthetic)", "UGX", ["Seedling Procurement"]),
    ("Koboko Agro Inputs (synthetic)", "UGX", ["Nursery Operations", "Plantation and Restoration"]),
    ("Field Crew Payroll — Site Office (synthetic)", "UGX", ["Personnel and Labour", "Land Preparation",
                                                             "Plantation and Restoration"]),
    ("Arua Haulage Services (synthetic)", "UGX", ["Transport and Logistics"]),
    ("Northern Fuel Depot (synthetic)", "UGX", ["Transport and Logistics", "Equipment and Machinery"]),
    ("Nile Basin Logistics Ltd (synthetic)", "EUR", ["Transport and Logistics"]),
    ("East Africa Plant Hire (synthetic)", "EUR", ["Equipment and Machinery", "Land Preparation"]),
    ("Yumbe Hardware Supplies (synthetic)", "UGX", ["Equipment and Machinery", "Nursery Operations",
                                                    "Other Project Costs"]),
    ("Community Liaison Programme Fund (synthetic)", "UGX", ["Community Development"]),
    ("GreenRoots Survey & Mapping (synthetic)", "EUR", ["Monitoring and Verification"]),
    ("Terra Carbon Advisory (synthetic)", "EUR", ["Monitoring and Verification"]),
    ("Riverline Field Lodge (synthetic)", "UGX", ["Administration", "Personnel and Labour"]),
    ("Kampala Office Services (synthetic)", "EUR", ["Administration"]),
    ("Contract Planting Team A (synthetic)", "UGX", ["Plantation and Restoration", "Land Preparation"]),
]

DESCRIPTIONS: dict[str, list[str]] = {
    "Seedling Procurement": ["Procurement of indigenous tree seedlings", "Teak seedlings — plantation block order",
                             "Native species seedlings for assisted natural regeneration",
                             "Seedling top-up order for replanting"],
    "Nursery Operations": ["Nursery materials — potting bags and substrate", "Nursery irrigation consumables",
                           "Nursery shade netting replacement", "Nursery attendants' monthly allowance"],
    "Land Preparation": ["Labour for land preparation — clearing and pitting", "Firebreak construction",
                         "Ripping and site preparation (hired tractor)", "Boundary marking and pegging"],
    "Plantation and Restoration": ["Planting labour — rainy season campaign", "Fertiliser and planting inputs",
                                   "Weeding and maintenance of planted blocks", "Enrichment planting in degraded areas"],
    "Personnel and Labour": ["Field crew wages", "Casual labour — seasonal peak", "Site supervisor salaries",
                             "Field staff overtime and allowances"],
    "Transport and Logistics": ["Transportation of seedlings to planting sites", "Vehicle fuel — field operations",
                                "Truck hire for materials", "Vehicle servicing and tyres"],
    "Equipment and Machinery": ["Plantation equipment — hand tools", "Brush cutters and spares",
                                "Water pump maintenance", "Equipment hire — water bowser"],
    "Community Development": ["Community sensitisation meetings", "Intercropping inputs for farmer groups",
                              "Farmer training session — sustainable agriculture", "Community liaison officer stipends"],
    "Monitoring and Verification": ["Monitoring activities — survival counts", "Biomass plot measurement",
                                    "Remote-sensing imagery and mapping", "Carbon project documentation support"],
    "Administration": ["Field accommodation", "Office rent and utilities", "Communications and internet",
                       "Bank charges and professional fees"],
    "Other Project Costs": ["Safety equipment and first aid", "Permits and local fees", "Miscellaneous site consumables"],
}


def _phase(annual: float, weights: list[int]) -> list[float]:
    """Split an annual amount across months; last month absorbs rounding so totals reconcile exactly."""
    total_w = sum(weights)
    months = [round(annual * w / total_w, 0) for w in weights[:-1]]
    months.append(round(annual - sum(months), 2))
    return months


def build_projects() -> pd.DataFrame:
    return pd.DataFrame([{
        "project_id": PROJECT_ID,
        "project_name": "Mount Kei Reforestation",
        "country": "Uganda",
        "currency": "EUR",
        "project_start_date": "2026-04-01",
        "project_end_date": "2027-03-31",
        "description": ("ILLUSTRATIVE FY2026/27 implementation budget for the Mount Kei Reforestation project "
                        "(Mount Kei Central Forest Reserve, West Nile, Uganda). Dates bound the monitored "
                        "budget phase only, not the project lifetime. All financial figures are synthetic."),
    }])


def build_budgets() -> pd.DataFrame:
    assert abs(sum(ANNUAL_BUDGET.values()) - TOTAL_APPROVED_BUDGET) < 0.01
    rows = []
    for cat in categories():
        for period, amt in zip(FY_MONTHS, _phase(ANNUAL_BUDGET[cat], PHASING[cat])):
            rows.append({"budget_id": f"BUD-{period}-{categories().index(cat) + 1:02d}",
                         "project_id": PROJECT_ID, "financial_period": period, "category": cat,
                         "approved_amount": amt, "currency": "EUR"})
    return pd.DataFrame(rows)


def _suppliers_for(cat: str) -> list[tuple[str, str]]:
    return [(n, c) for n, c, cats in SUPPLIERS if cat in cats]


def build_transactions(budgets: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    rates = fx_rates()
    rows: list[dict] = []
    for period in ACTUAL_MONTHS:
        year, month = map(int, period.split("-"))
        days_in_month = (dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)).day
        for cat in categories():
            budget_m = float(budgets.loc[(budgets.financial_period == period) & (budgets.category == cat),
                                         "approved_amount"].iloc[0])
            target = budget_m * ACTUAL_FACTOR[cat] * rng.uniform(0.92, 1.08)
            n = int(rng.integers(2, 5)) if target > 3000 else 1
            weights = rng.dirichlet(np.ones(n) * 2.0)
            supp = _suppliers_for(cat)
            for w in weights:
                amount_eur = round(target * w, 2)
                desc = str(rng.choice(DESCRIPTIONS[cat]))
                name, cur = supp[int(rng.integers(0, len(supp)))]
                amount = round(amount_eur * rates[cur], -3) if cur == "UGX" else amount_eur
                day = int(rng.integers(1, days_in_month + 1))
                rows.append({"transaction_date": dt.date(year, month, day).isoformat(), "supplier": name,
                             "description": desc, "category": cat, "amount": float(amount), "currency": cur})
            # Planted unusual item: one unplanned emergency equipment replacement in August.
            if cat == "Equipment and Machinery" and period == "2026-08":
                rows.append({"transaction_date": "2026-08-19", "supplier": "East Africa Plant Hire (synthetic)",
                             "description": "Emergency replacement of borehole pump and site generator (unplanned)",
                             "category": cat, "amount": 24_500.00, "currency": "EUR"})

    df = pd.DataFrame(rows).sort_values(["transaction_date", "category"]).reset_index(drop=True)
    df.insert(0, "transaction_id", [f"TXN-2026-{i + 1:04d}" for i in range(len(df))])
    df.insert(1, "invoice_id", [f"INV-{1000 + i * 7 + int(rng.integers(0, 6))}" for i in range(len(df))])
    df.insert(2, "project_id", PROJECT_ID)
    df["document_reference"] = [f"SYN-DOC-{i + 1:05d}" for i in range(len(df))]

    # Verification status: recent months are still under review.
    def _status(d: str) -> str:
        if d >= "2026-10-01":
            return "Pending Review" if rng.random() < 0.55 else "Verified"
        if d >= "2026-09-01":
            return "Pending Review" if rng.random() < 0.15 else "Verified"
        return "Verified"
    df["status"] = df["transaction_date"].map(_status)
    for idx in rng.choice(df.index[: len(df) - 20], size=3, replace=False):
        df.loc[idx, "status"] = "Queried"

    # ---- Planted data-quality issues (documented in FINANCIAL_LOGIC.md §8) ----
    n = len(df)
    # 1. Possible duplicate payment: same supplier, invoice and amount booked twice.
    src = df[(df.category == "Transport and Logistics") & (df.transaction_date.str.startswith("2026-09"))].iloc[0]
    dup = src.copy()
    dup["transaction_id"] = f"TXN-2026-{n + 1:04d}"
    dup["transaction_date"] = (dt.date.fromisoformat(src.transaction_date) + dt.timedelta(days=3)).isoformat()
    dup["document_reference"] = f"SYN-DOC-{n + 1:05d}"
    dup["status"] = "Pending Review"
    # 2. Uncategorised expense (category left blank by the local accountant).
    uncategorised = {"transaction_id": f"TXN-2026-{n + 2:04d}", "invoice_id": "INV-RCPT-0417",
                     "project_id": PROJECT_ID, "transaction_date": "2026-10-14",
                     "supplier": "Yumbe Hardware Supplies (synthetic)",
                     "description": "Miscellaneous field purchases — receipt bundle", "category": uncategorised_label(),
                     "amount": 7_585_000.0, "currency": "UGX", "status": "Pending Review",
                     "document_reference": f"SYN-DOC-{n + 2:05d}"}
    # 3. Credit note (negative amount): refund for seedlings that failed on arrival.
    credit = {"transaction_id": f"TXN-2026-{n + 3:04d}", "invoice_id": "CN-0032", "project_id": PROJECT_ID,
              "transaction_date": "2026-06-20", "supplier": "West Nile Seed & Seedling Co. (synthetic)",
              "description": "Credit note — seedlings rejected on delivery", "category": "Seedling Procurement",
              "amount": -9_840_000.0, "currency": "UGX", "status": "Verified",
              "document_reference": f"SYN-DOC-{n + 3:05d}"}
    df = pd.concat([df, pd.DataFrame([dup.to_dict(), uncategorised, credit])], ignore_index=True)
    # 4. Missing supporting document references.
    for tid in ("TXN-2026-0044", "TXN-2026-0121"):
        df.loc[df.transaction_id == tid, "document_reference"] = None

    df = df.sort_values(["transaction_date", "transaction_id"]).reset_index(drop=True)
    return df[["transaction_id", "invoice_id", "project_id", "transaction_date", "supplier", "description",
               "category", "amount", "currency", "status", "document_reference"]]


def build_forecasts(budgets: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for period in FORECAST_MONTHS:
        for i, cat in enumerate(categories(), start=1):
            b = float(budgets.loc[(budgets.financial_period == period) & (budgets.category == cat),
                                  "approved_amount"].iloc[0])
            factor, assumption = FORECAST_FACTOR[cat]
            rows.append({"forecast_id": f"FC-{period}-{i:02d}", "project_id": PROJECT_ID, "category": cat,
                         "forecast_period": period, "forecast_amount": round(b * factor, 2), "currency": "EUR",
                         "assumption": assumption, "updated_at": "2026-11-05T09:00:00"})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- upload test files

def build_valid_upload(existing: pd.DataFrame) -> pd.DataFrame:
    """A small, clean batch of late-arriving October invoices (passes validation)."""
    rows = [
        ("TXN-2026-U001", "INV-7001", "2026-10-28", "Arua Haulage Services (synthetic)",
         "Transportation of seedlings to planting sites", "Transport and Logistics", 6_150_000, "UGX"),
        ("TXN-2026-U002", "INV-7002", "2026-10-29", "Kei Highlands Nurseries Ltd (synthetic)",
         "Nursery materials — potting bags and substrate", "Nursery Operations", 3_280_000, "UGX"),
        ("TXN-2026-U003", "INV-7003", "2026-10-30", "GreenRoots Survey & Mapping (synthetic)",
         "Monitoring activities — survival counts", "Monitoring and Verification", 2_400.00, "EUR"),
        ("TXN-2026-U004", "INV-7004", "2026-10-30", "Riverline Field Lodge (synthetic)",
         "Field accommodation", "Administration", 1_845_000, "UGX"),
        ("TXN-2026-U005", "INV-7005", "2026-10-31", "Field Crew Payroll — Site Office (synthetic)",
         "Casual labour — seasonal peak", "Personnel and Labour", 12_300_000, "UGX"),
    ]
    return pd.DataFrame([{"transaction_id": r[0], "invoice_id": r[1], "project_id": PROJECT_ID,
                          "transaction_date": r[2], "supplier": r[3], "description": r[4], "category": r[5],
                          "amount": r[6], "currency": r[7], "status": "Pending Review",
                          "document_reference": f"SYN-DOC-U{i + 1:03d}"} for i, r in enumerate(rows)])


def build_problem_upload(existing: pd.DataFrame) -> pd.DataFrame:
    """A deliberately problematic batch used to demonstrate validation (each row annotated)."""
    first = existing.iloc[4]
    base = {"project_id": PROJECT_ID, "supplier": "Arua Haulage Services (synthetic)",
            "description": "Truck hire for materials", "category": "Transport and Logistics",
            "currency": "UGX", "status": "Pending Review"}
    rows = [
        {**base, "transaction_id": "TXN-2026-E001", "invoice_id": "INV-8001", "transaction_date": "2026-10-20",
         "amount": 4_100_000, "document_reference": "SYN-DOC-E001", "_issue": "valid row"},
        {**base, "transaction_id": "TXN-2026-E002", "invoice_id": "INV-8002", "transaction_date": "2026-10-21",
         "amount": 2_050_000, "document_reference": "SYN-DOC-E002", "_issue": "duplicate ID within file (1/2)"},
        {**base, "transaction_id": "TXN-2026-E002", "invoice_id": "INV-8003", "transaction_date": "2026-10-21",
         "amount": 1_230_000, "document_reference": "SYN-DOC-E003", "_issue": "duplicate ID within file (2/2)"},
        {**base, "transaction_id": first.transaction_id, "invoice_id": "INV-8004", "transaction_date": "2026-10-22",
         "amount": 820_000, "document_reference": "SYN-DOC-E004", "_issue": "ID already in database"},
        {**base, "transaction_id": "TXN-2026-E005", "invoice_id": first.invoice_id, "transaction_date": "2026-10-22",
         "amount": 3_075_000, "document_reference": "SYN-DOC-E005", "_issue": "invoice already in database"},
        {**base, "transaction_id": "TXN-2026-E006", "invoice_id": "INV-8006", "transaction_date": "2026-13-05",
         "amount": 615_000, "document_reference": "SYN-DOC-E006", "_issue": "invalid date"},
        {**base, "transaction_id": "TXN-2026-E007", "invoice_id": "INV-8007", "transaction_date": "2026-10-23",
         "amount": "four hundred", "document_reference": "SYN-DOC-E007", "_issue": "non-numeric amount"},
        {**base, "transaction_id": "TXN-2026-E008", "invoice_id": "INV-8008", "transaction_date": "2026-10-23",
         "amount": 0, "document_reference": "SYN-DOC-E008", "_issue": "zero amount"},
        {**base, "transaction_id": "TXN-2026-E009", "invoice_id": "INV-8009", "transaction_date": "2026-10-24",
         "category": "Catering", "amount": 410_000, "document_reference": "SYN-DOC-E009",
         "_issue": "unrecognised category"},
        {**base, "transaction_id": "TXN-2026-E010", "invoice_id": "INV-8010", "transaction_date": "2026-10-24",
         "supplier": None, "amount": 287_000, "document_reference": "SYN-DOC-E010", "_issue": "missing supplier"},
        {**base, "transaction_id": "TXN-2026-E011", "invoice_id": "INV-8011", "transaction_date": "2026-10-25",
         "currency": "XYZ", "amount": 1_000, "document_reference": "SYN-DOC-E011", "_issue": "unknown currency"},
        {**base, "transaction_id": "TXN-2026-E012", "invoice_id": "INV-8012", "transaction_date": "2026-10-25",
         "status": "Approved", "amount": 512_500, "document_reference": "SYN-DOC-E012",
         "_issue": "unrecognised status"},
        {**base, "transaction_id": "TXN-2026-E013", "invoice_id": "CN-8013", "transaction_date": "2026-10-26",
         "amount": -205_000, "document_reference": "SYN-DOC-E013", "_issue": "negative amount (warning: credit note?)"},
        {**base, "transaction_id": "TXN-2026-E014", "invoice_id": "INV-8014", "transaction_date": "2026-10-26",
         "category": None, "amount": 369_000, "document_reference": "SYN-DOC-E014",
         "_issue": "blank category (warning: imported as Uncategorised)"},
        {**base, "transaction_id": "TXN-2026-E015", "invoice_id": "INV-8015", "transaction_date": "2026-10-27",
         "amount": 451_000, "document_reference": None, "_issue": "missing document reference (warning)"},
        {**base, "transaction_id": "TXN-2026-E016", "invoice_id": "INV-8016", "transaction_date": "2025-12-15",
         "amount": 328_000, "document_reference": "SYN-DOC-E016",
         "_issue": "date outside budget phase (warning)"},
        {**base, "transaction_id": "TXN-2026-E017", "invoice_id": None, "transaction_date": "2026-10-27",
         "amount": 164_000, "document_reference": "SYN-DOC-E017", "_issue": "missing invoice ID (warning)"},
    ]
    df = pd.DataFrame(rows)
    return df.rename(columns={"_issue": "test_note"})


def build_forecast_update() -> pd.DataFrame:
    """Example forecast revision: transport forecast raised after a fuel price review."""
    return pd.DataFrame([{"project_id": PROJECT_ID, "category": "Transport and Logistics", "forecast_period": p,
                          "forecast_amount": amt, "currency": "EUR",
                          "assumption": "Revised Nov-26: fuel +20% vs budget per site manager update (illustrative)."}
                         for p, amt in zip(FORECAST_MONTHS, [12_600, 12_600, 14_400, 14_400, 12_600])])


# --------------------------------------------------------------------------- templates

TEMPLATE_SPECS: dict[str, dict] = {
    "budget": {
        "columns": ["project_id", "financial_period", "category", "approved_amount", "currency"],
        "example": [[PROJECT_ID, "2026-04", "Seedling Procurement", 30333, "EUR"],
                    [PROJECT_ID, "2026-04", "Nursery Operations", 20000, "EUR"]],
        "notes": ["financial_period: text 'YYYY-MM'", "category: one of the recognised categories (see list)",
                  "approved_amount: number >= 0 in `currency`", "currency: ISO code with a configured rate",
                  "Uploading a line for an existing project/period/category REVISES it (logged in the audit trail)."],
    },
    "transactions": {
        "columns": ["transaction_id", "invoice_id", "project_id", "transaction_date", "supplier", "description",
                    "category", "amount", "currency", "status", "document_reference"],
        "example": [["TXN-2026-9001", "INV-9001", PROJECT_ID, "2026-10-31", "Example Supplier Ltd",
                     "Transportation of seedlings to planting sites", "Transport and Logistics", 2050000, "UGX",
                     "Pending Review", "DOC-9001"],
                    ["TXN-2026-9002", "INV-9002", PROJECT_ID, "2026-10-31", "Example Consultants",
                     "Monitoring activities — survival counts", "Monitoring and Verification", 1800.00, "EUR",
                     "Pending Review", "DOC-9002"]],
        "notes": ["transaction_id: unique; must not already exist in the database",
                  "transaction_date: ISO date YYYY-MM-DD", "amount: non-zero number; negative = credit note",
                  "status: Verified / Pending Review / Queried",
                  "Leave category blank only if unknown — the row is imported as 'Uncategorised' and flagged."],
    },
    "forecast": {
        "columns": ["project_id", "category", "forecast_period", "forecast_amount", "currency", "assumption"],
        "example": [[PROJECT_ID, "Transport and Logistics", "2026-11", 12600, "EUR", "Fuel +20% vs budget"],
                    [PROJECT_ID, "Seedling Procurement", "2026-11", 8667, "EUR", "Per approved phasing"]],
        "notes": ["forecast_period: future month 'YYYY-MM'", "forecast_amount: expected spend in that month (>= 0)",
                  "assumption: REQUIRED in practice — explain the basis of the forecast",
                  "Uploading an existing project/category/period REPLACES that forecast (logged)."],
    },
}


def write_templates() -> None:
    out = templates_dir()
    out.mkdir(parents=True, exist_ok=True)
    for name, spec in TEMPLATE_SPECS.items():
        df = pd.DataFrame(spec["example"], columns=spec["columns"])
        df.to_csv(out / f"{name}_template.csv", index=False)
        with pd.ExcelWriter(out / f"{name}_template.xlsx", engine="openpyxl") as xw:
            df.to_excel(xw, sheet_name="data", index=False)
            notes = spec["notes"] + ["", "Recognised categories:"] + categories()
            pd.DataFrame({"instructions": notes}).to_excel(xw, sheet_name="instructions", index=False)


def generate_all(write_files: bool = True) -> dict[str, pd.DataFrame]:
    """Build the complete illustrative dataset; optionally write it to data/sample/."""
    rng = np.random.default_rng(SEED)
    projects = build_projects()
    budgets = build_budgets()
    transactions = build_transactions(budgets, rng)
    forecasts = build_forecasts(budgets)
    data = {"projects": projects, "budgets": budgets, "transactions": transactions, "forecasts": forecasts}
    if write_files:
        out = sample_dir()
        out.mkdir(parents=True, exist_ok=True)
        for name, df in data.items():
            df.to_csv(out / f"{name}.csv", index=False)
        with pd.ExcelWriter(out / "mount_kei_illustrative_dataset.xlsx", engine="openpyxl") as xw:
            pd.DataFrame({"notice": ["Illustrative financial data — not actual Hummingbirds financial information.",
                                     "Generated by src/data/sample_data.py (deterministic seed)."]}
                         ).to_excel(xw, sheet_name="READ_ME", index=False)
            for name, df in data.items():
                df.to_excel(xw, sheet_name=name, index=False)
        build_valid_upload(transactions).to_excel(out / "upload_example_valid_transactions.xlsx", index=False)
        build_problem_upload(transactions).to_csv(out / "upload_example_transactions_with_errors.csv", index=False)
        build_forecast_update().to_csv(out / "upload_example_forecast_revision.csv", index=False)
        write_templates()
    return data


def seed_database_from_sample(db_path=None) -> None:
    """Populate an empty database with the illustrative dataset."""
    from src.database import operations as ops

    data = generate_all(write_files=False)
    ops.seed_database(data["projects"], data["budgets"], data["transactions"], data["forecasts"], db_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--reset-db", action="store_true", help="delete and rebuild the SQLite database")
    args = parser.parse_args()
    data = generate_all(write_files=True)
    print(f"Wrote sample data to {sample_dir()} and templates to {templates_dir()}")
    for k, v in data.items():
        print(f"  {k}: {len(v)} rows")
    if args.reset_db:
        from src.database import operations as ops

        ops.reset_database()
        seed_database_from_sample()
        print("Database rebuilt from sample data.")


if __name__ == "__main__":
    main()
