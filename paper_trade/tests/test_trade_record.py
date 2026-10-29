import pandas as pd
import pytest

from paper_trade.simulator import Decision, simulate_sleeve
from paper_trade.trade_record import record

DAYS = pd.bdate_range("2026-01-05", periods=10)


def closes(*values):
    return pd.Series(values, index=DAYS[: len(values)], dtype=float)


def run(decisions, series, cash=1_000, bps=0):
    return simulate_sleeve("X", decisions, series, cash=cash, cost_bps=bps)


def test_a_round_trip_that_made_money_is_a_win_with_the_right_numbers():
    # buy 1,000 at 100 -> 10 shares; sell all at 120 -> 1,200
    sleeve = run([Decision("X", "2026-01-05", "Buy"), Decision("X", "2026-01-08", "Sell")],
                 closes(100, 100, 110, 110, 120, 120))
    sell = [t for t in sleeve.trades if t.pnl is not None][0]
    assert sell.pnl == pytest.approx(200)
    assert (sell.entry_date, sell.entry_price, sell.price) == ("2026-01-06", pytest.approx(100), 120)
    r = record(sleeve)
    assert (r["closed"], r["wins"], r["losses"], r["win_rate"]) == (1, 1, 0, 1.0)
    assert r["open"] is False and r["open_pnl"] == 0


def test_selling_below_cost_is_a_loss():
    sleeve = run([Decision("X", "2026-01-05", "Buy"), Decision("X", "2026-01-08", "Sell")],
                 closes(100, 100, 95, 90, 80, 80))
    r = record(sleeve)
    assert (r["wins"], r["losses"]) == (0, 1)
    assert r["realized"] == pytest.approx(-200)


def test_trimming_realises_only_the_part_sold_and_keeps_the_rest_open():
    # buy 10 shares at 100, price 120, Underweight trims to 25% -> sells 7.5 shares at 120
    sleeve = run([Decision("X", "2026-01-05", "Buy"), Decision("X", "2026-01-08", "Underweight")],
                 closes(100, 100, 110, 120, 120, 130))
    r = record(sleeve)
    assert r["closed"] == 1 and r["realized"] == pytest.approx(7.5 * 20)
    assert r["open"] is True and r["open_shares"] == pytest.approx(2.5)
    assert r["open_entry_price"] == pytest.approx(100)
    assert r["open_pnl"] == pytest.approx(2.5 * (130 - 100))


def test_fees_reduce_the_result_of_a_trade():
    series = closes(100, 100, 100, 100, 101, 101)
    free = record(run([Decision("X", "2026-01-05", "Buy"), Decision("X", "2026-01-08", "Sell")], series, bps=0))
    paid = record(run([Decision("X", "2026-01-05", "Buy"), Decision("X", "2026-01-08", "Sell")], series, bps=50))
    assert paid["realized"] < free["realized"]
    assert free["realized"] > 0 > paid["realized"] or paid["realized"] < free["realized"] - 5


def test_open_position_is_floating_profit_and_not_a_closed_trade():
    sleeve = run([Decision("X", "2026-01-05", "Buy")], closes(100, 100, 110, 125))
    r = record(sleeve)
    assert (r["closed"], r["win_rate"], r["fills"]) == (0, None, 1)
    assert r["open"] is True and r["open_since"] == "2026-01-06"
    assert r["open_pnl"] == pytest.approx(10 * 25)


def test_wins_and_losses_are_counted_separately_across_several_trades():
    series = closes(100, 100, 120, 120, 90, 90, 80, 80)       # first trade 100 -> 120 wins, second 90 -> 80 loses
    sleeve = run([Decision("X", "2026-01-05", "Buy"), Decision("X", "2026-01-07", "Sell"),
                  Decision("X", "2026-01-09", "Buy"), Decision("X", "2026-01-13", "Sell")], series)
    r = record(sleeve)
    assert (r["closed"], r["wins"], r["losses"]) == (2, 1, 1)
    assert r["win_rate"] == 0.5
