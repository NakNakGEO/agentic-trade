"""Send the planned orders, after the account's terminal permits it and the user has typed yes."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from paper_trade.bridge import settings
from paper_trade.bridge.broker import Broker
from paper_trade.bridge.models import SendResult, Step, TickerPlan
from paper_trade.bridge.session import Session


def _log(path: Path, plan: TickerPlan, step: Step, result: SendResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ticker": plan.ticker,
           "rating": plan.rating, "decision_date": plan.decision_date, "kind": step.kind,
           "request": asdict(step.request), "ok": result.ok, "retcode": result.retcode,
           "message": result.message, "price": result.price, "ticket": result.ticket}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def execute(session: Session, broker: Broker, confirm: Callable[[], bool],
            log_path: Path = settings.LOG_PATH) -> list[str]:
    """Send every ready plan's orders in order; returns one line per order. Nothing is sent unless confirmed.

    A plan whose closing order fails is stopped there, so the opposite position is never opened on top of it.
    """
    ready = [plan for plan in session.plans if plan.ready]
    if not ready:
        return ["nothing to send"]
    if not session.account.terminal_trading_allowed:
        return ["not sent: turn on Tools > Options > Expert Advisors > Allow algorithmic trading in the MT5 "
                "terminal (and the AutoTrading button in its toolbar)"]
    if not confirm():
        return ["not sent: not confirmed"]

    lines = []
    for plan in ready:
        for step in plan.steps:
            result = broker.send(step.request)
            _log(log_path, plan, step, result)
            r = step.request
            lines.append(f"{'sent' if result.ok else 'FAILED'}: {step.kind} {r.side} {r.volume:g} {r.symbol} "
                         f"-> {result.message}" + (f" at {result.price:g}" if result.ok and result.price else ""))
            if not result.ok:
                break
    return lines
