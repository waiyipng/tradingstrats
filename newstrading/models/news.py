"""JSON schema for the Sourcing -> Signaling contract (news_batch.json)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class NewsArticle:
    id: str
    source: str
    source_weight: float
    title: str
    summary: str
    source_tier: str = "secondary"
    url: str = ""
    content: str = ""
    published_at: Optional[str] = None
    author: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NewsBatch:
    batch_id: str
    symbol: str
    generated_at: str
    articles: List[NewsArticle] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "symbol": self.symbol,
            "generated_at": self.generated_at,
            "article_count": len(self.articles),
            "articles": [a.to_dict() for a in self.articles],
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "NewsBatch":
        articles = [NewsArticle(**a) for a in payload.get("articles", [])]
        return cls(
            batch_id=payload["batch_id"],
            symbol=payload["symbol"],
            generated_at=payload["generated_at"],
            articles=articles,
        )
