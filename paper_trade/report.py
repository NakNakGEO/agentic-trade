"""Load a run's decisions, paper-trade them, and render a plain-text/markdown report."""

from __future__ import annotations

import pandas as pd

from paper_trade import assets, config
from paper_trade.decide import memory_log, read_meta, run_dir
from paper_trade.portfolio import PortfolioResult, run_portfolio
from paper_trade.prices import load_bars, load_closes
from paper_trade.simulator import Decision, max_drawdown, total_return
from paper_trade.stats import daily_stats


def load_decisions(run_id: str) -> tuple[list[Decision], list[dict]]:
    """Tradeable decisions plus the raw log entries (for the framework's own scores)."""
    from tradingagents.agents.rating import RATING_REVIEW
    from tradingagents.memory import TradingMemoryLog

    path = memory_log(run_id)
    if not path.is_file():
        raise FileNotFoundError(f"no decisions logged for run '{run_id}' ({path})")
    entries = TradingMemoryLog({"memory_log_path": str(path)}).load_entries()
    usable = [Decision(e["ticker"], e["date"], e["rating"]) for e in entries
              if e["rating"] != RATING_REVIEW]
    return usable, entries


def _pct(value: float) -> str:
    return f"{value:+.2%}"


def _row(name: str, equity: pd.Series, cash: float) -> str:
    stats = daily_stats(equity, cash)
    return (f"| {name} | ${equity.iloc[-1]:,.2f} | {_pct(total_return(equity, cash))} "
            f"| {stats.per_calendar_day:+.3f} | {_pct(max_drawdown(equity))} |")


def _dollars(result: PortfolioResult) -> list[str]:
    stats = daily_stats(result.strategy, result.starting_cash)
    return [
        f"Put in ${stats.start_value:,.2f}, ended with ${stats.end_value:,.2f} "
        f"({'profit' if stats.profit >= 0 else 'loss'} of ${abs(stats.profit):,.2f}) "
        f"over {stats.calendar_days} calendar days.",
        f"Average {stats.per_calendar_day:+.3f} dollars per calendar day. "
        f"Best day {stats.best_day:+.2f}, worst day {stats.worst_day:+.2f}; "
        f"{stats.up_days} up days, {stats.down_days} down days.",
    ]


def _summary(result: PortfolioResult) -> list[str]:
    cash = result.starting_cash
    lines = [
        f"Window: {result.start:%Y-%m-%d} to {result.end:%Y-%m-%d}, start capital ${cash:,.2f}",
        "",
        *_dollars(result),
        "",
        "| Portfolio | End value | Return | $ per day | Max drawdown |",
        "|---|---|---|---|---|",
        _row("TradingAgents paper portfolio", result.strategy, cash),
        _row(f"{config.BENCHMARK} buy and hold", result.benchmark, cash),
        _row("Same assets, equal weight, buy and hold", result.equal_weight, cash),
        "",
        f"Average exposure to the market: {result.exposure.mean():.0%}. "
        f"Trades: {len(result.trades)}. Costs paid: ${sum(t.cost for t in result.trades):,.4f}.",
    ]
    excess = total_return(result.strategy, cash) - total_return(result.benchmark, cash)
    lines.append(f"Excess return versus {config.BENCHMARK}: {_pct(excess)}.")
    return lines


def _per_ticker(result: PortfolioResult) -> list[str]:
    slice_cash = result.starting_cash / len(result.sleeves)
    lines = ["| Ticker | Class | Strategy | Buy and hold | Strategy $ | Trades | Final exposure |",
             "|---|---|---|---|---|---|---|"]
    by_class: dict[str, list[str]] = {}
    for ticker, sleeve in sorted(result.sleeves.items()):
        window = sleeve.equity[sleeve.equity.index >= result.start]
        kind = assets.asset_class(ticker)
        by_class.setdefault(kind, []).append(ticker)
        lines.append(
            f"| {ticker} | {kind} | {_pct(total_return(window, slice_cash))} "
            f"| {_pct(total_return(result.buy_hold[ticker], slice_cash))} "
            f"| {window.iloc[-1] - slice_cash:+.2f} "
            f"| {len(sleeve.trades)} | {sleeve.exposure.iloc[-1]:.0%} |")

    lines += ["", "| Asset class | Strategy | Buy and hold | Strategy $ |", "|---|---|---|---|"]
    for kind, members in sorted(by_class.items()):
        cash = slice_cash * len(members)
        strategy = sum(result.sleeves[t].equity[result.sleeves[t].equity.index >= result.start]
                       for t in members)
        held = sum(result.buy_hold[t] for t in members)
        lines.append(f"| {kind} ({len(members)}) | {_pct(total_return(strategy, cash))} "
                     f"| {_pct(total_return(held, cash))} | {strategy.iloc[-1] - cash:+.2f} |")
    return lines


