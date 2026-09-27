"""Combines per-article scores and market context into a single trading signal.

Deliberately stops at decision/confidence - sizing and order details belong to
the order_recommendation module, not here.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from math import exp
from typing import Any, Dict, List

from newstrading.common import new_id, utcnow_iso
from newstrading.models.news import NewsBatch
from newstrading.models.signal import MarketContext, TradingSignal


def aggregate_signal(
    batch: NewsBatch,
    scored_articles: List[Dict[str, Any]],
    market_context: MarketContext,
    as_of: datetime | None = None,
) -> TradingSignal:
    if not scored_articles:
        return TradingSignal(
            signal_id=new_id("sig"),
            batch_id=batch.batch_id,
            symbol=batch.symbol,
            timestamp=utcnow_iso(),
            decision="HOLD",
            confidence=0.0,
            sentiment_score=0.0,
            urgency="LOW",
            market_context=market_context,
            evidence={"article_count": 0, "source_count": 0},
        )

    source_counts = Counter(item.get("source", "unknown") for item in scored_articles)
    source_tiers = {item.get("source"): item.get("source_tier", "secondary") for item in scored_articles}
    weighted_total = 0.0
    sentiment_total = 0.0
    opinionated_total = 0.0
    positive_total = 0.0
    negative_total = 0.0
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    for item in scored_articles:
        recency = 1.0
        published_at = item.get("published_at")
        if published_at:
            try:
                published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                age_hours = max(0.0, (now - published).total_seconds() / 3600.0)
                recency = exp(-age_hours / 72.0)
            except ValueError:
                pass

        source = item.get("source", "unknown")
        article_weight = float(item.get("source_weight", 0.5)) * recency / source_counts[source]
        item["source_article_count"] = source_counts[source]
        item["recency_weight"] = recency
        item["normalized_weight"] = article_weight
        item["sentiment_contribution"] = float(item["sentiment_score"]) * article_weight
        weighted_total += article_weight
        sentiment_total += float(item["sentiment_score"]) * article_weight
        if item["sentiment"] == "positive":
            positive_total += article_weight
            opinionated_total += article_weight
        elif item["sentiment"] == "negative":
            negative_total += article_weight
            opinionated_total += article_weight

    avg_sentiment = sentiment_total / weighted_total if weighted_total else 0.0
    consensus = (positive_total - negative_total) / opinionated_total if opinionated_total else 0.0
    coverage = min(1.0, opinionated_total / 2.0)
    source_diversity = min(1.0, len(source_counts) / 3.0)
    opinionated_ratio = opinionated_total / weighted_total if weighted_total else 0.0

    technical_adjustment = 0.0
    if market_context.trend == "BULLISH":
        technical_adjustment += 0.15
    elif market_context.trend == "BEARISH":
        technical_adjustment -= 0.15

    combined_score = 0.7 * avg_sentiment + 0.3 * consensus + technical_adjustment
    if combined_score >= 0.10:
        decision = "BUY"
    elif combined_score <= -0.10:
        decision = "SELL"
    else:
        decision = "HOLD"

    qualified_sources = sorted(source for source, tier in source_tiers.items() if tier in {"primary", "professional"})
    secondary_sources = sorted(source for source, tier in source_tiers.items() if tier == "secondary")
    quality_gate_reason = None
    if decision == "BUY" and not qualified_sources and len(secondary_sources) < 2:
        decision = "HOLD"
        quality_gate_reason = "BUY requires a primary/professional source or two independent secondary sources"

    intensity = min(1.0, abs(avg_sentiment) / 0.35)
    agreement = abs(consensus)
    confidence = 0.45 * intensity + 0.35 * agreement + 0.20 * coverage
    if decision in {"BUY", "SELL"} and len(source_counts) < 2:
        confidence *= 0.75
    confidence *= 0.7 + 0.3 * source_diversity
    if (decision == "BUY" and market_context.trend == "BULLISH") or (decision == "SELL" and market_context.trend == "BEARISH"):
        confidence *= 1.10
    elif (decision == "BUY" and market_context.trend == "BEARISH") or (decision == "SELL" and market_context.trend == "BULLISH"):
        confidence *= 0.75
    confidence = min(0.95, max(0.0, confidence))
    urgency = "HIGH" if confidence >= 0.75 else "MEDIUM" if confidence >= 0.4 else "LOW"

    topic_counts = Counter(item["topic"] for item in scored_articles)
    catalysts = [topic for topic, _ in topic_counts.most_common(3)]
    supporting_articles = [item["id"] for item in scored_articles if item["sentiment"] != "neutral"][:5]

    return TradingSignal(
        signal_id=new_id("sig"),
        batch_id=batch.batch_id,
        symbol=batch.symbol,
        timestamp=utcnow_iso(),
        decision=decision,
        confidence=float(confidence),
        sentiment_score=float(avg_sentiment),
        urgency=urgency,
        catalysts=catalysts,
        market_context=market_context,
        supporting_articles=supporting_articles,
        evidence={
            "article_count": len(scored_articles),
            "source_count": len(source_counts),
            "sources": sorted(source_counts),
            "source_tiers": source_tiers,
            "qualified_sources": qualified_sources,
            "secondary_sources": secondary_sources,
            "quality_gate_reason": quality_gate_reason,
            "positive_weight": round(positive_total, 3),
            "negative_weight": round(negative_total, 3),
            "opinionated_ratio": round(opinionated_ratio, 3),
            "consensus": round(consensus, 3),
            "source_diversity": round(source_diversity, 3),
            "combined_score": round(combined_score, 6),
        },
    )
