import dataclasses
import json
from types import SimpleNamespace

import pytest

import snapshot_live
from paper_trade.live import book as lb
from paper_trade.live import settings

NOW = "2026-10-30T01:00:00+00:00"
ACCOUNT = dataclasses.replace(settings.ACCOUNTS["gemma_short"], tickers=("EURUSD", "GBPUSD"), call_every_minutes=120)


def trade(side, entry, lot=0.01, ticker="EURUSD"):
    return lb.Position(ticker, side, entry, entry - side * 0.0015, entry + side * 0.003, NOW, "2026-10-30", "Buy" if side > 0 else "Sell", 1.5, 0.1, lot, "2026-10-30T13:00:00+00:00")


def call(ticker, rating, date="2026-10-30"):
    return SimpleNamespace(ticker=ticker, date=date, rating=rating)


def test_one_trade_reads_the_same_whether_it_is_passed_alone_or_in_a_list():
    pos = trade(-1, 1.1)
    alone = snapshot_live.pair_fields([call("EURUSD", "Sell")], pos, [], [], 1.099)
    listed = snapshot_live.pair_fields([call("EURUSD", "Sell")], [pos], [], [], 1.099)
    assert alone == listed and alone["status"] == "open" and alone["side"] == "short" and alone["entry_price"] == 1.1
    assert snapshot_live.pair_fields([], [], [], [], None)["status"] == "waiting"


def test_a_pair_with_several_trades_is_described_as_one_row_with_the_totals():
    positions = [trade(1, 1.1), trade(-1, 1.102, 0.02)]
    row = snapshot_live.pair_fields([call("EURUSD", "Sell")], positions, [], [], 1.101)
    expected = lb.qty("EURUSD", 1.101, 0.01) * (1.101 - 1.1) - lb.qty("EURUSD", 1.101, 0.02) * (1.101 - 1.102)
    assert row["status"] == "open" and row["open_trades"] == 2 and row["open_pnl"] == pytest.approx(round(expected, 2))
    assert "2 trades open on this pair (1 long, 1 short)" in row["fixed_text"] and row["pnl"] == pytest.approx(expected - 0.2)
    assert snapshot_live.pair_fields([], [trade(1, 1.1), trade(1, 1.101)], [], [], None)["side"] == "long"


def test_the_chart_marks_every_open_trade_of_a_pair(monkeypatch):
    book = lb.Book(created=NOW)
    book.positions = {"EURUSD": trade(1, 1.1), "EURUSD#2": trade(-1, 1.102, 0.02)}
    monkeypatch.setattr(snapshot_live.feeds, "intraday_bars", lambda ticker: None)
    rows = snapshot_live.chart_rows(book, ["EURUSD"])
    assert sum(r["kind"] == "entry" for r in rows) == 2 and sum(r["kind"] == "level" for r in rows) == 6
    assert {r["side"] for r in rows if r["kind"] == "level"} == {"long", "short"}


def test_the_monitor_files_read_every_round_and_count_the_trades(monkeypatch, tmp_path):
    book = lb.Book(created=NOW)
    book.positions = {"EURUSD": trade(1, 1.1), "EURUSD#2": trade(-1, 1.102, 0.02)}
    book.history = [{"t": NOW, "equity": 100.0}]
    logs = {"live_gemma": [call("EURUSD", "Buy", "2026-10-29")],
            "live_gemma_s202610300030": [call("EURUSD", "Buy"), call("GBPUSD", "Hold")],
            "live_gemma_s202610300230": [call("EURUSD", "Sell"), call("GBPUSD", "Sell")]}
    monkeypatch.setitem(settings.ACCOUNTS, "gemma_short", ACCOUNT)
    monkeypatch.setattr(snapshot_live.lb, "load", lambda path: book)
    monkeypatch.setattr(snapshot_live.schedule, "all_runs", lambda account: list(logs))
    monkeypatch.setattr(snapshot_live, "load_decisions", lambda run: (logs[run], None))
    monkeypatch.setattr(snapshot_live, "read_meta", lambda run: {"model": run})
    monkeypatch.setattr(snapshot_live, "model_usage", lambda run: {"calls": 7, "tokens_m": 0.1, "errors": 0})
    monkeypatch.setattr(snapshot_live, "feed_rows", lambda run: [])
    monkeypatch.setattr(snapshot_live, "read_pids", lambda: {})
    monkeypatch.setattr(snapshot_live.feeds, "latest_prices", lambda tickers: {"EURUSD": 1.101, "GBPUSD": 1.3})
    monkeypatch.setattr(snapshot_live.feeds, "intraday_bars", lambda ticker: None)
    snapshot_live.main("gemma", tmp_path)
    rows = {r["ticker"]: r for r in json.loads((tmp_path / "pairs.json").read_text())}
    eur, gbp = rows["EURUSD"], rows["GBPUSD"]
    assert eur["decisions"] == 3 and eur["last_rating"] == "Sell" and eur["open_trades"] == 2 and eur["status"] == "open"
    assert gbp["decisions"] == 2 and gbp["ratings"] == "Hold, Sell" and gbp["open_trades"] == 0
    assert eur["run_model"] == "live_gemma_s202610300230" and eur["run_done"] == 2 and eur["run_planned"] == 2      # the newest round: both pairs called
    assert {p.name for p in tmp_path.iterdir()} == {"pairs.json", "equity.json", "chart.json", "feed.json"}
