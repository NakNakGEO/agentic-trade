"""Dollar-per-day figures for an equity curve. Pure functions."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DailyStats:
    start_value: float
    end_value: float
    calendar_days: int
    per_calendar_day: float        # total profit spread over every calendar day in the window
    best_day: float
    worst_day: float
    up_days: int
    down_days: int

    @property
    def profit(self) -> float:
        return self.end_value - self.start_value


def daily_stats(equity: pd.Series, start_value: float) -> DailyStats:
    """Profit and day-by-day swings. ``start_value`` is the cash put in, not the first mark."""
    if equity.empty:
        raise ValueError("empty equity curve")
    changes = equity.diff().dropna()
    days = max((equity.index[-1] - equity.index[0]).days, 1)
    end = float(equity.iloc[-1])
    return DailyStats(
        start_value=start_value,
        end_value=end,
        calendar_days=days,
        per_calendar_day=(end - start_value) / days,
        best_day=float(changes.max()) if len(changes) else 0.0,
        worst_day=float(changes.min()) if len(changes) else 0.0,
        up_days=int((changes > 0).sum()),
        down_days=int((changes < 0).sum()),
    )
