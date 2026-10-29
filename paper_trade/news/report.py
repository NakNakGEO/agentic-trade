"""The news analyst's tools: headlines for one instrument and for the whole market, from many sources, deduplicated.

Sources: TradingView's news feed (per symbol and per category), investingLive (ForexLive), Investing.com, Kitco,
MarketWatch, CNBC, CoinDesk and CoinTelegraph, plus this week's scheduled releases (ForexFactory). No Yahoo.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from paper_trade import assets
from paper_trade.fundamentals import calendar
from paper_trade.live import tradingview as live_tv
from paper_trade.news import settings, sources

KINDS = {"forex": {"forex", "markets"}, "gold": {"gold", "markets", "forex"}, "crypto": {"crypto", "markets"},
         "stock": {"markets"}}
CATEGORY = {"forex": "forex", "gold": "forex", "crypto": "crypto", "stock": "stock"}


def _key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()[:90]


def dedupe(items: list[dict]) -> list[dict]:
    """One record per story (same headline from two feeds counts once), newest first."""
    seen, out = set(), []
    for item in sorted(items, key=lambda i: i["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        key = _key(item["title"])
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _words(ticker: str) -> tuple[list[str], list[str]]:
    """(the instrument's own words, US dollar and Fed words that also move it)."""
    symbol = assets.canonical(ticker)
    own = settings.WORDS.get(symbol) or settings.STOCK_WORDS.get(symbol, []) + [symbol.lower()]
    return own, settings.USD_WORDS if symbol.endswith("=X") or symbol == "GC=F" else []


def matches(item: dict, words: list[str]) -> bool:
    text = f" {item['title']} {item['summary']} ".lower()
    return any(re.search(rf"\b{re.escape(w.strip())}\b", text) for w in words)


def _window(items: list[dict], start: str, end: str) -> list[dict]:
    lo = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    hi = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
    return [i for i in items if i["published"] is None or lo <= i["published"] < hi]


def render(items: list[dict], title: str) -> list[str]:
    if not items:
        return [title, "", "No matching headlines in any feed for these dates."]
    lines = [title, f"{len(items)} headlines, newest first, from {len({i['source'] for i in items})} sources.", ""]
    for item in items:
        when = f", {item['published']:%Y-%m-%d %H:%M} UTC" if item["published"] else ""
        lines.append(f"- {item['title']} ({item['source']}{when})")
        if item["summary"]:
            lines.append(f"  {item['summary']}")
    return lines


def _currencies(ticker: str) -> list[str]:
    symbol, kind = assets.canonical(ticker), assets.asset_class(ticker)
    return [symbol[:3], symbol[3:6]] if kind == "forex" else ["USD"]


def get_news(ticker: str, start_date: str, end_date: str, *args, **kwargs) -> str:
    kind = assets.asset_class(ticker)
    spec = live_tv.symbol(ticker)
    tagged = sources.tradingview(spec.split("|")[0]) if spec else []      # TradingView already tied these to the symbol
    own, usd = _words(ticker)
    pool = _window(sources.tradingview(category=CATEGORY[kind]) + sources.rss(KINDS[kind]), start_date, end_date)
    direct = dedupe(_window(tagged, start_date, end_date) + [i for i in pool if matches(i, own)])
    seen = {_key(i["title"]) for i in direct}
    dollar = [i for i in dedupe([i for i in pool if usd and matches(i, usd)]) if _key(i["title"]) not in seen]
    items = direct + dollar                                    # the instrument's own news first, then dollar and Fed news
    lines = render(items[:settings.PER_TICKER], f"## News related to {ticker}, {start_date} to {end_date}")
    if kind != "crypto":
        lines += [""] + calendar.render(_currencies(ticker))
    return "\n".join(lines)


def get_global_news(curr_date: str, look_back_days: int | None = None, limit: int | None = None, *args, **kwargs) -> str:
    start = (datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=look_back_days or 3)).strftime("%Y-%m-%d")
    pool = sources.tradingview(category="base") + sources.rss({"markets", "forex"})
    items = dedupe(_window(pool, start, curr_date))
    lines = render(items[: limit or settings.GLOBAL_LIMIT], f"## Market and economy headlines, {start} to {curr_date}")
    return "\n".join(lines + [""] + calendar.render(["USD", "EUR", "GBP", "JPY"]))
