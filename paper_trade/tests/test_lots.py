import pandas as pd
import pytest

from paper_trade.bridge import settings
from paper_trade.lots import dollars_per_quote, run_lot_portfolio, side_of, units_of
from paper_trade.simulator import Decision

DAYS = pd.bdate_range("2026-01-05", periods=24)


def market(closes, spread=1.0):
    """Daily closes plus bars that open at the previous close and range +/- ``spread`` around the close."""
    series = pd.Series(closes, index=DAYS[: len(closes)], dtype=float)
    frame = pd.DataFrame({"Open": series.shift(1).fillna(series), "High": series + spread, "Low": series - spread,
                          "Close": series})
    return series, frame


def run(decisions, closes, spread=1.0, ticker="EURUSD"):
    series, frame = market(closes, spread)
    bench = pd.Series([100.0] * len(series), index=series.index)
    return run_lot_portfolio(decisions, {ticker: series}, {ticker: frame}, bench, 100.0)


@pytest.fixture(autouse=True)
def fixed(monkeypatch):
    monkeypatch.setattr(settings, "FIXED_LOT", 0.01)
    monkeypatch.setattr(settings, "FIXED_LOT_MAX_TOTAL_RISK", 100.0)       # the cap has its own test


def flat(n=24, price=1.0):
    return [price] * n


def test_the_lot_is_one_hundredth_of_the_contract_and_pairs_convert_to_dollars():
    assert units_of("EURUSD") == pytest.approx(1_000)
    assert units_of("BTC-USD") == pytest.approx(0.01)
    assert dollars_per_quote("EURUSD", 1.1) == 1.0
    assert dollars_per_quote("USDJPY", 157.5) == pytest.approx(1 / 157.5)
    with pytest.raises(ValueError):
        dollars_per_quote("EURJPY", 176.0)


def test_ratings_map_to_a_side():
    assert [side_of(r) for r in ("Buy", "Overweight", "Hold", "Underweight", "Sell")] == [1, 1, 0, -1, -1]


def test_a_buy_that_runs_up_to_its_target_makes_the_target_profit_in_dollars():
    # 14 flat bars with a range of 2 -> ATR 2 -> stop 4 away, target 8 away. Entry at 1.0; price jumps to 20.
    closes = flat(16) + [20.0] * 8
    result = run([Decision("EURUSD", "2026-01-22", "Buy")], closes)       # fills on the 23rd, the 15th bar
    sleeve = result.sleeves["EURUSD"]
    assert [t.opens for t in sleeve.trades if t.opens] == ["long"]
    exits = [t for t in sleeve.trades if t.pnl is not None]
    assert len(exits) == 1 and exits[0].rating == "Take-profit"
    assert exits[0].pnl == pytest.approx(1_000 * 8.0, rel=0.02)          # 1,000 units x 8 price units


def test_a_buy_that_falls_through_its_stop_loses_the_stop_distance():
    closes = flat(16) + [-20.0] * 8
    result = run([Decision("EURUSD", "2026-01-22", "Buy")], closes)
    exits = [t for t in result.sleeves["EURUSD"].trades if t.pnl is not None]
    assert exits[0].rating == "Stop-loss"
    assert exits[0].pnl == pytest.approx(-1_000 * 4.0, rel=0.02)


def test_a_short_profits_when_the_price_falls_to_its_target():
    closes = flat(16, 100.0) + [50.0] * 8
    result = run([Decision("EURUSD", "2026-01-22", "Sell")], closes)
    exits = [t for t in result.sleeves["EURUSD"].trades if t.pnl is not None]
    assert exits[0].rating == "Take-profit" and exits[0].closes == "short" and exits[0].pnl > 0


def test_an_opposite_call_closes_the_position_and_opens_the_other_side():
    decisions = [Decision("EURUSD", "2026-01-22", "Buy"), Decision("EURUSD", "2026-01-27", "Sell")]
    result = run(decisions, flat(24, 100.0), spread=0.5)
    kinds = [(t.closes, t.opens) for t in result.sleeves["EURUSD"].trades]
    assert kinds == [(None, "long"), ("long", None), (None, "short")]


