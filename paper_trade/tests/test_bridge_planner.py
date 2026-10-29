from datetime import datetime, timezone

import pytest
from fake_broker import SYMBOLS, FakeBroker, position

from paper_trade import config
from paper_trade.bridge import RealAccountError, build_session, settings
from paper_trade.bridge.models import SendResult
from paper_trade.simulator import Decision

pytestmark = pytest.mark.usefixtures("risk_sized")

NOW = datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc)
TODAY = "2026-10-28"


def plan_for(broker, *decisions, now=NOW):
    return build_session(broker, list(decisions), now).plans


def gold(rating, date=TODAY):
    return Decision("XAUUSD", date, rating)


def test_a_sell_opens_a_short_with_its_stop_above_and_target_below_the_entry():
    [plan] = plan_for(FakeBroker(), gold("Sell"))
    step = plan.steps[0]
    assert plan.action == "open" and plan.ready
    assert step.request.side == "sell" and step.request.symbol == "XAUUSDm"
    assert step.request.sl > step.request.price > step.request.tp
    assert step.reward_risk == pytest.approx(settings.REWARD_RISK)


def test_a_buy_opens_a_long_with_its_stop_below_the_entry():
    [plan] = plan_for(FakeBroker(), gold("Buy"))
    request = plan.steps[0].request
    assert request.side == "buy" and request.sl < request.price < request.tp


def test_every_order_has_a_stop_and_risks_no_more_than_two_percent():
    for rating in ("Buy", "Overweight", "Underweight", "Sell"):
        [plan] = plan_for(FakeBroker(), gold(rating))
        step = plan.steps[0]
        assert step.request.sl != 0
        assert step.risk_fraction <= settings.RISK_FRACTION + 1e-9


def test_a_buy_risks_the_full_budget_and_an_overweight_three_quarters_of_it():
    full = plan_for(FakeBroker(), gold("Buy"))[0].steps[0]
    part = plan_for(FakeBroker(), gold("Overweight"))[0].steps[0]
    assert full.request.volume == pytest.approx(0.05)       # 200 budget / 4,000 lost per lot
    assert part.request.volume == pytest.approx(0.03)       # 150 budget rounds down from 0.0375


def test_hold_changes_nothing_even_with_a_position_open():
    [plan] = plan_for(FakeBroker(positions=[position(side="buy")]), gold("Hold"))
    assert plan.action == "keep" and plan.steps == []


def test_a_buy_while_already_long_does_not_add():
    [plan] = plan_for(FakeBroker(positions=[position(side="buy")]), gold("Buy"))
    assert plan.action == "keep" and plan.steps == []


def test_a_sell_while_long_closes_the_long_then_opens_the_short():
    [plan] = plan_for(FakeBroker(positions=[position(side="buy", ticket=7)]), gold("Sell"))
    assert plan.action == "flip"
    close, opened = plan.steps
    assert close.kind == "close" and close.request.side == "sell" and close.request.position == 7
    assert opened.kind == "open" and opened.request.side == "sell" and opened.request.position is None


def test_a_position_opened_by_hand_is_never_closed_by_the_bridge():
    manual = position(side="buy", magic=0)
    [plan] = plan_for(FakeBroker(positions=[manual]), gold("Sell"))
    assert [s.kind for s in plan.steps] == ["open"]


def test_a_real_account_is_refused():
    with pytest.raises(RealAccountError):
        build_session(FakeBroker(demo=False), [gold("Sell")], NOW)


def test_a_decision_from_a_past_dated_run_is_never_traded():
    [plan] = plan_for(FakeBroker(), gold("Sell", date="2026-10-20"))
    assert plan.steps == [] and "days old" in plan.notes[0]


def test_a_decision_from_yesterday_is_still_fresh():
    [plan] = plan_for(FakeBroker(), gold("Sell", date="2026-10-27"))
    assert plan.action == "open"


def test_only_the_newest_decision_for_an_asset_counts():
    plans = plan_for(FakeBroker(), gold("Sell", date="2026-10-20"), gold("Buy", date=TODAY))
    assert len(plans) == 1 and plans[0].rating == "Buy"


def test_a_pair_missing_from_the_account_is_skipped_with_a_hint():
    [plan] = plan_for(FakeBroker(names=["EURUSDm"]), gold("Sell"))
    assert plan.steps == [] and "no matching symbol" in plan.notes[0]


def test_an_account_too_small_for_the_minimum_lot_is_skipped_not_over_risked():
    [plan] = plan_for(FakeBroker(equity=100.0), gold("Sell"))
    assert plan.steps == [] and "smallest lot" in plan.notes[0]


def test_a_symbol_that_forbids_shorting_is_skipped():
    [plan] = plan_for(FakeBroker(short_allowed=False), gold("Sell"))
    assert plan.steps == [] and "short" in plan.notes[0]


def test_a_stop_cannot_be_placed_without_enough_daily_history():
    class ShortHistory(FakeBroker):
        def daily_bars(self, symbol, count):
            return super().daily_bars(symbol, 5)

    [plan] = plan_for(ShortHistory(), gold("Sell"))
    assert plan.steps == [] and "daily bars" in plan.notes[0]


def test_a_reward_below_the_minimum_ratio_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "REWARD_RISK", 1.0)
    [plan] = plan_for(FakeBroker(), gold("Sell"))
    assert plan.steps == [] and "reward:risk" in plan.notes[0]


