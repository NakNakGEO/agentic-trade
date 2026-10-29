"""The local dashboard's view of a LIVE paper account (runs/live/<account>/book.json) instead of a replayed run.

It returns the same shapes the replay path uses (a PortfolioResult and the chart dict), so the page needs no changes:
the account value, positions, trades and wins/losses come from the live book, and the trade chart shows M1 candles.
"""

from __future__ import annotations

import re
import time

import pandas as pd

from paper_trade import assets
from paper_trade.bridge import settings as rules
from paper_trade.live import book as lb
from paper_trade.live import feeds, schedule, settings
from paper_trade.portfolio import PortfolioResult
from paper_trade.simulator import SleeveResult, Trade

CACHE_SECONDS = 30
CHART_MINUTES = 240
_cache: dict = {}


def account_for(run_id: str) -> settings.Account | None:
    return next((a for a in settings.ACCOUNTS.values() if a.run_id == run_id), None)


def source_run(run_id: str) -> str:
    """The run whose decision log, model feed and token counts the page shows for ``run_id``: an account that trades
    another account's calls shows that account's, since it has none of its own."""
    account = account_for(run_id)
    if account is None:
        return run_id
    rounds = schedule.slot_runs(account.decisions_run) if account.call_every_minutes else []
    return rounds[-1] if rounds else account.decisions_run          # an account that calls often shows its newest round


def _minute(stamp: str) -> str:
    return stamp[:16].replace("T", " ")


def _sleeve(book: lb.Book, ticker: str, slice_cash: float, equity_now: float, price: float | None,
            stamp: pd.Timestamp) -> SleeveResult:
    closed = [c for c in book.closed if c.ticker == ticker]
    open_trades = lb.held(book, ticker)
    trades = []
    for c in closed:
        side = "long" if c.side > 0 else "short"
        trades.append(Trade(ticker, c.decision_date, _minute(c.opened_at), c.rating, c.side * lb.qty(ticker, c.entry, c.lot),
                            c.entry, 0.0, opens=side))
        trades.append(Trade(ticker, c.decision_date, _minute(c.closed_at), c.reason, -c.side * lb.qty(ticker, c.exit, c.lot),
                            c.exit, 0.0, c.pnl, _minute(c.opened_at), c.entry, side, None))
    pnl, shares, basis, last = sum(c.pnl for c in closed), 0.0, 0.0, price or (open_trades[0].entry if open_trades else 0.0)
    for pos in open_trades:                              # several open trades add up: long and short trades on a pair offset each other
        held_shares = pos.side * lb.qty(ticker, last, pos.lot)
        shares += held_shares
        basis += held_shares * pos.entry
        pnl += held_shares * last - held_shares * pos.entry - pos.cost
        trades.append(Trade(ticker, pos.decision_date, _minute(pos.opened_at), pos.rating, held_shares, pos.entry, pos.cost,
                            opens="long" if pos.side > 0 else "short"))
    value = slice_cash + pnl
    exposure = shares * last / equity_now if equity_now else 0.0
    return SleeveResult(ticker, pd.Series([value], index=[stamp]), pd.Series([exposure], index=[stamp]), trades,
                        shares=shares, cash=value - shares * last, basis=basis,
                        open_date=_minute(open_trades[0].opened_at) if open_trades else None, last_price=last)


def build_result(book: lb.Book, prices: dict[str, float | None], start_prices: dict[str, float | None],
                 spy: tuple[float | None, float | None], tickers: tuple[str, ...] = settings.TICKERS) -> PortfolioResult:
    """The live book as a PortfolioResult. Buy-and-hold lines run from the close before the account started."""
    tickers = list(tickers)
    slice_cash = book.start_cash / len(tickers)
    now = pd.Timestamp.now("UTC").tz_localize(None)
    start = pd.Timestamp(book.created).tz_convert("UTC").tz_localize(None) if book.created else now
    per_day = {start.normalize(): book.start_cash}
    for point in book.history:
        per_day[pd.Timestamp(point["t"]).tz_convert("UTC").tz_localize(None).normalize()] = point["equity"]
    equity_now = lb.equity(book, prices)
    per_day[now.normalize()] = equity_now
    strategy = pd.Series(per_day).sort_index()

    def held(now_price, start_price, cash):
        return cash * now_price / start_price if now_price and start_price else cash

    buy_hold = {t: pd.Series([slice_cash, held(prices.get(t), start_prices.get(t), slice_cash)], index=[start, now])
                for t in tickers}
    equal_weight = pd.Series([book.start_cash, sum(s.iloc[-1] for s in buy_hold.values())], index=[start, now])
    benchmark = pd.Series([book.start_cash, held(spy[1], spy[0], book.start_cash)], index=[start, now]) if spy[0]         else equal_weight                    # live mode has no SPY price: the benchmark line is the same pairs, held
    sleeves = {t: _sleeve(book, t, slice_cash, equity_now, prices.get(t), now) for t in tickers}
    held_value = sum(s.shares * s.last_price for s in sleeves.values())
    return PortfolioResult(start=start, end=now, starting_cash=book.start_cash, strategy=strategy,
                           benchmark=benchmark.groupby(benchmark.index.normalize()).last(),
                           equal_weight=equal_weight.groupby(equal_weight.index.normalize()).last(),
                           exposure=pd.Series([held_value / equity_now if equity_now else 0.0], index=[now]),
                           sleeves=sleeves, buy_hold=buy_hold)


