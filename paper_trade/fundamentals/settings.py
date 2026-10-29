"""What the fundamentals analyst reads for each asset class. Every source here is free; FRED needs FRED_API_KEY."""

from __future__ import annotations

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_TTL = 6 * 3600
FRED_STALE_DAYS = 270                # a reading older than this is left out rather than shown as current
# currency -> [(FRED series, what it is, "yoy" to show the change over a year instead of the level)]
FRED_SERIES = {
    "USD": [("DFF", "Fed funds rate %", ""), ("CPIAUCSL", "CPI inflation, % over a year", "yoy"),
            ("UNRATE", "Unemployment rate %", ""), ("DGS10", "10-year Treasury yield %", ""),
            ("DFII10", "10-year real yield (TIPS) %", ""), ("T10YIE", "10-year inflation expectation %", ""),
            ("DTWEXBGS", "Broad US dollar index", "")],
    "EUR": [("ECBDFR", "ECB deposit rate %", ""), ("CP0000EZ19M086NEST", "Euro-area HICP inflation, % over a year", "yoy"),
            ("IRLTLT01DEM156N", "German 10-year yield %", "")],
    "GBP": [("IUDSOIA", "SONIA overnight rate %", ""), ("LRHUTTTTGBM156S", "UK unemployment rate %", ""),
            ("IRLTLT01GBM156N", "UK 10-year gilt yield %", "")],
    "JPY": [("IRSTCI01JPM156N", "Japan overnight call rate %", ""), ("LRHUTTTTJPM156S", "Japan unemployment rate %", ""),
            ("IRLTLT01JPM156N", "Japan 10-year yield %", "")],
    "AUD": [("IRSTCI01AUM156N", "Australia overnight rate %", ""), ("LRHUTTTTAUM156S", "Australia unemployment %", ""),
            ("IRLTLT01AUM156N", "Australia 10-year yield %", "")],
    "CAD": [("IRSTCI01CAM156N", "Canada overnight rate %", ""), ("LRHUTTTTCAM156S", "Canada unemployment %", ""),
            ("IRLTLT01CAM156N", "Canada 10-year yield %", "")],
    "CHF": [("IRLTLT01CHM156N", "Swiss 10-year yield %", "")],
    "NZD": [("LRHUTTTTNZQ156S", "New Zealand unemployment %", ""), ("IRLTLT01NZM156N", "New Zealand 10-year yield %", "")],
}
GOLD_SERIES = ["DFII10", "DGS10", "T10YIE", "DTWEXBGS", "CPIAUCSL", "DFF"]

# CFTC Commitments of Traders (legacy, futures only): speculators' positions, published every Friday for Tuesday.
COT_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
COT_TTL = 12 * 3600
COT_WEEKS = 4
COT_CODES = {"EUR": "099741", "GBP": "096742", "JPY": "097741", "AUD": "232741", "CAD": "090741", "CHF": "092741",
             "NZD": "112741", "USD": "098662", "GOLD": "088691", "BTC": "133741", "ETH": "146021"}

# ForexFactory's weekly calendar (the feed its own site publishes): scheduled releases with forecast and previous.
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CALENDAR_TTL = 3600
CALENDAR_IMPACTS = ("High", "Medium")

COINGECKO_URL = "https://api.coingecko.com/api/v3"
COINGECKO_IDS = {"BTC-USD": "bitcoin", "ETH-USD": "ethereum"}
DEFILLAMA_CHAINS_URL = "https://api.llama.fi/v2/chains"
DEFILLAMA_CHAIN = {"ETH-USD": "Ethereum"}
CRYPTO_TTL = 3600

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
INSIDER_DAYS = 90
