"""Writes the monitor page's data files (same shape as snapshot_run.py) from the LIVE paper account.
Usage: python snapshot_live.py <gemma_short|qwen_short> <out_dir>   (gemma and qwen mean the short-term accounts)"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from paper_trade import assets, config
from paper_trade.decide import read_meta
from paper_trade.live import book as lb
from paper_trade.live import feeds, settings
from paper_trade.report import load_decisions
from snapshot_positions import BLANK_CHART_ROW, CALL_WORDS, SIDE_WORDS, px
from snapshot_run import feed_rows, model_usage
from watch_overnight import alive, read_pids


def _when(stamp: str) -> str:
    return stamp[:16].replace("T", " ") + " UTC"


def pair_fields(mine: list, pos, closed: list, skipped: list, live: float | None) -> dict:
    """One pair in plain words, from the live account."""
    out = {"status": "waiting", "status_text": "Waiting for the first call", "side": "", "entry_price": None,
           "entry_date": "", "stop": None, "target": None, "last_price": live, "live_price": live, "open_pnl": 0.0,
           "closed_pnl": round(sum(c.pnl for c in closed), 2), "exit_reason": "", "exit_date": "", "exit_price": None,
           "call_text": CALL_WORDS.get(mine[-1].rating, mine[-1].rating) if mine else "", "pnl": 0.0,
           "ls_state": "flat" if mine else "waiting", "ls_text": "Not tracked in live mode."}
    if pos:
        price = live or pos.entry
        unrealized = pos.side * lb.qty(pos.ticker, price, pos.lot) * (price - pos.entry)
        word = SIDE_WORDS["long" if pos.side > 0 else "short"]
        out.update(status="open", side="long" if pos.side > 0 else "short", entry_price=pos.entry,
                   entry_date=pos.opened_at[:10], stop=pos.stop, target=pos.target, open_pnl=round(unrealized, 2),
                   pnl=unrealized - pos.cost + sum(c.pnl for c in closed), fixed_state="holding",
                   fixed_text=f"{word} since {_when(pos.opened_at)} at {px(pos.entry)}. It closes by itself at the profit "
                              f"target {px(pos.target)} or the stop {px(pos.stop)}"
                              + (f", or at the market by {_when(pos.deadline)}" if pos.deadline else "")
                              + f". Profit or loss so far {unrealized:+.2f}.")
        return out
    out["pnl"] = sum(c.pnl for c in closed)
    if closed:
        last = closed[-1]
        how = {"Take-profit": "profit target hit", "Stop-loss": "stop-loss hit", "Time limit": "time limit reached"}.get(last.reason, "closed by a new call")
        word = SIDE_WORDS["long" if last.side > 0 else "short"]
        out.update(status="closed", exit_reason=last.reason, exit_date=last.closed_at[:10], exit_price=last.exit,
                   fixed_state="won" if last.pnl > 0 else "lost",
                   fixed_text=f"{word} at {px(last.entry)} on {_when(last.opened_at)}, closed at {px(last.exit)} on "
                              f"{_when(last.closed_at)} ({how}). {'Won' if last.pnl > 0 else 'Lost'} ${abs(last.pnl):,.2f}.")
    elif not mine:
        out.update(fixed_state="waiting", fixed_text="No call yet.")
    elif mine[-1].rating == "Hold":
        out.update(status="flat", fixed_state="not_opened", fixed_text="The call was HOLD: do nothing. No trade was opened. HOLD does not mean waiting to buy or sell.")
    elif skipped:
        why = "the 50% risk limit had no room left" if "cap" in skipped[-1]["why"] else skipped[-1]["why"]
        out.update(status="flat", fixed_state="not_opened", fixed_text=f"Not opened: {why}.")
    else:
        out.update(status="pending", fixed_state="waiting", fixed_text="Call made. The trade starts at the next price update.")
    out["status_text"] = out["fixed_text"]
    return out


LEGACY_NAMES = {"gemma": "gemma_short", "qwen": "qwen_short"}     # the monitor pages were set up for the daily accounts
CHART_MINUTES = 240             # M1 candles shown per pair (more when a trade opened earlier, up to a day)
CHART_MAX_MINUTES = 1440


def _minute(stamp: str) -> str:
    """'2026-10-28T10:15:03+00:00' -> '2026-10-28 10:15' (UTC), the label of the M1 candle it falls in."""
    return stamp[:16].replace("T", " ")


def chart_rows(book: lb.Book, tickers) -> list[dict]:
    """M1 candles (UTC minute labels) for each pair, with the account's entry and exit marks and open levels."""
    rows = []
    for ticker in tickers:
        bars = feeds.intraday_bars(ticker)
        trades = [(c.opened_at, c.closed_at) for c in book.closed if c.ticker == ticker]
        pos = book.positions.get(ticker)
        starts = [t[0] for t in trades] + ([pos.opened_at] if pos else [])
        window = CHART_MINUTES
        if starts:
            earliest = pd.Timestamp(min(starts)).tz_convert("UTC").tz_localize(None)
            window = min(CHART_MAX_MINUTES, max(window, int((pd.Timestamp.utcnow().tz_localize(None) - earliest)
                                                            .total_seconds() / 60) + 30))
        if bars is not None and not bars.empty:
            for stamp, bar in bars.iloc[-window:].iterrows():
                rows.append({**BLANK_CHART_ROW, "kind": "bar", "ticker": ticker, "date": stamp.strftime("%Y-%m-%d %H:%M"),
                             "open": round(float(bar["Open"]), 5), "high": round(float(bar["High"]), 5),
                             "low": round(float(bar["Low"]), 5), "close": round(float(bar["Close"]), 5)})
        for c in (c for c in book.closed if c.ticker == ticker):
            side = "long" if c.side > 0 else "short"
            rows.append({**BLANK_CHART_ROW, "kind": "entry", "ticker": ticker, "date": _minute(c.opened_at),
                         "price": c.entry, "side": side, "label": c.rating})
            rows.append({**BLANK_CHART_ROW, "kind": "exit", "ticker": ticker, "date": _minute(c.closed_at),
                         "price": c.exit, "side": side, "label": c.reason, "pnl": round(c.pnl, 2)})
        if pos:
            side = "long" if pos.side > 0 else "short"
            rows.append({**BLANK_CHART_ROW, "kind": "entry", "ticker": ticker, "date": _minute(pos.opened_at),
                         "price": pos.entry, "side": side, "label": pos.rating})
            for name, price in (("entry", pos.entry), ("stop", pos.stop), ("target", pos.target)):
                rows.append({**BLANK_CHART_ROW, "kind": "level", "ticker": ticker, "date": _minute(pos.opened_at),
                             "price": round(price, 5), "name": name, "side": side})
    return rows or [dict(BLANK_CHART_ROW)]