def _close_before(ticker: str, when: pd.Timestamp) -> float | None:
    """The price when the account started, for the buy-and-hold comparison: the first TradingView minute recorded at
    or after ``when``, or else the last recorded daily close before it."""
    from paper_trade import daybook
    from paper_trade.live import tradingview

    try:
        minutes = tradingview.candles(ticker)["Close"]
        after = minutes[minutes.index >= when.floor("min")]
        if len(after):
            return float(after.iloc[0])
    except Exception:
        pass
    closes = daybook.bars(ticker)["Close"]
    before = closes[closes.index < when.normalize()]
    return float(before.iloc[-1]) if len(before) else None


RISK_SKIP = re.compile(r"open-risk cap: this trade risks \$([\d,.]+) with \$([\d,.]+) already at risk")


def plain_skip(why: str, limit: float) -> str:
    """The book's reason for not opening a trade, in plain words, with the account's risk limit in dollars."""
    found = RISK_SKIP.search(why)
    if not found:
        return "Not opened: " + (why[:1].lower() + why[1:] if why else "no reason recorded") + "."
    risk, held = (float(x.replace(",", "")) for x in found.groups())
    if risk > limit:
        return (f"Not opened: with the fixed lot, a stopped trade here would lose ${risk:,.2f}, more than the account's whole risk "
                f"limit of ${limit:,.2f} (half the account). It cannot open on an account this size.")
    return (f"Not opened: the stop could lose ${risk:,.2f}, but the risk limit is ${limit:,.2f} (half the account) and "
            f"${held:,.2f} is already at risk in other trades.")


def skipped_for(account: settings.Account) -> dict:
    """{ticker: {date, rating, why}} for the latest call per ticker that the account could not turn into a trade."""
    book = lb.load(settings.book_path(account))
    limit = rules.FIXED_LOT_MAX_TOTAL_RISK * (book.history[-1]["equity"] if book.history else book.start_cash)
    return {s["ticker"]: {"date": s["date"], "rating": s["rating"], "why": plain_skip(s["why"], limit)} for s in book.skipped
            if not lb.held(book, s["ticker"])}


def style_note(account: settings.Account | None) -> str | None:
    """The account's trade rules in plain words when they are not the standard daily ones, for the portfolio heading."""
    style = account.style if account else settings.DAILY
    if style == settings.DAILY:
        return None
    frame = "1-hour" if style.stop_frame == "1h" else "daily"
    text = (f"short-term version of the same calls: the stop is {style.stop_mult or rules.ATR_STOP_MULT:g} x the {frame} average range, "
            f"the target {style.reward_risk or rules.REWARD_RISK:g} stops away")
    if style.max_hours:
        text += f", and a trade is closed at the market after {style.max_hours:g} hours at the latest"
    if style.risk_fraction:
        text += f". Each trade is sized to lose about {style.risk_fraction:.0%} of the account at its stop (the smallest lot is {settings.LOT_STEP:g})"
        if style.fixed_lot_tickers:
            text += f", except {', '.join(style.fixed_lot_tickers)}, which stays at the fixed {rules.FIXED_LOT:g} lot"
    return text


def blotter_for(account: settings.Account) -> dict:
    """The account's open trades, orders and finished trades in TradingView's panel layout (see blotter.py), plus how much
    money is at risk in the open trades right now."""
    from paper_trade.dashboard import blotter

    book, prices = lb.load(settings.book_path(account)), feeds.latest_prices(account.tickers)
    value, at_risk = lb.equity(book, prices), sum(p.risk for p in book.positions.values())
    return {**blotter.build(book, prices),
            "risk": {"open": round(at_risk, 2), "account": round(value, 2), "share": round(at_risk / value, 4) if value > 0 else None,
                     "cap": account.risk_cap, "trades": len(book.positions)}}


