import pytest

from paper_trade.live import feeds, kraken

TICKER = {"PAXGUSD": {"a": ["4055.90", "1", "1.000"], "b": ["4055.30", "1", "1.000"], "c": ["4056.14", "0.08"]}}
OHLC = {"PAXGUSD": [[1793182800, "4050.1", "4052.0", "4049.5", "4051.2", "4050.8", "1.2", 7],
                    [1793182860, "4051.2", "4053.4", "4051.0", "4053.0", "4052.1", "0.4", 3]], "last": 1793182860}


@pytest.fixture(autouse=True)
def without_tradingview(monkeypatch):
    """These tests are about the sources after TradingView, so it is switched off here."""
    monkeypatch.setattr(feeds.tradingview, "enabled", lambda: False)


def test_the_price_is_the_middle_of_bid_and_ask():
    assert kraken.parse_ticker(TICKER) == pytest.approx(4055.6)


def test_ohlc_rows_become_candles_on_utc_minutes():
    frame = kraken.parse_ohlc(OHLC)
    assert list(frame.columns) == ["Open", "High", "Low", "Close"] and frame.index.tz is None
    assert frame.index[1] - frame.index[0] == __import__("pandas").Timedelta(minutes=1)
    assert frame["High"].iloc[1] == pytest.approx(4053.4)


def test_kraken_covers_the_live_pairs_but_not_usdjpy_or_nzdusd():
    assert [kraken.pair(t) for t in ("XAUUSD", "BTC-USD", "ETH-USD", "EURUSD", "USDCHF")] ==         ["PAXGUSD", "XBTUSD", "ETHUSD", "EURUSD", "USDCHF"]
    assert kraken.pair("USDJPY") is None and kraken.pair("NZDUSD") is None


def test_sources_fall_back_in_order(monkeypatch):
    monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
    assert [feeds.source(t) for t in ("XAUUSD", "BTC-USD", "EURUSD", "NZDUSD")] == ["kraken", "kraken", "kraken", "none"]
    monkeypatch.setenv("OANDA_API_TOKEN", "x")
    assert [feeds.source(t) for t in ("XAUUSD", "BTC-USD", "EURUSD")] == ["oanda", "kraken", "oanda"]


def test_no_live_source_means_no_price_never_a_fallback(monkeypatch):
    monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
    monkeypatch.setattr(kraken, "latest_price", lambda t: (_ for _ in ()).throw(OSError("blocked")))
    assert feeds.latest_prices(["XAUUSD", "NZDUSD"]) == {"XAUUSD": None, "NZDUSD": None}
