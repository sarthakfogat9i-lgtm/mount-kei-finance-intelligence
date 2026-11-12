"""Page 5 — Data Upload & Validation.

Workflow: choose dataset -> upload file -> automatic validation -> review errors,
warnings and preview -> explicit confirmation -> import (audited) -> dashboard updates.
"""
from __future__ import annotations

import datetime as dt

import streamlit as st

from src.data import validation as val
from src.data.ingestion import IngestionError, read_upload
from src.data.preprocessing import convert_to_base, prepare_budgets
from src.database import operations as ops
from src.ui.components import chip, kpi_card, kpi_row, section, step
from src.ui.layout import footer, load_data, page_shell
from src.utils.config import sample_dir, templates_dir
from src.utils.formatting import fmt_money

data = load_data()
page_shell(data, "upload", "Data Upload",
           "Consolidate updates from local accountants and project managers. Files are validated row by row and "
           "nothing is imported until you confirm.")
pid = data.project["project_id"]

TYPES = {"Actual expenditure transactions": "transactions", "Budget": "budget", "Forecast assumptions": "forecast"}
step(1, "Choose the dataset", "Each dataset has its own template and validation rules.")
label = st.radio("What are you uploading?", list(TYPES), horizontal=True, label_visibility="collapsed")
dtype = TYPES[label]

