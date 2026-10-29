"""Prices and indicators for the AI models: TradingView live data plus this system's own day-by-day record.

Functions take the same arguments as the framework's Yahoo vendor functions and return text for the agents. The live
part is TradingView's bar forming now and current indicator values on four timeframes; the history part is what this
system recorded itself, day by day (paper_trade.daybook). No TradingView history is used, so the record starts on the
first day the system ran. A past date is answered from the record only, never with today's numbers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from paper_trade import daybook
from paper_trade.assets import canonical
from paper_trade.live import settings as live
from paper_trade.tvdata import client

TIMEFRAMES = {"1h": "1 hour", "4h": "4 hours", "1d": "1 day", "1W": "1 week"}
# framework indicator name -> (TradingView field, what it is)
INDICATORS = {
    "close_50_sma": ("SMA50", "50-period simple moving average"),
    "close_200_sma": ("SMA200", "200-period simple moving average"),
    "close_10_ema": ("EMA10", "10-period exponential moving average"),
    "macd": ("MACD.macd", "MACD line (12, 26)"),
    "macds": ("MACD.signal", "MACD signal line (9)"),
    "macdh": ("MACD.hist", "MACD histogram: MACD line minus signal line"),
    "rsi": ("RSI", "14-period relative strength index"),
    "boll": ("SMA20", "Bollinger middle band (20-period simple moving average)"),
    "boll_ub": ("BB.upper", "Bollinger upper band (20, 2)"),
    "boll_lb": ("BB.lower", "Bollinger lower band (20, 2)"),
    "atr": ("ATR", "14-period average true range (daily timeframe only)"),
    "vwma": ("VWMA", "volume-weighted moving average (20)"),
}
LIVE_SLACK_DAYS = 3                 # an analysis date this many days old still counts as "today" (weekends)


def _live_ticker(symbol: str) -> str | None:
    wanted = canonical(symbol)
    return next((t for t in (*live.TICKERS, *live.TV_RECORD_EXTRA) if canonical(t) == wanted), None)


def is_live(as_of: str | None) -> bool:
    if not as_of:
        return True
    day = datetime.strptime(as_of[:10], "%Y-%m-%d").date()
    return day >= datetime.now(timezone.utc).date() - timedelta(days=LIVE_SLACK_DAYS)


def _frames(symbol: str) -> tuple[str | None, dict, str]:
    """TradingView's current bars and indicators for ``symbol``; empty when TradingView cannot be reached right now."""
    try:
        data = client.analysis()
    except Exception:                    # the recorded history still answers; the live part is reported missing
        return _live_ticker(symbol), {}, ""
    ticker = _live_ticker(symbol)
    return ticker, data.get("analysis", {}).get(ticker, {}) if ticker else {}, data.get("fetched_at", "")


