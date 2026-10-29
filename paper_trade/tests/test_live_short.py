from types import SimpleNamespace

import pandas as pd
import pytest

from paper_trade.bridge import settings as rules
from paper_trade.dashboard import live_view
from paper_trade.live import book as lb
from paper_trade.live import runner, settings

NOW = "2026-10-28T10:00:00+00:00"
SHORT = settings.SHORT
ACCOUNT = settings.ACCOUNTS["gemma_short"]


@pytest.fixture(autouse=True)
def fixed_lot(monkeypatch):
    monkeypatch.setattr(rules, "FIXED_LOT", 0.01)
    monkeypatch.setattr(rules, "FIXED_LOT_MAX_TOTAL_RISK", 100.0)       # the cap has its own test


def hourly(*rows):
    """rows of (hour, open, high, low) on 2026-10-28."""
    return pd.DataFrame([(o, h, low, o) for _, o, h, low in rows], columns=["Open", "High", "Low", "Close"],
                        index=[pd.Timestamp(f"2026-10-28 {hour}:00") for hour, *_ in rows])


def test_other_pairs_are_sized_to_lose_the_risk_share_at_the_stop():
    eur = lb.lot_for(SHORT, "EURUSD", 1.1136, 0.0016, 1000.0)            # $160 per lot at the stop; 2% of $1,000 is $20
    assert eur == pytest.approx(0.12)
    assert lb.lot_for(SHORT, "ETH-USD", 2308.0, 25.0, 100.0) == pytest.approx(0.08)   # $2 over $25 a coin


def test_the_smallest_trade_is_one_lot_step_even_when_it_risks_more_than_the_share():
    assert lb.lot_for(SHORT, "BTC-USD", 79828.0, 606.0, 100.0) == pytest.approx(0.01)   # $6 at the stop, 6% of $100


def test_gold_keeps_the_fixed_lot():
    assert lb.lot_for(SHORT, "XAUUSD", 4032.0, 23.4, 100.0) is None
    book = lb.Book(created=NOW)
    lb.apply_decision(book, "XAUUSD", "2026-10-28", "Sell", 4032.0, [], NOW, {"XAUUSD": 4032.0}, 15.6, SHORT)
    pos = book.positions["XAUUSD"]
    assert pos.lot is None and pos.risk == pytest.approx(15.6 * 1.5 * 1.0)        # 0.01 lot of gold is one ounce


def test_a_short_term_trade_has_a_tight_stop_a_target_two_stops_away_and_a_time_limit():
    book = lb.Book(created=NOW)
    lb.apply_decision(book, "EURUSD", "2026-10-28", "Sell", 1.1, [], NOW, {"EURUSD": 1.1}, 0.001, SHORT)
    pos = book.positions["EURUSD"]
    assert pos.stop == pytest.approx(1.1015) and pos.target == pytest.approx(1.1 - 0.0015 * 2)
    assert pos.lot == pytest.approx(0.01) and pos.deadline == "2026-10-28T22:00:00+00:00"


def test_the_standard_daily_rules_are_unchanged_without_a_style():
    book = lb.Book(created=NOW)
    lb.apply_decision(book, "EURUSD", "2026-10-28", "Sell", 100.0, [], NOW, {"EURUSD": 100.0}, 2.0)
    pos = book.positions["EURUSD"]
    assert pos.stop == pytest.approx(104.0) and pos.lot is None and pos.deadline == ""


def test_a_trade_is_closed_at_the_open_of_the_first_bar_at_its_time_limit():
    book = lb.Book(created=NOW)
    lb.apply_decision(book, "EURUSD", "2026-10-28", "Sell", 1.1, [], NOW, {"EURUSD": 1.1}, 0.001, SHORT)
    lb.step(book, "EURUSD", hourly((21, 1.1, 1.1005, 1.0995)))            # 21:00: still inside the 12 hours
    assert "EURUSD" in book.positions
    lb.step(book, "EURUSD", hourly((21, 1.1, 1.1005, 1.0995), (22, 1.0990, 1.1000, 1.0985)))
    assert book.closed[0].reason == "Time limit" and book.closed[0].exit == pytest.approx(1.0990)
    assert book.closed[0].pnl > 0 and book.closed[0].lot == pytest.approx(0.01)


