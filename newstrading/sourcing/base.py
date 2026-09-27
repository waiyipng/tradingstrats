"""Common interface all news source adapters implement."""
from __future__ import annotations

from typing import Any, Dict, List, Sequence


class NewsSource:
    name: str = "base"
    default_weight: float = 0.5
    tier: str = "secondary"
    required_env_var: str | None = None

    def is_configured(self) -> bool:
        return self.required_env_var is None

    def fetch(self, symbol: str, aliases: Sequence[str], lookback_days: int = 7) -> List[Dict[str, Any]]:
        """Return raw article dicts with keys: title, summary, url, published_at, author, content."""
        raise NotImplementedError
