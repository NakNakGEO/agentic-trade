import pandas as pd
import pytest

from paper_trade.bridge import settings as rules
from paper_trade.dashboard import live_view, market
from paper_trade.live import book as lb
from paper_trade.live import settings, tradingview

NOW = "2026-10-29T10:00:00+00:00"
SNAP = {"fetched_at": "2026-10-29T10:00:30+00:00", "symbols": {
    "EURUSD": {"m1": {"close": 1.1, "time": 1793268000}, "d1": {"open": 1.0}}, "XAUUSD": {"m1": {}, "d1": {}}}}


@pytest.fixture(autouse=True)
def fresh_cache():
    market._cache.update(at=0.0, key=None, rows=[])
    live_view._cache.clear()


def test_a_quote_has_price_change_sparkline_and_the_bars_own_age(monkeypatch):
    monkeypatch.setattr(tradingview, "snapshot", lambda tickers=None: SNAP)
    monkeypatch.setattr(tradingview, "candles", lambda ticker: pd.DataFrame({"Close": range(300)}))
    q = market.quote("EURUSD", pd.Timestamp("2026-10-29 10:05", tz="UTC"))
    assert q["price"] == 1.1 and q["change"] == pytest.approx(0.1) and len(q["spark"]) == 60 and q["source"] == "TradingView"
    assert q["lag_minutes"] == pytest.approx(5.0, abs=1.0) and q["symbol"] == "EURUSD=X" and q["class"] == "forex"


def test_a_quote_explains_why_it_has_no_price(monkeypatch):
    monkeypatch.setattr(tradingview, "snapshot", lambda tickers=None: SNAP)
    assert "no TradingView symbol" in market.quote("SPX500")["error"]
    assert "market closed" in market.quote("XAUUSD")["error"]
    monkeypatch.setattr(tradingview, "candles", lambda ticker: (_ for _ in ()).throw(ValueError("none yet")))
    assert market.quote("EURUSD")["spark"] == [1.1]                                    # no record yet: a single point


def test_when_tradingview_refuses_the_last_quote_is_shown_and_with_nothing_an_error(monkeypatch):
    def refused(tickers=None):
        raise RuntimeError("cooling down")

    monkeypatch.setattr(tradingview, "snapshot", refused)
    monkeypatch.setattr(tradingview, "last_snapshot", lambda: SNAP)
    monkeypatch.setattr(tradingview, "candles", lambda ticker: pd.DataFrame({"Close": [1.0, 1.1]}))
    assert market.quote("EURUSD")["price"] == 1.1
    monkeypatch.setattr(tradingview, "last_snapshot", lambda: None)
    assert market.quote("EURUSD")["error"].startswith("RuntimeError")


def test_quotes_are_cached_briefly_per_set_of_tickers(monkeypatch):
    calls = []
    monkeypatch.setattr(market, "quote", lambda ticker: calls.append(ticker) or {"ticker": ticker})
    assert [q["ticker"] for q in market.live_quotes(["EURUSD", "XAUUSD"])] == ["EURUSD", "XAUUSD"]
    market.live_quotes(["EURUSD", "XAUUSD"])
    assert calls == ["EURUSD", "XAUUSD"]
    market.live_quotes(["EURUSD"])
    assert calls == ["EURUSD", "XAUUSD", "EURUSD"]
    assert market._downsample(list(range(10)), 20) == list(range(10)) and market._downsample(list(range(100)), 10)[-1] == 99


def started_book():
    book = lb.Book(created=NOW)
    book.history = [{"t": NOW, "equity": 100.0}]
    lb.apply_decision(book, "EURUSD", "2026-10-29", "Sell", 1.1, [], NOW, {"EURUSD": 1.1}, 0.001, settings.SHORT)
    return book


def test_the_live_result_waits_for_a_started_account_and_is_cached_for_a_moment(monkeypatch):
    monkeypatch.setattr(rules, "FIXED_LOT_MAX_TOTAL_RISK", 100.0)
    account = settings.ACCOUNTS["gemma_short"]
    monkeypatch.setattr(live_view.lb, "load", lambda path: lb.Book())
    assert live_view.live_result(account) == "the live account has not started yet"
    book = started_book()
    loads = []
    monkeypatch.setattr(live_view.lb, "load", lambda path: loads.append(1) or book)
    monkeypatch.setattr(live_view, "_close_before", lambda ticker, when: 1.0)
    monkeypatch.setattr(live_view.feeds, "latest_prices", lambda tickers: {t: 1.1 for t in tickers})
    first = live_view.live_result(account)
    assert set(first.sleeves) == set(settings.SHORT_TICKERS) and live_view.live_result(account) is first and len(loads) == 1


def test_the_start_price_is_the_first_recorded_minute_else_the_last_daily_close(monkeypatch):
    when = pd.Timestamp("2026-10-29 07:26:11")
    minutes = pd.DataFrame({"Close": [1.05, 1.06]}, index=pd.to_datetime(["2026-10-29 07:26", "2026-10-29 07:27"]))
    monkeypatch.setattr(tradingview, "candles", lambda ticker: minutes)
    assert live_view._close_before("EURUSD", when) == 1.05
    monkeypatch.setattr(tradingview, "candles", lambda ticker: (_ for _ in ()).throw(ValueError("none")))
    from paper_trade import daybook
    monkeypatch.setattr(daybook, "bars", lambda ticker: pd.DataFrame({"Close": [1.01, 1.02]}, index=pd.to_datetime(["2026-10-27", "2026-10-28"])))
    assert live_view._close_before("EURUSD", when) == 1.02
    monkeypatch.setattr(daybook, "bars", lambda ticker: pd.DataFrame({"Close": []}, index=pd.to_datetime([])))
    assert live_view._close_before("EURUSD", when) is None


def test_the_trade_chart_has_candles_the_open_trade_and_a_marker_line_and_explains_missing_prices(monkeypatch):
    monkeypatch.setattr(rules, "FIXED_LOT_MAX_TOTAL_RISK", 100.0)
    account = settings.ACCOUNTS["gemma_short"]
    book = started_book()
    monkeypatch.setattr(live_view.lb, "load", lambda path: book)
    monkeypatch.setattr(live_view, "_close_before", lambda ticker, when: 1.0)
    monkeypatch.setattr(live_view.feeds, "latest_prices", lambda tickers: {t: 1.0995 for t in tickers})
    monkeypatch.setattr(live_view.feeds, "intraday_bars", lambda ticker: None)
    assert live_view.live_chart(account, "EURUSD") == {"ticker": "EURUSD", "error": "no 1-minute prices right now"}
    index = pd.date_range("2026-10-29 09:58", periods=5, freq="min")
    monkeypatch.setattr(live_view.feeds, "intraday_bars", lambda ticker: pd.DataFrame(
        {"Open": 1.1, "High": 1.1005, "Low": 1.099, "Close": 1.0995}, index=index))
    chart = live_view.live_chart(account, "EURUSD")
    assert len(chart["bars"]) == 5 and chart["open"]["side"] == "short" and chart["open"]["entry_price"] == pytest.approx(1.1)
    assert chart["trades"][0]["side"] == "sell" and chart["trades"][0]["opens"] == "short" and chart["exposure"]
    assert chart["record"]["open"] is True and chart["class"] == "forex"
    assert live_view.blotter_for(account)["positions"][0]["ticker"] == "EURUSD"
