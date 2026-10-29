import pytest

from paper_trade import webcache
from paper_trade.fundamentals import fred, report

FRED = {"DFF": [("2026-10-26", 3.88)], "ECBDFR": [("2026-10-28", 2.5)],
        "CPIAUCSL": [("2025-09-01", 324.0), ("2026-08-01", 334.0), ("2026-09-01", 336.3)],
        "IRLTLT01DEM156N": [("2024-01-01", 2.1)]}           # too old to show as current
COT = [{"report_date_as_yyyy_mm_dd": "2026-10-20T00:00:00.000", "market_and_exchange_names": "EURO FX - CME",
        "noncomm_positions_long_all": "238183", "noncomm_positions_short_all": "301439", "open_interest_all": "850000"}]
CALENDAR = [{"title": "Federal Funds Rate", "country": "USD", "date": "2026-10-28T14:00:00-04:00", "impact": "High",
             "forecast": "4.00%", "previous": "4.00%"},
            {"title": "Bank Holiday", "country": "NZD", "date": "2026-10-26T00:00:00-04:00", "impact": "Holiday"}]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fake_get(url, ttl, params=None, **kwargs):
        if "stlouisfed" in url:
            return {"observations": [{"date": d, "value": str(v)} for d, v in FRED.get(params["series_id"], [])]}
        if "cftc" in url:
            return COT
        if "faireconomy" in url:
            return CALENDAR
        raise AssertionError(f"unexpected fetch {url}")
    monkeypatch.setattr(webcache, "get", fake_get)
    monkeypatch.setenv("FRED_API_KEY", "test-key")


def test_fred_readings_turn_cpi_into_inflation_and_leave_out_stale_series():
    rows = {r["series"]: r for r in fred.currency_table("USD", "2026-10-28") + fred.currency_table("EUR", "2026-10-28")}
    assert rows["CPIAUCSL"]["value"] == pytest.approx((336.3 / 324.0 - 1) * 100)
    assert rows["ECBDFR"]["value"] == 2.5 and "IRLTLT01DEM156N" not in rows


def test_forex_fundamentals_compare_both_economies_with_positioning_and_the_calendar():
    text = report.get_fundamentals("EURUSD", "2026-10-28")
    assert "EUR economy (FRED)" in text and "USD economy (FRED)" in text and "ECB deposit rate" in text
    assert "EURO FX - CME" in text and "-63,256" in text
    assert "Federal Funds Rate" in text and "Bank Holiday" not in text


def test_gold_fundamentals_lead_with_yields_and_the_dollar():
    text = report.get_fundamentals("XAUUSD", "2026-10-28")
    assert "Fundamentals for gold" in text and "Fed funds rate" in text and "CFTC" in text


def test_company_statements_do_not_apply_to_currencies_or_crypto():
    assert report.get_balance_sheet("EURUSD", "quarterly", "2026-10-28").startswith("NOT_APPLICABLE")
    assert report.get_cashflow("BTC-USD").startswith("NOT_APPLICABLE")
    assert report.get_insider_transactions("XAUUSD").startswith("NOT_APPLICABLE")


def test_api_keys_never_reach_the_cache(monkeypatch, tmp_path):
    monkeypatch.undo()
    monkeypatch.setattr(webcache, "CACHE_DIR", tmp_path)

    class Reply:
        headers = {"Content-Type": "application/json"}

        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": 1}

    monkeypatch.setattr(webcache.requests, "get", lambda *a, **k: Reply())
    assert webcache.get("https://example.test/api", 60, params={"q": "x", "api_key": "SECRET"}, secret_params=("api_key",)) == {"ok": 1}
    assert all("SECRET" not in p.read_text() for p in tmp_path.iterdir())
