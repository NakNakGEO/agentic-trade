"""The account's real trading rules, added to the instrument context that every agent reads.

No agent loses any of its work: the analysts, researchers, trader, risk team and portfolio manager keep their own
prompts. This only tells all of them, in plain words, what their call will do in this account and where the data comes
from, so a Sell is argued as a short with its stop above the entry and the risk team weighs the real position size.
"""

from __future__ import annotations

import os

from paper_trade import config
from paper_trade.bridge import settings as rules


def rules_text() -> str:
    return (
        " Trading desk rules for this paper account (live data, no real money):"
        f" the account starts with ${config.STARTING_CASH:,.0f}, shared by every instrument;"
        f" every trade is a fixed {rules.FIXED_LOT} lot."
        f" {' or '.join(rules.LONG_RATINGS)} opens a LONG (it profits when the price rises);"
        f" {' or '.join(rules.SHORT_RATINGS)} opens a SHORT (it profits when the price falls), with its stop ABOVE the"
        " entry and its target BELOW it; Hold leaves any open position as it is."
        f" The stop sits {rules.ATR_STOP_MULT:g} x the daily average true range (ATR {rules.ATR_PERIOD}) from the entry"
        f" and the target {rules.REWARD_RISK:g} x the stop distance on the other side (reward {rules.REWARD_RISK:g} :"
        " risk 1); a call against an open position closes it first; one position per instrument; open risk of all"
        f" trades together is capped at {rules.FIXED_LOT_MAX_TOTAL_RISK:.0%} of the account."
        " Forex, gold and crypto prices are real time; the US stocks (AAPL, NVDA, MSFT) are 15 minutes delayed on TradingView's free"
        " data, so treat a stock price as 15 minutes old."
        " Data: TradingView live prices and indicators on 1 hour, 4 hour, daily and weekly bars; daily history only"
        " from this system's own day-by-day record (it starts on the first day the system ran, so a short history is"
        " expected, not an error); news from many feeds plus the week's economic calendar. For a currency pair, gold"
        " or crypto, 'fundamentals' means the economies, interest rates, speculator positioning and network figures"
        " that get_fundamentals returns, not company accounts."
    )


def memory_text(ticker: str) -> str:
    """The model's own recent calls on this instrument, for a worker of a round-based account (named in AGENTIC_ACCOUNT)."""
    from paper_trade.live import memory, settings

    account = settings.ACCOUNTS.get(os.environ.get("AGENTIC_ACCOUNT", ""))
    if account is None or not ticker:
        return ""
    try:
        return memory.recent_calls_text(account, ticker)
    except Exception:                         # a missing memory must never stop an agent run
        return ""


def with_rules(build):
    """Wrap the framework's ``build_instrument_context`` so its text ends with the desk rules (and the account's recent calls)."""
    def build_with_rules(*args, **kwargs) -> str:
        ticker = kwargs.get("ticker") or (args[0] if args else "")
        return build(*args, **kwargs) + rules_text() + memory_text(ticker)
    build_with_rules.__wrapped__ = build
    return build_with_rules
