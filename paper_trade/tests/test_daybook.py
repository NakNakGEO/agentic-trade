from datetime import datetime, timezone

import pytest

from paper_trade import daybook, prices
from paper_trade.daybook import settings, store


@pytest.fixture(autouse=True)
def folder(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DIR", tmp_path)
    return tmp_path


def analysis(fetched: str, close: float, high: float = 4070.0) -> dict:
    return {"fetched_at": fetched, "analysis": {"XAUUSD": {
        "1d": {"open": 4060.0, "high": high, "low": 4030.0, "close": close, "volume": 1200, "change": -0.1,
               "RSI": 41.0, "ATR": 71.6, "Recommend.All": -0.4},
        "1h": {"close": close, "Recommend.All": 0.2}}}}


def minute(fetched: str, close: float, high: float, low: float) -> dict:
    return {"fetched_at": fetched, "symbols": {"XAUUSD": {"m1": {"open": close, "high": high, "low": low, "close": close}}}}


def when(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def test_trading_days_follow_tradingviews_daily_bars():
    assert store.trading_day("BTC-USD", when("2026-10-28T23:30:00")) == "2026-10-28"            # crypto: UTC
    assert store.trading_day("XAUUSD", when("2026-10-28T20:30:00")) == "2026-10-28"             # 16:30 New York
    assert store.trading_day("EURUSD", when("2026-10-28T21:30:00")) == "2026-10-29"             # after 17:00 New York
    assert store.trading_day("AAPL", when("2026-10-29T02:00:00")) == "2026-10-28"               # New York date


def test_the_daily_analysis_writes_the_bar_and_every_daily_indicator():
    assert daybook.from_analysis(analysis("2026-10-28T13:00:00+00:00", 4050.0)) == 1
    row = daybook.row("XAUUSD", "2026-10-28")
    assert (row["open"], row["high"], row["low"], row["close"], row["volume"]) == (4060.0, 4070.0, 4030.0, 4050.0, 1200.0)
    assert row["indicators"] == {"RSI": 41.0, "ATR": 71.6, "Recommend.All": -0.4}
    assert row["ratings"] == {"1d": -0.4, "1h": 0.2}


def test_minutes_keep_the_close_current_and_an_older_analysis_does_not_roll_it_back():
    daybook.from_analysis(analysis("2026-10-28T13:00:00+00:00", 4050.0))
    daybook.from_minute(minute("2026-10-28T13:05:00+00:00", 4080.0, 4081.0, 4079.0))
    daybook.from_analysis(analysis("2026-10-28T13:00:00+00:00", 4050.0))      # the same cached analysis again
    row = daybook.row("XAUUSD", "2026-10-28")
    assert row["close"] == 4080.0 and row["high"] == 4081.0 and row["low"] == 4030.0


def test_a_new_day_starts_from_the_first_minute_until_the_analysis_gives_its_real_open():
    daybook.from_minute(minute("2026-10-28T22:01:00+00:00", 4100.0, 4101.0, 4099.0))        # gold's next day
    assert daybook.row("XAUUSD", "2026-10-29")["open"] == 4100.0
    daybook.from_analysis(analysis("2026-10-28T22:10:00+00:00", 4102.0))
    assert daybook.row("XAUUSD", "2026-10-29")["open"] == 4060.0


def test_history_reads_bars_closes_and_indicators_and_prices_drop_the_forming_day():
    for day, close in (("2026-10-26", 4000.0), ("2026-10-27", 4010.0)):
        daybook.from_analysis(analysis(f"{day}T15:00:00+00:00", close))
    assert daybook.first_day("XAUUSD") == "2026-10-26"
    assert daybook.closes("XAUUSD", "2026-10-26", "2026-10-27").tolist() == [4000.0]
    assert daybook.indicator("XAUUSD", "RSI", "2026-10-27", 5).tolist() == [41.0, 41.0]
    assert prices.load_closes("XAUUSD", "2026-10-01").tolist() == [4000.0, 4010.0]
    assert list(prices.load_bars("XAUUSD", "2026-10-01").columns) == ["Open", "High", "Low", "Close"]
    with pytest.raises(ValueError, match="record starts 2026-10-26"):
        prices.load_closes("XAUUSD", "2026-11-01")


def epoch(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())


def test_a_snapshot_is_filed_under_the_daily_bar_tradingview_named_not_the_clocks_day():
    # 21:13 UTC is after 17:00 New York, so the clock says gold's new day has begun; but its TradingView bar (started Tuesday
    # 17:00 New York) has not rolled yet during the daily break, and the row must stay with that bar.
    reply = analysis("2026-10-28T21:13:00+00:00", 4067.0)
    reply["analysis"]["XAUUSD"]["1d"]["time"] = epoch("2026-10-27T21:00:00")
    daybook.from_analysis(reply)
    snap = minute("2026-10-28T21:14:00+00:00", 4067.3, 4067.4, 4067.2)
    snap["symbols"]["XAUUSD"]["d1"] = {"time": epoch("2026-10-27T21:00:00")}
    daybook.from_minute(snap)
    assert daybook.row("XAUUSD", "2026-10-29") == {}                         # nothing filed under the clock's new day
    row = daybook.row("XAUUSD", "2026-10-28")
    assert row["open"] == 4060.0 and row["close"] == 4067.3 and row["indicators"].get("time") is None
    reply["analysis"]["XAUUSD"]["1d"]["time"] = epoch("2026-10-28T21:00:00")  # the bar rolls: the next row begins
    daybook.from_analysis(analysis("2026-10-28T22:05:00+00:00", 4070.0) | {"analysis": {"XAUUSD": {**reply["analysis"]["XAUUSD"], "1d": {**reply["analysis"]["XAUUSD"]["1d"], "close": 4070.0}}}})
    assert daybook.row("XAUUSD", "2026-10-29")["close"] == 4070.0


def test_bar_days_follow_each_markets_own_session():
    assert store.bar_day("EURUSD", epoch("2026-10-28T21:00:00")) == "2026-10-29"      # forex day starts 17:00 New York
    assert store.bar_day("BTC-USD", epoch("2026-10-28T00:00:00")) == "2026-10-28"     # crypto day starts 00:00 UTC
    assert store.bar_day("AAPL", epoch("2026-10-28T13:30:00")) == "2026-10-28"        # stock day starts 09:30 New York