def main(name: str, out: Path) -> None:
    account = settings.ACCOUNTS[LEGACY_NAMES.get(name, name)]
    book = lb.load(settings.book_path(account))
    try:
        decisions, _ = load_decisions(account.decisions_run)
    except FileNotFoundError:
        decisions = []
    meta = read_meta(account.decisions_run) if decisions or (config.RUNS_DIR / "backtest" / account.decisions_run).exists() else {}
    tickers = list(account.tickers)
    mine = {assets.canonical(t) for t in tickers}
    decisions = [d for d in decisions if assets.canonical(d.ticker) in mine]
    live = feeds.latest_prices(tickers)
    usage = model_usage(account.decisions_run)
    latest_day = max((d.date for d in decisions), default="")
    done_today = sum(1 for d in decisions if d.date == latest_day)
    planned = len(tickers)                      # one call per pair per day
    started = datetime.fromisoformat(meta["started"]) if meta.get("started") else None
    elapsed = (datetime.now() - started).total_seconds() / 60 if started else 0.0
    share = done_today / planned if planned else 0
    eta = round(elapsed * (1 - share) / share) if 0.05 < share < 1 else None
    loop_alive = any(alive(pid) for name, pid in read_pids().items() if name == f"live_loop_{account.name}")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    value = lb.equity(book, live)

    rows = []
    for ticker in tickers:
        key = assets.canonical(ticker)
        mine = sorted((d for d in decisions if assets.canonical(d.ticker) == key), key=lambda d: d.date)
        pos = next((p for t, p in book.positions.items() if assets.canonical(t) == key), None)
        closed = [c for c in book.closed if assets.canonical(c.ticker) == key]
        skipped = [s for s in book.skipped if assets.canonical(s["ticker"]) == key]
        fields = pair_fields(mine, pos, closed, skipped, live.get(ticker))
        wins, losses = sum(1 for c in closed if c.pnl > 0), sum(1 for c in closed if c.pnl < 0)
        rows.append({
            "ticker": ticker, "kind": assets.asset_class(ticker), "decisions": len(mine),
            "expected": sum(assets.trades_on(ticker, d) for d in [latest_day] if d),
            "last_rating": mine[-1].rating if mine else "", "ratings": ", ".join(d.rating for d in mine),
            "wins": wins, "losses": losses, "open_side": fields["side"],
            "fixed_lot_pnl": round(fields.pop("pnl"), 2), "long_short_pnl": 0.0,
            "run_done": done_today, "run_planned": planned, "run_calls": usage["calls"],
            "run_tokens_m": usage["tokens_m"], "run_errors": usage["errors"], "run_streams": 1 if loop_alive else 0,
            "run_elapsed_min": round(elapsed), "run_eta_min": eta, "run_model": meta.get("model", ""),
            "run_updated": now, "run_start_cash": book.start_cash, **fields})

    per_day = {}
    for point in book.history:
        per_day[point["t"][:10]] = point["equity"]
    equity = [{"date": day, "fixed_lot": round(v, 2), "long_short": None} for day, v in sorted(per_day.items())]

    out.mkdir(parents=True, exist_ok=True)
    (out / "pairs.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    (out / "equity.json").write_text(json.dumps(equity or [{"date": now[:10], "fixed_lot": 100.0, "long_short": None}]),
                                     encoding="utf-8")
    (out / "chart.json").write_text(json.dumps(chart_rows(book, tickers)), encoding="utf-8")
    feed = feed_rows(account.decisions_run) or [{"t": 0, "kind": "", "agent": "", "ticker": "", "date": "", "tool": "",
                                           "seconds": 0, "tokens_out": 0, "text": ""}]
    (out / "feed.json").write_text(json.dumps(feed, indent=1), encoding="utf-8")
    print(f"live account ${value:,.2f}; {done_today}/{planned} of today's decisions; {len(book.positions)} holding, "
          f"{len(book.closed)} finished, {len(book.skipped)} not opened")


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]))
