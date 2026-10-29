"""``python -m paper_trade whatif``: would other exit rules have made more from each live account's calls?"""

from __future__ import annotations

from paper_trade import whatif
from paper_trade.live import settings


def add_arguments(sub) -> None:
    card = sub.add_parser("whatif", help="replay each live account's trades under other stops, targets and time limits")
    card.add_argument("--account", choices=sorted(settings.ACCOUNTS), help="only this account (default: all)")


def run(args) -> int:
    for name, account in settings.ACCOUNTS.items():
        if args.account in (None, name):
            print(whatif.render(whatif.for_account(account), account.label), end="\n\n")
    return 0
