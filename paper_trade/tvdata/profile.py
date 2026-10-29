"""The instrument's identity for every agent (company name, sector, industry, exchange), from TradingView's screener.

Returns the same keys as the framework's Yahoo profile (longName, sector, industry, exchange, quoteType), so the
framework's identity guard works unchanged: agents are told exactly which company or pair they are analyzing.
"""

from __future__ import annotations

from paper_trade import assets
from paper_trade.tvdata import client

QUOTE_TYPES = {"stock": "EQUITY", "forex": "CURRENCY", "gold": "COMMODITY", "crypto": "CRYPTOCURRENCY"}


def company_profile(ticker: str) -> dict:
    wanted = assets.canonical(ticker)
    rows = client.screener().get("rows", {})
    row = next((r for t, r in rows.items() if assets.canonical(t) == wanted), None)
    if not row:
        return {}
    profile = {"longName": row.get("description") or row.get("name"),
               "quoteType": QUOTE_TYPES.get(assets.asset_class(ticker), "")}
    for key in ("sector", "industry", "exchange"):
        if row.get(key):
            profile[key] = row[key]
    return profile
