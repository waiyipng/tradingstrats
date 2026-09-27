"""Deduplicates raw articles across sources by (source, title, url)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid"}


def _canonical_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", title.lower()).strip()


def _canonical_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query) if key not in _TRACKING_PARAMS])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def dedupe_articles(articles: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unique, _ = dedupe_with_audit(articles)
    return unique


def dedupe_with_audit(articles: Sequence[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    seen = {}
    unique: List[Dict[str, Any]] = []
    audit: List[Dict[str, Any]] = []
    ranked = sorted(articles, key=lambda item: float(item.get("source_weight", 0.0)), reverse=True)
    for article in ranked:
        key = (
            _canonical_title(article.get("title") or ""),
            _canonical_url(article.get("url") or ""),
        )
        if key in seen or not key[0]:
            audit.append({**article, "deduplication": "discarded_duplicate" if key[0] else "discarded_empty_title"})
            continue
        seen[key] = article
        unique.append(article)
        audit.append({**article, "deduplication": "retained"})
    return unique, audit
