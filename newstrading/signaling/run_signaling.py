"""CLI entry point for the Signaling module.

Reads a news_batch.json artifact, applies sector-specific keyword scoring plus
optional price/trend context, and writes a trading_signal.json artifact
containing decision/confidence/sentiment ONLY - no order-sizing fields.

Usage:
    python -m newstrading.signaling.run_signaling --symbol AAPL
    python -m newstrading.signaling.run_signaling --batch-file path/to/news_batch.json
"""
from __future__ import annotations

import argparse
from typing import Any, Dict

from newstrading.audit import update_symbol
from newstrading.common import DATA_DIR, latest_artifact, load_json, save_json
from newstrading.config.loader import get_symbol_entry, market_data_symbol
from newstrading.models.news import NewsBatch
from newstrading.signaling.aggregator import aggregate_signal
from newstrading.signaling.analyzers.keyword_analyzer import score_article
from newstrading.signaling.analyzers.market_context import get_market_context
from newstrading.signaling.keyword_sets import financial as financial_keywords
from newstrading.signaling.keyword_sets import tech as tech_keywords

KEYWORD_SETS = {"tech": tech_keywords, "financial": financial_keywords}


def run_for_batch(batch: NewsBatch, audit_run_id: str | None = None) -> Dict[str, Any]:
    entry = get_symbol_entry(batch.symbol)
    keywords = KEYWORD_SETS[entry["sector"]]
    scored = [
        score_article(
            article.to_dict(),
            keywords.POSITIVE_KEYWORDS,
            keywords.NEGATIVE_KEYWORDS,
            keywords.TOPIC_KEYWORDS,
        )
        for article in batch.articles
    ]
    market_context = get_market_context(market_data_symbol(batch.symbol))
    signal = aggregate_signal(batch, scored, market_context)
    articles_by_id = {article.id: article.to_dict() for article in batch.articles}
    article_scores = []
    for item in scored:
        article = articles_by_id.get(item["id"], {})
        article_scores.append(
            {
                "article_id": item["id"],
                "title": article.get("title", item.get("title", "")),
                "summary": article.get("summary", ""),
                "url": article.get("url", ""),
                "source": item["source"],
                "source_tier": item.get("source_tier", "secondary"),
                "published_at": item.get("published_at"),
                "source_weight": item["source_weight"],
                "deduplication": "retained",
                "positive_keyword_hits": item.get("positive_keyword_hits", 0),
                "negative_keyword_hits": item.get("negative_keyword_hits", 0),
                "positive_keyword_matches": item.get("positive_keyword_matches", []),
                "negative_keyword_matches": item.get("negative_keyword_matches", []),
                "sentiment": item["sentiment"],
                "raw_sentiment_score": item["sentiment_score"],
                "topic": item["topic"],
                "recency_weight": item.get("recency_weight", 1.0),
                "source_article_count": item.get("source_article_count", 1),
                "normalized_weight": item.get("normalized_weight", 0.0),
                "sentiment_contribution": item.get("sentiment_contribution", 0.0),
            }
        )
    update_symbol(
        audit_run_id,
        batch.symbol,
        signaling={
            "signal": signal.to_dict(),
            "calculation": {
                "average_sentiment": signal.sentiment_score,
                "consensus": signal.evidence.get("consensus", 0.0),
                "technical_adjustment": 0.15 if market_context.trend == "BULLISH" else -0.15 if market_context.trend == "BEARISH" else 0.0,
                "combined_score": signal.evidence.get("combined_score", 0.0),
                "buy_threshold": 0.10,
                "sell_threshold": -0.10,
            },
            "article_scores": article_scores,
        },
    )
    return signal.to_dict()


def main() -> int:
    parser = argparse.ArgumentParser(description="Score a news_batch.json into a trading_signal.json.")
    parser.add_argument("--symbol", help="Use the latest news_batch.json for this symbol.")
    parser.add_argument("--batch-file", help="Path to a specific news_batch.json artifact.")
    parser.add_argument("--audit-run-id", help="Link this signal to a scheduler audit run.")
    args = parser.parse_args()

    if not args.symbol and not args.batch_file:
        parser.error("Provide --symbol SYMBOL or --batch-file PATH")

    batch_path = args.batch_file or str(latest_artifact("news_batches", args.symbol))
    batch = NewsBatch.from_dict(load_json(batch_path))
    signal_dict = run_for_batch(batch, args.audit_run_id)

    out_path = DATA_DIR / "signals" / batch.symbol / f"{signal_dict['signal_id']}.json"
    save_json(out_path, signal_dict)

    print(f"Signal for {batch.symbol}: {signal_dict['decision']} (confidence={signal_dict['confidence']:.0%})")
    print(f"  -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