# ------------------------------------------------------------------ templates
with st.container(border=True):
    st.markdown('<div class="mk-card-title">Templates & examples</div><div class="mk-card-sub">Supported formats: '
                '.xlsx, .xls, .csv · dates YYYY-MM-DD · periods YYYY-MM</div>', unsafe_allow_html=True)
    t1, t2, t3, t4 = st.columns(4)
    tdir, sdir = templates_dir(), sample_dir()
    for col, ext, mime in ((t1, "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                           (t2, "csv", "text/csv")):
        f = tdir / f"{dtype}_template.{ext}"
        if f.exists():
            col.download_button(f"Template (.{ext})", f.read_bytes(), file_name=f.name, mime=mime,
                                use_container_width=True)
    examples = {"transactions": [("Example: clean file", "upload_example_valid_transactions.xlsx"),
                                 ("Example: file with errors", "upload_example_transactions_with_errors.csv")],
                "budget": [], "forecast": [("Example: forecast revision", "upload_example_forecast_revision.csv")]}[dtype]
    for col, (text, name) in zip((t3, t4), examples):
        f = sdir / name
        if f.exists():
            col.download_button(text, f.read_bytes(), file_name=name, use_container_width=True, help=name)
    st.caption("Required columns: " + ", ".join(f"`{c}`" for c in val.SCHEMAS[dtype]["required"]) +
               ". Optional: " + ", ".join(f"`{c}`" for c in val.SCHEMAS[dtype]["optional"]) + ".")

step(2, "Upload the file", "Excel (.xlsx, .xls) or CSV · the file is read as text so validation sees exactly what was supplied.")
upload = st.file_uploader("Upload an Excel (.xlsx) or CSV file", label_visibility="collapsed", type=["xlsx", "xls", "csv"], key=f"up_{dtype}_{st.session_state.get('upload_nonce', 0)}")
if upload is None:
    st.markdown('<div class="mk-empty">No file selected. Download a template above, or try the example file with '
                'errors to see how validation works.</div>', unsafe_allow_html=True)
else:
    # ------------------------------------------------------------------ read + validate
    try:
        raw = read_upload(upload.getvalue(), upload.name)
    except IngestionError as exc:
        st.error(f"**The file could not be read.** {exc}")
        st.stop()

    projects = ops.get_projects()["project_id"].tolist()
    if dtype == "transactions":
        result = val.validate_transactions(raw, ops.existing_transaction_ids(), ops.existing_invoice_ids(),
                                           projects, data.fy_periods)
    elif dtype == "budget":
        result = val.validate_budget(raw, projects)
    else:
        result = val.validate_forecast(raw, projects, data.fy_periods, data.latest_actual_period)

    step(3, "Review the validation", f"{upload.name} · {result.summary()['dataset']}")
    s = result.summary()
    kpi_row([
        kpi_card("Rows received", f"{s['rows_received']}", "Data rows in the file"),
        kpi_card("Ready to import", f"{s['rows_ready']}", "No errors", tone="pos" if s["rows_ready"] else ""),
        kpi_card("Rows with errors", f"{s['rows_with_errors']}", "Will not be imported",
                 tone="neg" if s["rows_with_errors"] else ""),
        kpi_card("Errors", f"{s['errors']}", "Block the row", badge=chip("✕ must fix", "bad", "") if s["errors"] else ""),
        kpi_card("Warnings", f"{s['warnings']}", "Importable · need review",
                 badge=chip("review", "warn") if s["warnings"] else ""),
    ])
    st.markdown('<div class="mk-legend"><span><b style="color:var(--danger)">✕ Error</b> — the row cannot be imported '
                'as supplied</span><span><b style="color:var(--warning)">▲ Warning</b> — importable, but needs your '
                'attention</span></div>', unsafe_allow_html=True)

    for e in result.file_errors:
        st.error(f"**File cannot be imported:** {e}")
    if result.fully_valid and result.n_warnings == 0:
        st.success("All rows passed validation with no warnings.")
    elif result.fully_valid:
        st.warning(f"No errors. {result.n_warnings} warning(s) need your review before import.")
    elif not result.file_errors:
        st.error(f"{s['rows_with_errors']} row(s) have errors and cannot be imported as supplied. "
                 "Correct them in the source file and re-upload, or import only the valid rows below.")

    if not result.issues.empty:
        sev = st.segmented_control("Show", ["All", "Errors", "Warnings"], default="All") \
            if hasattr(st, "segmented_control") else st.radio("Show", ["All", "Errors", "Warnings"], horizontal=True)
        issues = result.issues
        if sev == "Errors":
            issues = issues[issues["severity"] == val.ERROR]
        elif sev == "Warnings":
            issues = issues[issues["severity"] == val.WARNING]
        shown = issues.assign(severity=issues["severity"].map({val.ERROR: "✕ Error", val.WARNING: "▲ Warning"}))
        st.dataframe(shown.rename(columns={"source_row": "File row", "column": "Column", "severity": "Severity",
                                           "rule": "Rule", "message": "What to correct", "value": "Value supplied"})
                     .style.apply(lambda r: ["color:#B23C3C;background-color:#FDF6F5" if r["Severity"].startswith("✕")
                                             else "color:#9A6510" for _ in r], axis=1),
                     hide_index=True, use_container_width=True, height=min(36 * (len(issues) + 1) + 4, 420))
        st.download_button("Download issue list (CSV)", result.issues.to_csv(index=False).encode(),
                           file_name=f"validation_issues_{upload.name}.csv")

    tabs = st.tabs(["Preview — rows ready to import", "Rows with errors (will NOT be imported)", "Raw file"])
    tabs[0].dataframe(result.clean, hide_index=True, use_container_width=True, height=300)
    tabs[1].dataframe(result.excluded, hide_index=True, use_container_width=True, height=300)
    if not result.excluded.empty:
        tabs[1].download_button("Download rows with errors (CSV) to send back for correction",
                                result.excluded.to_csv(index=False).encode(), file_name=f"rows_to_correct_{upload.name}.csv")
    tabs[2].dataframe(raw, hide_index=True, use_container_width=True, height=300)

    # ------------------------------------------------------------------ impact preview
    if not result.is_blocked:
        step(4, "Confirm and import", "Imports run in one database transaction and are written to the audit log.")
        if dtype == "transactions":
            total = convert_to_base(result.clean["amount"], result.clean["currency"]).sum()
            st.write(f"Importing adds **{len(result.clean)}** transaction(s) totalling **{fmt_money(total)}** "
                     "(converted at configured planning rates) to actual expenditure.")
        elif dtype == "budget":
            cur_b = data.budgets[["project_id", "financial_period", "category", "amount_base"]]
            new_b = prepare_budgets(result.clean)[["project_id", "financial_period", "category", "amount_base"]]
            merged = new_b.merge(cur_b, on=["project_id", "financial_period", "category"], how="left",
                                 suffixes=("_new", "_current"))
            revised = merged["amount_base_current"].notna().sum()
            delta = (merged["amount_base_new"] - merged["amount_base_current"].fillna(0)).sum()
            st.write(f"**{revised}** existing budget line(s) will be revised and **{len(merged) - revised}** added. "
                     f"Total approved budget changes by **{fmt_money(delta)}** "
                     f"(from {fmt_money(data.budgets['amount_base'].sum())} to "
                     f"{fmt_money(data.budgets['amount_base'].sum() + delta)}). "
                     "Previous amounts are kept in the audit log.")
            if abs(delta) > 0.01:
                st.warning("This changes the approved budget. Confirm that the revision has been formally approved.")
        else:
            closed = result.clean[result.clean["forecast_period"] <= (data.latest_actual_period or "")]
            st.write(f"**{len(result.clean)}** forecast line(s) will be inserted or replaced. "
                     + (f"{len(closed)} line(s) are for months that already have actuals and will not affect the "
                        "forecast at completion." if len(closed) else ""))

        confirm_warn = True
        if result.n_warnings:
            confirm_warn = st.checkbox(f"I have reviewed the {result.n_warnings} warning(s) listed above.")
        confirm_partial = True
        if len(result.excluded):
            confirm_partial = st.checkbox(f"Import only the {len(result.clean)} valid row(s). The "
                                          f"{len(result.excluded)} row(s) with errors will be excluded and recorded "
                                          "in the import log.")
        note = st.text_input("Import note (optional)", placeholder="e.g. October close — site accountant pack v2")
        if st.button("Import into database", type="primary", disabled=not (confirm_warn and confirm_partial)):
            args = dict(file_name=upload.name, rows_received=result.rows_received,
                        rows_excluded=len(result.excluded), warnings=result.n_warnings, note=note or None)
            try:
                if dtype == "transactions":
                    batch = ops.insert_transactions(result.clean, **args)
                elif dtype == "budget":
                    batch = ops.upsert_budgets(result.clean, **args)
                else:
                    batch = ops.upsert_forecasts(result.clean, **args)
            except Exception as exc:  # noqa: BLE001 — never fail silently
                st.error(f"Import failed and was rolled back; no data was changed. Details: {exc}")
            else:
                st.session_state["last_import"] = (batch, len(result.clean), label)
                # New uploader key clears the file so it is not re-validated against itself.
                st.session_state["upload_nonce"] = st.session_state.get("upload_nonce", 0) + 1
                st.rerun()

if "last_import" in st.session_state:
    b, n, lab = st.session_state.pop("last_import")
    st.success(f"Imported {n} row(s) of {lab.lower()} — batch `{b}`. All pages now reflect the new data.")

# ------------------------------------------------------------------ history
section("Import history", "Every confirmed upload, with rows received, imported and excluded.")
hist = ops.get_import_batches()
if hist.empty:
    st.caption("No uploads yet. The database currently holds the illustrative sample dataset.")
else:
    st.dataframe(hist, hide_index=True, use_container_width=True)

with st.expander("Reset the database to the illustrative sample data"):
    st.caption("Deletes all uploaded data and the audit log, then reloads the synthetic dataset. Cannot be undone.")
    if st.checkbox("I understand that all uploaded data will be deleted.") and \
            st.button("Reset database", type="secondary"):
        ops.reset_database()
        st.cache_data.clear()
        st.session_state.pop("as_of", None)
        st.success(f"Database reset at {dt.datetime.now():%H:%M:%S}.")
        st.rerun()
footer()
