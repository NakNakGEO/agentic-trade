import pytest

from paper_trade.bridge import settings as rules
from paper_trade.bridge.models import Bar
from paper_trade.dashboard import live_view
from paper_trade.live import book as lb
from paper_trade.trade_record import record

NOW = "2026-10-28T10:00:00+00:00"
BARS = [Bar(1.01, 0.99, 1.0)] * 20


@pytest.fixture(autouse=True)
def fixed_lot(monkeypatch):
    monkeypatch.setattr(rules, "FIXED_LOT", 0.01)
    monkeypatch.setattr(rules, "FIXED_LOT_MAX_TOTAL_RISK", 100.0)


def book_with_trades():
    book = lb.Book(created=NOW)
    lb.apply_decision(book, "EURUSD", "2026-10-28", "Sell", 1.0, BARS, NOW, {"EURUSD": 1.0})
    lb.apply_decision(book, "GBPUSD", "2026-10-28", "Buy", 1.0, BARS, NOW, {"GBPUSD": 1.0})
    import pandas as pd
    hourly = pd.DataFrame([(1.0, 1.05, 0.99, 1.0)], columns=["Open", "High", "Low", "Close"],
                          index=[pd.Timestamp("2026-10-28 11:00")])
    lb.step(book, "EURUSD", hourly)                                     # the 1.04 stop is hit
    return book


def test_live_runs_are_recognised():
    assert live_view.account_for("live_gemma_short").name == "gemma_short"
    assert live_view.account_for("live_qwen_short").name == "qwen_short"
    assert live_view.account_for("fx9_api") is None


def test_the_live_book_becomes_a_portfolio_with_its_trades_and_open_position():
    book = book_with_trades()
    prices = {"EURUSD": 1.0, "GBPUSD": 1.01}
    result = live_view.build_result(book, prices, {"EURUSD": 1.0, "GBPUSD": 1.0}, (500.0, 505.0))
    assert result.starting_cash == 100.0
    assert result.strategy.iloc[-1] == pytest.approx(lb.equity(book, prices))
    eur, gbp = record(result.sleeves["EURUSD"]), record(result.sleeves["GBPUSD"])
    assert (eur["closed"], eur["losses"], eur["open"]) == (1, 1, False)
    assert gbp["open_side"] == "long" and gbp["open_pnl"] == pytest.approx(1000 * 0.01, rel=0.01)
    assert result.benchmark.iloc[-1] == pytest.approx(101.0)          # SPY 500 -> 505 on $100


def test_the_pairs_add_up_to_the_account_value():
    book = book_with_trades()
    prices = {"EURUSD": 1.0, "GBPUSD": 1.01}
    result = live_view.build_result(book, prices, {}, (None, None))
    total = sum(float(s.equity.iloc[-1]) for s in result.sleeves.values())
    assert total == pytest.approx(lb.equity(book, prices))


def test_each_open_trade_shows_where_its_stop_and_take_profit_are(monkeypatch):
    book = book_with_trades()                                # EURUSD was stopped out, GBPUSD is still open
    monkeypatch.setattr(live_view.lb, "load", lambda path: book)
    levels = live_view.levels_for(live_view.settings.ACCOUNTS["gemma_short"])
    pos = book.positions["GBPUSD"]
    assert list(levels) == ["GBPUSD"]
    win, lose = lb.outcomes(pos)
    assert levels["GBPUSD"] == {"stop": pos.stop, "target": pos.target, "lot": None, "deadline": "",   # the fixed lot, no time limit
                                "win": round(win, 2), "lose": round(lose, 2)}
    assert win > 0 > lose
    assert pos.stop < pos.entry < pos.target                 # a long: the stop is below the entry, the target above


def test_a_call_the_account_could_not_open_is_explained_in_plain_words():
    why = "open-risk cap: this trade risks $143.20 with $45.30 already at risk"
    text = live_view.plain_skip(why, limit=47.68)
    assert "$143.20" in text and "$47.68" in text and "cannot open on an account this size" in text
    room = live_view.plain_skip("open-risk cap: this trade risks $8.93 with $45.30 already at risk", limit=47.68)
    assert "$8.93" in room and "$45.30 is already at risk in other trades" in room and "cannot" not in room
    assert live_view.plain_skip("not enough price history to place a stop", 47.0) == "Not opened: not enough price history to place a stop."


def test_only_calls_without_an_open_trade_are_listed_as_not_opened(monkeypatch):
    book = lb.Book(created=NOW)
    book.history = [{"t": NOW, "equity": 100.0}]
    book.skipped = [{"ticker": "XAUUSD", "date": "2026-10-28", "rating": "Sell", "why": "open-risk cap: this trade risks $143.20 with $0.00 already at risk"},
                    {"ticker": "EURUSD", "date": "2026-10-28", "rating": "Sell", "why": "open-risk cap: this trade risks $9.00 with $45.00 already at risk"}]
    book.positions = {"EURUSD": object()}                    # EURUSD opened later: no longer "not opened"
    monkeypatch.setattr(live_view.lb, "load", lambda path: book)
    monkeypatch.setattr(rules, "FIXED_LOT_MAX_TOTAL_RISK", 0.5)        # the real limit: half the account
    out = live_view.skipped_for(live_view.settings.ACCOUNTS["gemma_short"])
    assert list(out) == ["XAUUSD"] and out["XAUUSD"]["rating"] == "Sell" and "$50.00" in out["XAUUSD"]["why"]
