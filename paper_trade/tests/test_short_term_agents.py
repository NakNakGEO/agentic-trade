import dataclasses

import pandas as pd
import pytest

from paper_trade.live import settings
from paper_trade.tvdata import candles, desk, vendor

ACCOUNT = dataclasses.replace(settings.ACCOUNTS["gemma_short"], call_every_minutes=120)


def minute_frame(start="2026-10-29 08:00", minutes=190):
    """Minute candles that rise one pip a minute: easy to read back as hours."""
    index = pd.date_range(start, periods=minutes, freq="min")
    close = pd.Series([1.1 + 0.0001 * i for i in range(minutes)], index=index)
    return pd.DataFrame({"Open": close - 0.00005, "High": close + 0.0002, "Low": close - 0.0002, "Close": close})


def test_minutes_become_hours_with_the_first_open_the_highest_high_the_lowest_low_and_the_last_close():
    minutes = minute_frame()
    hours = candles.resample(minutes, "1h")
    first = hours.iloc[0]
    assert list(hours.index[:2]) == [pd.Timestamp("2026-10-29 08:00"), pd.Timestamp("2026-10-29 09:00")]
    assert first.Open == pytest.approx(minutes.Open.iloc[0]) and first.Close == pytest.approx(minutes.Close.iloc[59])
    assert first.High == pytest.approx(minutes.High.iloc[:60].max()) and first.Low == pytest.approx(minutes.Low.iloc[:60].min())
    assert len(candles.resample(minutes, "4h")) == 1 and len(candles.resample(minute_frame(minutes=600), "4h")) == 3     # 08:00, 12:00, 16:00
    assert candles.resample(None, "1h").empty and candles.resample(minutes.iloc[:0], "1h").empty


def test_the_tables_name_their_source_mark_the_forming_candle_and_show_only_the_latest_rows():
    text = "\n".join(candles.tables(minute_frame(minutes=60 * 30 + 10)))           # ends ten minutes into an hour
    assert "1-hour candles built from this system's own minute record" in text and "4-hour candles built" in text
    assert text.count("the last candle is still forming") == 2
    assert text.count("\n| 2026-10-") == 24 + 8 and "| Start (UTC) | Open | High | Low | Close | Range |" in text
    assert candles.tables(None) == [] and candles.tables(minute_frame().iloc[:0]) == []


def test_a_candle_that_is_over_is_not_marked_as_forming():
    text = "\n".join(candles.table(minute_frame(minutes=120), "1-hour", "1h", 24, 1))
    assert "still forming" not in text and text.count("\n| 2026-10-29") == 2


def test_only_a_round_based_short_term_account_gets_the_short_term_rules(monkeypatch):
    monkeypatch.delenv("AGENTIC_ACCOUNT", raising=False)
    assert desk.round_account() is None and desk.short_account() is None
    monkeypatch.setenv("AGENTIC_ACCOUNT", "gemma_short")
    assert desk.short_account() is settings.ACCOUNTS["gemma_short"]
    monkeypatch.setenv("AGENTIC_ACCOUNT", "no_such_account")
    assert desk.round_account() is None and desk.short_account() is None
    daily = dataclasses.replace(settings.ACCOUNTS["gemma_short"], style=settings.DAILY)
    monkeypatch.setitem(settings.ACCOUNTS, "daily_test", daily)
    monkeypatch.setenv("AGENTIC_ACCOUNT", "daily_test")
    assert desk.round_account() is daily and desk.short_account() is None


def test_the_short_term_rules_carry_the_accounts_own_numbers_and_ask_for_no_conditions():
    text = desk.short_rules_text(ACCOUNT)
    for part in ("SHORT-TERM", "about 2% of the account", "XAUUSD always trades a fixed 0.01 lot", "1.5 x the 1-hour average true range",
                 "2 x the stop distance", "12 hours after its entry is closed at the market", "asked again every 120 minutes",
                 "do not put conditions on it", "answer Hold", "1-hour and 4-hour candle tables"):
        assert part in text, part
    assert "daily average true range" not in text and "fixed 0.01 lot." in text
    assert "asked again every" not in desk.short_rules_text(dataclasses.replace(ACCOUNT, call_every_minutes=None))


def test_the_instrument_context_ends_with_the_rules_of_the_account_it_is_built_for(monkeypatch):
    monkeypatch.setattr(desk, "memory_text", lambda ticker: " [memory]")
    build = desk.with_rules(lambda ticker, *a, **k: f"context for {ticker}.")
    monkeypatch.delenv("AGENTIC_ACCOUNT", raising=False)
    old = build(ticker="EURUSD")
    assert old.startswith("context for EURUSD.") and "paper account" in old and "SHORT-TERM" not in old and old.endswith("[memory]")
    monkeypatch.setenv("AGENTIC_ACCOUNT", "gemma_short")
    new = build(ticker="EURUSD")
    assert "SHORT-TERM" in new and "fixed 0.01 lot" in new and new.endswith("[memory]")


@pytest.fixture
def prices(monkeypatch):
    monkeypatch.setattr(vendor.daybook, "bars", lambda symbol, start, end: pd.DataFrame())
    monkeypatch.setattr(vendor, "_frames", lambda symbol: ("EURUSD", {}, ""))
    monkeypatch.setattr(vendor, "_minute_candles", lambda symbol: minute_frame())
    monkeypatch.setattr(vendor, "is_live", lambda as_of: True)


def test_the_hourly_tables_are_added_for_a_short_term_account_only(prices, monkeypatch):
    monkeypatch.delenv("AGENTIC_ACCOUNT", raising=False)
    assert "candles built from this system's own minute record" not in vendor.get_stock_data("EURUSD", "2026-10-28", "2026-10-29")
    monkeypatch.setenv("AGENTIC_ACCOUNT", "gemma_short")
    text = vendor.get_stock_data("EURUSD", "2026-10-28", "2026-10-29")
    assert "1-hour candles built from this system's own minute record" in text and "4-hour candles built" in text
    monkeypatch.setattr(vendor, "is_live", lambda as_of: False)
    assert vendor.get_stock_data("EURUSD", "2026-10-28", "2026-10-29").startswith("NO_DATA_AVAILABLE")      # a past date: the record only


def test_missing_minute_candles_never_break_the_prices_tool(monkeypatch):
    from paper_trade.live import tradingview

    def none_yet(ticker):
        raise ValueError("no TradingView candles recorded for it yet")

    monkeypatch.setattr(tradingview, "candles", none_yet)
    assert vendor._minute_candles("EURUSD") is None and vendor._minute_candles("NOT-A-LIVE-PAIR") is None
