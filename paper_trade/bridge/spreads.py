"""Measure what each pair costs to enter on this account: the live spread against the pair's daily range."""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from paper_trade.bridge import guards, settings, sizing, symbols
from paper_trade.bridge.broker import Broker
from paper_trade.bridge.models import SymbolSpec


@dataclass
class SpreadRow:
    ticker: str
    symbol: str | None
    spec: SymbolSpec | None = None
    average_range: float | None = None
    samples: list[float] = field(default_factory=list)      # spread in price units, one per look

    @property
    def median(self) -> float:
        return statistics.median(self.samples)

    @property
    def verdict(self) -> str:
        if self.symbol is None or self.spec is None:
            return "not on this account"
        if not self.samples:
            return "no price"
        if self.average_range is None:
            return "no daily history"
        distance = sizing.stop_distance(self.spec, self.average_range)
        return "OK" if guards.wide_spread(symbols.base_name(self.ticker), self.spec, self.median, distance) is None \
            else "WIDE"


def measure(broker: Broker, tickers: list[str], looks: int = 1, interval: float = 15.0,
            sleep: Callable[[float], None] = time.sleep) -> list[SpreadRow]:
    """Look at every pair's spread ``looks`` times, ``interval`` seconds apart."""
    available = broker.symbol_names()
    rows = []
    for ticker in tickers:
        name = symbols.resolve(ticker, available)
        row = SpreadRow(ticker, name)
        if name is not None:
            row.spec = broker.spec(name)
            row.average_range = sizing.atr(broker.daily_bars(name, settings.ATR_PERIOD + 1))
        rows.append(row)
    for look in range(looks):
        if look:
            sleep(interval)
        for row in rows:
            if row.spec is not None:
                quote = broker.quote(row.symbol)
                row.samples.append(quote.ask - quote.bid)
    return rows


def render(rows: list[SpreadRow], looks: int) -> str:
    head = (f"{'pair':<9} {'symbol':<10} {'spread now':>10} {'median':>8} {'worst':>8} {'of daily range':>15}  verdict "
            f"(points; {looks} look{'s' if looks != 1 else ''})")
    lines = [head]
    for row in rows:
        if not row.samples or row.spec is None:
            lines.append(f"{row.ticker:<9} {row.symbol or '-':<10} {'':>10} {'':>8} {'':>8} {'':>15}  {row.verdict}")
            continue
        point = row.spec.point
        share = f"{row.median / row.average_range:.1%}" if row.average_range else "-"
        lines.append(f"{row.ticker:<9} {row.symbol:<10} {row.samples[-1] / point:>10.0f} {row.median / point:>8.0f} "
                     f"{max(row.samples) / point:>8.0f} {share:>15}  {row.verdict}")
    fixed = ", ".join(f"{name} {limit} points" for name, limit in settings.MAX_SPREAD_POINTS.items())
    lines += ["", f"OK means the median spread is within {settings.MAX_SPREAD_FRACTION_OF_STOP:.0%} of the stop "
                  f"distance ({settings.ATR_STOP_MULT:g} x the 14-day range); fixed limits: {fixed}.",
              "Spreads widen at the 21:00-23:00 UTC rollover, around news and on weekends, so one look is a "
              "snapshot: use --minutes to sample over time, and repeat at different hours."]
    return "\n".join(lines)
