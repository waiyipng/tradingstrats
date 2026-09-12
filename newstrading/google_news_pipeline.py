"""Multi-source Google/Alphabet news pipeline.

This script builds a practical news-to-signal pipeline for GOOGL/GOOG using a
mix of quality sources:
- Finnhub: symbol-specific company news
- Polygon: market-news and event-driven technology headlines
- Reuters RSS: high-quality general news feed with keyword filtering

It has three phases:
1. Source collection and deduplication
2. Relevance filtering and scoring
3. Signal generation and reporting

Usage examples:
    python google_news_pipeline.py --demo
    python google_news_pipeline.py --symbol GOOGL --inspect
    FINNHUB_API_KEY=... POLYGON_API_KEY=... python google_news_pipeline.py --symbol GOOGL
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib import parse, request


DEFAULT_SYMBOLS = ["GOOGL", "GOOG"]
QUALITY_SOURCES = [
    "Reuters",
    "Finnhub",
    "Polygon",
    "Bloomberg",
    "Benzinga",
    "Seeking Alpha",
    "Yahoo Finance",
    "Google News",
]
REPUTABLE_NEWS_SOURCES = [
    "Reuters",
    "Bloomberg",
    "WSJ",
    "Benzinga",
    "Seeking Alpha",
    "Finnhub",
    "Polygon",
    "Yahoo Finance",
    "Google News",
]
SOURCE_QUALITY = {
    "Reuters": 1.00,
    "Bloomberg": 1.00,
    "WSJ": 0.95,
    "Benzinga": 0.85,
    "Seeking Alpha": 0.80,
    "Finnhub": 0.80,
    "Polygon": 0.80,
    "Yahoo Finance": 0.70,
    "Google News": 0.55,
    "Demo": 0.50,
    "unknown": 0.50,
}

POSITIVE_KEYWORDS = {
    "surge",
    "strong",
    "growth",
    "accelerat",
    "beat",
    "beats",
    "profit",
    "rally",
    "record",
    "guide",
    "guidance",
    "cloud",
    "ai",
    "demand",
    "upgrade",
    "expansion",
    "gain",
    "higher",
    "revenue",
}
NEGATIVE_KEYWORDS = {
    "miss",
    "misses",
    "decline",
    "drop",
    "weak",
    "slowdown",
    "sluggish",
    "risk",
    "regulatory",
    "antitrust",
    "lawsuit",
    "litigation",
    "delay",
    "downgrade",
    "loss",
    "pressure",
    "concern",
    "overhang",
}
ALPHABET_KEYWORDS = {
    "google",
    "alphabet",
    "googl",
    "goog",
    "youtube",
    "android",
    "search",
    "cloud",
    "gemini",
    "ai",
    "ads",
    "chrome",
}
TOPIC_KEYWORDS = {
    "earnings": {"earnings", "revenue", "profit", "quarter", "guidance"},
    "cloud": {"cloud", "infrastructure", "gcp", "ai infrastructure"},
    "ai": {"ai", "gemini", "artificial intelligence"},
    "antitrust": {"antitrust", "lawsuit", "regulatory", "court"},
    "search": {"search", "ads", "ad revenue", "traffic"},
    "product": {"youtube", "android", "chrome", "pixel", "launch"},
}


@dataclass
class NewsArticle:
    source: str
    title: str
    summary: str
    url: str = ""
    published_at: Optional[str] = None
    relevance: float = 0.0
    sentiment: str = "neutral"
    sentiment_score: float = 0.0
    topic: str = "general"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "published_at": self.published_at,
            "relevance": round(self.relevance, 3),
            "sentiment": self.sentiment,
            "sentiment_score": round(self.sentiment_score, 3),
            "topic": self.topic,
        }


class NewsSource:
    name: str = "base"

    def fetch(self, symbols: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        return []


class FinnhubNewsSource(NewsSource):
    name = "Finnhub"

    def __init__(self, api_key: Optional[str]):
        self.api_key = api_key or os.getenv("FINNHUB_API_KEY")

    def fetch(self, symbols: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []
        articles: List[Dict[str, Any]] = []
        for symbol in symbols:
            from_date = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
            to_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            url = (
                "https://finnhub.io/api/v1/company-news"
                f"?symbol={parse.quote(symbol)}&from={from_date}&to={to_date}&token={self.api_key}"
            )
            try:
                payload = safe_json_get(url)
            except Exception:
                continue
            if not isinstance(payload, list):
                continue
            for item in payload:
                title = (item.get("headline") or item.get("summary") or "").strip()
                summary = (item.get("summary") or title or "").strip()
                if not title and not summary:
                    continue
                published = item.get("datetime")
                dt_value = datetime.utcfromtimestamp(int(published)).isoformat() if published else None
                articles.append(
                    {
                        "source": "Finnhub",
                        "title": title,
                        "summary": summary,
                        "url": item.get("url") or "",
                        "published_at": dt_value,
                    }
                )
        return articles


class PolygonNewsSource(NewsSource):
    name = "Polygon"

    def __init__(self, api_key: Optional[str]):
        self.api_key = api_key or os.getenv("POLYGON_API_KEY")

    def fetch(self, symbols: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []
        articles: List[Dict[str, Any]] = []
        for symbol in symbols:
            url = (
                "https://api.polygon.io/v2/reference/news"
                f"?limit=20&order=desc&sort=published_utc&ticker={parse.quote(symbol)}&apiKey={self.api_key}"
            )
            try:
                payload = safe_json_get(url)
            except Exception:
                continue
            for item in payload.get("results", []) if isinstance(payload, dict) else []:
                title = (item.get("title") or "").strip()
                summary = (item.get("description") or item.get("summary") or title or "").strip()
                if not title and not summary:
                    continue
                publications = item.get("published_utc") or item.get("publishedAt") or None
                articles.append(
                    {
                        "source": "Polygon",
                        "title": title,
                        "summary": summary,
                        "url": item.get("url") or "",
                        "published_at": publications,
                    }
                )
        return articles


class ReutersRSSSource(NewsSource):
    name = "Reuters"

    def fetch(self, symbols: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        urls = [
            "https://feeds.reuters.com/reuters/technologyNews",
            "https://feeds.reuters.com/reuters/businessNews",
        ]
        articles: List[Dict[str, Any]] = []

        for url in urls:
            try:
                payload = safe_http_get(url)
            except Exception:
                continue
            root = ET.fromstring(payload)
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                description = (item.findtext("description") or item.findtext("content") or "").strip()
                published_raw = item.findtext("pubDate") or ""
                try:
                    published = parsedate_to_datetime(published_raw).isoformat() if published_raw else None
                except Exception:
                    published = None
                content = f"{title} {description}".lower()
                if not any(key in content for key in ("google", "alphabet", "googl", "youtube", "android", "search", "ai")):
                    continue
                if not any(sym.lower() in content for sym in ["google", "alphabet", "googl", "google cloud", "youtube", "android"]):
                    continue
                articles.append(
                    {
                        "source": "Reuters",
                        "title": title,
                        "summary": description or title,
                        "url": link,
                        "published_at": published,
                    }
                )
        return articles


class YahooFinanceRSSSource(NewsSource):
    name = "Yahoo Finance"

    def fetch(self, symbols: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        articles: List[Dict[str, Any]] = []
        for symbol in symbols:
            url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={parse.quote(symbol)}&region=US&lang=en-US"
            try:
                payload = safe_http_get(url)
            except Exception:
                continue
            try:
                root = ET.fromstring(payload)
            except ET.ParseError:
                continue
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                description = (item.findtext("description") or title or "").strip()
                published_raw = item.findtext("pubDate") or ""
                try:
                    published = parsedate_to_datetime(published_raw).isoformat() if published_raw else None
                except Exception:
                    published = None
                if not title:
                    continue
                articles.append(
                    {
                        "source": "Yahoo Finance",
                        "title": title,
                        "summary": description or title,
                        "url": link,
                        "published_at": published,
                    }
                )
        return articles


class GoogleNewsRSSSource(NewsSource):
    name = "Google News"

    def fetch(self, symbols: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        queries = [
            "Alphabet Google AI",
            "Google Cloud AI",
            "GOOGL earnings",
            "Alphabet antitrust",
            "Google search revenue",
        ]
        articles: List[Dict[str, Any]] = []
        for query in queries:
            encoded = parse.quote(query)
            url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
            try:
                payload = safe_http_get(url)
            except Exception:
                continue
            try:
                root = ET.fromstring(payload)
            except ET.ParseError:
                continue
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                description = (item.findtext("description") or title or "").strip()
                published_raw = item.findtext("pubDate") or ""
                try:
                    published = parsedate_to_datetime(published_raw).isoformat() if published_raw else None
                except Exception:
                    published = None
                if not title:
                    continue
                content = f"{title} {description}".lower()
                if not any(keyword in content for keyword in ("google", "alphabet", "googl", "cloud", "android", "ai", "youtube", "search")):
                    continue
                articles.append(
                    {
                        "source": "Google News",
                        "title": title,
                        "summary": description or title,
                        "url": link,
                        "published_at": published,
                    }
                )
        return articles


def safe_http_get(url: str) -> bytes:
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with request.urlopen(req, timeout=20) as resp:
        return resp.read()


def safe_json_get(url: str) -> Any:
    return json.loads(safe_http_get(url).decode("utf-8", errors="replace"))


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9+\-]{3,}", (text or "").lower())


def match_keywords(text: str, keyword_set: Iterable[str]) -> int:
    text_l = text.lower()
    matches = 0
    for keyword in keyword_set:
        if " " in keyword:
            if keyword in text_l:
                matches += 1
        else:
            if keyword in tokenize(text_l):
                matches += 1
    return matches


def infer_topic(text: str) -> str:
    scores: Dict[str, int] = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        scores[topic] = match_keywords(text, keywords)
    if not any(scores.values()):
        return "general"
    return max(scores, key=scores.get)


def score_article(article: Dict[str, Any]) -> Dict[str, Any]:
    text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
    pos_hits = match_keywords(text, POSITIVE_KEYWORDS)
    neg_hits = match_keywords(text, NEGATIVE_KEYWORDS)
    alpha_hits = match_keywords(text, ALPHABET_KEYWORDS)
    raw_score = (pos_hits - neg_hits) / max(1, pos_hits + neg_hits + 1)
    if raw_score > 0.05:
        sentiment = "positive"
    elif raw_score < -0.05:
        sentiment = "negative"
    else:
        sentiment = "neutral"
    relevance = min(1.0, (alpha_hits + 1) / 6.0)
    source_name = article.get("source") or "unknown"
    source_weight = SOURCE_QUALITY.get(source_name, SOURCE_QUALITY["unknown"])
    weighted_score = raw_score * source_weight
    return {
        "source": source_name,
        "title": article.get("title") or "Untitled article",
        "summary": article.get("summary") or article.get("title") or "",
        "url": article.get("url") or "",
        "published_at": article.get("published_at"),
        "relevance": relevance,
        "sentiment": sentiment,
        "sentiment_score": raw_score,
        "weighted_score": weighted_score,
        "source_weight": source_weight,
        "topic": infer_topic(text),
    }


def dedupe_articles(articles: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique: List[Dict[str, Any]] = []
    for article in articles:
        key = (article.get("source", ""), (article.get("title") or "").strip().lower(), (article.get("url") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        unique.append(article)
    return unique


def aggregate_signal(scored_articles: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not scored_articles:
        return {"decision": "HOLD", "score": 0.0, "confidence": 0.0, "articles": []}

    weighted = []
    for article in scored_articles:
        relevance = article.get("relevance", 0.0)
        sentiment_score = article.get("weighted_score", 0.0)
        weighted.append(relevance * (1.5 * sentiment_score))

    composite = sum(weighted)
    positive = sum(1 for item in scored_articles if item.get("sentiment") == "positive")
    negative = sum(1 for item in scored_articles if item.get("sentiment") == "negative")
    confidence = min(0.99, max(0.0, abs(composite) / (len(scored_articles) * 2.0 + 1e-6)))

    if composite >= 0.8:
        decision = "BUY"
    elif composite <= -0.8:
        decision = "SELL"
    else:
        decision = "HOLD"

    return {
        "decision": decision,
        "score": float(composite),
        "confidence": float(confidence),
        "positive": positive,
        "negative": negative,
        "articles": list(scored_articles),
    }


def pipeline_demo(symbols: Sequence[str]) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    demo = [
        {
            "source": "Demo",
            "title": "Alphabet says AI infrastructure and cloud demand are accelerating across Google Cloud",
            "summary": "Google Cloud revenue and AI adoption continue to expand as enterprise customers increase workloads.",
            "url": "https://example.com/google-ai-cloud",
            "published_at": (now - timedelta(hours=2)).isoformat(),
        },
        {
            "source": "Demo",
            "title": "Google antitrust scrutiny remains a key risk for search and ad businesses",
            "summary": "Regulators are increasing pressure on Alphabet's ad and search businesses, raising legal risk.",
            "url": "https://example.com/google-antitrust",
            "published_at": (now - timedelta(days=1)).isoformat(),
        },
        {
            "source": "Demo",
            "title": "Alphabet beats estimates as cloud and search revenue both accelerate",
            "summary": "The company delivered a strong quarter with rising ad demand and a solid cloud growth outlook.",
            "url": "https://example.com/google-beat",
            "published_at": (now - timedelta(days=2)).isoformat(),
        },
    ]
    return demo


def get_default_sources() -> List[NewsSource]:
    return [
        ReutersRSSSource(),
        FinnhubNewsSource(os.getenv("FINNHUB_API_KEY")),
        PolygonNewsSource(os.getenv("POLYGON_API_KEY")),
        YahooFinanceRSSSource(),
        GoogleNewsRSSSource(),
    ]


def get_reputable_sources() -> List[NewsSource]:
    source_map = {
        "Reuters": ReutersRSSSource,
        "Finnhub": FinnhubNewsSource,
        "Polygon": PolygonNewsSource,
        "Yahoo Finance": YahooFinanceRSSSource,
        "Google News": GoogleNewsRSSSource,
    }
    sources: List[NewsSource] = []
    for name in REPUTABLE_NEWS_SOURCES:
        factory = source_map.get(name)
        if factory is None:
            continue
        if name == "Finnhub":
            sources.append(factory(os.getenv("FINNHUB_API_KEY")))
        elif name == "Polygon":
            sources.append(factory(os.getenv("POLYGON_API_KEY")))
        else:
            sources.append(factory())
    return sources


def run_pipeline(symbols: Sequence[str], lookback_days: int = 7, demo: bool = False, sources: Optional[Sequence[NewsSource]] = None) -> Dict[str, Any]:
    if demo:
        raw = pipeline_demo(symbols)
    else:
        source_list = list(sources) if sources is not None else get_default_sources()
        raw = []
        for source in source_list:
            try:
                raw.extend(source.fetch(symbols, lookback_days=lookback_days))
            except Exception:
                continue
        raw = dedupe_articles(raw)

    scored = [score_article(article) for article in raw]
    scored = [item for item in scored if item["relevance"] >= 0.15]
    signal = aggregate_signal(scored)
    return {
        "symbols": list(symbols),
        "sources": list({article["source"] for article in scored}),
        "source_count": len(raw),
        "scored_count": len(scored),
        "signal": signal,
        "articles": [article for article in scored],
        "source_quality": {key: SOURCE_QUALITY.get(key, SOURCE_QUALITY["unknown"]) for key in sorted({item["source"] for item in scored})},
    }


def print_report(result: Dict[str, Any]) -> None:
    sig = result["signal"]
    print("=" * 72)
    print("Alphabet multi-source news pipeline")
    print("=" * 72)
    print(f"Symbols: {', '.join(result['symbols'])}")
    print(f"Raw article count: {result['source_count']}")
    print(f"Scored article count: {result['scored_count']}")
    print(f"Decision: {sig['decision']} | score={sig['score']:.3f} | confidence={sig['confidence']:.0%}")
    print(f"Positive: {sig['positive']} | Negative: {sig['negative']}")
    print(f"Source quality: {result.get('source_quality', {})}")
    print("-" * 72)
    for article in sig["articles"][:10]:
        short_time = article.get("published_at", "unknown")
        print(f"[{article['source']}] {short_time} | {article['topic']} | {article['sentiment']} | {article['title']}")
    print("=" * 72)


def scheduler_loop(symbols: Sequence[str], delay_seconds: int, lookback_days: int = 7, demo: bool = False) -> None:
    print(f"Starting continuous ingestion loop; checking every {delay_seconds} seconds.")
    while True:
        result = run_pipeline(symbols, lookback_days=lookback_days, demo=demo)
        print_report(result)
        time.sleep(delay_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a multi-source news pipeline for Alphabet with source quality weighting.")
    parser.add_argument("--symbol", action="append", default=[], help="Ticker(s) to monitor; can be passed multiple times. Default: GOOGL GOOG")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days.")
    parser.add_argument("--demo", action="store_true", help="Use demo articles instead of live API calls.")
    parser.add_argument("--inspect", action="store_true", help="Print the raw article list before the final summary.")
    parser.add_argument("--schedule-seconds", type=int, default=0, help="If > 0, continuously re-run the pipeline every N seconds.")
    parser.add_argument("--reputable-only", action="store_true", help="Use only a curated reputable source list as the adapter set.")
    args = parser.parse_args()

    symbols = args.symbol or DEFAULT_SYMBOLS
    if args.reputable_only:
        sources = get_reputable_sources()
    else:
        sources = get_default_sources()
    if args.schedule_seconds > 0:
        scheduler_loop(symbols, delay_seconds=args.schedule_seconds, lookback_days=args.days, demo=args.demo)
        return 0

    result = run_pipeline(symbols, lookback_days=args.days, demo=args.demo, sources=sources)
    if args.inspect:
        for article in result["articles"]:
            print(json.dumps(article, sort_keys=True))
    print_report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