def levels_for(account: settings.Account) -> dict:
    """{ticker: {stop, target, ...}} for the trades the account holds on each pair, so the portfolio table can show where
    they will exit. A pair with several trades shows no single stop or target: the totals, and how many trades."""
    book = lb.load(settings.book_path(account))
    out = {}
    for ticker in dict.fromkeys(p.ticker for p in book.positions.values()):
        trades = lb.held(book, ticker)
        results = [lb.outcomes(p) for p in trades]
        win, lose = round(sum(r[0] for r in results), 2), round(sum(r[1] for r in results), 2)
        deadline = min((p.deadline for p in trades if p.deadline), default="")
        if len(trades) == 1:
            p = trades[0]
            out[ticker] = {"stop": p.stop, "target": p.target, "lot": p.lot, "deadline": deadline, "win": win, "lose": lose}
        else:
            lots = [p.lot for p in trades]
            out[ticker] = {"stop": None, "target": None, "lot": None if None in lots else round(sum(lots), 8),
                           "deadline": deadline, "win": win, "lose": lose, "trades": len(trades)}
    return out


def live_result(account: settings.Account) -> PortfolioResult | str:
    """The live account for the dashboard, cached for a few seconds; an error string when it cannot be read."""
    hit = _cache.get(("result", account.name))
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    book = lb.load(settings.book_path(account))
    if not book.created:
        return "the live account has not started yet"
    created = pd.Timestamp(book.created).tz_convert("UTC").tz_localize(None)
    starts = _cache.get(("starts", account.name, book.created))
    if starts is None:
        starts = {t: _close_before(t, created) for t in account.tickers}
        _cache[("starts", account.name, book.created)] = starts
    prices = feeds.latest_prices(account.tickers)
    result = build_result(book, prices, starts, (None, None), account.tickers)     # no live SPY source: the page compares with holding
    _cache[("result", account.name)] = (time.time(), result)
    return result


def live_chart(account: settings.Account, ticker: str) -> dict:
    """M1 candles for ``ticker`` with the live account's entries, exits and open position, in the chart's shape."""
    from paper_trade.trade_record import record

    book = lb.load(settings.book_path(account))
    bars = feeds.intraday_bars(ticker)
    if bars is None or bars.empty:
        return {"ticker": ticker, "error": "no 1-minute prices right now"}
    bars = bars.iloc[-CHART_MINUTES:]
    labels = [i.strftime("%Y-%m-%d %H:%M") for i in bars.index]
    result = live_result(account)
    sleeve = None if isinstance(result, str) else next(
        (s for t, s in result.sleeves.items() if assets.canonical(t) == assets.canonical(ticker)), None)
    trades = []
    for t in (sleeve.trades if sleeve else []):
        trades.append({"fill_date": t.fill_date, "decision_date": t.decision_date, "rating": t.rating,
                       "side": "buy" if t.shares > 0 else "sell", "price": round(t.price, 5),
                       "value": round(abs(t.shares) * t.price, 4), "pnl": None if t.pnl is None else round(t.pnl, 4),
                       "entry_date": t.entry_date, "entry_price": None if t.entry_price is None else round(t.entry_price, 5),
                       "closes": t.closes, "opens": t.opens})
    trades_open = lb.held(book, ticker)
    net = sum(p.side for p in trades_open)               # long and short trades offset each other
    exposure = [[label, (1.0 if net > 0 else -1.0)] for label in labels if net and label >= _minute(trades_open[0].opened_at)]
    return {"ticker": ticker, "class": assets.asset_class(ticker), "start": labels[0],
            "bars": [[label, round(float(r.Open), 5), round(float(r.High), 5), round(float(r.Low), 5),
                      round(float(r.Close), 5)] for label, (_, r) in zip(labels, bars.iterrows())],
            "decisions": [], "trades": trades, "exposure": exposure, "pending": [],
            "record": record(sleeve) if sleeve else None,
            "open": None if not (sleeve and sleeve.shares) else {
                "side": "long" if sleeve.shares > 0 else "short", "entry_date": sleeve.open_date,
                "entry_price": round(sleeve.basis / sleeve.shares, 5), "shares": sleeve.shares,
                "last_price": sleeve.last_price, "pnl": round(sleeve.shares * sleeve.last_price - sleeve.basis, 4)}}
