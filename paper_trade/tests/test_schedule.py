import dataclasses
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from paper_trade import config, eventlog
from paper_trade.live import book as lb
from paper_trade.live import runner, schedule, settings

GEMMA = dataclasses.replace(settings.ACCOUNTS["gemma_short"], call_every_minutes=120)
DAILY = settings.ACCOUNTS["gemma_short"]


def utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def test_the_grid_starts_at_the_daily_decision_time_and_steps_by_the_interval():
    assert schedule.latest_slot(utc("2026-10-30T01:00"), 120) == utc("2026-10-30T00:30")
    assert schedule.latest_slot(utc("2026-10-30T02:29"), 120) == utc("2026-10-30T00:30")
    assert schedule.latest_slot(utc("2026-10-30T02:30"), 120) == utc("2026-10-30T02:30")
    assert schedule.latest_slot(utc("2026-10-30T13:12"), 60) == utc("2026-10-30T12:30")
    assert schedule.latest_slot(utc("2026-10-30T13:12"), 1440) == utc("2026-10-30T00:30")
    assert schedule.latest_slot(utc("2026-10-30T00:10"), 120) == utc("2026-10-29T22:30")          # before the anchor: the day before's last slot


def test_a_round_has_its_own_run_folder_named_by_its_slot():
    slot = utc("2026-10-30T02:30")
    assert schedule.slot_id(slot) == "202610300230" and schedule.slot_run_id("live_gemma", slot) == "live_gemma_s202610300230"
    assert schedule.slot_of("live_gemma_s202610300230") == "202610300230" and schedule.slot_of("live_gemma") == ""


