"""Classify tickers the way TradingAgents' own CLI does, and pick analysts per asset type."""

from __future__ import annotations

from datetime import datetime

CRYPTO_SUFFIXES = ("-USD", "-USDT", "-USDC", "-BTC", "-ETH")   # mirrors cli/prompts.py


def canonical(ticker: str) -> str:
    """The Yahoo symbol the data layer prices (``XAUUSD`` -> ``GC=F``, ``EURUSD`` -> ``EURUSD=X``)."""
    from tradingagents.dataflows.symbols import normalize_symbol

    return normalize_symbol(ticker)


def asset_type(ticker: str) -> str:
    """``crypto`` or ``stock``. Forex and gold run through the stock pipeline, as in the CLI."""
    return "crypto" if canonical(ticker).endswith(CRYPTO_SUFFIXES) else "stock"


def asset_class(ticker: str) -> str:
    """Reporting label: stock, crypto, forex or gold."""
    symbol = canonical(ticker)
    if symbol.endswith(CRYPTO_SUFFIXES):
        return "crypto"
    if symbol.endswith("=X"):
        return "forex"
    if symbol.endswith("=F"):
        return "gold" if symbol == "GC=F" else "futures"
    return "stock"


def trades_on(ticker: str, date: str) -> bool:
    """Whether the asset has a daily bar on ``date``: crypto every day, everything else Monday to Friday."""
    if asset_type(ticker) == "crypto":
        return True
    return datetime.strptime(date, "%Y-%m-%d").weekday() < 5


def analysts_for(ticker: str, requested: tuple[str, ...], crypto_fundamentals: bool = False) -> tuple[str, ...]:
    """Crypto has no company filings, so the CLI drops the fundamentals analyst there.

    ``crypto_fundamentals`` keeps it: this system's fundamentals vendor serves market size, supply and network data."""
    if asset_type(ticker) == "crypto" and not crypto_fundamentals:
        return tuple(a for a in requested if a != "fundamentals")
    return requested


def group_by_pipeline(tickers: list[str], requested: tuple[str, ...],
                      crypto_fundamentals: bool = False) -> dict[tuple[str, tuple], list[str]]:
    """Tickers that share an (asset type, analyst set) can be analyzed in one backtest call."""
    groups: dict[tuple[str, tuple], list[str]] = {}
    for ticker in tickers:
        key = (asset_type(ticker), analysts_for(ticker, requested, crypto_fundamentals))
        groups.setdefault(key, []).append(ticker)
    return groups
