"""OANDA v20 prices for the live book: forex and gold candles and the latest price, no account id needed.

Switched on by ``OANDA_API_TOKEN`` in the project's ``.env`` (a practice-account token is free; ``OANDA_ENV=live`` would
use the live host). OANDA has no crypto, so BTC and ETH keep coming from Kraken. Every failure raises, and the callers fall
back to Kraken, so a bad token or a network problem never stops the live loop.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

import pandas as pd

from paper_trade import assets, config

try:
    from dotenv import load_dotenv

    load_dotenv(config.ROOT / ".env", override=False)
except ImportError:                     # the token can still come from the real environment
    pass

HOSTS = {"practice": "https://api-fxpractice.oanda.com", "live": "https://api-fxtrade.oanda.com"}
TIMEOUT_SECONDS = 20
MAX_COUNT = 5000                        # OANDA's limit per candle request


def enabled() -> bool:
    return bool(os.environ.get("OANDA_API_TOKEN"))


def instrument(ticker: str) -> str | None:
    """OANDA's name for a ticker (EUR_USD, XAU_USD), or None when OANDA does not list it (crypto, stocks)."""
    symbol = assets.canonical(ticker)
    if symbol == "GC=F":
        return "XAU_USD"
    if symbol.endswith("=X") and len(symbol) == 8:
        return f"{symbol[:3]}_{symbol[3:6]}"
    return None


def _get(path: str, params: dict) -> dict:
    host = HOSTS.get(os.environ.get("OANDA_ENV", "practice"), HOSTS["practice"])
    request = urllib.request.Request(f"{host}{path}?{urllib.parse.urlencode(params)}",
                                     headers={"Authorization": f"Bearer {os.environ['OANDA_API_TOKEN']}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
        return json.loads(reply.read().decode("utf-8"))


def parse_candles(payload: dict) -> pd.DataFrame:
    """OANDA's candle JSON as Open/High/Low/Close rows indexed by UTC time without a time zone."""
    rows = [(pd.Timestamp(c["time"]).tz_localize(None), float(c["mid"]["o"]), float(c["mid"]["h"]),
             float(c["mid"]["l"]), float(c["mid"]["c"])) for c in payload.get("candles", []) if "mid" in c]
    frame = pd.DataFrame(rows, columns=["time", "Open", "High", "Low", "Close"])
    return frame.set_index("time")


def candles(ticker: str, granularity: str = "M1", count: int = 240) -> pd.DataFrame:
    name = instrument(ticker)
    if name is None:
        raise ValueError(f"OANDA does not list {ticker}")
    payload = _get(f"/v3/instruments/{name}/candles",
                   {"granularity": granularity, "count": min(count, MAX_COUNT), "price": "M"})
    return parse_candles(payload)


def latest_price(ticker: str) -> float:
    return float(candles(ticker, "M1", 2)["Close"].iloc[-1])
