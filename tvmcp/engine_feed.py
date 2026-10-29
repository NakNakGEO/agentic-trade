"""TradingView data for the AI models' research, run inside tvmcp/.venv (the tradingview-mcp package's environment).

Reads one JSON request from standard input and prints one JSON reply, each made with ONE scanner request (see scan.py):
  {"mode": "analysis", "symbols": {ticker: "EXCHANGE:SYMBOL|screener"}, "intervals": ["1h", "4h", "1d", "1W"]}
      -> {"fetched_at", "analysis": {ticker: {interval: {indicator: value}}}}   (about 36 indicators per timeframe)
  {"mode": "screener", "symbols": {...}, "stock_fields": [...]}
      -> {"fetched_at", "rows": {ticker: {field: value}}}   (name and description for all, company figures for stocks)
Callers asking for the same thing within SHARE_SECONDS share one fetch, one process at a time (gate.py).
"""

import json
import sys
from datetime import datetime, timezone

import gate
import scan

SHARE_SECONDS = 120


def analysis(symbols: dict, intervals: list) -> dict:
    columns = [name + scan.TIMEFRAMES[i] for i in intervals for name in scan.INDICATORS] + ["time"]    # time: the daily bar's start
    rows = scan.scan(symbols, columns)
    out = {}
    for ticker in symbols:
        row = rows.get(ticker, {})
        frames = {i: {name: row.get(name + scan.TIMEFRAMES[i]) for name in scan.INDICATORS} for i in intervals}
        out[ticker] = {i: {k: v for k, v in f.items() if v is not None} for i, f in frames.items() if f["close"] is not None}
        if "1d" in out[ticker] and row.get("time") is not None:
            out[ticker]["1d"]["time"] = row["time"]
    return out


def screener(symbols: dict, stock_fields: list) -> dict:
    """Current screener fields per ticker, in one request: company figures are empty for anything but stocks."""
    fields = list(dict.fromkeys([*stock_fields, "name", "description", "type", "currency"]))
    return {t: {k: v for k, v in row.items() if v is not None} for t, row in scan.scan(symbols, fields).items()}


def answer(request: dict) -> str:
    reply = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if request["mode"] == "analysis":
        reply["analysis"] = analysis(request["symbols"], request["intervals"])
    else:
        reply["rows"] = screener(request["symbols"], request["stock_fields"])
    return json.dumps(reply)


if __name__ == "__main__":
    request = json.loads(sys.stdin.read())
    print(gate.serve(request, SHARE_SECONDS, lambda: answer(request)))
