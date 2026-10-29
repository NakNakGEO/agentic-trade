import pandas as pd
import pytest

from paper_trade import config
from paper_trade.compare import agreement, build_comparison, common_cells, direction, render
from paper_trade.simulator import Decision

DAYS = pd.bdate_range("2026-01-05", periods=12)


def closes(*values):
    return pd.Series(values, index=DAYS[: len(values)], dtype=float)


def test_only_decisions_both_runs_made_are_compared():
    a = [Decision("AAPL", "2026-01-05", "Buy"), Decision("AAPL", "2026-01-12", "Sell"), Decision("MSFT", "2026-01-05", "Hold")]
    b = [Decision("AAPL", "2026-01-05", "Overweight"), Decision("MSFT", "2026-01-05", "Buy"), Decision("MSFT", "2026-01-12", "Hold")]
    ca, cb = common_cells(a, b)
    assert [(d.ticker, d.date) for d in ca] == [("AAPL", "2026-01-05"), ("MSFT", "2026-01-05")]
    assert [d.rating for d in ca] == ["Buy", "Hold"] and [d.rating for d in cb] == ["Overweight", "Buy"]


def test_gold_and_forex_names_match_across_runs_whatever_each_run_called_them():
    a = [Decision("XAUUSD", "2026-01-05", "Buy")]
    b = [Decision("GC=F", "2026-01-05", "Sell")]
    ca, cb = common_cells(a, b)
    assert len(ca) == len(cb) == 1 and ca[0].ticker == cb[0].ticker == "GC=F"


def test_agreement_counts_exact_ratings_and_directions():
    da = [Decision("X", "d1", "Buy"), Decision("X", "d2", "Hold"), Decision("X", "d3", "Sell")]
    db = [Decision("X", "d1", "Overweight"), Decision("X", "d2", "Hold"), Decision("X", "d3", "Buy")]
    assert agreement(da, db) == {"cells": 3, "same_rating": 1, "same_direction": 2}
    assert [direction(r) for r in ("Buy", "Overweight", "Hold", "Underweight", "Sell")] == [1, 1, 0, -1, -1]


def test_the_model_that_bought_a_riser_beats_the_one_that_stayed_out():
    rising = closes(100, 100, 110, 120, 130, 140)
    da = [Decision("X", "2026-01-05", "Buy")]
    db = [Decision("X", "2026-01-05", "Hold")]
    c = build_comparison(da, db, {"X": rising}, rising, cash=100)
    assert c.a.strategy.iloc[-1] > 130 and c.b.strategy.iloc[-1] == pytest.approx(100)

    text = render({"Long only": c}, "Local", "API", {"X": "X"}, ("run_a", "run_b"), (1, 1))
    assert "Local ended ahead" in text and "$100 paper account" in text
    assert "cannot show which model trades better" in text


def test_a_tiny_gap_is_called_too_close():
    flat = closes(100, 100, 100, 100)
    c = build_comparison([Decision("X", "2026-01-05", "Buy")], [Decision("X", "2026-01-05", "Hold")],
                         {"X": flat}, flat, cash=100)
    assert "Too close to call" in render({"Long only": c}, "A", "B", {}, ("a", "b"), (1, 1))


def test_shorting_lets_a_bearish_model_profit_from_a_fall_that_long_only_cannot():
    falling = closes(100, 100, 90, 80, 70, 60)
    sell, hold = [Decision("X", "2026-01-05", "Sell")], [Decision("X", "2026-01-05", "Hold")]
    long_only = build_comparison(sell, hold, {"X": falling}, falling, cash=100, bounds=config.RATING_BOUNDS)
    long_short = build_comparison(sell, hold, {"X": falling}, falling, cash=100, bounds=config.RATING_BOUNDS_LONG_SHORT)
    assert long_only.a.strategy.iloc[-1] == pytest.approx(100)          # nothing to sell, so no trade
    assert long_short.a.strategy.iloc[-1] > 130                          # shorted 100 at 100, price now 60

    text = render({"Long and short": long_short, "Long only": long_only}, "Bear", "Hold", {}, ("a", "b"), (1, 1))
    assert text.index("Long and short") < text.index("Long only") and "Bear ended ahead" in text
