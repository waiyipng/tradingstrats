"""Benzinga News API source (added to replace the blocked WSJ scraper)."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence
from urllib import parse

from newstrading.sourcing.base import NewsSource
from newstrading.sourcing.http_utils import safe_json_get


class BenzingaNewsSource(NewsSource):
    name = "benzinga"
    default_weight = 0.85
    tier = "professional"
    required_env_var = "BENZINGA_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("BENZINGA_API_KEY")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fetch(self, symbol: str, aliases: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []
        query = parse.urlencode({"tickers": symbol, "pagesize": 50, "token": self.api_key})
        url = f"https://api.benzinga.com/api/v2/news?{query}"
        payload = safe_json_get(url, headers={"Accept": "application/json"})
        if not isinstance(payload, list):
            return []

        articles: List[Dict[str, Any]] = []
        for item in payload:
            title = (item.get("title") or "").strip()
            summary = (item.get("teaser") or title or "").strip()
            if not title:
                continue
            articles.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": item.get("url") or "",
                    "published_at": item.get("created"),
                    "author": item.get("author") or "",
                    "content": "",
                }
            )
        return articles
