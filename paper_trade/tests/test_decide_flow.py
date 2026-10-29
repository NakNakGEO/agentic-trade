import json
from types import SimpleNamespace

import pytest

from paper_trade import config, decide

PAIRS = ["EURUSD", "GBPUSD", "BTC-USD", "XAUUSD"]


@pytest.fixture
def fake_framework(monkeypatch, tmp_path):
    """Run the whole decide() flow with a fake agent run, so nothing talks to a model."""
    import tradingagents.backtest as backtest
    import paper_trade.tvdata as tvdata

    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    calls = []

    def run_backtest(group, dates, settings, asset_type, selected_analysts, run_id, progress):
        calls.append({"group": list(group), "dates": dates, "kind": asset_type, "analysts": selected_analysts, "settings": settings})
        for ticker in group:
            progress(1, len(group), ticker, dates[0])
        failures = [(group[0], dates[0], "model said no")] if calls[-1]["kind"] == "crypto" else []
        return SimpleNamespace(cells_run=len(group), skipped=0, failures=failures)

    monkeypatch.setattr(backtest, "run_backtest", run_backtest)
    monkeypatch.setattr(tvdata, "use_tradingview", lambda settings: {**settings, "patched": True})
    return calls


def test_every_group_of_pairs_is_run_once_and_the_run_records_what_it_did(fake_framework, tmp_path, capsys):
    tally = decide.decide(PAIRS, ["2026-10-29"], "demo", thinking=True)
    assert sorted(t for call in fake_framework for t in call["group"]) == sorted(PAIRS)
    assert all(call["settings"].get("patched") for call in fake_framework)                    # our data layer is installed
    assert tally["ran"] == len(PAIRS) and tally["failed"] == [("BTC-USD", "2026-10-29", "model said no")]
    meta = json.loads((tmp_path / "backtest" / "demo" / "meta.json").read_text())
    assert meta["tickers"] == PAIRS and meta["dates"] == ["2026-10-29"] and meta["thinking"] is True
    assert meta["market_data"] == "tradingview" and meta["planned_cells"] == len(PAIRS)
    log = (tmp_path / "backtest" / "demo" / "progress.log").read_text()
    assert "date 1/1 2026-10-29" in log and "FAILED BTC-USD 2026-10-29: model said no" in log and "done: ran=4" in log
    assert "cell 1/" in capsys.readouterr().out


def test_only_limits_this_process_but_the_run_still_lists_every_pair(fake_framework, tmp_path):
    decide.decide(PAIRS, ["2026-10-29"], "demo", only=["EURUSD"], thinking=True)
    assert [t for call in fake_framework for t in call["group"]] == ["EURUSD"]
    meta = json.loads((tmp_path / "backtest" / "demo" / "meta.json").read_text())
    assert meta["tickers"] == PAIRS and meta["planned_cells"] == len(PAIRS)
    assert decide.read_meta("demo")["resumed"] and decide.logged_cells("demo") == 0


def test_a_run_that_is_resumed_keeps_its_first_start_and_counts_what_was_already_done(fake_framework, tmp_path):
    decide.decide(PAIRS, ["2026-10-29"], "demo", thinking=True)
    first = decide.read_meta("demo")["started"]
    (tmp_path / "backtest" / "demo" / "trading_memory.md").write_text("[2026-10-29 | EURUSD | Sell | pending]\n[2026-10-29 | GBPUSD | Buy | pending]\n", encoding="utf-8")
    decide.decide(PAIRS, ["2026-10-29"], "demo", thinking=True)
    meta = decide.read_meta("demo")
    assert meta["started"] == first and meta["baseline_done"] == 2 and decide.logged_cells("demo") == 2


def test_the_thinking_options_are_passed_to_the_model_switches(fake_framework, monkeypatch):
    import paper_trade.nothink as nothink
    seen = []
    monkeypatch.setattr(nothink, "set_reasoning_effort", lambda provider, effort: seen.append(("effort", provider, effort)) or True)
    monkeypatch.setattr(nothink, "disable_thinking", lambda provider: seen.append(("off", provider)) or True)
    decide.decide(PAIRS[:1], ["2026-10-29"], "a", effort="medium")
    decide.decide(PAIRS[:1], ["2026-10-29"], "b")                                    # a local model defaults to thinking off
    decide.decide(PAIRS[:1], ["2026-10-29"], "c", thinking=True)
    assert seen == [("effort", "ollama", "medium"), ("off", "ollama")]
    assert decide.read_meta("a")["thinking"] is True and decide.read_meta("b")["thinking"] is False and decide.read_meta("c")["thinking"] is True
    assert decide.read_meta("a")["effort"] == "medium"


def test_a_hosted_provider_gets_a_retry_budget_and_the_model_override(fake_framework):
    decide.decide(PAIRS[:1], ["2026-10-29"], "h", thinking=True, llm={"llm_provider": "openai_compatible", "quick_think_llm": "qwen/x", "deep_think_llm": "qwen/x"})
    settings = fake_framework[0]["settings"]
    assert settings["llm_provider"] == "openai_compatible" and settings["llm_max_retries"] == config.HOSTED_LLM_RETRIES
    assert decide.read_meta("h")["model"] == "qwen/x"


def test_weekend_dates_skip_the_assets_that_do_not_trade_them(fake_framework):
    decide.decide(["EURUSD", "BTC-USD"], ["2026-10-31"], "weekend", thinking=True)          # a Saturday
    assert [t for call in fake_framework for t in call["group"]] == ["BTC-USD"]
    assert decide.read_meta("weekend")["planned_cells"] == 1


def test_a_missing_run_has_no_meta_and_no_cells(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    assert decide.read_meta("nope") == {} and decide.logged_cells("nope") == 0
    (tmp_path / "backtest" / "bom").mkdir(parents=True)
    (tmp_path / "backtest" / "bom" / "meta.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"run_id": "bom"}).encode())
    assert decide.read_meta("bom") == {"run_id": "bom"}                                      # a Windows BOM is tolerated
