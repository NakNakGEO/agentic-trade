"""Supervisor for a run split into one stream per ticker (see launch_fx9.ps1).

Exit code 0 = every planned decision is logged, or the deadline passed. Exit code 1 = something needs attention
(a crashed stream, a stalled run, a burst of failed model calls, the sleep blocker gone).
Usage: python watch_run.py <run_id> [deadline_hours]
"""

from __future__ import annotations

import sys
import time

from paper_trade import assets
from paper_trade.decide import read_meta
from watch_overnight import (CHECK_EVERY, RUNS, STALL_MINUTES, alive, decisions, mtime, read_pids,
                             recent_errors)

ERROR_BURST = (20, 600)         # retried rate-limit replies are logged too, so allow more than the overnight run


def expected(meta: dict, ticker: str) -> int:
    return sum(assets.trades_on(ticker, d) for d in meta["dates"])


def check(run: str, started: float, deadline_hours: float) -> tuple[int | None, str]:
    meta = read_meta(run)
    done = decisions(run)
    summary = f"{run} {len(done)}/{meta['planned_cells']}"
    if len(done) >= meta["planned_cells"]:
        return 0, f"ALL DONE: {summary}"
    if time.time() - started > deadline_hours * 3600:
        return 0, f"DEADLINE ({deadline_hours:g} h) reached: {summary}"

    pids, problems = read_pids(), []
    logged = [assets.canonical(ticker) for ticker, _ in done]
    for ticker in meta["tickers"]:
        name = f"{run}_{ticker}"
        finished = logged.count(assets.canonical(ticker)) >= expected(meta, ticker)
        if name in pids and not alive(pids[name]) and not finished:
            problems.append(f"CRASHED {name}")
    if "keep_awake" in pids and not alive(pids["keep_awake"]):
        problems.append("the keep-awake helper stopped")
    last = mtime(RUNS / run / "events.jsonl")
    if last and time.time() - last > STALL_MINUTES * 60:
        problems.append(f"STALLED {run}: no model activity for {int((time.time() - last) / 60)} min")
    burst = recent_errors(RUNS / run / "events.jsonl", ERROR_BURST[1])
    if burst >= ERROR_BURST[0]:
        problems.append(f"API ERRORS: {burst} failed model calls in the last {ERROR_BURST[1] // 60} min")
    return (1, "; ".join(problems) + f"  [{summary}]") if problems else (None, summary)


def main() -> int:
    run = sys.argv[1]
    deadline = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
    started = time.time()
    while True:
        code, message = check(run, started, deadline)
        if code is not None:
            print(message, flush=True)
            return code
        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    sys.exit(main())