@pytest.fixture
def folders(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    eventlog._logs.clear()
    for name in ("live_gemma", "live_gemma_s202610300030", "live_gemma_s202610300230", "live_qwen_s202610300030", "live_gemma_sxyz", "other"):
        (tmp_path / "backtest" / name).mkdir(parents=True)
    return tmp_path


def test_the_rounds_of_a_run_are_found_oldest_first_and_other_runs_are_ignored(folders):
    assert schedule.slot_runs("live_gemma") == ["live_gemma_s202610300030", "live_gemma_s202610300230"]
    assert schedule.all_runs(GEMMA) == ["live_gemma", "live_gemma_s202610300030", "live_gemma_s202610300230"]
    assert schedule.all_runs(DAILY) == ["live_gemma"]                                  # no interval: the old single run only


def write_events(folder, cell, times):
    (folder / "events.jsonl").write_text("\n".join(json.dumps({"t": t, "cell": cell, "kind": "llm", "node": "Trader"}) for t in times) + "\n", encoding="utf-8")


def test_a_round_is_running_until_every_pair_has_a_call_or_its_work_stalls(folders, monkeypatch):
    run, started, now = "live_gemma_s202610300030", utc("2026-10-30T00:30"), utc("2026-10-30T01:00")
    tickers = ["EURUSD", "GBPUSD"]
    assert schedule.round_state(run, tickers, None, now) == "none"
    assert schedule.round_state(run, tickers, started, started + timedelta(minutes=5)) == "running"       # just started: no events yet
    assert schedule.round_state(run, tickers, started, started + timedelta(minutes=30)) == "over"          # never showed up
    write_events(folders / "backtest" / run, "EURUSD 2026-10-30", [now.timestamp() - 60])
    assert schedule.round_state(run, tickers, started, now) == "running"
    assert schedule.round_state(run, tickers, started, now + timedelta(minutes=30)) == "over"              # stalled
    monkeypatch.setattr(schedule, "logged_cells", lambda run_id: 2)
    assert schedule.round_state(run, tickers, started, now) == "over"                                      # both pairs have their call


def test_the_pace_shows_how_long_rounds_take_which_slots_were_skipped_and_whether_the_model_is_too_slow(folders, monkeypatch):
    (folders / "backtest" / "live_gemma_s202610300630").mkdir()
    account = dataclasses.replace(GEMMA, tickers=("EURUSD",))
    assert schedule.pace(DAILY) is None and schedule.pace(dataclasses.replace(account, decisions_run_id="live_none")) is None   # no interval / no rounds yet
    monkeypatch.setattr(schedule, "logged_cells", lambda run: 1)
    base = 1_800_000_000
    runs = ("live_gemma_s202610300030", "live_gemma_s202610300230", "live_gemma_s202610300630")
    for run, minutes in zip(runs, (20, 30, 150)):
        write_events(folders / "backtest" / run, "EURUSD 2026-10-30", [base, base + minutes * 60])
    assert schedule.pace(account) == {"every": 120, "typical": 30, "rounds": 3, "skipped": 1, "too_slow": False}      # 02:30 -> 06:30 skipped the 04:30 slot
    eventlog._logs.clear()
    for run in runs:
        write_events(folders / "backtest" / run, "EURUSD 2026-10-30", [base, base + 150 * 60])
    slow = schedule.pace(account)
    assert slow["typical"] == 150 and slow["too_slow"] is True
    monkeypatch.setattr(schedule, "logged_cells", lambda run: 0)                                                       # unfinished rounds say nothing about speed
    assert schedule.pace(account)["typical"] is None


def test_a_round_that_started_late_gets_its_start_up_time_from_when_it_really_started(folders):
    """Found by a real round: the grace was counted from the slot time, so a round that had waited was judged over at once."""
    run, slot, began = "live_gemma_s202610291230", utc("2026-10-29T12:30"), utc("2026-10-29T13:28")
    tickers = ["EURUSD"]
    assert schedule.round_state(run, tickers, slot, began + timedelta(seconds=30)) == "over"                 # counted from the slot: wrong
    assert schedule.round_state(run, tickers, began, began + timedelta(seconds=30)) == "running"             # counted from the real start
    assert schedule.busy(GEMMA, slot, began + timedelta(seconds=30), began) is True
    assert schedule.busy(GEMMA, slot, began + timedelta(minutes=15), began) is False
    assert schedule.due(GEMMA, utc("2026-10-29T14:31"), slot, began) == utc("2026-10-29T14:30")             # an hour later the next slot starts


def test_a_round_is_due_on_the_grid_never_while_the_last_one_works_and_then_only_the_newest_starts(folders, monkeypatch):
    assert schedule.due(DAILY, utc("2026-10-30T03:00"), None) is None                    # no interval: this module does nothing
    assert schedule.due(GEMMA, utc("2026-10-30T01:00"), None) == utc("2026-10-30T00:30")
    assert schedule.due(GEMMA, utc("2026-10-30T01:00"), utc("2026-10-30T00:30")) is None   # this slot was already served
    state = {"running": False}
    monkeypatch.setattr(schedule, "round_state", lambda run, tickers, started, now: "running" if state["running"] else "over")
    last = utc("2026-10-30T00:30")
    state["running"] = True
    assert schedule.due(GEMMA, utc("2026-10-30T02:40"), last) is None                    # the slot arrived but the last round is still working
    state["running"] = False
    assert schedule.due(GEMMA, utc("2026-10-30T06:45"), last) == utc("2026-10-30T06:30")  # a long gap: only the newest slot, no replay of 02:30 and 04:30


def test_the_loop_follows_the_grid_and_a_round_goes_to_its_own_run_with_its_slot_date(monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(runner, "_worker", lambda account, today, only, run_id=None: started.append((today, only, run_id)))
    monkeypatch.setattr(settings, "state_path", lambda account: tmp_path / "state.json")
    monkeypatch.setattr(schedule, "round_state", lambda *args: "over")
    assert runner.decisions_due(GEMMA, utc("2026-10-30T00:29")) is True and runner._last_slot(GEMMA) is None   # 22:30 on the 29th is the newest slot
    runner.start_decisions(GEMMA, utc("2026-10-30T00:31"))
    assert started == [("2026-10-30", None, "live_gemma_s202610300030")]
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["last_slot"] == "2026-10-30T00:30:00+00:00" and saved["last_started"].startswith("2026-10-30T00:31")
    assert runner._last_started(GEMMA) == utc("2026-10-30T00:31")
    assert runner.decisions_due(GEMMA, utc("2026-10-30T01:00")) is False and runner.decisions_due(GEMMA, utc("2026-10-30T02:30")) is True


# --- decisions from several rounds in one account ---

def test_a_pair_can_have_a_call_in_every_round_of_a_day_and_each_is_acted_on_once():
    book = lb.Book(created="2026-10-30T00:00:00+00:00")
    args = dict(price=1.1, daily_bars=[], when="2026-10-30T01:00:00+00:00", prices={"EURUSD": 1.1}, average_range=0.001, style=settings.SHORT)
    lb.apply_decision(book, "EURUSD", "2026-10-30", "Sell", slot="202610300030", **args)
    lb.apply_decision(book, "EURUSD", "2026-10-30", "Sell", slot="202610300030", **args)          # the same round again: ignored
    assert book.applied == ["EURUSD|2026-10-30|202610300030"] and book.positions["EURUSD"].side == -1
    lb.apply_decision(book, "EURUSD", "2026-10-30", "Buy", slot="202610300230", **{**args, "price": 1.099})
    assert book.applied[-1] == "EURUSD|2026-10-30|202610300230" and book.positions["EURUSD"].side == 1
    assert [c.reason for c in book.closed] == ["New call"]                                        # the later round flipped it


def test_decisions_are_read_from_the_daily_run_and_every_round_in_order(monkeypatch, folders):
    logs = {"live_gemma": [SimpleNamespace(ticker="EURUSD", date="2026-10-29", rating="Sell")],
            "live_gemma_s202610300030": [SimpleNamespace(ticker="EURUSD", date="2026-10-30", rating="Sell"), SimpleNamespace(ticker="AAPL", date="2026-10-30", rating="Buy")],
            "live_gemma_s202610300230": [SimpleNamespace(ticker="EURUSD", date="2026-10-30", rating="Buy")]}

    def load(run_id):
        if run_id not in logs:
            raise FileNotFoundError(run_id)
        return logs[run_id], None

    monkeypatch.setattr("paper_trade.report.load_decisions", load)
    book = lb.Book()
    found = runner.new_decisions(book, GEMMA)
    assert [(d.ticker, d.rating, d.slot) for d in found] == [("EURUSD", "Sell", ""), ("EURUSD", "Sell", "202610300030"), ("EURUSD", "Buy", "202610300230")]   # no stock
    assert [d.key for d in found][1] == "EURUSD|2026-10-30|202610300030"
    book.applied = [found[0].key, found[1].key]
    assert [d.slot for d in runner.new_decisions(book, GEMMA)] == ["202610300230"]
    assert [d.slot for d in runner.new_decisions(lb.Book(), DAILY)] == [""]                       # an account without an interval reads only its daily run
    runner._skip_old_calls(book, GEMMA, "2026-10-30")
    assert "EURUSD|2026-10-29" in book.applied                                                    # yesterday's call is skipped for a new account
