"""A live account's trades laid out like TradingView's trading panel (Positions, Orders, Trade history), one row per
order or trade, so two trades on the same pair show as two rows.

A trade is opened by one order and closed by another (a stop loss, a take profit, a time limit or a new call all close it
with a market order). An open trade's row shows its take profit and stop loss with what it makes or loses at each; a
closed trade's rows show whether it won or lost. Price moves are in pips for forex and in dollars of price (per ounce,
coin or share) for everything else.
"""

from __future__ import annotations

from datetime import datetime

from paper_trade import assets
from paper_trade.bridge import settings as rules
from paper_trade.live import book as lb
from paper_trade.lots import units_of


def _t(stamp: str | None) -> str:
    """An ISO time as 'YYYY-MM-DD HH:MM' (UTC), or a dash."""
    return stamp[:16].replace("T", " ") if stamp else "-"


def _lot(trade) -> float:
    return trade.lot if trade.lot is not None else rules.FIXED_LOT


def _action(side: int, opening: bool) -> str:
    """The order's side: opening a long or closing a short is a Buy, opening a short or closing a long is a Sell."""
    return "Buy" if (side > 0) == opening else "Sell"


def _word(side: int) -> str:
    return "long" if side > 0 else "short"


def _distance(ticker: str, move: float, signed: bool = False) -> str:
    """A price move in the pair's usual unit: pips for forex, dollars of price for everything else."""
    symbol = assets.canonical(ticker)
    if assets.asset_class(ticker) == "forex":
        pip = 0.01 if symbol.endswith("JPY=X") else 0.0001
        text = f"{abs(move) / pip:.1f} pips"
    else:
        text = f"${abs(move):,.2f}"
    return ("+" if move > 0 else "-" if move < 0 else "") + text if signed else text


def _floating(trade, prices: dict) -> float:
    """What an open trade is worth now, before the exit fee."""
    last = prices.get(trade.ticker) or trade.entry
    return round(trade.side * lb.qty(trade.ticker, last, trade.lot) * (last - trade.entry), 2)


def _trades(book: lb.Book) -> list[tuple[int, str, object]]:
    """Every trade, open or closed, as (number, 'open'|'closed', trade), oldest first. A trade keeps its number because a
    new trade always starts later than the rest."""
    rows = [("open", p) for p in book.positions.values()] + [("closed", c) for c in book.closed]
    rows.sort(key=lambda r: (r[1].opened_at, r[1].ticker))
    return [(n, state, trade) for n, (state, trade) in enumerate(rows, 1)]


def _outcome(trade, state: str, prices: dict) -> dict:
    """What the trade makes or loses: its floating result while open, its final result once closed."""
    if state == "open":
        return {"result": "open", "pnl": _floating(trade, prices)}
    return {"result": "win" if trade.pnl > 0 else "loss", "pnl": round(trade.pnl, 2)}


def _orders(n: int, state: str, trade, prices: dict) -> list[dict]:
    """The order that opened the trade and, once it is closed, the order that closed it."""
    held = state == "open"
    base = {"trade": n, "ticker": trade.ticker, "lot": _lot(trade), "status": "Filled", **_outcome(trade, state, prices)}
    entry = {**base, "kind": "open", "side": _action(trade.side, True), "fill": trade.entry, "tp": trade.target, "sl": trade.stop,
             "time": _t(trade.opened_at), "win": None, "lose": None, "win_move": "", "lose_move": ""}
    if held:
        win, lose = lb.outcomes(trade)
        entry.update(win=round(win, 2), lose=round(lose, 2), win_move=_distance(trade.ticker, trade.target - trade.entry),
                     lose_move=_distance(trade.ticker, trade.stop - trade.entry))
        return [entry]
    close = {**base, "kind": "close", "side": _action(trade.side, False), "fill": trade.exit, "tp": None, "sl": None,
             "time": _t(trade.closed_at), "win": None, "lose": None, "win_move": "", "lose_move": ""}
    return [entry, close]


def _position(n: int, trade, prices: dict) -> dict:
    last = prices.get(trade.ticker) or trade.entry
    win, lose = lb.outcomes(trade)
    symbol = assets.canonical(trade.ticker)
    return {"trade": n, "ticker": trade.ticker, "symbol": symbol, "side": _word(trade.side),
            "sign": trade.side, "lot": _lot(trade), "units": units_of(trade.ticker, trade.lot),
            "usd_base": symbol.endswith("=X") and symbol.startswith("USD"), "entry": trade.entry, "last": last,
            "stop": trade.stop, "target": trade.target, "win": round(win, 2), "lose": round(lose, 2),
            "to_target": _distance(trade.ticker, trade.target - trade.entry), "to_stop": _distance(trade.ticker, trade.stop - trade.entry),
            "pnl": _floating(trade, prices), "opened": _t(trade.opened_at), "expiry": _t(trade.deadline or None),
            "call": trade.rating}


def _history(n: int, trade) -> dict:
    held = (datetime.fromisoformat(trade.closed_at) - datetime.fromisoformat(trade.opened_at)).total_seconds() / 60
    return {"trade": n, "ticker": trade.ticker, "side": _word(trade.side), "lot": _lot(trade),
            "entry": trade.entry, "exit": trade.exit, "pnl": round(trade.pnl, 2), "reason": trade.reason,
            "move": _distance(trade.ticker, trade.side * (trade.exit - trade.entry), signed=True),
            "opened": _t(trade.opened_at), "closed": _t(trade.closed_at), "minutes": round(held), "call": trade.rating}


def build(book: lb.Book, prices: dict) -> dict:
    """{positions, orders, history}: open trades, every order newest first, and finished trades newest first."""
    trades = _trades(book)
    orders = [o for n, state, trade in trades for o in _orders(n, state, trade, prices)]
    orders.sort(key=lambda o: (o["time"], o["trade"], o["kind"] == "close"), reverse=True)
    return {"positions": [_position(n, t, prices) for n, state, t in reversed(trades) if state == "open"],
            "orders": orders,
            "history": [_history(n, t) for n, state, t in reversed(trades) if state == "closed"]}
