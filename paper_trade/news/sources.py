"""Read headlines from TradingView's news feed and from the RSS feeds in settings, as one list of plain records."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from paper_trade import webcache
from paper_trade.news import settings

TAG = re.compile(r"<[^>]+>")
ATOM = "{http://www.w3.org/2005/Atom}"


def _clean(text: str | None) -> str:
    return " ".join(html.unescape(TAG.sub(" ", text or "")).split())


def _when(text: str | None):
    if not text:
        return None
    try:
        return parsedate_to_datetime(text).astimezone(timezone.utc)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None


def parse_rss(text: str, source: str) -> list[dict]:
    """RSS 2.0 or Atom items as {title, summary, url, published (UTC datetime or None), source}.

    A feed declaring entities or a document type is refused: news feeds have no need for them, and they are how
    hostile XML expands or reaches outside files (expat already limits expansion; this is a second guard)."""
    if re.search(r"<!(DOCTYPE|ENTITY)", text[:4000] if isinstance(text, str) else "", re.IGNORECASE):
        raise ValueError(f"{source}: feed declares a document type or entities; not parsed")
    root = ElementTree.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    items = root.iter("item") if root.find(".//item") is not None else root.iter(f"{ATOM}entry")
    out = []
    for item in items:
        get = lambda *names: next((item.findtext(n) for n in names if item.findtext(n)), "")   # noqa: E731
        link = get("link") or (item.find(f"{ATOM}link").get("href") if item.find(f"{ATOM}link") is not None else "")
        title = _clean(get("title", f"{ATOM}title"))
        if title:
            out.append({"title": title, "summary": _clean(get("description", f"{ATOM}summary"))[:settings.SUMMARY_CHARS],
                        "url": link.strip(), "published": _when(get("pubDate", f"{ATOM}updated", f"{ATOM}published")),
                        "source": source})
    return out


def rss(kinds: set[str] | None = None) -> list[dict]:
    """Every configured feed (or those covering ``kinds``); a feed that fails is skipped."""
    out = []
    for source, url, kind in settings.RSS_FEEDS:
        if kinds and kind not in kinds:
            continue
        try:
            out += parse_rss(webcache.get(url, settings.NEWS_TTL, as_json=False), source)
        except Exception:
            continue
    return out


def tradingview(tv_symbol: str | None = None, category: str | None = None) -> list[dict]:
    """TradingView's own headlines for one symbol ("OANDA:XAUUSD") or one category ("forex", "crypto", "stock")."""
    params = {"client": "web", "lang": "en"}
    params.update({"symbol": tv_symbol} if tv_symbol else {"category": category or "base"})
    try:
        body = webcache.get(settings.TV_HEADLINES_URL, settings.NEWS_TTL, params=params)
    except Exception:
        return []
    out = []
    for item in body.get("items", []):
        published = item.get("published")
        out.append({"title": _clean(item.get("title")), "summary": "", "source": f"TradingView ({item.get('source', '')})",
                    "url": settings.TV_STORY_URL + item["storyPath"] if item.get("storyPath") else "",
                    "published": datetime.fromtimestamp(published, timezone.utc) if published else None})
    return out
