"""Display formatting helpers. Formatting never changes the underlying numbers."""
from __future__ import annotations

import math

CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "UGX": "UGX "}


def _is_missing(value: float | None) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def fmt_money(value: float | None, currency: str = "EUR", decimals: int = 0) -> str:
    """Format an amount, e.g. 1234567.8 -> '€1,234,568'. Negative -> '-€1,234'."""
    if _is_missing(value):
        return "n/a"
    sym = CURRENCY_SYMBOLS.get(currency, f"{currency} ")
    sign = "-" if value < 0 else ""
    return f"{sign}{sym}{abs(value):,.{decimals}f}"


def fmt_money_short(value: float | None, currency: str = "EUR") -> str:
    """Compact amount for KPI cards: €2.40m, €845k."""
    if _is_missing(value):
        return "n/a"
    sym = CURRENCY_SYMBOLS.get(currency, f"{currency} ")
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000:
        return f"{sign}{sym}{v / 1_000_000:,.2f}m"
    if v >= 10_000:
        return f"{sign}{sym}{v / 1_000:,.0f}k"
    return f"{sign}{sym}{v:,.0f}"


def fmt_pct(value: float | None, decimals: int = 1, signed: bool = False) -> str:
    if _is_missing(value):
        return "n/a"
    return f"{value:+.{decimals}f}%" if signed else f"{value:.{decimals}f}%"


def fmt_variance(value: float | None, currency: str = "EUR") -> str:
    """Variance with an explicit direction word. Positive = overspend (house convention)."""
    if _is_missing(value):
        return "n/a"
    if abs(value) < 0.005:
        return f"{fmt_money(0, currency)} (on budget)"
    word = "over" if value > 0 else "under"
    return f"{fmt_money(abs(value), currency)} {word}"


def period_label(period: str) -> str:
    """'2026-04' -> 'Apr 2026'."""
    import datetime as dt

    try:
        return dt.datetime.strptime(period, "%Y-%m").strftime("%b %Y")
    except (TypeError, ValueError):
        return str(period)


def period_label_short(period: str) -> str:
    """'2026-04' -> "Apr 26" (compact axis labels)."""
    import datetime as dt

    try:
        return dt.datetime.strptime(period, "%Y-%m").strftime("%b %y")
    except (TypeError, ValueError):
        return str(period)
