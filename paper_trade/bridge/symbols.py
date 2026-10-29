"""Find the broker's name for a ticker: Exness spells XAUUSD as XAUUSDm, XAUUSDz and so on."""

from __future__ import annotations

from paper_trade.assets import canonical
from paper_trade.bridge import settings


def base_name(ticker: str) -> str | None:
    """The broker's undecorated name for a ticker, or None when the bridge does not know the asset."""
    symbol = canonical(ticker)
    if symbol in settings.BROKER_BASE_NAMES:
        return settings.BROKER_BASE_NAMES[symbol]
    return symbol[:-2] if symbol.endswith("=X") else None      # any forex pair: GBPUSD=X is GBPUSD at the broker


def resolve(ticker: str, available: list[str]) -> str | None:
    """The exact symbol on this account for ``ticker``; None when no candidate exists."""
    names = {name.lower(): name for name in available}
    for override in (settings.SYMBOL_OVERRIDES.get(ticker), settings.SYMBOL_OVERRIDES.get(canonical(ticker))):
        if override:
            return names.get(override.lower())
    base = base_name(ticker)
    if base is None:
        return None
    for suffix in settings.SYMBOL_SUFFIXES:
        found = names.get((base + suffix).lower())
        if found:
            return found
    return None


def similar(ticker: str, available: list[str], limit: int = 8) -> list[str]:
    """Names on the account that look like the ticker, to help fill in SYMBOL_OVERRIDES."""
    base = (base_name(ticker) or ticker.split("-")[0]).lower()
    return [name for name in available if base[:3] in name.lower()][:limit]
