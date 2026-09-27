"""CLI entry point for the Sourcing module.

Fetches news for one or more watchlist symbols across all configured providers,
deduplicates, and writes a news_batch.json artifact per symbol.

Usage:
    python -m newstrading.sourcing.run_sourcing --symbol AAPL
    python -m newstrading.sourcing.run_sourcing --all
    python -m newstrading.sourcing.run_sourcing --symbol AAPL --demo
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from newstrading.common import DATA_DIR, new_id, save_json, utcnow_iso
from newstrading.audit import update_symbol
from newstrading.config.loader import all_symbols, get_symbol_entry
from newstrading.models.news import NewsArticle, NewsBatch
from newstrading.sourcing.deduplicator import dedupe_with_audit
from newstrading.sourcing.sources.alpha_vantage_news import AlphaVantageNewsSource
from newstrading.sourcing.sources.benzinga import BenzingaNewsSource
from newstrading.sourcing.sources.finnhub import FinnhubNewsSource
from newstrading.sourcing.sources.marketaux import MarketauxNewsSource
from newstrading.sourcing.sources.polygon import PolygonNewsSource
from newstrading.sourcing.sources.rss_feeds import (
    GoogleNewsRSSSource,
    ReutersRSSSource,
    YahooFinanceRSSSource,
)
from newstrading.sourcing.sources.tiingo import TiingoNewsSource
from newstrading.sourcing.sources.sec_edgar import SecEdgarSource

DEMO_ARTICLES = [
    {
        "title": "{name} reports accelerating demand and raises forward guidance",
        "summary": "Analysts note strengthening fundamentals and a more constructive outlook for {name}.",
        "url": "https://example.com/demo-positive",
        "author": "Demo",
        "content": "",
    },
    {
        "title": "Regulatory scrutiny raises risk overhang for {name}",
        "summary": "Analysts flag rising regulatory and legal risk that could pressure {name} shares.",
        "url": "https://example.com/demo-negative",
        "author": "Demo",
        "content": "",
    },
]


def get_sources() -> List[Any]:
    return [
        SecEdgarSource(),
        FinnhubNewsSource(),
        PolygonNewsSource(),
        TiingoNewsSource(),
        AlphaVantageNewsSource(),
        BenzingaNewsSource(),
        MarketauxNewsSource(),
        ReutersRSSSource(),
        YahooFinanceRSSSource(),
        GoogleNewsRSSSource(),
    ]


def fetch_demo_articles(name: str) -> List[Dict[str, Any]]:
    now = utcnow_iso()
    articles = []
    for template in DEMO_ARTICLES:
        item = dict(template)
        item["title"] = item["title"].format(name=name)
        item["summary"] = item["summary"].format(name=name)
        item["published_at"] = now
        articles.append(item)
    return articles


def recent_articles(items: List[Dict[str, Any]], lookback_days: int) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    retained: List[Dict[str, Any]] = []
    for item in items:
        published_at = item.get("published_at")
        if not published_at:
            continue
        try:
            published = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if published >= cutoff:
            retained.append(item)
    return retained


def run_for_symbol(symbol: str, lookback_days: int, demo: bool, audit_run_id: str | None = None) -> NewsBatch:
    entry = get_symbol_entry(symbol)
    aliases = entry.get("aliases", [])

    if demo:
        raw_with_source = [{**a, "source": "demo", "source_weight": 0.5} for a in fetch_demo_articles(entry["name"])]
        provider_results = [{"provider": "demo", "status": "ok", "article_count": len(raw_with_source)}]
    else:
        raw_with_source = []
        provider_results = []
        for source in get_sources():
            if not source.is_configured():
                provider_results.append(
                    {
                        "provider": source.name,
                        "tier": source.tier,
                        "status": "unconfigured",
                        "article_count": 0,
                        "error": f"Missing {source.required_env_var}",
                    }
                )
                continue
            try:
                fetched = source.fetch(symbol, aliases, lookback_days=lookback_days)
            except Exception as exc:
                print(f"  [warn] {source.name} failed: {exc}", file=sys.stderr)
                provider_results.append({"provider": source.name, "tier": source.tier, "status": "failed", "article_count": 0, "error": str(exc)})
                continue
            recent = recent_articles(fetched, lookback_days)
            provider_results.append(
                {
                    "provider": source.name,
                    "tier": source.tier,
                    "status": "ok" if recent else "empty",
                    "article_count": len(recent),
                    "out_of_window_count": len(fetched) - len(recent),
                }
            )
            for item in recent:
                raw_with_source.append({**item, "source": source.name, "source_weight": source.default_weight, "source_tier": source.tier})

    deduped, dedupe_audit = dedupe_with_audit(raw_with_source)
    articles = [
        NewsArticle(
            id=uuid.uuid4().hex[:12],
            source=item["source"],
            source_weight=item["source_weight"],
            title=item["title"],
            summary=item["summary"],
            source_tier=item.get("source_tier", "secondary"),
            url=item.get("url", ""),
            content=item.get("content", ""),
            published_at=item.get("published_at"),
            author=item.get("author", ""),
        )
        for item in deduped
    ]

    batch = NewsBatch(batch_id=new_id("batch"), symbol=symbol, generated_at=utcnow_iso(), articles=articles)
    retained_ids = {(article.title, article.url): article.id for article in articles}
    audit_articles = [
        {
            **item,
            "article_id": retained_ids.get((item.get("title", ""), item.get("url", ""))),
            "summary": item.get("summary", ""),
            "url": item.get("url", ""),
        }
        for item in dedupe_audit
    ]
    update_symbol(
        audit_run_id,
        symbol,
        sourcing={
            "batch_id": batch.batch_id,
            "generated_at": batch.generated_at,
            "provider_results": provider_results,
            "fetched_article_count": len(raw_with_source),
            "retained_article_count": len(articles),
            "deduplicated_article_count": len(raw_with_source) - len(articles),
            "articles": audit_articles,
        },
    )
    return batch


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch and normalize multi-source news into news_batch.json artifacts.")
    parser.add_argument("--symbol", help="Single ticker to fetch, e.g. AAPL.")
    parser.add_argument("--all", action="store_true", help="Fetch for every symbol in config/watchlist.json.")
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--demo", action="store_true", help="Use built-in demo articles instead of live providers.")
    parser.add_argument("--audit-run-id", help="Link this source batch to a scheduler audit run.")
    args = parser.parse_args()

    if not args.symbol and not args.all:
        parser.error("Provide --symbol SYMBOL or --all")

    symbols = all_symbols() if args.all else [args.symbol.upper()]
    for symbol in symbols:
        print(f"Sourcing news for {symbol}...")
        batch = run_for_symbol(symbol, args.lookback_days, args.demo, args.audit_run_id)
        out_path = DATA_DIR / "news_batches" / symbol / f"{batch.batch_id}.json"
        save_json(out_path, batch.to_dict())
        print(f"  {len(batch.articles)} articles -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