def _decisions(result: PortfolioResult, entries: list[dict]) -> list[str]:
    scores = {(e["ticker"], e["date"]): e for e in entries}
    lines = ["| Date | Ticker | Rating | Filled | Price | 5d return | 5d alpha vs SPY |",
             "|---|---|---|---|---|---|---|"]
    filled = {(t.ticker, t.decision_date): t for t in result.trades}
    for (ticker, date), entry in sorted(scores.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        trade = filled.get((ticker, date))
        lines.append(
            f"| {date} | {ticker} | {entry['rating']} "
            f"| {trade.fill_date if trade else 'no trade'} "
            f"| {f'{trade.price:,.2f}' if trade else '-'} "
            f"| {entry.get('raw') or 'pending'} | {entry.get('alpha') or 'pending'} |")
    return lines


def full_universe(decided: set[str], planned: list[str]) -> list[str]:
    """Decided tickers plus planned ones with no decision yet, which wait in cash.

    A partial run must not split the cash across only the assets decided so far.
    """
    known = {assets.canonical(t) for t in decided}
    return sorted(decided | {t for t in planned if assets.canonical(t) not in known})


def history_start(first_decision: str, mode: str) -> str:
    """First day of price history to load: the fixed-lot account needs 14 earlier bars to place its stops."""
    days = config.LOT_HISTORY_DAYS if mode in config.LOT_MODES else config.HISTORY_DAYS
    return (pd.Timestamp(first_decision) - pd.Timedelta(days=days)).strftime("%Y-%m-%d")


def simulate_run(run_id: str, cash: float = config.STARTING_CASH,
                 mode: str = config.DEFAULT_MODE) -> tuple[PortfolioResult, list[dict]]:
    """Paper-trade every decision logged so far for a run. Also used by the dashboard.

    ``mode`` is ``long_only`` or ``long_short``: the same decisions, traded under different account rules."""
    decisions, entries = load_decisions(run_id)
    if not decisions:
        raise ValueError("the run has no readable decisions to trade")
    first = min(d.date for d in decisions)
    start = history_start(first, mode)
    planned = read_meta(run_id).get("tickers", [])
    tickers = full_universe({d.ticker for d in decisions}, planned)
    closes = {t: load_closes(t, start) for t in tickers}
    benchmark = load_closes(config.BENCHMARK, start)
    if mode in config.LOT_MODES:
        from paper_trade.lots import run_lot_portfolio

        bars = {t: load_bars(t, start) for t in tickers}
        return run_lot_portfolio(decisions, closes, bars, benchmark, cash, order=planned), entries
    return run_portfolio(decisions, closes, benchmark, cash, bounds=config.ACCOUNT_MODES[mode]), entries


def run_simulation(run_id: str, cash: float = config.STARTING_CASH, mode: str = config.DEFAULT_MODE) -> str:
    from tradingagents.backtest import summarize

    result, entries = simulate_run(run_id, cash, mode)

    sections = [
        f"# Paper-trade report: {run_id} ({config.MODE_LABELS[mode]})", "",
        "## Portfolio", *_summary(result), "",
        "## By ticker", *_per_ticker(result), "",
        "## Decisions", *_decisions(result, entries), "",
        "## TradingAgents' own decision score (settled outcomes)",
        summarize(memory_log(run_id)).render(), "",
        f"Logs and raw decisions: {run_dir(run_id)}",
    ]
    return "\n".join(sections)
