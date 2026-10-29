"""Win/loss record of one asset's paper trades. A trade is closed when part of a position is closed (shares sold
from a long, or bought back from a short); it wins if that made money after fees against the average entry price
of those shares. What is still held is "open"."""

from __future__ import annotations

from paper_trade.simulator import SleeveResult


def record(sleeve: SleeveResult) -> dict:
    closed = [t for t in sleeve.trades if t.pnl is not None]
    wins = sum(1 for t in closed if t.pnl > 0)
    losses = sum(1 for t in closed if t.pnl < 0)
    holding = sleeve.shares != 0
    return {
        "closed": len(closed), "wins": wins, "losses": losses,
        "win_rate": wins / len(closed) if closed else None,
        "realized": sum(t.pnl for t in closed),
        "open": holding,
        "open_side": "long" if sleeve.shares > 0 else "short" if sleeve.shares < 0 else None,
        "open_pnl": sleeve.shares * sleeve.last_price - sleeve.basis if holding else 0.0,
        "open_since": sleeve.open_date,
        "open_entry_price": sleeve.basis / sleeve.shares if holding else None,
        "open_shares": sleeve.shares,
        "fills": len(sleeve.trades),
    }
