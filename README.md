# Mount Kei Finance Intelligence

**Financial Monitoring & Project Reporting — illustrative prototype**

> **Illustrative financial data — not actual Hummingbirds financial information.**
> Every budget, transaction, supplier and forecast in this application is synthetic.
> Public facts about the Mount Kei project come from the sources in [docs/SOURCE_REGISTER.md](docs/SOURCE_REGISTER.md).
> The tool is not connected to, and does not imply access to, any Hummingbirds accounting system.

## What it does

A finance-first dashboard that gives a financial analyst and a CFO one place to understand the financial position of the
Mount Kei Reforestation project (Mount Kei Central Forest Reserve, West Nile, Uganda). It covers this workflow:

1. Local accountants and project managers send monthly spreadsheets.
2. The analyst uploads them. The tool validates each row, explains every problem, and imports only after confirmation.
3. The tool categorises spend, compares actuals with the phased budget, flags unusual or incomplete transactions,
   and forecasts cost at completion.
4. The analyst generates a monthly report (Excel / PDF) for CFO review.

It is deliberately **narrow**. It is a financial monitoring tool, not a project-management, carbon-trading or
biodiversity platform.

## Who it is for

| User | Main use |
|---|---|
| **Financial analyst** (primary) | Upload and validate data, investigate variances and flagged transactions, maintain forecasts, prepare the monthly report |
| **CFO / CEO** (secondary) | Read the Financial Overview and the monthly report without opening Excel files |

## Main features

| Page | What you can do |
|---|---|
| **1 · Financial Overview** | A one-sentence verdict (Within Budget / Watchlist / Potential Overspend, with the rules behind it). Four KPIs: approved budget, actual expenditure, forecast at completion, forecast variance. One chart of spend to date vs budget phased to date. A forecast vs budget comparison, a category table and the items requiring attention. |
| **2 · Budget & Expenditure** | A detailed budget vs actual table by category for any period window, plus one monthly actual vs phased-budget trend. Filter by period, category, supplier and status. Drill into individual transactions. |
| **3 · Transaction Register** | Search, filter and sort all transactions. Automatic flags for duplicate IDs and invoices, missing values, uncategorised spend, categories over budget, unusually large amounts, credit notes and missing FX rates. Audited status and category changes. |
| **4 · Forecasting** | Forecast at completion = actual to date + forecast remaining. Base, optimistic and pessimistic scenarios, compared in one chart, with editable, transparent % assumptions. Category-level adjustments. A run-rate cross-check. Month-by-month traceability to each assumption. |
| **5 · Data Upload** | Upload budget, transaction or forecast files (.xlsx / .csv). Validation summary, row-level errors and warnings, preview, impact preview, explicit confirmation, import history, downloadable templates. |
| **6 · Reporting** | A concise monthly management report covering financial position, budget vs actual, category deviations, forecast at completion, data-quality issues and attention items, plus analyst commentary. Exports to **Excel** and **PDF**. |

The data is stored in a local **SQLite** database, so uploaded data persists across restarts. Every change is written
to an **audit log** that records the previous and new values.

## Technology stack

Python 3.10+ · Streamlit · Pandas · Plotly · SQLite · OpenPyXL · ReportLab (PDF) · PyYAML · Pytest.
No AI API key or internet connection is required.

## Installation

```bash
cd mount_kei_finance_intelligence
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Running the application

```bash
streamlit run app.py
```

On first run the database (`data/database/mount_kei_finance.db`) is created and seeded with the illustrative dataset.
To regenerate the sample files and rebuild the database:

```bash
python -m src.data.sample_data --reset-db
```

Run the tests:

```bash
python -m pytest -q
```

## Uploading data

1. Open **Data Upload** and choose the dataset type: *Actual expenditure transactions*, *Budget* or
   *Forecast assumptions*.
2. Download the template (`data/templates/`) and fill it in. Dates must be `YYYY-MM-DD` and periods `YYYY-MM`.
3. Upload the `.xlsx` or `.csv` file. The validation summary shows:
   - **Errors**: the row cannot be imported as supplied (e.g. invalid date, unknown category, duplicate ID).
   - **Warnings**: the row can be imported but needs attention (e.g. credit note, missing document, invoice already recorded).
4. Review the issue list, the preview and the impact statement. Tick the confirmation boxes and click **Import into database**.
   Rows with errors are never silently dropped. They are listed, downloadable and counted in the import log.

Try `data/sample/upload_example_transactions_with_errors.csv` to see validation at work, and
`data/sample/upload_example_valid_transactions.xlsx` for a clean import.

## Generating reports

Open **Reporting**, choose the month and optionally type your analyst commentary. Then click **Export to Excel**
(8 sheets: summary, categories, monthly, deviations, data quality, flagged transactions, status rules, reconciliation)
or **Export to PDF** (a concise management report).

## Documentation

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full technical architecture, Mermaid diagrams, how-to guides for extending the app |
| [docs/FINANCIAL_LOGIC.md](docs/FINANCIAL_LOGIC.md) | Every formula, definition, rule and worked example |
| [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) | Every field: type, required, example, validation rule |
| [docs/SOURCE_REGISTER.md](docs/SOURCE_REGISTER.md) | Public sources on Mount Kei, discrepancies, information gaps |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Version history |
