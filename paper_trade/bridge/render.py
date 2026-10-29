"""Plain-text view of a bridge session: the account, one block per ticker, and what is about to be sent."""

from __future__ import annotations

from paper_trade.bridge import settings
from paper_trade.bridge.models import Step, TickerPlan
from paper_trade.bridge.session import Session


def _step_line(step: Step) -> str:
    r = step.request
    verdict = "no server check" if step.check is None else ("server accepts" if step.check.ok
                                                            else f"server REFUSES: {step.check.message}")
    if step.kind == "close":
        return f"    CLOSE {r.side.upper()} {r.volume:g} {r.symbol} at {r.price:g}  [{verdict}]"
    return (f"    OPEN {r.side.upper()} {r.volume:g} {r.symbol} at {r.price:g}  stop {r.sl:g}  target {r.tp:g}  "
            f"risk {step.risk_money:,.2f} ({step.risk_fraction:.2%})  R:R 1:{step.reward_risk:.1f}  [{verdict}]")


def _plan_block(plan: TickerPlan) -> list[str]:
    symbol = plan.symbol or "-"
    lines = [f"{plan.ticker:<9} {plan.rating:<12} {plan.action.upper():<5} {symbol}  (decision {plan.decision_date})"]
    lines += [_step_line(step) for step in plan.steps]
    lines += [f"    note: {note}" for note in plan.notes]
    lines += [f"    WARNING: {warning}" for warning in plan.warnings]
    return lines


def render(session: Session, sending: bool) -> str:
    account = session.account
    fixed = settings.FIXED_LOT
    sizing_rule = f"fixed lot {fixed:g}" if fixed else f"risk at most {settings.RISK_FRACTION:.0%} of equity per trade"
    cap = settings.FIXED_LOT_MAX_TOTAL_RISK if fixed else settings.MAX_TOTAL_RISK
    lines = [f"Account {account.login} on {account.server}: DEMO, balance {account.balance:,.2f} "
             f"{account.currency}, equity {account.equity:,.2f}",
             f"Rules: stop on every order, {sizing_rule}, reward:risk 1:{settings.REWARD_RISK:g}, one position per "
             f"pair, open risk capped at {cap:.0%}", ""]
    for plan in session.plans:
        lines += _plan_block(plan)
    ready = [p for p in session.plans if p.ready]
    orders = sum(len(p.steps) for p in ready)
    lines += ["", f"{orders} order(s) ready on {len(ready)} pair(s). {settings.NEWS_REMINDER}"]
    lines.append("This is a dry run: nothing was sent. Add --send to be asked for confirmation."
                 if not sending else "Sending needs a typed 'yes'.")
    return "\n".join(lines)
