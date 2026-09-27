"""Alpha Vantage News & Sentiment API source (added to replace the blocked WSJ scraper)."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from urllib import parse

from newstrading.sourcing.base import NewsSource
from newstrading.sourcing.http_utils import safe_json_get


class AlphaVantageNewsSource(NewsSource):
    name = "alpha_vantage"
    default_weight = 0.75
    required_env_var = "ALPHAVANTAGE_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ALPHAVANTAGE_API_KEY")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fetch(self, symbol: str, aliases: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []
        url = (
            "https://www.alphavantage.co/query"
            f"?function=NEWS_SENTIMENT&tickers={parse.quote(symbol)}&apikey={self.api_key}"
        )
        payload = safe_json_get(url)
        feed = payload.get("feed", []) if isinstance(payload, dict) else []

        articles: List[Dict[str, Any]] = []
        for item in feed:
            title = (item.get("title") or "").strip()
            summary = (item.get("summary") or title or "").strip()
            if not title:
                continue
            articles.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": item.get("url") or "",
                    "published_at": _parse_av_timestamp(item.get("time_published")),
                    "author": item.get("source") or "",
                    "content": "",
                }
            )
        return articles


def _parse_av_timestamp(raw: Optional[str]) -> Optional[str]:
    # Alpha Vantage uses a compact "YYYYMMDDTHHMMSS" timestamp format.
    if not raw or len(raw) < 15:
        return None
    try:
        return datetime.strptime(raw, "%Y%m%dT%H%M%S").isoformat()
    except ValueError:
        return None
