import json, time, urllib.request, warnings
warnings.filterwarnings("ignore")
def get(url, ua="paper-trade-research/1.0"):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, r.read()
# (TradingView price history is not used: this system records its own, day by day.)
# 2) TradingView scanner fundamentals + profile (tradingview_screener)
try:
    from tradingview_screener import Query
    cols = ["name", "description", "sector", "industry", "exchange", "country", "market_cap_basic", "price_earnings_ttm",
            "earnings_per_share_basic_ttm", "total_revenue_ttm", "net_income_ttm", "dividends_yield_current", "debt_to_equity", "return_on_equity"]
    n, df = Query().select(*cols).set_tickers("NASDAQ:AAPL", "NASDAQ:MSFT").get_scanner_data()
    print("TV stock fundamentals:", df.to_dict("records")[0])
    n, fx = Query().set_markets("forex").select("name", "description", "type", "currency").set_tickers("OANDA:EURUSD").get_scanner_data()
    print("TV forex profile:", fx.to_dict("records"))
except Exception as e:
    print("TV fundamentals FAILED:", type(e).__name__, str(e)[:200])
# 3) CFTC COT (legacy futures only, Euro FX 099741, gold 088691)
try:
    s, b = get("https://publicreporting.cftc.gov/resource/6dca-aqww.json?$where=cftc_contract_market_code%20in%28%27099741%27,%27088691%27%29&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=2")
    rows = json.loads(b); print("CFTC COT:", s, [(r["market_and_exchange_names"][:30], r["report_date_as_yyyy_mm_dd"][:10], r["noncomm_positions_long_all"], r["noncomm_positions_short_all"]) for r in rows])
except Exception as e:
    print("CFTC COT FAILED:", type(e).__name__, str(e)[:120])
# 4) Crypto fundamentals (keyless)
for name, url in (("CoinGecko", "https://api.coingecko.com/api/v3/coins/bitcoin?localization=false&tickers=false&community_data=false&developer_data=false"),
                  ("CoinPaprika", "https://api.coinpaprika.com/v1/tickers/btc-bitcoin"), ("DefiLlama", "https://api.llama.fi/v2/chains")):
    try:
        s, b = get(url); print(f"{name}: {s} {len(b)//1024} KB")
    except Exception as e:
        print(f"{name} FAILED:", type(e).__name__, str(e)[:80])