def test_open_risk_across_pairs_is_capped(monkeypatch):
    monkeypatch.setattr(settings, "MAX_TOTAL_RISK", 0.03)       # room for one 2% trade, not two
    first, second = plan_for(FakeBroker(), gold("Sell"), Decision("EURUSD", TODAY, "Sell"))
    assert first.action == "open"
    assert second.steps == [] and "total open risk" in second.notes[0]


def test_the_number_of_open_positions_is_capped(monkeypatch):
    monkeypatch.setattr(settings, "MAX_OPEN_POSITIONS", 1)
    first, second = plan_for(FakeBroker(), gold("Sell"), Decision("EURUSD", TODAY, "Sell"))
    assert first.action == "open" and second.steps == [] and "open positions" in second.notes[0]


def test_three_positions_on_one_symbol_is_the_limit():
    crowded = [position(side="buy", magic=0, ticket=n) for n in range(settings.MAX_POSITIONS_PER_SYMBOL)]
    [plan] = plan_for(FakeBroker(positions=crowded), gold("Sell"))
    assert plan.steps == [] and "positions already open" in plan.notes[0]


def test_a_wide_gold_spread_is_a_warning_not_a_block():
    [plan] = plan_for(FakeBroker(spread=0.5), gold("Sell"))         # 50 points against a 30-point limit
    assert plan.ready and any("spread" in w for w in plan.warnings)


def test_a_tight_gold_spread_has_no_warning():
    [plan] = plan_for(FakeBroker(spread=0.1), gold("Sell"))
    assert plan.warnings == []


def test_the_low_liquidity_window_is_a_warning():
    late = datetime(2026, 10, 28, 22, 0, tzinfo=timezone.utc)
    [plan] = plan_for(FakeBroker(), Decision("XAUUSD", TODAY, "Sell"), now=late)
    assert any("low-liquidity" in w for w in plan.warnings)


def test_an_order_the_server_would_refuse_is_not_ready():
    broker = FakeBroker()
    broker.check_result = SendResult(False, "Market closed", 10018)
    [plan] = plan_for(broker, gold("Sell"))
    assert plan.steps and not plan.ready


def test_the_dry_run_asks_the_server_but_sends_nothing():
    broker = FakeBroker()
    plan_for(broker, gold("Sell"))
    assert len(broker.checked) == 1 and broker.sent == []


def test_all_seven_pairs_get_a_plan_in_one_run():
    decisions = [Decision(t, TODAY, "Sell") for t in config.UNIVERSE]
    plans = plan_for(FakeBroker(), *decisions)
    assert [p.symbol for p in plans] == list(SYMBOLS)
    opened = [p for p in plans if p.action == "open"]
    assert len(opened) == 5            # the 10% open-risk cap fits five 2% trades, so the last two wait
    assert all(p.steps[0].request.sl for p in opened)


# --- fixed lot (the shipped default): every order is 0.01 lot, the stop is still mandatory ------------------------

@pytest.fixture
def fixed_lot(monkeypatch):
    monkeypatch.setattr(settings, "FIXED_LOT", 0.01)


def test_a_fixed_lot_is_used_whatever_the_rating(fixed_lot):
    for rating in ("Buy", "Overweight", "Underweight", "Sell"):
        [plan] = plan_for(FakeBroker(), gold(rating))
        assert plan.steps[0].request.volume == pytest.approx(0.01)


def test_a_fixed_lot_still_has_a_stop_and_a_take_profit(fixed_lot):
    [plan] = plan_for(FakeBroker(), gold("Sell"))
    request = plan.steps[0].request
    assert request.sl > request.price > request.tp and plan.ready


def test_a_fixed_lot_that_risks_more_than_two_percent_is_allowed_but_warned(fixed_lot):
    [plan] = plan_for(FakeBroker(equity=100.0), gold("Sell"))       # 40-away stop x 0.01 lot loses 40 = 40% of 100
    assert plan.action == "open" and any("above the 2% rule" in w for w in plan.warnings)


def test_a_fixed_lot_below_the_symbols_minimum_is_skipped(fixed_lot):
    [plan] = plan_for(FakeBroker(volume_min=0.1), gold("Sell"))
    assert plan.steps == [] and "minimum" in plan.notes[0]


def test_with_a_fixed_lot_the_wider_open_risk_cap_applies(fixed_lot, monkeypatch):
    monkeypatch.setattr(settings, "FIXED_LOT_MAX_TOTAL_RISK", 0.5)
    plans = plan_for(FakeBroker(equity=100.0), *[Decision(t, TODAY, "Sell") for t in ("XAUUSD", "EURUSD", "GBPUSD")])
    assert [p.action for p in plans] == ["open", "skip", "skip"]    # each loses 40 at its stop: only one fits under 50


def test_the_runs_own_pair_order_decides_who_gets_the_open_risk_first(monkeypatch):
    monkeypatch.setattr(settings, "MAX_OPEN_POSITIONS", 1)
    decisions = [Decision("EURUSD", TODAY, "Sell"), Decision("XAUUSD", TODAY, "Sell")]
    first, second = plan_for_order(decisions, ["XAUUSD", "EURUSD"])
    assert (first.ticker, first.action, second.action) == ("XAUUSD", "open", "skip")


def plan_for_order(decisions, order):
    return build_session(FakeBroker(), decisions, NOW, order=order).plans
