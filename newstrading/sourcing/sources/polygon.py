"""Polygon market-news source (migrated from legacy google_news_pipeline.py)."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence
from urllib import parse

from newstrading.sourcing.base import NewsSource
from newstrading.sourcing.http_utils import safe_json_get


class PolygonNewsSource(NewsSource):
    name = "polygon"
    default_weight = 0.8
    required_env_var = "POLYGON_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("POLYGON_API_KEY")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fetch(self, symbol: str, aliases: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []
        url = (
            "https://api.polygon.io/v2/reference/news"
            f"?limit=20&order=desc&sort=published_utc&ticker={parse.quote(symbol)}&apiKey={self.api_key}"
        )
        payload = safe_json_get(url)
        results = payload.get("results", []) if isinstance(payload, dict) else []

        articles: List[Dict[str, Any]] = []
        for item in results:
            title = (item.get("title") or "").strip()
            summary = (item.get("description") or item.get("summary") or title or "").strip()
            if not title and not summary:
                continue
            articles.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": item.get("url") or "",
                    "published_at": item.get("published_utc") or item.get("publishedAt"),
                    "author": item.get("author") or "",
                    "content": "",
                }
            )
        return articles
