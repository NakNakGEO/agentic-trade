"""Live market data for the live book: the latest price, M1 bars, the daily range. No Yahoo.

Each ticker is read from the best live source that covers it, trying the next one when a source fails:
TradingView (through the tradingview-mcp package; all ten pairs) -> OANDA (only with a token) -> Kraken (most pairs).
"""

from __future__ import annotations

import pandas as pd

from paper_trade.bridge.models import Bar
from paper_trade.live import kraken, oanda, tradingview


def _from_tv(ticker: str) -> bool:
    return tradingview.enabled() and tradingview.symbol(ticker) is not None


def _from_oanda(ticker: str) -> bool:
    return oanda.enabled() and oanda.instrument(ticker) is not None


def _from_kraken(ticker: str) -> bool:
    return kraken.pair(ticker) is not None


def source(ticker: str) -> str:
    """Where this ticker's live prices come from first: tradingview, oanda, kraken, or none."""
    return ("tradingview" if _from_tv(ticker) else "oanda" if _from_oanda(ticker)
            else "kraken" if _from_kraken(ticker) else "none")


def _first(attempts):
    for attempt in attempts:
        try:
            value = attempt()
        except Exception:
            continue                            # try the next source
        if value is not None and not (isinstance(value, pd.DataFrame) and value.empty):
            return value
    return None


def record_minute(stamp: str) -> None:
    """Save this minute's TradingView candle of every pair (called once per loop cycle)."""
    if tradingview.enabled():
        try:
            tradingview.record_minute(stamp)
        except Exception:
            pass                                # a missed minute only leaves a gap in the chart


def latest_prices(tickers) -> dict[str, float | None]:
    """The latest price of each ticker from its best live source; None when no source can be read right now."""
    prices = {}
    for ticker in tickers:
        attempts = []
        if _from_tv(ticker):
            attempts.append(lambda t=ticker: tradingview.latest_price(t))
        if _from_oanda(ticker):
            attempts.append(lambda t=ticker: oanda.latest_price(t))
        if _from_kraken(ticker):
            attempts.append(lambda t=ticker: kraken.latest_price(t))
        prices[ticker] = _first(attempts)
    return prices


def intraday_bars(ticker: str) -> pd.DataFrame | None:
    """Recent M1 bars, indexed by UTC time without a time zone; None when no live source returns any."""
    attempts = []
    if _from_tv(ticker):
        attempts.append(lambda: tradingview.candles(ticker))
    if _from_oanda(ticker):
        attempts.append(lambda: oanda.candles(ticker, "M1", 1500))
    if _from_kraken(ticker):
        attempts.append(lambda: kraken.candles(ticker, 1))
    return _first(attempts)


def daily_range(ticker: str) -> float | None:
    """The 14-day average daily range (ATR) straight from TradingView; None to fall back to daily bars."""
    return _first([lambda: tradingview.daily_atr(ticker)]) if _from_tv(ticker) else None


def hourly_range(ticker: str) -> float | None:
    """The 14-hour average range (ATR on 1-hour candles) from TradingView's analysis; None when it cannot be read now."""
    from paper_trade import assets
    from paper_trade.tvdata import client

    try:
        analysis = client.analysis()["analysis"]
    except Exception:
        return None
    wanted = assets.canonical(ticker)
    frame = next((f for t, f in analysis.items() if assets.canonical(t) == wanted), {}).get("1h", {})
    return float(frame["ATR"]) if frame.get("ATR") else None


def daily_bars(ticker: str, days: int = 60) -> list[Bar]:
    """Completed daily bars (today's unfinished bar is left out), oldest first, for when no ready ATR is available.

    This system's own day-by-day record comes first once it holds enough days for the stop's ATR."""
    from paper_trade import prices
    from paper_trade.bridge import settings as rules

    def recorded() -> pd.DataFrame:
        frame = prices.load_bars(ticker, "2000-01-01").iloc[-days:]
        if len(frame) <= rules.ATR_PERIOD:
            raise ValueError("not enough recorded days yet")
        return frame

    attempts = [recorded]
    if _from_oanda(ticker):
        attempts.append(lambda: oanda.candles(ticker, "D", days).iloc[:-1])
    if _from_kraken(ticker):
        attempts.append(lambda: kraken.candles(ticker, 1440).iloc[-days - 1:-1])
    frame = _first(attempts)
    return [Bar(float(r["High"]), float(r["Low"]), float(r["Close"])) for _, r in frame.iterrows()] if frame is not None else []
