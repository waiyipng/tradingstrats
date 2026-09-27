"""Finnhub company-news source (migrated from legacy google_news_pipeline.py)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence
from urllib import parse

from newstrading.sourcing.base import NewsSource
from newstrading.sourcing.http_utils import safe_json_get


class FinnhubNewsSource(NewsSource):
    name = "finnhub"
    default_weight = 0.8
    required_env_var = "FINNHUB_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("FINNHUB_API_KEY")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fetch(self, symbol: str, aliases: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []
        from_date = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        url = (
            "https://finnhub.io/api/v1/company-news"
            f"?symbol={parse.quote(symbol)}&from={from_date}&to={to_date}&token={self.api_key}"
        )
        payload = safe_json_get(url)
        if not isinstance(payload, list):
            return []

        articles: List[Dict[str, Any]] = []
        for item in payload:
            title = (item.get("headline") or item.get("summary") or "").strip()
            summary = (item.get("summary") or title or "").strip()
            if not title and not summary:
                continue
            published = item.get("datetime")
            published_at = datetime.utcfromtimestamp(int(published)).isoformat() if published else None
            articles.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": item.get("url") or "",
                    "published_at": published_at,
                    "author": item.get("source") or "",
                    "content": "",
                }
            )
        return articles
