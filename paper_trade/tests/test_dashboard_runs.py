import json
import os

from paper_trade import config
from paper_trade.dashboard.routes import list_runs


def _make_run(root, name, meta, decisions=0, touched=None):
    folder = root / "backtest" / name
    folder.mkdir(parents=True)
    if meta is not None:
        (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    log = "".join(f"[2026-09-02 | T{i} | Buy | pending]\n\nDECISION:\nx\n<!-- ENTRY_END -->\n" for i in range(decisions))
    (folder / "trading_memory.md").write_text(log, encoding="utf-8")
    if touched:
        os.utime(folder / "trading_memory.md", (touched, touched))


def test_runs_are_listed_newest_activity_first_with_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    _make_run(tmp_path, "old_run", {"model": "ta-gemma12b", "tickers": ["A", "B"], "dates": ["d1", "d2"]}, 2, 1_000_000)
    _make_run(tmp_path, "new_run", {"model": "qwen/qwen3.8-27b", "provider": "openai_compatible",
                                    "tickers": ["A"], "dates": ["d1", "d2", "d3"]}, 1, 2_000_000)

    runs = list_runs()

    assert [r["run"] for r in runs] == ["new_run", "old_run"]
    assert runs[0]["provider"] == "openai_compatible" and runs[0]["decisions"] == 1 and runs[0]["planned"] == 3
    assert runs[1]["provider"] == "ollama" and runs[1]["decisions"] == 2 and runs[1]["planned"] == 4


def test_folders_without_a_record_are_skipped_and_a_missing_root_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    assert list_runs() == []
    _make_run(tmp_path, "no_meta_run", None, 3)
    assert list_runs() == []
