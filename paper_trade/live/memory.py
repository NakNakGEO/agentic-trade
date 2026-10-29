"""What a model said before, for its own next round.

The agent framework keeps one decision per pair per date and its own memory is split by date, so the rounds of a day do not
see each other. This puts a model's own recent calls on a pair into the context every agent reads (see tvdata/desk.py).
"""

from __future__ import annotations

from datetime import datetime, timezone

from paper_trade import assets, eventlog
from paper_trade.decide import feed_path
from paper_trade.live import schedule, settings

RECENT_CALLS = 6


def recent_calls(account: settings.Account, ticker: str, limit: int = RECENT_CALLS) -> list[tuple[float, str]]:
    """(landing time, rating) of the account's latest calls on ``ticker``, oldest first."""
    from paper_trade.report import load_decisions

    wanted, found = assets.canonical(ticker), []
    for run in schedule.all_runs(account):
        try:
            decisions, _ = load_decisions(run)
        except FileNotFoundError:
            continue
        cells = {}
        for label, cell in eventlog.cells(feed_path(run)).items():
            parts = eventlog.split(label)
            if parts:
                cells[(assets.canonical(parts[0]), parts[1])] = cell["last"]
        found += [(cells[key], d.rating) for d in decisions if (key := (assets.canonical(d.ticker), d.date)) in cells and key[0] == wanted]
    return sorted(found)[-limit:]


def recent_calls_text(account: settings.Account, ticker: str) -> str:
    """One sentence for the agents' context, or nothing when there are no earlier calls."""
    calls = recent_calls(account, ticker)
    if not calls:
        return ""
    said = ", ".join(f"{datetime.fromtimestamp(t, timezone.utc):%m-%d %H:%M} {rating}" for t, rating in calls)
    return (f" Your own latest calls on this instrument (UTC, oldest first): {said}. They are context, not a conclusion:"
            " judge the market as it is now, and call Hold or the opposite when the picture has changed.")
