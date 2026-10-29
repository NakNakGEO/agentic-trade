"""Produce TradingAgents decisions for a (ticker, date) grid, resumable and isolated.

Uses the framework's own ``run_backtest`` so decisions come from the same tested path
(point-in-time data guards, its own memory log, settlement of realised alpha). Dates run
one at a time, every ticker per date, so a stopped run still leaves a coherent portfolio.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from paper_trade import assets, config


def build_config(llm: dict | None = None) -> dict:
    """Framework settings. ``llm`` overrides the local default (provider, models, backend_url)."""
    from tradingagents.default_config import build_default_config

    settings = build_default_config()
    settings.update(config.LLM_SETTINGS)
    settings.update({k: v for k, v in (llm or {}).items() if v})
    if settings["llm_provider"] != "ollama":
        settings["llm_max_retries"] = config.HOSTED_LLM_RETRIES   # ride out rate-limit (429) replies
    settings["results_dir"] = str(config.RUNS_DIR)
    settings["data_cache_dir"] = str(config.CACHE_DIR)
    return settings


def run_dir(run_id: str) -> Path:
    return config.RUNS_DIR / "backtest" / run_id


def memory_log(run_id: str) -> Path:
    return run_dir(run_id) / "trading_memory.md"


def feed_path(run_id: str) -> Path:
    return run_dir(run_id) / "events.jsonl"


def meta_path(run_id: str) -> Path:
    return run_dir(run_id) / "meta.json"


def _write_meta(run_id: str, meta: dict) -> None:
    """Record what the run is doing. Several processes may share a run, so a clash is not fatal."""
    try:
        meta_path(run_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except OSError:
        pass


def logged_cells(run_id: str) -> int:
    """How many decisions the run's memory log holds."""
    try:
        text = memory_log(run_id).read_text(encoding="utf-8")
    except OSError:
        return 0
    return sum(1 for line in text.splitlines() if re.match(r"^\[\d{4}-\d{2}-\d{2} \| ", line))


def read_meta(run_id: str) -> dict:
    """What the run was asked to do (tickers, dates, ...), or {} when it has no record."""
    try:
        return json.loads(meta_path(run_id).read_text(encoding="utf-8-sig"))     # tolerate a Windows BOM
    except (OSError, ValueError):
        return {}


def decide(tickers: list[str], dates: list[str], run_id: str,
           analysts: tuple[str, ...] = config.REPLAY_ANALYSTS, llm: dict | None = None,
           no_thinking: bool = False, only: list[str] | None = None,
           thinking: bool = False, effort: str | None = None, data: str = "tradingview") -> dict:
    """Analyze every cell; re-running with the same ``run_id`` skips finished cells.

    ``only`` limits THIS process to some of the run's tickers, so several processes can share one run
    (each takes different assets) and finish sooner. The run's record still lists every ticker.
    Thinking: ``effort`` keeps it on at that level; ``thinking`` leaves a local model's thinking on;
    ``no_thinking`` asks for it off. The local model defaults to off, hosted ones to the model's default.
    ``data="tradingview"`` (the default) gives the models this system's data: TradingView live prices and indicators
    with our own day-by-day record, many news feeds, and fundamentals for every asset class (paper_trade.tvdata).
    """
    from tradingagents.backtest import run_backtest

    settings = build_config(llm)
    if data == "tradingview":
        from paper_trade.tvdata import use_tradingview

        settings = use_tradingview(settings)
    provider = settings["llm_provider"]
    thinking_on = None                                   # None = the model's own default, not changed here
    if effort:
        from paper_trade.nothink import set_reasoning_effort

        thinking_on = set_reasoning_effort(provider, effort) or None
    elif thinking:
        thinking_on = True
    elif no_thinking or (provider == "ollama" and config.DISABLE_THINKING):
        from paper_trade.nothink import disable_thinking

        if disable_thinking(provider):
            thinking_on = False
        else:
            print(f"note: no thinking-off switch is known for provider '{provider}'; running as configured",
                  flush=True)
    mine = only or tickers
    pipelines = assets.group_by_pipeline(mine, analysts, crypto_fundamentals=data == "tradingview")
    progress_file = run_dir(run_id) / "progress.log"
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    # Stocks, forex and gold have no daily bar on weekends, so a day only counts for assets that trade it.
    planned_cells = sum(assets.trades_on(t, d) for t in tickers for d in dates)
    total = sum(assets.trades_on(t, d) for t in mine for d in dates)
    tally = {"ran": 0, "skipped": 0, "failed": []}

    from paper_trade import events

    feed = events.install(feed_path(run_id))
    previous = read_meta(run_id)
    _write_meta(run_id, {
        "run_id": run_id, "tickers": tickers, "dates": dates, "analysts": list(analysts),
        "provider": settings["llm_provider"], "backend_url": settings.get("backend_url"),
        "model": settings["quick_think_llm"],
        "deep_model": settings["deep_think_llm"], "max_tokens": settings.get("max_tokens"),
        "thinking": thinking_on, "effort": effort, "planned_cells": planned_cells, "market_data": data,
        "started": previous.get("started") or datetime.now().isoformat(timespec="seconds"),
        "resumed": datetime.now().isoformat(timespec="seconds"),   # this launch, for pace
        "baseline_done": logged_cells(run_id),                     # decisions before this launch
    })

    def on_cell(done: int, n: int, ticker: str, when: str) -> None:
        feed.set_cell(ticker, when)
        say(f"  cell {done}/{n} {ticker} {when}")

    def say(message: str) -> None:
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
        print(line, flush=True)
        with open(progress_file, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    for index, date in enumerate(dates, 1):
        elapsed = (time.time() - started) / 60
        say(f"date {index}/{len(dates)} {date} ({total} cells overall, elapsed {elapsed:.1f} min)")
        for (kind, group_analysts), group in pipelines.items():
            group = [t for t in group if assets.trades_on(t, date)]
            if not group:
                continue
            result = run_backtest(group, [date], settings, asset_type=kind,
                                  selected_analysts=group_analysts, run_id=run_id,
                                  progress=on_cell)
            tally["ran"] += result.cells_run
            tally["skipped"] += result.skipped
            tally["failed"].extend(result.failures)
            for ticker, when, reason in result.failures:
                say(f"  FAILED {ticker} {when}: {reason[:200]}")

    say(f"done: ran={tally['ran']} skipped={tally['skipped']} failed={len(tally['failed'])} "
        f"in {(time.time() - started) / 60:.1f} min")
    return tally
