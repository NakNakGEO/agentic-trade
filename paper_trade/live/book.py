"""The live paper account: each new decision enters at the live price with the bridge's lot, stop and take-profit.

Pure logic (no network): prices and bars come in as arguments, so it is easy to test. One shared pool of money, a stop
at 2 x the 14-day range and a target twice as far, one position per pair, and an open-risk cap, exactly as in lots.py.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from paper_trade import assets, config
from paper_trade.bridge import settings as rules
from paper_trade.bridge import sizing
from paper_trade.lots import dollars_per_quote, side_of, units_of
from paper_trade.live import settings


@dataclass
class Position:
    ticker: str
    side: int               # +1 long, -1 short
    entry: float
    stop: float
    target: float
    opened_at: str          # ISO time, UTC
    decision_date: str
    rating: str
    risk: float             # dollars lost if the stop is hit
    cost: float             # fee paid on entry
    lot: float | None = None    # None: the fixed lot
    deadline: str = ""      # ISO time, UTC: close at the market then (empty: no time limit)
    note: str = ""          # how the trade differs from the usual rules ("agent stop", "mild size"), empty for the usual


@dataclass(frozen=True)
class Tweaks:
    """What an account may take from the agent's full answer beyond its rating (see plan.py). Empty = the usual rules."""
    stop: float | None = None   # the stop level the agent asked for, used when it is sane
    scale: float = 1.0          # share of the usual size
    hold: str = ""              # the agent said to wait for a condition: why this call does not trade now


@dataclass
class Closed:
    ticker: str
    side: int
    entry: float
    exit: float
    opened_at: str
    closed_at: str
    reason: str             # Take-profit, Stop-loss, Time limit or New call
    pnl: float              # after both fees
    decision_date: str
    rating: str
    lot: float | None = None
    stop: float | None = None       # the levels the trade had (empty on trades closed before these were kept)
    target: float | None = None


@dataclass
class Book:
    start_cash: float = config.STARTING_CASH
    created: str = ""
    realized: float = 0.0
    positions: dict = field(default_factory=dict)       # ticker -> Position
    closed: list = field(default_factory=list)          # Closed
    skipped: list = field(default_factory=list)         # {"ticker", "date", "rating", "why"}
    applied: list = field(default_factory=list)         # "TICKER|date" of every decision already acted on
    history: list = field(default_factory=list)         # {"t", "equity"}


def qty(ticker: str, price: float, lot: float | None = None) -> float:
    """Shares-equivalent of ``lot`` lots (the fixed lot when none is given): quantity x price is its value in dollars."""
    return units_of(ticker, lot) * dollars_per_quote(ticker, price)


def _fee(ticker: str, price: float, lot: float | None = None) -> float:
    rate = config.LOT_COST_BPS.get(assets.asset_class(ticker), config.COST_BPS) / 1e4
    return qty(ticker, price, lot) * price * rate


def lot_for(style: settings.Style, ticker: str, price: float, distance: float, account_value: float, scale: float = 1.0) -> float | None:
    """Lots that lose about ``style.risk_fraction`` (times ``scale``) of the account at the stop, rounded down to the lot step
    but never below the smallest trade. None means the fixed lot (no risk sizing, or a pair that keeps the fixed lot)."""
    if style.risk_fraction is None or assets.canonical(ticker) in {assets.canonical(t) for t in style.fixed_lot_tickers}:
        return None
    per_lot = distance * qty(ticker, price, 1.0)
    steps = math.floor(style.risk_fraction * scale * account_value / per_lot / settings.LOT_STEP + 1e-9) if per_lot > 0 else 1
    return round(min(max(steps, 1) * settings.LOT_STEP, settings.MAX_LOT), 8)


def outcomes(pos: Position) -> tuple[float, float]:
    """What the position finally makes, after both fees: (if it ends at its take-profit, if it ends at its stop)."""
    def net(price: float) -> float:
        return pos.side * qty(pos.ticker, price, pos.lot) * (price - pos.entry) - _fee(pos.ticker, price, pos.lot) - pos.cost
    return net(pos.target), net(pos.stop)


def equity(book: Book, prices: dict[str, float | None]) -> float:
    """Start cash plus finished results plus the open positions valued at ``prices``."""
    total = book.start_cash + book.realized
    for ticker, pos in book.positions.items():
        price = prices.get(ticker) or pos.entry
        total += pos.side * qty(ticker, price, pos.lot) * (price - pos.entry)
    return total


def close_position(book: Book, ticker: str, price: float, when: str, reason: str) -> None:
    """Close an open position by hand (for example when a pair leaves the live list)."""
    _close(book, book.positions[ticker], price, when, reason)


def _close(book: Book, pos: Position, price: float, when: str, reason: str) -> None:
    gross = pos.side * qty(pos.ticker, price, pos.lot) * (price - pos.entry)
    fee = _fee(pos.ticker, price, pos.lot)
    book.realized += gross - fee
    book.closed.append(Closed(pos.ticker, pos.side, pos.entry, price, pos.opened_at, when, reason,
                              round(gross - fee - pos.cost, 4), pos.decision_date, pos.rating, pos.lot, pos.stop, pos.target))
    del book.positions[pos.ticker]


