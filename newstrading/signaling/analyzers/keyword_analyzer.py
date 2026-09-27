"""Keyword-based sentiment and topic scoring, parametrized by a sector keyword set."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Set


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9+\-]{3,}", (text or "").lower())


def match_keywords(text: str, keyword_set: Iterable[str]) -> int:
    return len(matched_keywords(text, keyword_set))


def matched_keywords(text: str, keyword_set: Iterable[str]) -> List[str]:
    text_l = text.lower()
    tokens = set(tokenize(text_l))
    matches: List[str] = []
    for keyword in keyword_set:
        if " " in keyword:
            if keyword in text_l:
                matches.append(keyword)
        elif keyword in tokens:
            matches.append(keyword)
    return sorted(matches)


def infer_topic(text: str, topic_keywords: Dict[str, Set[str]]) -> str:
    scores = {topic: match_keywords(text, keywords) for topic, keywords in topic_keywords.items()}
    if not any(scores.values()):
        return "general"
    return max(scores, key=scores.get)


def score_article(
    article: Dict[str, Any],
    positive_keywords: Iterable[str],
    negative_keywords: Iterable[str],
    topic_keywords: Dict[str, Set[str]],
) -> Dict[str, Any]:
    text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
    positive_matches = matched_keywords(text, positive_keywords)
    negative_matches = matched_keywords(text, negative_keywords)
    pos_hits = len(positive_matches)
    neg_hits = len(negative_matches)
    raw_score = (pos_hits - neg_hits) / max(1, pos_hits + neg_hits + 1)
    if raw_score > 0.05:
        sentiment = "positive"
    elif raw_score < -0.05:
        sentiment = "negative"
    else:
        sentiment = "neutral"
    weighted_score = raw_score * float(article.get("source_weight", 0.5))
    return {
        "id": article.get("id"),
        "source": article.get("source", "unknown"),
        "source_tier": article.get("source_tier", "secondary"),
        "source_weight": float(article.get("source_weight", 0.5)),
        "title": article.get("title", ""),
        "published_at": article.get("published_at"),
        "sentiment": sentiment,
        "positive_keyword_hits": pos_hits,
        "negative_keyword_hits": neg_hits,
        "positive_keyword_matches": positive_matches,
        "negative_keyword_matches": negative_matches,
        "sentiment_score": raw_score,
        "weighted_score": weighted_score,
        "topic": infer_topic(text, topic_keywords),
    }