def test_the_same_call_again_does_not_add_to_the_position():
    decisions = [Decision("EURUSD", "2026-01-22", "Buy"), Decision("EURUSD", "2026-01-26", "Overweight")]
    result = run(decisions, flat(24, 100.0), spread=0.5)
    assert sum(1 for t in result.sleeves["EURUSD"].trades if t.opens) == 1


def test_hold_never_trades():
    result = run([Decision("EURUSD", "2026-01-19", "Hold")], flat(24, 100.0))
    assert result.sleeves["EURUSD"].trades == []
    assert result.strategy.iloc[-1] == pytest.approx(100.0)


def test_the_open_risk_cap_skips_a_trade_that_would_not_fit(monkeypatch):
    monkeypatch.setattr(settings, "FIXED_LOT_MAX_TOTAL_RISK", 0.01)            # 1% of $100 = $1; a trade risks far more
    result = run([Decision("EURUSD", "2026-01-22", "Buy")], flat(24, 100.0), spread=1.0)
    assert result.sleeves["EURUSD"].trades == []


def test_pooled_equity_is_the_starting_cash_plus_every_pairs_profit():
    result = run([Decision("EURUSD", "2026-01-22", "Buy")], flat(24, 1.1), spread=0.005)
    assert result.strategy.iloc[-1] == pytest.approx(100.0, abs=0.5)         # prices never moved: only the fees
    sleeve = result.sleeves["EURUSD"]
    assert sleeve.equity.iloc[-1] == pytest.approx(result.strategy.iloc[-1])


def test_an_open_position_reports_its_side_and_unrealised_profit():
    closes = flat(18, 100.0) + [101.0] * 6
    result = run([Decision("EURUSD", "2026-01-22", "Buy")], closes, spread=0.5)
    sleeve = result.sleeves["EURUSD"]
    assert sleeve.shares > 0 and sleeve.open_date is not None
    assert sleeve.shares * sleeve.last_price - sleeve.basis == pytest.approx(
        sleeve.shares * (sleeve.last_price - sleeve.basis / sleeve.shares))


def test_a_usd_based_pair_converts_profit_to_dollars():
    closes = flat(16, 100.0) + [50.0] * 8                    # USDJPY-style pair; a short wins when the price falls
    result = run([Decision("USDJPY", "2026-01-22", "Sell")], closes, ticker="USDJPY")
    exits = [t for t in result.sleeves["USDJPY"].trades if t.pnl is not None]
    assert exits[0].pnl > 0 and exits[0].pnl < 1_000 * 50.0       # 1,000 units x 50 yen is far more than the dollars


def test_the_fixed_lot_account_loads_enough_history_for_its_stop():
    from paper_trade.report import history_start

    assert history_start("2026-09-15", "fixed_lot") == "2026-08-01"          # 45 days: well over 14 trading days
    assert history_start("2026-09-15", "long_short") == "2026-09-08"


def test_pairs_are_tried_in_the_runs_order_so_the_risk_cap_favours_the_first(monkeypatch):
    from paper_trade.lots import in_order

    assert in_order(["BTC-USD", "EURUSD", "GBPUSD"], ["EURUSD", "GBPUSD", "BTC-USD"]) == ["EURUSD", "GBPUSD", "BTC-USD"]
    assert in_order(["BTC-USD", "ZZZ", "EURUSD"], ["EURUSD"]) == ["EURUSD", "BTC-USD", "ZZZ"]

    # each pair risks $20 at its stop and the cap is $30, so only the first one tried can open
    monkeypatch.setattr(settings, "FIXED_LOT_MAX_TOTAL_RISK", 0.3)
    pairs = ("EURUSD", "GBPUSD")
    closes = {t: market(flat(24, 1.0))[0] for t in pairs}
    bars = {t: market(flat(24, 1.0), 0.005)[1] for t in pairs}
    decisions = [Decision(t, "2026-01-22", "Buy") for t in pairs]
    bench = pd.Series([100.0] * 24, index=DAYS[:24])

    def opened(order):
        result = run_lot_portfolio(decisions, closes, bars, bench, 100.0, order=order)
        return sorted(t for t, sleeve in result.sleeves.items() if sleeve.trades)

    assert opened(["EURUSD", "GBPUSD"]) == ["EURUSD"]
    assert opened(["GBPUSD", "EURUSD"]) == ["GBPUSD"]
