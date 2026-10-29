"""Read the day-by-day record: daily bars, closes and indicator series for every tool that needs past prices."""

from __future__ import annotations

import pandas as pd

from paper_trade.daybook import store

COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def bars(ticker: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Recorded daily bars with ``start <= day <= end`` (both optional), indexed by day; empty when nothing matches."""
    rows = [(pd.Timestamp(day), row.get("open"), row.get("high"), row.get("low"), row.get("close"), row.get("volume"))
            for day, row in store.load(ticker).items()
            if row.get("close") is not None and (not start or day >= start) and (not end or day <= end)]
    frame = pd.DataFrame(rows, columns=["day", *COLUMNS]).set_index("day")
    return frame.astype(float)


def closes(ticker: str, start: str, end: str) -> pd.Series:
    """Recorded daily closes with ``start <= day < end``."""
    frame = bars(ticker, start)
    return frame["Close"][frame.index < pd.Timestamp(end)]


def indicator(ticker: str, field: str, end: str, days: int) -> pd.Series:
    """One daily indicator (a TradingView field such as ``RSI``) over the ``days`` before ``end``, as recorded."""
    since = (pd.Timestamp(end) - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    values = {}
    for day, row in store.load(ticker).items():
        if since <= day <= end:
            found = row.get("indicators", {})
            if field == "MACD.hist" and "MACD.macd" in found and "MACD.signal" in found:
                values[pd.Timestamp(day)] = found["MACD.macd"] - found["MACD.signal"]
            elif found.get(field) is not None:
                values[pd.Timestamp(day)] = found[field]
    return pd.Series(values, dtype=float)


def row(ticker: str, day: str) -> dict:
    return store.load(ticker).get(day, {})


def first_day(ticker: str) -> str | None:
    """The first day this system recorded for ``ticker``."""
    days = list(store.load(ticker))
    return days[0] if days else None
