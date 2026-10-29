"""The exit what-if: would other stops, targets or time limits have made more from the same calls?

Every trade of a live account is replayed on the recorded minute candles under each exit rule in a small grid, changing one
thing at a time (see whatif/settings.py). The replay uses the live account's own stop-and-target logic, and it is checked
first: the trades are replayed exactly as they were traded and must come out as they really did.
"""

from __future__ import annotations

from paper_trade.whatif import replay, settings
from paper_trade.whatif.replay import Result, Trade, replay as replay_trade, trades_of

__all__ = ["Result", "Trade", "replay_trade", "trades_of", "variants", "run", "for_account", "render"]


def variants(style) -> list[tuple[str, float, float, float]]:
    """(name, stop in ranges, target in stops, hours): the account's own rules first, then each rule changed alone."""
    base = (style.stop_mult, style.reward_risk, style.max_hours)
    out = [("as set", *base)]
    for index, (label, values) in enumerate((("stop", settings.STOP_MULTS), ("target", settings.REWARD_RISKS), ("hours", settings.MAX_HOURS))):
        for value in values:
            rule = list(base)
            rule[index] = value
            if tuple(rule) != base:
                out.append((f"{label} {value:g}" + ("x" if label == "stop" else " stops" if label == "target" else " h"), *rule))
    return out


def run(trades: list[Trade], minutes: dict, style, equity: float) -> dict:
    """Replay ``trades`` (minute candles by ticker) under every variant. A trade with no minutes recorded since it opened
    cannot be replayed and is counted apart."""
    import pandas as pd

    usable, skipped = [], 0
    for trade in trades:
        frame = minutes.get(trade.ticker)
        opened = pd.Timestamp(trade.opened_at).tz_convert("UTC").tz_localize(None)
        if frame is None or frame.empty or frame.index[0] > opened + pd.Timedelta(minutes=settings.COVERAGE_SLACK_MINUTES):
            skipped += 1
            continue
        usable.append((trade, frame))
    finished = [(t, f) for t, f in usable if t.reason]
    wrong = [(t, why) for t, f in finished if (why := replay.differences(t, replay.as_traded(t, f, style.max_hours)))]
    rows = []
    for name, stop, reward, hours in variants(style):
        results = [replay_trade(t, f, style, stop, reward, hours, equity) for t, f in usable]
        pnl = [r.pnl for r in results]
        rows.append({"name": name, "trades": len(results), "open": sum(r.reason == "Open" for r in results),
                     "wins": sum(p > 0 for p in pnl), "total": round(sum(pnl), 2), "average": round(sum(pnl) / len(pnl), 2) if pnl else None,
                     "worst": round(min(pnl), 2) if pnl else None})
    return {"trades": len(usable), "skipped": skipped, "rows": rows, "enough": len(usable) >= settings.MIN_TRADES,
            "check": {"finished": len(finished), "exact": len(finished) - len(wrong),
                      "differences": [f"{t.ticker} {t.opened_at[:16]}: " + "; ".join(why) for t, why in wrong]}}


def for_account(account) -> dict:
    """The what-if of one live account, from its book and the recorded minutes."""
    from paper_trade.live import book as livebook
    from paper_trade.live import settings as live
    from paper_trade.live import tradingview

    book = livebook.load(live.book_path(account))
    trades, minutes = trades_of(book), {}
    for ticker in {t.ticker for t in trades}:
        try:
            minutes[ticker] = tradingview.all_candles(ticker)
        except Exception:                             # no recorded minutes for this pair: its trades cannot be replayed
            continue
    return run(trades, minutes, account.style, book.start_cash)


def render(result: dict, title: str = "") -> str:
    """A plain-text table of one what-if (for the command line)."""
    check = result["check"]
    lines = [f"{title}: {result['trades']} trades replayed" + (f" ({result['skipped']} older than the minute record, left out)" if result["skipped"] else ""),
             f"replay check: {check['exact']} of {check['finished']} finished trades come out exactly as traded" + ("" if check["exact"] == check["finished"] else " - the others:")]
    lines += [f"   {line}" for line in check["differences"]]
    lines.append(f"{'exit rule':<17} {'wins':>5} {'total $':>9} {'avg $':>7} {'worst $':>8}  (every row sized to the account's risk share at $100)")
    for row in result["rows"]:
        wins = f"{row['wins']}/{row['trades']}"
        average = "-" if row["average"] is None else f"{row['average']:+.2f}"
        worst = "-" if row["worst"] is None else f"{row['worst']:+.2f}"
        lines.append(f"{row['name']:<17} {wins:>5} {row['total']:>+9.2f} {average:>7} {worst:>8}" + (f"  ({row['open']} still open)" if row["open"] else ""))
    if not result["enough"]:
        lines.append(f"too few trades to judge (fewer than {settings.MIN_TRADES}): read this as a test of the tool, not as advice")
    return "\n".join(lines)