def apply_decision(book: Book, ticker: str, date: str, rating: str, price: float, daily_bars: list,
                   when: str, prices: dict[str, float | None], average_range: float | None = None,
                   style: settings.Style = settings.DAILY, slot: str = "", tweaks: Tweaks | None = None) -> None:
    """Act on one new decision at the live ``price``. Every decision is acted on once, whatever came of it.

    ``average_range`` is the 14-bar range the stop is measured in (the daily one unless the style says otherwise).
    ``tweaks`` carries what an account chose to take from the agent's full answer (none: the usual rules)."""
    key = f"{ticker}|{date}|{slot}" if slot else f"{ticker}|{date}"      # a round of calls adds its slot: one pair can have several a day
    if key in book.applied:
        return
    book.applied.append(key)
    side = side_of(rating)
    if side == 0:
        return
    held = book.positions.get(ticker)
    if held and held.side == side:
        return

    def skip(why: str) -> None:
        book.skipped.append({"ticker": ticker, "date": date, "rating": rating, "why": why})

    tweaks = tweaks or Tweaks()
    if tweaks.hold:                                      # the agent put a condition on this call: nothing changes now
        return skip(f"the agent said to wait: {tweaks.hold}")
    if held:
        _close(book, held, price, when, "New call")
    average_range = average_range or sizing.atr(daily_bars)
    if average_range is None:
        return skip("not enough price history to place a stop")
    distance, notes = average_range * (style.stop_mult or rules.ATR_STOP_MULT), []
    planned = side * (price - tweaks.stop) if tweaks.stop is not None else 0.0      # how far below (long) or above (short) the price the agent put it
    if settings.PLAN_STOP_MIN * distance <= planned <= settings.PLAN_STOP_MAX * distance:
        distance = planned
        notes.append("agent stop")
    now_equity = equity(book, prices)
    lot = lot_for(style, ticker, price, distance, now_equity, tweaks.scale)
    if tweaks.scale != 1.0 and lot is not None:          # a fixed-lot pair (gold) cannot get smaller
        notes.append("mild size")
    risk = distance * qty(ticker, price, lot)
    open_risk = sum(p.risk for p in book.positions.values())
    if now_equity <= 0 or open_risk + risk > rules.FIXED_LOT_MAX_TOTAL_RISK * now_equity:
        return skip(f"open-risk cap: this trade risks ${risk:,.2f} with ${open_risk:,.2f} already at risk")
    fee = _fee(ticker, price, lot)
    book.realized -= fee
    deadline = (datetime.fromisoformat(when) + timedelta(hours=style.max_hours)).isoformat(timespec="seconds") if style.max_hours else ""
    book.positions[ticker] = Position(ticker, side, price, price - side * distance,
                                      price + side * distance * (style.reward_risk or rules.REWARD_RISK), when, date, rating,
                                      risk, fee, lot, deadline, ", ".join(notes))


def _utc(stamp: str) -> pd.Timestamp:
    """An ISO time as a UTC time without a time zone, the way the minute bars are indexed."""
    moment = pd.Timestamp(stamp)
    return moment.tz_convert("UTC").tz_localize(None) if moment.tzinfo else moment


def step(book: Book, ticker: str, bars: pd.DataFrame) -> None:
    """Close the position if a bar after its entry touched the stop or the target (the stop wins a tie), or if the
    first bar at or after its time limit has opened (it closes there, at that open)."""
    pos = book.positions.get(ticker)
    if pos is None or bars is None or bars.empty:
        return
    opened = _utc(pos.opened_at)
    limit = _utc(pos.deadline) if pos.deadline else None
    for stamp, bar in bars[bars.index > opened].iterrows():
        high, low, first = float(bar["High"]), float(bar["Low"]), float(bar["Open"])
        if limit is not None and stamp >= limit:
            _close(book, pos, first, pd.Timestamp(stamp).strftime("%Y-%m-%dT%H:%M:%S+00:00"), "Time limit")
            return
        if pos.side > 0:
            hit_stop, hit_target = low <= pos.stop, high >= pos.target
            stop_price, target_price = min(pos.stop, first), max(pos.target, first)
        else:
            hit_stop, hit_target = high >= pos.stop, low <= pos.target
            stop_price, target_price = max(pos.stop, first), min(pos.target, first)
        if hit_stop or hit_target:
            when = pd.Timestamp(stamp).strftime("%Y-%m-%dT%H:%M:%S+00:00")
            _close(book, pos, stop_price if hit_stop else target_price, when, "Stop-loss" if hit_stop else "Take-profit")
            return


def record(book: Book, prices: dict[str, float | None], when: str) -> float:
    """Append the account value to the history and return it."""
    value = round(equity(book, prices), 4)
    book.history.append({"t": when, "equity": value})
    del book.history[:-settings.HISTORY_KEEP]
    return value


def save(book: Book, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(book)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def load(path: Path) -> Book:
    if not path.exists():
        return Book()
    data = json.loads(path.read_text(encoding="utf-8"))
    book = Book(**{k: v for k, v in data.items() if k not in ("positions", "closed")})
    book.positions = {t: Position(**p) for t, p in data["positions"].items()}
    book.closed = [Closed(**c) for c in data["closed"]]
    return book
