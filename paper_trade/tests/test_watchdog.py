import json
import time
from types import SimpleNamespace

import pytest

from paper_trade import config
from paper_trade.live import settings, watchdog
from paper_trade.live.watchdog import Process

LOOP = "C:\\x\\python.exe -W ignore -m paper_trade live --account {} loop"


def procs(*names):
    return [Process(100 + i, LOOP.format(name)) for i, name in enumerate(names)]


def test_the_listing_is_parsed_whether_it_has_none_one_or_many_processes():
    assert watchdog.parse_processes("") == [] and watchdog.parse_processes("  \n") == []
    assert watchdog.parse_processes('{"ProcessId": 5, "CommandLine": "a b"}') == [Process(5, "a b")]
    many = watchdog.parse_processes(json.dumps([{"ProcessId": 1, "CommandLine": None}, {"ProcessId": 2, "CommandLine": "x"}]))
    assert many == [Process(1, ""), Process(2, "x")]


def test_a_loop_is_found_by_its_account_and_both_of_its_processes_count():
    processes = procs("gemma_short") + [Process(7, LOOP.format("gemma_short")), Process(8, "python -m paper_trade.dashboard --run live_gemma_short")]
    assert watchdog.loop_pids(processes, "gemma_short") == [100, 7] and watchdog.loop_pids(processes, "qwen_short") == []
    assert watchdog.dashboard_running(processes) and not watchdog.dashboard_running(procs("qwen_short"))


def test_the_plan_starts_what_is_missing_restarts_what_is_hung_and_leaves_the_rest():
    both = procs("gemma_short", "qwen_short")
    assert watchdog.plan(both, {"gemma_short": 30, "qwen_short": 30}) == {"gemma_short": "ok", "qwen_short": "ok"}
    assert watchdog.plan(procs("qwen_short"), {"gemma_short": 30, "qwen_short": 30})["gemma_short"] == "start"
    assert watchdog.plan(both, {"gemma_short": 30, "qwen_short": 5000})["qwen_short"] == "restart"
    assert watchdog.plan(both, {"gemma_short": None, "qwen_short": 30})["gemma_short"] == "ok"        # never saved yet: give it time
    assert watchdog.plan(both, {"gemma_short": 700, "qwen_short": 30}, stale=900)["gemma_short"] == "ok"


@pytest.fixture
def machine(monkeypatch, tmp_path):
    state = {"processes": [], "ages": {}, "killed": [], "started": []}
    monkeypatch.setattr(config, "IS_TEST_COPY", False)
    monkeypatch.setattr(config, "READ_ONLY_DATA", False)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(watchdog, "running_processes", lambda: list(state["processes"]))
    monkeypatch.setattr(watchdog, "book_age", lambda account: state["ages"].get(account.name))
    monkeypatch.setattr(watchdog, "kill", lambda pids: state["killed"].extend(pids))
    monkeypatch.setattr(watchdog, "start_loop", lambda name: state["started"].append(name) or 900 + len(state["started"]))
    monkeypatch.setattr(watchdog, "start_dashboard", lambda: state["started"].append("dashboard") or 999)
    return state


def test_a_pass_fixes_only_what_needs_fixing_and_says_so(machine):
    machine["processes"] = procs("qwen_short")
    machine["ages"] = {"qwen_short": 4000}
    said = watchdog.check(dashboard=True)
    assert machine["killed"] == [100]                                         # only the hung loop is killed
    assert sorted(machine["started"]) == ["dashboard", "gemma_short", "qwen_short"]
    assert any(line.startswith("qwen_short: restart") for line in said) and any(line.startswith("gemma_short: start") for line in said)
    assert any(line.startswith("dashboard: start") for line in said)


def test_healthy_loops_and_a_dry_run_change_nothing(machine):
    machine["processes"] = procs("gemma_short", "qwen_short")
    machine["ages"] = {"gemma_short": 20, "qwen_short": 20}
    assert watchdog.check() == [] and machine["started"] == [] and machine["killed"] == []
    machine["processes"] = []
    said = watchdog.check(dry_run=True)
    assert len(said) == 2 and all("(dry run)" in line for line in said) and machine["started"] == []


def test_a_test_copy_never_touches_the_live_loops(machine, monkeypatch):
    monkeypatch.setattr(config, "IS_TEST_COPY", True)
    assert "test copy" in watchdog.check()[0] and machine["started"] == [] and machine["killed"] == []
    monkeypatch.setattr(config, "IS_TEST_COPY", False)
    monkeypatch.setattr(config, "READ_ONLY_DATA", True)
    assert "test copy" in watchdog.check()[0]


def test_a_started_loop_is_detached_logged_and_written_to_the_pid_list(monkeypatch, tmp_path):
    launched = {}

    class Popen:
        pid = 4242

        def __init__(self, command, **kwargs):
            launched.update(command=command, kwargs=kwargs)

    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(watchdog.subprocess, "Popen", Popen)
    assert watchdog.start_loop("qwen_short") == 4242
    assert launched["command"][1:] == ["-W", "ignore", "-m", "paper_trade", "live", "--account", "qwen_short", "loop"]
    assert launched["kwargs"]["cwd"] == tmp_path and launched["kwargs"]["creationflags"] == watchdog.DETACHED
    assert (tmp_path / "logs" / "live_loop_qwen_short.err.log").exists()
    assert (tmp_path / "logs" / "pids.txt").read_text() == "live_loop_qwen_short 4242\n"
    assert watchdog.start_dashboard() == 4242 and launched["command"][1:3] == ["-m", "paper_trade.dashboard"]


def test_the_age_of_a_book_is_its_time_since_last_saved(monkeypatch, tmp_path):
    account = settings.ACCOUNTS["gemma_short"]
    monkeypatch.setattr(settings, "book_path", lambda a: tmp_path / "book.json")
    assert watchdog.book_age(account) is None
    (tmp_path / "book.json").write_text("{}")
    assert -1 < watchdog.book_age(account) < 5 and watchdog.book_age(account, now=time.time() + 100) > 99


def test_the_command_runs_and_reports(monkeypatch, capsys):
    monkeypatch.setattr(watchdog, "check", lambda dashboard, dry_run, stale: [])
    assert watchdog.run(SimpleNamespace(dashboard=False, dry_run=True, stale_seconds=600)) == 0 and "all loops healthy" in capsys.readouterr().out
    monkeypatch.setattr(watchdog, "check", lambda dashboard, dry_run, stale: ["qwen_short: start -> pid 1"])
    watchdog.run(SimpleNamespace(dashboard=True, dry_run=False, stale_seconds=600))
    assert "qwen_short: start -> pid 1" in capsys.readouterr().out
