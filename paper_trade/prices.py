"""Daily prices for the reports, comparisons and charts: this system's own day-by-day record (paper_trade.daybook).

The record is built from the live TradingView fetches, starting on the first day the system ran; no Yahoo and no
TradingView history. The day still forming is left out, as the framework's own settlement does.
"""

from __future__ import annotations

import pandas as pd

from paper_trade import daybook


def _completed(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    today = pd.Timestamp(daybook.trading_day(ticker, pd.Timestamp.now(tz="UTC")))
    frame = frame[(frame["Close"] > 0) & (frame.index < today)]
    return frame


def load_bars(ticker: str, start: str) -> pd.DataFrame:
    """Completed daily open/high/low/close bars from ``start``, indexed by trading day."""
    frame = _completed(daybook.bars(ticker, start), ticker)
    if frame.empty:
        raise ValueError(f"no recorded days for {ticker} from {start} (the record starts {daybook.first_day(ticker)})")
    return frame[["Open", "High", "Low", "Close"]]


def load_closes(ticker: str, start: str, end: str | None = None) -> pd.Series:
    """Completed daily closes from ``start`` (to ``end``, exclusive, when given), indexed by trading day."""
    frame = _completed(daybook.bars(ticker, start), ticker)
    series = frame["Close"] if end is None else frame["Close"][frame.index < pd.Timestamp(end)]
    if series.empty:
        raise ValueError(f"no recorded days for {ticker} from {start} (the record starts {daybook.first_day(ticker)})")
    return series
