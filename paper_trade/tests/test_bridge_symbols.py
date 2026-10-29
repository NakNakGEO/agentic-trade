from fake_broker import SYMBOLS

from paper_trade.bridge import settings, symbols


def test_every_pair_in_the_universe_finds_its_exness_style_symbol():
    from paper_trade import config

    found = {ticker: symbols.resolve(ticker, list(SYMBOLS)) for ticker in config.UNIVERSE}
    assert found == {"AAPL": "AAPLm", "GOOGL": "GOOGLm", "AMZN": "AMZNm", "BTC-USD": "BTCUSDm",
                     "ETH-USD": "ETHUSDm", "EURUSD": "EURUSDm", "XAUUSD": "XAUUSDm"}


def test_the_yahoo_names_in_the_decision_log_resolve_too():
    assert symbols.resolve("GC=F", list(SYMBOLS)) == "XAUUSDm"
    assert symbols.resolve("EURUSD=X", list(SYMBOLS)) == "EURUSDm"


def test_an_undecorated_name_is_found_and_the_match_ignores_case():
    assert symbols.resolve("XAUUSD", ["xauusd"]) == "xauusd"


def test_a_ticker_missing_from_the_account_is_none_and_similar_names_are_offered():
    available = ["XAUUSD.pro", "EURUSD.pro"]
    assert symbols.resolve("XAUUSD", available) is None
    assert symbols.similar("XAUUSD", available) == ["XAUUSD.pro"]


def test_any_forex_pair_maps_to_its_own_name_with_the_accounts_suffix():
    available = ["GBPUSDm", "USDJPYm", "EURJPYm"]
    assert [symbols.resolve(p, available) for p in ("GBPUSD", "USDJPY", "EURJPY")] == available


def test_an_asset_the_bridge_has_no_name_for_is_none():
    assert symbols.resolve("TSLA", list(SYMBOLS)) is None


def test_an_override_wins_over_the_naming_rules(monkeypatch):
    monkeypatch.setattr(settings, "SYMBOL_OVERRIDES", {"AAPL": "AAPL.US"})
    assert symbols.resolve("AAPL", ["AAPLm", "AAPL.US"]) == "AAPL.US"
