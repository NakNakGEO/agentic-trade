"""Replay one trade on the recorded minute candles under an exit rule, with the live account's own stop-and-target logic.

The replay builds a position and hands it to ``live.book.step``, the function the live account uses, so a trade replayed
with the rules it was traded under ends the way it really ended. A trade that a later call closed ("New call") is cut at
that call: the exit rules only get the minutes before it, and the call's own price closes it if they did not.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from paper_trade.live import book as lb
from paper_trade.live import settings as live
from paper_trade.whatif import settings


@dataclass(frozen=True)
class Trade:
    """A trade as it was opened, plus how it really ended (empty for a trade still open)."""
    ticker: str
    side: int
    entry: float
    stop: float
    target: float
    lot: float | None
    opened_at: str
    closed_at: str = ""
    reason: str = ""
    exit: float | None = None
    pnl: float | None = None


@dataclass(frozen=True)
class Result:
    pnl: float                  # after both fees (an open trade: marked at the last recorded minute, exit fee included)
    reason: str                 # Take-profit, Stop-loss, Time limit, New call, or Open
    closed_at: str
    exit: float | None


def trades_of(book: lb.Book) -> list[Trade]:
    """Every trade of a book, finished and open, oldest first."""
    done = [Trade(c.ticker, c.side, c.entry, c.stop, c.target, c.lot, c.opened_at, c.closed_at, c.reason, c.exit, c.pnl)
            for c in book.closed if c.stop is not None and c.target is not None]
    still = [Trade(p.ticker, p.side, p.entry, p.stop, p.target, p.lot, p.opened_at) for p in book.positions.values()]
    return sorted(done + still, key=lambda t: t.opened_at)


def _position(trade: Trade, stop: float, target: float, lot: float | None, hours: float) -> lb.Position:
    distance = abs(trade.entry - stop)
    deadline = (datetime.fromisoformat(trade.opened_at) + timedelta(hours=hours)).isoformat(timespec="seconds") if hours else ""
    return lb.Position(trade.ticker, trade.side, trade.entry, stop, target, trade.opened_at, trade.opened_at[:10], "",
                       distance * lb.qty(trade.ticker, trade.entry, lot), lb._fee(trade.ticker, trade.entry, lot), lot, deadline)


def replay(trade: Trade, minutes: pd.DataFrame, style: live.Style, stop_mult: float, reward_risk: float, hours: float,
           equity: float | None = None, friction=None) -> Result:
    """The trade under another exit rule: stop ``stop_mult`` average ranges away, target ``reward_risk`` stops away, closed
    after ``hours``. The range is the one the live stop was placed with, so only the rule changes. Sized to the style's
    risk share of ``equity`` (``None``: the lot the trade really had, for a replay of the trade as it was). ``friction`` is the
    account's slippage (none: fills at the price); the entry price of a trade already includes its entry slippage."""
    distance = abs(trade.entry - trade.stop) / style.stop_mult * stop_mult
    stop, target = trade.entry - trade.side * distance, trade.entry + trade.side * distance * reward_risk
    lot = trade.lot if equity is None else lb.lot_for(style, trade.ticker, trade.entry, distance, equity)
    return _run(trade, minutes, _position(trade, stop, target, lot, hours), friction)


def as_traded(trade: Trade, minutes: pd.DataFrame, hours: float, friction=None) -> Result:
    """The trade with the exact stop, target and lot it had (to check the replay against what really happened)."""
    return _run(trade, minutes, _position(trade, trade.stop, trade.target, trade.lot, hours), friction)


def _run(trade: Trade, minutes: pd.DataFrame, position: lb.Position, friction=None) -> Result:
    cut = pd.Timestamp(trade.closed_at).tz_convert("UTC").tz_localize(None) if trade.reason == "New call" else None
    window = minutes if cut is None else minutes[minutes.index < cut]
    book = lb.Book()
    book.positions[trade.ticker] = position
    lb.step(book, trade.ticker, window, friction)
    if not book.closed and trade.reason == "New call":      # the call's own price is the fill the trade really got: no slippage on it again
        lb.close_position(book, trade.ticker, trade.exit, trade.closed_at, "New call")
    if book.closed:
        closed = book.closed[0]
        return Result(closed.pnl, closed.reason, closed.closed_at, closed.exit)
    last = float(minutes["Close"].iloc[-1])
    gross = position.side * lb.qty(trade.ticker, last, position.lot) * (last - position.entry)
    return Result(round(gross - lb._fee(trade.ticker, last, position.lot) - position.cost, 4), "Open", "", None)


def differences(trade: Trade, now: Result) -> list[str]:
    """How a replay of a finished trade differs from what really happened (empty: it was reproduced exactly)."""
    out = []
    if now.reason != trade.reason:
        out.append(f"ended by {now.reason}, really {trade.reason}")
    if now.closed_at != trade.closed_at:
        out.append(f"at {now.closed_at}, really {trade.closed_at}")
    if abs(now.pnl - trade.pnl) > settings.MONEY_TOLERANCE:
        out.append(f"made {now.pnl:+.2f}, really {trade.pnl:+.2f}")
    return out
