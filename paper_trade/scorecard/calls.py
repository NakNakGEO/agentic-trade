"""The calls to grade: each model's decisions with the moment each one landed and TradingView's rating from the evening before."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from paper_trade import assets, daybook, eventlog
from paper_trade.decide import feed_path
from paper_trade.lots import side_of


@dataclass(frozen=True)
class Call:
    run: str                    # the decision run it came from (live_gemma, live_qwen)
    ticker: str
    day: str                    # the date the call was made for
    rating: str                 # as written: Buy, Overweight, Hold, Underweight, Sell (anything else could not be read)
    side: int                   # +1 buy, -1 sell, 0 hold or unreadable
    at: float                   # epoch seconds when the call landed (the newest event of its work)
    tv_before: float | None     # TradingView's daily rating at the end of the previous recorded day, if we have it


def tv_rating_before(ticker: str, day: str, look_back_days: int = 5) -> float | None:
    """TradingView's daily rating (-1 to +1) from the latest recorded day before ``day``: what was known when the call was made."""
    when = datetime.strptime(day, "%Y-%m-%d")
    for back in range(1, look_back_days + 1):
        value = (daybook.row(ticker, (when - timedelta(days=back)).strftime("%Y-%m-%d")).get("ratings") or {}).get("1d")
        if value is not None:
            return float(value)
    return None


def load_calls(run_id: str, tickers=None) -> list[Call]:
    """Every decision of a run that has a recorded landing time, oldest first (optionally only for some pairs)."""
    from paper_trade.report import load_decisions

    try:
        decisions, _ = load_decisions(run_id)
    except FileNotFoundError:
        return []
    wanted = {assets.canonical(t) for t in tickers} if tickers else None
    cells = {}
    for label, cell in eventlog.cells(feed_path(run_id)).items():
        parts = eventlog.split(label)
        if parts:
            cells[(assets.canonical(parts[0]), parts[1])] = cell
    out = []
    for d in decisions:
        key = (assets.canonical(d.ticker), d.date)
        if key not in cells or (wanted is not None and key[0] not in wanted):
            continue
        out.append(Call(run_id, d.ticker, d.date, d.rating, side_of(d.rating), cells[key]["last"], tv_rating_before(d.ticker, d.date)))
    return sorted(out, key=lambda c: c.at)
