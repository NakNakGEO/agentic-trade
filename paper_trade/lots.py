"""A paper account that trades a fixed lot the way the MT5 demo bridge does: the same lot, stop, take-profit and
open-risk cap. All pairs share one pool of money, so the result is leveraged (0.01 lot of EURUSD is about $1,100).

Conventions: a decision dated D fills at the first close after D (as in simulator.py); the stop is 2 x the 14-day
average range and the target twice that distance away, both checked against each later day's high and low (a stop
and a target touched on the same day count as the stop); a gap through a level fills at that day's open.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from paper_trade import assets, config
from paper_trade.bridge import settings, sizing
from paper_trade.bridge.models import Bar
from paper_trade.portfolio import PortfolioResult, assemble, first_fill
from paper_trade.simulator import Decision, SleeveResult, Trade, fill_date


def units_of(ticker: str, lot: float | None = None) -> float:
    """Units of the instrument in ``lot`` lots (the fixed lot when none is given)."""
    kind = assets.asset_class(ticker)
    if kind not in config.LOT_CONTRACT_UNITS:
        raise ValueError(f"no contract size for {kind} assets ({ticker}): add it to config.LOT_CONTRACT_UNITS")
    return (settings.FIXED_LOT if lot is None else lot) * config.LOT_CONTRACT_UNITS[kind]


def dollars_per_quote(ticker: str, price: float) -> float:
    """What one unit of the quote currency is worth in dollars: 1 for USD-quoted pairs, 1/price for USDJPY and kin."""
    symbol = assets.canonical(ticker)
    if symbol.endswith("=X") and symbol[:3] == "USD":
        return 1.0 / price
    if symbol.endswith("=X") and symbol[3:6] != "USD":
        raise ValueError(f"{ticker} has no US dollar leg, so its profit cannot be converted to dollars here")
    return 1.0


def side_of(rating: str) -> int:
    """+1 long, -1 short, 0 leave things alone."""
    return 1 if rating in settings.LONG_RATINGS else -1 if rating in settings.SHORT_RATINGS else 0


@dataclass
class _Open:
    side: int
    entry: float
    stop: float
    target: float
    since: str
    risk: float
    cost: float
    decision_date: str


@dataclass
class _Sleeve:
    ticker: str
    closes: pd.Series
    bars: pd.DataFrame                  # Open, High, Low, Close on the same days as closes
    decisions: list[Decision]
    cash: float
    units: float = 0.0
    cost_rate: float = 0.0
    pos: _Open | None = None
    realized: float = 0.0
    trades: list[Trade] = field(default_factory=list)
    equity: dict = field(default_factory=dict)
    notional: dict = field(default_factory=dict)
    last_equity: float = 0.0
    queue: list = field(default_factory=list)       # (fill day, decision)
    pending: list = field(default_factory=list)
    series: list[Bar] = field(default_factory=list)
    skipped: list = field(default_factory=list)     # (decision date, why no trade was opened)

    def __post_init__(self):
        kind = assets.asset_class(self.ticker)
        self.units = units_of(self.ticker)
        self.cost_rate = config.LOT_COST_BPS.get(kind, config.COST_BPS) / 1e4
        self.last_equity = self.cash
        self.series = [Bar(float(h), float(low), float(c)) for h, low, c in
                       zip(self.bars["High"], self.bars["Low"], self.bars["Close"])]
        for decision in sorted(self.decisions, key=lambda d: d.date):
            when = fill_date(self.closes, decision.date)
            (self.pending.append(decision) if when is None else self.queue.append((when, decision)))

    def qty(self, price: float) -> float:
        """Shares-equivalent of the lot: units, converted so qty x price is its value in dollars."""
        return self.units * dollars_per_quote(self.ticker, price)

    def step(self, day: pd.Timestamp, book: Callable[[], tuple[float, float]]) -> None:
        price = float(self.closes.loc[day])
        if self.pos and self.pos.since < day.strftime("%Y-%m-%d"):
            self._exits(day)
        for when, decision in [q for q in self.queue if q[0] == day]:
            self.queue.remove((when, decision))
            self._decide(decision, day, price, book)
        pos = self.pos
        unrealized = pos.side * self.qty(price) * (price - pos.entry) if pos else 0.0
        self.last_equity = self.cash + self.realized + unrealized
        self.equity[day] = self.last_equity
        self.notional[day] = pos.side * self.qty(price) * price if pos else 0.0

    def _exits(self, day: pd.Timestamp) -> None:
        bar, pos = self.bars.loc[day], self.pos
        high, low, opened = float(bar["High"]), float(bar["Low"]), float(bar["Open"])
        if pos.side > 0:
            if low <= pos.stop:
                self._close(day, min(pos.stop, opened), "Stop-loss")
            elif high >= pos.target:
                self._close(day, max(pos.target, opened), "Take-profit")
        else:
            if high >= pos.stop:
                self._close(day, max(pos.stop, opened), "Stop-loss")
            elif low <= pos.target:
                self._close(day, min(pos.target, opened), "Take-profit")

    def _decide(self, decision: Decision, day: pd.Timestamp, price: float,
                book: Callable[[], tuple[float, float]]) -> None:
        side = side_of(decision.rating)
        if side == 0 or (self.pos and self.pos.side == side):
            return
        if self.pos:
            self._close(day, price, decision.rating)
        equity, open_risk = book()
        index = self.closes.index.get_loc(day)
        average_range = sizing.atr(self.series[max(0, index - settings.ATR_PERIOD):index + 1])
        if equity <= 0 or average_range is None:
            self.skipped.append((decision.date, "account is empty" if equity <= 0
                                 else "not enough price history to place a stop"))
            return
        distance = average_range * settings.ATR_STOP_MULT
        risk = distance * self.qty(price)
        if open_risk + risk > settings.FIXED_LOT_MAX_TOTAL_RISK * equity:
            self.skipped.append((decision.date, f"open-risk cap: this trade risks ${risk:,.2f} with ${open_risk:,.2f} already at risk"))
            return
        cost = self.qty(price) * price * self.cost_rate
        self.realized -= cost
        self.pos = _Open(side, price, price - side * distance, price + side * distance * settings.REWARD_RISK,
                         day.strftime("%Y-%m-%d"), risk, cost, decision.date)
        self.trades.append(Trade(self.ticker, decision.date, day.strftime("%Y-%m-%d"), decision.rating,
                                 side * self.qty(price), price, cost, opens="long" if side > 0 else "short"))

    def _close(self, day: pd.Timestamp, price: float, label: str) -> None:
        pos = self.pos
        qty = self.qty(price)
        cost = qty * price * self.cost_rate
        gross = pos.side * qty * (price - pos.entry)
        self.realized += gross - cost
        self.trades.append(Trade(self.ticker, pos.decision_date, day.strftime("%Y-%m-%d"), label,
                                 -pos.side * qty, price, cost, gross - cost - pos.cost, pos.since, pos.entry,
                                 "long" if pos.side > 0 else "short", None))
        self.pos = None

    def result(self, pooled: pd.Series) -> SleeveResult:
        equity = pd.Series(self.equity, dtype=float)
        notional = pd.Series(self.notional, dtype=float)
        last = float(self.closes.iloc[-1])
        pos = self.pos
        shares = pos.side * self.qty(last) if pos else 0.0
        return SleeveResult(
            self.ticker, equity, notional / pooled.reindex(notional.index), self.trades, self.pending,
            shares=shares, cash=float(equity.iloc[-1]) - shares * last, basis=shares * pos.entry if pos else 0.0,
            open_date=pos.since if pos else None, last_price=last,
            levels={"side": "long" if pos.side > 0 else "short", "entry": pos.entry, "stop": pos.stop,
                    "target": pos.target, "since": pos.since, "risk": pos.risk} if pos else None,
            notes=[f"{day}: {why}" for day, why in self.skipped])


def _aligned(bars: pd.DataFrame, closes: pd.Series) -> pd.DataFrame:
    """Bars on exactly the days of ``closes``; a day with no bar gets its close as open, high and low."""
    frame = bars.reindex(closes.index)
    for column in ("Open", "High", "Low"):
        frame[column] = frame[column].fillna(closes)
    frame["Close"] = closes
    return frame


def in_order(tickers, order: list[str] | None) -> list[str]:
    """``tickers`` in the order of ``order`` (matched by canonical symbol), anything not listed after, alphabetically."""
    ranks = {assets.canonical(t): i for i, t in enumerate(order or [])}
    return sorted(tickers, key=lambda t: (ranks.get(assets.canonical(t), len(ranks)), t))


def run_lot_portfolio(decisions: list[Decision], closes: dict[str, pd.Series], bars: dict[str, pd.DataFrame],
                      benchmark_closes: pd.Series, starting_cash: float = config.STARTING_CASH,
                      order: list[str] | None = None) -> PortfolioResult:
    """Every ticker trades the fixed lot against one shared pool of ``starting_cash``.

    The open-risk cap is first come, first served, so pairs are tried in ``order`` (the run's own list of tickers),
    the way the bridge tries them, instead of alphabetically."""
    if not settings.FIXED_LOT:
        raise ValueError("the bridge sizes by risk (FIXED_LOT is None), so there is no fixed lot to simulate")
    tickers = in_order(closes, order)
    start = first_fill(decisions, closes)
    sleeves = {t: _Sleeve(t, closes[t], _aligned(bars[t], closes[t]), [d for d in decisions if d.ticker == t],
                          starting_cash / len(tickers)) for t in tickers}

    def book() -> tuple[float, float]:
        return (sum(s.last_equity for s in sleeves.values()),
                sum(s.pos.risk for s in sleeves.values() if s.pos))

    for day in sorted(set().union(*(s.closes.index for s in sleeves.values()))):
        for sleeve in sleeves.values():
            if day in sleeve.closes.index:
                sleeve.step(day, book)

    equity = pd.concat({t: pd.Series(s.equity, dtype=float) for t, s in sleeves.items()}, axis=1, sort=True).ffill()
    pooled = equity.sum(axis=1)
    notional = pd.concat({t: pd.Series(s.notional, dtype=float) for t, s in sleeves.items()},
                         axis=1, sort=True).ffill().sum(axis=1)
    return assemble({t: s.result(pooled) for t, s in sleeves.items()}, closes, benchmark_closes, starting_cash,
                    start, exposure=notional / pooled)
