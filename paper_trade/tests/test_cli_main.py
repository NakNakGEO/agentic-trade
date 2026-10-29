import subprocess
import sys
from types import SimpleNamespace

import pytest

from paper_trade import cli, config


def test_decide_splits_tickers_builds_the_model_options_and_runs_the_grid(monkeypatch):
    import paper_trade.decide as decide_module
    import tradingagents.backtest as backtest
    seen = {}
    monkeypatch.setattr(backtest, "iter_grid", lambda start, end, every: [f"{start}..{end}/{every}"])
    monkeypatch.setattr(decide_module, "decide", lambda *args, **kwargs: seen.update(args=args, kwargs=kwargs))
    code = cli.main(["decide", "--tickers", "eurusd, btc-usd,", "--start", "2026-10-29", "--end", "2026-10-29", "--every", "1", "--run-id", "r1",
                     "--provider", "openai_compatible", "--model", "m", "--backend-url", "https://x/v1", "--max-tokens", "8000",
                     "--effort", "medium", "--only", "eurusd"])
    tickers, dates, run_id, analysts, llm = seen["args"]
    assert code == 0 and tickers == ["EURUSD", "BTC-USD"] and dates == ["2026-10-29..2026-10-29/1"] and run_id == "r1"
    assert analysts == config.REPLAY_ANALYSTS and llm["deep_think_llm"] == "m" and llm["max_tokens"] == 8000
    assert seen["kwargs"] == {"no_thinking": False, "only": ["EURUSD"], "thinking": False, "effort": "medium", "data": "tradingview"}
    cli.main(["decide", "--start", "a", "--end", "b", "--run-id", "r2", "--live", "--no-thinking"])
    assert seen["args"][3] == config.LIVE_ANALYSTS and seen["kwargs"]["no_thinking"] is True and seen["kwargs"]["only"] is None


def test_compare_prints_and_can_save_the_report(monkeypatch, tmp_path, capsys):
    import paper_trade.compare as compare
    monkeypatch.setattr(compare, "compare_runs", lambda a, b, cash, la, lb: f"{la} vs {lb} on {cash:g}")
    out = tmp_path / "deep" / "report.txt"
    assert cli.main(["compare", "--a", "x", "--b", "y", "--label-a", "G", "--label-b", "Q", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == "G vs Q on 100\n" and "G vs Q" in capsys.readouterr().out


def test_simulate_live_and_bridge_are_handed_to_their_modules(monkeypatch, capsys):
    import paper_trade.bridge.cli as bridge_cli
    import paper_trade.live.cli as live_cli
    import paper_trade.report as report
    monkeypatch.setattr(report, "run_simulation", lambda run_id, cash, mode: f"sim {run_id} {cash:g} {mode}")
    monkeypatch.setattr(live_cli, "run", lambda args: 7 if args.action == "status" else 0)
    monkeypatch.setattr(bridge_cli, "run", lambda args: 9)
    assert cli.main(["simulate", "--run-id", "r", "--mode", "long_only"]) == 0 and "sim r 100 long_only" in capsys.readouterr().out
    assert cli.main(["live", "--account", "qwen_short", "status"]) == 7
    assert cli.main(["bridge", "--run-id", "r"]) == 9                       # planning only: nothing is sent without --send


def test_a_command_is_required_and_data_can_only_be_tradingview():
    with pytest.raises(SystemExit):
        cli.main([])
    with pytest.raises(SystemExit):
        cli.main(["decide", "--start", "a", "--end", "b", "--run-id", "r", "--data", "other"])


def test_the_module_can_be_run_as_a_program():
    done = subprocess.run([sys.executable, "-m", "paper_trade", "live", "--help"], cwd=config.ROOT, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and "gemma_short" in done.stdout and "qwen_short" in done.stdout
