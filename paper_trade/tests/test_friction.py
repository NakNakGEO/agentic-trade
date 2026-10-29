import dataclasses
from datetime import datetime, timezone

import pandas as pd
import pytest

from paper_trade import whatif
from paper_trade.live import book as lb
from paper_trade.live import friction, runner, settings
from paper_trade.whatif import replay

SHORT = settings.SHORT
SLIP = friction.Friction()
WHEN = "2026-10-30T01:00:00+00:00"


def bars(*rows):
    return pd.DataFrame([(o, h, low, o) for _, o, h, low in rows], columns=["Open", "High", "Low", "Close"],
                        index=[pd.Timestamp(f"2026-10-30 01:{minute:02d}") for minute, *_ in rows])


def test_each_kind_of_fill_slips_by_its_own_amount_and_a_take_profit_does_not():
    market, stop = settings.SLIPPAGE_BPS["forex"]
    assert SLIP.into("EURUSD", 1, 1.1) == pytest.approx(1.1 * (1 + market / 1e4)) and SLIP.into("EURUSD", -1, 1.1) < 1.1       # a buyer pays more, a seller gets less
    assert SLIP.out("EURUSD", 1, 1.1, "Time limit") == pytest.approx(1.1 * (1 - market / 1e4))
    assert SLIP.out("EURUSD", 1, 1.1, "Stop-loss") == pytest.approx(1.1 * (1 - stop / 1e4))
    assert SLIP.out("EURUSD", 1, 1.1, "Stop-loss") < SLIP.out("EURUSD", 1, 1.1, "Time limit")                       # a stop slips more than a market order
    assert SLIP.out("EURUSD", -1, 1.1, "Stop-loss") > 1.1 and SLIP.out("EURUSD", 1, 1.1, "Take-profit") == 1.1
    assert SLIP.out("EURUSD", 1, 1.1, "Wiped out") == SLIP.out("EURUSD", 1, 1.1, "Stop-loss")
    assert SLIP.into("AAPL", 1, 200.0) == 200.0 and friction.Friction({"forex": (10.0, 20.0)}).into("EURUSD", 1, 1.0) == pytest.approx(1.001)


def test_only_an_account_that_switched_slippage_on_gets_it():
    account = settings.ACCOUNTS["gemma_short"]
    assert friction.for_account(account) is None and isinstance(friction.for_account(dataclasses.replace(account, slippage=True)), friction.Friction)
    out = settings.apply_overrides({"gemma_short": account, "qwen_short": settings.ACCOUNTS["qwen_short"]},
                                   {"AGENTIC_SLIPPAGE_GEMMA_SHORT": "ON", "AGENTIC_SLIPPAGE_QWEN_SHORT": "maybe"})
    assert out["gemma_short"].slippage is True and out["qwen_short"].slippage is False


def open_trade(slip=None, side=-1):
    book = lb.Book()
    lb.apply_decision(book, "EURUSD", "2026-10-30", "Sell" if side < 0 else "Buy", 1.1, [], WHEN, {"EURUSD": 1.1}, 0.001, SHORT, "a", None, None, slip)
    return book


def test_an_entry_fills_worse_than_the_price_and_the_levels_follow_the_fill():
    plain, slipped = open_trade().positions["EURUSD"], open_trade(SLIP).positions["EURUSD"]
    assert plain.entry == 1.1 and slipped.entry < 1.1                         # a short is filled a little lower
    assert slipped.stop - slipped.entry == pytest.approx(plain.stop - plain.entry) and slipped.entry == pytest.approx(SLIP.into("EURUSD", -1, 1.1))


def test_a_stop_loss_closes_worse_than_the_stop_and_costs_more_than_without_slippage():
    results = {}
    for name, slip in (("plain", None), ("slipped", SLIP)):
        book = open_trade(slip)
        pos = book.positions["EURUSD"]
        lb.step(book, "EURUSD", bars((2, 1.1, pos.stop + 0.0001, 1.1)), slip)
        results[name] = book.closed[0]
    assert results["plain"].reason == "Stop-loss" == results["slipped"].reason
    assert results["slipped"].exit > results["plain"].stop - 1                   # filled above the stop for a short
    assert results["slipped"].exit == pytest.approx(SLIP.out("EURUSD", -1, results["slipped"].stop, "Stop-loss"))
    assert results["slipped"].pnl < results["plain"].pnl


