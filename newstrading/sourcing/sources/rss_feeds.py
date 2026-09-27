"""RSS-based sources: Reuters, Yahoo Finance, and Google News search feeds.

Relevance filtering uses each watchlist symbol's configured aliases instead of
a hardcoded single-company keyword list, so this works across the whole
multi-symbol watchlist.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Sequence
from urllib import parse

from newstrading.sourcing.base import NewsSource
from newstrading.sourcing.http_utils import safe_http_get


def _parse_rss_items(payload: bytes) -> List[Dict[str, Any]]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []
    items: List[Dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        link = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or title).strip()
        published_raw = item.findtext("pubDate") or ""
        try:
            published_at = parsedate_to_datetime(published_raw).isoformat() if published_raw else None
        except Exception:
            published_at = None
        items.append({"title": title, "summary": description, "url": link, "published_at": published_at})
    return items


class ReutersRSSSource(NewsSource):
    """Reuters-restricted discovery via Google News RSS.

    Reuters retired the former feeds.reuters.com RSS host. This uses Google's
    published RSS search endpoint to discover Reuters links without scraping
    Reuters pages or representing the feed as direct Reuters delivery.
    """

    name = "reuters_rss"
    default_weight = 0.75

    def fetch(self, symbol: str, aliases: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        company = aliases[0] if aliases else symbol
        query = parse.quote(f'site:reuters.com "{company}"')
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        articles: List[Dict[str, Any]] = []
        payload = safe_http_get(url)
        for item in _parse_rss_items(payload):
            content = f"{item['title']} {item['summary']}".lower()
            if "reuters" not in content:
                continue
            articles.append({**item, "author": "Reuters via Google News RSS", "content": ""})
        return articles


class YahooFinanceRSSSource(NewsSource):
    name = "yahoo_finance_rss"
    default_weight = 0.7

    def fetch(self, symbol: str, aliases: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={parse.quote(symbol)}&region=US&lang=en-US"
        payload = safe_http_get(url)
        return [{**item, "author": "", "content": ""} for item in _parse_rss_items(payload)]


class GoogleNewsRSSSource(NewsSource):
    """Wraps the Google News aggregator search feed - a data source, not a legacy app file."""

    name = "google_news_rss"
    default_weight = 0.55

    def fetch(self, symbol: str, aliases: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        company = aliases[0] if aliases else symbol
        queries = [f"{symbol} stock", f"{company} earnings", f"{company} stock news"]
        needles = [a.lower() for a in aliases] + [symbol.lower()]
        articles: List[Dict[str, Any]] = []
        for query in queries:
            encoded = parse.quote(query)
            url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
            payload = safe_http_get(url)
            for item in _parse_rss_items(payload):
                content = f"{item['title']} {item['summary']}".lower()
                if not any(needle in content for needle in needles):
                    continue
                articles.append({**item, "author": "", "content": ""})
        return articles
