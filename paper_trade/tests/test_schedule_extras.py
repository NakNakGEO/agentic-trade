import dataclasses
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from paper_trade import config, eventlog, scorecard
from paper_trade.dashboard import live_view
from paper_trade.live import keys, memory, runner, schedule, settings
from paper_trade.tvdata import desk

QWEN = settings.ACCOUNTS["qwen_short"]
GEMMA = dataclasses.replace(settings.ACCOUNTS["gemma_short"], call_every_minutes=120)


# --- the key list ---

def test_keys_come_from_the_environment_and_the_env_file_in_order_without_repeats_or_blanks(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# keys\nOPENAI_COMPATIBLE_API_KEY=first\nOPENAI_COMPATIBLE_API_KEY_3 = 'third'\nOPENAI_COMPATIBLE_API_KEY_4=\nOTHER=x\n", encoding="utf-8")
    environ = {"OPENAI_COMPATIBLE_API_KEY_2": "second", "OPENAI_COMPATIBLE_API_KEY_5": "first"}              # a repeat of the first key
    assert keys.load_keys("OPENAI_COMPATIBLE_API_KEY", environ, env_file) == ["first", "second", "third"]
    assert keys.load_keys("NOT_SET", {}, env_file) == [] and keys.load_keys("X", {}, tmp_path / "missing.env") == []


def test_workers_use_the_keys_in_turn_and_with_no_keys_nothing_is_picked():
    assert [keys.pick(["a", "b", "c"], i) for i in range(5)] == ["a", "b", "c", "a", "b"] and keys.pick([], 3) is None


def test_a_round_worker_gets_its_account_name_and_its_own_key(monkeypatch):
    monkeypatch.setattr(keys, "load_keys", lambda name: ["k1", "k2"])
    online = dataclasses.replace(QWEN, call_every_minutes=60)
    first = runner._worker_environment(online, "EURUSD", "live_qwen_s202610300030")
    second = runner._worker_environment(online, "GBPUSD", "live_qwen_s202610300030")
    assert first == {"AGENTIC_ACCOUNT": "qwen_short", "OPENAI_COMPATIBLE_API_KEY": "k1"} and second["OPENAI_COMPATIBLE_API_KEY"] == "k2"
    assert runner._worker_environment(QWEN, "EURUSD", "live_qwen") == {"OPENAI_COMPATIBLE_API_KEY": "k1"}        # no interval: no account name
    assert runner._worker_environment(settings.ACCOUNTS["gemma_short"], None, "live_gemma") == {}                 # a local model has no key
    monkeypatch.setattr(keys, "load_keys", lambda name: [])
    assert runner._worker_environment(QWEN, "EURUSD", "live_qwen") == {}


def test_a_single_worker_rotates_through_the_keys_from_round_to_round(monkeypatch):
    monkeypatch.setattr(keys, "load_keys", lambda name: ["k1", "k2"])
    online = dataclasses.replace(QWEN, call_every_minutes=60)
    picked = [runner._worker_environment(online, None, f"live_qwen_s2026103000{m}")["OPENAI_COMPATIBLE_API_KEY"] for m in ("30", "31")]
    assert picked == ["k1", "k2"] and runner._slot_number("live_qwen") == 0


def test_the_environment_is_handed_to_the_worker_process_and_only_when_there_is_something_to_add(monkeypatch, tmp_path):
    launched = []
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda command, **kwargs: launched.append(kwargs))
    monkeypatch.setattr(keys, "load_keys", lambda name: ["secret-key"])
    runner._worker(QWEN, "2026-10-30", "EURUSD")
    runner._worker(settings.ACCOUNTS["gemma_short"], "2026-10-30", None)
    assert launched[0]["env"]["OPENAI_COMPATIBLE_API_KEY"] == "secret-key" and "env" not in launched[1]
    assert "secret-key" not in (tmp_path / "logs" / "live_qwen_EURUSD.log").read_text()                         # keys are never logged


# --- the switch ---

def test_the_call_interval_is_switched_on_and_off_from_the_environment():
    base = {"gemma_short": settings.ACCOUNTS["gemma_short"], "qwen_short": QWEN}
    on = settings.apply_overrides(base, {"AGENTIC_CALL_EVERY_GEMMA_SHORT": "120", "AGENTIC_CALL_EVERY_QWEN_SHORT": "60"})
    assert (on["gemma_short"].call_every_minutes, on["qwen_short"].call_every_minutes) == (120, 60)
    assert settings.apply_overrides(base, {}) == base and settings.apply_overrides(base, {"AGENTIC_CALL_EVERY_QWEN_SHORT": "0"})["qwen_short"].call_every_minutes is None
    assert settings.apply_overrides(base, {"AGENTIC_CALL_EVERY_QWEN_SHORT": "soon"}) == base                          # not a number: ignored


