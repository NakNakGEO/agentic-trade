from datetime import datetime, timezone

import pytest

from paper_trade.daybook import settings as day_settings
from paper_trade.daybook import store
from paper_trade.tvdata import client, profile, vendor

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
ANALYSIS = {"fetched_at": "2026-10-28T12:59:33+00:00", "analysis": {
    "XAUUSD": {
        "1h": {"open": 4050.0, "high": 4056.0, "low": 4049.0, "close": 4052.7, "change": 0.1, "RSI": 55.0, "RSI[1]": 52.0,
               "Recommend.All": 0.42},
        "1d": {"open": 4061.2, "high": 4070.8, "low": 4028.2, "close": 4052.7, "change": -0.19, "RSI": 40.2, "RSI[1]": 38.0,
               "SMA20": 4119.7, "SMA50": 4279.1, "SMA200": 4500.5, "EMA10": 4077.4, "EMA20": 4122.2,
               "MACD.macd": -58.2, "MACD.signal": -54.3, "BB.upper": 4233.8, "BB.lower": 4005.5, "ATR": 71.6,
               "ADX": 26.8, "Recommend.All": -0.40}}}}
RECORD = {"2026-09-14": {"open": 4000.0, "high": 4010.0, "low": 3990.0, "close": 4005.0, "indicators": {"RSI": 61.0}},
          "2026-09-15": {"open": 4005.0, "high": 4030.0, "low": 4001.0, "close": 4025.0,
                         "indicators": {"RSI": 63.5, "MACD.macd": 5.0, "MACD.signal": 3.5}, "ratings": {"1d": 0.3}}}


@pytest.fixture(autouse=True)
def fake_tradingview(monkeypatch, tmp_path):
    monkeypatch.setattr(client, "analysis", lambda: ANALYSIS)
    monkeypatch.setattr(day_settings, "DIR", tmp_path)
    store.save("XAUUSD", RECORD)


def test_the_snapshot_carries_price_indicators_and_tradingviews_rating():
    text = vendor.market_snapshot("XAUUSD", TODAY)
    assert "from TradingView" in text and "4,052.70" in text and "71.6000" in text
    assert "1 day: SELL (-0.40" in text and "1 hour: BUY (+0.42" in text
    assert "record of XAUUSD starts on 2026-09-14" in text


def test_indicators_show_every_timeframe_now_and_the_recorded_daily_values():
    rsi = vendor.get_indicators("XAUUSD", "rsi", TODAY)
    assert "| 1 day | 40.2000 | 38.0000 |" in rsi and "| 1 hour | 55.0000 | 52.0000 |" in rsi
    assert "-3.9000" in vendor.get_indicators("GC=F", "macdh", TODAY)          # the Yahoo name for gold resolves too
    assert vendor.get_indicators("XAUUSD", "kdjk", TODAY).startswith("NO_DATA_AVAILABLE")
    past = vendor.get_indicators("XAUUSD", "rsi", "2026-09-15", 30)
    assert "| 2026-09-15 | 63.5000 |" in past and "Now on TradingView" not in past     # no live numbers for a past date


def test_a_past_date_is_answered_from_the_record_only():
    prices = vendor.get_stock_data("XAUUSD", "2026-09-01", "2026-09-15")
    assert "| 2026-09-15 | 4,005.00 | 4,030.00 | 4,001.00 | 4,025.00 |" in prices and "forming now" not in prices
    snap = vendor.market_snapshot("XAUUSD", "2026-09-15")
    assert "record of 2026-09-15" in snap and "4,025.00" in snap
    assert vendor.market_snapshot("XAUUSD", "2026-08-01").startswith("NO_DATA_AVAILABLE")
    assert vendor.get_stock_data("XAUUSD", "2026-08-01", "2026-08-05").startswith("NO_DATA_AVAILABLE")


def test_live_prices_show_the_record_and_the_bars_forming_now():
    text = vendor.get_stock_data("XAUUSD", "2026-09-01", TODAY)
    assert "| 2026-09-14 |" in text and "| 1 day | 4,061.20 | 4,070.80 | 4,028.20 | 4,052.70 |" in text


def test_closes_for_scoring_come_from_the_record():
    closes = vendor.closes("XAUUSD", "2026-09-01", "2026-09-15")
    assert closes.tolist() == [4005.0]


def test_tradingview_being_unreachable_still_serves_the_record(monkeypatch):
    monkeypatch.setattr(client, "analysis", lambda: (_ for _ in ()).throw(RuntimeError("429")))
    assert "| 2026-09-15 |" in vendor.get_stock_data("XAUUSD", "2026-09-01", TODAY)


def test_the_profile_names_the_instrument_with_the_frameworks_keys(monkeypatch):
    monkeypatch.setattr(client, "screener", lambda: {"rows": {
        "AAPL": {"description": "Apple Inc.", "sector": "Electronic Technology", "industry": "Telecom", "exchange": "NASDAQ"},
        "EURUSD": {"description": "EUR/USD"}}})
    assert profile.company_profile("AAPL") == {"longName": "Apple Inc.", "quoteType": "EQUITY",
                                               "sector": "Electronic Technology", "industry": "Telecom", "exchange": "NASDAQ"}
    assert profile.company_profile("EURUSD=X") == {"longName": "EUR/USD", "quoteType": "CURRENCY"}
    assert profile.company_profile("MSFT") == {}


def test_installing_routes_the_engine_to_this_systems_data_and_adds_the_desk_rules():
    from tradingagents.agents import context, rating, tools
    from tradingagents.dataflows import router
    from tradingagents.graph import trading_graph
    from tradingagents.memory import settlement

    from paper_trade import fundamentals, news
    from paper_trade.tvdata import use_tradingview

    saved = (tools.build_verified_market_snapshot, context.get_company_profile, settlement.get_closes,
             trading_graph.build_instrument_context)
    saved_rating = rating.extract_rating
    try:
        settings = use_tradingview({"data_vendors": {"core_stock_apis": "yfinance"}, "tool_vendors": {"get_news": "yfinance"}})
        vendors = settings["data_vendors"]
        assert {vendors[k] for k in ("core_stock_apis", "technical_indicators", "fundamental_data", "news_data")} == {"tradingview"}
        assert vendors["macro_data"] == "fred" and "get_news" not in settings["tool_vendors"]
        assert router.VENDOR_METHODS["get_fundamentals"]["tradingview"] is fundamentals.get_fundamentals
        assert router.VENDOR_METHODS["get_news"]["tradingview"] is news.get_news
        assert tools.build_verified_market_snapshot is vendor.market_snapshot
        assert context.get_company_profile is profile.company_profile and settlement.get_closes is vendor.closes
        text = trading_graph.build_instrument_context("EURUSD", "stock", {}, None)
        assert "`EURUSD`" in text and "SHORT" in text and "0.01 lot" in text
        use_tradingview({})                                                     # a second install does not wrap twice
        assert trading_graph.build_instrument_context("EURUSD").count("Trading desk rules") == 1
    finally:
        (tools.build_verified_market_snapshot, context.get_company_profile, settlement.get_closes,
         trading_graph.build_instrument_context) = saved
        rating.extract_rating = saved_rating
