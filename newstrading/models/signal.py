"""JSON schema for the Signaling -> Order Recommendation contract (trading_signal.json).

Deliberately excludes sizing/order fields - see models/order_recommendation.py for those.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MarketContext:
    current_price: Optional[float] = None
    sma_20: Optional[float] = None
    trend: str = "UNKNOWN"


@dataclass
class TradingSignal:
    signal_id: str
    batch_id: str
    symbol: str
    timestamp: str
    decision: str  # BUY | SELL | HOLD
    confidence: float
    sentiment_score: float
    urgency: str = "LOW"
    catalysts: List[str] = field(default_factory=list)
    market_context: MarketContext = field(default_factory=MarketContext)
    supporting_articles: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TradingSignal":
        market_context = MarketContext(**payload.get("market_context", {}))
        return cls(
            signal_id=payload["signal_id"],
            batch_id=payload["batch_id"],
            symbol=payload["symbol"],
            timestamp=payload["timestamp"],
            decision=payload["decision"],
            confidence=payload["confidence"],
            sentiment_score=payload["sentiment_score"],
            urgency=payload.get("urgency", "LOW"),
            catalysts=payload.get("catalysts", []),
            market_context=market_context,
            supporting_articles=payload.get("supporting_articles", []),
            evidence=payload.get("evidence", {}),
        )
