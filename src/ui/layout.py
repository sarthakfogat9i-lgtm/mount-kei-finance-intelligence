"""Application shell: theme injection, top header, sidebar, page header, cached data loading.

Every page starts with::

    data = load_data()
    as_of = page_shell(data, "budget", "Budget & Expenditure", "Where is the money going?")

No financial calculation happens in this module; it only reads results from ``src/finance``.
Reusable visual components live in ``src/ui/components.py``; styles in ``src/ui/assets/theme.css``.
"""
from __future__ import annotations

import datetime as dt
import html
from functools import lru_cache
from pathlib import Path

import pandas as pd
import streamlit as st

from src.data.preprocessing import ProjectData, build_project_data
from src.database import operations as ops
from src.finance import budget_analysis as ba
from src.ui.navigation import NAV
from src.utils.config import default_project_id, illustrative_label, load_config
from src.utils.formatting import fmt_money, fmt_pct, period_label

THEME_PATH = Path(__file__).parent / "assets" / "theme.css"

# url_path of each page as registered in app.py ("" = default page). Used to highlight the active nav item.
PAGE_TITLES = {key: title for key, _path, title, _icon, _url in NAV}


def _flat(markup: str) -> str:
    """Collapse multi-line HTML onto one line so Markdown never treats indented lines as code."""
    return " ".join(line.strip() for line in markup.splitlines() if line.strip())


# --------------------------------------------------------------------------- theme

@lru_cache(maxsize=1)
def _theme_css() -> str:
    return THEME_PATH.read_text(encoding="utf-8")


def inject_theme(page_key: str) -> None:
    """Load the shared stylesheet and mark the active navigation item for this page."""
    # Streamlit renders st.page_link anchors with the page title in the href attribute.
    title = PAGE_TITLES.get(page_key, "").replace('"', '\\"')
    selector = f'a[data-testid="stPageLink-NavLink"][href="{title}"]'
    active = (f"{selector}{{background:var(--teal-soft)!important;border-left-color:var(--teal)!important;}}"
              f"{selector} span{{color:var(--teal-dark)!important;font-weight:600!important;}}"
              f'{selector} [data-testid="stIconMaterial"]{{color:var(--teal)!important;}}')
    st.markdown(f"<style>{_theme_css()}{active}</style>", unsafe_allow_html=True)


# --------------------------------------------------------------------------- data

def ensure_database() -> None:
    """On first run, seed the SQLite database with the illustrative dataset."""
    if ops.is_empty():
        from src.data.sample_data import seed_database_from_sample

        seed_database_from_sample()


@st.cache_data(show_spinner=False)
def _load(project_id: str, version: int) -> ProjectData:
    """Cached by data version: any write (audit-log entry) invalidates the cache automatically."""
    projects = ops.get_projects()
    project = projects[projects["project_id"] == project_id].iloc[0].to_dict()
    return build_project_data(project, ops.get_budgets(project_id), ops.get_transactions(project_id),
                              ops.get_forecasts(project_id))


def load_data() -> ProjectData:
    ensure_database()
    pid = st.session_state.get("project_id", default_project_id())
    return _load(pid, ops.data_version())


def data_status(data: ProjectData, as_of: str) -> tuple[str, str, str]:
    """Describe the ACTUAL state of the loaded data (not connectivity): tone, label, detail.

    * bad  — a reconciliation check fails
    * warn — reconciled, but unverified transactions or data warnings exist
    * ok   — reconciled and every transaction to date is verified
    """
    recon = ba.reconciliation_checks(data, as_of)
    tx = data.transactions[data.transactions["period"] <= as_of]
    unverified = int((tx["status"] != "Verified").sum())
    if not recon["passed"].all():
        return "bad", "Reconciliation failed", f"{int((~recon['passed']).sum())} check(s) failed"
    if unverified or data.warnings:
        detail = f"{unverified} unverified" if unverified else f"{len(data.warnings)} data warning(s)"
        return "warn", "Reconciled · review open", detail
    return "ok", "Reconciled · verified", "All transactions to date verified"


# --------------------------------------------------------------------------- shell

def _sidebar(data: ProjectData) -> None:
    """Brand, all six navigation links, and the project panel (pushed to the bottom by CSS)."""
    p = data.project
    with st.sidebar:
        st.markdown('<div class="mk-side-brand">Mount Kei <span>·</span> Finance<br>Intelligence'
                    '<small>Financial Monitoring &amp; Reporting</small></div>', unsafe_allow_html=True)
        st.markdown('<div class="mk-side-label">Navigation</div>', unsafe_allow_html=True)
        for _key, path, title, icon, _url in NAV:
            try:
                st.page_link(path, label=title, icon=icon)
            except Exception:  # noqa: BLE001 — headless tests run a single page without the navigation registry
                pass
        st.markdown(_flat(
            f"""<div class="mk-side-project">
              <div class="k">Project</div>
              <div class="v">{html.escape(str(p['project_name']).replace(' Reforestation', ''))}</div>
              <div class="s">{html.escape(str(p['country']))} · {html.escape(str(p['project_id']))} · {data.base_currency}</div>
              <div class="tag">Illustrative financial dataset</div>
            </div>"""), unsafe_allow_html=True)


