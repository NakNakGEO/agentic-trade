import pandas as pd
import pytest

from paper_trade.stats import daily_stats

DAYS = pd.date_range("2026-01-01", periods=5, freq="D")


def test_profit_per_calendar_day_and_swings():
    equity = pd.Series([100, 102, 101, 105, 104], index=DAYS, dtype=float)
    stats = daily_stats(equity, 100)
    assert stats.profit == pytest.approx(4)
    assert stats.calendar_days == 4
    assert stats.per_calendar_day == pytest.approx(1.0)
    assert (stats.best_day, stats.worst_day) == (4, -1)
    assert (stats.up_days, stats.down_days) == (2, 2)


def test_loss_is_negative_and_empty_is_rejected():
    stats = daily_stats(pd.Series([100, 90], index=DAYS[:2], dtype=float), 100)
    assert stats.per_calendar_day == pytest.approx(-10)
    with pytest.raises(ValueError):
        daily_stats(pd.Series(dtype=float), 100)
