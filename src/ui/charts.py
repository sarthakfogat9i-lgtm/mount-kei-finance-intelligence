"""Plotly chart builders (visualisation layer) — v0.3: three charts, each answering one question.

| Chart                        | Page          | Financial question it answers                                      |
|------------------------------|---------------|--------------------------------------------------------------------|
| ``spend_to_date``            | Overview      | Is cumulative spend running ahead of the budget phased to date?    |
| ``monthly_actual_vs_budget`` | Budget & Exp. | In which months did spending run above or below plan?              |
| ``scenario_comparison``      | Forecasting   | Under each scenario, where does the project finish vs the budget?  |

Charts receive already-calculated DataFrames from ``src/finance`` and only draw. Titles live outside
the figure (``components.chart_card``). Fixed colour roles on every page:
    Budget -> indigo #6E66D1 · Actual -> teal #008F89 · Forecast -> ochre #C08A2E, always hatched.
Red/green are reserved for status. The trio passes colour-vision checks (all pairs ΔE >= 12).
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.utils.formatting import period_label_short as period_label

BUDGET = "#6E66D1"
ACTUAL = "#008F89"
FORECAST = "#C08A2E"
DANGER = "#B23C3C"
SUCCESS = "#27845A"
GRID = "#EEF1F0"
AXIS = "#D7DDDA"
INK = "#151515"
MUTED = "#737B78"
FONT = "Inter, -apple-system, Segoe UI, Helvetica, Arial, sans-serif"
HATCH = dict(color="white", line=dict(color=FORECAST, width=1.5), pattern=dict(shape="/", fgcolor=FORECAST, size=6))


def _layout(fig: go.Figure, height: int = 340, legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=4, r=8, t=34 if legend else 10, b=4),
        plot_bgcolor="white", paper_bgcolor="white", showlegend=legend,
        font=dict(family=FONT, size=12, color=INK),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=11.5, color=MUTED)),
        hoverlabel=dict(bgcolor="white", bordercolor=AXIS, font=dict(family=FONT, size=12, color=INK)),
        bargap=0.3,
    )
    fig.update_yaxes(gridcolor=GRID, zeroline=True, zerolinecolor=AXIS, tickprefix="€", tickformat="~s",
                     tickfont=dict(color=MUTED, size=11), title=None)
    fig.update_xaxes(showgrid=False, tickfont=dict(color=MUTED, size=11), tickangle=0, title=None, linecolor=AXIS)
    return fig


def spend_to_date(monthly: pd.DataFrame) -> go.Figure:
    """Cumulative budget phased to date vs cumulative actual, CLOSED months only (no forecast, no full-year line).

    ``monthly`` is ``budget_analysis.monthly_summary``. The gap at the last point is the variance to date.
    """
    closed = monthly[monthly["closed"]]
    x = [period_label(p) for p in closed["period"]]
    fig = go.Figure()
    fig.add_scatter(x=x, y=closed["cumulative_budget"], name="Budget phased to date", mode="lines+markers",
                    line=dict(color=BUDGET, width=2.5), marker=dict(size=6),
                    hovertemplate="Budget phased to date: €%{y:,.0f}<extra></extra>")
    fig.add_scatter(x=x, y=closed["cumulative_actual"], name="Actual expenditure to date", mode="lines+markers",
                    line=dict(color=ACTUAL, width=2.5), marker=dict(size=6),
                    hovertemplate="Actual to date: €%{y:,.0f}<extra></extra>")
    if not closed.empty:
        b, a = float(closed["cumulative_budget"].iloc[-1]), float(closed["cumulative_actual"].iloc[-1])
        for y, txt, col in ((b, f"€{b / 1e6:,.2f}m budget", BUDGET), (a, f"€{a / 1e6:,.2f}m actual", ACTUAL)):
            fig.add_annotation(x=x[-1], y=y, text=f"<b>{txt}</b>", showarrow=False, xanchor="left", xshift=8,
                               yshift=8 if y == max(a, b) else -8, font=dict(color=col, size=11.5))
    fig = _layout(fig, height=330)
    fig.update_layout(hovermode="x unified", margin=dict(r=110))
    fig.update_yaxes(rangemode="tozero")
    return fig


def monthly_actual_vs_budget(df: pd.DataFrame) -> go.Figure:
    """Monthly actual spend (bars) against the phased monthly budget (line). ``df`` from
    ``budget_analysis.monthly_budget_vs_actual``; variance shown in the tooltip (positive = overspend)."""
    x = [period_label(p) for p in df["period"]]
    fig = go.Figure()
    fig.add_bar(x=x, y=df["actual"], name="Actual", marker_color=ACTUAL, customdata=df["variance"],
                hovertemplate="Actual: €%{y:,.0f}<br>vs budget: %{customdata:+,.0f}<extra></extra>")
    fig.add_scatter(x=x, y=df["budget"], name="Phased budget", mode="lines+markers",
                    line=dict(color=BUDGET, width=2), marker=dict(size=7),
                    hovertemplate="Phased budget: €%{y:,.0f}<extra></extra>")
    fig = _layout(fig, height=320)
    fig.update_layout(hovermode="x unified")
    return fig


def scenario_comparison(scen: pd.DataFrame, approved: float) -> go.Figure:
    """One bar per scenario: actual to date (identical in every scenario) + forecast remaining (the only part
    that changes), against the approved budget line. ``scen`` from ``forecasting.scenario_comparison``."""
    df = scen.iloc[::-1]
    fig = go.Figure()
    fig.add_bar(y=df["scenario"], x=df["actual_to_date"], name="Actual to date (same in every scenario)",
                orientation="h", marker_color=ACTUAL, hovertemplate="Actual to date: €%{x:,.0f}<extra></extra>")
    fig.add_bar(y=df["scenario"], x=df["forecast_remaining"], name="Forecast remaining", orientation="h",
                marker=HATCH, hovertemplate="Forecast remaining: €%{x:,.0f}<extra></extra>")
    for r in df.itertuples():
        over = r.forecast_variance > 0
        fig.add_annotation(y=r.scenario, x=r.forecast_at_completion, xanchor="left", xshift=8, showarrow=False,
                           text=f"<b>€{r.forecast_at_completion:,.0f}</b>  "
                                f"<span style='color:{DANGER if over else SUCCESS}'>{'▲ +' if over else '▼ −'}"
                                f"€{abs(r.forecast_variance):,.0f} ({r.forecast_variance_pct:+.1f}%)</span>",
                           font=dict(size=12, color=INK))
    fig.add_vline(x=approved, line=dict(color=BUDGET, width=2),
                  annotation_text=f"Approved budget €{approved:,.0f}", annotation_position="top",
                  annotation_font=dict(color=BUDGET, size=11))
    fig = _layout(fig, height=300)
    # Legend below the plot so the approved-budget label above the line never collides with it.
    fig.update_layout(barmode="stack", bargap=0.45, margin=dict(r=210, t=26, b=8),
                      legend=dict(yanchor="top", y=-0.14, xanchor="left", x=0))
    fig.update_xaxes(tickprefix="€", tickformat="~s", showgrid=True, gridcolor=GRID, rangemode="tozero")
    fig.update_yaxes(tickprefix="", showgrid=False, tickfont=dict(color=INK, size=12.5), zeroline=False)
    return fig
