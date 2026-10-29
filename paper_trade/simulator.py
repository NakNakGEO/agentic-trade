"""Turn a list of ratings into a paper portfolio. Pure logic: prices in, numbers out.

Convention (same as TradingAgents' own settlement): a decision dated D is filled at the
first close strictly after D, because a run on D reads news published after D's close.

Positions are signed: positive shares are a long, negative shares are a short (sold first, bought back
later, so it profits when the price falls). Whether shorts are allowed is decided by the rating bounds
passed in (see ``config.ACCOUNT_MODES``): long-only bounds never go below zero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from paper_trade import config


@dataclass(frozen=True)
class Decision:
    ticker: str
    date: str
    rating: str


@dataclass(frozen=True)
class Trade:
    ticker: str
    decision_date: str
    fill_date: str
    rating: str
    shares: float          # signed: positive buys, negative sells
    price: float
    cost: float
    # A fill that closes part of a position carries its realised result (fees included) against the
    # average entry price of the shares closed.
    pnl: float | None = None
    entry_date: str | None = None     # when the position being reduced was opened
    entry_price: float | None = None  # average entry price per share of the shares closed
    closes: str | None = None         # "long" or "short": which position this fill closed
    opens: str | None = None          # "long" or "short": which position this fill opened or added to


@dataclass
class SleeveResult:
    ticker: str
    equity: pd.Series
    exposure: pd.Series    # signed share of equity held at each close: negative while short
    trades: list[Trade] = field(default_factory=list)
    pending: list[Decision] = field(default_factory=list)   # no close after the date yet
    # Where the sleeve ended: what it holds, what it cost, and the last price it was valued at.
    shares: float = 0.0                # negative while short
    cash: float = 0.0
    basis: float = 0.0                 # signed like shares: cost of a long, minus the proceeds of a short, fees included
    open_date: str | None = None
    last_price: float = 0.0
    levels: dict | None = None         # the open position's entry, stop and target (fixed-lot account only)
    notes: list[str] = field(default_factory=list)      # why a call did not turn into a trade, when known


@dataclass
class _Position:
    shares: float = 0.0
    basis: float = 0.0
    opened: str | None = None


def fill_date(closes: pd.Series, decision_date: str) -> pd.Timestamp | None:
    """First trading day strictly after ``decision_date``, or None if it has not traded."""
    later = closes.index[closes.index > pd.Timestamp(decision_date)]
    return later[0] if len(later) else None


def _fill(pos: _Position, ticker: str, decision: Decision, fill: str, qty: float, price: float, cost: float) -> list[Trade]:
    """Apply a trade of ``qty`` shares (positive buys, negative sells) to the position and return its fills.

    Trading against the position first closes it, which makes a fill with a result; any quantity left
    over opens the other side (a flip from long to short, or back, is two fills on the same day).
    """
    rows = []
    against = pos.shares != 0 and qty * pos.shares < 0
    closing = -math.copysign(min(abs(qty), abs(pos.shares)), pos.shares) if against else 0.0
    opening = qty - closing
    cost_close = cost * abs(closing) / abs(qty)
    if closing:
        removed = -closing                          # position shares that leave, same sign as the position
        basis_closed = pos.basis * (removed / pos.shares)
        pnl = removed * price - basis_closed - cost_close      # works for a long and for a short
        rows.append(Trade(ticker, decision.date, fill, decision.rating, closing, price, cost_close, pnl,
                          pos.opened, basis_closed / removed, "long" if pos.shares > 0 else "short", None))
        pos.shares -= removed
        pos.basis -= basis_closed
        if abs(pos.shares) < 1e-9:                  # fully closed
            pos.shares, pos.basis, pos.opened = 0.0, 0.0, None
    if abs(opening) > 1e-12:
        if pos.shares == 0:
            pos.opened = fill
        pos.basis += math.copysign(abs(opening) * price, opening) + (cost - cost_close)   # fees make entry dearer
        pos.shares += opening
        rows.append(Trade(ticker, decision.date, fill, decision.rating, opening, price, cost - cost_close,
                          None, None, None, None, "long" if opening > 0 else "short"))
    return rows


def simulate_sleeve(
    ticker: str,
    decisions: list[Decision],
    closes: pd.Series,
    cash: float,
    cost_bps: float = config.COST_BPS,
    bounds: dict[str, tuple[float, float]] | None = None,
) -> SleeveResult:
    """Run one ticker's decisions against its closes, from the first fill onward."""
    bounds = bounds or config.RATING_BOUNDS
    unknown = {d.rating for d in decisions} - bounds.keys()
    if unknown:
        raise ValueError(f"no exposure defined for rating(s) {sorted(unknown)}")
    cost_rate = cost_bps / 1e4

    queue, pending = [], []
    for decision in sorted(decisions, key=lambda d: d.date):
        when = fill_date(closes, decision.date)
        if when is None:
            pending.append(decision)
        else:
            queue.append((decision, when))
    queue.sort(key=lambda pair: (pair[1], pair[0].date))

    pos, trades = _Position(), []
    equity, exposure = {}, {}
    for day, price in closes.items():
        while queue and queue[0][1] == day:
            decision, _ = queue.pop(0)
            total = cash + pos.shares * price
            if total <= 0:                                  # wiped out: nothing left to trade with
                continue
            floor, cap = bounds[decision.rating]
            current = pos.shares * price / total
            target = min(max(current, floor), cap)         # clamp: ratings never push the wrong way
            delta = target * total - pos.shares * price    # value to trade: positive buys, negative sells
            if abs(delta) < config.MIN_TRADE_FRACTION * total:
                continue
            if delta > 0:
                delta = min(delta, cash / (1 + cost_rate))     # never spend past the cash
                if delta <= 0:
                    continue
            cost = abs(delta) * cost_rate
            cash -= delta + cost
            trades += _fill(pos, ticker, decision, day.strftime("%Y-%m-%d"), delta / price, float(price), cost)
        value = cash + pos.shares * price
        equity[day], exposure[day] = value, (pos.shares * price / value if value else 0.0)

    return SleeveResult(ticker, pd.Series(equity, dtype=float), pd.Series(exposure, dtype=float),
                        trades, pending, shares=pos.shares, cash=cash, basis=pos.basis, open_date=pos.opened,
                        last_price=float(closes.iloc[-1]) if len(closes) else 0.0)


def buy_and_hold(closes: pd.Series, start: pd.Timestamp, cash: float,
                 cost_bps: float = config.COST_BPS) -> pd.Series:
    """Equity of buying at ``start``'s close (one entry cost) and holding to the end."""
    window = closes[closes.index >= start]
    shares = cash / (1 + cost_bps / 1e4) / window.iloc[0]
    return window * shares


def max_drawdown(equity: pd.Series) -> float:
    """Largest peak-to-trough fall as a negative fraction (0.0 for a series that never falls)."""
    return float((equity / equity.cummax() - 1).min()) if len(equity) else 0.0


def total_return(equity: pd.Series, start_value: float) -> float:
    return float(equity.iloc[-1] / start_value - 1) if len(equity) else 0.0
