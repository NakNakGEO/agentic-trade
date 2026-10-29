"""Candles for the live chart page: this system's recorded TradingView minutes (and days), with both accounts' trades.

Times are UTC seconds, the shape the chart library reads. The bar forming now is taken from the latest TradingView
snapshot, so the last candle moves between recorded minutes.
"""

from __future__ import annotations

import time

import pandas as pd

from paper_trade import assets, daybook
from paper_trade.live import book as lb
from paper_trade.live import settings, tradingview, tv_guard

FRAMES = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1D": None}
MAX_BARS = 1500
AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}


def _seconds(stamp) -> int:
    stamp = pd.Timestamp(stamp)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return int(stamp.timestamp())


def _bars(ticker: str, frame: str) -> pd.DataFrame:
    if FRAMES[frame] is None:
        return daybook.bars(ticker)[["Open", "High", "Low", "Close"]]
    minutes = tradingview.candles(ticker)
    if frame == "1m":
        return minutes
    return minutes.resample(FRAMES[frame], label="left", closed="left").agg(AGG).dropna()


def _live(ticker: str) -> dict | None:
    try:
        snap = tradingview.snapshot()
    except Exception:
        return None
    row = snap.get("symbols", {}).get(ticker, {})
    m1, d1 = row.get("m1") or {}, row.get("d1") or {}
    if m1.get("close") is None:
        return None
    late = 0
    if str(row.get("mode", "")).startswith("delayed") and m1.get("time") is not None:
        late = round((time.time() - m1["time"]) / 60)             # minutes the feed is behind (US stocks on free data)
    return {"price": float(m1["close"]), "fetched_at": snap.get("fetched_at"), "minute": m1,
            "day_open": d1.get("open"), "delay": late}


def _merge_live(rows: list[dict], live: dict | None, frame: str) -> None:
    """Fold the snapshot's forming minute into the last candle (or start a new one when its period began)."""
    if not live or not rows or frame == "1D":
        return
    minute = live["minute"]
    stamp = pd.Timestamp(minute["time"], unit="s", tz="UTC") if minute.get("time") else pd.Timestamp(live["fetched_at"]).tz_convert("UTC")
    start = stamp.floor(FRAMES[frame])
    t = int(start.timestamp())
    last = rows[-1]
    if t == last["time"]:
        last.update(high=max(last["high"], minute["high"]), low=min(last["low"], minute["low"]), close=minute["close"])
    elif t > last["time"]:
        rows.append({"time": t, "open": minute["open"], "high": minute["high"], "low": minute["low"],
                     "close": minute["close"]})


def _account_marks(ticker: str, price: float | None) -> tuple[list, list]:
    """Open positions (entry, stop, target, result so far in dollars) and past trades of every live account."""
    wanted, positions, trades = assets.canonical(ticker), [], []
    for account in settings.ACCOUNTS.values():
        book = lb.load(settings.book_path(account))
        for pos in book.positions.values():              # a pair can hold several trades: the key is not the ticker
            if assets.canonical(pos.ticker) == wanted:
                pnl = pos.side * lb.qty(pos.ticker, price, pos.lot) * (price - pos.entry) - pos.cost if price else None
                positions.append({"account": account.label, "side": "long" if pos.side > 0 else "short",
                                  "entry": pos.entry, "stop": pos.stop, "target": pos.target, "risk": pos.risk,
                                  "pnl": None if pnl is None else round(pnl, 2),
                                  "opened": _seconds(pos.opened_at), "rating": pos.rating})
                trades.append({"account": account.label, "time": _seconds(pos.opened_at), "kind": "open",
                               "side": "long" if pos.side > 0 else "short", "price": pos.entry})
        for done in book.closed:
            if assets.canonical(done.ticker) == wanted:
                side = "long" if done.side > 0 else "short"
                trades.append({"account": account.label, "time": _seconds(done.opened_at), "kind": "open",
                               "side": side, "price": done.entry})
                trades.append({"account": account.label, "time": _seconds(done.closed_at), "kind": "close",
                               "side": side, "price": done.exit, "pnl": round(done.pnl, 2), "reason": done.reason})
    return positions, sorted(trades, key=lambda t: t["time"])


def chart(ticker: str, frame: str = "1m") -> dict:
    frame = frame if frame in FRAMES else "1m"
    try:
        bars = _bars(ticker, frame).iloc[-MAX_BARS:]
    except ValueError as error:
        bars, note = pd.DataFrame(columns=list(AGG)), str(error)
    else:
        note = ""
    rows = [{"time": _seconds(i), "open": float(r.Open), "high": float(r.High), "low": float(r.Low),
             "close": float(r.Close)} for i, r in bars.iterrows()]
    live = _live(ticker)
    _merge_live(rows, live, frame)
    price = live["price"] if live else (rows[-1]["close"] if rows else None)
    positions, trades = _account_marks(ticker, price)
    opened = live and live.get("day_open")
    return {"ticker": ticker, "frame": frame, "class": assets.asset_class(ticker), "bars": rows, "note": note,
            "price": price, "change": (price / float(opened) - 1) if price and opened else None,
            "fetched_at": live["fetched_at"] if live else None, "cooldown": tv_guard.seconds_left(),
            "delay": live["delay"] if live else 0,
            "positions": positions, "trades": trades,
            "record_starts": daybook.first_day(ticker), "source": "TradingView (recorded by this system)"}


def symbols() -> list[dict]:
    """Every live instrument with its class and TradingView's own symbol (for TradingView's embedded chart)."""
    return [{"ticker": t, "class": assets.asset_class(t), "tv": tradingview.symbol(t).split("|")[0]}
            for t in settings.TICKERS]
