"""TradingView prices for the live paper accounts, run inside tvmcp/.venv (the tradingview-mcp package's environment).

Reads a JSON map of ticker -> "EXCHANGE:SYMBOL|screener" from standard input and prints one JSON object:
{"fetched_at", "symbols": {ticker: {"m1": bar, "m1_prev": bar, "d1": {open, high, low, close, atr, volume}, "mode": ...}}}
where a bar is {open, high, low, close, time} (``time`` = the 1-minute bar's own start, epoch seconds): ``m1`` is the bar
forming now, ``m1_prev`` the one before it, now finished, and ``mode`` is TradingView's data mode for the instrument
("streaming" = real time, "delayed_streaming_900" = 15 minutes behind, as for US stocks on TradingView's free data).
It makes ONE scanner request for every instrument (see scan.py). Callers within SHARE_SECONDS share one fetch, one process
at a time (gate.py), so the loops, the dashboard and the decision workers together ask TradingView about once a minute.
"""

import json
import sys
from datetime import datetime, timezone

import gate
import scan

SHARE_SECONDS = 40
BAR_FIELDS = ("open", "high", "low", "close", "time")
COLUMNS = ([f"{k}{offset}|1" for offset in ("", "[1]") for k in BAR_FIELDS]
           + ["open", "high", "low", "close", "volume", "time", "ATR", "update_mode"])


def _bar(row: dict, offset: str):
    bar = {k: row.get(f"{k}{offset}|1") for k in BAR_FIELDS}
    return bar if bar["close"] is not None and bar["time"] is not None else None


def fetch(symbols: dict) -> dict:
    rows = scan.scan(symbols, COLUMNS)
    out = {}
    for ticker in symbols:
        row = rows.get(ticker) or {}
        day = {k: row.get(k) for k in ("open", "high", "low", "close", "volume", "time")}   # ``time``: the daily bar's own start
        out[ticker] = {"m1": _bar(row, ""), "m1_prev": _bar(row, "[1]"), "mode": row.get("update_mode"),
                       "d1": {**day, "atr": row.get("ATR")} if day["close"] is not None else None}
    return {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "symbols": out}


if __name__ == "__main__":
    request = json.loads(sys.stdin.read())
    print(gate.serve(request, SHARE_SECONDS, lambda: json.dumps(fetch(request))))
