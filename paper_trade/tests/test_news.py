from datetime import datetime, timezone

import pytest

from paper_trade.fundamentals import calendar
from paper_trade.news import report, sources

RSS = """<?xml version="1.0" encoding="UTF-8"?><rss><channel>
<item><title>Gold slips ahead of the Fed</title><description>&lt;p&gt;Bullion fell 0.4%&lt;/p&gt;</description>
<link>https://example.test/1</link><pubDate>Wed, 28 Oct 2026 11:25:00 GMT</pubDate></item>
<item><title>Thousands of dollars saved on used cars</title><description>Pain at the pump</description>
<pubDate>Wed, 28 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>Dollar steady before the Fed decision</title><pubDate>Wed, 28 Oct 2026 09:00:00 GMT</pubDate></item>
<item><title>Old gold story</title><pubDate>Mon, 12 Oct 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    feed = sources.parse_rss(RSS, "Kitco")
    tagged = [{"title": "Comex gold delivery intentions", "summary": "", "source": "TradingView (Dow Jones)", "url": "",
               "published": at("2026-10-28T12:00:00")},
              {"title": "Gold slips ahead of the Fed", "summary": "", "source": "TradingView (Reuters)", "url": "",
               "published": at("2026-10-28T11:20:00")}]
    monkeypatch.setattr(sources, "rss", lambda kinds=None: feed)
    monkeypatch.setattr(sources, "tradingview", lambda tv_symbol=None, category=None: tagged if tv_symbol else [])
    monkeypatch.setattr(calendar, "render", lambda currencies, now=None: [f"### Economic calendar ({', '.join(currencies)})"])


def test_rss_items_are_cleaned_and_dated():
    item = sources.parse_rss(RSS, "Kitco")[0]
    assert item["summary"] == "Bullion fell 0.4%" and item["published"] == at("2026-10-28T11:25:00")


def test_a_feed_declaring_entities_is_refused():
    with pytest.raises(ValueError, match="entities"):
        sources.parse_rss('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><rss/>', "bad")


def test_instrument_news_comes_first_is_deduplicated_and_kept_to_the_dates():
    text = report.get_news("XAUUSD", "2026-10-25", "2026-10-28")
    assert text.count("Gold slips ahead of the Fed") == 1 and "Comex gold delivery" in text
    assert "Dollar steady" in text and text.index("Comex gold") < text.index("Dollar steady")
    assert "Thousands of dollars" not in text and "Old gold story" not in text
    assert "Economic calendar (USD)" in text


def test_forex_news_lists_both_currencies_calendar_and_crypto_has_none():
    assert "Economic calendar (EUR, USD)" in report.get_news("EURUSD", "2026-10-25", "2026-10-28")
    assert "Economic calendar" not in report.get_news("BTC-USD", "2026-10-25", "2026-10-28")


def test_global_news_spans_the_look_back():
    text = report.get_global_news("2026-10-28", look_back_days=3)
    assert "2026-10-25 to 2026-10-28" in text and "Old gold story" not in text
