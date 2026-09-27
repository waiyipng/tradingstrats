"""Primary US filing events from the SEC EDGAR submissions API."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from typing import Any, Dict, List, Sequence

from newstrading.config.loader import get_symbol_entry
from newstrading.sourcing.base import NewsSource
from newstrading.sourcing.http_utils import safe_json_get

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
INCLUDED_FORMS = {"8-K", "10-Q", "10-K", "6-K", "20-F", "40-F", "4"}


class SecEdgarSource(NewsSource):
    name = "sec_edgar"
    tier = "primary"
    default_weight = 1.0
    required_env_var = "SEC_USER_AGENT"

    def __init__(self, user_agent: str | None = None):
        self.user_agent = user_agent or os.getenv("SEC_USER_AGENT")

    def is_configured(self) -> bool:
        return bool(self.user_agent)

    def fetch(self, symbol: str, aliases: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        entry = get_symbol_entry(symbol)
        cik = entry.get("sec_cik")
        if not cik:
            return []
        payload = safe_json_get(SEC_SUBMISSIONS_URL.format(cik=int(cik)), headers={"User-Agent": self.user_agent})
        recent = payload.get("filings", {}).get("recent", {})
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=lookback_days)
        articles: List[Dict[str, Any]] = []
        for form, filing_date, accession, document, report_date in zip(
            recent.get("form", []),
            recent.get("filingDate", []),
            recent.get("accessionNumber", []),
            recent.get("primaryDocument", []),
            recent.get("reportDate", []),
        ):
            if form not in INCLUDED_FORMS:
                continue
            filed = datetime.fromisoformat(filing_date).date()
            if filed < cutoff:
                continue
            accession_compact = accession.replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_compact}/{document}"
            articles.append(
                {
                    "title": f"{entry['name']} filed SEC Form {form}",
                    "summary": f"Official SEC filing: Form {form}, filed {filing_date}" + (f", report date {report_date}" if report_date else ""),
                    "url": url,
                    "published_at": f"{filing_date}T00:00:00+00:00",
                    "author": "U.S. Securities and Exchange Commission",
                    "content": "",
                }
            )
        return articles