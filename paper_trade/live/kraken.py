"""Kraken's free public market data for the live book: live forex, gold (through PAXG) and crypto, with real M1 candles.

No key or account is needed; this is Kraken's documented public API. Gold uses PAX Gold (PAXG), a token backed by one
troy ounce of gold per token, so it follows spot gold live (usually within a few dollars). Every failure raises, and the
callers try their next live source.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

import pandas as pd

from paper_trade import assets

HOST = "https://api.kraken.com/0/public"
TIMEOUT_SECONDS = 15
PAIRS = {"GC=F": "PAXGUSD", "BTC-USD": "XBTUSD", "ETH-USD": "ETHUSD",       # canonical ticker -> Kraken pair
         "EURUSD=X": "EURUSD", "GBPUSD=X": "GBPUSD", "AUDUSD=X": "AUDUSD", "USDCAD=X": "USDCAD", "USDCHF=X": "USDCHF"}


def pair(ticker: str) -> str | None:
    """Kraken's pair for a ticker, or None when this feed does not cover it."""
    return PAIRS.get(assets.canonical(ticker))


def _get(path: str, params: dict) -> dict:
    request = urllib.request.Request(f"{HOST}/{path}?{urllib.parse.urlencode(params)}",
                                     headers={"User-Agent": "paper-trade-monitor"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
        payload = json.loads(reply.read().decode("utf-8"))
    if payload.get("error"):
        raise RuntimeError("Kraken: " + "; ".join(payload["error"]))
    return payload["result"]


def parse_ticker(result: dict) -> float:
    """The mid of the best bid and ask from a Ticker reply (its one pair, whatever Kraken names it)."""
    quote = next(iter(result.values()))
    return (float(quote["a"][0]) + float(quote["b"][0])) / 2


def parse_ohlc(result: dict) -> pd.DataFrame:
    """An OHLC reply as Open/High/Low/Close rows indexed by UTC time without a time zone."""
    rows = next(v for k, v in result.items() if k != "last")
    frame = pd.DataFrame([(pd.Timestamp(int(r[0]), unit="s"), float(r[1]), float(r[2]), float(r[3]), float(r[4]))
                          for r in rows], columns=["time", "Open", "High", "Low", "Close"])
    return frame.set_index("time")


def latest_price(ticker: str) -> float:
    return parse_ticker(_get("Ticker", {"pair": pair(ticker)}))


def candles(ticker: str, minutes: int = 1) -> pd.DataFrame:
    """Recent candles of ``minutes`` length (1 = M1, 1440 = daily); Kraken returns up to 720 of them."""
    if pair(ticker) is None:
        raise ValueError(f"Kraken feed does not cover {ticker}")
    return parse_ohlc(_get("OHLC", {"pair": pair(ticker), "interval": minutes}))
