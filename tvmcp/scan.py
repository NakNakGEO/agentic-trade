"""One TradingView scanner request for many instruments across markets (forex, gold, crypto, stocks).

TradingView's scanner answers for any mix of instruments in a single request, with any number of columns and any timeframe:
a column name ending ``|1`` is the 1-minute value, ``|60`` hourly, ``|240`` four-hourly, ``|1W`` weekly, and a bare name
the daily value. Asking once for everything, instead of one request per market and timeframe, keeps us far under
TradingView's rate limit (it answers HTTP 429 to a client that asks too often).

It uses the tradingview-screener package (the one the tradingview-mcp server is built on) as shipped.
"""

import math

from tradingview_screener import Query

MARKETS = ("forex", "cfd", "crypto", "america")
TIMEFRAMES = {"1h": "|60", "4h": "|240", "1d": "", "1W": "|1W"}
INDICATORS = ("open", "high", "low", "close", "volume", "change", "Recommend.All", "Recommend.MA", "Recommend.Other", "RSI",
              "RSI[1]", "SMA10", "SMA20", "SMA50", "SMA100", "SMA200", "EMA10", "EMA20", "EMA50", "EMA100", "EMA200",
              "MACD.macd", "MACD.signal", "BB.upper", "BB.lower", "ATR", "ADX", "ADX+DI", "ADX-DI", "Stoch.K", "Stoch.D",
              "CCI20", "Mom", "W.R", "AO", "VWMA")
MINUTE = ("open|1", "high|1", "low|1", "close|1")


def clean(value):
    """None for a missing or NaN cell, else the plain value."""
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else value


def scan(symbols: dict, columns: list) -> dict:
    """{ticker: {column: value}} for ``symbols`` ({ticker: "EXCHANGE:SYMBOL|screener"}), in one request."""
    names = {spec.split("|")[0]: ticker for ticker, spec in symbols.items()}
    markets = [m for m in MARKETS if any(spec.endswith("|" + m) for spec in symbols.values())]
    _, frame = Query().set_markets(*markets).select(*columns).set_tickers(*names).get_scanner_data()
    return {names[row["ticker"]]: {c: clean(row.get(c)) for c in columns} for row in frame.to_dict("records")
            if row["ticker"] in names}
