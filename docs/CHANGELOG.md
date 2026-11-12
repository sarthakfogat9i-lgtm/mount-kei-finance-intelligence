# Changelog

All notable changes are recorded here. Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: SemVer.

## [0.3.0] — 2026-11-11 — Dashboard simplification (information architecture)

No financial formula, assumption, data model, validation rule, reconciliation check, audit behaviour or export
content changed. The full-year vs phased-to-date distinction, the variance sign convention (positive = overspend),
the FAC formula and FX-before-aggregation are unchanged. The full audit and decisions are in ARCHITECTURE.md §4b.

### Changed
- **Financial Overview** now answers four questions top-down:
  - A one-sentence verdict.
  - Four KPI cards: Approved Budget, Actual Expenditure, Forecast at Completion, Forecast Budget Variance. Remaining
    budget and utilisation moved to a secondary line and tooltips.
  - One main chart: cumulative budget phased to date vs actual to date, closed months only, with the reporting period
    in the title.
  - A compact forecast-at-completion comparison.
  - One category table (phased budget, actual, variance, %, status), highlighting categories more than 10% over plan.
  - The attention list, with no repeats of the table.
  - Status rules and reconciliation are in collapsed expanders.
- **Budget & Expenditure:** the detailed category table is primary (overspend rows highlighted). One monthly actual vs
  phased-budget trend chart. Two redundant charts and the KPI row (which duplicated the total row) are removed.
- **Transaction Register:** KPI cards reduced from 6 to 4 review counts.
- **Forecasting:** KPI order is actual → remaining → FAC → approved → variance. One scenario chart shows that only
  remaining spend differs between scenarios, with a table that states each assumption. The FAC bridge, scenario cards
  and per-category chart are removed.
- **Reporting:** a concise 7-section management report: financial position, budget vs actual (month and to date),
  category deviations, FAC, data-quality issues, attention items, analyst commentary. The inline chart and duplicated
  tables are removed.

### Added
- `budget_analysis.monthly_budget_vs_actual()` (aggregation of existing data; the optional category filter applies to
  budget and actuals alike).
- A `kind` field on `attention_items()` so pages can avoid repeating issues.
- `components.verdict`, `components.forecast_comparison`, row highlighting in `html_table`, compact status labels.
- `tests/test_ui_charts.py` (6 tests). Full suite: 82 passed.

### Removed
- Chart builders: `budget_vs_actual_by_category`, `monthly_trend`, `cumulative_chart`, `forecast_vs_budget`,
  `fac_bridge`, `scenario_bars`, `monthly_by_category_chart`. Components: `status_strip`, `scenario_card` (and their CSS).

## [0.2.0] — 2026-11-11 — UI/UX redesign (presentation only)

No financial calculation, data model, database structure, validation rule, forecasting formula or export content was
changed. All 74 existing tests pass unchanged; 2 tests were added for the new attention list.

### Changed
- **Visual identity** taken from hummingbirds.eu's own stylesheet: brand teal `#009892` / `#136C69`, near-black text,
  white space. **Inter** for text and **Inter Tight** for headings (the site's heading font, PangeaAfrikan, is
  commercial). Tabular numerals throughout.
- **Application shell:** a slim top header (identity, reporting-period selector, real data-status indicator, "data last
  updated"); a light sidebar with Material line icons, a teal active state and the project panel at the bottom; a
  consistent page header with the "Illustrative data — not actual project accounts" badge.
- **Financial Overview:** a status strip that shows the rules behind the status. Six compact KPI cards with definition
  tooltips, comparison badges and a utilisation meter. Charts in titled cards. A new **Items requiring attention**
  panel, built only from triggered rules and flags.
- **Budget & Expenditure:** an accounting-style comparison table (right-aligned numbers, utilisation progress bars,
  status badges with icon and label, total row) and a summary card row for the selected window.
- **Transaction Register:** filters in a card, text status badges, flag markers and tinted flagged rows; the review
  panel is grouped in a card.
- **Forecasting:** recorded facts (budget, actual) are visually separated from forecasts (remaining, FAC) by colour
  role. Scenario cards show each assumption beside its result. Scenario bars no longer carry overlapping labels.
- **Data Upload:** a numbered 4-step flow, a visible templates panel, summary cards, and a clear `✕ Error` vs
  `▲ Warning` distinction.
- **Reporting:** report "document" layout with numbered sections, key-figure grid, compact tables and an inline
  cumulative chart. PDF/Excel exports re-coloured to the teal palette.
- **Charts:** new colour roles (budget indigo, actual teal, forecast hatched ochre), titles moved out of the plot,
  toolbar hidden, zero-based bars, unified hover on time series.
- The reporting period now persists when switching pages via the sidebar. Before this, a page switch could reset it.

### Added
- `src/ui/assets/theme.css`, `src/ui/components.py`, `src/ui/navigation.py`.
- `operations.last_updated()` (read-only) and `budget_analysis.attention_items()` (restates existing rules and flags).
- Responsive rules for smaller laptops (≤ 1360 / 1200 / 1100 px) and print rules.

## [0.1.0] — 2026-11-11 — First build

### Added
- **Research:** reviewed the Hummingbirds Mount Kei article (project folder) and public sources. Created
  `docs/SOURCE_REGISTER.md` with 10 sources, the discrepancies between them (area, CO₂, jobs, Lendosphere terms) and
  information gaps (no public budget; no verified link to Gondwana).
- **Data model:** SQLite schema with `projects`, `budgets`, `transactions`, `forecasts`, `audit_log`,
  `import_batches`. Currency is stored on every monetary row.
- **Synthetic dataset** (`src/data/sample_data.py`, deterministic): €2.4m FY2026/27 budget across 11 categories ×
  12 months, 234 transactions (EUR + UGX, 15 fictional suppliers), 55 forecast lines with assumptions, and planted
  data-quality issues. Also example upload files (valid and with errors) and templates (CSV and XLSX).
- **Financial engine:** pure calculation functions, category and monthly summaries, forecasting (FAC, scenarios,
  category adjustments, run-rate cross-check), transaction flags, rule-based financial status, reconciliation checks.
- **Validation:** required columns, types, ISO dates, duplicate IDs and invoices (in file and in DB), categories,
  statuses, FX availability, and credit notes. Error vs warning severities; no silent discards.
- **Dashboard (Streamlit, 6 pages):** Financial Overview, Budget & Expenditure, Transaction Register, Forecasting,
  Data Upload & Validation, Reporting. Global "as-of month" selector; illustrative-data labels throughout.
- **Reporting:** monthly report with facts, rule-based observations, significant deviations, data quality, attention
  items and human-written commentary. Excel (8 sheets) and PDF export.
- **Audit:** every insert and update is logged with previous and new values. Imports are logged as batches. Analysts
  can change status and category from the register (audited).
- **Tests:** 74 tests, covering the specification's worked example (€2.0m / €0.9m / €1.3m → FAC €2.2m, +€200k),
  edge cases, reconciliation for every month, validation rules, DB persistence and rollback, exports, and headless
  rendering of every page for four as-of months.
- **Docs:** README, ARCHITECTURE (with 4 Mermaid diagrams), DATA_DICTIONARY, FINANCIAL_LOGIC, SOURCE_REGISTER,
  CHANGELOG.

### Known limitations
See `docs/ARCHITECTURE.md` §14.
