"""This system's market data for the AI models: TradingView live data plus our own day-by-day record, replacing Yahoo."""


def use_tradingview(settings: dict) -> dict:
    """See ``tvdata.install.use_tradingview`` (imported on call: fundamentals and news import tvdata.client)."""
    from paper_trade.tvdata.install import use_tradingview as install

    return install(settings)


__all__ = ["use_tradingview"]
