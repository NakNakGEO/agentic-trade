"""When a model's next round of calls is due, for accounts that call more often than once a day.

An account with ``call_every_minutes`` set makes a round of calls on a fixed clock grid (UTC, starting at the daily decision
time, so every 120 minutes means 00:30, 02:30, ...). Two rules keep it orderly:
  * a model never runs two rounds at once: if the last round is still working when a slot arrives, the slot waits and the
    round starts as soon as the last one is done (a backlog of missed slots is not replayed, only the newest one starts);
  * each round writes into its own run folder (<decisions run>_s<YYYYMMDDHHMM>), because the agent framework keeps only
    one decision per pair per date.
An account without ``call_every_minutes`` keeps the old once-a-day behaviour and never touches this module.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from paper_trade import config, eventlog
from paper_trade.decide import feed_path, logged_cells
from paper_trade.live import settings

STALL_SECONDS = 900                  # a round whose pairs have not moved for this long, and is not complete, counts as over
START_GRACE_SECONDS = 600            # a round that was just started has no events yet: give its workers this long to show up
_SLOT_NAME = re.compile(r"^(?P<base>.+)_s(?P<slot>\d{12})$")


def latest_slot(now: datetime, every_minutes: int, anchor: tuple[int, int] = settings.DECISION_AFTER_UTC) -> datetime:
    """The newest grid time at or before ``now`` (UTC), counting from the anchor time of the day."""
    now = now.astimezone(timezone.utc)
    first = now.replace(hour=anchor[0], minute=anchor[1], second=0, microsecond=0)
    steps = int((now - first).total_seconds() // (every_minutes * 60))          # negative before the anchor: floors into yesterday
    return first + timedelta(minutes=steps * every_minutes)


def slot_id(slot: datetime) -> str:
    return slot.astimezone(timezone.utc).strftime("%Y%m%d%H%M")


def slot_run_id(base: str, slot: datetime) -> str:
    return f"{base}_s{slot_id(slot)}"


def slot_runs(base: str) -> list[str]:
    """The run ids of every round made so far for this decision run, oldest first."""
    root = config.RUNS_DIR / "backtest"
    names = [p.name for p in root.iterdir() if p.is_dir()] if root.exists() else []
    found = [n for n in names if (m := _SLOT_NAME.match(n)) and m.group("base") == base]
    return sorted(found)


def all_runs(account: settings.Account) -> list[str]:
    """Every decision run an account has: the old daily one, then each round's, oldest first."""
    runs = [account.decisions_run]
    if account.call_every_minutes:
        runs += slot_runs(account.decisions_run)
    return runs


def slot_of(run_id: str) -> str:
    """The slot id a run folder name carries, or '' for an old daily run."""
    match = _SLOT_NAME.match(run_id)
    return match.group("slot") if match else ""


def round_state(run_id: str, tickers, started: datetime | None, now: datetime) -> str:
    """'none' (no such round), 'running', or 'over' (every pair has its call, or the work stalled)."""
    if started is None:
        return "none"
    if logged_cells(run_id) >= len(tickers):
        return "over"
    cells = eventlog.cells(feed_path(run_id))
    newest = max((c["last"] for c in cells.values()), default=None)
    if newest is None:
        return "running" if (now - started).total_seconds() < START_GRACE_SECONDS else "over"
    return "running" if now.timestamp() - newest < STALL_SECONDS else "over"


def busy(account: settings.Account, last_slot: datetime | None, now: datetime, last_started: datetime | None = None) -> bool:
    """Is this account's latest round still working? ``last_started`` is when that round actually began (it can be later than
    its slot time when the round had to wait for the one before it); without it the slot time is used."""
    if last_slot is None:
        return False
    return round_state(slot_run_id(account.decisions_run, last_slot), account.tickers, last_started or last_slot, now) == "running"


def due(account: settings.Account, now: datetime, last_slot: datetime | None, last_started: datetime | None = None) -> datetime | None:
    """The slot to start now, or None: the newest grid time not yet served, and only when no round is still running."""
    if not account.call_every_minutes:
        return None
    slot = latest_slot(now, account.call_every_minutes)
    if last_slot is not None and slot <= last_slot:
        return None
    return None if busy(account, last_slot, now, last_started) else slot
