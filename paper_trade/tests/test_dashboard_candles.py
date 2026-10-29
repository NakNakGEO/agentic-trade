import pandas as pd
import pytest

from paper_trade.bridge import settings as rules
from paper_trade.bridge.models import Bar
from paper_trade.dashboard import candles
from paper_trade.live import book as lb
from paper_trade.live import settings, tradingview

MINUTES = pd.DataFrame(
    [(1.1000, 1.1004, 1.0999, 1.1003), (1.1003, 1.1006, 1.1001, 1.1005), (1.1005, 1.1009, 1.1004, 1.1008)],
    columns=["Open", "High", "Low", "Close"],
    index=pd.to_datetime(["2026-10-28 12:58", "2026-10-28 12:59", "2026-10-28 13:00"]))
SNAP = {"fetched_at": "2026-10-28T13:01:12+00:00", "symbols": {
    "EURUSD": {"m1": {"open": 1.1008, "high": 1.1012, "low": 1.1007, "close": 1.1010}, "d1": {"open": 1.0990}}}}


@pytest.fixture(autouse=True)
def recorded(monkeypatch, tmp_path):
    monkeypatch.setattr(tradingview, "candles", lambda ticker: MINUTES)
    monkeypatch.setattr(tradingview, "snapshot", lambda tickers=None: SNAP)
    monkeypatch.setattr(settings, "book_path", lambda account: tmp_path / f"{account.name}.json")
    monkeypatch.setattr(rules, "FIXED_LOT", 0.01)
    book = lb.Book(created="2026-10-28T12:58:30+00:00")
    lb.apply_decision(book, "EURUSD", "2026-10-28", "Sell", 1.1003, [Bar(1.11, 1.09, 1.10)] * 20,
                      "2026-10-28T12:58:30+00:00", {"EURUSD": 1.1003}, average_range=0.005)
    lb.save(book, tmp_path / "gemma_short.json")


def test_minute_candles_end_with_the_bar_forming_now():
    data = candles.chart("EURUSD", "1m")
    assert [b["close"] for b in data["bars"]] == [1.1003, 1.1005, 1.1008, 1.1010]
    assert data["bars"][-1]["time"] == int(pd.Timestamp("2026-10-28 13:01", tz="UTC").timestamp())
    assert data["price"] == 1.1010 and data["change"] == pytest.approx(1.1010 / 1.0990 - 1)


def test_longer_timeframes_merge_minutes_and_the_forming_bar():
    bars = candles.chart("EURUSD", "5m")["bars"]
    assert len(bars) == 2 and bars[0]["open"] == 1.1000 and bars[0]["close"] == 1.1005
    assert bars[1]["high"] == 1.1012 and bars[1]["close"] == 1.1010


def test_open_trades_carry_entry_stop_target_and_result_so_far():
    data = candles.chart("EURUSD", "1m")
    (pos,) = data["positions"]
    assert pos["account"] == "short-term Gemma" and pos["side"] == "short"
    assert pos["stop"] == pytest.approx(1.1003 + 0.01) and pos["target"] == pytest.approx(1.1003 - 0.02)
    assert pos["pnl"] < 0                                    # the price rose against the short
    assert data["trades"][0]["kind"] == "open"


def test_an_unknown_timeframe_falls_back_to_one_minute_and_symbols_are_listed():
    assert candles.chart("EURUSD", "3m")["frame"] == "1m"
    assert {"ticker": "AAPL", "class": "stock", "tv": "NASDAQ:AAPL"} in candles.symbols()
    assert {"ticker": "XAUUSD", "class": "gold", "tv": "OANDA:XAUUSD"} in candles.symbols()


def test_the_chart_says_how_long_tradingview_is_pausing_us(monkeypatch):
    monkeypatch.setattr(candles.tv_guard, "seconds_left", lambda: 321)
    assert candles.chart("EURUSD", "1m")["cooldown"] == 321


def test_a_delayed_stock_says_how_late_it_is_and_merges_by_its_own_bar_minute(monkeypatch):
    import time as clock

    bar_start = int(pd.Timestamp("2026-10-28 13:00", tz="UTC").timestamp())
    monkeypatch.setattr(clock, "time", lambda: bar_start + 15 * 60 + 20)
    monkeypatch.setattr(candles.time, "time", lambda: bar_start + 15 * 60 + 20)
    snap = {"fetched_at": "2026-10-28T13:15:20+00:00", "symbols": {"EURUSD": {"mode": "delayed_streaming_900", "d1": {"open": 1.0990},
            "m1": {"open": 1.1008, "high": 1.1012, "low": 1.1007, "close": 1.1010, "time": bar_start}}}}
    monkeypatch.setattr(tradingview, "snapshot", lambda tickers=None: snap)
    data = candles.chart("EURUSD", "1m")
    assert data["delay"] == 15
    assert data["bars"][-1]["time"] == bar_start and data["bars"][-1]["close"] == 1.1010     # its own minute, not the fetch's
