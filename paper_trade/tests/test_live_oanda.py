import json

import pytest

from paper_trade.live import feeds, oanda

SAMPLE = {"instrument": "EUR_USD", "granularity": "M1", "candles": [
    {"complete": True, "volume": 12, "time": "2026-10-28T10:15:00.000000000Z",
     "mid": {"o": "1.11234", "h": "1.11240", "l": "1.11230", "c": "1.11236"}},
    {"complete": False, "volume": 3, "time": "2026-10-28T10:16:00.000000000Z",
     "mid": {"o": "1.11236", "h": "1.11250", "l": "1.11235", "c": "1.11248"}}]}


@pytest.fixture(autouse=True)
def without_tradingview(monkeypatch):
    """These tests are about the sources after TradingView, so it is switched off here."""
    monkeypatch.setattr(feeds.tradingview, "enabled", lambda: False)


def test_candle_json_becomes_ohlc_rows_on_utc_time():
    frame = oanda.parse_candles(SAMPLE)
    assert list(frame.columns) == ["Open", "High", "Low", "Close"]
    assert frame.index[0].strftime("%Y-%m-%d %H:%M") == "2026-10-28 10:15" and frame.index.tz is None
    assert frame["High"].iloc[1] == pytest.approx(1.11250)


def test_instrument_names():
    assert [oanda.instrument(t) for t in ("EURUSD", "USDJPY", "XAUUSD", "GC=F", "BTC-USD", "AAPL")] == \
        ["EUR_USD", "USD_JPY", "XAU_USD", "XAU_USD", None, None]


def test_it_is_off_without_a_token(monkeypatch):
    monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
    assert not oanda.enabled() and not feeds._from_oanda("EURUSD")


def test_with_a_token_forex_and_gold_use_oanda_and_crypto_does_not(monkeypatch):
    monkeypatch.setenv("OANDA_API_TOKEN", "x")
    assert feeds._from_oanda("EURUSD") and feeds._from_oanda("XAUUSD") and not feeds._from_oanda("BTC-USD")


def test_a_failing_oanda_falls_back_to_kraken(monkeypatch):
    monkeypatch.setenv("OANDA_API_TOKEN", "x")
    monkeypatch.setattr(oanda, "latest_price", lambda ticker: (_ for _ in ()).throw(OSError("down")))
    monkeypatch.setattr(feeds.kraken, "latest_price", lambda ticker: 1.5)
    assert feeds.latest_prices(["EURUSD"]) == {"EURUSD": 1.5}


def test_oanda_prices_are_used_when_available(monkeypatch):
    monkeypatch.setenv("OANDA_API_TOKEN", "x")
    monkeypatch.setattr(oanda, "latest_price", lambda ticker: 1.2345)
    monkeypatch.setattr(feeds.kraken, "latest_price", lambda ticker: 98.0)        # crypto is not on OANDA
    assert feeds.latest_prices(["EURUSD", "BTC-USD"]) == {"EURUSD": 1.2345, "BTC-USD": 98.0}
