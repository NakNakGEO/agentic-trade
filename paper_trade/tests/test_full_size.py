import pandas as pd
import pytest

from paper_trade import config
from paper_trade.simulator import Decision, simulate_sleeve

DAYS = pd.bdate_range("2026-01-05", periods=6)
FLAT = pd.Series([100.0] * 6, index=DAYS)


def shares_after(rating, bounds):
    sleeve = simulate_sleeve("X", [Decision("X", "2026-01-05", rating)], FLAT, cash=1_000, cost_bps=0, bounds=bounds)
    return sleeve.trades[0].shares


def test_the_full_size_mode_is_offered_and_labelled():
    assert config.ACCOUNT_MODES["full_size"] is config.RATING_BOUNDS_FULL_SIZE
    assert "full size" in config.MODE_LABELS["full_size"]


@pytest.mark.parametrize("rating, base, full", [("Overweight", 7.5, 10.0), ("Underweight", -7.5, -10.0),
                                                ("Buy", 10.0, 10.0), ("Sell", -10.0, -10.0)])
def test_every_directional_call_commits_the_whole_sleeve_in_full_size(rating, base, full):
    assert shares_after(rating, config.RATING_BOUNDS_LONG_SHORT) == pytest.approx(base)
    assert shares_after(rating, config.RATING_BOUNDS_FULL_SIZE) == pytest.approx(full)


def test_hold_still_leaves_the_position_alone():
    sleeve = simulate_sleeve("X", [Decision("X", "2026-01-05", "Hold")], FLAT, cash=1_000, cost_bps=0,
                             bounds=config.RATING_BOUNDS_FULL_SIZE)
    assert sleeve.trades == []
