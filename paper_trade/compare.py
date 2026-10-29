"""Two runs head to head: same $, same assets, same decision dates, so only the model differs.

The same decisions are scored under both account rules (long only, and long and short), so you can see
how much of the result comes from being allowed to bet on a fall.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from paper_trade import assets, config
from paper_trade.decide import feed_path, read_meta
from paper_trade.portfolio import PortfolioResult, run_portfolio
from paper_trade.prices import load_closes
from paper_trade.report import load_decisions
from paper_trade.simulator import Decision, max_drawdown, total_return
from paper_trade.stats import daily_stats
from paper_trade.trade_record import record

BULLISH = {"Buy", "Overweight"}
BEARISH = {"Underweight", "Sell"}
RATINGS = ("Buy", "Overweight", "Hold", "Underweight", "Sell")
TOO_CLOSE = 0.01          # a gap under 1% of the starting cash is noise at this sample size


def direction(rating: str) -> int:
    return 1 if rating in BULLISH else -1 if rating in BEARISH else 0


def _canonical(decisions: list[Decision]) -> dict[tuple[str, str], Decision]:
    out = {}
    for d in decisions:
        symbol = assets.canonical(d.ticker)
        out[(symbol, d.date)] = Decision(symbol, d.date, d.rating)
    return out


def common_cells(a: list[Decision], b: list[Decision]) -> tuple[list[Decision], list[Decision]]:
    """The decisions both runs made (same asset, same date), in date order, under one naming."""
    ka, kb = _canonical(a), _canonical(b)
    keys = sorted(ka.keys() & kb.keys(), key=lambda k: (k[1], k[0]))
    return [ka[k] for k in keys], [kb[k] for k in keys]


def agreement(da: list[Decision], db: list[Decision]) -> dict:
    """How often the two models gave the same call (lists must be aligned, as common_cells returns them)."""
    return {"cells": len(da),
            "same_rating": sum(x.rating == y.rating for x, y in zip(da, db, strict=True)),
            "same_direction": sum(direction(x.rating) == direction(y.rating) for x, y in zip(da, db, strict=True))}


@dataclass
class Comparison:
    a: PortfolioResult
    b: PortfolioResult
    decisions_a: list[Decision]
    decisions_b: list[Decision]
    agree: dict


def build_comparison(da: list[Decision], db: list[Decision], closes: dict[str, pd.Series],
                     benchmark: pd.Series, cash: float,
                     bounds: dict[str, tuple[float, float]] | None = None) -> Comparison:
    """Paper-trade both sets of decisions against the same prices, under the same account rules."""
    return Comparison(run_portfolio(da, closes, benchmark, cash, bounds), run_portfolio(db, closes, benchmark, cash, bounds),
                      da, db, agreement(da, db))


# ---- text report -------------------------------------------------------------------------------

def _money(v: float) -> str:
    return f"{'+' if v >= 0 else '-'}${abs(v):,.2f}"


def _fills(result: PortfolioResult) -> str:
    rec = [record(s) for s in result.sleeves.values()]
    wins, losses = sum(r["wins"] for r in rec), sum(r["losses"] for r in rec)
    return f"{len(result.trades)} fills, {wins} won / {losses} lost"


def _row(name: str, equity: pd.Series, cash: float, trades: str = "-") -> str:
    stats = daily_stats(equity, cash)
    return (f"| {name} | ${equity.iloc[-1]:,.2f} | {_money(stats.profit)} | {total_return(equity, cash):+.2%} "
            f"| {stats.per_calendar_day:+.3f} | {max_drawdown(equity):+.2%} | {trades} |")


def _verdict(c: Comparison, la: str, lb: str) -> str:
    cash = c.a.starting_cash
    gap = float(c.a.strategy.iloc[-1] - c.b.strategy.iloc[-1])
    if abs(gap) < TOO_CLOSE * cash:
        return (f"**Too close to call.** {la} and {lb} ended within {_money(abs(gap))} of each other, "
                f"which is smaller than the noise you get from this few decisions.")
    leader, other = (la, lb) if gap > 0 else (lb, la)
    return (f"**{leader} ended ahead by {_money(abs(gap))}** on these {c.agree['cells']} shared decisions. "
            f"Treat that as a weak hint only: it could easily come from which dates and assets were sampled, "
            f"and {other} might lead on a different stretch of the market.")


def _per_asset(c: Comparison, labels: dict[str, str]) -> list[str]:
    slice_cash = c.a.starting_cash / len(c.a.sleeves)
    lines = ["| Asset | Class | A profit | B profit | Just holding it |", "|---|---|---|---|---|"]
    for symbol in sorted(c.a.sleeves):
        pa = c.a.sleeves[symbol].equity.iloc[-1] - slice_cash
        pb = c.b.sleeves[symbol].equity.iloc[-1] - slice_cash
        hold = c.a.buy_hold[symbol].iloc[-1] - slice_cash
        lines.append(f"| {labels.get(symbol, symbol)} | {assets.asset_class(symbol)} | {_money(pa)} | {_money(pb)} | {_money(hold)} |")
    return lines


def _ratings(c: Comparison, la: str, lb: str) -> list[str]:
    def count(ds):
        return {r: sum(d.rating == r for d in ds) for r in RATINGS}

    ca, cb = count(c.decisions_a), count(c.decisions_b)
    lines = [f"| Rating | {la} | {lb} |", "|---|---|---|"]
    lines += [f"| {r} | {ca[r]} | {cb[r]} |" for r in RATINGS]
    return lines


def _effort(run_id: str) -> str:
    """Calls, tokens and reply time of a run, from its event log (the cost of the model, not its skill)."""
    from paper_trade.dashboard.state import token_totals

    t = token_totals(feed_path(run_id))
    if not t.get("calls"):
        return "no call log"
    return (f"{t['calls']:,} model calls, {t['tokens_in'] + t['tokens_out']:,} tokens, "
            f"average reply {t['ms_avg']:,} ms (slowest {t['ms_max']:,} ms)")


def _section(c: Comparison, la: str, lb: str, labels: dict[str, str], title: str) -> list[str]:
    """Everything that depends on the account rules: results, who won, and the per-asset split."""
    cash = c.a.starting_cash
    return [
        f"## {title}", "",
        _verdict(c, la, lb), "",
        "| Portfolio | End value | Profit | Return | $ per day | Max drawdown | Trades |",
        "|---|---|---|---|---|---|---|",
        _row(la, c.a.strategy, cash, _fills(c.a)),
        _row(lb, c.b.strategy, cash, _fills(c.b)),
        _row(f"{config.BENCHMARK} buy and hold", c.a.benchmark, cash),
        _row("Same assets, equal weight, buy and hold", c.a.equal_weight, cash),
        "",
        *_per_asset(c, labels), "",
    ]


def render(by_mode: dict[str, Comparison], la: str, lb: str, labels: dict[str, str],
           runs: tuple[str, str], totals: tuple[int, int]) -> str:
    """One report with a section per account rule. ``by_mode`` maps a heading to its comparison."""
    first = next(iter(by_mode.values()))
    cash, ag = first.a.starting_cash, first.agree
    pct = lambda k: f"{ag[k] / ag['cells']:.0%} ({ag[k]} of {ag['cells']})"      # noqa: E731
    lines = [
        f"# {la} vs {lb}: ${cash:,.0f} paper account", "",
        f"Window {first.a.start:%Y-%m-%d} to {first.a.end:%Y-%m-%d}. Scored only on the **{ag['cells']} decisions both runs "
        f"made** (same asset, same date). {la} made {totals[0]} in total, {lb} made {totals[1]}. "
        f"The same decisions are traded under each account rule below.", "",
        "## Did the two models agree?",
        f"Same rating: {pct('same_rating')}. Same direction (bullish / neutral / bearish): {pct('same_direction')}.", "",
        *_ratings(first, la, lb), "",
    ]
    for title, c in by_mode.items():
        lines += _section(c, la, lb, labels, title)
    lines += [
        "## What each model cost to run",
        f"- {la} ({runs[0]}): {_effort(runs[0])}",
        f"- {lb} ({runs[1]}): {_effort(runs[1])}",
        "",
        "## Read this before believing any number above",
        "- A few dozen decisions over a short stretch cannot show which model trades better. "
        "The gap between them is smaller than the difference one lucky or unlucky week makes.",
        "- Fractional units, 5 bps cost per trade, no leverage. Short trades pay no borrow fee here, which flatters them a "
        "little compared with a real broker. Nothing here is real money or a recommendation.",
        "- Assets the models were not both asked about stay in cash, which is why a quiet model can beat "
        "'just holding it' when the market falls.",
    ]
    return "\n".join(lines)


def compare_runs(run_a: str, run_b: str, cash: float = config.STARTING_CASH,
                 label_a: str = "A", label_b: str = "B", modes: tuple[str, ...] = ("long_short", "long_only")) -> str:
    """Load two runs, keep the decisions they share, paper-trade each, and write the comparison."""
    da_all, _ = load_decisions(run_a)
    db_all, _ = load_decisions(run_b)
    da, db = common_cells(da_all, db_all)
    if not da:
        raise ValueError("the two runs have no decision in common yet (same asset and date)")

    planned = [*read_meta(run_a).get("tickers", []), *read_meta(run_b).get("tickers", [])]
    symbols = sorted({assets.canonical(t) for t in planned} | {d.ticker for d in da})
    labels = {assets.canonical(t): t for t in planned}
    start = (pd.Timestamp(min(d.date for d in da)) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    closes = {s: load_closes(s, start) for s in symbols}
    benchmark = load_closes(config.BENCHMARK, start)
    by_mode = {config.MODE_LABELS[m]: build_comparison(da, db, closes, benchmark, cash, config.ACCOUNT_MODES[m])
               for m in modes}
    return render(by_mode, label_a, label_b, labels, (run_a, run_b), (len(da_all), len(db_all)))
