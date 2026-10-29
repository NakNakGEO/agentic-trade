"""Position status per pair and the candle-chart rows for the monitor page (fixed-lot account)."""

from __future__ import annotations

from paper_trade.dashboard import market
from paper_trade.prices import load_bars

CALL_WORDS = {"Buy": "BUY", "Overweight": "BUY (mild)", "Hold": "HOLD (do nothing)", "Underweight": "SELL (mild)", "Sell": "SELL"}
SIDE_WORDS = {"long": "BUY (long)", "short": "SELL (short)"}


def px(value: float) -> str:
    """A price with sensible digits: 2 for large prices, 3 for yen-like, 5 for forex."""
    return f"{value:,.2f}" if abs(value) >= 1000 else f"{value:.3f}" if abs(value) >= 10 else f"{value:.5f}"


BLANK_CHART_ROW = {"kind": "", "ticker": "", "date": "", "open": None, "high": None, "low": None, "close": None,
                   "price": None, "side": "", "label": "", "pnl": None, "name": ""}


def live_prices(tickers: list[str]) -> dict[str, float | None]:
    """The latest 1-minute price of each pair from Yahoo; None when it cannot be read right now."""
    prices = {}
    for ticker in tickers:
        prices[ticker] = market.quote(ticker).get("price")
    return prices


def position_fields(decisions: list, sleeve, live: float | None) -> dict:
    """Where one pair stands: waiting for a call, call waiting to fill, open, closed, or never opened."""
    out = {"status": "waiting", "status_text": "Waiting for the first call", "side": "", "entry_price": None,
           "entry_date": "", "stop": None, "target": None, "last_price": None, "live_price": live,
           "open_pnl": 0.0, "closed_pnl": 0.0, "exit_reason": "", "exit_date": "", "exit_price": None}
    if not decisions:
        return {**out, **plain_fixed(decisions, sleeve, out)}
    if sleeve is None:
        out.update(status="pending", status_text="Call made, waiting for prices")
        return {**out, **plain_fixed(decisions, sleeve, out)}
    closed = [t for t in sleeve.trades if t.pnl is not None]
    out["closed_pnl"] = round(sum(t.pnl for t in closed), 2)
    out["last_price"] = sleeve.last_price
    if sleeve.shares != 0 and sleeve.levels:
        level = sleeve.levels
        price = live or sleeve.last_price
        out.update(status="open", side=level["side"], entry_price=level["entry"], entry_date=level["since"],
                   stop=level["stop"], target=level["target"],
                   open_pnl=round(sleeve.shares * price - sleeve.basis, 2),
                   status_text=f"Open {level['side']} since {level['since']}")
    elif sleeve.pending:
        out.update(status="pending", status_text=f"{sleeve.pending[-1].rating} call made; it fills at the next close")
    elif closed:
        last = closed[-1]
        out.update(status="closed", exit_reason=last.rating, exit_date=last.fill_date, exit_price=last.price,
                   status_text=f"Closed on {last.fill_date}: {last.rating}, {last.pnl:+.2f}")
    elif sleeve.notes:
        out.update(status="flat", status_text="Not opened: " + sleeve.notes[-1].split(": ", 1)[-1])
    else:
        out.update(status="flat", status_text=f"No position: last call was {decisions[-1].rating}")
    return {**out, **plain_fixed(decisions, sleeve, out)}


