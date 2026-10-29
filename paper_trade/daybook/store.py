"""Our own day-by-day record of what this system fetched from TradingView: one JSON file per instrument.

Each file maps a trading day to that day's row: the daily bar (open, high, low, close, volume), every daily indicator
TradingView reported, and its ratings on the other timeframes. A row is rewritten while its day is still forming, so
the last write of a day holds its final values. Nothing here comes from TradingView's own price history.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from paper_trade import assets
from paper_trade.daybook import settings


def path(ticker: str) -> Path:
    return settings.DIR / f"{assets.canonical(ticker)}.json"


def load(ticker: str) -> dict[str, dict]:
    """{"YYYY-MM-DD": row}, oldest first; {} before the first recording."""
    try:
        rows = json.loads(path(ticker).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(sorted(rows.items()))


def save(ticker: str, rows: dict[str, dict]) -> None:
    target = path(ticker)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(dict(sorted(rows.items())), separators=(",", ":")), encoding="utf-8")
    for attempt in range(settings.WRITE_RETRIES):
        try:
            tmp.replace(target)
            return
        except PermissionError:              # the other live loop is replacing the same file this instant
            time.sleep(0.2 * (attempt + 1))
    tmp.unlink(missing_ok=True)


def trading_day(ticker: str, when: datetime) -> str:
    """The trading day a moment belongs to, as TradingView cuts daily bars.

    Crypto: the UTC date. Stocks: the New York date. Forex and gold: the day that starts at 17:00 New York.
    """
    stamp = pd.Timestamp(when)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp
    kind = assets.asset_class(ticker)
    if kind == "crypto":
        return stamp.tz_convert("UTC").strftime("%Y-%m-%d")
    local = stamp.tz_convert(settings.NEW_YORK)
    if kind in ("forex", "gold"):
        local += pd.Timedelta(hours=settings.FX_ROLL_HOURS)
    return local.strftime("%Y-%m-%d")


def bar_day(ticker: str, bar_start: float) -> str:
    """The trading day of a daily bar that TradingView says began at ``bar_start`` (epoch seconds).

    Used instead of the clock when TradingView says which bar it is: gold's bar, for example, has not rolled yet in the
    hour after 17:00 New York, while forex's has."""
    return trading_day(ticker, datetime.fromtimestamp(bar_start, timezone.utc))


def tickers() -> list[str]:
    """Every instrument with a record, by its canonical symbol."""
    return sorted(p.stem for p in settings.DIR.glob("*.json")) if settings.DIR.exists() else []
