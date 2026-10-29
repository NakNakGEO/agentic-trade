"""TradingView prices for the live book, through the tradingview-mcp package (installed in its own venv, tvmcp/.venv).

Each call runs ``tvmcp/feed.py`` there and reads back the current 1-minute candle and today's daily candle with its
14-day ATR for every pair. TradingView only serves the candle that is forming now, so the live loop records each minute's
candle in ``settings.TV_CANDLE_DIR``; the M1 history (for stops, targets and the charts) builds up from those records.
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone

import pandas as pd

from paper_trade import assets, config
from paper_trade.live import settings, tv_guard

CREATE_NO_WINDOW = 0x08000000
_cache: dict = {"at": 0.0, "data": None, "error": None, "failed_at": 0.0}


def symbol(ticker: str) -> str | None:
    """TradingView's 'EXCHANGE:SYMBOL|screener' for a ticker, or None when it is not mapped."""
    return settings.TV_SYMBOLS.get(assets.canonical(ticker))


def enabled() -> bool:
    return settings.TV_PYTHON.exists() and settings.TV_FEED.exists()


def snapshot(tickers=None) -> dict:
    """{ticker: {"m1": {...}, "d1": {...}}} for the mapped tickers.

    One snapshot file is shared by every live loop, so TradingView is asked at most once per TV_CACHE_SECONDS.
    A read-only (test) copy only reads that file and never asks TradingView."""
    if config.READ_ONLY_DATA:
        return _read_only_snapshot()
    if _cache["data"] is not None and time.time() - _cache["at"] < settings.TV_CACHE_SECONDS:
        return _cache["data"]
    shared = settings.TV_SNAPSHOT_PATH
    if shared.exists() and time.time() - shared.stat().st_mtime < settings.TV_CACHE_SECONDS:
        data = json.loads(shared.read_text(encoding="utf-8"))
        _cache.update(at=shared.stat().st_mtime, data=data)
        return data
    tv_guard.check()
    if _cache["error"] and time.time() - _cache["failed_at"] < settings.TV_RETRY_SECONDS:
        raise RuntimeError(_cache["error"])      # one failure per cycle, not one for each of the pairs asking
    tickers = [t for t in (tickers or settings.TICKERS) if symbol(t)]
    wanted = {**{t: symbol(t) for t in tickers}, **settings.TV_RECORD_EXTRA}
    try:
        reply = subprocess.run([str(settings.TV_PYTHON), str(settings.TV_FEED)], input=json.dumps(wanted), capture_output=True,
                               text=True, timeout=settings.TV_TIMEOUT_SECONDS, creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:            # waited too long behind other requests: not TradingView refusing us
        _cache.update(error="TradingView feed timed out waiting its turn", failed_at=time.time())
        raise RuntimeError(_cache["error"]) from None
    if reply.returncode != 0:
        tv_guard.failed()
        _cache.update(error=f"TradingView feed failed: {tv_guard.why(reply.stderr)}", failed_at=time.time())
        raise RuntimeError(_cache["error"])
    tv_guard.succeeded()
    _cache["error"] = None
    data = json.loads(reply.stdout.strip().splitlines()[-1])
    shared.parent.mkdir(parents=True, exist_ok=True)
    shared.write_text(json.dumps(data), encoding="utf-8")
    _cache.update(at=time.time(), data=data)
    return data


def _read_only_snapshot() -> dict:
    path = settings.TV_SNAPSHOT_PATH
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        raise RuntimeError("read-only data mode: the live system has not written a TradingView snapshot yet") from None
    if age > settings.READ_ONLY_MAX_AGE_SECONDS:
        raise RuntimeError(f"read-only data mode: the live snapshot is {age:.0f} s old (is the live loop running?)")
    return json.loads(path.read_text(encoding="utf-8"))


def last_snapshot() -> dict | None:
    """The newest snapshot on disk however old, for screens that show a quote with its age (never for trading)."""
    try:
        return json.loads(settings.TV_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _row(ticker: str, key: str) -> dict:
    row = snapshot()["symbols"].get(ticker, {}).get(key)
    if not row or row.get("close") is None:
        raise ValueError(f"TradingView has no {key} candle for {ticker}")
    return row


def latest_price(ticker: str) -> float:
    return float(_row(ticker, "m1")["close"])


def daily_atr(ticker: str) -> float:
    return float(_row(ticker, "d1")["atr"])


def _store(ticker: str):
    return settings.TV_CANDLE_DIR / f"{ticker}.jsonl"


OHLC = ("open", "high", "low", "close")


def _minute_of(bar: dict, fetched: str) -> str:
    """The UTC minute a bar began: TradingView's own start time for it (a delayed instrument's bar is older than the fetch)."""
    if bar.get("time") is not None:
        return datetime.fromtimestamp(bar["time"], timezone.utc).strftime("%Y-%m-%d %H:%M")
    return fetched[:16].replace("T", " ")


def _recent(path) -> list[dict]:
    """The last few recorded lines of a candle file, read from its end."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - 900))
            lines = handle.read().decode("utf-8", "ignore").strip().splitlines()[-8:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def record_minute(stamp: str) -> None:
    """Save each pair's candles from the newest snapshot (the loop calls this every cycle).

    A snapshot carries the minute that has just finished and the one forming now. Both are saved under their own minute,
    so a finished minute replaces the partial copy saved while it was forming (the last record of a minute wins), and a
    record identical to one already saved (another loop sharing the snapshot, or a market that is closed) is not repeated.
    A read-only (test) copy records nothing."""
    if config.READ_ONLY_DATA:
        return
    settings.TV_CANDLE_DIR.mkdir(parents=True, exist_ok=True)
    data = snapshot()
    fetched = data.get("fetched_at") or stamp
    for ticker, rows in data["symbols"].items():
        path = _store(ticker)
        seen = {(r.get("t"), *(r.get(k) for k in OHLC)) for r in _recent(path)}
        new = []
        for bar in (rows.get("m1_prev"), rows.get("m1")):          # the finished minute first, then the forming one
            if bar and bar.get("close") is not None:
                record = {"t": _minute_of(bar, fetched), **{k: bar[k] for k in OHLC}, "at": fetched, "v": 2}
                key = (record["t"], *(record[k] for k in OHLC))
                if key not in seen:
                    seen.add(key)
                    new.append(record)
        if new:
            with open(path, "a", encoding="utf-8") as out:
                out.write("".join(json.dumps(r) + "\n" for r in new))


def parse_store(lines) -> pd.DataFrame:
    """Recorded candles as Open/High/Low/Close rows on UTC minutes; the last record of each minute wins."""
    rows = {}
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        rows[r["t"]] = (float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
    frame = pd.DataFrame([(pd.Timestamp(t), *v) for t, v in sorted(rows.items())],
                         columns=["time", "Open", "High", "Low", "Close"])
    return frame.set_index("time")


_parsed: dict = {}


def all_candles(ticker: str) -> pd.DataFrame:
    """Every recorded M1 candle of ``ticker``, however old (for replays; ``candles`` keeps only the latest two days)."""
    path = _store(ticker)
    if not path.exists():
        raise ValueError(f"no TradingView candles recorded for {ticker} yet")
    return parse_store(path.read_text(encoding="utf-8").splitlines())


def candles(ticker: str) -> pd.DataFrame:
    """The recorded M1 candles of ``ticker`` (re-read only when its file has grown)."""
    path = _store(ticker)
    if not path.exists():
        raise ValueError(f"no TradingView candles recorded for {ticker} yet")
    size = path.stat().st_size
    hit = _parsed.get(ticker)
    if hit and hit[0] == size:
        return hit[1]
    frame = parse_store(path.read_text(encoding="utf-8").splitlines()[-settings.TV_CANDLES_KEEP:])
    _parsed[ticker] = (size, frame)
    return frame
