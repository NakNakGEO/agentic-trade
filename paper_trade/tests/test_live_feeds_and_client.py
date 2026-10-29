import json
import subprocess
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from paper_trade.live import feeds, settings, tv_guard
from paper_trade.tvdata import client

BARS = pd.DataFrame([(1.0, 1.1, 0.9, 1.05)], columns=["Open", "High", "Low", "Close"], index=[pd.Timestamp("2026-10-29 10:00")])


@pytest.fixture
def no_other_sources(monkeypatch):
    monkeypatch.setattr(feeds.oanda, "enabled", lambda: False)
    monkeypatch.setattr(feeds.kraken, "pair", lambda ticker: None)


def test_a_price_falls_back_to_the_next_source_when_one_fails(monkeypatch):
    monkeypatch.setattr(feeds.tradingview, "enabled", lambda: True)
    monkeypatch.setattr(feeds.oanda, "enabled", lambda: False)
    monkeypatch.setattr(feeds.kraken, "pair", lambda ticker: "XBTUSD" if ticker == "BTC-USD" else None)
    monkeypatch.setattr(feeds.kraken, "latest_price", lambda ticker: 79_000.0)

    def fail(ticker):
        raise RuntimeError("TradingView is cooling down")

    monkeypatch.setattr(feeds.tradingview, "latest_price", fail)
    prices = feeds.latest_prices(["BTC-USD", "EURUSD"])
    assert prices["BTC-USD"] == 79_000.0 and prices["EURUSD"] is None            # no other source covers EURUSD
    assert feeds.source("BTC-USD") == "tradingview" and feeds.source("NOPE") == "none"


def test_minute_bars_come_from_the_first_source_that_has_any(monkeypatch, no_other_sources):
    monkeypatch.setattr(feeds.tradingview, "enabled", lambda: True)
    monkeypatch.setattr(feeds.tradingview, "candles", lambda ticker: pd.DataFrame(columns=list(BARS.columns)))   # empty: try the next
    monkeypatch.setattr(feeds.oanda, "enabled", lambda: True)
    monkeypatch.setattr(feeds.oanda, "instrument", lambda ticker: "EUR_USD")
    monkeypatch.setattr(feeds.oanda, "candles", lambda ticker, granularity, count: BARS)
    assert feeds.intraday_bars("EURUSD") is BARS
    monkeypatch.setattr(feeds.oanda, "enabled", lambda: False)
    assert feeds.intraday_bars("EURUSD") is None


def test_the_hourly_range_is_read_from_the_analysis_by_instrument_whatever_its_label(monkeypatch):
    reply = {"analysis": {"XAUUSD": {"1h": {"ATR": 15.6}, "1d": {"ATR": 70.8}}, "EURUSD": {"1h": {}}}}
    monkeypatch.setattr(client, "analysis", lambda: reply)
    assert feeds.hourly_range("GC=F") == 15.6 and feeds.hourly_range("XAUUSD") == 15.6
    assert feeds.hourly_range("EURUSD") is None and feeds.hourly_range("BTC-USD") is None

    def boom():
        raise RuntimeError("no analysis")

    monkeypatch.setattr(client, "analysis", boom)
    assert feeds.hourly_range("XAUUSD") is None


def test_the_daily_range_comes_from_tradingview_only_when_it_covers_the_pair(monkeypatch):
    monkeypatch.setattr(feeds.tradingview, "enabled", lambda: True)
    monkeypatch.setattr(feeds.tradingview, "daily_atr", lambda ticker: 0.0057)
    assert feeds.daily_range("EURUSD") == 0.0057
    monkeypatch.setattr(feeds.tradingview, "enabled", lambda: False)
    assert feeds.daily_range("EURUSD") is None


def test_daily_bars_use_our_own_record_first_and_else_nothing(monkeypatch, no_other_sources):
    from paper_trade import prices
    frame = pd.DataFrame({"Open": 1.0, "High": 1.1, "Low": 0.9, "Close": 1.0, "Volume": 0.0}, index=pd.date_range("2026-10-01", periods=20))
    monkeypatch.setattr(prices, "load_bars", lambda ticker, start: frame)
    bars = feeds.daily_bars("EURUSD")
    assert len(bars) == 20 and (bars[0].high, bars[0].low, bars[0].close) == (1.1, 0.9, 1.0)
    monkeypatch.setattr(prices, "load_bars", lambda ticker, start: frame.iloc[:5])           # fewer days than the range needs
    assert feeds.daily_bars("EURUSD") == []


# --- the TradingView client ---

def done(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_a_request_succeeds_fails_or_times_out_and_each_is_reported_to_the_guard(monkeypatch):
    seen = []
    monkeypatch.setattr(tv_guard, "check", lambda: seen.append("check"))
    monkeypatch.setattr(tv_guard, "succeeded", lambda: seen.append("ok"))
    monkeypatch.setattr(tv_guard, "failed", lambda: seen.append("failed"))
    monkeypatch.setattr(client.subprocess, "run", lambda *a, **k: done(stdout='noise\n{"fetched_at": "x", "analysis": {}}\n'))
    assert client._run({"mode": "analysis"}) == {"fetched_at": "x", "analysis": {}}
    monkeypatch.setattr(client.subprocess, "run", lambda *a, **k: done(1, stderr="429 Too Many Requests"))
    with pytest.raises(RuntimeError, match="TradingView request failed"):
        client._run({})

    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired("x", 1)

    monkeypatch.setattr(client.subprocess, "run", slow)
    with pytest.raises(RuntimeError, match="timed out waiting its turn"):
        client._run({})
    assert seen == ["check", "ok", "check", "failed", "check"]                       # a timeout is not TradingView refusing us


def test_a_cached_reply_is_reused_refreshed_when_old_and_kept_when_a_refresh_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(client, "CACHE_DIR", tmp_path)
    fetches = []

    def fetch():
        fetches.append(1)
        return {"n": len(fetches)}

    assert client._cached("x", 60, fetch) == {"n": 1} and client._cached("x", 60, fetch) == {"n": 1} and len(fetches) == 1
    old = time.time() - 3600
    import os
    os.utime(tmp_path / "x.json", (old, old))
    assert client._cached("x", 60, fetch) == {"n": 2}

    def broken():
        raise RuntimeError("cooling down")

    os.utime(tmp_path / "x.json", (old, old))
    assert client._cached("x", 60, broken) == {"n": 2}                                # the last reply still answers
    with pytest.raises(RuntimeError):
        client._cached("never-fetched", 60, broken)


def test_the_analysis_and_screener_requests_name_every_live_pair_and_spy(monkeypatch, tmp_path):
    monkeypatch.setattr(client, "CACHE_DIR", tmp_path)
    requests = []
    monkeypatch.setattr(client, "_run", lambda request: requests.append(request) or {"ok": True})
    client.analysis()
    client.screener()
    analysis, screener = requests
    assert analysis["mode"] == "analysis" and analysis["intervals"] == ["1h", "4h", "1d", "1W"]
    assert analysis["symbols"]["EURUSD"] == "OANDA:EURUSD|forex" and "SPY" in analysis["symbols"] and len(analysis["symbols"]) == 14
    assert screener["mode"] == "screener" and "SPY" not in screener["symbols"] and "market_cap_basic" in screener["stock_fields"]
    assert client.cache_path("analysis") == tmp_path / "analysis.json"
