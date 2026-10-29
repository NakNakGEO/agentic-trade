"""News sources for the news analyst. No Yahoo. Each feed is read at most once per NEWS_TTL, shared by every process."""

from __future__ import annotations

NEWS_TTL = 10 * 60
TV_HEADLINES_URL = "https://news-headlines.tradingview.com/v2/headlines"
TV_STORY_URL = "https://www.tradingview.com"
# (source name, RSS feed, what it covers)
RSS_FEEDS = [
    ("investingLive (ForexLive)", "https://investinglive.com/feed/", "forex"),
    ("Investing.com forex", "https://www.investing.com/rss/news_1.rss", "forex"),
    ("Investing.com commodities", "https://www.investing.com/rss/news_11.rss", "gold"),
    ("Kitco", "https://www.kitco.com/news/category/mining/rss", "gold"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "markets"),
    ("CNBC markets", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "markets"),
    ("CNBC economy", "https://www.cnbc.com/id/10000664/device/rss/rss.html", "markets"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "crypto"),
    ("CoinTelegraph", "https://cointelegraph.com/rss", "crypto"),
]
# words that tie a headline to an instrument (lower case, matched on word starts)
WORDS = {
    "EURUSD=X": ["eur", "euro", "ecb", "lagarde", "eurozone"], "GBPUSD=X": ["gbp", "pound", "sterling", "boe", "cable"],
    "USDJPY=X": ["jpy", "yen", "boj", "japan", "ueda"], "AUDUSD=X": ["aud", "aussie", "australia", "rba"],
    "USDCAD=X": ["cad", "loonie", "canada", "boc", "crude", "oil"], "USDCHF=X": ["chf", "franc", "snb", "swiss"],
    "NZDUSD=X": ["nzd", "kiwi", "new zealand", "rbnz"], "GC=F": ["gold", "xau", "bullion", "precious metal"],
    "BTC-USD": ["bitcoin", "btc", "crypto"], "ETH-USD": ["ether", "ethereum", "eth ", "crypto"],
}
USD_WORDS = ["dollar", "usd", "fed", "powell", "fomc", "federal reserve", "treasury yields", "nonfarm", "payrolls",
             "us cpi", "us inflation"]
STOCK_WORDS = {"AAPL": ["apple", "iphone"], "NVDA": ["nvidia"], "MSFT": ["microsoft", "azure"]}
PER_TICKER = 20
GLOBAL_LIMIT = 25
SUMMARY_CHARS = 260