def _topbar(data: ProjectData) -> str:
    """Slim header: identity (left), reporting period selector (middle), data state (right)."""
    periods = data.fy_periods
    default = data.latest_actual_period or periods[-1]
    # The selected month is kept in a plain session_state entry ("as_of"), NOT as a widget key:
    # Streamlit discards widget state when the user switches page, which would reset the period.
    if st.session_state.get("as_of") not in periods:
        st.session_state["as_of"] = default

    c1, c2, c3 = st.columns([3.4, 2.2, 3.6], vertical_alignment="center")
    c1.markdown('<div class="mk-topbar-id"><div class="name">Mount Kei Finance Intelligence</div>'
                '<div class="sub">Financial Monitoring &amp; Reporting</div></div>', unsafe_allow_html=True)
    # (identity repeated in the sidebar; the top bar keeps it for context when the sidebar is collapsed)
    as_of = c2.selectbox("Reporting period (month-end)", periods, index=periods.index(st.session_state["as_of"]),
                         format_func=period_label, label_visibility="collapsed",
                         help="Actuals are counted to the end of this month; later months use the forecast.")
    st.session_state["as_of"] = as_of
    tone, label, detail = data_status(data, as_of)
    colour = {"ok": "var(--success)", "warn": "var(--warning-mark)", "bad": "var(--danger-mark)"}[tone]
    ts = ops.last_updated()
    try:
        ts_txt = dt.datetime.fromisoformat(ts).strftime("%d %b %Y, %H:%M") if ts else "n/a"
    except ValueError:
        ts_txt = str(ts)
    c3.markdown(f'<div class="mk-topbar-meta"><div><span class="mk-dot" style="background:{colour}"></span>'
                f'<b>{html.escape(label)}</b> · {html.escape(detail)}</div>'
                f'<div>Data last updated {html.escape(ts_txt)} · actuals to {period_label(default)}</div></div>',
                unsafe_allow_html=True)
    st.markdown('<div class="mk-topbar-rule"></div>', unsafe_allow_html=True)
    return as_of


def page_shell(data: ProjectData, page_key: str, title: str, lede: str = "", eyebrow: str = "Mount Kei") -> str:
    """Draw theme, sidebar, top header and page header. Returns the selected as-of month ('YYYY-MM')."""
    inject_theme(page_key)
    _sidebar(data)
    as_of = _topbar(data)
    st.markdown(_flat(
        f"""<div class="mk-pagehead"><div>
              <div class="mk-eyebrow">{html.escape(eyebrow)}</div>
              <div class="mk-h1">{html.escape(title)}</div>
              {f'<div class="mk-lede">{html.escape(lede)}</div>' if lede else ''}
            </div>
            <div class="mk-badge-illustrative" title="{html.escape(illustrative_label())}">
              ILLUSTRATIVE DATA — NOT ACTUAL PROJECT ACCOUNTS</div></div>"""),
        unsafe_allow_html=True)
    for w in data.warnings:
        st.warning(w, icon=":material/warning:")
    return as_of


def footer() -> None:
    cfg = load_config()["app"]
    st.markdown(f'<div class="mk-foot"><div>{html.escape(illustrative_label())} Public project facts: '
                'docs/SOURCE_REGISTER.md. Not connected to any Hummingbirds accounting system.</div>'
                f'<div>Mount Kei Finance Intelligence · v{html.escape(cfg["version"])}</div></div>',
                unsafe_allow_html=True)


# --------------------------------------------------------------------------- dataframe helpers

def styled_table(df: pd.DataFrame, money: list[str] = (), pct: list[str] = (),
                 variance: list[str] = ()) -> "pd.io.formats.style.Styler":
    """Format a numeric st.dataframe while keeping the numbers sortable.

    ``variance`` columns are shown in red when positive (positive = overspend).
    """
    def _money(v):
        return fmt_money(v) if isinstance(v, (int, float)) and v == v else "n/a"

    def _pct(v, signed):
        return fmt_pct(v, signed=signed) if isinstance(v, (int, float)) and v == v else "n/a"

    fmt = {c: _money for c in money if c in df.columns}
    fmt.update({c: (lambda v, s=(c in variance): _pct(v, s)) for c in pct if c in df.columns})
    styler = df.style.format(fmt, na_rep="n/a")
    present = [c for c in variance if c in df.columns]
    if present:
        styler = styler.map(lambda v: "color: #B23C3C; font-weight: 600" if isinstance(v, (int, float))
                            and v == v and v > 0 else "", subset=present)
    return styler


def download_df(df: pd.DataFrame, label: str, file_name: str) -> None:
    st.download_button(label, df.to_csv(index=False).encode("utf-8"), file_name=file_name, mime="text/csv")


def eur2(v) -> str:
    """Styler formatter: '-€1,234.56' (sign before the symbol), 'n/a' for missing."""
    return fmt_money(v, "EUR", 2) if isinstance(v, (int, float)) and v == v else "n/a"
