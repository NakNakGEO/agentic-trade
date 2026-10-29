"""``python -m paper_trade scorecard``: are each model's calls right? Prints the scorecard of each live account."""

from __future__ import annotations

from paper_trade import scorecard
from paper_trade.live import settings


def add_arguments(sub) -> None:
    card = sub.add_parser("scorecard", help="grade each live account's calls against what the price did")
    card.add_argument("--account", choices=sorted(settings.ACCOUNTS), help="only this account (default: all)")


def run(args) -> int:
    for name, account in settings.ACCOUNTS.items():
        if args.account in (None, name):
            print(scorecard.render(scorecard.for_account(account), account.label), end="\n\n")
    return 0
