"""Write the day-by-day record from what the live loop fetches: TradingView's daily analysis and its minute candles.

The daily analysis (every 15 minutes) gives the day's true open, high, low, close and every daily indicator; the minute
snapshot (every cycle) keeps the close current between analyses and widens the high and low when price moves past them.
A price only replaces the stored close when it was fetched later than the stored one.
"""

from __future__ import annotations

from datetime import datetime, timezone

from paper_trade import config
from paper_trade.daybook import settings, store

BAR_KEYS = set(settings.BAR_FIELDS) | {"change", "change_abs", "time"}


def _merge_range(row: dict, high, low) -> None:
    if high is not None:
        row["high"] = max(float(high), row.get("high", float(high)))
    if low is not None:
        row["low"] = min(float(low), row.get("low", float(low)))


def _update(ticker: str, day: str, change) -> None:
    rows = store.load(ticker)
    row = rows.setdefault(day, {"day": day})
    change(row)
    store.save(ticker, rows)


def _day(ticker: str, fetched: str, bar_time) -> str:
    """The row a snapshot belongs to: the daily bar TradingView named (its start time), else the clock's trading day."""
    if bar_time:
        return store.bar_day(ticker, float(bar_time))
    return store.trading_day(ticker, datetime.fromisoformat(fetched))


def from_analysis(reply: dict) -> int:
    """Store each instrument's daily bar and daily indicators from one ``tvdata.client.analysis()`` reply."""
    if config.READ_ONLY_DATA:
        return 0
    fetched = reply.get("fetched_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    written = 0
    for ticker, frames in (reply.get("analysis") or {}).items():
        daily = frames.get("1d") or {}
        if daily.get("close") is None:
            continue

        def change(row: dict, daily=daily, frames=frames) -> None:
            row["open"] = float(daily["open"])
            if daily.get("volume") is not None:
                row["volume"] = float(daily["volume"])
            _merge_range(row, daily.get("high"), daily.get("low"))
            if fetched >= row.get("close_at", ""):
                row.update(close=float(daily["close"]), close_at=fetched)
            row["indicators"] = {k: v for k, v in daily.items() if k not in BAR_KEYS}
            row["ratings"] = {tf: f.get("Recommend.All") for tf, f in frames.items() if f.get("Recommend.All") is not None}
            row["analysis_at"] = fetched

        _update(ticker, _day(ticker, fetched, daily.get("time")), change)
        written += 1
    return written


def from_minute(snapshot: dict) -> int:
    """Keep each instrument's row current from one ``live.tradingview.snapshot()`` (its 1-minute candles)."""
    if config.READ_ONLY_DATA:
        return 0
    fetched = snapshot.get("fetched_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    written = 0
    for ticker, live in (snapshot.get("symbols") or {}).items():
        minute = (live or {}).get("m1") or {}
        if minute.get("close") is None:
            continue
        finished = (live or {}).get("m1_prev") or {}

        def change(row: dict, minute=minute, finished=finished) -> None:
            row.setdefault("open", float(minute.get("open") or minute["close"]))   # until the daily analysis gives the real one
            _merge_range(row, finished.get("high"), finished.get("low"))
            _merge_range(row, minute.get("high"), minute.get("low"))
            if fetched >= row.get("close_at", ""):
                row.update(close=float(minute["close"]), close_at=fetched)

        _update(ticker, _day(ticker, fetched, ((live or {}).get("d1") or {}).get("time")), change)
        written += 1
    return written
