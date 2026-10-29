"""The scorecard: are the models' calls right? See paper_trade/scorecard/grading.py for how a call is graded."""

from __future__ import annotations

import time

from paper_trade.scorecard import settings
from paper_trade.scorecard.calls import Call, load_calls
from paper_trade.scorecard.grading import Prices, grade

__all__ = ["Call", "Prices", "grade", "load_calls", "for_account", "render"]
_cache: dict = {}


def _recorded_prices(tickers) -> dict:
    from paper_trade.live import tradingview

    out = {}
    for ticker in tickers:
        try:
            out[ticker] = Prices(tradingview.candles(ticker)["Close"])
        except Exception:                           # no recorded minutes for this pair yet: its calls cannot be graded
            continue
    return out


def for_account(account) -> dict | None:
    """The scorecard for one live account's model on its own pairs, from the recorded minutes (cached for a minute)."""
    hit = _cache.get(account.name)
    if hit and time.time() - hit[0] < settings.CACHE_SECONDS:
        return hit[1]
    from paper_trade.live import schedule

    calls = sorted((c for run in schedule.all_runs(account) for c in load_calls(run, account.tickers)), key=lambda c: c.at)
    result = grade(calls, _recorded_prices({c.ticker for c in calls})) if calls else None
    if result:
        result.update(model=account.label, run=account.decisions_run)
    _cache[account.name] = (time.time(), result)
    return result


def render(result: dict | None, title: str = "") -> str:
    """A plain-text table of one scorecard (for the command line)."""
    if not result:
        return f"{title}: no calls with a recorded landing time yet."
    lines = [f"{title or result.get('model', '')}: {result['calls']} calls ({result['holds']} holds, {result['unreadable']} unreadable)",
             f"{'after':>6} {'graded':>7} {'right %':>8} {'avg bps':>8} | {'always sell':>11} {'always buy':>11} {'TradingView':>12}"]
    for name, row in result["horizons"].items():
        base = row["baselines"]
        pct = lambda d: "-" if d["right_pct"] is None else f"{d['right_pct']:.1f}%"
        lines.append(f"{name:>6} {row['n']:>7} {pct(row):>8} {row['avg_bps'] if row['avg_bps'] is not None else '-':>8} | "
                     f"{pct(base['sell']):>11} {pct(base['buy']):>11} {pct(base['tv']):>12}" + ("" if row["enough"] else "   (too few to judge)"))
    return "\n".join(lines)
