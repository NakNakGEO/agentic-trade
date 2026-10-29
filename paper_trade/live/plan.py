"""Reading more of what an agent wrote than its rating, for the accounts that switch it on.

The agent's answer is a rating plus a trader's plan with an entry price and a stop loss. An account can use three things from it,
each its own switch (settings.PLAN_OPTIONS), all off by default so the account trades the rating alone:
  * levels: the agent's stop level replaces the account's own stop, when it is on the right side of the price and its distance
    is sane (within PLAN_STOP_MIN..PLAN_STOP_MAX of the account's own stop distance);
  * wait:   a call whose summary puts a condition on entering ("do not enter until", "wait for" ...) does not trade now;
    the next round's call decides again;
  * mild:   an Overweight or Underweight call trades MILD_SIZE of the usual size.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from paper_trade import config
from paper_trade.live import settings
from paper_trade.live.book import Tweaks

_STOP = re.compile(r"\*\*Stop Loss:?\*\*:?\s*\$?\s*([0-9][0-9,]*\.?[0-9]*)", re.I)
_WAIT = re.compile(settings.WAIT_PATTERN, re.I)
_SUMMARY_END = "Investment Thesis"          # the rating and its summary come before this heading in the final decision


@dataclass(frozen=True)
class Plan:
    stop: float | None      # the stop level in the trader's plan
    wait: str               # the words that put a condition on entering ('' when the call is unconditional)


def stop_of(plan_text: str) -> float | None:
    """The Stop Loss number in a trader's plan, or None when it has none the account can read."""
    found = _STOP.search(plan_text or "")
    try:
        return float(found.group(1).replace(",", "").rstrip(".")) if found else None
    except ValueError:
        return None


def wait_of(decision_text: str) -> str:
    """A short quote of the condition the call's summary puts on entering, or '' when it puts none."""
    summary = (decision_text or "").split(_SUMMARY_END)[0]
    found = _WAIT.search(summary)
    return summary[max(0, found.start() - 40): found.end() + 80].replace("\n", " ").strip() if found else ""


def read_plan(run_id: str, ticker: str, date: str) -> Plan | None:
    """The plan behind one call, from the agent's saved state for that pair and date (None when it is missing or unreadable)."""
    path = config.RUNS_DIR / "backtest" / run_id / ticker / "TradingAgentsStrategy_logs" / f"full_states_log_{date}.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return Plan(stop_of(state.get("trader_investment_plan")), wait_of(state.get("final_trade_decision")))


def tweaks_for(options: tuple[str, ...], run_id: str, ticker: str, date: str, rating: str) -> Tweaks | None:
    """What the account's switches take from this call (None: the rating alone)."""
    if not options:
        return None
    plan = read_plan(run_id, ticker, date) if {settings.PLAN_LEVELS, settings.PLAN_WAIT} & set(options) else None
    return Tweaks(stop=plan.stop if plan and settings.PLAN_LEVELS in options else None,
                  scale=settings.MILD_SIZE if settings.PLAN_MILD in options and rating in settings.MILD_RATINGS else 1.0,
                  hold=plan.wait if plan and settings.PLAN_WAIT in options else "")
