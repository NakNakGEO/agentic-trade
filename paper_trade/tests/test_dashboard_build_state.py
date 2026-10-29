import json
import time

import pytest

from paper_trade import config
from paper_trade.bridge import settings as rules
from paper_trade.dashboard import live_view, routes, state, sysinfo
from paper_trade.live import book as lb
from paper_trade.live import settings

THIRTEEN = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "BTC-USD", "ETH-USD", "XAUUSD", "AAPL", "NVDA", "MSFT"]
NOW = "2026-10-29T10:00:00+00:00"


@pytest.fixture
def folders(monkeypatch, tmp_path):
    """A run folder the way the loop leaves it: meta, a memory log with calls, and an event log with a pair mid-round."""
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    folder = tmp_path / "backtest" / "live_gemma"
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(json.dumps({
        "run_id": "live_gemma", "tickers": THIRTEEN, "dates": ["2026-10-29"], "provider": "ollama", "model": "ta-gemma12b",
        "started": "2026-10-28T14:05:00", "resumed": "2026-10-29T00:30:00", "baseline_done": 13, "planned_cells": 13}), encoding="utf-8")
    (folder / "trading_memory.md").write_text(
        "[2026-10-29 | EURUSD | Sell | pending]\n[2026-10-29 | AAPL | Buy | pending]\n[2026-10-29 | XAUUSD | Hold | pending]\n", encoding="utf-8")
    now = time.time()
    events = [{"t": now - 30, "cell": "GBPUSD 2026-10-29", "kind": "llm", "node": "Market Analyst", "tokens_in": 100, "tokens_out": 20},
              {"t": now - 5, "cell": "GBPUSD 2026-10-29", "kind": "llm", "node": "News Analyst", "tokens_in": 100, "tokens_out": 20}]
    (folder / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    monkeypatch.setattr(sysinfo, "gpu_stats", lambda: {"gpu": "fake"})
    monkeypatch.setattr(sysinfo, "ollama_stats", lambda since: {"ollama": "fake"})
    monkeypatch.setattr(state, "portfolio_state", lambda run_id, done, mode: {"done": done})
    monkeypatch.setattr(state, "skipped_calls", lambda run_id: {})
    monkeypatch.setattr(live_view, "blotter_for", lambda account: {"positions": [], "orders": [], "history": []})
    return folder


def test_a_live_account_shows_its_own_pairs_todays_round_and_the_shared_decision_feed(folders):
    d = state.build_state("live_gemma_short")
    assert d["run_id"] == "live_gemma_short" and d["system"]["model"] == "ta-gemma12b" and d["system"]["gpu"] == {"gpu": "fake"}
    assert [x["ticker"] for x in d["decisions"]] == ["EURUSD", "XAUUSD"]                     # the stock call is not this account's
    assert (d["cells_done"], d["cells_total"]) == (2, 10) and d["running"] is True and d["current_cell"] == "GBPUSD 2026-10-29"
    rows = {r["ticker"]: r["status"] for r in d["round"]["rows"]}
    assert rows["EURUSD"] == "done" and rows["GBPUSD"] == "working" and rows["BTC-USD"] == "waiting" and len(rows) == 10
    assert d["elapsed_seconds"] == d["round"]["elapsed"] and d["seconds_per_cell"] is None    # the round's clock, not the run's whole life
    assert d["tokens"]["calls"] == 2 and d["current_node"] == "News Analyst" and "short-term" in d["style_note"]
    assert d["portfolio"] == {"done": 2} and d["blotter"] == {"positions": [], "orders": [], "history": []}
    assert d["classes"]["EURUSD"] == "forex"


def test_an_old_run_without_an_account_still_builds_without_a_round(folders, tmp_path):
    other = tmp_path / "backtest" / "fx9"
    other.mkdir()
    (other / "meta.json").write_text(json.dumps({"run_id": "fx9", "tickers": ["AAPL"], "dates": ["2026-09-01", "2026-09-02"], "provider": "openai_compatible", "model": "qwen/x"}), encoding="utf-8")
    d = state.build_state("fx9")
    assert d["round"] is None and d["blotter"] is None and d["cells_total"] == 2 and d["decisions"] == [] and d["portfolio"] is None
    assert d["system"]["local"] is False and d["running"] is False and d["style_note"] is None


def test_a_replayed_run_is_simulated_once_cached_and_an_error_becomes_text(monkeypatch, folders):
    import paper_trade.report as report
    calls = []

    def simulate(run_id, mode):
        calls.append(mode)
        return {"result": run_id}, None

    monkeypatch.setattr(report, "simulate_run", simulate)
    state._cache.clear()
    assert state.simulation("live_gemma", 2, "long_short") == {"result": "live_gemma"}
    assert state.simulation("live_gemma", 2, "long_short") == {"result": "live_gemma"} and calls == ["long_short"]
    monkeypatch.setattr(report, "simulate_run", lambda run_id, mode: (_ for _ in ()).throw(ValueError("no prices yet")))
    state._cache.clear()
    assert state.simulation("live_gemma", 2, "long_only") == "no prices yet"
    assert state.simulation("live_gemma", 2, "no_such_mode") == "no prices yet"            # an unknown mode falls back to the default


def test_the_live_portfolio_rows_carry_levels_lot_results_and_the_account_total(monkeypatch):
    monkeypatch.setattr(rules, "FIXED_LOT", 0.01)
    monkeypatch.setattr(rules, "FIXED_LOT_MAX_TOTAL_RISK", 100.0)
    book = lb.Book(created=NOW)
    book.history = [{"t": NOW, "equity": 100.0}]
    lb.apply_decision(book, "EURUSD", "2026-10-29", "Sell", 1.1, [], NOW, {"EURUSD": 1.1}, 0.001, settings.SHORT)
    book.closed.append(lb.Closed("GBPUSD", 1, 1.3, 1.31, NOW, NOW, "Take-profit", 2.0, "2026-10-29", "Buy", 0.01, 1.29, 1.32))
    monkeypatch.setattr(live_view.lb, "load", lambda path: book)
    prices = {"EURUSD": 1.0995, "GBPUSD": 1.31}
    result = live_view.build_result(book, prices, {}, (None, None), ("EURUSD", "GBPUSD"))
    monkeypatch.setattr(state, "simulation", lambda run_id, done, mode: result)
    value = state.portfolio_state("live_gemma_short", 2)
    rows = {r["ticker"]: r for r in value["tickers"]}
    assert value["live"] is True and set(rows) == {"EURUSD", "GBPUSD"}
    assert rows["EURUSD"]["open"] is True and rows["EURUSD"]["stop"] == pytest.approx(1.1015) and rows["EURUSD"]["lot"] == pytest.approx(0.01)
    assert rows["EURUSD"]["win"] > 0 > rows["EURUSD"]["lose"] and rows["EURUSD"]["deadline"].startswith("2026-10-29T22:00")
    assert rows["GBPUSD"]["wins"] == 1 and rows["GBPUSD"]["realized"] == pytest.approx(2.0) and "stop" not in rows["GBPUSD"]
    assert value["record"]["closed"] == 1 and value["record"]["wins"] == 1 and value["record"]["realized"] == pytest.approx(2.0)
    monkeypatch.setattr(state, "simulation", lambda run_id, done, mode: "the live account has not started yet")
    assert state.portfolio_state("live_gemma_short", 0) == {"error": "the live account has not started yet"}


def test_the_chart_and_candle_routes_pick_the_live_view_for_a_live_account(monkeypatch):
    monkeypatch.setattr(live_view, "live_chart", lambda account, ticker: {"live": account.name, "ticker": ticker})
    assert routes.chart_for("live_qwen_short", {"ticker": ["EURUSD"]}) == {"live": "qwen_short", "ticker": "EURUSD"}
    assert routes.chart_for("live_qwen_short", {})["ticker"] == "EURUSD"                       # the account's first pair
    assert routes.tickers_of("live_qwen_short") == list(settings.SHORT_TICKERS)
    from paper_trade.dashboard import candles
    monkeypatch.setattr(candles, "symbols", lambda: ["symbols"])
    monkeypatch.setattr(candles, "chart", lambda ticker, tf: {"chart": ticker, "tf": tf})
    assert routes.candles_for("x", {}) == {"symbols": ["symbols"]}
    assert routes.candles_for("x", {"ticker": ["BTC-USD"], "tf": ["4h"]}) == {"chart": "BTC-USD", "tf": "4h"}
    assert routes.mode_of({"mode": ["long_only"]}) == "long_only" and routes.mode_of({"mode": ["nope"]}) == config.DEFAULT_MODE


def test_the_scorecard_is_in_the_state_and_a_failure_in_it_never_blanks_the_page(folders, monkeypatch):
    from paper_trade import scorecard
    monkeypatch.setattr(scorecard, "for_account", lambda account: {"model": account.label, "calls": 3, "horizons": {}})
    assert state.build_state("live_gemma_short")["scorecard"] == {"model": "short-term Gemma", "calls": 3, "horizons": {}}
    monkeypatch.setattr(scorecard, "for_account", lambda account: 1 / 0)
    assert state.build_state("live_gemma_short")["scorecard"] is None
