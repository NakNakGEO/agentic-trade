"""Combine per-ticker sleeves into one portfolio and line it up against buy-and-hold."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from paper_trade import config
from paper_trade.simulator import (
    Decision,
    SleeveResult,
    buy_and_hold,
    fill_date,
    simulate_sleeve,
)


@dataclass
class PortfolioResult:
    start: pd.Timestamp
    end: pd.Timestamp
    starting_cash: float
    strategy: pd.Series
    benchmark: pd.Series            # benchmark ticker, buy and hold
    equal_weight: pd.Series         # the same tickers, bought equally on day one and held
    exposure: pd.Series             # share of the portfolio held in stocks
    sleeves: dict[str, SleeveResult]
    buy_hold: dict[str, pd.Series]  # per-ticker buy and hold, same cash as its sleeve

    @property
    def trades(self):
        return sorted((t for s in self.sleeves.values() for t in s.trades),
                      key=lambda t: (t.fill_date, t.ticker))


def run_portfolio(
    decisions: list[Decision],
    closes: dict[str, pd.Series],
    benchmark_closes: pd.Series,
    starting_cash: float = config.STARTING_CASH,
    bounds: dict[str, tuple[float, float]] | None = None,
) -> PortfolioResult:
    """Each ticker trades its own equal slice of cash; sleeves are summed day by day.

    ``bounds`` picks the account rules (long only, or long and short); see ``config.ACCOUNT_MODES``."""
    tickers = sorted(closes)
    slice_cash = starting_cash / len(tickers)
    by_ticker = {t: [d for d in decisions if d.ticker == t] for t in tickers}

    start = first_fill(decisions, closes)
    sleeves = {t: simulate_sleeve(t, by_ticker[t], closes[t], slice_cash, bounds=bounds) for t in tickers}
    return assemble(sleeves, closes, benchmark_closes, starting_cash, start)


def first_fill(decisions: list[Decision], closes: dict[str, pd.Series]) -> pd.Timestamp:
    """The day of the earliest paper fill: the first close after any decision."""
    fills = [fill_date(closes[d.ticker], d.date) for d in decisions]
    fills = [f for f in fills if f is not None]
    if not fills:
        raise ValueError("no decision has a later close to trade on yet")
    return min(fills)


def assemble(sleeves: dict[str, SleeveResult], closes: dict[str, pd.Series], benchmark_closes: pd.Series,
             starting_cash: float, start: pd.Timestamp, exposure: pd.Series | None = None) -> PortfolioResult:
    """Line the sleeves up with buy-and-hold. ``exposure`` overrides the default of sleeve holdings over total equity."""
    tickers = sorted(sleeves)
    slice_cash = starting_cash / len(tickers)
    equity = pd.concat({t: s.equity for t, s in sleeves.items()}, axis=1, sort=True).ffill()
    held = pd.concat({t: s.exposure * s.equity for t, s in sleeves.items()}, axis=1, sort=True).ffill()
    strategy = equity.sum(axis=1)
    if exposure is None:
        exposure = held.sum(axis=1) / strategy

    buy_hold = {t: buy_and_hold(closes[t], start, slice_cash) for t in tickers}
    # Crypto trades on weekends and stocks do not: carry each asset's last value over days it
    # did not trade (and its unspent cash before its first bar), or those days sum to zero.
    held_value = pd.concat(buy_hold, axis=1, sort=True).ffill().fillna(slice_cash)
    end = strategy.index[-1]
    return PortfolioResult(
        start=start,
        end=end,
        starting_cash=starting_cash,
        strategy=strategy[strategy.index >= start],
        benchmark=buy_and_hold(benchmark_closes, start, starting_cash),
        equal_weight=held_value.sum(axis=1),
        exposure=exposure[exposure.index >= start],
        sleeves=sleeves,
        buy_hold=buy_hold,
    )
