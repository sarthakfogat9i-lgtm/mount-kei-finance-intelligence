# Data Dictionary

Schema source of truth: `src/database/models.py`. Upload validation rules: `src/data/validation.py`.
Dates are ISO `YYYY-MM-DD`. Periods are `YYYY-MM`. Amounts are decimal numbers in the row's own `currency`.

## projects

| Field | Description | Type | Required | Example | Validation rule |
|---|---|---|---|---|---|
| project_id | Unique project identifier | TEXT (PK) | Yes | `MK-001` | Unique; referenced by all financial tables |
| project_name | Display name | TEXT | Yes | `Mount Kei Reforestation` | Non-blank |
| country | Country of implementation | TEXT | Yes | `Uganda` | Non-blank |
| currency | Project reporting currency | TEXT | Yes | `EUR` | ISO 4217 code |
| project_start_date | Start of the monitored budget phase | TEXT (date) | Yes | `2026-04-01` | ISO date |
| project_end_date | End of the monitored budget phase | TEXT (date) | Yes | `2027-03-31` | ISO date ≥ start |
| description | Free-text description and scope note | TEXT | No | `ILLUSTRATIVE FY2026/27…` | — |

## budgets

| Field | Description | Type | Required | Example | Validation rule |
|---|---|---|---|---|---|
| budget_id | Unique budget line ID | TEXT (PK) | Yes (generated if absent) | `BUD-2026-04-01` | Unique |
| project_id | Project | TEXT (FK → projects) | Yes | `MK-001` | Must exist in `projects` |
| financial_period | Budget month | TEXT | Yes | `2026-04` | Matches `YYYY-MM`, month 01–12 |
| category | Expense category | TEXT | Yes | `Seedling Procurement` | One of the configured categories (not "Uncategorised") |
| approved_amount | Approved budget for the month | REAL | Yes | `36400` | Numeric, ≥ 0 |
| currency | Currency of `approved_amount` | TEXT | Yes | `EUR` | Has a rate in `fx_rates` |
| *(unique)* | (project_id, financial_period, category) | — | — | — | No duplicates in a file; upload **revises** an existing line, and the audit log keeps the previous value |

## transactions

| Field | Description | Type | Required | Example | Validation rule |
|---|---|---|---|---|---|
| transaction_id | Unique transaction ID | TEXT (PK) | Yes | `TXN-2026-0001` | Unique within the file **and** not already in the database (error) |
| invoice_id | Supplier invoice reference | TEXT | No* | `INV-1003` | Blank → warning. Duplicate in file → warning. Already in DB → warning (possible double payment) |
| project_id | Project | TEXT (FK) | Yes | `MK-001` | Must exist |
| transaction_date | Transaction / posting date | TEXT (date) | Yes | `2026-10-14` | ISO date only (ambiguous `03/04/2026` rejected). Outside the budget phase or in the future → warning |
| supplier | Supplier name | TEXT | Yes | `Arua Haulage Services (synthetic)` | Non-blank |
| description | Expense description | TEXT | No* | `Transportation of seedlings to planting sites` | Blank → warning |
| category | Expense category | TEXT | Yes | `Transport and Logistics` | Recognised category; blank → imported as `Uncategorised` with a warning; unknown → error |
| amount | Amount in `currency` | REAL | Yes | `6150000` | Numeric; 0 → error; negative → warning (credit note). Accepts `1,234.50`, `(500)` |
| currency | Currency of `amount` | TEXT | Yes | `UGX` | Has a rate in `fx_rates` |
| status | Verification status | TEXT | Yes | `Pending Review` | `Verified` / `Pending Review` / `Queried`; blank → `Pending Review` with a warning |
| document_reference | Supporting document reference | TEXT | No* | `SYN-DOC-00012` | Blank → warning. `SYN-DOC-…` means a synthetic placeholder, not a real document |
| import_batch_id | Upload batch that created the row | TEXT (FK → import_batches) | System | `IMP-20261111…` | Set automatically; NULL for seed data |

\* Optional for import, but flagged on the register when blank.

## forecasts

| Field | Description | Type | Required | Example | Validation rule |
|---|---|---|---|---|---|
| forecast_id | Unique forecast line ID | TEXT (PK) | System | `FC-2026-11-06` | Generated |
| project_id | Project | TEXT (FK) | Yes | `MK-001` | Must exist |
| category | Expense category | TEXT | Yes | `Transport and Logistics` | Recognised category |
| forecast_period | Future month | TEXT | Yes | `2026-11` | `YYYY-MM`. Outside the phase → warning. Already closed (has actuals) → warning, ignored in FAC |
| forecast_amount | Expected spend in the month | REAL | Yes | `12600` | Numeric, ≥ 0 |
| currency | Currency of the forecast | TEXT | No | `EUR` | Defaults to base currency (warning); must have a rate |
| assumption | Basis of the forecast | TEXT | No (strongly expected) | `Fuel +15% vs budget persists` | Blank → warning |
| updated_at | Last change timestamp | TEXT (datetime) | System | `2026-11-05T09:00:00` | Set automatically |
| *(unique)* | (project_id, category, forecast_period) | — | — | — | Upload **replaces** an existing line (audited) |

## audit_log

| Field | Description | Type | Required | Example | Validation rule |
|---|---|---|---|---|---|
| log_id | Sequence number | INTEGER (PK, autoincrement) | System | `57` | — |
| record_type | Table affected | TEXT | System | `transaction` | budget / transaction / forecast / projects… |
| record_id | Affected record ID (`*` = whole-table seed) | TEXT | System | `TXN-2026-0001` | — |
| action | What happened | TEXT | System | `update` | insert / update / seed |
| previous_value | Values before the change (JSON) | TEXT | No | `{"status": "Pending Review"}` | — |
| new_value | Values after the change (JSON) | TEXT | No | `{"status": "Verified"}` | — |
| timestamp | When | TEXT (datetime) | System | `2026-11-11T17:51:04` | — |

## import_batches

| Field | Description | Type | Example |
|---|---|---|---|
| batch_id | Upload ID | TEXT (PK) | `IMP-20261111175104-5d8f02` |
| dataset_type | budget / transactions / forecast | TEXT | `transactions` |
| file_name | Uploaded file name | TEXT | `october_pack.xlsx` |
| rows_received | Data rows in the file | INTEGER | `17` |
| rows_imported | Rows written | INTEGER | `9` |
| rows_excluded | Rows with errors, not written | INTEGER | `8` |
| warnings | Warnings acknowledged by the analyst | INTEGER | `5` |
| imported_at | Timestamp | TEXT | `2026-11-11T17:51:04` |
| note | Analyst note | TEXT | `October close v2` |

## Derived (in-memory) fields

| Field | Where | Definition |
|---|---|---|
| amount_base | all monetary frames | Amount converted to base currency (see FINANCIAL_LOGIC §1) |
| period | transactions | `YYYY-MM` of `transaction_date` |
| fx_missing | transactions | Currency without a configured rate |
| flag_* / flags / flag_count | register | See FINANCIAL_LOGIC §5 |
| source_row | uploads | Row number in the uploaded file (header = row 1) |

## Recognised expense categories (illustrative)

Seedling Procurement · Nursery Operations · Land Preparation · Plantation and Restoration · Personnel and Labour ·
Transport and Logistics · Equipment and Machinery · Community Development · Monitoring and Verification ·
Administration · Other Project Costs. Plus the system label **Uncategorised** for transactions only.
These are proposed categories, **not** confirmed Hummingbirds accounting categories.
