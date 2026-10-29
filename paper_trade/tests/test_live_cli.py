import argparse
from types import SimpleNamespace

import pytest

from paper_trade.live import book as lb
from paper_trade.live import cli

NOW = "2026-10-29T10:00:00+00:00"


def parser():
    top = argparse.ArgumentParser()
    cli.add_arguments(top.add_subparsers(dest="command"))
    return top


def test_the_command_line_accepts_only_the_live_accounts_and_actions():
    args = parser().parse_args(["live", "--account", "qwen_short", "status"])
    assert (args.account, args.action) == ("qwen_short", "status")
    assert parser().parse_args(["live", "loop"]).account == "gemma_short"          # the default account
    with pytest.raises(SystemExit):
        parser().parse_args(["live", "--account", "gemma", "status"])               # retired
    with pytest.raises(SystemExit):
        parser().parse_args(["live", "explode"])


def test_status_lists_open_trades_with_lot_and_time_limit_finished_trades_and_skipped_calls():
    book = lb.Book(created=NOW)
    book.history = [{"t": NOW, "equity": 99.5}]
    book.positions["EURUSD"] = lb.Position("EURUSD", -1, 1.1, 1.1015, 1.097, NOW, "2026-10-29", "Sell", 1.5, 0.1, 0.02, "2026-10-29T22:00:00+00:00")
    book.closed.append(lb.Closed("GBPUSD", 1, 1.3, 1.31, NOW, NOW, "Take-profit", 2.5, "2026-10-29", "Buy"))
    book.skipped.append({"ticker": "XAUUSD", "date": "2026-10-29", "rating": "Sell", "why": "open-risk cap"})
    text = cli.status_text(book)
    assert "$99.50" in text and "HOLDING SELL EURUSD" in text and "0.02 lot" in text and "closes at the latest 2026-10-29T22:00:00" in text
    assert "Take-profit: BUY GBPUSD" in text and "Skipped XAUUSD" in text
    assert "No position is open." in cli.status_text(lb.Book())


def test_each_action_calls_the_right_thing(monkeypatch, capsys):
    calls = []
    book = lb.Book(created=NOW)
    monkeypatch.setattr(cli.livebook, "load", lambda path: book)
    monkeypatch.setattr(cli.runner, "update", lambda b, account: 101.5)
    monkeypatch.setattr(cli.runner, "loop", lambda account: calls.append(("loop", account.name)))
    monkeypatch.setattr(cli.runner, "start_decisions", lambda account: calls.append(("decide", account.name)))

    def run(action, account="gemma_short"):
        return cli.run(SimpleNamespace(account=account, action=action))

    assert run("update") == 0 and "$101.50" in capsys.readouterr().out
    assert run("status") == 0 and "Live paper account" in capsys.readouterr().out
    assert run("decide", "qwen_short") == 0 and "10 pairs" in capsys.readouterr().out
    assert run("loop") == 0
    assert calls == [("decide", "qwen_short"), ("loop", "gemma_short")]
