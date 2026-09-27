"""Marketaux entity-filtered financial news source."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence
from urllib import parse

from newstrading.config.loader import get_symbol_entry
from newstrading.sourcing.base import NewsSource
from newstrading.sourcing.http_utils import safe_json_get

NEWS_URL = "https://api.marketaux.com/v1/news/all"


class MarketauxNewsSource(NewsSource):
    name = "marketaux"
    tier = "secondary"
    default_weight = 0.7
    required_env_var = "MARKETAUX_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("MARKETAUX_API_KEY")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fetch(self, symbol: str, aliases: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []
        entry = get_symbol_entry(symbol)
        marketaux_symbol = entry.get("marketaux_symbol", symbol)
        published_after = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%dT%H:%M")
        query = parse.urlencode(
            {
                "api_token": self.api_key,
                "symbols": marketaux_symbol,
                "filter_entities": "true",
                "must_have_entities": "true",
                "language": "en",
                "published_after": published_after,
                "limit": 50,
            }
        )
        payload = safe_json_get(f"{NEWS_URL}?{query}", headers={"Accept": "application/json"})
        articles: List[Dict[str, Any]] = []
        for item in payload.get("data", []) if isinstance(payload, dict) else []:
            title = (item.get("title") or "").strip()
            summary = (item.get("description") or item.get("snippet") or title).strip()
            if not title:
                continue
            articles.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": item.get("url") or "",
                    "published_at": item.get("published_at"),
                    "author": item.get("source") or "Marketaux",
                    "content": "",
                }
            )
        return articles