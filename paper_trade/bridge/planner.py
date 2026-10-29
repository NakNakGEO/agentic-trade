"""Turn one fresh decision into the orders it calls for. Read-only: nothing is sent from here."""

from __future__ import annotations

from datetime import datetime

from paper_trade.bridge import guards, settings, sizing, symbols
from paper_trade.bridge.broker import Broker
from paper_trade.bridge.models import (AccountState, OrderRequest, Position, Step, SymbolSpec, TickerPlan)
from paper_trade.simulator import Decision


def _target_side(rating: str) -> str | None:
    if rating in settings.LONG_RATINGS:
        return "buy"
    if rating in settings.SHORT_RATINGS:
        return "sell"
    return None


def _close_step(broker: Broker, position: Position) -> Step:
    quote = broker.quote(position.symbol)
    side = "sell" if position.side == "buy" else "buy"
    price = quote.bid if position.side == "buy" else quote.ask
    request = OrderRequest(position.symbol, side, position.volume, price, position=position.ticket,
                           comment=settings.COMMENT)
    return Step("close", request)


def _lots(plan: TickerPlan, spec: SymbolSpec, account: AccountState, distance: float) -> float | None:
    """The volume to open, or None after noting why this symbol cannot be traded at the configured size."""
    if settings.FIXED_LOT:
        lots = sizing.fixed_lots(spec, settings.FIXED_LOT)
        if lots == 0.0:
            plan.notes.append(f"the fixed lot {settings.FIXED_LOT:g} is below this symbol's minimum "
                              f"({spec.volume_min:g})")
            return None
        return lots
    budget_money = account.equity * settings.RISK_FRACTION * settings.CONVICTION[plan.rating]
    lots = sizing.lots_for_risk(spec, budget_money, distance)
    if lots == 0.0:
        smallest = sizing.loss_per_lot(spec, distance) * spec.volume_min
        plan.notes.append(f"the smallest lot ({spec.volume_min:g}) would lose {smallest:,.2f} at the stop, "
                          f"over the {budget_money:,.2f} budget ({settings.RISK_FRACTION:.0%} of equity)")
        return None
    return lots


def _open_step(plan: TickerPlan, broker: Broker, account: AccountState, spec: SymbolSpec, side: str,
               budget: guards.Budget, now: datetime) -> Step | None:
    """The order that opens the position, or None after noting why it cannot be opened."""
    if not (spec.long_allowed if side == "buy" else spec.short_allowed):
        plan.notes.append(f"{plan.symbol} does not allow {'long' if side == 'buy' else 'short'} trades right now")
        return None
    average_range = sizing.atr(broker.daily_bars(spec.name, settings.ATR_PERIOD + 1))
    if average_range is None:
        plan.notes.append(f"fewer than {settings.ATR_PERIOD + 1} daily bars, so no stop can be placed")
        return None
    quote = broker.quote(spec.name)
    distance = sizing.stop_distance(spec, average_range)
    entry = quote.ask if side == "buy" else quote.bid
    stop, target = sizing.levels(spec, side, entry, distance)
    reward_risk = abs(target - entry) / abs(entry - stop) if entry != stop else 0.0
    if reward_risk < settings.MIN_REWARD_RISK:
        plan.notes.append(f"reward:risk {reward_risk:.2f} is under the {settings.MIN_REWARD_RISK} minimum")
        return None

    lots = _lots(plan, spec, account, distance)
    if lots is None:
        return None
    risk = sizing.loss_per_lot(spec, distance) * lots
    if settings.FIXED_LOT and risk > account.equity * settings.RISK_FRACTION:
        plan.warnings.append(f"fixed lot {lots:g} risks {risk / account.equity:.1%} of equity at the stop, above "
                             f"the {settings.RISK_FRACTION:.0%} rule")
    if (reason := budget.refusal(risk)) is not None:
        plan.notes.append(reason)
        return None
    budget.take(risk)

    for warning in (guards.wide_spread(symbols.base_name(plan.ticker), spec, quote.ask - quote.bid, distance),
                    guards.low_liquidity(now)):
        if warning:
            plan.warnings.append(warning)
    request = OrderRequest(spec.name, side, lots, entry, stop, target, comment=settings.COMMENT)
    return Step("open", request, risk, risk / account.equity, reward_risk)


def plan_ticker(decision: Decision, broker: Broker, account: AccountState, available: list[str],
                positions: list[Position], budget: guards.Budget, now: datetime) -> TickerPlan:
    plan = TickerPlan(decision.ticker, symbols.resolve(decision.ticker, available), decision.rating, decision.date)
    if plan.symbol is None:
        near = symbols.similar(decision.ticker, available)
        plan.notes.append("no matching symbol on this account" + (f" (similar: {', '.join(near)})" if near else "")
                          + "; set SYMBOL_OVERRIDES in bridge/settings.py")
        return plan
    spec = broker.spec(plan.symbol)
    side = _target_side(decision.rating)
    if spec is None:
        plan.notes.append("the broker returned no symbol details")
        return plan
    if side is None:
        plan.action = "keep"
        plan.notes.append(f"{decision.rating}: leave any position as it is")
        return plan

    mine = [p for p in positions if p.symbol == plan.symbol and p.magic == settings.MAGIC]
    if any(p.side == side for p in mine):
        plan.action = "keep"
        plan.notes.append(f"already {'long' if side == 'buy' else 'short'}; no adding to a position")
        return plan
    for position in mine:                       # the rating turned against the open position: leave it
        plan.steps.append(_close_step(broker, position))
        budget.release(sizing.position_risk(spec, position, account.equity))
    if sum(1 for p in positions if p.symbol == plan.symbol) - len(mine) >= settings.MAX_POSITIONS_PER_SYMBOL:
        plan.notes.append(f"{settings.MAX_POSITIONS_PER_SYMBOL} positions already open on {plan.symbol}")
    else:
        opened = _open_step(plan, broker, account, spec, side, budget, now)
        if opened:
            plan.steps.append(opened)

    kinds = [s.kind for s in plan.steps]
    plan.action = "flip" if {"open", "close"} <= set(kinds) else (kinds[0] if kinds else "skip")
    for step in plan.steps:
        step.check = broker.check(step.request)     # the server's own dry-run; places nothing
    return plan
