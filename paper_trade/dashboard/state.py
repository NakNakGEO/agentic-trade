"""Everything the dashboard page shows, gathered into one JSON-ready dict."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from paper_trade import assets, config, scorecard
from paper_trade.bridge import settings as rules
from paper_trade.dashboard import rounds, sysinfo
from paper_trade.decide import feed_path, memory_log, read_meta, run_dir
from paper_trade.trade_record import record

FEED_ROWS = 60
PORTFOLIO_TTL = 120          # seconds; the simulation fetches prices, so do not redo it every poll
RUNNING_IF_ACTIVE_WITHIN = 240
SLOW_MS = 30_000          # a model reply taking this long counts as slow; the page colours by the same limits

_cache: dict = {}
_token_cache: dict = {}
_log_start = sysinfo.log_offset()
_ENTRY = re.compile(r"^\[(\d{4}-\d{2}-\d{2}) \| ([^|]+?) \| (\w+) \|(?: ([^|]+?) \| ([^|]+?) \|)?")


def read_feed(path: Path, rows: int = FEED_ROWS, window: int = 2_000_000) -> list[dict]:
    """The last ``rows`` events, reading only the end of the file; a half-written line is skipped."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            handle.seek(max(0, size - window))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []
    if size > window:
        lines = lines[1:]                     # the first line of the window may be cut in half
    lines = lines[-rows:]
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def token_totals(path: Path) -> dict:
    """Totals over every event ever logged for the run, recomputed only when the file changes."""
    try:
        stat = path.stat()
    except OSError:
        return {}
    key = (stat.st_mtime_ns, stat.st_size)
    hit = _token_cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    total = {"calls": 0, "tokens_in": 0, "tokens_out": 0, "llm_seconds": 0.0, "tool_calls": 0, "errors": 0}
    by_node: dict[str, dict] = {}
    waits: list[int] = []                  # response time of each model call, in milliseconds
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("kind")
        if kind == "tool":
            total["tool_calls"] += 1
        elif kind == "error":
            total["errors"] += 1
        elif kind == "llm":
            used_in, used_out = event.get("tokens_in") or 0, event.get("tokens_out") or 0
            total["calls"] += 1
            total["tokens_in"] += used_in
            total["tokens_out"] += used_out
            total["llm_seconds"] += event.get("seconds") or 0
            took = event.get("ms")
            waits.append(round((event.get("seconds") or 0) * 1000) if took is None else took)   # older events: seconds only
            node = by_node.setdefault(event.get("node") or "-", {"node": event.get("node") or "-",
                                                                  "calls": 0, "tokens": 0})
            node["calls"] += 1
            node["tokens"] += used_in + used_out
    ordered = sorted(waits)
    latency = {"ms_last": waits[-1] if waits else None,
               "ms_avg": round(sum(waits) / len(waits)) if waits else None,
               "ms_median": ordered[len(ordered) // 2] if waits else None,
               "ms_max": ordered[-1] if waits else None,
               "slow_calls": sum(1 for w in waits if w >= SLOW_MS)}
    value = {**total, **latency, "by_node": sorted(by_node.values(), key=lambda n: -n["tokens"])[:10]}
    _token_cache[path] = (key, value)
    return value


def read_decisions(path: Path) -> list[dict]:
    """Rating tags from the memory log; return/alpha are blank until the 5-day window settles."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        match = _ENTRY.match(line)
        if match:
            date, ticker, rating, raw, alpha = match.groups()
            settled = raw is not None and "%" in raw
            rows.append({"date": date, "ticker": ticker, "rating": rating,
                         "raw": raw if settled else None, "alpha": alpha if settled else None,
                         "class": assets.asset_class(ticker)})
    return rows


def _series(series: pd.Series) -> list[list]:
    return [[idx.strftime("%Y-%m-%d"), round(float(value), 4)] for idx, value in series.items()]


def simulation(run_id: str, done: int, mode: str = config.DEFAULT_MODE):
    """The paper-trade result for a run: cached, redone when a decision lands or the cache ages.

    ``mode`` (long_only or long_short) changes only how the same decisions are traded.
    Returns a PortfolioResult, or an error string when nothing is tradeable yet or prices fail.
    """
    from paper_trade.dashboard import live_view
    from paper_trade.report import simulate_run

    account = live_view.account_for(run_id)
    if account is not None:                 # a live account: read its book, not a replay of its decisions
        try:
            return live_view.live_result(account)
        except Exception as exc:
            return str(exc)[:200]
    mode = mode if mode in config.ACCOUNT_MODES else config.DEFAULT_MODE
    try:                                   # any change to the decision log invalidates the cached result
        stamp = memory_log(run_id).stat().st_mtime_ns
    except OSError:
        stamp = 0
    key = (run_id, mode)
    hit = _cache.get(key)
    if hit and hit["done"] == done and hit["stamp"] == stamp and time.time() - hit["at"] < PORTFOLIO_TTL:
        return hit["result"]
    try:
        result, _ = simulate_run(run_id, mode=mode)
    except Exception as exc:
        return str(exc)[:200]
    _cache[key] = {"done": done, "stamp": stamp, "at": time.time(), "result": result}
    return result


def portfolio_state(run_id: str, done: int, mode: str = config.DEFAULT_MODE) -> dict | None:
    """The paper portfolio so far, in the shape the page draws."""
    from paper_trade.stats import daily_stats

    result = simulation(run_id, done, mode)
    if isinstance(result, str):
        return {"error": result}
    cash = result.starting_cash
    stats = daily_stats(result.strategy, cash)
    slice_cash = cash / len(result.sleeves)
    value = {
        "cash": cash,
        "series": {"strategy": _series(result.strategy), "spy": _series(result.benchmark),
                   "hold": _series(result.equal_weight)},
        "end": {"strategy": stats.end_value, "spy": float(result.benchmark.iloc[-1]),
                "hold": float(result.equal_weight.iloc[-1])},
        "per_day": stats.per_calendar_day, "best_day": stats.best_day, "worst_day": stats.worst_day,
        "up_days": stats.up_days, "down_days": stats.down_days, "days": stats.calendar_days,
        "exposure": float(result.exposure.iloc[-1]), "trades": len(result.trades),
        "tickers": [{"ticker": t, "symbol": assets.canonical(t), "class": assets.asset_class(t),
                     "strategy": float(s.equity.iloc[-1] - slice_cash),
                     "hold": float(result.buy_hold[t].iloc[-1] - slice_cash),
                     "exposure": float(s.exposure.iloc[-1]),
                     # what the sleeve holds at the last close, so the page can value it at live prices
                     "cash": float(s.cash), "shares": float(s.shares), "last_price": float(s.last_price),
                     **record(s)}
                    for t, s in sorted(result.sleeves.items())],
    }
    from paper_trade.dashboard import live_view

    account = live_view.account_for(run_id)
    value["live"] = account is not None     # live accounts have no SPY line, only the same pairs held
    rows = value["tickers"]
    if account is not None:                 # a live trade has a stop and a take-profit: show them beside the entry price
        levels = live_view.levels_for(account)
        for r in rows:
            r.update(levels.get(r["ticker"], {}))
    value["record"] = {"closed": sum(r["closed"] for r in rows), "wins": sum(r["wins"] for r in rows),
                       "losses": sum(r["losses"] for r in rows), "realized": sum(r["realized"] for r in rows),
                       "open_pnl": sum(r["open_pnl"] for r in rows)}
    return value


def describe_model(meta: dict) -> dict:
    """Which model served a run, in words the page can show. Runs without a provider were local."""
    provider = meta.get("provider") or "ollama"
    local = provider == "ollama"
    info = config.PROVIDER_INFO.get(urlparse(meta.get("backend_url") or "").hostname or "", {})
    label = "Local model (Ollama, on your GPU)" if local else info.get("label") or f"Online API ({provider})"
    return {"local": local, "provider": provider, "provider_label": label,
            "model": meta.get("model") or config.LLM_SETTINGS["quick_think_llm"],
            "thinking": meta.get("thinking"), "effort": meta.get("effort"),
            "monthly_tokens": info.get("monthly_tokens")}


def skipped_calls(run_id: str) -> dict:
    """For a live account: the calls it could not open as trades, with the reason in plain words (else nothing)."""
    from paper_trade.dashboard import live_view

    account = live_view.account_for(run_id)
    return live_view.skipped_for(account) if account is not None else {}


def build_state(run_id: str, mode: str = config.DEFAULT_MODE) -> dict:
    from paper_trade.dashboard import live_view

    source = live_view.source_run(run_id)        # an account that trades another's calls shows that account's decisions and feed
    account = live_view.account_for(run_id)
    meta = read_meta(source)
    decisions = read_decisions(memory_log(source))
    if account is not None:
        mine = {assets.canonical(t) for t in account.tickers}
        decisions = [d for d in decisions if assets.canonical(d["ticker"]) in mine]
    feed = read_feed(feed_path(source))
    planned = meta.get("planned_cells") or len(meta.get("tickers", [])) * len(meta.get("dates", []))
    if account is not None:
        planned = len(account.tickers) * max(1, len(meta.get("dates", [])))
    labels = {assets.canonical(t): t for t in meta.get("tickers", [])}     # show the names the run was given
    for row in decisions:
        row["ticker"] = labels.get(assets.canonical(row["ticker"]), row["ticker"])
    classes = {t: assets.asset_class(t) for t in {*meta.get("tickers", []), *(r["ticker"] for r in decisions)}}
    resumed = meta.get("resumed")
    since = (datetime.now() - datetime.fromisoformat(resumed)).total_seconds() if resumed else None
    fresh = len(decisions) - meta.get("baseline_done", 0)       # decisions made since this launch
    seconds_per_cell = since / fresh if since and fresh > 0 else None
    started = meta.get("started")
    elapsed = (datetime.now() - datetime.fromisoformat(started)).total_seconds() if started else None
    last_event = feed[-1]["t"] if feed else None
    progress_log = run_dir(source) / "progress.log"
    try:
        idle = time.time() - progress_log.stat().st_mtime
    except OSError:
        idle = None
    system = describe_model(meta)
    if system["local"]:                      # GPU and local-model readings only make sense for a local run
        system.update(gpu=sysinfo.gpu_stats(), ollama=sysinfo.ollama_stats(_log_start))
    round_now = None
    score = None
    done_count = len(decisions)
    if account is not None:                  # a live account: the page shows today's round, not the run's whole life
        round_now = rounds.progress(feed_path(source), decisions, rounds.pairs_of_round(account.tickers, meta.get("tickers")), account.parallel)
        if round_now:
            done_count, planned = round_now["done"], round_now["total"]
        elapsed, seconds_per_cell = (round_now or {}).get("elapsed"), None
        try:
            score = scorecard.for_account(account)
        except Exception:                    # the scorecard is extra: a problem in it must never blank the page
            score = None
    return {
        "run_id": run_id, "meta": meta, "now": time.time(),
        "running": bool(last_event and time.time() - last_event < RUNNING_IF_ACTIVE_WITHIN),
        "idle_seconds": idle,
        "cells_done": done_count, "cells_total": planned, "elapsed_seconds": elapsed, "round": round_now, "scorecard": score,
        "pace": live_view.schedule.pace(account) if account is not None else None,      # is the model keeping up with its call interval
        "seconds_per_cell": seconds_per_cell, "classes": classes,
        "tokens": token_totals(feed_path(source)),
        "current_cell": feed[-1]["cell"] if feed else None,
        "current_node": next((e["node"] for e in reversed(feed) if e.get("node") not in (None, "-")), None),
        "feed": feed, "decisions": decisions,
        "portfolio": portfolio_state(run_id, len(decisions), mode) if decisions else None,
        "mode": mode if mode in config.ACCOUNT_MODES else config.DEFAULT_MODE,
        "lot": rules.FIXED_LOT,
        "style_note": live_view.style_note(account),     # the trade rules in words, when they are not the standard daily ones
        "blotter": live_view.blotter_for(account) if account is not None else None,
        "skipped": skipped_calls(run_id),
        "system": system,
    }
