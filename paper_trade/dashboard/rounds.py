"""How the day's round of calls is going, pair by pair, read from the run's event log.

Each pair is a team of 11 AI agents that work one after another (three analysts in any order, then the researchers, the
manager, the trader, the three risk reviewers and the portfolio manager, who writes the call). A hosted model works on all
pairs at once; a local one takes them one at a time. The log itself is read by paper_trade.eventlog.
"""

from __future__ import annotations

import time
from pathlib import Path

from paper_trade import assets, eventlog

STAGES = ("Market Analyst", "News Analyst", "Fundamentals Analyst", "Bull Researcher", "Bear Researcher", "Research Manager",
          "Trader", "Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager")
PAUSED_AFTER_SECONDS = 300          # a pair with no activity for this long, and no call yet, is shown as paused


def _row(ticker: str, cell: dict | None, rating: str | None, now: float) -> dict:
    if cell is None:
        return {"ticker": ticker, "status": "done" if rating else "waiting", "steps": ["done" if rating else "todo"] * len(STAGES), "now": "",
                "seconds": 0, "tokens": 0, "rating": rating, "started": ""}
    quiet = now - cell["last"]
    status = "done" if rating else "paused" if quiet > PAUSED_AFTER_SECONDS else "working"
    working = status == "working"
    steps = ["now" if working and stage == cell["node"] else "done" if stage in cell["nodes"] else "todo" for stage in STAGES]
    if rating:
        steps = ["done"] * len(STAGES)
    return {"ticker": ticker, "status": status, "steps": steps, "now": cell["node"] if working else "",
            "seconds": round((cell["last"] if rating or not working else now) - cell["first"]), "tokens": cell["tokens"],
            "rating": rating, "started": time.strftime("%H:%M", time.gmtime(cell["first"])), "quiet": round(quiet)}


def pairs_of_round(account_tickers, asked) -> list[str]:
    """The pairs a round was started for: the account's pairs that the round's own record lists (a test round may ask about one
    pair only, and the rest of the account's pairs are not 'waiting', they were never asked). All of them without a record."""
    wanted = {assets.canonical(t) for t in asked or []}
    return [t for t in account_tickers if assets.canonical(t) in wanted] or list(account_tickers)


def progress(path: Path, decisions: list[dict], tickers, parallel: bool, now: float | None = None) -> dict | None:
    """The latest day's round: one row per pair, plus the round's elapsed time and a rough time left. None without a log."""
    now = now or time.time()
    cells = eventlog.cells(path)
    days = {label.rsplit(" ", 1)[1] for label in cells if " " in label}
    if not days:
        return None
    day = max(days)
    by_key = {assets.canonical(label.rsplit(" ", 1)[0]): cell for label, cell in cells.items() if label.endswith(" " + day)}
    called = {assets.canonical(d["ticker"]): d["rating"] for d in decisions if d["date"] == day}
    rows = [_row(t, by_key.get(assets.canonical(t)), called.get(assets.canonical(t)), now) for t in tickers]
    started = [c["first"] for c in by_key.values()]
    finished = [r for r in rows if r["status"] == "done"]
    working = [r for r in rows if r["status"] in ("working", "paused")]
    waiting = [r for r in rows if r["status"] == "waiting"]
    average = sum(r["seconds"] for r in finished) / len(finished) if finished else None
    left = None
    if average and (working or waiting):                          # a paused pair says nothing about how long the rest will take
        left = max((max(0, average - r["seconds"]) for r in working if r["status"] == "working"), default=0)             + (0 if parallel else average * len(waiting))
    ends = max((c["last"] for c in by_key.values()), default=now)
    return {"day": day, "rows": rows, "done": len(finished), "total": len(rows), "parallel": parallel,
            "started": time.strftime("%H:%M", time.gmtime(min(started))) if started else "",
            "elapsed": round((ends if not (working or waiting) else now) - min(started)) if started else 0,
            "left": round(left) if left else None, "stages": list(STAGES)}
