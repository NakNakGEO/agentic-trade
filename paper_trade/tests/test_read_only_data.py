import json
import os
import time
from datetime import datetime, timezone

import pytest

from paper_trade import config, daybook
from paper_trade.daybook import settings as daybook_settings
from paper_trade.live import runner, settings, tradingview
from paper_trade.tvdata import client

SNAPSHOT = {"fetched_at": "2026-10-29T10:00:00+00:00", "symbols": {"EURUSD": {"m1": {"open": 1.1, "high": 1.1, "low": 1.1, "close": 1.1}}}}


@pytest.fixture
def read_only(monkeypatch, tmp_path):
    """A test copy: it reads the live folder (here a temp folder) and must never write to it or ask TradingView."""
    monkeypatch.setattr(config, "READ_ONLY_DATA", True)
    monkeypatch.setattr(settings, "TV_SNAPSHOT_PATH", tmp_path / "tv_snapshot.json")
    monkeypatch.setattr(settings, "TV_CANDLE_DIR", tmp_path / "tv_candles")
    monkeypatch.setattr(client, "CACHE_DIR", tmp_path / "tv_cache")
    monkeypatch.setattr(daybook_settings, "DIR", tmp_path / "daybook")

    def no_fetch(*args, **kwargs):
        raise AssertionError("a read-only copy must never ask TradingView")

    monkeypatch.setattr(tradingview.subprocess, "run", no_fetch)
    monkeypatch.setattr(client.subprocess, "run", no_fetch)
    return tmp_path


def test_the_switch_follows_the_environment_variable():
    assert config.READ_ONLY_DATA == bool(os.environ.get("AGENTIC_LIVE_DATA_DIR"))
    assert config.DATA_DIR == (config.Path(os.environ["AGENTIC_LIVE_DATA_DIR"]) if config.READ_ONLY_DATA else config.RUNS_DIR)


def test_the_snapshot_is_read_from_the_live_file_and_never_fetched(read_only):
    (read_only / "tv_snapshot.json").write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    assert tradingview.snapshot() == SNAPSHOT
    assert tradingview.latest_price("EURUSD") == 1.1


def test_a_missing_or_stale_snapshot_is_an_error_not_a_fetch(read_only, monkeypatch):
    with pytest.raises(RuntimeError, match="has not written"):
        tradingview.snapshot()
    path = read_only / "tv_snapshot.json"
    path.write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    old = time.time() - settings.READ_ONLY_MAX_AGE_SECONDS - 60
    os.utime(path, (old, old))
    with pytest.raises(RuntimeError, match="is the live loop running"):
        tradingview.snapshot()


def test_no_candles_are_recorded(read_only):
    (read_only / "tv_snapshot.json").write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    tradingview.record_minute("2026-10-29T10:00:00+00:00")
    assert not (read_only / "tv_candles").exists()


def test_the_daily_record_is_not_written(read_only):
    analysis = {"fetched_at": "2026-10-29T10:00:00+00:00", "analysis": {"EURUSD": {"1d": {"open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15}}}}
    assert daybook.from_analysis(analysis) == 0 and daybook.from_minute(SNAPSHOT) == 0
    assert not (read_only / "daybook").exists()


def test_the_analysis_cache_is_read_however_old_and_never_refreshed(read_only):
    (read_only / "tv_cache").mkdir()
    path = read_only / "tv_cache" / "analysis.json"
    path.write_text(json.dumps({"analysis": {"EURUSD": {}}}), encoding="utf-8")
    old = time.time() - 86_400
    os.utime(path, (old, old))
    assert client.analysis() == {"analysis": {"EURUSD": {}}}
    path.unlink()
    with pytest.raises(RuntimeError, match="no 'analysis' reply yet"):
        client.analysis()


def test_the_loop_records_nothing_and_a_test_copy_only_starts_model_calls_when_told(read_only, monkeypatch):
    calls = []
    monkeypatch.setattr(runner.feeds, "record_minute", lambda stamp: calls.append("minute"))
    monkeypatch.setattr(runner, "_record_day", lambda: calls.append("day"))
    monkeypatch.setattr(runner.feeds, "latest_prices", lambda tickers: {})
    monkeypatch.setattr(runner.livebook, "save", lambda book, path: None)
    account = settings.ACCOUNTS["gemma_short"]
    runner.update(runner.livebook.Book(), account, datetime(2026, 10, 30, 0, 31, tzinfo=timezone.utc))
    assert calls == []
    started = []
    monkeypatch.setattr(runner, "start_decisions", lambda acct, now=None: started.append(acct.name))
    monkeypatch.setattr(runner, "decisions_due", lambda acct, now: True)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt))
    monkeypatch.setattr(runner.livebook, "load", lambda path: runner.livebook.Book())
    for allowed, expected in ((False, []), (True, ["gemma_short"])):
        monkeypatch.setattr(config, "ALLOW_TEST_ROUNDS", allowed)
        started.clear()
        with pytest.raises(KeyboardInterrupt):
            runner.loop(account)
        assert started == expected
