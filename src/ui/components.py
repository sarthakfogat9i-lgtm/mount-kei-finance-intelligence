"""Reusable visual components (HTML + Streamlit) used by every page.

All components are presentational: they receive numbers already calculated by
``src/finance`` and never compute financial figures themselves. Styles are in
``src/ui/assets/theme.css`` (classes prefixed ``mk-``).

Accessibility rule: status is never shown by colour alone — every chip/badge
carries an icon character and a text label.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Callable, Iterable

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.utils.config import reporting_rules
from src.utils.formatting import fmt_money, fmt_pct

PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}

STATUS_TONE = {"Within Budget": ("ok", "●"), "Watchlist": ("warn", "▲"), "Potential Overspend": ("bad", "■")}
TONE_ICON = {"ok": "●", "warn": "▲", "bad": "■", "info": "i", "neutral": "○"}


def _e(x) -> str:
    return html.escape(str(x))


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and v == v


# --------------------------------------------------------------------------- small pieces

def chip(text: str, tone: str = "neutral", icon: str | None = None) -> str:
    """Pill badge with icon + text. tone: ok | warn | bad | info | neutral."""
    icon = TONE_ICON.get(tone, "") if icon is None else icon
    return f'<span class="mk-chip {tone}">{_e(icon)} {_e(text)}</span>'


def info_tip(text: str) -> str:
    """Small (i) marker with a CSS tooltip — used for KPI definitions."""
    return f'<i class="mk-info" tabindex="0" data-tip="{_e(text)}" aria-label="{_e(text)}">i</i>'


def section(title: str, sub: str = "") -> None:
    st.markdown(f'<div class="mk-h2">{_e(title)}</div>' + (f'<div class="mk-h2-sub">{_e(sub)}</div>' if sub else ""),
                unsafe_allow_html=True)


def card_title(title: str, sub: str = "") -> None:
    st.markdown(f'<div class="mk-card-title">{_e(title)}</div>' + (f'<div class="mk-card-sub">{_e(sub)}</div>' if sub else ""),
                unsafe_allow_html=True)


def step(no: int, title: str, sub: str = "") -> None:
    st.markdown(f'<div class="mk-step"><div class="no">{no}</div><div><div class="t">{_e(title)}</div>'
                + (f'<div class="s">{_e(sub)}</div>' if sub else "") + "</div></div>", unsafe_allow_html=True)


# --------------------------------------------------------------------------- KPI cards

def kpi_card(label: str, value: str, context: str = "", tone: str = "", tip: str = "",
             meter: float | None = None, meter_over: bool = False, accent: bool = False, badge: str = "",
             role: str = "") -> str:
    """Compact financial KPI card.

    tone: '' | 'neg' (adverse, red) | 'pos' (favourable, green). ``meter`` (0-100+) draws a thin bar.
    ``badge`` is pre-rendered chip HTML shown under the value.
    ``role`` ('budget' | 'actual' | 'forecast') adds the chart colour of that concept as a top rule,
    so budget, actual and forecast read consistently between cards and charts.
    """
    meter_html = ""
    if meter is not None and _is_num(meter):
        meter_html = (f'<div class="meter" role="img" aria-label="{meter:.0f}%"><i class="{"over" if meter_over else ""}" '
                      f'style="width:{max(0.0, min(meter, 100.0)):.1f}%"></i></div>')
    classes = "mk-kpi" + (" accent" if accent else "") + (f" role-{role}" if role else "")
    return (f'<div class="{classes}">'
            f'<div class="label">{_e(label)}{info_tip(tip) if tip else ""}</div>'
            f'<div class="value {tone}">{_e(value)}</div>'
            f'{f"<div style=margin-top:6px>{badge}</div>" if badge else ""}'
            f'<div class="ctx">{_e(context)}</div>{meter_html}</div>')


def kpi_row(cards: list[str], gap: str = "small") -> None:
    cols = st.columns(len(cards), gap=gap)
    for col, card in zip(cols, cards):
        col.markdown(card, unsafe_allow_html=True)


# --------------------------------------------------------------------------- status

def category_status(variance_pct: float, budgeted: bool = True, compact: bool = False) -> str:
    """Status chip for a category variance (positive = overspend). Threshold = reporting.significant_variance_pct.

    ``compact`` uses short labels for narrow tables (same thresholds, same icons).
    """
    labels = {"unbudgeted": ("Unbudgeted", "No budget"), "over": ("Overspend", "Over"), "above": ("Above plan", "Above"),
              "under": ("Underspend", "Under"), "ok": ("On track", "On track")}

    def lab(key: str) -> str:
        return labels[key][1 if compact else 0]

    if not budgeted:
        return chip(lab("unbudgeted"), "bad")
    if not _is_num(variance_pct):
        return chip("n/a", "neutral")
    thr = reporting_rules()["significant_variance_pct"]
    if variance_pct > thr:
        return chip(lab("over"), "bad")
    if variance_pct > 0:
        return chip(lab("above"), "warn")
    if variance_pct < -thr:
        return chip(lab("under"), "info", "▼")
    return chip(lab("ok"), "ok")


# --------------------------------------------------------------------------- attention list

def attention_panel(items: list[dict], currency: str = "EUR", limit: int | None = None) -> None:
    """Render items from ``budget_analysis.attention_items`` (only rule-backed issues)."""
    if not items:
        st.markdown('<div class="mk-empty">● No issues triggered by the monitoring rules for this period.</div>',
                    unsafe_allow_html=True)
        return
    rows = []
    for it in items[: limit or len(items)]:
        tone = it["severity"]
        amt = it.get("amount")
        amt_html = f'<div class="amt">{_e(fmt_money(amt, currency))}</div>' if _is_num(amt) else '<div class="amt"></div>'
        rows.append(f'<div class="mk-alert {tone}"><div class="ic">{TONE_ICON.get(tone, "!")}</div>'
                    f'<div class="t">{_e(it["title"])}</div>{amt_html}<div class="d">{_e(it["detail"])}</div></div>')
    st.markdown("".join(rows), unsafe_allow_html=True)
    if limit and len(items) > limit:
        st.caption(f"+ {len(items) - limit} more item(s) — see Reporting for the full list.")


# --------------------------------------------------------------------------- HTML financial table

@dataclass
class Col:
    """Column spec for ``html_table``.

    kind: text | money | pct | spct (signed %) | var (money, red if > 0) | varpct (signed %, red if > 0)
          | bar (utilisation % with progress bar) | html (pre-rendered) | wrap (long text)
    """
    key: str
    label: str
    kind: str = "text"


def _cell(v, kind: str, currency: str) -> tuple[str, str]:
    """Return (css class, inner html)."""
    if kind == "text":
        return "", _e("" if v is None or (isinstance(v, float) and v != v) else v)
    if kind == "wrap":
        return "wrap", _e("" if v is None else v)
    if kind == "html":
        return "", str(v)
    if not _is_num(v):
        return "num muted", "n/a"
    if kind == "money":
        return "num", _e(fmt_money(v, currency))
    if kind == "pct":
        return "num", _e(fmt_pct(v))
    if kind == "spct":
        return "num", _e(fmt_pct(v, signed=True))
    if kind == "var":
        return ("num neg" if v > 0.5 else "num"), _e(("+" if v > 0.5 else "") + fmt_money(v, currency))
    if kind == "varpct":
        return ("num neg" if v > 0.05 else "num"), _e(fmt_pct(v, signed=True))
    if kind == "bar":
        over = v > 100
        return "num", (f'<div class="mk-bar"><span>{_e(fmt_pct(v))}</span><span class="track">'
                       f'<i class="{"over" if over else ""}" style="width:{max(0, min(v, 100)):.1f}%"></i></span></div>')
    return "", _e(v)


def html_table(df: pd.DataFrame, cols: list[Col], currency: str = "EUR", total: dict | None = None,
               max_height: int | None = None, highlight: list[bool] | None = None) -> None:
    """Accounting-style table: sticky header, right-aligned tabular numbers, total row, hover.

    ``highlight`` (one bool per row) tints the rows that need attention, so only those stand out.
    """
    num_kinds = {"money", "pct", "spct", "var", "varpct", "bar"}
    head = "".join(f'<th class="{"num" if c.kind in num_kinds else ""}">{_e(c.label)}</th>' for c in cols)
    body = []
    flags = list(highlight) if highlight is not None else [False] * len(df)
    for row, hl in zip(df.to_dict("records"), flags):
        tds = "".join(f'<td class="{cls}">{inner}</td>' for cls, inner in (_cell(row.get(c.key), c.kind, currency) for c in cols))
        body.append(f'<tr class="{"attn" if hl else ""}">{tds}</tr>')
    if total:
        tds = "".join(f'<td class="{cls}">{inner}</td>' for cls, inner in (_cell(total.get(c.key), c.kind, currency) for c in cols))
        body.append(f'<tr class="total">{tds}</tr>')
    style = f' style="max-height:{max_height}px"' if max_height else ""
    st.markdown(f'<div class="mk-table-wrap"{style}><table class="mk-table"><thead><tr>{head}</tr></thead>'
                f'<tbody>{"".join(body)}</tbody></table></div>', unsafe_allow_html=True)


# --------------------------------------------------------------------------- charts & cards

def chart_card(title: str, sub: str, fig: go.Figure) -> None:
    """Bordered card with a typographic title, a one-line explanation and the Plotly chart."""
    with st.container(border=True):
        card_title(title, sub)
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)


def fact_grid(rows: Iterable[tuple[str, str]]) -> None:
    cells = "".join(f'<div><div class="k">{_e(k)}</div><div class="v">{_e(v)}</div></div>' for k, v in rows)
    st.markdown(f'<div class="mk-facts">{cells}</div>', unsafe_allow_html=True)


def bullet_list(items: Iterable[str], fmt: Callable[[str], str] = _e) -> None:
    st.markdown('<ul class="mk-obs">' + "".join(f"<li>{fmt(i)}</li>" for i in items) + "</ul>", unsafe_allow_html=True)


# --------------------------------------------------------------------------- verdict & forecast comparison

def verdict(status: str, headline: str, detail: str = "") -> None:
    """One-line answer to 'are we on track?': status chip + plain-language sentence built from engine figures."""
    tone, icon = STATUS_TONE[status]
    st.markdown(f'<div class="mk-verdict {tone}"><span class="mk-chip {tone}">{icon} {_e(status)}</span>'
                f'<span class="h">{_e(headline)}</span>' + (f'<span class="d">{_e(detail)}</span>' if detail else "")
                + "</div>", unsafe_allow_html=True)


def forecast_comparison(approved: float, actual: float, remaining: float, fac: float, variance: float,
                        variance_pct: float, currency: str = "EUR") -> None:
    """Two horizontal bars on one scale: approved budget vs forecast at completion (actual + remaining).

    Widths are display proportions of figures already calculated by src/finance — nothing is recomputed
    except the bar scale.
    """
    scale = max(approved, fac, 1.0)

    def w(v: float) -> str:
        return f"{max(0.0, v) / scale * 100:.2f}%"

    over = variance > 0
    var_chip = chip(f"{'+' if over else ''}{fmt_money(variance, currency)} ({fmt_pct(variance_pct, signed=True)})",
                    "bad" if over else "ok", "▲" if over else "▼")
    st.markdown(
        f'<div class="mk-cmp">'
        f'<div class="row"><div class="k">Approved budget</div><div class="track"><i class="b" style="width:{w(approved)}"></i></div>'
        f'<div class="v mk-num">{_e(fmt_money(approved, currency))}</div></div>'
        f'<div class="row"><div class="k">Forecast at completion</div><div class="track">'
        f'<i class="a" style="width:{w(actual)}" title="Actual to date"></i>'
        f'<i class="f" style="width:{w(remaining)}" title="Forecast remaining"></i></div>'
        f'<div class="v mk-num">{_e(fmt_money(fac, currency))}</div></div>'
        f'<div class="legend"><span><i class="a"></i>Actual to date {_e(fmt_money(actual, currency))}</span>'
        f'<span><i class="f"></i>Forecast remaining {_e(fmt_money(remaining, currency))}</span></div>'
        f'<div class="var">Forecast variance {var_chip}</div></div>', unsafe_allow_html=True)
