import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from paper_trade import config
from paper_trade.live import runner, settings

REAL_RECORD_DAY = runner._record_day
ACCOUNT = settings.ACCOUNTS["gemma_short"]
NOW = datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc)


def call(date, ticker, rating):
    return SimpleNamespace(ticker=ticker, date=date, rating=rating)


@pytest.fixture
def world(monkeypatch, tmp_path):
    """A fake outside world for one account: a decision log, live prices, an hourly range and minute bars."""
    state = {"log": [], "prices": {"EURUSD": 1.1}, "range": 0.001, "bars": None, "recorded": [], "path": tmp_path / "book.json"}
    monkeypatch.setattr(config, "READ_ONLY_DATA", False)
    monkeypatch.setattr("paper_trade.report.load_decisions", lambda run_id: (state["log"], None))
    monkeypatch.setattr(runner.feeds, "latest_prices", lambda tickers: dict(state["prices"]))
    monkeypatch.setattr(runner.feeds, "hourly_range", lambda ticker: state["range"])
    monkeypatch.setattr(runner.feeds, "intraday_bars", lambda ticker: state["bars"])
    monkeypatch.setattr(runner.feeds, "record_minute", lambda stamp: state["recorded"].append("minute"))
    monkeypatch.setattr(runner, "_record_day", lambda: state["recorded"].append("day"))
    monkeypatch.setattr(settings, "book_path", lambda account: state["path"])
    monkeypatch.setattr(settings, "state_path", lambda account: tmp_path / "state.json")
    return state


def test_a_new_account_skips_old_calls_and_opens_a_trade_for_todays(world):
    world["log"] = [call("2026-10-29", "EURUSD", "Buy"), call("2026-10-30", "EURUSD", "Sell")]
    book = runner.livebook.Book()
    value = runner.update(book, ACCOUNT, NOW)
    pos = book.positions["EURUSD"]
    assert pos.side == -1 and pos.entry == 1.1 and pos.stop == pytest.approx(1.1015)
    assert book.applied == ["EURUSD|2026-10-29", "EURUSD|2026-10-30"] and book.created.startswith("2026-10-30T01:00")
    assert world["recorded"] == ["minute", "day"] and json.loads(world["path"].read_text())["positions"]["EURUSD"]
    assert value == pytest.approx(book.history[-1]["equity"]) and value < 100                  # the entry fee


def test_a_call_waits_for_a_price_and_for_an_hourly_range_instead_of_being_lost(world):
    world["log"] = [call("2026-10-30", "EURUSD", "Sell")]
    book = runner.livebook.Book(created="2026-10-30T00:00:00+00:00")
    world["prices"] = {}
    runner.update(book, ACCOUNT, NOW)
    assert book.positions == {} and book.applied == []                    # no price right now: left for the next cycle
    world["prices"], world["range"] = {"EURUSD": 1.1}, None
    runner.update(book, ACCOUNT, NOW)
    assert book.positions == {} and book.applied == []                    # no range, so no stop can be placed
    world["range"] = 0.001
    runner.update(book, ACCOUNT, NOW)
    assert "EURUSD" in book.positions and book.applied == ["EURUSD|2026-10-30"]


def test_an_update_closes_a_trade_whose_stop_was_touched_by_a_recorded_minute(world):
    world["log"] = [call("2026-10-30", "EURUSD", "Sell")]
    book = runner.livebook.Book(created="2026-10-30T00:00:00+00:00")
    runner.update(book, ACCOUNT, NOW)
    world["bars"] = pd.DataFrame([(1.1, 1.102, 1.1, 1.1)], columns=["Open", "High", "Low", "Close"], index=[pd.Timestamp("2026-10-30 01:05")])
    runner.update(book, ACCOUNT, datetime(2026, 10, 30, 1, 6, tzinfo=timezone.utc))
    assert book.positions == {} and [c.reason for c in book.closed] == ["Stop-loss"]


def test_a_failed_record_never_stops_the_trading_cycle(monkeypatch, capsys):
    from paper_trade import daybook
    from paper_trade.live import tradingview
    from paper_trade.tvdata import client

    def boom(*args, **kwargs):
        raise RuntimeError("TradingView said no")

    monkeypatch.setattr(tradingview, "snapshot", boom)
    monkeypatch.setattr(client, "analysis", boom)
    monkeypatch.setattr(daybook, "from_minute", lambda data: 0)
    REAL_RECORD_DAY()
    out = capsys.readouterr().out
    assert out.count("day record skipped") == 2 and "TradingView said no" in out


def test_the_decision_command_is_built_from_the_account(monkeypatch, tmp_path):
    launched = []
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda command, **kwargs: launched.append(command))
    runner._worker(ACCOUNT, "2026-10-30", None)
    runner._worker(settings.ACCOUNTS["qwen_short"], "2026-10-30", "EURUSD")
    gemma, qwen = launched
    assert gemma[gemma.index("--run-id") + 1] == "live_gemma" and "--only" not in gemma and "--thinking" in gemma
    assert gemma[gemma.index("--tickers") + 1] == ",".join(settings.SHORT_TICKERS) and "--data" in gemma
    assert qwen[qwen.index("--run-id") + 1] == "live_qwen" and qwen[qwen.index("--only") + 1] == "EURUSD" and "--provider" in qwen
    assert (tmp_path / "logs" / "live_gemma.log").exists() and (tmp_path / "logs" / "live_qwen_EURUSD.log").exists()


def test_a_local_model_gets_one_worker_and_a_hosted_model_one_per_pair(monkeypatch, tmp_path):
    workers = []
    monkeypatch.setattr(runner, "_worker", lambda account, today, only: workers.append((account.name, only)))
    monkeypatch.setattr(settings, "state_path", lambda account: tmp_path / account.name / "state.json")
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)

    class Inline:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(runner.threading, "Thread", Inline)
    runner.start_decisions(ACCOUNT, NOW)
    assert workers == [("gemma_short", None)]
    runner.start_decisions(settings.ACCOUNTS["qwen_short"], NOW)
    assert [only for name, only in workers if name == "qwen_short"] == list(settings.SHORT_TICKERS)
    assert json.loads((tmp_path / "gemma_short" / "state.json").read_text()) == {"decisions_started": "2026-10-30"}
    assert runner._state(ACCOUNT) == {"decisions_started": "2026-10-30"}


def test_the_loop_survives_a_failed_update_and_starts_the_days_calls_once_due(monkeypatch, capsys):
    steps = {"updates": 0}
    started = []
    monkeypatch.setattr(config, "READ_ONLY_DATA", False)
    monkeypatch.setattr(runner.livebook, "load", lambda path: runner.livebook.Book())
    monkeypatch.setattr(runner, "decisions_due", lambda account, now: True)
    monkeypatch.setattr(runner, "start_decisions", lambda account, now=None: started.append(account.name))

    def update(book, account, now=None):
        steps["updates"] += 1
        raise ValueError("a half-written log")

    def sleep(seconds):
        if steps["updates"] >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(runner, "update", update)
    monkeypatch.setattr(runner.time, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        runner.loop(ACCOUNT)
    assert steps["updates"] == 2 and started == ["gemma_short", "gemma_short"]
    assert capsys.readouterr().out.count("update failed: ValueError: a half-written log") == 2
