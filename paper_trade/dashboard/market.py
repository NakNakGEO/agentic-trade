"""Near-live quotes for the dashboard's quote strip, from TradingView through the tradingview-mcp package.

The price is the close of TradingView's 1-minute bar forming now; the change is against today's daily open; the sparkline
uses the 1-minute candles the live loop records (paper_trade.live.tradingview). For watching only; nothing trades on
these. Every quote carries how old its snapshot is.
"""

from __future__ import annotations

import time

import pandas as pd

from paper_trade import assets

QUOTE_TTL = 8             # seconds; the TradingView snapshot itself is shared and refreshed about once a minute
SPARK_POINTS = 60

_cache: dict = {"at": 0.0, "key": None, "rows": []}


def _downsample(values: list[float], points: int) -> list[float]:
    if len(values) <= points:
        return values
    step = len(values) / points
    return [values[int(i * step)] for i in range(points - 1)] + [values[-1]]


def quote(ticker: str, now: pd.Timestamp | None = None) -> dict:
    """Latest price, change since today's open, a sparkline, and how old the TradingView snapshot is."""
    from paper_trade.live import tradingview

    now = now or pd.Timestamp.now(tz="UTC")
    row = {"ticker": ticker, "symbol": assets.canonical(ticker), "class": assets.asset_class(ticker)}
    if tradingview.symbol(ticker) is None:
        return {**row, "error": "no TradingView symbol for this asset"}
    try:
        try:
            snap = tradingview.snapshot()
        except Exception:                          # refused or cooling down: show the last quote with its real age
            snap = tradingview.last_snapshot()
            if snap is None:
                raise
        live = next((v for k, v in snap["symbols"].items() if assets.canonical(k) == row["symbol"]), {})
        price, opened = (live.get("m1") or {}).get("close"), (live.get("d1") or {}).get("open")
        if price is None:
            return {**row, "error": "TradingView has no 1-minute bar right now (market closed?)"}
        try:
            spark = [float(v) for v in tradingview.candles(ticker)["Close"].tail(SPARK_POINTS * 4)]
        except Exception:
            spark = [float(price)]
        bar_time = (live.get("m1") or {}).get("time")
        fetched = pd.Timestamp(bar_time, unit="s", tz="UTC") if bar_time else pd.Timestamp(snap["fetched_at"])   # the bar's own age
        return {**row, "price": float(price), "change": float(price) / float(opened) - 1 if opened else 0.0,
                "spark": _downsample(spark, SPARK_POINTS), "last_bar": fetched.isoformat(),
                "lag_minutes": round((now - fetched).total_seconds() / 60, 1), "source": "TradingView"}
    except Exception as exc:                                   # one asset failing must not blank the rest
        return {**row, "error": f"{type(exc).__name__}: {str(exc)[:80]}"}


def live_quotes(tickers: list[str]) -> list[dict]:
    """Quotes for every ticker, refreshed at most every ``QUOTE_TTL`` seconds."""
    key = tuple(tickers)
    if _cache["key"] == key and time.time() - _cache["at"] < QUOTE_TTL:
        return _cache["rows"]
    rows = [quote(t) for t in tickers]
    _cache.update(at=time.time(), key=key, rows=rows)
    return rows
