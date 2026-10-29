import pandas as pd
import pytest

from paper_trade import config
from paper_trade.simulator import Decision, simulate_sleeve
from paper_trade.trade_record import record

DAYS = pd.bdate_range("2026-01-05", periods=12)
LS = config.RATING_BOUNDS_LONG_SHORT


def closes(*values):
    return pd.Series(values, index=DAYS[: len(values)], dtype=float)


def run(decisions, series, cash=1_000, bps=0, bounds=LS):
    return simulate_sleeve("X", decisions, series, cash=cash, cost_bps=bps, bounds=bounds)


def test_a_sell_opens_a_short_and_buying_it_back_cheaper_is_a_win():
    # short 10 shares at 100 (proceeds 1,000), price falls to 80, a Buy covers them and goes long
    sleeve = run([Decision("X", "2026-01-05", "Sell"), Decision("X", "2026-01-08", "Buy")],
                 closes(100, 100, 90, 80, 80, 80))
    short, cover, long_ = sleeve.trades
    assert (short.opens, short.shares) == ("short", pytest.approx(-10))
    assert (cover.closes, cover.shares) == ("short", pytest.approx(10))
    assert cover.pnl == pytest.approx(200)                   # 10 shares x (100 - 80)
    assert (cover.entry_price, cover.entry_date) == (pytest.approx(100), "2026-01-06")
    assert long_.opens == "long" and long_.shares == pytest.approx(15)
    r = record(sleeve)
    assert (r["closed"], r["wins"], r["losses"]) == (1, 1, 0)
    assert r["open_side"] == "long"


def test_a_short_that_is_covered_at_a_higher_price_is_a_loss():
    sleeve = run([Decision("X", "2026-01-05", "Sell"), Decision("X", "2026-01-08", "Buy")],
                 closes(100, 100, 110, 120, 120, 120))
    cover = [t for t in sleeve.trades if t.pnl is not None][0]
    assert cover.pnl == pytest.approx(-200)
    assert record(sleeve)["losses"] == 1


def test_an_open_short_shows_floating_profit_when_the_price_has_fallen():
    sleeve = run([Decision("X", "2026-01-05", "Sell")], closes(100, 100, 90, 85))
    r = record(sleeve)
    assert r["open_side"] == "short" and r["open_shares"] == pytest.approx(-10)
    assert r["open_entry_price"] == pytest.approx(100)
    assert r["open_pnl"] == pytest.approx(10 * (100 - 85))
    assert sleeve.exposure.iloc[-1] < 0                      # exposure is negative while short


def test_underweight_from_flat_shorts_in_long_short_mode_but_buys_nothing_in_long_only():
    series = closes(100, 100, 100, 100)
    assert record(run([Decision("X", "2026-01-05", "Underweight")], series))["open_side"] == "short"
    flat = run([Decision("X", "2026-01-05", "Underweight")], series, bounds=config.RATING_BOUNDS)
    assert flat.trades == [] and flat.shares == 0


def test_hold_keeps_a_short_and_overweight_never_adds_to_one():
    sleeve = run([Decision("X", "2026-01-05", "Sell"), Decision("X", "2026-01-07", "Hold")], closes(100, 100, 100, 100, 100))
    assert len(sleeve.trades) == 1 and sleeve.shares == pytest.approx(-10)
    flipped = run([Decision("X", "2026-01-05", "Sell"), Decision("X", "2026-01-07", "Overweight")], closes(100, 100, 100, 100, 100))
    assert flipped.shares > 0                                  # Overweight turns a short into a 75% long


def test_underweight_adds_to_a_short_up_to_75_percent_and_never_covers():
    sleeve = run([Decision("X", "2026-01-05", "Sell"), Decision("X", "2026-01-07", "Underweight")], closes(100, 100, 100, 100, 100))
    assert sleeve.shares == pytest.approx(-10)                 # already -100%, Underweight (<= -75%) leaves it


def test_total_profit_always_equals_realised_plus_floating_through_longs_shorts_flips_and_fees():
    series = closes(100, 104, 98, 93, 99, 107, 111, 104, 96, 101, 109, 115)
    ratings = ["Buy", "Sell", "Overweight", "Underweight", "Hold", "Sell", "Buy"]
    decisions = [Decision("X", DAYS[i].strftime("%Y-%m-%d"), r) for i, r in enumerate(ratings)]
    sleeve = run(decisions, series, cash=1_000, bps=25)
    r = record(sleeve)
    assert sleeve.equity.iloc[-1] - 1_000 == pytest.approx(r["realized"] + r["open_pnl"])
    assert any(t.opens == "short" for t in sleeve.trades) and any(t.closes == "short" for t in sleeve.trades)


def test_equity_does_not_change_at_the_moment_a_short_is_opened_apart_from_fees():
    sleeve = run([Decision("X", "2026-01-05", "Sell")], closes(100, 100, 100), cash=1_000, bps=10)
    assert sleeve.equity.iloc[1] == pytest.approx(1_000 - 1_000 * 0.001)
