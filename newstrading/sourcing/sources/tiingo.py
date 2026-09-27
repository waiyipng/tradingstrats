"""Tiingo News API source (added to replace the blocked WSJ scraper)."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence
from urllib import parse

import requests

from newstrading.sourcing.base import NewsSource
from newstrading.sourcing.http_utils import safe_json_get


class TiingoNewsSource(NewsSource):
    name = "tiingo"
    default_weight = 0.8
    required_env_var = "TIINGO_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("TIINGO_API_KEY")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fetch(self, symbol: str, aliases: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []
        query = parse.urlencode({"tickers": symbol, "limit": 50, "token": self.api_key})
        url = f"https://api.tiingo.com/tiingo/news?{query}"
        try:
            payload = safe_json_get(url, headers={"Accept": "application/json"})
        except requests.HTTPError as exc:
            response = exc.response
            if response is not None and response.status_code in {401, 403}:
                raise RuntimeError("Tiingo News API entitlement is not enabled for this token") from exc
            raise
        if not isinstance(payload, list):
            return []

        articles: List[Dict[str, Any]] = []
        for item in payload:
            title = (item.get("title") or "").strip()
            summary = (item.get("description") or title or "").strip()
            if not title:
                continue
            articles.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": item.get("url") or "",
                    "published_at": item.get("publishedDate"),
                    "author": item.get("source") or "",
                    "content": "",
                }
            )
        return articles