def plain_fixed(decisions: list, sleeve, out: dict) -> dict:
    """The fixed-lot account in plain words: a one-word state and a sentence saying what happened."""
    call = CALL_WORDS.get(decisions[-1].rating, decisions[-1].rating) if decisions else ""
    if not decisions:
        return {"call_text": "", "fixed_state": "waiting", "fixed_text": "No call yet."}
    if sleeve is None:
        return {"call_text": call, "fixed_state": "waiting", "fixed_text": "Call made, waiting for prices."}
    if out["status"] == "open":
        word = SIDE_WORDS[out["side"]]
        return {"call_text": call, "fixed_state": "holding",
                "fixed_text": f"{word} since {out['entry_date']} at {px(out['entry_price'])}. It closes by itself at the "
                              f"profit target {px(out['target'])} or the stop {px(out['stop'])}."}
    closed = [t for t in sleeve.trades if t.pnl is not None]
    if closed:
        last = closed[-1]
        how = {"Take-profit": "profit target hit", "Stop-loss": "stop-loss hit"}.get(last.rating, "closed by a new call")
        word = SIDE_WORDS.get(last.closes, last.closes)
        return {"call_text": call, "fixed_state": "won" if last.pnl > 0 else "lost",
                "fixed_text": f"{word} at {px(last.entry_price)} on {last.entry_date}, closed at {px(last.price)} on "
                              f"{last.fill_date} ({how}). {'Won' if last.pnl > 0 else 'Lost'} ${abs(last.pnl):,.2f}."}
    if out["status"] == "pending":
        return {"call_text": call, "fixed_state": "waiting", "fixed_text": "Call made. The trade starts at the next daily close."}
    if decisions[-1].rating == "Hold":
        return {"call_text": call, "fixed_state": "not_opened", "fixed_text": "The call was HOLD: do nothing. No trade was opened. HOLD does not mean waiting to buy or sell."}
    why = sleeve.notes[-1].split(": ", 1)[-1] if sleeve.notes else "no trade was made"
    why = "the 50% risk limit had no room left" if "cap" in why else why
    return {"call_text": call, "fixed_state": "not_opened", "fixed_text": f"Not opened: {why}."}


def long_short_fields(decisions: list, sleeve) -> dict:
    """The long/short account in plain words: holding, no position, or waiting for a call."""
    if not decisions:
        return {"ls_state": "waiting", "ls_text": "No call yet."}
    if sleeve is None:
        return {"ls_state": "waiting", "ls_text": "Call made, waiting for prices."}
    if sleeve.shares != 0:
        word = "BUY (long)" if sleeve.shares > 0 else "SELL (short)"
        share = abs(float(sleeve.exposure.iloc[-1])) * 100
        pnl = sleeve.shares * sleeve.last_price - sleeve.basis
        return {"ls_state": "holding", "ls_text": f"{word}, about {share:.0f}% of its slice, since {sleeve.open_date}. "
                                                  f"Profit or loss so far {pnl:+.2f}."}
    return {"ls_state": "flat", "ls_text": "No position."}


def chart_rows(tickers: list[str], sleeves: dict, since: str) -> list[dict]:
    """Daily candles since ``since`` for each pair, plus its entry and exit marks and the open position's levels."""
    rows = []
    for ticker in tickers:
        try:
            bars = load_bars(ticker, since)
        except Exception:               # a pair whose prices cannot be read just has no chart
            continue
        for day, bar in bars.iterrows():
            rows.append({**BLANK_CHART_ROW, "kind": "bar", "ticker": ticker, "date": day.strftime("%Y-%m-%d"),
                         "open": round(float(bar["Open"]), 5), "high": round(float(bar["High"]), 5),
                         "low": round(float(bar["Low"]), 5), "close": round(float(bar["Close"]), 5)})
        sleeve = sleeves.get(ticker)
        if sleeve is None:
            continue
        for trade in sleeve.trades:
            closing = trade.pnl is not None
            rows.append({**BLANK_CHART_ROW, "kind": "exit" if closing else "entry", "ticker": ticker,
                         "date": trade.fill_date, "price": round(trade.price, 5),
                         "side": trade.closes if closing else trade.opens, "label": trade.rating,
                         "pnl": round(trade.pnl, 2) if closing else None})
        if sleeve.levels:
            for name in ("entry", "stop", "target"):
                rows.append({**BLANK_CHART_ROW, "kind": "level", "ticker": ticker, "date": sleeve.levels["since"],
                             "price": round(sleeve.levels[name], 5), "name": name, "side": sleeve.levels["side"]})
    return rows or [dict(BLANK_CHART_ROW)]
