import pytest
from fake_broker import bars, position, spec

from paper_trade.bridge import settings, sizing
from paper_trade.bridge.models import Bar


def test_average_range_of_flat_bars_is_their_height():
    assert sizing.atr(bars(20.0)) == pytest.approx(20.0)


def test_a_gap_counts_towards_the_range():
    history = bars(10.0, 15)
    history[-1] = Bar(high=130.0, low=125.0, close=128.0)     # opened far above the previous close of 100
    expected = (13 * 10.0 + 30.0) / 14                        # high - previous close = 30 beats high - low = 5
    assert sizing.atr(history) == pytest.approx(expected)


def test_too_little_history_gives_no_average_range():
    assert sizing.atr(bars(20.0, count=settings.ATR_PERIOD)) is None


def test_stop_distance_is_a_multiple_of_the_range_but_never_inside_the_brokers_minimum():
    assert sizing.stop_distance(spec("X"), 20.0) == pytest.approx(20.0 * settings.ATR_STOP_MULT)
    assert sizing.stop_distance(spec("X", min_stop=100.0), 20.0) == 100.0


def test_lots_are_sized_so_the_stop_loses_the_risk_budget():
    lots = sizing.lots_for_risk(spec("X"), risk_money=200.0, distance=40.0)     # 4,000 lost per lot
    assert lots == pytest.approx(0.05)


def test_lots_round_down_so_the_budget_is_never_exceeded():
    assert sizing.lots_for_risk(spec("X"), risk_money=190.0, distance=40.0) == pytest.approx(0.04)


def test_no_trade_when_the_smallest_lot_would_lose_more_than_the_budget():
    assert sizing.lots_for_risk(spec("X"), risk_money=2.0, distance=40.0) == 0.0


def test_lots_are_capped_at_the_brokers_maximum():
    assert sizing.lots_for_risk(spec("X"), risk_money=1e9, distance=40.0) == 100.0


def test_a_long_has_its_stop_below_and_target_above_the_entry():
    stop, target = sizing.levels(spec("X"), "buy", entry=2_000.0, distance=40.0)
    assert (stop, target) == (1_960.0, 2_000.0 + 40.0 * settings.REWARD_RISK)


def test_a_short_has_its_stop_above_and_target_below_the_entry():
    stop, target = sizing.levels(spec("X"), "sell", entry=2_000.0, distance=40.0)
    assert (stop, target) == (2_040.0, 2_000.0 - 40.0 * settings.REWARD_RISK)


def test_open_risk_is_the_loss_at_the_stop_and_an_unprotected_position_is_charged_a_full_budget():
    assert sizing.position_risk(spec("X"), position(volume=0.05, price=2_000.0, sl=1_960.0), 10_000.0) == \
        pytest.approx(200.0)
    assert sizing.position_risk(spec("X"), position(sl=0.0), 10_000.0) == pytest.approx(
        10_000.0 * settings.RISK_FRACTION)
