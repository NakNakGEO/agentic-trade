import subprocess
import sys
import time

import pytest

from paper_trade import config
from paper_trade.live import settings, tradingview, tv_guard

sys.path.insert(0, str(config.ROOT / "tvmcp"))
import gate  # noqa: E402  (the standard-library gate that tvmcp/feed.py and engine_feed.py share)


@pytest.fixture(autouse=True)
def folders(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "LOCK", tmp_path / "fetch.lock")
    monkeypatch.setattr(gate, "RECENT", tmp_path / "recent")
    monkeypatch.setattr(settings, "TV_COOLDOWN_PATH", tmp_path / "cooldown.txt")


def test_callers_asking_for_the_same_thing_share_one_fetch():
    calls = []
    first = gate.serve({"mode": "analysis"}, 60, lambda: calls.append(1) or '{"n": 1}')
    second = gate.serve({"mode": "analysis"}, 60, lambda: calls.append(1) or '{"n": 2}')
    other = gate.serve({"mode": "screener"}, 60, lambda: calls.append(1) or '{"n": 3}')
    assert (first, second, other) == ('{"n": 1}', '{"n": 1}', '{"n": 3}') and len(calls) == 2


def test_an_old_answer_is_fetched_again():
    gate.serve({"a": 1}, 60, lambda: "old")
    path = next(gate.RECENT.iterdir())
    past = time.time() - 120
    import os
    os.utime(path, (past, past))
    assert gate.serve({"a": 1}, 60, lambda: "new") == "new"


def test_a_request_waits_while_another_is_running_and_gives_up_after_the_limit(monkeypatch):
    gate.LOCK.write_text("")                               # another process is mid-request
    monkeypatch.setattr(gate, "LOCK_WAIT_SECONDS", 1)
    with pytest.raises(TimeoutError):
        gate.serve({"a": 2}, 60, lambda: "never")
    assert gate.LOCK.exists()                              # the other process's lock is left alone


def test_a_lock_left_by_a_dead_process_is_cleared(monkeypatch):
    gate.LOCK.write_text("")
    long_ago = time.time() - gate.LOCK_STALE_SECONDS - 5
    import os
    os.utime(gate.LOCK, (long_ago, long_ago))
    assert gate.serve({"a": 3}, 60, lambda: "ran") == "ran" and not gate.LOCK.exists()


def test_the_lock_is_released_when_the_fetch_fails():
    with pytest.raises(RuntimeError):
        gate.serve({"a": 4}, 60, lambda: (_ for _ in ()).throw(RuntimeError("refused")))
    assert not gate.LOCK.exists() and gate.serve({"a": 4}, 60, lambda: "after") == "after"


def test_pauses_start_short_double_and_cap_and_a_success_clears_them():
    tv_guard.failed()
    first = tv_guard.seconds_left()
    for _ in range(6):
        tv_guard.failed()
    assert settings.TV_COOLDOWN_SECONDS - 2 <= first <= settings.TV_COOLDOWN_SECONDS
    assert tv_guard.seconds_left() == pytest.approx(settings.TV_COOLDOWN_MAX_SECONDS, abs=2)
    with pytest.raises(tv_guard.CoolingDown):
        tv_guard.check()
    tv_guard.succeeded()
    assert tv_guard.seconds_left() == 0
    tv_guard.check()


def test_the_failure_reason_keeps_what_tradingview_answered():
    stderr = ("[tradingview_mcp] socket default timeout set to 20.0s\n"
              "[tradingview_mcp] transient TA error (attempt 1/3, slept 0.0s): JSONDecodeError('Expecting value')\n"
              "Traceback (most recent call last):\n  ...\nRuntimeError: Upstream TradingView scanner returned errors")
    text = tv_guard.why(stderr)
    assert "JSONDecodeError" in text and text.endswith("returned errors") and tv_guard.why("") == "no error text"


def test_a_failed_snapshot_is_reported_once_not_once_per_pair(monkeypatch):
    runs = []

    def refused(*args, **kwargs):
        runs.append(1)
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="[tradingview_mcp] transient TA error: boom")

    monkeypatch.setattr(tradingview.subprocess, "run", refused)
    monkeypatch.setitem(tradingview._cache, "at", 0.0)
    monkeypatch.setitem(tradingview._cache, "data", None)
    monkeypatch.setitem(tradingview._cache, "error", None)
    monkeypatch.setattr(settings, "TV_SNAPSHOT_PATH", gate.RECENT.parent / "snapshot.json")
    for _ in range(3):
        with pytest.raises(Exception, match="boom|slow down"):
            tradingview.snapshot()
    assert len(runs) == 1
