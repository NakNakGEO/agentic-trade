"""Crypto fundamentals: market size, supply and trading volume (CoinGecko), money locked on the network (DefiLlama)."""

from __future__ import annotations

from paper_trade import webcache
from paper_trade.fundamentals import settings


def _money(value) -> str:
    if value is None:
        return "n/a"
    value = float(value)
    for size, unit in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if abs(value) >= size:
            return f"${value / size:,.2f} {unit}"
    return f"${value:,.2f}"


def coin(ticker: str) -> dict:
    coin_id = settings.COINGECKO_IDS[ticker]
    return webcache.get(f"{settings.COINGECKO_URL}/coins/{coin_id}", settings.CRYPTO_TTL, params={
        "localization": "false", "tickers": "false", "community_data": "false", "developer_data": "false"})


def market_share() -> dict:
    return webcache.get(f"{settings.COINGECKO_URL}/global", settings.CRYPTO_TTL).get("data", {})


def network_tvl(ticker: str) -> float | None:
    chain = settings.DEFILLAMA_CHAIN.get(ticker)
    if not chain:
        return None
    rows = webcache.get(settings.DEFILLAMA_CHAINS_URL, settings.CRYPTO_TTL)
    return next((r.get("tvl") for r in rows if r.get("name") == chain), None)


def render(ticker: str) -> list[str]:
    lines = [f"### {ticker} network and market fundamentals (CoinGecko, DefiLlama; current values)"]
    try:
        data = coin(ticker)
        m = data.get("market_data", {})
        usd = lambda key: (m.get(key) or {}).get("usd")                   # noqa: E731
        rows = [("Market value of all coins", _money(usd("market_cap"))), ("Market rank", data.get("market_cap_rank")),
                ("Trading volume, 24 hours", _money(usd("total_volume"))),
                ("Coins in circulation", f"{m.get('circulating_supply', 0):,.0f}"),
                ("Maximum supply", f"{m['max_supply']:,.0f}" if m.get("max_supply") else "no cap"),
                ("All-time high", f"{_money(usd('ath'))} ({(m.get('ath_change_percentage') or {}).get('usd', 0):+.1f}% from it)"),
                ("Price change 7 / 30 / 365 days %", " / ".join(f"{m.get(k) or 0:+.1f}" for k in (
                    "price_change_percentage_7d", "price_change_percentage_30d", "price_change_percentage_1y")))]
        share = market_share().get("market_cap_percentage", {}).get(data.get("symbol", ""))
        if share is not None:
            rows.append(("Share of the whole crypto market", f"{share:.1f}%"))
        tvl = network_tvl(ticker)
        if tvl is not None:
            rows.append(("Money locked in apps on the network (TVL)", _money(tvl)))
        lines += ["| Measure | Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows]
    except Exception as error:
        lines.append(f"Unavailable: {type(error).__name__}: {str(error)[:120]}")
    return lines
