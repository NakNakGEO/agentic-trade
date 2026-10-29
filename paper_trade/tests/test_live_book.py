import pandas as pd
import pytest

from paper_trade.bridge import settings as rules
from paper_trade.bridge.models import Bar
from paper_trade.live import book as lb
from paper_trade.live import settings

NOW = "2026-10-28T10:00:00+00:00"
BARS = [Bar(101.0, 99.0, 100.0)] * 20            # average range 2 -> stop 4 away, target 8 away


@pytest.fixture(autouse=True)
def fixed_lot(monkeypatch):
    monkeypatch.setattr(rules, "FIXED_LOT", 0.01)
    monkeypatch.setattr(rules, "FIXED_LOT_MAX_TOTAL_RISK", 100.0)       # the cap has its own test


def new_book():
    return lb.Book(created=NOW)


def act(book, ticker, rating, price=100.0, date="2026-10-28", prices=None):
    lb.apply_decision(book, ticker, date, rating, price, BARS, NOW, prices or {ticker: price})


def hourly(*rows):
    """rows of (hour, open, high, low) on 2026-10-28."""
    return pd.DataFrame([(o, h, low, o) for _, o, h, low in rows], columns=["Open", "High", "Low", "Close"],
                        index=[pd.Timestamp(f"2026-10-28 {hour}:00") for hour, *_ in rows])


def test_a_sell_opens_a_short_at_the_live_price_with_the_stop_above_and_target_below():
    book = new_book()
    act(book, "EURUSD", "Sell")
    pos = book.positions["EURUSD"]
    assert pos.side == -1 and pos.entry == 100.0 and pos.stop == pytest.approx(104.0)
    assert pos.target == pytest.approx(100.0 - 4.0 * rules.REWARD_RISK)
    assert book.realized < 0                                           # the entry fee


def test_hold_makes_no_trade_and_a_decision_is_never_acted_on_twice():
    book = new_book()
    act(book, "EURUSD", "Hold")
    act(book, "EURUSD", "Hold")
    assert book.positions == {} and book.applied == ["EURUSD|2026-10-28"]
    act(book, "GBPUSD", "Sell")
    act(book, "GBPUSD", "Sell")
    assert len(book.positions) == 1 and book.applied.count("GBPUSD|2026-10-28") == 1


def test_the_same_call_again_does_not_add_to_the_position():
    book = new_book()
    act(book, "EURUSD", "Sell", date="2026-10-28")
    act(book, "EURUSD", "Underweight", date="2026-10-29", price=99.0)
    assert book.positions["EURUSD"].entry == 100.0 and book.closed == []


def test_an_opposite_call_closes_the_position_at_the_live_price_and_opens_the_other_side():
    book = new_book()
    act(book, "EURUSD", "Sell", date="2026-10-28")
    act(book, "EURUSD", "Buy", date="2026-10-29", price=99.0)
    assert [c.reason for c in book.closed] == ["New call"] and book.closed[0].pnl > 0
    assert book.positions["EURUSD"].side == 1 and book.positions["EURUSD"].entry == 99.0


def test_the_open_risk_cap_skips_a_trade_and_says_why(monkeypatch):
    monkeypatch.setattr(rules, "FIXED_LOT_MAX_TOTAL_RISK", 0.5)        # 50% of $100: one $40 risk fits, two do not
    small = [Bar(1.01, 0.99, 1.0)] * 20                                 # range 0.02 -> stop 0.04 away -> $40 on 1,000 units
    book = new_book()
    for ticker in ("EURUSD", "GBPUSD"):
        lb.apply_decision(book, ticker, "2026-10-28", "Sell", 1.0, small, NOW, {ticker: 1.0})
    assert list(book.positions) == ["EURUSD"] and "open-risk cap" in book.skipped[0]["why"]


def test_a_stop_touched_by_an_hourly_bar_closes_at_the_stop():
    book = new_book()
    act(book, "EURUSD", "Sell")
    lb.step(book, "EURUSD", hourly((11, 100.5, 104.5, 100.0)))        # the high reaches the 104 stop
    assert book.positions == {} and book.closed[0].reason == "Stop-loss"
    assert book.closed[0].exit == pytest.approx(104.0) and book.closed[0].pnl < 0


def test_a_target_touched_by_an_hourly_bar_closes_at_the_target():
    book = new_book()
    act(book, "EURUSD", "Sell")
    lb.step(book, "EURUSD", hourly((11, 99.0, 99.5, 91.0)))
    assert book.closed[0].reason == "Take-profit" and book.closed[0].exit == pytest.approx(92.0)
    assert book.closed[0].pnl > 0


def test_a_bar_touching_both_counts_as_the_stop_and_bars_before_entry_are_ignored():
    book = new_book()
    act(book, "EURUSD", "Sell")
    lb.step(book, "EURUSD", hourly((9, 100.0, 120.0, 80.0)))          # before the 10:00 entry: ignored
    assert "EURUSD" in book.positions
    lb.step(book, "EURUSD", hourly((11, 100.0, 120.0, 80.0)))
    assert book.closed[0].reason == "Stop-loss"


def test_a_gap_through_the_stop_fills_at_the_open():
    book = new_book()
    act(book, "EURUSD", "Sell")
    lb.step(book, "EURUSD", hourly((11, 107.0, 108.0, 106.0)))
    assert book.closed[0].exit == pytest.approx(107.0)


def test_equity_marks_open_positions_at_live_prices():
    book = new_book()
    act(book, "EURUSD", "Sell")
    start = lb.equity(book, {"EURUSD": 100.0})
    assert start == pytest.approx(100.0 + book.realized)
    assert lb.equity(book, {"EURUSD": 99.0}) - start == pytest.approx(1000 * 1.0)      # 1,000 units x 1.0 price move


def test_the_book_survives_a_save_and_load(tmp_path):
    book = new_book()
    act(book, "EURUSD", "Sell")
    lb.step(book, "EURUSD", hourly((11, 100.5, 104.5, 100.0)))
    act(book, "GBPUSD", "Buy")
    lb.record(book, {"GBPUSD": 100.0}, NOW)
    path = tmp_path / "book.json"
    lb.save(book, path)
    again = lb.load(path)
    assert again.applied == book.applied and again.closed == book.closed and again.positions == book.positions
    assert again.history == book.history and again.realized == pytest.approx(book.realized)
    assert lb.load(tmp_path / "missing.json").start_cash == 100.0


def test_history_is_capped(monkeypatch):
    monkeypatch.setattr(settings, "HISTORY_KEEP", 3)
    book = new_book()
    for i in range(6):
        lb.record(book, {}, f"2026-10-28T10:0{i}:00+00:00")
    assert len(book.history) == 3 and book.history[-1]["t"].endswith("10:05:00+00:00")
