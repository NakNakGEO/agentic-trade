"""One bridge run: read the latest decisions, then plan the orders they call for against the broker."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from paper_trade import config
from paper_trade.assets import canonical
from paper_trade.bridge import guards, settings, sizing
from paper_trade.bridge.broker import Broker
from paper_trade.bridge.models import AccountState, TickerPlan
from paper_trade.bridge.planner import plan_ticker
from paper_trade.simulator import Decision


@dataclass
class Session:
    account: AccountState
    plans: list[TickerPlan] = field(default_factory=list)


def latest_per_ticker(decisions: list[Decision], order: list[str] | None = None) -> list[Decision]:
    """The newest decision for each asset, in the order of ``order`` (the run's tickers) or the configured universe."""
    newest: dict[str, Decision] = {}
    for decision in sorted(decisions, key=lambda d: d.date):
        newest[canonical(decision.ticker)] = decision
    order = [canonical(t) for t in (order or config.UNIVERSE)]
    return sorted(newest.values(), key=lambda d: order.index(canonical(d.ticker))
                  if canonical(d.ticker) in order else len(order))


def age_in_days(decision: Decision, now: datetime) -> int:
    return (now.date() - datetime.strptime(decision.date, "%Y-%m-%d").date()).days


def build_session(broker: Broker, decisions: list[Decision], now: datetime | None = None,
                  order: list[str] | None = None) -> Session:
    """Plan every fresh decision. Raises RealAccountError unless the terminal is on a demo account."""
    now = now or datetime.now(timezone.utc)
    account = broker.account()
    guards.require_demo(account)
    available, positions = broker.symbol_names(), broker.positions()
    open_risk = 0.0
    for position in positions:
        spec = broker.spec(position.symbol)
        open_risk += sizing.position_risk(spec, position, account.equity) if spec else 0.0
    cap = settings.FIXED_LOT_MAX_TOTAL_RISK if settings.FIXED_LOT else settings.MAX_TOTAL_RISK
    budget = guards.Budget(len(positions), open_risk, account.equity, cap)

    session = Session(account)
    for decision in latest_per_ticker(decisions, order):
        age = age_in_days(decision, now)
        if not 0 <= age <= settings.MAX_DECISION_AGE_DAYS:
            stale = TickerPlan(decision.ticker, None, decision.rating, decision.date)
            stale.notes.append(f"decision is dated {decision.date} ({age} days old, limit "
                               f"{settings.MAX_DECISION_AGE_DAYS}); a past-dated run is never traded")
            session.plans.append(stale)
            continue
        session.plans.append(plan_ticker(decision, broker, account, available, positions, budget, now))
    return session