def _fmt(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n/a"
    value = float(value)
    return f"{value:,.2f}" if abs(value) >= 1000 else f"{value:.4f}" if abs(value) >= 1 else f"{value:.6f}"


def _record_note(symbol: str) -> str:
    first = daybook.first_day(symbol)
    return (f"This system's own daily record of {symbol} starts on {first}; days before that are not available "
            "(no outside price history is used)." if first else
            f"This system has not recorded any full day of {symbol} yet; only the live bars below exist.")


def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    recorded = daybook.bars(symbol, start_date, end_date)
    lines = [f"# {symbol} prices, {start_date} to {end_date}", _record_note(symbol)]
    if len(recorded):
        lines += ["", "Daily bars recorded by this system from TradingView (the last day may still be forming):",
                  "| Day | Open | High | Low | Close | Volume |", "|---|---|---|---|---|---|"]
        lines += [f"| {day:%Y-%m-%d} | {_fmt(r.Open)} | {_fmt(r.High)} | {_fmt(r.Low)} | {_fmt(r.Close)} | "
                  f"{'n/a' if pd.isna(r.Volume) else f'{r.Volume:,.0f}'} |" for day, r in recorded.iterrows()]
    if is_live(end_date):
        ticker, frames, stamp = _frames(symbol)
        if frames:
            lines += ["", f"Bars forming now on TradingView (fetched {stamp} UTC):",
                      "| Timeframe | Open | High | Low | Close | Change vs previous bar % |", "|---|---|---|---|---|---|"]
            for key, label in TIMEFRAMES.items():
                bar = frames.get(key)
                if bar:
                    lines.append(f"| {label} | {_fmt(bar.get('open'))} | {_fmt(bar.get('high'))} | {_fmt(bar.get('low'))} | "
                                 f"{_fmt(bar.get('close'))} | {bar.get('change', 0):+.3f} |")
    if len(lines) == 2:
        return f"NO_DATA_AVAILABLE: no recorded or live prices for {symbol} on {start_date} to {end_date}. {lines[1]}"
    return "\n".join(lines)


def _value(values: dict, field: str):
    if field == "MACD.hist":
        both = "MACD.macd" in values and "MACD.signal" in values
        return (values["MACD.macd"] - values["MACD.signal"]) if both else None, None
    return values.get(field), values.get(f"{field}[1]")


def get_indicators(symbol: str, indicator: str, as_of_date: str, look_back_days: int = 30) -> str:
    if indicator not in INDICATORS:
        return f"NO_DATA_AVAILABLE: '{indicator}' is not supplied. Available: {', '.join(INDICATORS)}."
    field, meaning = INDICATORS[indicator]
    lines = [f"## {indicator} ({meaning}) for {symbol}"]
    if is_live(as_of_date):
        _, frames, stamp = _frames(symbol)
        rows = [(label, *_value(frames.get(key, {}), field)) for key, label in TIMEFRAMES.items()]
        rows = [r for r in rows if r[1] is not None]
        if rows:
            lines += [f"Now on TradingView (fetched {stamp} UTC), on each timeframe:",
                      "| Timeframe | Value now | Previous bar |", "|---|---|---|"]
            lines += [f"| {label} | {_fmt(now)} | {_fmt(before)} |" for label, now, before in rows]
    history = daybook.indicator(symbol, field, as_of_date[:10], look_back_days)
    if len(history):
        lines += ["", f"Daily values recorded by this system over the {look_back_days} days to {as_of_date[:10]}:",
                  "| Day | Value |", "|---|---|"] + [f"| {d:%Y-%m-%d} | {_fmt(v)} |" for d, v in history.items()]
    if len(lines) == 1:
        return f"NO_DATA_AVAILABLE: no {indicator} for {symbol} as of {as_of_date}. {_record_note(symbol)}"
    return "\n".join(lines + ["", _record_note(symbol)])


def _rating(value) -> str:
    if value is None:
        return "n/a"
    value = float(value)
    words = ("STRONG SELL" if value <= -0.5 else "SELL" if value < -0.1 else "NEUTRAL" if value <= 0.1
             else "BUY" if value < 0.5 else "STRONG BUY")
    return f"{words} ({value:+.2f} on TradingView's -1 to +1 scale)"


def _snapshot_rows(day: dict, bar: dict) -> list[tuple]:
    return [("Price (close of the daily bar)", bar.get("close")), ("Daily open", bar.get("open")),
            ("Daily high", bar.get("high")), ("Daily low", bar.get("low")), ("Change on the day %", day.get("change")),
            ("SMA 20 / 50 / 200", " / ".join(_fmt(day.get(k)) for k in ("SMA20", "SMA50", "SMA200"))),
            ("EMA 10 / 20", " / ".join(_fmt(day.get(k)) for k in ("EMA10", "EMA20"))),
            ("RSI 14", day.get("RSI")), ("MACD line / signal", f"{_fmt(day.get('MACD.macd'))} / {_fmt(day.get('MACD.signal'))}"),
            ("Bollinger upper / lower", f"{_fmt(day.get('BB.upper'))} / {_fmt(day.get('BB.lower'))}"),
            ("ATR 14 (daily)", day.get("ATR")), ("ADX", day.get("ADX"))]


def market_snapshot(symbol: str, as_of_date: str, look_back_days: int = 30, indicators=None) -> str:
    """Stands in for the framework's verified market snapshot: the daily bar, key indicators and TradingView ratings."""
    if is_live(as_of_date):
        ticker, frames, stamp = _frames(symbol)
        day, ratings, source = frames.get("1d", {}), {k: frames.get(k, {}).get("Recommend.All") for k in TIMEFRAMES}, \
            f"from TradingView (fetched {stamp} UTC)"
        bar = day
    else:
        row = daybook.row(symbol, as_of_date[:10])
        day, bar, ratings, source = row.get("indicators", {}), row, row.get("ratings", {}), \
            f"from this system's record of {as_of_date[:10]}"
    if not bar or bar.get("close") is None:
        return f"NO_DATA_AVAILABLE: no snapshot for {symbol} on {as_of_date}. {_record_note(symbol)}"
    lines = [f"# Verified market snapshot for {symbol} {source}", "", "| Field | Value |", "|---|---|"]
    lines += [f"| {name} | {value if isinstance(value, str) else _fmt(value)} |" for name, value in _snapshot_rows(day, bar)]
    lines += ["", "TradingView's own technical rating (all indicators combined):"]
    lines += [f"- {TIMEFRAMES[k]}: {_rating(ratings.get(k))}" for k in TIMEFRAMES]
    return "\n".join(lines + ["", _record_note(symbol)])


def closes(symbol: str, start_date: str, end_date: str) -> pd.Series:
    """Daily closes from this system's record, ``start <= day < end`` (scores past decisions; no outside history)."""
    return daybook.closes(symbol, start_date, end_date)
