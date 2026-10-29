"""Data for the per-asset trade chart: daily candles, the paper trades on them, position size."""

from __future__ import annotations

import time

import pandas as pd

from paper_trade import assets, config
from paper_trade.dashboard.state import read_decisions, simulation
from paper_trade.decide import memory_log
from paper_trade.prices import load_bars
from paper_trade.trade_record import record

BARS_TTL = 300
LEAD_DAYS = 21          # show some history before the first decision

_bars_cache: dict = {}


def _bars(ticker: str, start: str) -> pd.DataFrame:
    hit = _bars_cache.get((ticker, start))
    if hit and time.time() - hit[0] < BARS_TTL:
        return hit[1]
    frame = load_bars(ticker, start)
    _bars_cache[(ticker, start)] = (time.time(), frame)
    return frame


def _day(stamp) -> str:
    return pd.Timestamp(stamp).strftime("%Y-%m-%d")


def chart_state(run_id: str, ticker: str, done: int, mode: str = config.DEFAULT_MODE) -> dict:
    """Candles for ``ticker`` with the run's decisions, fills and position size drawn on top."""
    wanted = assets.canonical(ticker)
    decisions = [d for d in read_decisions(memory_log(run_id)) if assets.canonical(d["ticker"]) == wanted]
    first = min((d["date"] for d in decisions), default=None)
    start = (pd.Timestamp(first) - pd.Timedelta(days=LEAD_DAYS)).strftime("%Y-%m-%d") if first else (
        pd.Timestamp.now() - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    try:
        frame = _bars(ticker, start)
    except Exception as exc:
        return {"ticker": ticker, "error": f"no price history: {str(exc)[:120]}"}

    out = {"ticker": ticker, "class": assets.asset_class(ticker), "start": start,
           "bars": [[_day(i), round(r.Open, 4), round(r.High, 4), round(r.Low, 4), round(r.Close, 4)]
                    for i, r in frame.iterrows()],
           "decisions": [{"date": d["date"], "rating": d["rating"]} for d in decisions],
           "trades": [], "exposure": [], "pending": [], "record": None, "open": None}
    result = simulation(run_id, done, mode) if decisions else None
    if result is None or isinstance(result, str):
        return out
    sleeve = next((s for name, s in result.sleeves.items() if assets.canonical(name) == wanted), None)
    if sleeve is None:
        return out
    out["trades"] = [{"fill_date": t.fill_date, "decision_date": t.decision_date, "rating": t.rating,
                      "side": "buy" if t.shares > 0 else "sell", "price": round(t.price, 4),
                      "value": round(abs(t.shares) * t.price, 4),
                      # sells carry their result against the average cost of the shares sold
                      "pnl": None if t.pnl is None else round(t.pnl, 4), "entry_date": t.entry_date,
                      "entry_price": None if t.entry_price is None else round(t.entry_price, 4),
                      # which position the fill closed (with a result) and/or opened: "long" or "short"
                      "closes": t.closes, "opens": t.opens}
                     for t in sleeve.trades]
    out["record"] = record(sleeve)
    out["open"] = None if sleeve.shares == 0 else {
        "side": "long" if sleeve.shares > 0 else "short",
        "entry_date": sleeve.open_date, "entry_price": round(sleeve.basis / sleeve.shares, 4),
        "shares": sleeve.shares, "last_price": sleeve.last_price,
        "pnl": round(sleeve.shares * sleeve.last_price - sleeve.basis, 4)}
    out["pending"] = [{"date": d.date, "rating": d.rating} for d in sleeve.pending]
    out["exposure"] = [[_day(i), round(float(v), 4)] for i, v in sleeve.exposure.items()
                       if i >= pd.Timestamp(start)]
    return out
