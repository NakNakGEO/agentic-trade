import pytest
from fake_broker import FakeBroker

from paper_trade.bridge import spreads


def rows_for(broker, tickers, looks=1):
    return {r.ticker: r for r in spreads.measure(broker, tickers, looks, interval=0, sleep=lambda s: None)}


def test_a_tight_spread_against_the_daily_range_is_ok():
    rows = rows_for(FakeBroker(spread=0.1, daily_range=20.0), ["XAUUSD", "EURUSD"])
    assert rows["EURUSD"].verdict == "OK"
    assert rows["XAUUSD"].verdict == "OK"       # 10 points, under gold's 30-point limit


def test_a_spread_that_is_a_big_share_of_the_range_is_wide():
    # daily range 2 -> stop distance 4 -> 15% is 0.6; a spread of 1.0 is over it
    rows = rows_for(FakeBroker(spread=1.0, daily_range=2.0), ["EURUSD"])
    assert rows["EURUSD"].verdict == "WIDE"


def test_gold_has_its_fixed_point_limit_whatever_the_range():
    rows = rows_for(FakeBroker(spread=0.5, daily_range=200.0), ["XAUUSD"])      # 50 points
    assert rows["XAUUSD"].verdict == "WIDE"


def test_the_median_and_worst_come_from_every_look():
    widths = iter([0.1, 0.1, 0.9])

    class Moving(FakeBroker):
        def quote(self, symbol):
            self.spread = next(widths)
            return super().quote(symbol)

    row = rows_for(Moving(daily_range=20.0), ["EURUSD"], looks=3)["EURUSD"]
    assert row.median == pytest.approx(0.1) and max(row.samples) == pytest.approx(0.9)
    assert len(row.samples) == 3


def test_a_pair_missing_from_the_account_is_reported_not_crashed():
    rows = rows_for(FakeBroker(names=["EURUSDm"]), ["EURUSD", "GBPUSD"])
    assert rows["GBPUSD"].verdict == "not on this account" and rows["EURUSD"].verdict == "OK"


def test_the_table_lists_every_pair_with_its_verdict():
    text = spreads.render(list(rows_for(FakeBroker(names=["EURUSDm"]), ["EURUSD", "GBPUSD"]).values()), 1)
    assert "EURUSD" in text and "GBPUSD" in text and "not on this account" in text and "OK" in text
