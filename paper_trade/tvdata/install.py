"""Switch the TradingAgents engine from Yahoo to this system's data, inside this process only.

Nothing in the cloned framework is edited: a "tradingview" vendor is registered with its data router for prices,
indicators, fundamentals and news, the settings point those categories at it (macro data stays on FRED), and the
places that call Yahoo directly (the verified market snapshot, the company profile, and the price lookups that score
past decisions) are pointed here too. Every agent's context also gets the account's trading rules (tvdata.desk).
"""

from __future__ import annotations

from paper_trade import fundamentals, news
from paper_trade.tvdata import desk, profile, rating_fix, vendor

VENDOR = "tradingview"
METHODS = {
    "get_stock_data": vendor.get_stock_data,
    "get_indicators": vendor.get_indicators,
    "get_fundamentals": fundamentals.get_fundamentals,
    "get_balance_sheet": fundamentals.get_balance_sheet,
    "get_cashflow": fundamentals.get_cashflow,
    "get_income_statement": fundamentals.get_income_statement,
    "get_news": news.get_news,
    "get_global_news": news.get_global_news,
    "get_insider_transactions": fundamentals.get_insider_transactions,
}
CATEGORIES = {"core_stock_apis": VENDOR, "technical_indicators": VENDOR, "fundamental_data": VENDOR,
              "news_data": VENDOR, "macro_data": "fred"}


def use_tradingview(settings: dict) -> dict:
    """Register the vendor, patch the direct Yahoo calls, add the desk rules, and return the routed ``settings``."""
    from tradingagents.agents import context, tools
    from tradingagents.dataflows import router
    from tradingagents.graph import trading_graph
    from tradingagents.memory import settlement

    for method, function in METHODS.items():
        router.VENDOR_METHODS[method][VENDOR] = function
    tools.build_verified_market_snapshot = vendor.market_snapshot
    context.get_company_profile = profile.company_profile
    context._identity.cache_clear()
    settlement.get_closes = vendor.closes
    if not hasattr(trading_graph.build_instrument_context, "__wrapped__"):
        trading_graph.build_instrument_context = desk.with_rules(trading_graph.build_instrument_context)
    rating_fix.install()                      # a heading-style rating is a rating, not an unreadable decision
    settings.setdefault("data_vendors", {}).update(CATEGORIES)
    settings["tool_vendors"] = {k: v for k, v in settings.get("tool_vendors", {}).items() if k not in METHODS}
    settings["market_data"] = VENDOR
    return settings
