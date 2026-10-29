from paper_trade.assets import trades_on


def test_crypto_trades_every_day_and_everything_else_only_on_weekdays():
    saturday, monday = "2026-10-17", "2026-10-19"
    assert trades_on("BTC-USD", saturday) is True
    for ticker in ("AAPL", "EURUSD", "XAUUSD"):
        assert trades_on(ticker, saturday) is False
        assert trades_on(ticker, monday) is True
