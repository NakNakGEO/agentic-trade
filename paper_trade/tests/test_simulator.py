import pandas as pd
import pytest

from paper_trade.simulator import (
    Decision,
    buy_and_hold,
    fill_date,
    max_drawdown,
    simulate_sleeve,
    total_return,
)

DAYS = pd.bdate_range("2026-01-05", periods=10)   # Mon 5 Jan .. Fri 16 Jan


def closes(*values):
    return pd.Series(values, index=DAYS[: len(values)], dtype=float)


def test_fill_is_first_close_strictly_after_decision_date():
    series = closes(*range(100, 110))
    assert fill_date(series, "2026-01-05") == DAYS[1]      # same-day close is not tradeable
    assert fill_date(series, "2026-01-10") == DAYS[5]      # a Saturday fills Monday
    assert fill_date(series, "2026-01-16") is None         # nothing after the last close


def test_buy_then_sell_round_trip_with_costs():
    series = closes(100, 100, 110, 110, 120, 120)
    result = simulate_sleeve(
        "X", [Decision("X", "2026-01-05", "Buy"), Decision("X", "2026-01-08", "Sell")],
        series, cash=10_000, cost_bps=10)
    buy, sell = result.trades
    assert buy.fill_date == "2026-01-06" and buy.price == 100
    assert sell.fill_date == "2026-01-09" and sell.price == 120
    assert sell.shares == pytest.approx(-buy.shares)
    # all cash bought at 100, sold at 120, 10 bps each way: ~ +20% less ~20 bps
    assert result.equity.iloc[-1] == pytest.approx(10_000 * 1.2 * (1 - 0.001) / (1 + 0.001), rel=1e-6)
    assert result.exposure.iloc[-1] == 0.0


def test_hold_before_any_position_stays_in_cash():
    result = simulate_sleeve("X", [Decision("X", "2026-01-05", "Hold")],
                             closes(100, 110, 120), cash=5_000)
    assert result.trades == []
    assert (result.equity == 5_000).all()


def test_overweight_takes_partial_position_and_never_overspends():
    result = simulate_sleeve("X", [Decision("X", "2026-01-05", "Overweight")],
                             closes(100, 100, 100), cash=10_000, cost_bps=0)
    assert result.exposure.iloc[-1] == pytest.approx(0.75)
    assert result.equity.iloc[-1] == pytest.approx(10_000)


def test_underweight_from_flat_buys_nothing():
    result = simulate_sleeve("X", [Decision("X", "2026-01-05", "Underweight")],
                             closes(100, 100, 100), cash=1_000, cost_bps=0)
    assert result.trades == [] and (result.equity == 1_000).all()


def test_underweight_trims_a_full_position_to_a_quarter():
    result = simulate_sleeve(
        "X", [Decision("X", "2026-01-05", "Buy"), Decision("X", "2026-01-07", "Underweight")],
        closes(100, 100, 100, 100, 100), cash=1_000, cost_bps=0)
    assert result.exposure.iloc[-1] == pytest.approx(0.25)
    assert result.trades[-1].shares < 0


def test_overweight_never_sells_an_existing_full_position():
    result = simulate_sleeve(
        "X", [Decision("X", "2026-01-05", "Buy"), Decision("X", "2026-01-07", "Overweight")],
        closes(100, 100, 100, 100, 100), cash=1_000, cost_bps=0)
    assert len(result.trades) == 1 and result.exposure.iloc[-1] == pytest.approx(1.0)


def test_full_buy_with_costs_leaves_cash_non_negative():
    result = simulate_sleeve("X", [Decision("X", "2026-01-05", "Buy")],
                             closes(100, 100, 100), cash=10_000, cost_bps=50)
    held = sum(t.shares for t in result.trades) * 100
    assert held + 0 <= 10_000
    assert result.equity.iloc[-1] == pytest.approx(10_000 / 1.005, rel=1e-6)


def test_decision_with_no_later_close_is_pending_not_traded():
    result = simulate_sleeve("X", [Decision("X", "2026-01-06", "Buy")], closes(100, 101), cash=1_000)
    assert result.trades == [] and len(result.pending) == 1


def test_tiny_rebalance_is_skipped():
    series = closes(100, 100, 100.5, 100.5)
    result = simulate_sleeve(
        "X", [Decision("X", "2026-01-05", "Buy"), Decision("X", "2026-01-07", "Buy")],
        series, cash=10_000, cost_bps=0)
    assert len(result.trades) == 1


def test_unknown_rating_is_rejected():
    with pytest.raises(ValueError, match="REVIEW"):
        simulate_sleeve("X", [Decision("X", "2026-01-05", "REVIEW")], closes(100, 101), cash=1)


def test_buy_and_hold_and_drawdown():
    series = closes(100, 120, 90, 110)
    equity = buy_and_hold(series, DAYS[0], 1_000, cost_bps=0)
    assert total_return(equity, 1_000) == pytest.approx(0.10)
    assert max_drawdown(equity) == pytest.approx(90 / 120 - 1)
    assert max_drawdown(closes(1, 2, 3)) == 0.0
