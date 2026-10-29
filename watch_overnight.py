"""Overnight supervisor. Sleeps and checks; exits the first time something needs attention.

Exit code 1 = a problem (crashed stream, stalled run, burst of API errors, sleep blocker gone).
Exit code 0 = both runs finished, or the deadline passed (so partial results can be written up).
Usage: python watch_overnight.py [deadline_hours]
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(r"D:\turic trading agent")
RUNS = ROOT / "runs" / "backtest"
PIDS = ROOT / "logs" / "pids.txt"
LOCAL_RUN, API_RUN = "daily_local_think", "daily_api_think"
LOCAL_STREAM = "local_think"
SHARDS = {"api_think_s1": ("AAPL",), "api_think_s2": ("BTC-USD",),
          "api_think_s3": ("EURUSD",), "api_think_s4": ("XAUUSD",)}
WINDOW = (date(2026, 10, 12), date(2026, 10, 27))      # daily decisions
CHECK_EVERY = 120                  # seconds
STALL_MINUTES = 40                 # thinking mode makes single replies slow, so allow longer silences
ERROR_BURST = (8, 600)             # this many failed model calls within this many seconds
ALIASES = {"XAUUSD": {"XAUUSD", "GC=F"}, "EURUSD": {"EURUSD", "EURUSD=X"}}
ENTRY = re.compile(r"^\[(\d{4}-\d{2}-\d{2}) \| ([^|]+?) \|")


def expected(ticker: str) -> int:
    """Daily decisions for an asset in the window: crypto every day, the rest on weekdays."""
    days = [WINDOW[0] + timedelta(n) for n in range((WINDOW[1] - WINDOW[0]).days + 1)]
    return sum(1 for d in days if ticker.endswith("-USD") or d.weekday() < 5)


TOTAL = sum(expected(t) for tickers in SHARDS.values() for t in tickers)


def alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], capture_output=True, text=True,
                         creationflags=0x08000000).stdout
    return f'"{pid}"' in out


def read_pids() -> dict[str, int]:
    pids = {}
    if PIDS.exists():
        for line in PIDS.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit():
                pids[parts[0]] = int(parts[1])          # the latest line for a name wins
    return pids


def decisions(run: str) -> list[tuple[str, str]]:
    path = RUNS / run / "trading_memory.md"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = ENTRY.match(line)
        if m:
            rows.append((m.group(2).strip(), m.group(1)))
    return rows


def shard_done(name: str, api: list[tuple[str, str]]) -> bool:
    wanted = set().union(*(ALIASES.get(t, {t}) for t in SHARDS[name]))
    return sum(1 for ticker, _ in api if ticker in wanted) >= sum(expected(t) for t in SHARDS[name])


def recent_errors(path: Path, seconds: int) -> int:
    if not path.exists():
        return 0
    cutoff, count = time.time() - seconds, 0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-300:]:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        count += event.get("kind") == "error" and event.get("t", 0) > cutoff
    return count


def mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def check(started: float, deadline_hours: float) -> tuple[int | None, str]:
    local, api = decisions(LOCAL_RUN), decisions(API_RUN)
    summary = f"{LOCAL_RUN} {len(local)}/{TOTAL}, {API_RUN} {len(api)}/{TOTAL}"
    if len(local) >= TOTAL and len(api) >= TOTAL:
        return 0, f"ALL DONE: {summary}"
    if time.time() - started > deadline_hours * 3600:
        return 0, f"DEADLINE ({deadline_hours:g} h) reached: {summary}"

    pids, problems = read_pids(), []
    for name, pid in pids.items():
        if alive(pid):
            continue
        if name == "keep_awake":
            problems.append("the keep-awake helper stopped")
        elif name == LOCAL_STREAM and len(local) < TOTAL:
            problems.append(f"CRASHED {name}")
        elif name in SHARDS and not shard_done(name, api):
            problems.append(f"CRASHED {name}")
    for run, names in ((LOCAL_RUN, [LOCAL_STREAM]), (API_RUN, list(SHARDS))):
        last = mtime(RUNS / run / "events.jsonl")
        if last and any(n in pids and alive(pids[n]) for n in names) and time.time() - last > STALL_MINUTES * 60:
            problems.append(f"STALLED {run}: no model activity for {int((time.time() - last) / 60)} min")
    burst = recent_errors(RUNS / API_RUN / "events.jsonl", ERROR_BURST[1])
    if burst >= ERROR_BURST[0]:
        problems.append(f"API ERRORS: {burst} failed model calls in the last {ERROR_BURST[1] // 60} min")
    return (1, "; ".join(problems) + f"  [{summary}]") if problems else (None, summary)


def main() -> int:
    deadline = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    started = time.time()
    while True:
        code, message = check(started, deadline)
        if code is not None:
            print(message, flush=True)
            return code
        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    sys.exit(main())
