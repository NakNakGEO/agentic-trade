import pandas as pd
import pytest

from paper_trade.dashboard import candles, live_view
from paper_trade.live import book as lb
from paper_trade.live import settings

NOW = "2026-10-28T10:00:00+00:00"
ACCOUNT = settings.ACCOUNTS["gemma_short"]


def two_trades():
    """A long and a short on one pair: the pair holds two trades at once."""
    book = lb.Book(created=NOW)
    book.positions["EURUSD"] = lb.Position("EURUSD", 1, 1.10, 1.0985, 1.103, NOW, "2026-10-28", "Buy", 1.5, 0.11, 0.01, "2026-10-29T10:00:00+00:00")
    book.positions["EURUSD#2"] = lb.Position("EURUSD", -1, 1.102, 1.1035, 1.099, NOW, "2026-10-28", "Sell", 3.0, 0.22, 0.02, "2026-10-29T09:00:00+00:00")
    return book


@pytest.fixture
def book(monkeypatch):
    held = two_trades()
    monkeypatch.setattr(live_view.lb, "load", lambda path: held)
    monkeypatch.setattr(candles.lb, "load", lambda path: held)
    monkeypatch.setattr(live_view.feeds, "latest_prices", lambda tickers: {"EURUSD": 1.101})
    return held


def test_a_pair_with_several_trades_shows_totals_and_how_many_instead_of_one_stop(book):
    row = live_view.levels_for(ACCOUNT)["EURUSD"]
    wins, loses = zip(*(lb.outcomes(p) for p in book.positions.values()))
    assert row["stop"] is None and row["target"] is None and row["trades"] == 2
    assert row["lot"] == pytest.approx(0.03) and row["deadline"] == "2026-10-29T09:00:00+00:00"           # the earliest time limit
    assert row["win"] == pytest.approx(round(sum(wins), 2)) and row["lose"] == pytest.approx(round(sum(loses), 2))


def test_a_pair_with_one_trade_still_shows_its_own_levels_and_no_trade_count(book):
    del book.positions["EURUSD#2"]
    row = live_view.levels_for(ACCOUNT)["EURUSD"]
    assert row["stop"] == 1.0985 and row["target"] == 1.103 and row["lot"] == 0.01 and "trades" not in row


def test_the_pair_row_adds_the_trades_up_so_a_long_and_a_short_offset(book):
    stamp = pd.Timestamp("2026-10-28 10:05")
    sleeve = live_view._sleeve(book, "EURUSD", 10.0, 100.0, 1.101, stamp)
    long_units, short_units = lb.qty("EURUSD", 1.101, 0.01), lb.qty("EURUSD", 1.101, 0.02)
    assert sleeve.shares == pytest.approx(long_units - short_units) and len(sleeve.trades) == 2
    expected = long_units * (1.101 - 1.10) - short_units * (1.101 - 1.102) - 0.11 - 0.22
    assert sleeve.cash + sleeve.shares * 1.101 - 10.0 == pytest.approx(expected)


def test_the_trades_panel_always_shows_the_open_risk_and_the_cap(book):
    risk = live_view.blotter_for(ACCOUNT)["risk"]
    assert risk["open"] == pytest.approx(4.5) and risk["trades"] == 2 and risk["cap"] is None
    assert risk["share"] == pytest.approx(4.5 / risk["account"], abs=1e-4)
    book.positions.clear()
    assert live_view.blotter_for(ACCOUNT)["risk"]["open"] == 0 and live_view.blotter_for(ACCOUNT)["risk"]["share"] == pytest.approx(0.0)


def test_a_pair_that_has_one_trade_open_is_not_listed_as_not_opened(book):
    book.skipped = [{"ticker": "EURUSD", "date": "2026-10-28", "rating": "Sell", "why": "open-risk cap: this trade risks $9.00 with $45.00 already at risk"}]
    assert live_view.skipped_for(ACCOUNT) == {}


def test_the_chart_lists_every_open_trade_of_the_pair(book, monkeypatch):
    monkeypatch.setattr(candles.settings, "ACCOUNTS", {"gemma_short": ACCOUNT})
    positions, trades = candles._account_marks("EURUSD", 1.101)
    assert [p["side"] for p in positions] == ["long", "short"] and len(trades) == 2
