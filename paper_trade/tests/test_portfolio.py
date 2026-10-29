import pandas as pd
import pytest

from paper_trade.portfolio import run_portfolio
from paper_trade.simulator import Decision, total_return

DAYS = pd.bdate_range("2026-01-05", periods=8)


def closes(*values):
    return pd.Series(values, index=DAYS[: len(values)], dtype=float)


def test_sleeves_sum_and_start_at_first_fill():
    result = run_portfolio(
        [Decision("A", "2026-01-05", "Buy")],                    # B never gets a decision
        {"A": closes(100, 100, 110, 121), "B": closes(50, 50, 50, 50)},
        benchmark_closes=closes(10, 10, 11, 12.1),
        starting_cash=20_000,
    )
    assert result.start == DAYS[1]                                # first close after 5 Jan
    # A's sleeve (10k) buys on day 1 and rides +21%; B's sleeve (10k) stays in cash
    assert result.strategy.iloc[-1] == pytest.approx(10_000 * 1.21 / 1.0005 + 10_000, rel=1e-4)
    assert result.exposure.iloc[0] == pytest.approx(0.5, rel=1e-3)
    assert total_return(result.benchmark, 20_000) == pytest.approx(0.21, abs=2e-3)


def test_equal_weight_benchmark_is_sum_of_ticker_buy_and_hold():
    result = run_portfolio(
        [Decision("A", "2026-01-05", "Hold"), Decision("B", "2026-01-05", "Hold")],
        {"A": closes(100, 100, 120), "B": closes(50, 50, 40)},
        benchmark_closes=closes(10, 10, 10),
        starting_cash=2_000,
    )
    assert result.equal_weight.iloc[-1] == pytest.approx(
        1_000 * 1.2 / 1.0005 + 1_000 * 0.8 / 1.0005, rel=1e-6)
    assert result.strategy.iloc[-1] == pytest.approx(2_000)       # all holds: all cash


def test_equal_weight_line_survives_mixed_weekday_and_weekend_calendars():
    weekdays = pd.bdate_range("2026-01-05", periods=10)                 # stocks: no weekend bars
    every_day = pd.date_range("2026-01-05", "2026-01-18", freq="D")     # crypto: every day
    stock = pd.Series(100.0, index=weekdays)
    coin = pd.Series(50.0, index=every_day)
    result = run_portfolio(
        [Decision("STK", "2026-01-04", "Hold"), Decision("BTC", "2026-01-04", "Hold")],
        {"STK": stock, "BTC": coin}, benchmark_closes=stock, starting_cash=2_000)

    # flat prices: two equal sleeves held, so the total must never dip on a weekend
    assert result.equal_weight.min() == pytest.approx(result.equal_weight.max(), rel=1e-9)
    assert result.equal_weight.index.isin(every_day).all() and len(result.equal_weight) >= 13


def test_no_fillable_decision_is_an_error():
    with pytest.raises(ValueError, match="later close"):
        run_portfolio([Decision("A", "2026-01-07", "Buy")], {"A": closes(100, 101, 102)},
                      closes(1, 1, 1), 1_000)
