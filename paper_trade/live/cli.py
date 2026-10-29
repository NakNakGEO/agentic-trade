"""``python -m paper_trade live loop|update|decide|status``: forward paper trading at live prices."""

from __future__ import annotations

import argparse

from paper_trade.live import book as livebook
from paper_trade.live import runner, settings


def add_arguments(sub) -> None:
    live = sub.add_parser("live", help="forward paper trading: today's decisions entered at live prices")
    live.add_argument("--account", choices=sorted(settings.ACCOUNTS), default="gemma_short",
                      help="gemma_short: the local model; qwen_short: the hosted model (spends the free token allowance)")
    live.add_argument("action", choices=("loop", "update", "decide", "status"),
                      help="loop: run forever (decisions each day, updates every few minutes); update: one update now; "
                           "decide: start today's decisions now; status: print the account")


def status_text(book: livebook.Book) -> str:
    last = book.history[-1]["equity"] if book.history else book.start_cash
    lines = [f"Live paper account: ${last:,.2f} (started with ${book.start_cash:,.2f} on {book.created or 'not started'})",
             f"Decisions acted on: {len(book.applied)}; trades skipped: {len(book.skipped)}", ""]
    lines += [f"HOLDING {'BUY' if p.side > 0 else 'SELL'} {t} since {p.opened_at} at {p.entry:g}, "
              f"stop {p.stop:g}, target {p.target:g}" + (f", {p.lot:g} lot" if p.lot else "")
              + (f", closes at the latest {p.deadline}" if p.deadline else "")
              for t, p in book.positions.items()] or ["No position is open."]
    lines += [f"{c.reason}: {'BUY' if c.side > 0 else 'SELL'} {c.ticker} {c.entry:g} -> {c.exit:g}, {c.pnl:+.2f}"
              for c in book.closed]
    lines += [f"Skipped {s['ticker']} {s['date']} ({s['rating']}): {s['why']}" for s in book.skipped]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    account = settings.ACCOUNTS[args.account]
    if args.action == "loop":
        runner.loop(account)
    elif args.action == "decide":
        runner.start_decisions(account)
        print(f"started today's decisions for {len(account.tickers)} pairs ({account.label})")
    elif args.action == "update":
        book = livebook.load(settings.book_path(account))
        print(f"account value ${runner.update(book, account):,.2f}")
    else:
        print(status_text(livebook.load(settings.book_path(account))))
    return 0