def test_the_stop_still_comes_before_the_time_limit_when_it_is_touched_earlier():
    book = lb.Book(created=NOW)
    lb.apply_decision(book, "EURUSD", "2026-10-28", "Sell", 1.1, [], NOW, {"EURUSD": 1.1}, 0.001, SHORT)
    lb.step(book, "EURUSD", hourly((12, 1.1, 1.102, 1.0995), (23, 1.1, 1.1, 1.1)))
    assert [c.reason for c in book.closed] == ["Stop-loss"]


def test_a_bigger_lot_scales_the_profit_and_the_account_value():
    book = lb.Book(created=NOW)
    lb.apply_decision(book, "ETH-USD", "2026-10-28", "Buy", 2300.0, [], NOW, {"ETH-USD": 2300.0}, 16.0, SHORT)
    assert book.positions["ETH-USD"].lot == pytest.approx(0.08)
    start = lb.equity(book, {"ETH-USD": 2300.0})
    assert lb.equity(book, {"ETH-USD": 2310.0}) - start == pytest.approx(0.08 * 10.0)


def test_the_win_and_lose_amounts_are_what_the_trade_really_makes_at_its_target_or_stop():
    for side_call, bars, reason in (("Sell", hourly((11, 1.1, 1.1001, 1.0900)), "Take-profit"),
                                    ("Sell", hourly((11, 1.1, 1.1100, 1.0999)), "Stop-loss")):
        book = lb.Book(created=NOW)
        lb.apply_decision(book, "EURUSD", "2026-10-28", side_call, 1.1, [], NOW, {"EURUSD": 1.1}, 0.001, SHORT)
        win, lose = lb.outcomes(book.positions["EURUSD"])
        lb.step(book, "EURUSD", bars)
        assert book.closed[0].reason == reason
        assert book.closed[0].pnl == pytest.approx(win if reason == "Take-profit" else lose, abs=1e-3)
        assert win > 0 > lose


def test_lot_and_time_limit_survive_a_save_and_load(tmp_path):
    book = lb.Book(created=NOW)
    lb.apply_decision(book, "ETH-USD", "2026-10-28", "Buy", 2300.0, [], NOW, {"ETH-USD": 2300.0}, 16.0, SHORT)
    path = tmp_path / "book.json"
    lb.save(book, path)
    assert lb.load(path).positions == book.positions


def decisions(*rows):
    return [SimpleNamespace(date=date, ticker=ticker, rating="Sell") for date, ticker in rows]


def test_a_new_account_skips_old_calls_and_never_trades_stocks(monkeypatch):
    log = decisions(("2026-10-28", "EURUSD"), ("2026-10-29", "EURUSD"), ("2026-10-29", "AAPL"))
    monkeypatch.setattr("paper_trade.report.load_decisions", lambda run_id: (log, None))
    book = lb.Book()
    runner._skip_old_calls(book, ACCOUNT, "2026-10-29")
    assert book.applied == ["EURUSD|2026-10-28"]
    assert [(d.ticker, d.date) for d in runner.new_decisions(book, ACCOUNT)] == [("EURUSD", "2026-10-29")]


def test_each_account_decides_into_the_run_folder_that_already_holds_its_history(monkeypatch):
    assert (ACCOUNT.run_id, ACCOUNT.decisions_run) == ("live_gemma_short", "live_gemma")
    assert settings.ACCOUNTS["qwen_short"].decisions_run == "live_qwen" and list(settings.ACCOUNTS) == ["gemma_short", "qwen_short"]
    monkeypatch.setattr(runner, "_state", lambda account: {})
    assert runner.decisions_due(ACCOUNT, pd.Timestamp("2026-10-29 03:00").to_pydatetime()) is True
    monkeypatch.setattr(runner, "_state", lambda account: {"decisions_started": "2026-10-29"})
    assert runner.decisions_due(ACCOUNT, pd.Timestamp("2026-10-29 03:00").to_pydatetime()) is False     # once a day


def test_the_page_describes_the_short_term_rules_in_plain_words():
    text = live_view.style_note(ACCOUNT)
    assert "1.5 x the 1-hour average range" in text and "12 hours" in text and "2%" in text and "XAUUSD" in text
    assert live_view.style_note(None) is None                     # the standard daily rules need no note
    assert live_view.source_run("live_qwen_short") == "live_qwen"
