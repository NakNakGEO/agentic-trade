"""Hourly and 4-hour candle tables for the short-term agents, built from this system's own minute record.

The record keeps about two days of minute candles (live.tradingview.candles), so these tables show the last day or so of
hours. They are the system's own numbers, never an outside price history, and the text says how far back they reach.
"""

from __future__ import annotations

import pandas as pd

# (table title, pandas frequency, rows shown, hours one bar covers)
FRAMES = (("1-hour", "1h", 24, 1), ("4-hour", "4h", 8, 4))


def resample(minutes: pd.DataFrame, frequency: str) -> pd.DataFrame:
    """Minute candles (UTC, Open/High/Low/Close) as candles of ``frequency``, oldest first, empty periods dropped."""
    if minutes is None or minutes.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close"])
    grouped = minutes.resample(frequency)
    bars = pd.concat([grouped["Open"].first(), grouped["High"].max(), grouped["Low"].min(), grouped["Close"].last()], axis=1)
    return bars.dropna()


def _fmt(value: float) -> str:
    return f"{value:,.2f}" if abs(value) >= 1000 else f"{value:.4f}" if abs(value) >= 1 else f"{value:.6f}"


def table(minutes: pd.DataFrame, title: str, frequency: str, rows: int, hours: int) -> list[str]:
    """One markdown table of the last ``rows`` candles; the newest is marked as still forming when its period is not over."""
    bars = resample(minutes, frequency).iloc[-rows:]
    if bars.empty:
        return []
    forming = bars.index[-1] + pd.Timedelta(hours=hours) > minutes.index[-1] + pd.Timedelta(minutes=1)
    heading = f"{title} candles built from this system's own minute record ({minutes.index[0]:%Y-%m-%d %H:%M} to {minutes.index[-1]:%Y-%m-%d %H:%M} UTC"
    heading += "; the last candle is still forming):" if forming else "):"
    lines = ["", heading, "| Start (UTC) | Open | High | Low | Close | Range |", "|---|---|---|---|---|---|"]
    for stamp, bar in bars.iterrows():
        lines.append(f"| {stamp:%Y-%m-%d %H:%M} | {_fmt(bar.Open)} | {_fmt(bar.High)} | {_fmt(bar.Low)} | {_fmt(bar.Close)} | {_fmt(bar.High - bar.Low)} |")
    return lines


def tables(minutes: pd.DataFrame | None) -> list[str]:
    """The hourly and 4-hour tables for one instrument's minute candles (nothing when there are none yet)."""
    if minutes is None or minutes.empty:
        return []
    return [line for frame in FRAMES for line in table(minutes, *frame)]
