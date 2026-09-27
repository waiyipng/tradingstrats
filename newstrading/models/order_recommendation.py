"""JSON schema for the Order Recommendation -> Execution contract (order_recommendation.json)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass
class AccountSnapshot:
    cash: float
    net_liquidation: float
    existing_position_qty: int = 0
    open_position_count: int = 0
    gross_position_value: float = 0.0


@dataclass
class OrderRecommendation:
    recommendation_id: str
    signal_id: str
    symbol: str
    timestamp: str
    action: str  # BUY | SELL | HOLD
    order_type: str
    qty: int
    limit_price: Optional[float]
    time_in_force: str
    stop_loss_pct: float
    take_profit_pct: float
    target_allocation_pct: float
    max_slippage_pct: float
    account_snapshot: AccountSnapshot

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "OrderRecommendation":
        data = dict(payload)
        data["account_snapshot"] = AccountSnapshot(**payload["account_snapshot"])
        return cls(**data)
