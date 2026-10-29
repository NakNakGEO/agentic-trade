import dataclasses
import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from paper_trade.live import book as lb
from paper_trade.live import runner, settings

SHORT = settings.SHORT
STACK = lb.Policy(max_per_pair=3)
HEDGE = lb.Policy(max_per_pair=1, hedge=True)
WHEN = "2026-10-30T01:00:00+00:00"


def act(book, rating, slot, price=1.1, policy=None, ticker="EURUSD", prices=None, average_range=0.001):
    lb.apply_decision(book, ticker, "2026-10-30", rating, price, [], WHEN, prices or {ticker: price}, average_range, SHORT, slot, None, policy)


def bars(*rows):
    """rows of (minute, open, high, low) on 2026-10-30 01:xx."""
    return pd.DataFrame([(o, h, low, o) for _, o, h, low in rows], columns=["Open", "High", "Low", "Close"],
                        index=[pd.Timestamp(f"2026-10-30 01:{minute:02d}") for minute, *_ in rows])


def test_by_default_a_pair_holds_one_trade_and_a_second_call_the_same_way_changes_nothing():
    book = lb.Book()
    act(book, "Sell", "a")
    act(book, "Sell", "b")
    assert list(book.positions) == ["EURUSD"] and book.applied == ["EURUSD|2026-10-30|a", "EURUSD|2026-10-30|b"]


def test_a_pair_can_hold_several_trades_in_the_same_direction_up_to_its_limit():
    book = lb.Book()
    for slot in "abcd":
        act(book, "Sell", slot, policy=STACK)
    assert list(book.positions) == ["EURUSD", "EURUSD#2", "EURUSD#3"]               # the fourth call was ignored: three is the limit
    assert len(lb.held(book, "EURUSD")) == 3 and book.applied[-1] == "EURUSD|2026-10-30|d"
    assert lb.equity(book, {"EURUSD": 1.1}) == pytest.approx(100 - 3 * lb._fee("EURUSD", 1.1, 0.01))


def test_the_trades_of_a_pair_are_valued_and_closed_each_on_its_own_levels():
    book = lb.Book()
    act(book, "Buy", "a", price=1.1, policy=STACK)
    act(book, "Buy", "b", price=1.1020, policy=STACK, prices={"EURUSD": 1.102})
    first, second = lb.held(book, "EURUSD")
    assert first.stop < second.stop
    assert lb.equity(book, {"EURUSD": 1.103}) == pytest.approx(100 + book.realized + 1000 * (1.103 - 1.1) + 1000 * (1.103 - 1.102))
    # a dip that reaches only the second trade's stop (it sits closer to the price) closes that one and leaves the first
    lb.step(book, "EURUSD", bars((2, 1.1025, 1.1026, second.stop - 0.00001)))
    assert [c.reason for c in book.closed] == ["Stop-loss"] and book.closed[0].entry == 1.1020
    assert list(book.positions) == ["EURUSD"] and book.positions["EURUSD"].entry == 1.1


def test_a_call_against_the_trades_closes_all_of_them_unless_the_account_hedges():
    book = lb.Book()
    act(book, "Buy", "a", policy=STACK)
    act(book, "Buy", "b", policy=STACK)
    act(book, "Sell", "c", price=1.099, policy=STACK, prices={"EURUSD": 1.099})
    assert [c.reason for c in book.closed] == ["New call", "New call"] and [p.side for p in book.positions.values()] == [-1]


def test_a_hedging_account_keeps_the_trade_and_opens_the_opposite_one_beside_it():
    book = lb.Book()
    act(book, "Buy", "a", policy=HEDGE)
    act(book, "Sell", "b", price=1.099, policy=HEDGE, prices={"EURUSD": 1.099})
    assert book.closed == [] and sorted(p.side for p in book.positions.values()) == [-1, 1]
    act(book, "Sell", "c", price=1.098, policy=HEDGE, prices={"EURUSD": 1.098})        # the short side is already at its limit of one
    assert len(book.positions) == 2
    prices = {"EURUSD": 1.095}
    assert lb.equity(book, prices) == pytest.approx(100 + book.realized + 1000 * (1.095 - 1.1) - 1000 * (1.095 - 1.099))
    lb.close_position(book, "EURUSD", 1.095, WHEN, "Pair left the list")
    assert book.positions == {} and len(book.closed) == 2


def test_the_risk_cap_is_a_switch_and_an_account_with_no_money_left_cannot_open_a_trade():
    capped = lb.Book()
    act(capped, "Sell", "a", policy=lb.Policy(risk_cap=0.001))
    assert capped.positions == {} and "open-risk cap" in capped.skipped[0]["why"]
    free = lb.Book()
    act(free, "Sell", "a", policy=lb.Policy(risk_cap=None))
    assert len(free.positions) == 1 and free.skipped == []
    broke = lb.Book(realized=-100.0)
    act(broke, "Sell", "a", policy=lb.Policy(risk_cap=None))
    assert broke.positions == {} and "wiped out" in broke.skipped[0]["why"]


def test_when_the_account_falls_to_zero_every_trade_is_closed_where_it_stands():
    book = lb.Book()
    act(book, "Buy", "a", policy=STACK)
    act(book, "Buy", "b", policy=STACK)
    assert lb.wipe_out(book, {"EURUSD": 1.1}, WHEN) is False and len(book.positions) == 2
    assert lb.wipe_out(book, {"EURUSD": 0.001}, WHEN) is True
    assert book.positions == {} and [c.reason for c in book.closed] == ["Wiped out", "Wiped out"]
    assert lb.wipe_out(book, {"EURUSD": 0.001}, WHEN) is False                          # nothing left to close


