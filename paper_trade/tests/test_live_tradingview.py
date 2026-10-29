import copy

import pytest

from paper_trade.live import feeds, settings, tradingview

SNAP = {"fetched_at": "2026-10-28T12:41:42+00:00", "symbols": {
    "XAUUSD": {"m1": {"open": 4054.875, "high": 4054.92, "low": 4054.325, "close": 4054.78, "atr": 1.55},
               "d1": {"open": 4061.24, "high": 4070.84, "low": 4028.19, "close": 4054.91, "atr": 71.6}},
    "EURUSD": {"m1": {"open": 1.11319, "high": 1.11322, "low": 1.11316, "close": 1.11322, "atr": 0.0001},
               "d1": {"open": 1.11278, "high": 1.1137, "low": 1.11132, "close": 1.11319, "atr": 0.00569}}}}


@pytest.fixture
def snap(monkeypatch, tmp_path):
    data = copy.deepcopy(SNAP)
    monkeypatch.setattr(tradingview, "snapshot", lambda tickers=None: data)
    monkeypatch.setattr(settings, "TV_CANDLE_DIR", tmp_path)
    monkeypatch.setattr(tradingview, "enabled", lambda: True)
    return data


def test_every_live_pair_has_a_tradingview_symbol():
    assert all(tradingview.symbol(t) for t in settings.TICKERS)
    assert tradingview.symbol("XAUUSD") == "OANDA:XAUUSD|cfd" and tradingview.symbol("NZDUSD") == "OANDA:NZDUSD|forex"


def test_price_and_daily_range_come_from_the_snapshot(snap):
    assert tradingview.latest_price("XAUUSD") == pytest.approx(4054.78)
    assert tradingview.daily_atr("EURUSD") == pytest.approx(0.00569)
    assert feeds.source("XAUUSD") == "tradingview" and feeds.daily_range("XAUUSD") == pytest.approx(71.6)


def test_recorded_minutes_build_m1_candles_and_the_last_write_of_a_minute_wins(snap, tmp_path):
    tradingview.record_minute("2026-10-28T12:41:43+00:00")
    tradingview.record_minute("2026-10-28T12:41:44+00:00")                # the other loop, same snapshot: not written again
    assert len((tmp_path / "XAUUSD.jsonl").read_text().splitlines()) == 1
    snap["fetched_at"], snap["symbols"]["XAUUSD"]["m1"]["close"] = "2026-10-28T12:41:58+00:00", 4055.0
    tradingview.record_minute("2026-10-28T12:41:59+00:00")                # a newer snapshot in the same minute
    snap["fetched_at"], snap["symbols"]["XAUUSD"]["m1"]["close"] = "2026-10-28T12:42:05+00:00", 4056.0
    tradingview.record_minute("2026-10-28T12:42:06+00:00")
    frame = tradingview.candles("XAUUSD")
    assert [i.strftime("%H:%M") for i in frame.index] == ["12:41", "12:42"]
    assert frame["Close"].tolist() == pytest.approx([4055.0, 4056.0])
    assert feeds.intraday_bars("XAUUSD") is not None


def test_a_bad_line_in_the_store_is_skipped():
    frame = tradingview.parse_store(['{"t": "2026-10-28 12:41", "open": 1, "high": 2, "low": 0.5, "close": 1.5}', "{bro"])
    assert len(frame) == 1 and frame["High"].iloc[0] == 2


def test_tradingview_failing_falls_back_to_kraken(monkeypatch):
    monkeypatch.setattr(tradingview, "enabled", lambda: True)
    monkeypatch.setattr(tradingview, "latest_price", lambda t: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
    monkeypatch.setattr(feeds.kraken, "latest_price", lambda t: 4050.0)
    assert feeds.latest_prices(["XAUUSD"]) == {"XAUUSD": 4050.0}


def _epoch(text: str) -> int:
    from datetime import datetime, timezone

    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())


def test_a_finished_minute_replaces_the_partial_copy_saved_while_it_was_forming(snap, tmp_path):
    snap["symbols"]["XAUUSD"]["m1"] = {"open": 4054.0, "high": 4054.1, "low": 4054.0, "close": 4054.05,
                                       "time": _epoch("2026-10-28T12:41:00")}
    snap["symbols"]["XAUUSD"]["m1_prev"] = None
    tradingview.record_minute("2026-10-28T12:41:03+00:00")                   # 12:41 forming, a few seconds old
    snap["fetched_at"] = "2026-10-28T12:42:04+00:00"
    snap["symbols"]["XAUUSD"]["m1_prev"] = {"open": 4054.0, "high": 4055.2, "low": 4053.4, "close": 4054.6,
                                            "time": _epoch("2026-10-28T12:41:00")}
    snap["symbols"]["XAUUSD"]["m1"] = {"open": 4054.6, "high": 4054.7, "low": 4054.6, "close": 4054.7,
                                       "time": _epoch("2026-10-28T12:42:00")}
    tradingview.record_minute("2026-10-28T12:42:05+00:00")
    frame = tradingview.candles("XAUUSD")
    assert [i.strftime("%H:%M") for i in frame.index] == ["12:41", "12:42"]
    assert (frame.loc["2026-10-28 12:41", ["High", "Low", "Close"]] == [4055.2, 4053.4, 4054.6]).all()   # the whole minute


def test_a_delayed_stock_is_stamped_with_its_own_bar_time_and_a_closed_market_adds_nothing(snap, tmp_path):
    snap["symbols"]["AAPL"] = {"mode": "delayed_streaming_900", "m1_prev": None,
                               "m1": {"open": 345.0, "high": 345.2, "low": 344.9, "close": 345.1, "time": _epoch("2026-10-28T12:26:00")}}
    tradingview.record_minute("2026-10-28T12:41:10+00:00")                   # the bar is 15 minutes older than the fetch
    snap["fetched_at"] = "2026-10-28T12:42:10+00:00"
    tradingview.record_minute("2026-10-28T12:42:11+00:00")                   # nothing new has traded
    lines = (tmp_path / "AAPL.jsonl").read_text().splitlines()
    assert len(lines) == 1 and '"t": "2026-10-28 12:26"' in lines[0]
