from types import SimpleNamespace

import pandas as pd
import pytest

from paper_trade import whatif
from paper_trade.live import book as lb
from paper_trade.live import settings
from paper_trade.whatif import cli, replay

SHORT = settings.SHORT
OPEN = "2026-10-30T01:00:00+00:00"


def minutes(prices, start="2026-10-30 01:01"):
    close = pd.Series(prices, index=pd.date_range(start, periods=len(prices), freq="min"))
    return pd.DataFrame({"Open": close, "High": close + 0.00002, "Low": close - 0.00002, "Close": close})


def open_short(book, rating="Sell", when=OPEN, price=1.1):
    lb.apply_decision(book, "EURUSD", when[:10], rating, price, [], when, {"EURUSD": price}, 0.001, SHORT, slot=when[11:16].replace(":", ""))


def falling(minutes_count=60, end=1.0955):
    return [1.1 + (end - 1.1) * i / minutes_count for i in range(minutes_count)]


def trade_of(book):
    return replay.trades_of(book)[0]


def live_run(path, rating="Sell"):
    """A trade opened and stepped by the real live code over ``path``; returns its book and the minute candles."""
    book, bars = lb.Book(), minutes(path)
    open_short(book, rating)
    lb.step(book, "EURUSD", bars)
    return book, bars


@pytest.mark.parametrize("name, path, reason", [
    ("target", falling(), "Take-profit"),
    ("stop", [1.1 + 0.0001 * i for i in range(30)], "Stop-loss"),
    ("time limit", [1.1 + 0.00001 * (i % 5) for i in range(12 * 60 + 5)], "Time limit"),
])
def test_a_trade_replayed_as_it_was_traded_ends_exactly_as_it_really_did(name, path, reason):
    book, bars = live_run(path)
    trade = trade_of(book)
    assert trade.reason == reason
    now = replay.as_traded(trade, bars, SHORT.max_hours)
    assert replay.differences(trade, now) == [] and now.pnl == pytest.approx(trade.pnl) and now.exit == trade.exit


def test_a_trade_closed_by_a_later_call_is_cut_at_that_call_and_still_matches():
    book, bars = live_run(falling(30, 1.0988))                                    # drifts down, touches nothing
    assert len(book.positions) == 1
    lb.apply_decision(book, "EURUSD", "2026-10-30", "Buy", 1.0990, [], "2026-10-30T01:31:00+00:00", {"EURUSD": 1.099}, 0.001, SHORT, slot="0131")
    trade = [t for t in replay.trades_of(book) if t.reason][0]
    assert trade.reason == "New call" and trade.exit == 1.0990
    later = minutes(falling(30, 1.0988) + [1.0, 1.0, 1.0], start="2026-10-30 01:01")          # minutes after the call must not count
    assert replay.differences(trade, replay.as_traded(trade, later, SHORT.max_hours)) == []


def test_a_trade_still_open_is_marked_at_the_last_recorded_minute():
    book, bars = live_run(falling(10, 1.0990))
    trade = trade_of(book)
    now = replay.as_traded(trade, bars, SHORT.max_hours)
    assert trade.reason == "" and now.reason == "Open" and now.closed_at == ""
    assert now.pnl > 0 - 0.2 and now.pnl == pytest.approx(lb.equity(book, {"EURUSD": float(bars.Close.iloc[-1])}) - 100 + 0.0, abs=0.2)


def test_a_difference_from_what_really_happened_is_reported_in_words():
    book, bars = live_run(falling())
    trade = trade_of(book)
    shifted = replay.Result(trade.pnl + 1.0, "Stop-loss", "2026-10-30T09:00:00+00:00", 1.0)
    text = "; ".join(replay.differences(trade, shifted))
    assert "ended by Stop-loss, really Take-profit" in text and "made" in text and "at 2026-10-30T09:00" in text


def test_the_variants_start_with_the_accounts_own_rules_and_change_one_rule_at_a_time():
    names = [v[0] for v in whatif.variants(SHORT)]
    assert names[0] == "as set" and len(names) == 1 + 3 + 3 + 4
    assert {"stop 1x", "stop 2x", "stop 3x", "target 1 stops", "target 3 stops", "hours 4 h", "hours 48 h"} <= set(names)
    assert "stop 1.5x" not in names and "target 2 stops" not in names and "hours 12 h" not in names
    assert [v for v in whatif.variants(SHORT) if v[0] == "hours 4 h"] == [("hours 4 h", 1.5, 2.0, 4)]