def test_stacked_trades_survive_saving_and_loading(tmp_path):
    book = lb.Book()
    for slot in "ab":
        act(book, "Sell", slot, policy=STACK)
    lb.save(book, tmp_path / "book.json")
    again = lb.load(tmp_path / "book.json")
    assert list(again.positions) == ["EURUSD", "EURUSD#2"] and again.positions == book.positions


def test_the_environment_sets_the_trade_limit_the_hedge_and_the_risk_cap_per_account():
    accounts = {"gemma_short": settings.ACCOUNTS["gemma_short"], "qwen_short": settings.ACCOUNTS["qwen_short"]}
    out = settings.apply_overrides(accounts, {"AGENTIC_MAX_PER_PAIR_GEMMA_SHORT": "3", "AGENTIC_HEDGE_GEMMA_SHORT": "ON",
                                              "AGENTIC_RISK_CAP_GEMMA_SHORT": "50%", "AGENTIC_MAX_PER_PAIR_QWEN_SHORT": "0",
                                              "AGENTIC_HEDGE_QWEN_SHORT": "maybe", "AGENTIC_RISK_CAP_QWEN_SHORT": "nonsense"})
    gemma, qwen = out["gemma_short"], out["qwen_short"]
    assert (gemma.max_per_pair, gemma.hedge, gemma.risk_cap) == (3, True, 0.5)
    assert (qwen.max_per_pair, qwen.hedge, qwen.risk_cap) == (1, False, None)               # unusable values change nothing
    assert settings.apply_overrides({"gemma_short": dataclasses.replace(gemma, risk_cap=0.5)}, {"AGENTIC_RISK_CAP_GEMMA_SHORT": "off"})["gemma_short"].risk_cap is None
    assert settings.apply_overrides(accounts, {})["gemma_short"].risk_cap is None and settings.ACCOUNTS["gemma_short"].max_per_pair == 1


@pytest.fixture
def world(monkeypatch, tmp_path):
    state = {"log": [], "prices": {"EURUSD": 1.1}, "bars": None}
    monkeypatch.setattr(runner.config, "READ_ONLY_DATA", False)
    monkeypatch.setattr("paper_trade.report.load_decisions", lambda run_id: (state["log"], None))
    monkeypatch.setattr(runner.feeds, "latest_prices", lambda tickers: dict(state["prices"]))
    monkeypatch.setattr(runner.feeds, "hourly_range", lambda ticker: 0.001)
    monkeypatch.setattr(runner.feeds, "intraday_bars", lambda ticker: state["bars"])
    monkeypatch.setattr(runner.feeds, "record_minute", lambda stamp: None)
    monkeypatch.setattr(runner, "_record_day", lambda: None)
    monkeypatch.setattr(settings, "book_path", lambda account: tmp_path / "book.json")
    monkeypatch.setattr(settings, "state_path", lambda account: tmp_path / "state.json")
    return state


def calls(*ratings):
    from types import SimpleNamespace
    return [SimpleNamespace(ticker="EURUSD", date="2026-10-30", rating=r) for r in ratings]


def test_the_account_update_stacks_trades_only_when_its_limit_allows(world, monkeypatch):
    monkeypatch.setattr(runner.schedule, "all_runs", lambda account: ["live_gemma_s202610300030", "live_gemma_s202610300230"])
    monkeypatch.setattr("paper_trade.report.load_decisions", lambda run_id: (calls("Sell"), None))
    now = datetime(2026, 10, 30, 3, 0, tzinfo=timezone.utc)
    plain, stacked = lb.Book(created="2026-10-30T00:00:00+00:00"), lb.Book(created="2026-10-30T00:00:00+00:00")
    runner.update(plain, settings.ACCOUNTS["gemma_short"], now)
    runner.update(stacked, dataclasses.replace(settings.ACCOUNTS["gemma_short"], max_per_pair=2), now)
    assert len(plain.positions) == 1 and len(stacked.positions) == 2 and len(stacked.applied) == 2


def test_the_account_update_closes_everything_when_the_account_is_wiped_out(world, monkeypatch):
    monkeypatch.setattr("paper_trade.report.load_decisions", lambda run_id: (calls("Buy"), None))
    now = datetime(2026, 10, 30, 3, 0, tzinfo=timezone.utc)
    book = lb.Book(created="2026-10-30T00:00:00+00:00")
    runner.update(book, settings.ACCOUNTS["gemma_short"], now)
    assert len(book.positions) == 1
    world["prices"] = {"EURUSD": 0.001}
    runner.update(book, settings.ACCOUNTS["gemma_short"], now)
    assert book.positions == {} and book.closed[-1].reason == "Wiped out" and json.loads((runner.settings.book_path(None)).read_text())["closed"]


def test_switches_can_be_set_in_the_env_file_and_a_variable_set_by_hand_wins(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("OPENAI_COMPATIBLE_API_KEY=not-a-switch\nAGENTIC_HEDGE_GEMMA_SHORT=on\nAGENTIC_MAX_PER_PAIR_GEMMA_SHORT=2\n", encoding="utf-8")
    monkeypatch.setattr(settings.config, "ROOT", tmp_path)
    monkeypatch.setenv("AGENTIC_MAX_PER_PAIR_GEMMA_SHORT", "3")
    found = settings._switches()
    assert found["AGENTIC_HEDGE_GEMMA_SHORT"] == "on" and found["AGENTIC_MAX_PER_PAIR_GEMMA_SHORT"] == "3"
    assert "OPENAI_COMPATIBLE_API_KEY" not in found                       # a key is never read as a switch
    accounts = settings.apply_overrides({"gemma_short": settings.ACCOUNTS["gemma_short"]}, found)
    assert accounts["gemma_short"].hedge is True and accounts["gemma_short"].max_per_pair == 3