def test_by_default_no_account_calls_more_than_once_a_day(monkeypatch):
    for name in list(settings.ACCOUNTS):
        monkeypatch.delenv(f"AGENTIC_CALL_EVERY_{name.upper()}", raising=False)
    assert all(a.call_every_minutes is None for a in settings.apply_overrides(settings.ACCOUNTS, {}).values())
    assert all(a.call_every_minutes is None for a in (settings.ACCOUNTS["gemma_short"], QWEN))


# --- the model's own earlier calls ---

@pytest.fixture
def two_rounds(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    eventlog._logs.clear()
    logs = {"live_gemma": [SimpleNamespace(ticker="EURUSD", date="2026-10-29", rating="Sell")],
            "live_gemma_s202610300030": [SimpleNamespace(ticker="EURUSD", date="2026-10-30", rating="Sell"), SimpleNamespace(ticker="GBPUSD", date="2026-10-30", rating="Buy")],
            "live_gemma_s202610300230": [SimpleNamespace(ticker="EURUSD", date="2026-10-30", rating="Hold")]}
    land = {"live_gemma": 1793231400.0, "live_gemma_s202610300030": 1793237000.0, "live_gemma_s202610300230": 1793244200.0}
    for run, decisions in logs.items():
        folder = tmp_path / "backtest" / run
        folder.mkdir(parents=True)
        events = [{"t": land[run] + n, "cell": f"{d.ticker} {d.date}", "kind": "llm", "node": "Portfolio Manager"} for n, d in enumerate(decisions)]
        (folder / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    monkeypatch.setattr("paper_trade.report.load_decisions", lambda run: (logs[run], None) if run in logs else (_ for _ in ()).throw(FileNotFoundError(run)))
    return logs


def test_the_recent_calls_of_a_pair_are_listed_oldest_first_across_rounds(two_rounds):
    calls = memory.recent_calls(GEMMA, "EURUSD")
    assert [rating for t, rating in calls] == ["Sell", "Sell", "Hold"] and calls == sorted(calls)
    assert [r for t, r in memory.recent_calls(GEMMA, "EURUSD", limit=2)] == ["Sell", "Hold"] and memory.recent_calls(GEMMA, "BTC-USD") == []
    text = memory.recent_calls_text(GEMMA, "EURUSD")
    assert "Sell, " in text and text.count("Hold") >= 1 and "judge the market as it is now" in text and memory.recent_calls_text(GEMMA, "BTC-USD") == ""


def test_the_agents_see_their_own_calls_only_in_a_round_based_workers_context(two_rounds, monkeypatch):
    monkeypatch.setattr(settings, "ACCOUNTS", {"gemma_short": GEMMA})
    build = desk.with_rules(lambda ticker, *a, **k: f"context for {ticker}.")
    monkeypatch.delenv("AGENTIC_ACCOUNT", raising=False)
    assert "Your own latest calls" not in build("EURUSD")
    monkeypatch.setenv("AGENTIC_ACCOUNT", "gemma_short")
    assert "Your own latest calls on this instrument" in build("EURUSD") and "Your own latest calls" not in build("BTC-USD")
    assert build(ticker="EURUSD").startswith("context for EURUSD.") and desk.memory_text("") == ""
    monkeypatch.setattr(memory, "recent_calls_text", lambda account, ticker: 1 / 0)
    assert desk.memory_text("EURUSD") == ""                                                                      # a failure here never stops an agent run


# --- the dashboard and the scorecard read every round ---

def test_the_dashboard_shows_the_newest_round_and_the_scorecard_grades_all_of_them(two_rounds, monkeypatch):
    monkeypatch.setattr(settings, "ACCOUNTS", {"gemma_short": GEMMA})
    assert live_view.source_run("live_gemma_short") == "live_gemma_s202610300230" and live_view.source_run("fx9") == "fx9"
    monkeypatch.setattr(settings, "ACCOUNTS", {"gemma_short": dataclasses.replace(GEMMA, call_every_minutes=None)})
    assert live_view.source_run("live_gemma_short") == "live_gemma"
    seen = []
    monkeypatch.setattr(scorecard, "load_calls", lambda run, tickers: seen.append(run) or [])
    monkeypatch.setattr(settings, "ACCOUNTS", {"gemma_short": GEMMA})
    scorecard._cache.clear()
    scorecard.for_account(GEMMA)
    assert seen == ["live_gemma", "live_gemma_s202610300030", "live_gemma_s202610300230"]