def test_a_take_profit_fills_at_its_level_and_a_time_limit_and_a_new_call_fill_at_the_market_with_slippage():
    book = open_trade(SLIP)
    pos = book.positions["EURUSD"]
    lb.step(book, "EURUSD", bars((2, 1.1, 1.1, pos.target - 0.0001)), SLIP)
    assert book.closed[0].reason == "Take-profit" and book.closed[0].exit == pos.target
    flip = open_trade(SLIP)
    lb.apply_decision(flip, "EURUSD", "2026-10-30", "Buy", 1.099, [], WHEN, {"EURUSD": 1.099}, 0.001, SHORT, "b", None, None, SLIP)
    assert flip.closed[0].reason == "New call" and flip.closed[0].exit == pytest.approx(SLIP.out("EURUSD", -1, 1.099, "New call"))
    assert flip.positions["EURUSD"].entry == pytest.approx(SLIP.into("EURUSD", 1, 1.099))


def test_a_wiped_out_account_closes_everything_with_slippage():
    book = open_trade(SLIP, side=1)
    assert lb.wipe_out(book, {"EURUSD": 0.001}, WHEN, SLIP) is True
    assert book.closed[0].reason == "Wiped out" and book.closed[0].exit == pytest.approx(SLIP.out("EURUSD", 1, 0.001, "Wiped out"))


def test_the_account_update_uses_slippage_only_when_its_switch_is_on(monkeypatch, tmp_path):
    from types import SimpleNamespace
    monkeypatch.setattr(runner.config, "READ_ONLY_DATA", False)
    monkeypatch.setattr("paper_trade.report.load_decisions", lambda run_id: ([SimpleNamespace(ticker="EURUSD", date="2026-10-30", rating="Sell")], None))
    monkeypatch.setattr(runner.feeds, "latest_prices", lambda tickers: {"EURUSD": 1.1})
    monkeypatch.setattr(runner.feeds, "hourly_range", lambda ticker: 0.001)
    monkeypatch.setattr(runner.feeds, "intraday_bars", lambda ticker: None)
    monkeypatch.setattr(runner.feeds, "record_minute", lambda stamp: None)
    monkeypatch.setattr(runner, "_record_day", lambda: None)
    monkeypatch.setattr(settings, "book_path", lambda account: tmp_path / "book.json")
    now = datetime(2026, 10, 30, 3, 0, tzinfo=timezone.utc)
    plain, slipped = lb.Book(created="2026-10-30T00:00:00+00:00"), lb.Book(created="2026-10-30T00:00:00+00:00")
    runner.update(plain, settings.ACCOUNTS["gemma_short"], now)
    runner.update(slipped, dataclasses.replace(settings.ACCOUNTS["gemma_short"], slippage=True), now)
    assert plain.positions["EURUSD"].entry == 1.1 and slipped.positions["EURUSD"].entry == pytest.approx(SLIP.into("EURUSD", -1, 1.1))


def test_the_what_if_replays_a_slipped_trade_exactly_when_it_is_given_the_same_slippage():
    book = open_trade(SLIP)
    path = [1.1 + 0.0001 * i for i in range(30)]
    minutes = pd.DataFrame({"Open": path, "High": [p + 0.00002 for p in path], "Low": [p - 0.00002 for p in path], "Close": path},
                           index=pd.date_range("2026-10-30 01:01", periods=30, freq="min"))
    lb.step(book, "EURUSD", minutes, SLIP)
    trade = replay.trades_of(book)[0]
    assert trade.reason == "Stop-loss"
    assert whatif.run([trade], {"EURUSD": minutes}, SHORT, 100.0, SLIP)["check"]["exact"] == 1
    assert whatif.run([trade], {"EURUSD": minutes}, SHORT, 100.0, None)["check"]["exact"] == 0       # without it the replay no longer matches
