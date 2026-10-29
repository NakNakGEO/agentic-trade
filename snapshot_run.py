"""Writes the monitor page's data files for a run: pairs.json (one row per pair with its position status, run totals
repeated on each), equity.json (one row per day), chart.json (candles and trade marks) and feed.json (agent messages).
Usage: python snapshot_run.py <run_id> <out_dir>"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paper_trade import assets, config
from paper_trade.dashboard.state import read_feed
from paper_trade.decide import feed_path as events_path, read_meta
from paper_trade.report import load_decisions, simulate_run
from paper_trade.trade_record import record
from snapshot_positions import chart_rows, live_prices, long_short_fields, position_fields
from watch_overnight import alive, read_pids

FEED_ROWS = 40                  # latest events shown on the page, newest first
FEED_TEXT = 1800                # characters kept per model message
CALLS_PER_DECISION = 18         # measured on earlier runs; only used for a rough progress estimate


def simulate(run: str, mode: str):
    try:
        return simulate_run(run, mode=mode)[0]
    except Exception:           # nothing tradeable yet, or prices not reachable: the page shows "waiting"
        return None


def model_usage(run: str) -> dict:
    calls = tokens = errors = 0
    path = events_path(run)
    for line in (path.read_text(encoding="utf-8", errors="ignore").splitlines() if path.exists() else []):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("kind") == "llm":
            calls += 1
            tokens += (event.get("tokens_in") or 0) + (event.get("tokens_out") or 0)
        elif event.get("kind") == "error":
            errors += 1
    return {"calls": calls, "tokens_m": round(tokens / 1e6, 2), "errors": errors}


def feed_rows(run: str) -> list[dict]:
    """The latest agent messages and tool calls, newest first, with long texts cut."""
    rows = []
    for event in reversed(read_feed(events_path(run), rows=FEED_ROWS)):
        ticker, _, date = (event.get("cell") or "").partition(" ")
        text = event.get("text") or ""
        kind = event.get("kind")
        if kind == "llm" and not text:
            text = "(asked for tool calls: " + ", ".join(str(c.get("name", c)) if isinstance(c, dict) else str(c)
                                                          for c in event.get("tool_calls") or []) + ")"
        rows.append({"t": round(event.get("t", 0), 1), "kind": kind, "agent": event.get("node") or "",
                     "ticker": ticker, "date": date, "tool": event.get("tool") or "",
                     "seconds": event.get("seconds") or 0, "tokens_out": event.get("tokens_out") or 0,
                     "text": text[:FEED_TEXT] + (" ..." if len(text) > FEED_TEXT else "")})
    return rows


def streams_alive(run: str) -> int:
    return sum(1 for name, pid in read_pids().items() if (name == run or name.startswith(run + "_")) and alive(pid))


def sleeve_of(result, ticker: str):
    if result is None:
        return None
    return next((s for name, s in result.sleeves.items() if assets.canonical(name) == assets.canonical(ticker)), None)


def main(run: str, out: Path) -> None:
    meta = read_meta(run)
    tickers, planned = meta["tickers"], meta["planned_cells"]
    try:
        decisions, _ = load_decisions(run)
    except FileNotFoundError:
        decisions = []
    fixed, short = simulate(run, "fixed_lot"), simulate(run, "long_short")
    usage = model_usage(run)
    started = datetime.fromisoformat(meta["started"]) if meta.get("started") else None
    elapsed = (datetime.now() - started).total_seconds() / 60 if started else 0.0
    share = max(len(decisions) / planned, usage["calls"] / (planned * CALLS_PER_DECISION))
    eta = round(elapsed * (1 - share) / share) if 0.05 < share < 1 else None
    slice_cash = config.STARTING_CASH / len(tickers)
    live = live_prices(tickers)

    rows = []
    for ticker in tickers:
        mine = sorted((d for d in decisions if assets.canonical(d.ticker) == assets.canonical(ticker)),
                      key=lambda d: d.date)
        fixed_sleeve, short_sleeve = sleeve_of(fixed, ticker), sleeve_of(short, ticker)
        rec = record(fixed_sleeve) if fixed_sleeve else None
        rows.append({
            "ticker": ticker, "kind": assets.asset_class(ticker),
            "decisions": len(mine), "expected": sum(assets.trades_on(ticker, d) for d in meta["dates"]),
            "last_rating": mine[-1].rating if mine else "",
            "ratings": ", ".join(d.rating for d in mine),
            "wins": rec["wins"] if rec else 0, "losses": rec["losses"] if rec else 0,
            "open_side": (rec["open_side"] or "") if rec else "",
            "fixed_lot_pnl": round(float(fixed_sleeve.equity.iloc[-1]) - slice_cash, 2) if fixed_sleeve else 0.0,
            "long_short_pnl": round(float(short_sleeve.equity.iloc[-1]) - slice_cash, 2) if short_sleeve else 0.0,
            "run_done": len(decisions), "run_planned": planned, "run_calls": usage["calls"],
            "run_tokens_m": usage["tokens_m"], "run_errors": usage["errors"],
            "run_streams": streams_alive(run), "run_elapsed_min": round(elapsed), "run_eta_min": eta,
            "run_model": meta.get("model", ""), "run_updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_start_cash": config.STARTING_CASH,
            **position_fields(mine, fixed_sleeve, live.get(ticker)),
            **long_short_fields(mine, short_sleeve),
        })

    curve = {}
    for name, result in (("fixed_lot", fixed), ("long_short", short)):
        if result is not None:
            for day, value in result.strategy.items():
                curve.setdefault(day.strftime("%Y-%m-%d"), {})[name] = round(float(value), 2)
    equity = [{"date": day, "fixed_lot": values.get("fixed_lot"), "long_short": values.get("long_short")}
              for day, values in sorted(curve.items())]

    if not equity:                      # the page needs at least one row; an all-empty row means "no fills yet"
        equity = [{"date": datetime.now().strftime("%Y-%m-%d"), "fixed_lot": None, "long_short": None}]

    first = min((d.date for d in decisions), default=meta["dates"][0])
    since = (datetime.fromisoformat(first) - timedelta(days=10)).strftime("%Y-%m-%d")
    sleeves = {t: sleeve_of(fixed, t) for t in tickers}
    chart = chart_rows(tickers, {t: s for t, s in sleeves.items() if s is not None}, since)

    out.mkdir(parents=True, exist_ok=True)
    (out / "chart.json").write_text(json.dumps(chart), encoding="utf-8")
    (out / "pairs.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    (out / "equity.json").write_text(json.dumps(equity, indent=1), encoding="utf-8")
    feed = feed_rows(run) or [{"t": 0, "kind": "", "agent": "", "ticker": "", "date": "", "tool": "", "seconds": 0,
                               "tokens_out": 0, "text": ""}]
    (out / "feed.json").write_text(json.dumps(feed, indent=1), encoding="utf-8")
    print(f"{len(decisions)}/{planned} decisions, {usage['calls']} calls, fixed-lot "
          f"{'n/a' if fixed is None else round(float(fixed.strategy.iloc[-1]), 2)}, {len(equity)} equity days")


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]))