def test_another_exit_rule_changes_the_result_of_the_same_trade():
    book, bars = live_run(falling())
    trade = trade_of(book)
    same = replay.replay(trade, bars, SHORT, 1.5, 2.0, 12, equity=100.0)
    assert same.reason == "Take-profit" and same.pnl > 0
    far = replay.replay(trade, bars, SHORT, 1.5, 3.0, 12, equity=100.0)             # a target 3 stops away is never reached here,
    assert far.reason == "Open" and far.pnl > same.pnl                              # so the trade keeps riding the fall
    tight = replay.replay(trade_of(live_run([1.1 + 0.0001 * i for i in range(30)])[0]), minutes([1.1 + 0.00005 * i for i in range(60)]), SHORT, 1.0, 2.0, 12, 100.0)
    assert tight.reason == "Stop-loss" and tight.pnl < 0
    quick = replay.replay(trade, minutes([1.1] * 300), SHORT, 1.5, 2.0, 4, 100.0)
    assert quick.reason == "Time limit"


def test_a_full_run_checks_the_replay_first_then_tries_every_variant():
    wins, _ = live_run(falling())
    trades = replay.trades_of(wins)
    result = whatif.run(trades, {"EURUSD": minutes(falling())}, SHORT, 100.0)
    assert result["trades"] == 1 and result["skipped"] == 0 and result["enough"] is False
    assert result["check"] == {"finished": 1, "exact": 1, "differences": []}
    assert [r["name"] for r in result["rows"]][0] == "as set" and result["rows"][0]["wins"] == 1 and result["rows"][0]["total"] > 0
    text = whatif.render(result, "Test account")
    assert "1 of 1 finished trades come out exactly as traded" in text and "too few trades to judge" in text and "as set" in text


def test_a_trade_without_minutes_since_it_opened_is_left_out_not_guessed():
    book, bars = live_run(falling())
    trades = replay.trades_of(book)
    late = minutes(falling(), start="2026-10-30 02:00")                           # the record starts after the trade opened
    result = whatif.run(trades, {"EURUSD": late, "NOPAIR": bars}, SHORT, 100.0)
    assert result["trades"] == 0 and result["skipped"] == 1 and result["rows"][0]["average"] is None
    assert "1 older than the minute record" in whatif.render(result, "x") and whatif.run(trades, {}, SHORT, 100.0)["skipped"] == 1


def test_a_mismatch_in_the_check_is_listed_by_pair_and_time():
    book, bars = live_run(falling())
    trade = trade_of(book)
    wrong = replay.Trade(**{**trade.__dict__, "pnl": trade.pnl + 5})
    result = whatif.run([wrong], {"EURUSD": bars}, SHORT, 100.0)
    assert result["check"]["exact"] == 0 and "EURUSD 2026-10-30T01:00" in result["check"]["differences"][0]
    assert "the others:" in whatif.render(result, "x")


def test_the_command_prints_one_what_if_per_account(monkeypatch, capsys):
    monkeypatch.setattr(whatif, "for_account", lambda account: {"trades": 0, "skipped": 0, "rows": [], "enough": False, "check": {"finished": 0, "exact": 0, "differences": []}})
    assert cli.run(SimpleNamespace(account="gemma_short")) == 0
    out = capsys.readouterr().out
    assert "short-term Gemma" in out and "short-term Qwen" not in out
    cli.run(SimpleNamespace(account=None))
    assert "short-term Qwen" in capsys.readouterr().out


def test_for_account_reads_the_book_and_every_recorded_minute(monkeypatch, tmp_path):
    from paper_trade.live import tradingview

    book, bars = live_run(falling())
    monkeypatch.setattr(lb, "load", lambda path: book)
    monkeypatch.setattr(tradingview, "all_candles", lambda ticker: bars if ticker == "EURUSD" else pytest.fail(ticker))
    result = whatif.for_account(settings.ACCOUNTS["gemma_short"])
    assert result["trades"] == 1 and result["check"]["exact"] == 1
    monkeypatch.setattr(tradingview, "all_candles", lambda ticker: (_ for _ in ()).throw(ValueError("none recorded")))
    assert whatif.for_account(settings.ACCOUNTS["gemma_short"])["skipped"] == 1
